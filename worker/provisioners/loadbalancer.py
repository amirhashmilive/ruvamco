"""
RUVAMCO Worker — NLB / ALB load-balancer provisioner.

Creates and manages AWS Elastic Load Balancers (Network Load Balancer
for L4, Application Load Balancer for L7) as entry points for the
Envoy proxy fleet.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class LoadBalancerProvisioner:
    """Manages AWS ELBv2 load balancers for Envoy proxy fleets."""

    def __init__(self):
        self._elbv2 = boto3.client("elbv2")

    def create_nlb(
        self,
        instance_id: str,
        subnets: List[str],
        vpc_id: str,
        port: int = 443,
        tags: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create a Network Load Balancer with a target group and listener."""
        name = f"ruvamco-{instance_id[:24]}"
        logger.info("Creating NLB %s in subnets %s", name, subnets)

        tag_list = [{"Key": "ruvamco:instance", "Value": instance_id}]
        if tags:
            tag_list.extend({"Key": k, "Value": v} for k, v in tags.items())

        try:
            # Create LB
            lb_resp = self._elbv2.create_load_balancer(
                Name=name,
                Subnets=subnets,
                Type="network",
                Scheme="internet-facing",
                IpAddressType="dualstack",
                Tags=tag_list,
            )
            lb = lb_resp["LoadBalancers"][0]
            lb_arn = lb["LoadBalancerArn"]

            # Create target group
            tg_resp = self._elbv2.create_target_group(
                Name=f"ruvamco-tg-{instance_id[:20]}",
                Protocol="TCP",
                Port=port,
                VpcId=vpc_id,
                TargetType="instance",
                HealthCheckProtocol="HTTP",
                HealthCheckPath="/health",
                HealthCheckIntervalSeconds=10,
                HealthyThresholdCount=2,
                UnhealthyThresholdCount=2,
            )
            tg_arn = tg_resp["TargetGroups"][0]["TargetGroupArn"]

            # Create listener
            self._elbv2.create_listener(
                LoadBalancerArn=lb_arn,
                Protocol="TCP",
                Port=port,
                DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
            )

            result = {
                "lb_arn": lb_arn,
                "dns_name": lb["DNSName"],
                "target_group_arn": tg_arn,
                "status": "provisioning",
            }
            logger.info("NLB created: %s", result)
            return result

        except ClientError:
            logger.exception("NLB creation failed for instance %s", instance_id)
            raise

    def delete_nlb(self, lb_arn: str, tg_arn: Optional[str] = None) -> None:
        """Delete a load balancer and its target group."""
        logger.info("Deleting NLB %s", lb_arn)
        try:
            self._elbv2.delete_load_balancer(LoadBalancerArn=lb_arn)
            if tg_arn:
                self._elbv2.delete_target_group(TargetGroupArn=tg_arn)
            logger.info("NLB deleted: %s", lb_arn)
        except ClientError:
            logger.exception("NLB deletion failed: %s", lb_arn)
            raise

    def register_targets(self, tg_arn: str, instance_ids: List[str], port: int = 443) -> None:
        """Register EC2 instances with a target group."""
        targets = [{"Id": iid, "Port": port} for iid in instance_ids]
        self._elbv2.register_targets(TargetGroupArn=tg_arn, Targets=targets)
        logger.info("Registered %d targets with %s", len(targets), tg_arn)

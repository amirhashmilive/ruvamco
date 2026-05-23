"""
RUVAMCO Worker — Route 53 DNS provisioner.

Creates, updates, and deletes DNS records for edge-proxy instances
using AWS Route 53.  Supports A, CNAME, and ALIAS record types
with health-check association.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Default hosted-zone — overridden via env in production
DEFAULT_HOSTED_ZONE_ID = "Z0000000000000"


class DNSProvisioner:
    """Manages Route 53 DNS records for proxy instances."""

    def __init__(self, hosted_zone_id: str = DEFAULT_HOSTED_ZONE_ID):
        self.hosted_zone_id = hosted_zone_id
        self._r53 = boto3.client("route53")

    def create_record(
        self,
        domain: str,
        target: str,
        record_type: str = "CNAME",
        ttl: int = 60,
    ) -> Dict[str, Any]:
        """Create or upsert a DNS record."""
        logger.info("Creating DNS %s record: %s → %s", record_type, domain, target)

        change_batch = {
            "Comment": f"RUVAMCO auto-provision for {domain}",
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": domain,
                        "Type": record_type,
                        "TTL": ttl,
                        "ResourceRecords": [{"Value": target}],
                    },
                }
            ],
        }

        try:
            resp = self._r53.change_resource_record_sets(
                HostedZoneId=self.hosted_zone_id,
                ChangeBatch=change_batch,
            )
            change_id = resp["ChangeInfo"]["Id"]
            logger.info("DNS change submitted: %s (status=%s)", change_id, resp["ChangeInfo"]["Status"])
            return {"change_id": change_id, "status": resp["ChangeInfo"]["Status"]}
        except ClientError:
            logger.exception("DNS record creation failed for %s", domain)
            raise

    def delete_record(
        self,
        domain: str,
        record_type: str = "CNAME",
        target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a DNS record.  Looks up the current value if target not supplied."""
        logger.info("Deleting DNS record for %s", domain)

        if target is None:
            target = self._lookup_current_value(domain, record_type)
            if target is None:
                logger.warning("No existing DNS record found for %s; skipping delete", domain)
                return {"status": "not_found"}

        change_batch = {
            "Comment": f"RUVAMCO deprovision for {domain}",
            "Changes": [
                {
                    "Action": "DELETE",
                    "ResourceRecordSet": {
                        "Name": domain,
                        "Type": record_type,
                        "TTL": 60,
                        "ResourceRecords": [{"Value": target}],
                    },
                }
            ],
        }

        try:
            resp = self._r53.change_resource_record_sets(
                HostedZoneId=self.hosted_zone_id,
                ChangeBatch=change_batch,
            )
            return {"change_id": resp["ChangeInfo"]["Id"], "status": resp["ChangeInfo"]["Status"]}
        except ClientError:
            logger.exception("DNS record deletion failed for %s", domain)
            raise

    def _lookup_current_value(self, domain: str, record_type: str) -> Optional[str]:
        """Look up the current DNS record value for a given domain."""
        try:
            resp = self._r53.list_resource_record_sets(
                HostedZoneId=self.hosted_zone_id,
                StartRecordName=domain,
                StartRecordType=record_type,
                MaxItems="1",
            )
            for rrs in resp.get("ResourceRecordSets", []):
                if rrs["Name"].rstrip(".") == domain.rstrip(".") and rrs["Type"] == record_type:
                    return rrs["ResourceRecords"][0]["Value"]
        except ClientError:
            logger.exception("DNS lookup failed for %s", domain)
        return None

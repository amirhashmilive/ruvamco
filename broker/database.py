"""
RUVAMCO Broker — DynamoDB persistence layer.

Provides an async-friendly wrapper around boto3 DynamoDB operations
with automatic table creation, pagination, and structured error handling.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from .models import ServiceInstance, InstanceStatus

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages instance state in DynamoDB."""

    def __init__(self, table_name: str, region: str, endpoint_url: Optional[str] = None):
        self.table_name = table_name
        kwargs: Dict[str, Any] = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._dynamo = boto3.resource("dynamodb", **kwargs)
        self._client = boto3.client("dynamodb", **kwargs)
        self._table = self._dynamo.Table(table_name)

    # ── Bootstrap ────────────────────────────────────────────────

    async def ensure_table_exists(self) -> None:
        """Create the instances table if it does not exist (idempotent)."""
        try:
            self._client.describe_table(TableName=self.table_name)
            logger.info("DynamoDB table %s already exists", self.table_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("Creating DynamoDB table %s", self.table_name)
                self._client.create_table(
                    TableName=self.table_name,
                    KeySchema=[{"AttributeName": "instance_id", "KeyType": "HASH"}],
                    AttributeDefinitions=[
                        {"AttributeName": "instance_id", "AttributeType": "S"}
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                waiter = self._client.get_waiter("table_exists")
                waiter.wait(TableName=self.table_name)
                logger.info("DynamoDB table %s created", self.table_name)
            else:
                raise

    # ── CRUD ─────────────────────────────────────────────────────

    async def save_instance(self, instance: ServiceInstance) -> None:
        self._table.put_item(Item=instance.dict())
        logger.debug("Saved instance %s", instance.instance_id)

    async def get_instance(self, instance_id: str) -> Optional[ServiceInstance]:
        resp = self._table.get_item(Key={"instance_id": instance_id})
        item = resp.get("Item")
        if item is None:
            return None
        return ServiceInstance(**item)

    async def instance_exists(self, instance_id: str) -> bool:
        return (await self.get_instance(instance_id)) is not None

    async def update_status(
        self,
        instance_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        expr = "SET #s = :s, #u = :u"
        names = {"#s": "status", "#u": "updated_at"}
        values: Dict[str, Any] = {
            ":s": status,
            ":u": datetime.utcnow().isoformat(),
        }
        if error_message is not None:
            expr += ", error_message = :e"
            values[":e"] = error_message

        self._table.update_item(
            Key={"instance_id": instance_id},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        logger.info("Updated instance %s → %s", instance_id, status)

    async def delete_instance(self, instance_id: str) -> None:
        self._table.delete_item(Key={"instance_id": instance_id})
        logger.info("Deleted instance %s", instance_id)

    # ── Queries ──────────────────────────────────────────────────

    async def get_all_instances(self, status_filter: Optional[str] = None) -> List[Dict]:
        """Full table scan with optional status filter (acceptable at <10 k rows)."""
        kwargs: Dict[str, Any] = {}
        if status_filter:
            kwargs["FilterExpression"] = "#s = :s"
            kwargs["ExpressionAttributeNames"] = {"#s": "status"}
            kwargs["ExpressionAttributeValues"] = {":s": status_filter}

        items: List[Dict] = []
        response = self._table.scan(**kwargs)
        items.extend(response.get("Items", []))

        while "LastEvaluatedKey" in response:
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = self._table.scan(**kwargs)
            items.extend(response.get("Items", []))

        return items

    async def count_active_instances(self) -> int:
        items = await self.get_all_instances(status_filter=InstanceStatus.ACTIVE.value)
        return len(items)

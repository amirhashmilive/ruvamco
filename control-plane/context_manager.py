"""
RUVAMCO Control Plane — Context Manager.

Fetches, caches, and invalidates instance configuration contexts
stored in S3.  Serves as the single source of truth for the
template renderer and xDS server.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class ContextManager:
    """In-memory LRU cache backed by S3 for instance contexts."""

    def __init__(self, settings):
        self.bucket = settings.context_bucket
        self.ttl = settings.cache_ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ts: Dict[str, float] = {}

        kwargs: Dict[str, Any] = {}
        endpoint = os.environ.get("S3_ENDPOINT")
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        self._s3 = boto3.client("s3", **kwargs)

        self._dynamo = boto3.resource(
            "dynamodb",
            endpoint_url=os.environ.get("DYNAMODB_ENDPOINT"),
        )
        self._table = self._dynamo.Table(settings.dynamodb_table)

    async def initialize(self) -> None:
        """Warm the cache on startup."""
        logger.info("Warming context cache from S3 bucket %s", self.bucket)
        try:
            resp = self._s3.list_objects_v2(Bucket=self.bucket, Prefix="contexts/")
            for obj in resp.get("Contents", []):
                iid = obj["Key"].replace("contexts/", "").replace(".json", "")
                if iid:
                    await self.get_context(iid)
            logger.info("Cache warmed with %d entries", len(self.cache))
        except ClientError:
            logger.warning("Cache warming failed — S3 bucket may not exist yet")

    async def get_context(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Return cached context or fetch from S3."""
        now = time.time()
        if instance_id in self.cache:
            age = now - self._cache_ts.get(instance_id, 0)
            if age < self.ttl:
                return self.cache[instance_id]

        # Fetch from S3
        key = f"contexts/{instance_id}.json"
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
            ctx = json.loads(resp["Body"].read().decode())
            self.cache[instance_id] = ctx
            self._cache_ts[instance_id] = now
            return ctx
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise

    async def invalidate_cache(self, instance_id: str) -> None:
        """Remove an entry from the local cache."""
        self.cache.pop(instance_id, None)
        self._cache_ts.pop(instance_id, None)
        logger.debug("Cache invalidated for %s", instance_id)

    async def store_generated_config(self, instance_id: str, config: Dict) -> None:
        """Persist the generated Envoy config back to S3."""
        key = f"generated/{instance_id}.json"
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(config, default=str),
            ContentType="application/json",
        )
        logger.info("Generated config stored: s3://%s/%s", self.bucket, key)

    async def get_all_instances(self) -> List[Dict]:
        """Return all active instances from DynamoDB."""
        items: List[Dict] = []
        try:
            resp = self._table.scan(
                FilterExpression="#s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "active"},
            )
            items.extend(resp.get("Items", []))
            while "LastEvaluatedKey" in resp:
                resp = self._table.scan(
                    ExclusiveStartKey=resp["LastEvaluatedKey"],
                    FilterExpression="#s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "active"},
                )
                items.extend(resp.get("Items", []))
        except ClientError:
            logger.exception("Failed to scan instances")
        return items

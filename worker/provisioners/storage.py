"""
RUVAMCO Worker — S3 context storage provisioner.

Stores and retrieves JSON configuration contexts in S3 (or MinIO
in development).  These contexts are consumed by the control plane
to generate Envoy xDS snapshots.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class StorageProvisioner:
    """Manages instance configuration contexts in S3."""

    def __init__(
        self,
        bucket: str = "ruvamco-context",
        endpoint_url: Optional[str] = None,
    ):
        self.bucket = bucket
        kwargs: Dict[str, Any] = {}
        if endpoint_url or os.environ.get("S3_ENDPOINT"):
            kwargs["endpoint_url"] = endpoint_url or os.environ["S3_ENDPOINT"]
        self._s3 = boto3.client("s3", **kwargs)
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create the bucket if it does not exist (idempotent)."""
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            logger.info("Creating S3 bucket %s", self.bucket)
            try:
                self._s3.create_bucket(Bucket=self.bucket)
            except ClientError:
                logger.debug("Bucket %s may already exist (race)", self.bucket)

    def store_context(self, instance_id: str, context: Dict[str, Any]) -> None:
        """Write a JSON context to S3."""
        key = f"contexts/{instance_id}.json"
        body = json.dumps(context, default=str)
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
        logger.info("Context stored: s3://%s/%s (%d bytes)", self.bucket, key, len(body))

    def get_context(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a JSON context from S3."""
        key = f"contexts/{instance_id}.json"
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp["Body"].read().decode())
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                logger.warning("Context not found for %s", instance_id)
                return None
            raise

    def delete_context(self, instance_id: str) -> None:
        """Delete a context from S3."""
        key = f"contexts/{instance_id}.json"
        self._s3.delete_object(Bucket=self.bucket, Key=key)
        logger.info("Context deleted: s3://%s/%s", self.bucket, key)

    def list_contexts(self) -> list[str]:
        """Return all instance IDs with stored contexts."""
        resp = self._s3.list_objects_v2(Bucket=self.bucket, Prefix="contexts/")
        ids = []
        for obj in resp.get("Contents", []):
            name = obj["Key"].replace("contexts/", "").replace(".json", "")
            if name:
                ids.append(name)
        return ids

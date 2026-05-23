"""
RUVAMCO Broker — SQS queue manager.

Wraps boto3 SQS operations for sending provisioning tasks to the
async worker fleet.  Supports local ElasticMQ via endpoint override.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from .models import ProvisionTask

logger = logging.getLogger(__name__)


class QueueManager:
    """Sends and receives messages on the provisioning task queue."""

    def __init__(self, queue_url: str, region: str, endpoint_url: Optional[str] = None):
        self.queue_url = queue_url
        kwargs: Dict[str, Any] = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        self._sqs = boto3.client("sqs", **kwargs)

    async def send_message(self, task: ProvisionTask) -> str:
        """Enqueue a provisioning task.  Returns the SQS MessageId."""
        body = task.json()
        try:
            resp = self._sqs.send_message(
                QueueUrl=self.queue_url,
                MessageBody=body,
                MessageAttributes={
                    "operation": {
                        "DataType": "String",
                        "StringValue": task.operation,
                    },
                    "instance_id": {
                        "DataType": "String",
                        "StringValue": task.instance_id,
                    },
                },
                MessageGroupId=task.instance_id if self.queue_url.endswith(".fifo") else None,
            )
            msg_id = resp["MessageId"]
            logger.info(
                "Enqueued task %s (%s) for instance %s  → MessageId %s",
                task.task_id,
                task.operation,
                task.instance_id,
                msg_id,
            )
            return msg_id
        except ClientError:
            logger.exception("Failed to enqueue task %s", task.task_id)
            raise

    async def receive_messages(self, max_messages: int = 10, wait_seconds: int = 20):
        """Long-poll for messages (used by the worker, not the broker)."""
        resp = self._sqs.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=300,
            MessageAttributeNames=["All"],
        )
        return resp.get("Messages", [])

    async def delete_message(self, receipt_handle: str) -> None:
        self._sqs.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle,
        )

    async def get_queue_depth(self) -> int:
        """Return approximate number of messages in the queue."""
        resp = self._sqs.get_queue_attributes(
            QueueUrl=self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(resp["Attributes"].get("ApproximateNumberOfMessages", 0))

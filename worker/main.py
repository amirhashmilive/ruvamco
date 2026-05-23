"""
RUVAMCO - Async Provisioning Worker
Handles asynchronous resource provisioning tasks
"""

import json
import boto3
from typing import Dict, Any
import time
import logging
from datetime import datetime
import requests
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .provisioners.dns import DNSProvisioner
from .provisioners.cdn import CDNProvisioner
from .provisioners.storage import StorageProvisioner
from .provisioners.loadbalancer import LoadBalancerProvisioner

class ProvisioningWorker:
    """Main worker for processing provisioning tasks"""
    
    def __init__(self):
        self.sqs = boto3.client('sqs')
        self.dns_provisioner = DNSProvisioner()
        self.cdn_provisioner = CDNProvisioner()
        self.storage_provisioner = StorageProvisioner()
        self.lb_provisioner = LoadBalancerProvisioner()
        
        self.queue_url = "https://sqs.us-east-1.amazonaws.com/account/ruvamco-tasks"
        self.control_plane_url = "http://control-plane:8080"
        
    def run(self):
        """Main worker loop"""
        logger.info("Starting RUVAMCO provisioning worker")
        
        while True:
            try:
                response = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20,
                    VisibilityTimeout=300
                )
                
                messages = response.get('Messages', [])
                for message in messages:
                    self.process_message(message)
                    
                    self.sqs.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=message['ReceiptHandle']
                    )
                    
            except Exception as e:
                logger.error(f"Worker error: {e}")
                time.sleep(5)
    
    def process_message(self, message: Dict):
        """Process individual message"""
        body = json.loads(message['Body'])
        operation = body['operation']
        instance_id = body['instance_id']
        
        logger.info(f"Processing {operation} for {instance_id}")
        
        try:
            if operation == 'provision':
                self.provision(instance_id, body['parameters'])
            elif operation == 'deprovision':
                self.deprovision(instance_id)
            elif operation == 'update':
                self.update(instance_id, body['parameters'])
        except Exception as e:
            logger.error(f"Failed {operation} for {instance_id}: {e}")
            self.mark_failed(instance_id, str(e))
            raise
    
    def provision(self, instance_id: str, params: Dict[str, Any]):
        """Execute full provisioning workflow"""
        
        logger.info(f"Provisioning {instance_id} with params: {params}")
        
        # Step 1: Create DNS records
        dns_result = self.dns_provisioner.create_record(
            domain=params['domain'],
            target=f"{instance_id}.ruvamco.internal"
        )
        logger.info(f"DNS record created: {dns_result}")
        
        # Step 2: Configure CDN (for enterprise plans)
        if params.get('plan_id') == 'enterprise':
            cdn_result = self.cdn_provisioner.create_distribution(
                instance_id=instance_id,
                domain=params['domain'],
                origin=f"{instance_id}.ruvamco.internal"
            )
            logger.info(f"CDN distribution created: {cdn_result}")
        
        # Step 3: Store configuration context
        context = {
            'instance_id': instance_id,
            'domain': params['domain'],
            'backend': params['backend'],
            'rate_limit': params.get('rate_limit', {}),
            'auth': params.get('auth', {}),
            'timeouts': params.get('timeouts', {}),
            'plan': params.get('plan_id', 'developer'),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        self.storage_provisioner.store_context(instance_id, context)
        logger.info(f"Context stored for {instance_id}")
        
        # Step 4: Notify control plane to reload
        response = requests.post(
            f"{self.control_plane_url}/v1/reload",
            json={'instance_id': instance_id}
        )
        logger.info(f"Control plane notified: {response.status_code}")
        
        # Step 5: Mark as active
        self.mark_active(instance_id)
        logger.info(f"Successfully provisioned {instance_id}")
    
    def deprovision(self, instance_id: str):
        """Clean up resources"""
        logger.info(f"Deprovisioning {instance_id}")
        
        # Get instance context
        context = self.storage_provisioner.get_context(instance_id)
        
        # Delete DNS records
        if context and 'domain' in context:
            self.dns_provisioner.delete_record(context['domain'])
        
        # Delete CDN distribution
        if context and context.get('plan') == 'enterprise':
            self.cdn_provisioner.delete_distribution(instance_id)
        
        # Delete context storage
        self.storage_provisioner.delete_context(instance_id)
        
        # Mark as deleted
        self.mark_deleted(instance_id)
        
        logger.info(f"Successfully deprovisioned {instance_id}")
    
    def update(self, instance_id: str, params: Dict[str, Any]):
        """Update existing configuration"""
        logger.info(f"Updating {instance_id}")
        
        # Store updated context
        context = self.storage_provisioner.get_context(instance_id)
        context.update(params)
        context['updated_at'] = datetime.utcnow().isoformat()
        
        self.storage_provisioner.store_context(instance_id, context)
        
        # Notify control plane
        requests.post(
            f"{self.control_plane_url}/v1/reload",
            json={'instance_id': instance_id}
        )
        
        logger.info(f"Successfully updated {instance_id}")
    
    def mark_active(self, instance_id: str):
        """Mark instance as active in database"""
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('ruvamco-instances')
        
        table.update_item(
            Key={'instance_id': instance_id},
            UpdateExpression="SET #status = :status, #updated = :updated",
            ExpressionAttributeNames={"#status": "status", "#updated": "updated_at"},
            ExpressionAttributeValues={
                ":status": "active",
                ":updated": datetime.utcnow().isoformat()
            }
        )
    
    def mark_failed(self, instance_id: str, error: str):
        """Mark instance as failed"""
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('ruvamco-instances')
        
        table.update_item(
            Key={'instance_id': instance_id},
            UpdateExpression="SET #status = :status, error_message = :error",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "failed", ":error": error}
        )
    
    def mark_deleted(self, instance_id: str):
        """Mark instance as deleted"""
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table('ruvamco-instances')
        
        table.update_item(
            Key={'instance_id': instance_id},
            UpdateExpression="SET #status = :status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": "deleted"}
        )

if __name__ == "__main__":
    worker = ProvisioningWorker()
    worker.run()

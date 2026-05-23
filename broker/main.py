"""
RUVAMCO - Service Broker API
Open Service Broker compliant provisioning API
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, Literal
from enum import Enum
import uuid
import json
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
from contextlib import asynccontextmanager
import logging

from .models import ProvisionRequest, ServiceInstance, ProvisionTask
from .database import DatabaseManager
from .queue import QueueManager
from .auth import verify_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
class Settings(BaseModel):
    environment: str = "production"
    dynamodb_table: str = "ruvamco-instances"
    sqs_queue_url: str = "https://sqs.us-east-1.amazonaws.com/account/ruvamco-tasks"
    region: str = "us-east-1"
    
settings = Settings()

# Initialize managers
db = DatabaseManager(settings.dynamodb_table, settings.region)
queue = QueueManager(settings.sqs_queue_url, settings.region)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting RUVAMCO Broker API")
    await db.ensure_table_exists()
    yield
    logger.info("Shutting down RUVAMCO Broker API")

app = FastAPI(
    title="RUVAMCO Service Broker",
    version="1.0.0",
    description="Self-service edge proxy provisioning API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.get("/v2/catalog", response_model=Dict)
async def get_catalog(auth=Depends(verify_api_key)):
    """Return available services and plans"""
    return {
        "services": [{
            "id": "edge-proxy-service",
            "name": "RUVAMCO Edge Load Balancer",
            "description": "Self-service edge proxy with authentication, rate limiting, and observability",
            "bindable": True,
            "plans": [
                {
                    "id": "developer",
                    "name": "Developer",
                    "description": "Single region, 100 RPS, basic features"
                },
                {
                    "id": "business",
                    "name": "Business", 
                    "description": "Multi-region, 10,000 RPS, JWT auth, advanced routing"
                },
                {
                    "id": "enterprise",
                    "name": "Enterprise",
                    "description": "Global, 100k+ RPS, mTLS, WAF, dedicated instances"
                }
            ]
        }]
    }

@app.put("/v2/service_instances/{instance_id}", status_code=202)
async def provision(
    instance_id: str,
    request: ProvisionRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(verify_api_key)
):
    """Provision a new edge proxy instance"""
    
    logger.info(f"Provisioning request for instance: {instance_id}")
    
    # Validate instance doesn't exist
    if await db.instance_exists(instance_id):
        raise HTTPException(status_code=409, detail="Instance already exists")
    
    # Validate parameters against plan limits
    await validate_plan_limits(request.plan_id, request.parameters)
    
    # Create instance record
    instance = ServiceInstance(
        instance_id=instance_id,
        service_id=request.service_id,
        plan_id=request.plan_id,
        parameters=request.parameters.dict(),
        context=request.context,
        status="provisioning",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        operation=f"provision-{uuid.uuid4().hex[:8]}"
    )
    
    await db.save_instance(instance)
    
    # Queue provisioning task
    task = ProvisionTask(
        task_id=str(uuid.uuid4()),
        operation="provision",
        instance_id=instance_id,
        parameters=request.parameters.dict(),
        timestamp=datetime.utcnow()
    )
    
    background_tasks.add_task(queue.send_message, task)
    
    logger.info(f"Provisioning queued for instance: {instance_id}")
    
    return {
        "operation": instance.operation,
        "dashboard_url": f"https://ruvamco.internal/instances/{instance_id}"
    }

@app.get("/v2/service_instances/{instance_id}/last_operation")
async def get_last_operation(
    instance_id: str,
    operation: Optional[str] = None,
    auth=Depends(verify_api_key)
):
    """Poll operation status"""
    
    instance = await db.get_instance(instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    
    state_map = {
        "provisioning": "in progress",
        "active": "succeeded",
        "failed": "failed",
        "deprovisioning": "in progress",
        "deleted": "succeeded"
    }
    
    return {
        "state": state_map.get(instance.status, "in progress"),
        "description": f"Instance is {instance.status}",
        "last_operation": instance.operation
    }

@app.delete("/v2/service_instances/{instance_id}")
async def deprovision(
    instance_id: str,
    service_id: str,
    plan_id: str,
    background_tasks: BackgroundTasks,
    auth=Depends(verify_api_key)
):
    """Deprovision a service instance"""
    
    logger.info(f"Deprovisioning instance: {instance_id}")
    
    await db.update_status(instance_id, "deprovisioning")
    
    task = ProvisionTask(
        task_id=str(uuid.uuid4()),
        operation="deprovision",
        instance_id=instance_id,
        timestamp=datetime.utcnow()
    )
    
    background_tasks.add_task(queue.send_message, task)
    
    return {"operation": f"deprovision-{uuid.uuid4().hex[:8]}"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ruvamco-broker",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return {
        "provisioning_requests_total": 0,
        "provisioning_duration_seconds": 0,
        "active_instances": await db.count_active_instances()
    }

async def validate_plan_limits(plan_id: str, parameters: Dict):
    """Validate configuration against plan limits"""
    limits = {
        "developer": {"max_rps": 100, "max_regions": 1},
        "business": {"max_rps": 10000, "max_regions": 3},
        "enterprise": {"max_rps": 100000, "max_regions": 10}
    }
    
    limit = limits.get(plan_id, limits["developer"])
    
    if parameters.get("rate_limit", {}).get("requests_per_second", 0) > limit["max_rps"]:
        raise HTTPException(422, f"RPS exceeds {plan_id} plan limit of {limit['max_rps']}")

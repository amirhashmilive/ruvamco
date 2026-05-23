"""
RUVAMCO - Envoy Control Plane
Dynamic configuration management for Envoy proxies
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import json
import yaml
import asyncio
from datetime import datetime
import boto3
import grpc
from concurrent import futures
import logging

from .xds_server import AggregatedDiscoveryService
from .context_manager import ContextManager
from .template_renderer import TemplateRenderer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Settings(BaseModel):
    context_bucket: str = "ruvamco-context"
    template_bucket: str = "ruvamco-templates"
    dynamodb_table: str = "ruvamco-instances"
    xds_port: int = 18000
    http_port: int = 8080
    cache_ttl_seconds: int = 5

settings = Settings()

# Initialize components
context_manager = ContextManager(settings)
template_renderer = TemplateRenderer(settings)

app = FastAPI(
    title="RUVAMCO Control Plane",
    version="1.0.0",
    description="Dynamic Envoy configuration management"
)

@app.on_event("startup")
async def startup_event():
    """Initialize connections and caches"""
    logger.info("Starting RUVAMCO Control Plane")
    await context_manager.initialize()
    await template_renderer.initialize()
    
    # Start gRPC server for xDS
    asyncio.create_task(start_grpc_server())

async def start_grpc_server():
    """Start gRPC xDS server"""
    grpc_server = grpc.aio.server()
    ads_service = AggregatedDiscoveryService(context_manager, template_renderer)
    
    from .generated import envoy_service_discovery_pb2_grpc
    envoy_service_discovery_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(
        ads_service, grpc_server
    )
    
    grpc_server.add_insecure_port(f'[::]:{settings.xds_port}')
    await grpc_server.start()
    logger.info(f"gRPC xDS server started on port {settings.xds_port}")
    
    await grpc_server.wait_for_termination()

@app.get("/v1/status")
async def get_status():
    """Return control plane status"""
    instances = await context_manager.get_all_instances()
    return {
        "status": "healthy",
        "service": "ruvamco-control-plane",
        "instance_count": len(instances),
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }

class ReloadRequest(BaseModel):
    """Request body for reload endpoint"""
    instance_id: str


@app.post("/v1/reload")
async def trigger_reload(request: ReloadRequest):
    """Force configuration reload for instance"""
    instance_id = request.instance_id
    
    logger.info(f"Reload triggered for {instance_id}")
    
    # Clear cache
    await context_manager.invalidate_cache(instance_id)
    
    # Generate fresh configuration
    context = await context_manager.get_context(instance_id)
    config = await template_renderer.render_all(context)
    
    # Store generated config
    await context_manager.store_generated_config(instance_id, config)
    
    return {
        "status": "reload_triggered",
        "instance_id": instance_id,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/v1/instances/{instance_id}/config")
async def get_instance_config(instance_id: str):
    """Get rendered configuration for debugging"""
    
    context = await context_manager.get_context(instance_id)
    
    return {
        "listener": await template_renderer.render_listener(context),
        "cluster": await template_renderer.render_cluster(context),
        "route": await template_renderer.render_route(context)
    }

@app.get("/v1/instances")
async def list_instances():
    """List all active instances"""
    instances = await context_manager.get_all_instances()
    return {
        "instances": [
            {
                "id": inst.get('instance_id'),
                "domain": inst.get('domain'),
                "plan": inst.get('plan'),
                "status": inst.get('status', 'active')
            }
            for inst in instances
        ]
    }

@app.get("/health")
async def health():
    """Health check"""
    return {
        "status": "healthy",
        "service": "ruvamco-control-plane",
        "grpc_port": settings.xds_port,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/metrics")
async def metrics():
    """Prometheus metrics"""
    instances = await context_manager.get_all_instances()
    return {
        "active_instances": len(instances),
        "cache_size": len(context_manager.cache),
        "config_generations_total": template_renderer.generation_count
    }

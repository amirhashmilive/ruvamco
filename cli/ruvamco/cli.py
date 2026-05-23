#!/usr/bin/env python3
"""
RUVAMCO CLI - Command Line Interface for Edge Proxy Management
"""

import click
import yaml
import requests
import json
import time
import os
from typing import Dict, Any, List
from tabulate import tabulate
from datetime import datetime

API_ENDPOINT = os.environ.get('RUVAMCO_API', 'https://broker.ruvamco.internal/v2')
TOKEN_PATH = os.path.expanduser('~/.ruvamco/token')

class RuvamcoClient:
    """API client for RUVAMCO platform"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.get_token()}',
            'Content-Type': 'application/json'
        })
    
    def get_token(self):
        """Load authentication token"""
        if os.path.exists(TOKEN_PATH):
            with open(TOKEN_PATH, 'r') as f:
                return f.read().strip()
        return os.environ.get('RUVAMCO_TOKEN', '')
    
    def provision(self, instance_id: str, config: Dict) -> Dict:
        """Provision new instance"""
        response = self.session.put(
            f"{API_ENDPOINT}/service_instances/{instance_id}",
            json=config
        )
        response.raise_for_status()
        return response.json()
    
    def get_status(self, instance_id: str, operation: str = None) -> Dict:
        """Get operation status"""
        params = {'operation': operation} if operation else {}
        response = self.session.get(
            f"{API_ENDPOINT}/service_instances/{instance_id}/last_operation",
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    def delete(self, instance_id: str, service_id: str, plan_id: str) -> Dict:
        """Delete instance"""
        response = self.session.delete(
            f"{API_ENDPOINT}/service_instances/{instance_id}",
            params={'service_id': service_id, 'plan_id': plan_id}
        )
        response.raise_for_status()
        return response.json()
    
    def list_instances(self) -> List[Dict]:
        """List all instances"""
        response = self.session.get(f"{API_ENDPOINT}/instances")
        response.raise_for_status()
        return response.json().get('instances', [])

@click.group()
def cli():
    """RUVAMCO - Self-service edge proxy platform"""
    pass

@cli.command()
@click.argument('config_file', type=click.Path(exists=True))
@click.option('--wait', is_flag=True, help='Wait for provisioning to complete')
def apply(config_file, wait):
    """Apply configuration to provision a load balancer"""
    
    click.echo(f"📄 Loading configuration from {config_file}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Generate instance ID
    instance_id = f"{config['metadata']['namespace']}-{config['metadata']['name']}"
    
    # Build request
    request = {
        "service_id": "edge-proxy-service",
        "plan_id": config['spec'].get('plan', 'developer'),
        "context": {
            "platform": "kubernetes",
            "namespace": config['metadata']['namespace'],
            "service_name": config['metadata']['name']
        },
        "parameters": config['spec']
    }
    
    click.echo(f"🚀 Provisioning {instance_id}...")
    
    client = RuvamcoClient()
    result = client.provision(instance_id, request)
    
    operation = result['operation']
    click.echo(f"✅ Provisioning started: {operation}")
    
    if wait:
        click.echo("⏳ Waiting for completion...")
        
        while True:
            status = client.get_status(instance_id, operation)
            state = status['state']
            
            if state == 'succeeded':
                click.echo(f"✅ Service ready at https://{config['spec']['domain']}")
                click.echo(f"📊 Dashboard: {result['dashboard_url']}")
                break
            elif state == 'failed':
                click.echo(f"❌ Provisioning failed: {status['description']}")
                break
            
            click.echo("⏳ Still provisioning...")
            time.sleep(5)
    else:
        click.echo(f"🔍 Check status: ruvamco status {instance_id}")

@cli.command()
@click.argument('instance_id')
def status(instance_id):
    """Check status of an instance"""
    
    client = RuvamcoClient()
    
    try:
        status = client.get_status(instance_id)
        
        click.echo(f"\n📊 Instance: {instance_id}")
        click.echo(f"Status: {status['state']}")
        click.echo(f"Description: {status['description']}")
        
        if status.get('last_operation'):
            click.echo(f"Operation: {status['last_operation']}")
            
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            click.echo(f"❌ Instance {instance_id} not found")
        else:
            click.echo(f"❌ Error: {e}")

@cli.command()
def list():
    """List all provisioned instances"""
    
    client = RuvamcoClient()
    instances = client.list_instances()
    
    if not instances:
        click.echo("No instances found")
        return
    
    table = []
    for inst in instances:
        table.append([
            inst['id'],
            inst.get('domain', 'N/A'),
            inst.get('plan', 'N/A'),
            inst.get('status', 'unknown')
        ])
    
    click.echo("\n" + tabulate(
        table,
        headers=["Instance ID", "Domain", "Plan", "Status"],
        tablefmt="grid"
    ))

@cli.command()
@click.argument('instance_id')
@click.option('--force', is_flag=True, help='Force deletion without confirmation')
def delete(instance_id, force):
    """Delete a load balancer instance"""
    
    if not force:
        click.confirm(f"⚠️  Delete instance {instance_id}?", abort=True)
    
    click.echo(f"🗑️  Deleting {instance_id}...")
    
    client = RuvamcoClient()
    result = client.delete(instance_id, "edge-proxy-service", "developer")
    
    click.echo(f"✅ Deprovisioning started: {result['operation']}")

@cli.command()
@click.option('--tail', default=50, help='Number of lines to tail')
@click.option('--component', type=click.Choice(['broker', 'worker', 'control-plane', 'all']),
              default='all', help='Component to fetch logs for')
@click.option('--follow', '-f', is_flag=True, help='Follow log output')
def logs(tail, component, follow):
    """View platform logs"""

    click.echo(f"📋 Fetching last {tail} log entries...")

    # Try CloudWatch first (production)
    try:
        import boto3

        logs_client = boto3.client('logs')
        log_group = os.environ.get('RUVAMCO_LOG_GROUP', '/ruvamco/services')

        streams_to_query = []
        if component == 'all':
            streams_to_query = ['broker', 'worker', 'control-plane']
        else:
            streams_to_query = [component]

        for stream_name in streams_to_query:
            try:
                response = logs_client.get_log_events(
                    logGroupName=log_group,
                    logStreamName=stream_name,
                    limit=tail,
                    startFromHead=False,
                )
                events = response.get('events', [])
                if events:
                    click.echo(f"\n── {stream_name} ──")
                    for event in events:
                        ts = datetime.fromtimestamp(event['timestamp'] / 1000).strftime('%H:%M:%S')
                        click.echo(f"  {ts}  {event['message']}")
            except logs_client.exceptions.ResourceNotFoundException:
                continue

        return
    except Exception as e:
        if "RUVAMCO_DEBUG" in os.environ:
            click.echo(f"ℹ️  CloudWatch fallback triggered: {e}", err=True)
        pass  # Fall through to Docker

    # Fallback: docker-compose logs (local development)
    import subprocess

    docker_cmd = ['docker-compose', 'logs', f'--tail={tail}']
    if follow:
        docker_cmd.append('--follow')
    if component != 'all':
        docker_cmd.append(component)

    try:
        result = subprocess.run(docker_cmd, capture_output=not follow, text=True)
        if not follow and result.stdout:
            click.echo(result.stdout)
        if result.returncode != 0 and result.stderr:
            click.echo(f"⚠️  {result.stderr.strip()}")
    except FileNotFoundError:
        click.echo("⚠️  Neither CloudWatch nor Docker available.")
        click.echo("   Set RUVAMCO_LOG_GROUP for CloudWatch, or install Docker for local logs.")

@cli.command()
def version():
    """Display version information"""
    
    click.echo("RUVAMCO CLI v1.0.0")
    click.echo("Self-service edge proxy platform")
    click.echo("License: MIT")
    click.echo("Copyright (c) 2024 Ruvamco")

if __name__ == "__main__":
    cli()

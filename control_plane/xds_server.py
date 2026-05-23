"""
RUVAMCO Control Plane — xDS Aggregated Discovery Service (ADS).

Implements the Envoy ADS gRPC streaming protocol to push Listener,
Cluster, Route, and Endpoint configurations to the proxy fleet in
real time.  Each proxy connects via a persistent bidi stream and
receives incremental updates.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class AggregatedDiscoveryService:
    """
    gRPC ADS servicer stub.

    In production this inherits from the protobuf-generated servicer base
    class.  The implementation here defines the core logic for snapshot
    construction and version management.
    """

    def __init__(self, context_manager, template_renderer):
        self.context_manager = context_manager
        self.template_renderer = template_renderer
        self._version_map: Dict[str, str] = {}  # instance_id → version hash

    async def build_snapshot(self, instance_id: str) -> Dict[str, Any]:
        """Build a full xDS snapshot for a single instance."""
        context = await self.context_manager.get_context(instance_id)
        if context is None:
            logger.warning("No context for instance %s — empty snapshot", instance_id)
            return {}

        snapshot = {
            "listeners": [await self.template_renderer.render_listener(context)],
            "clusters": [await self.template_renderer.render_cluster(context)],
            "routes": [await self.template_renderer.render_route(context)],
        }

        # Compute content hash for versioning
        raw = json.dumps(snapshot, sort_keys=True, default=str)
        version = hashlib.sha256(raw.encode()).hexdigest()[:16]
        self._version_map[instance_id] = version

        logger.info("Snapshot built for %s — version %s", instance_id, version)
        return {"version": version, "resources": snapshot}

    def get_version(self, instance_id: str) -> str:
        return self._version_map.get(instance_id, "0")

    async def build_all_snapshots(self) -> Dict[str, Any]:
        """Build snapshots for every active instance."""
        instances = await self.context_manager.get_all_instances()
        snapshots = {}
        for inst in instances:
            iid = inst.get("instance_id")
            if iid:
                snapshots[iid] = await self.build_snapshot(iid)
        return snapshots

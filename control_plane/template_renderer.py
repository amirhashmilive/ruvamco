"""
RUVAMCO Control Plane — Jinja2 Template Renderer.

Renders Envoy Listener, Cluster, Route, and VirtualHost configurations
from Jinja2 templates using instance context data.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


class TemplateRenderer:
    """Renders Envoy xDS resources from Jinja2 templates."""

    def __init__(self, settings):
        self.settings = settings
        self.generation_count: int = 0
        self._env: Optional[Environment] = None

    async def initialize(self) -> None:
        """Load templates from disk."""
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATE_DIR),
            autoescape=select_autoescape(default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        templates = self._env.list_templates()
        logger.info("Template renderer initialized with %d templates: %s", len(templates), templates)

    def _render(self, template_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Render a single template and return parsed YAML/JSON."""
        import yaml

        if self._env is None:
            raise RuntimeError("TemplateRenderer not initialized — call initialize() first")

        tmpl = self._env.get_template(template_name)
        rendered = tmpl.render(**context)
        self.generation_count += 1
        return yaml.safe_load(rendered) or {}

    async def render_listener(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._render("listener.j2", context)

    async def render_cluster(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._render("cluster.j2", context)

    async def render_route(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._render("route.j2", context)

    async def render_virtualhost(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self._render("virtualhost.j2", context)

    async def render_all(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Render every resource type and return a combined dict."""
        return {
            "listener": await self.render_listener(context),
            "cluster": await self.render_cluster(context),
            "route": await self.render_route(context),
            "virtualhost": await self.render_virtualhost(context),
        }

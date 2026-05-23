"""
RUVAMCO — Control Plane Unit Tests

Tests for the xDS server, context manager, and template renderer.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestTemplateRenderer:
    """Tests for the Jinja2 template renderer."""

    @pytest.fixture
    def renderer(self):
        with patch("control_plane.template_renderer.os.path.dirname", return_value="."):
            from control_plane.template_renderer import TemplateRenderer
            settings = MagicMock()
            r = TemplateRenderer(settings)
            return r

    def test_generation_count_starts_at_zero(self, renderer):
        assert renderer.generation_count == 0

    def test_render_raises_before_init(self, renderer):
        with pytest.raises(RuntimeError, match="not initialized"):
            renderer._render("test.j2", {})


class TestXDSServer:
    """Tests for the ADS server."""

    @pytest.fixture
    def ads(self):
        from control_plane.xds_server import AggregatedDiscoveryService
        ctx_mgr = AsyncMock()
        tmpl_renderer = AsyncMock()
        return AggregatedDiscoveryService(ctx_mgr, tmpl_renderer)

    @pytest.mark.asyncio
    async def test_build_snapshot_returns_empty_for_missing_context(self, ads):
        ads.context_manager.get_context.return_value = None
        result = await ads.build_snapshot("nonexistent")
        assert result == {}

    @pytest.mark.asyncio
    async def test_build_snapshot_returns_versioned_resources(self, ads):
        ads.context_manager.get_context.return_value = {
            "instance_id": "test-001",
            "domain": "api.test.com",
        }
        ads.template_renderer.render_listener.return_value = {"name": "listener_test-001"}
        ads.template_renderer.render_cluster.return_value = {"name": "cluster_test-001"}
        ads.template_renderer.render_route.return_value = {"name": "route_test-001"}

        result = await ads.build_snapshot("test-001")
        assert "version" in result
        assert len(result["version"]) == 16  # SHA256 truncated to 16 chars
        assert "resources" in result
        assert len(result["resources"]["listeners"]) == 1

    def test_get_version_returns_zero_for_unknown(self, ads):
        assert ads.get_version("unknown") == "0"

    @pytest.mark.asyncio
    async def test_build_all_snapshots(self, ads):
        ads.context_manager.get_all_instances.return_value = [
            {"instance_id": "inst-1"},
            {"instance_id": "inst-2"},
        ]
        ads.context_manager.get_context.return_value = {"instance_id": "test", "domain": "t.com"}
        ads.template_renderer.render_listener.return_value = {}
        ads.template_renderer.render_cluster.return_value = {}
        ads.template_renderer.render_route.return_value = {}

        result = await ads.build_all_snapshots()
        assert len(result) == 2


class TestContextManager:
    """Tests for context caching."""

    @pytest.mark.asyncio
    async def test_invalidate_removes_from_cache(self):
        from control_plane.context_manager import ContextManager

        with patch("control_plane.context_manager.boto3"):
            settings = MagicMock()
            settings.context_bucket = "test-bucket"
            settings.cache_ttl_seconds = 5
            settings.dynamodb_table = "test-table"
            mgr = ContextManager(settings)

            mgr.cache["test-id"] = {"domain": "test.com"}
            mgr._cache_ts["test-id"] = 9999999999

            await mgr.invalidate_cache("test-id")
            assert "test-id" not in mgr.cache
            assert "test-id" not in mgr._cache_ts

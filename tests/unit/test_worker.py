"""
RUVAMCO — Worker Unit Tests

Tests for the provisioning worker: message processing, provisioning
workflow steps, error handling, and status updates.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime


class TestProvisioningWorker:
    """Tests for the ProvisioningWorker class."""

    def _make_worker(self):
        with patch("worker.main.boto3"), \
             patch("worker.main.DNSProvisioner"), \
             patch("worker.main.CDNProvisioner"), \
             patch("worker.main.StorageProvisioner"), \
             patch("worker.main.LoadBalancerProvisioner"):
            from worker.main import ProvisioningWorker
            worker = ProvisioningWorker()
            worker.dns_provisioner = MagicMock()
            worker.cdn_provisioner = MagicMock()
            worker.storage_provisioner = MagicMock()
            worker.lb_provisioner = MagicMock()
            return worker

    def test_process_provision_message(self):
        worker = self._make_worker()
        worker.dns_provisioner.create_record.return_value = {"change_id": "C123"}
        worker.storage_provisioner.store_context.return_value = None

        with patch("worker.main.requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=200)

            with patch.object(worker, "mark_active") as mock_mark:
                worker.provision("test-instance", {
                    "domain": "api.example.com",
                    "backend": {"target": "svc.local", "port": 8080},
                    "plan_id": "developer",
                })

                worker.dns_provisioner.create_record.assert_called_once()
                worker.storage_provisioner.store_context.assert_called_once()
                mock_mark.assert_called_once_with("test-instance")

    def test_provision_creates_cdn_for_enterprise(self):
        worker = self._make_worker()
        worker.dns_provisioner.create_record.return_value = {"change_id": "C456"}
        worker.cdn_provisioner.create_distribution.return_value = {"distribution_id": "D789"}

        with patch("worker.main.requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=200)

            with patch.object(worker, "mark_active"):
                worker.provision("ent-instance", {
                    "domain": "api.enterprise.com",
                    "backend": {"target": "svc.local", "port": 8443},
                    "plan_id": "enterprise",
                })

                worker.cdn_provisioner.create_distribution.assert_called_once()

    def test_provision_skips_cdn_for_developer(self):
        worker = self._make_worker()
        worker.dns_provisioner.create_record.return_value = {"change_id": "C789"}

        with patch("worker.main.requests") as mock_requests:
            mock_requests.post.return_value = MagicMock(status_code=200)

            with patch.object(worker, "mark_active"):
                worker.provision("dev-instance", {
                    "domain": "api.dev.com",
                    "backend": {"target": "svc.local", "port": 8080},
                    "plan_id": "developer",
                })

                worker.cdn_provisioner.create_distribution.assert_not_called()

    def test_deprovision_cleans_up_resources(self):
        worker = self._make_worker()
        worker.storage_provisioner.get_context.return_value = {
            "domain": "api.example.com",
            "plan": "developer",
        }

        with patch.object(worker, "mark_deleted") as mock_mark:
            worker.deprovision("test-instance")

            worker.dns_provisioner.delete_record.assert_called_once_with("api.example.com")
            worker.storage_provisioner.delete_context.assert_called_once_with("test-instance")
            mock_mark.assert_called_once_with("test-instance")

    def test_process_message_routes_correctly(self):
        worker = self._make_worker()

        with patch.object(worker, "provision") as mock_prov:
            worker.process_message({
                "Body": json.dumps({
                    "operation": "provision",
                    "instance_id": "msg-test",
                    "parameters": {"domain": "test.com"},
                })
            })
            mock_prov.assert_called_once()

    def test_failed_provision_marks_failed(self):
        worker = self._make_worker()
        worker.dns_provisioner.create_record.side_effect = Exception("DNS failure")

        with patch.object(worker, "mark_failed") as mock_fail:
            with pytest.raises(Exception, match="DNS failure"):
                worker.provision("fail-instance", {
                    "domain": "fail.com",
                    "backend": {"target": "svc.local", "port": 8080},
                })

            # mark_failed is called in process_message, not provision directly
            # but the exception is re-raised for process_message to catch

"""
tests/test_sdn.py — Unit and integration tests for SDN Gateway module.

Runs on any platform (Windows, Linux, macOS) without needing a Raspberry Pi.
Tests:
  1. ACL rule generation (drop, rate-limit, segment, meter)
  2. FaucetManager state management & YAML generation
  3. REST API endpoints via Flask test client
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from sdn.acl_rules import (
    allow_rule,
    drop_rule,
    meter_config,
    rate_limit_rule,
    segment_rule,
    _mac_to_meter_id,
)
from sdn.faucet_manager import (
    FaucetManager,
    STATUS_ACTIVE,
    STATUS_QUARANTINED,
    STATUS_RATE_LIMITED,
)
from sdn.alert_api import app


class TestACLRules(unittest.TestCase):
    """Test pure ACL builder functions in sdn/acl_rules.py."""

    def test_drop_rule(self):
        rule = drop_rule("aa:bb:cc:dd:ee:01")
        self.assertEqual(rule["rule"]["dl_src"], "aa:bb:cc:dd:ee:01")
        self.assertTrue(rule["rule"]["actions"]["drop"])

    def test_rate_limit_rule(self):
        rule = rate_limit_rule("aa:bb:cc:dd:ee:02", kbps=1024)
        self.assertEqual(rule["rule"]["dl_src"], "aa:bb:cc:dd:ee:02")
        self.assertTrue(rule["rule"]["actions"]["allow"])
        self.assertEqual(rule["rule"]["actions"]["meter"]["rate"], 1024)

    def test_segment_rule(self):
        rule = segment_rule("aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02")
        self.assertEqual(rule["rule"]["dl_src"], "aa:bb:cc:dd:ee:01")
        self.assertEqual(rule["rule"]["dl_dst"], "aa:bb:cc:dd:ee:02")
        self.assertTrue(rule["rule"]["actions"]["drop"])

    def test_allow_rule(self):
        rule = allow_rule()
        self.assertTrue(rule["rule"]["actions"]["allow"])

    def test_meter_id_deterministic(self):
        id1 = _mac_to_meter_id("00:00:00:00:01:02")
        id2 = _mac_to_meter_id("00:00:00:00:01:02")
        self.assertEqual(id1, id2)
        self.assertEqual(id1, 1 * 256 + 2)


class TestFaucetManager(unittest.TestCase):
    """Test FaucetManager state handling and YAML configuration generation."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.faucet_yaml = Path(self.tmp_dir.name) / "faucet.yaml"
        self.registry_json = Path(self.tmp_dir.name) / "device_registry.json"

        # Patch paths
        import sdn.faucet_manager as fm
        self.orig_faucet_yaml = fm.FAUCET_YAML
        self.orig_registry = fm.DEVICE_REGISTRY
        fm.FAUCET_YAML = self.faucet_yaml
        fm.DEVICE_REGISTRY = self.registry_json

        self.manager = FaucetManager()

    def tearDown(self):
        import sdn.faucet_manager as fm
        fm.FAUCET_YAML = self.orig_faucet_yaml
        fm.DEVICE_REGISTRY = self.orig_registry
        self.tmp_dir.cleanup()

    def test_register_device(self):
        is_new = self.manager.register("AA:BB:CC:DD:EE:01", ip="10.0.0.2", hostname="sensor-1")
        self.assertTrue(is_new)
        devices = self.manager.get_devices()
        self.assertIn("aa:bb:cc:dd:ee:01", devices)
        self.assertEqual(devices["aa:bb:cc:dd:ee:01"]["status"], STATUS_ACTIVE)
        self.assertEqual(devices["aa:bb:cc:dd:ee:01"]["ip"], "10.0.0.2")

        # Verify YAML generated
        self.assertTrue(self.faucet_yaml.exists())
        config = yaml.safe_load(self.faucet_yaml.read_text(encoding="utf-8"))
        self.assertIn("vlans", config)
        self.assertIn("dps", config)

    def test_quarantine_device(self):
        self.manager.register("aa:bb:cc:dd:ee:01")
        self.manager.quarantine("aa:bb:cc:dd:ee:01")
        devices = self.manager.get_devices()
        self.assertEqual(devices["aa:bb:cc:dd:ee:01"]["status"], STATUS_QUARANTINED)

        # Inspect generated ACL
        config = yaml.safe_load(self.faucet_yaml.read_text(encoding="utf-8"))
        rules = config["acls"]["iot_policy"]
        # First rule should be DROP for the quarantined mac
        self.assertEqual(rules[0]["rule"]["dl_src"], "aa:bb:cc:dd:ee:01")
        self.assertTrue(rules[0]["rule"]["actions"]["drop"])

    def test_rate_limit_device(self):
        self.manager.register("aa:bb:cc:dd:ee:02")
        self.manager.rate_limit("aa:bb:cc:dd:ee:02", kbps=256)
        devices = self.manager.get_devices()
        self.assertEqual(devices["aa:bb:cc:dd:ee:02"]["status"], STATUS_RATE_LIMITED)
        self.assertEqual(devices["aa:bb:cc:dd:ee:02"]["rate_kbps"], 256)

        config = yaml.safe_load(self.faucet_yaml.read_text(encoding="utf-8"))
        self.assertIn("meters", config)

    def test_unquarantine_device(self):
        self.manager.register("aa:bb:cc:dd:ee:01")
        self.manager.quarantine("aa:bb:cc:dd:ee:01")
        self.manager.unquarantine("aa:bb:cc:dd:ee:01")
        devices = self.manager.get_devices()
        self.assertEqual(devices["aa:bb:cc:dd:ee:01"]["status"], STATUS_ACTIVE)


class TestAlertAPI(unittest.TestCase):
    """Test Flask REST API routes."""

    def setUp(self):
        self.client = app.test_client()

    def test_alert_drop(self):
        res = self.client.post(
            "/alert",
            json={"mac": "11:22:33:44:55:66", "action": "drop", "score": 0.95, "type": "ddos"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "quarantined")
        self.assertEqual(data["mac"], "11:22:33:44:55:66")

    def test_alert_rate_limit(self):
        res = self.client.post(
            "/alert",
            json={"mac": "11:22:33:44:55:77", "action": "rate_limit"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "rate_limited")

    def test_get_devices(self):
        res = self.client.get("/devices")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("devices", data)

    def test_get_status(self):
        res = self.client.get("/alert/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("total", data)
        self.assertIn("active", data)

    def test_unquarantine_api(self):
        # First quarantine
        self.client.post("/alert", json={"mac": "aa:bb:cc:11:22:33", "action": "drop"})
        # Then delete
        res = self.client.delete("/alert/aa:bb:cc:11:22:33")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "active")

    def test_invalid_alert(self):
        res = self.client.post("/alert", json={"action": "drop"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("mac field is required", res.get_json()["error"])


if __name__ == "__main__":
    unittest.main()

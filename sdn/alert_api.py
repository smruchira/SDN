"""
sdn/alert_api.py — REST API for NIDS/HIDS to trigger SDN policies.

Endpoints:
  POST   /alert              Quarantine or rate-limit a device
  DELETE /alert/<mac>        Restore a device to active (unquarantine)
  GET    /alert/status       Faucet datapath status summary
  GET    /devices            List all discovered devices + current status

All request/response bodies are JSON.
See PROJECT.md → REST API Reference for full field documentation.

Run standalone (dev):
  python3 -m sdn.alert_api

Run in production:
  Managed by systemd sdn-api.service (see systemd/ directory)
"""

import logging
import threading

from flask import Flask, jsonify, request
from flask_cors import CORS

from .config import API_HOST, API_PORT
from .device_discovery import DeviceDiscovery
from .faucet_manager import FaucetManager

log = logging.getLogger(__name__)

# ── App and shared state ──────────────────────────────────────────────────
app     = Flask(__name__)
CORS(app)                   # Allow cross-origin requests from NIDS dashboards
manager = FaucetManager()   # Singleton shared with discovery daemon


# ── Routes ────────────────────────────────────────────────────────────────

@app.post("/alert")
def receive_alert():
    """
    Trigger a quarantine or rate-limit action on a device.

    Request body:
      { "mac": "aa:bb:cc:dd:ee:ff",
        "action": "drop" | "rate_limit",
        "score": 0.95,          ← optional, from NIDS
        "type": "flood"         ← optional, threat type label
      }

    Response 200:
      { "status": "quarantined" | "rate_limited", "mac": "..." }
    Response 400:
      { "error": "<reason>" }
    """
    body = request.get_json(silent=True)
    if not body:
        return _err("request body must be JSON", 400)

    mac    = body.get("mac", "").strip().lower()
    action = body.get("action", "drop").lower()

    if not mac:
        return _err("mac field is required", 400)

    log.warning("ALERT | mac=%s action=%s score=%s type=%s",
                mac, action, body.get("score"), body.get("type"))

    if action == "drop":
        manager.quarantine(mac)
        return jsonify({"status": "quarantined", "mac": mac})

    if action == "rate_limit":
        manager.rate_limit(mac)
        return jsonify({"status": "rate_limited", "mac": mac})

    return _err(f"unknown action '{action}'. Use 'drop' or 'rate_limit'", 400)


@app.delete("/alert/<path:mac>")
def unquarantine(mac: str):
    """
    Restore a quarantined/rate-limited device to normal active status.

    Response 200: { "status": "active", "mac": "..." }
    Response 404: { "error": "device not found" }
    """
    mac = mac.strip().lower()
    ok = manager.unquarantine(mac)
    if not ok:
        return _err("device not found", 404)
    log.info("UNQUARANTINE | mac=%s", mac)
    return jsonify({"status": "active", "mac": mac})


@app.get("/alert/status")
def get_status():
    """
    Quick health-check — returns a count of devices by status.

    Response 200:
      { "total": 5, "active": 3, "quarantined": 1, "rate_limited": 1 }
    """
    devices = manager.get_devices()
    counts = {"total": len(devices), "active": 0, "quarantined": 0, "rate_limited": 0}
    for info in devices.values():
        counts[info["status"]] = counts.get(info["status"], 0) + 1
    return jsonify(counts)


@app.get("/devices")
def list_devices():
    """
    List all discovered IoT devices and their current SDN status.

    Response 200:
      { "devices": { "<mac>": { "ip", "hostname", "status", "first_seen", "last_seen" } } }
    """
    return jsonify({"devices": manager.get_devices()})


# ── Helpers ───────────────────────────────────────────────────────────────

def _err(message: str, status: int):
    return jsonify({"error": message}), status


# ── Standalone entry-point ────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Start device discovery as a background daemon thread
    discovery = DeviceDiscovery(manager)
    t = threading.Thread(target=discovery.run, daemon=True, name="discovery")
    t.start()
    log.info("SDN Alert API starting on %s:%d", API_HOST, API_PORT)
    app.run(host=API_HOST, port=API_PORT)

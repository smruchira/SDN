#!/usr/bin/env python3
"""
REST alert endpoint for SecureMediNet Module 1.

POST /alert
  Body: {"mac": "00:00:00:00:00:02", "action": "drop"|"rate_limit", "score": 0.9, "type": "flood"}
  Response: 200 OK  {"status": "quarantined"|"rate_limited", "mac": "..."}
           400      {"error": "..."}
           500      {"error": "no datapath"}

Mounted on SecureSwitch via WSGIApplication (_CONTEXTS).
"""

import json
import logging

from ryu.app.wsgi import ControllerBase, Response, route

log = logging.getLogger(__name__)

INSTANCE_NAME = "secure_switch_app"


class AlertController(ControllerBase):
    def __init__(self, req, link, data, **cfg):
        super().__init__(req, link, data, **cfg)
        self.switch = data[INSTANCE_NAME]

    @route("alert", "/alert", methods=["POST"])
    def receive_alert(self, req, **kwargs):
        try:
            body = json.loads(req.body)
        except (ValueError, TypeError):
            return _json_response({"error": "invalid JSON"}, status=400)

        mac = body.get("mac", "").strip().lower()
        action = body.get("action", "drop").lower()

        if not mac:
            return _json_response({"error": "mac field required"}, status=400)

        log.warning(
            "ALERT received: mac=%s action=%s score=%s type=%s",
            mac, action, body.get("score"), body.get("type"),
        )

        if action == "drop":
            ok = self.switch.quarantine(mac)
            if not ok:
                return _json_response({"error": "no datapath connected"}, status=500)
            return _json_response({"status": "quarantined", "mac": mac})

        if action == "rate_limit":
            ok = self.switch.rate_limit(mac)
            if not ok:
                return _json_response({"error": "no datapath connected"}, status=500)
            return _json_response({"status": "rate_limited", "mac": mac})

        return _json_response({"error": f"unknown action: {action}"}, status=400)

    @route("alert_status", "/alert/status", methods=["GET"])
    def status(self, req, **kwargs):
        dps = list(getattr(self.switch, "datapaths", {}).keys())
        return _json_response({"datapaths": dps, "iomt_macs": list(self.switch.IOMT_MACS)})


def _json_response(data, status=200):
    body = json.dumps(data).encode()
    return Response(content_type="application/json", body=body, status=status)

#!/usr/bin/env python3
"""
Ryu SDN controller for SecureMediNet.

Extends SimpleSwitch13 with device-to-device blocking, a REST quarantine
endpoint, and OVS DROP/rate-limit rule injection on alert.

Run:
    ryu-manager gateway/module1_sdn/secure_switch.py \
                gateway/module1_sdn/quarantine_api.py
"""

import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ryu.app.simple_switch_13 import SimpleSwitch13
from ryu.app.wsgi import WSGIApplication
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib.packet import ethernet, packet
from ryu.ofproto import ofproto_v1_3

from gateway.module1_sdn.flow_rules import (
    build_drop_rule, build_rate_limit_rule,
    build_segment_rule, _install_meter_and_rule,
)

log = logging.getLogger(__name__)

DEVICE_PROFILES = Path(__file__).resolve().parents[2] / "config/device_profiles.json"
INSTANCE_NAME = "secure_switch_app"


class SecureSwitch(SimpleSwitch13):
    _CONTEXTS = {"wsgi": WSGIApplication}

    IOMT_MACS = set()

    def __init__(self, *args, **kwargs):
        self.wsgi = kwargs["wsgi"]
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self._load_device_macs()
        from gateway.module1_sdn.quarantine_api import AlertController
        self.wsgi.register(AlertController, {INSTANCE_NAME: self})
        log.info("SecureSwitch started. IoMT MACs: %s", self.IOMT_MACS)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        log.info("Datapath connected: dpid=%s", dp.id)
        super().switch_features_handler(ev)

    def _load_device_macs(self):
        if DEVICE_PROFILES.exists():
            try:
                profiles = json.loads(DEVICE_PROFILES.read_text())
                for device in profiles.values():
                    if "mac" in device:
                        self.IOMT_MACS.add(device["mac"].lower())
                log.info("Loaded %d MACs from %s", len(self.IOMT_MACS), DEVICE_PROFILES)
            except Exception as exc:
                log.warning("Could not load device profiles: %s", exc)
        else:
            self.IOMT_MACS = {
                "00:00:00:00:00:01",
                "00:00:00:00:00:02",
                "00:00:00:00:00:03",
                "00:00:00:00:00:04",
                "00:00:00:00:00:05",
            }
            log.info("device_profiles.json not found, using simulation MACs")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        src = eth.src.lower()
        dst = eth.dst.lower()

        if src in self.IOMT_MACS and dst in self.IOMT_MACS:
            log.warning("Device-to-device blocked: %s -> %s", src, dst)
            build_segment_rule(dp, src, dst)
            return

        SimpleSwitch13._packet_in_handler(self, ev)

    def quarantine(self, mac):
        mac = mac.lower()
        if not self.datapaths:
            log.error("No datapaths connected, cannot quarantine %s", mac)
            return False
        for dp in self.datapaths.values():
            build_drop_rule(dp, mac)
            log.warning("QUARANTINE: DROP rule for %s on dp %s", mac, dp.id)
        return True

    def rate_limit(self, mac):
        mac = mac.lower()
        if not self.datapaths:
            log.error("No datapaths connected, cannot rate_limit %s", mac)
            return False
        for dp in self.datapaths.values():
            try:
                _install_meter_and_rule(dp, mac)
                log.warning("RATE_LIMIT: meter rule for %s on dp %s", mac, dp.id)
            except Exception as exc:
                log.warning("Meter install failed (%s), falling back to drop rule", exc)
                build_rate_limit_rule(dp, mac)
        return True

"""
sdn/faucet_manager.py — Manages Faucet config (faucet.yaml) and device state.

FaucetManager is the single source of truth for:
  • Which IoT devices are registered
  • Which devices are quarantined, rate-limited, or active
  • The current Faucet YAML that enforces those policies

Calling any policy method (quarantine / rate_limit / unquarantine / register)
automatically rebuilds faucet.yaml and hot-reloads Faucet via SIGHUP.

State is persisted to device_registry.json so policies survive reboots.
"""

import json
import logging
import os
import signal
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional

import yaml

from .acl_rules import (
    allow_rule, drop_rule, meter_config,
    rate_limit_rule, segment_rule,
)
from .config import (
    DEVICE_REGISTRY, FAUCET_DP_ID, FAUCET_DP_NAME, FAUCET_YAML,
    HOTSPOT_IFACE, OVS_PORT_HOTSPOT, OVS_PORT_UPLINK, RATE_LIMIT_KBPS,
    UPLINK_IFACE,
)

log = logging.getLogger(__name__)


# ── Device status constants ────────────────────────────────────────────────
STATUS_ACTIVE       = "active"
STATUS_QUARANTINED  = "quarantined"
STATUS_RATE_LIMITED = "rate_limited"


class FaucetManager:
    """
    Manages IoT device policies and keeps faucet.yaml in sync.

    Thread-safe: all public methods acquire a lock before modifying state.

    ── Quick reference ───────────────────────────────────────────────────────
    manager.register(mac, ip, hostname)   → add device, apply isolation
    manager.quarantine(mac)               → DROP all traffic from device
    manager.rate_limit(mac)               → throttle device to RATE_LIMIT_KBPS
    manager.unquarantine(mac)             → restore device to active
    manager.get_devices()                 → dict of all known devices + status
    ─────────────────────────────────────────────────────────────────────────
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {mac: {ip, hostname, first_seen, last_seen, status}}
        self._devices: dict[str, dict] = {}
        self._load_registry()

    # ── Public policy API ──────────────────────────────────────────────────

    def register(self, mac: str, ip: str = "", hostname: str = "") -> bool:
        """
        Register a newly-discovered IoT device.
        Returns True if the device is new (triggers a Faucet reload),
        False if it was already known (only updates last_seen).
        """
        mac = _norm_mac(mac)
        with self._lock:
            if mac in self._devices:
                self._devices[mac]["last_seen"] = _now()
                if ip:
                    self._devices[mac]["ip"] = ip
                self._save_registry()
                return False

            self._devices[mac] = {
                "ip":         ip,
                "hostname":   hostname,
                "first_seen": _now(),
                "last_seen":  _now(),
                "status":     STATUS_ACTIVE,
            }
            log.info("New IoT device registered: mac=%s ip=%s host=%s", mac, ip, hostname)
            self._apply()
            return True

    def quarantine(self, mac: str) -> bool:
        """Block ALL traffic from mac. Creates a DROP rule in Faucet."""
        mac = _norm_mac(mac)
        with self._lock:
            if mac not in self._devices:
                self.register.__func__(self, mac)   # register without lock
            self._devices[mac]["status"] = STATUS_QUARANTINED
            log.warning("QUARANTINE applied: %s", mac)
            self._apply()
        return True

    def rate_limit(self, mac: str, kbps: int = RATE_LIMIT_KBPS) -> bool:
        """Throttle traffic from mac to kbps kb/s."""
        mac = _norm_mac(mac)
        with self._lock:
            if mac not in self._devices:
                self.register.__func__(self, mac)
            self._devices[mac]["status"] = STATUS_RATE_LIMITED
            self._devices[mac]["rate_kbps"] = kbps
            log.warning("RATE_LIMIT applied: %s @ %d kbps", mac, kbps)
            self._apply()
        return True

    def unquarantine(self, mac: str) -> bool:
        """Restore mac to normal active status (removes DROP/rate-limit rule)."""
        mac = _norm_mac(mac)
        with self._lock:
            if mac not in self._devices:
                return False
            self._devices[mac]["status"] = STATUS_ACTIVE
            self._devices[mac].pop("rate_kbps", None)
            log.info("UNQUARANTINE: %s restored to active", mac)
            self._apply()
        return True

    def get_devices(self) -> dict:
        """Return a snapshot of all devices and their current status."""
        with self._lock:
            return dict(self._devices)

    # ── Internal: config builder ───────────────────────────────────────────

    def _build_faucet_config(self) -> dict:
        """
        Assemble the complete faucet.yaml Python dict.

        Rule ordering inside iot_policy ACL (matters — first match wins):
          1. DROP rules   — quarantined devices (highest priority)
          2. Rate-limit   — throttled devices
          3. Isolation    — block IoT ↔ IoT direct traffic
          4. Allow-all    — default catch-all (lowest priority, always last)
        """
        acl_rules = []
        meters: dict = {}

        active_macs = [
            mac for mac, info in self._devices.items()
            if info["status"] == STATUS_ACTIVE
        ]

        # 1. Quarantine (DROP)
        for mac, info in self._devices.items():
            if info["status"] == STATUS_QUARANTINED:
                acl_rules.append(drop_rule(mac))

        # 2. Rate-limit
        for mac, info in self._devices.items():
            if info["status"] == STATUS_RATE_LIMITED:
                kbps = info.get("rate_kbps", RATE_LIMIT_KBPS)
                acl_rules.append(rate_limit_rule(mac, kbps))
                meters.update(meter_config(mac, kbps))

        # 3. Device-to-device isolation (all active IoT pairs)
        for src in active_macs:
            for dst in active_macs:
                if src != dst:
                    acl_rules.append(segment_rule(src, dst))

        # 4. Default allow (must be last)
        acl_rules.append(allow_rule())

        config: dict = {
            "vlans": {
                "iot": {"vid": 100, "description": "IoT device VLAN"},
            },
            "acls": {
                "iot_policy": acl_rules,
            },
            "dps": {
                FAUCET_DP_NAME: {
                    "dp_id": FAUCET_DP_ID,
                    "hardware": "Open vSwitch",
                    "interfaces": {
                        OVS_PORT_HOTSPOT: {
                            "name":        HOTSPOT_IFACE,
                            "description": "IoT Wi-Fi AP",
                            "native_vlan": "iot",
                            "acls_in":     ["iot_policy"],
                        },
                        OVS_PORT_UPLINK: {
                            "name":        UPLINK_IFACE,
                            "description": "Internet uplink",
                            "native_vlan": "iot",
                        },
                    },
                }
            },
        }

        if meters:
            config["meters"] = meters

        return config

    def _apply(self) -> None:
        """Rebuild faucet.yaml and hot-reload Faucet. Call while holding _lock."""
        FAUCET_YAML.parent.mkdir(parents=True, exist_ok=True)
        config = self._build_faucet_config()
        FAUCET_YAML.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=True),
            encoding="utf-8",
        )
        log.debug("faucet.yaml written: %s", FAUCET_YAML)
        self._save_registry()
        _reload_faucet()

    # ── Persistence ───────────────────────────────────────────────────────

    def _load_registry(self) -> None:
        if DEVICE_REGISTRY.exists():
            try:
                data = json.loads(DEVICE_REGISTRY.read_text(encoding="utf-8"))
                self._devices = data.get("devices", {})
                log.info("Loaded %d devices from registry", len(self._devices))
                # Rebuild faucet.yaml so policies are applied after reboot
                self._apply()
            except Exception as exc:
                log.warning("Could not load registry: %s", exc)

    def _save_registry(self) -> None:
        DEVICE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        DEVICE_REGISTRY.write_text(
            json.dumps({"devices": self._devices}, indent=2),
            encoding="utf-8",
        )


# ── Module-level helpers ───────────────────────────────────────────────────

def _norm_mac(mac: str) -> str:
    """Normalise MAC to lowercase colon-separated format."""
    return mac.strip().lower().replace("-", ":")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reload_faucet() -> None:
    """
    Send SIGHUP to the Faucet process so it hot-reloads faucet.yaml.
    Silently skips if Faucet is not running (safe for development on Windows).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "faucet"],
            capture_output=True, text=True, check=False,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            os.kill(int(pid), signal.SIGHUP)
        if pids:
            log.info("Faucet reloaded (SIGHUP → pids %s)", pids)
        else:
            log.debug("Faucet not running — config written but not reloaded")
    except Exception as exc:
        log.debug("SIGHUP skipped: %s", exc)

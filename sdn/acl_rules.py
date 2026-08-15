"""
sdn/acl_rules.py — Pure rule-builder functions for Faucet ACL YAML.

Each function returns a Python dict that maps directly to a Faucet ACL
entry list. No side effects — these are builders only.
FaucetManager calls these and assembles the final faucet.yaml.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO ADD A NEW RULE TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Write a function here that returns a list of Faucet rule dicts.
   Match fields: https://docs.faucet.nz/en/latest/configuration.html#acl-fields
2. Call it from FaucetManager._build_acl_rules() in faucet_manager.py.
3. Expose a public method on FaucetManager for the API to call.
4. Add the new endpoint to alert_api.py.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from .config import RATE_LIMIT_KBPS


# ── Rule builders ──────────────────────────────────────────────────────────

def drop_rule(mac: str) -> dict:
    """
    Block ALL traffic originating from mac (quarantine).
    Highest priority — placed first in the ACL list by FaucetManager.
    """
    return {
        "rule": {
            "dl_src": mac,
            "actions": {"drop": True},
        }
    }


def rate_limit_rule(mac: str, kbps: int = RATE_LIMIT_KBPS) -> dict:
    """
    Allow traffic from mac but throttle it to kbps kilobits/second.
    OVS meter ID is derived from the MAC so each device gets its own meter.
    """
    meter_id = _mac_to_meter_id(mac)
    return {
        "rule": {
            "dl_src": mac,
            "actions": {
                "meter": {"meter_id": meter_id, "rate": kbps},
                "allow": True,
            },
        }
    }


def segment_rule(src_mac: str, dst_mac: str) -> dict:
    """
    Block direct traffic from src_mac to dst_mac (device-to-device isolation).
    FaucetManager generates one rule per ordered pair of IoT device MACs.
    """
    return {
        "rule": {
            "dl_src": src_mac,
            "dl_dst": dst_mac,
            "actions": {"drop": True},
        }
    }


def allow_rule() -> dict:
    """
    Default catch-all rule — allow everything not matched above.
    FaucetManager always appends this last.
    """
    return {"rule": {"actions": {"allow": True}}}


# ── Meter config builder (for the top-level `meters:` section) ─────────────

def meter_config(mac: str, kbps: int = RATE_LIMIT_KBPS) -> dict:
    """
    Build a Faucet meter entry for mac.
    Returns {meter_id: <meter_config_dict>} to merge into faucet.yaml meters.
    """
    meter_id = _mac_to_meter_id(mac)
    return {
        meter_id: {
            "meter_id": meter_id,
            "entry": {
                "flags": "KBPS",
                "bands": [{"type": "DROP", "rate": kbps}],
            },
        }
    }


# ── Internal helpers ───────────────────────────────────────────────────────

def _mac_to_meter_id(mac: str) -> int:
    """
    Deterministically map a MAC to an integer meter ID.
    Uses the last two octets so IDs stay in a small range (1–65535).
    """
    parts = mac.replace("-", ":").split(":")
    return int(parts[-2], 16) * 256 + int(parts[-1], 16) or 1

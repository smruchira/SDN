"""
sdn/config.py — Central configuration for the Pi SDN Gateway.

ALL tuneable parameters live here. When adding new features, add constants
here instead of hardcoding them in individual modules.

Environment-variable overrides: set SDN_<PARAM_NAME> to override any value
at runtime without editing this file. Useful for deployment and testing.
"""

import os
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).resolve().parent.parent
CONFIG_DIR      = Path(os.getenv("SDN_CONFIG_DIR",  str(BASE_DIR / "config")))
FAUCET_YAML     = Path(os.getenv("SDN_FAUCET_YAML", str(CONFIG_DIR / "faucet.yaml")))
DEVICE_REGISTRY = Path(os.getenv("SDN_REGISTRY",    str(CONFIG_DIR / "device_registry.json")))

# ── Network interfaces ────────────────────────────────────────────────────
HOTSPOT_IFACE = os.getenv("SDN_HOTSPOT_IFACE", "wlan0")   # Wi-Fi AP interface
UPLINK_IFACE  = os.getenv("SDN_UPLINK_IFACE",  "eth0")    # Internet uplink
OVS_BRIDGE    = os.getenv("SDN_OVS_BRIDGE",    "br-sdn")  # OVS bridge name

# ── Hotspot ───────────────────────────────────────────────────────────────
HOTSPOT_SSID = os.getenv("SDN_SSID",     "IoT-Gateway")
HOTSPOT_PASS = os.getenv("SDN_PASSWORD", "iotgateway123")
GATEWAY_IP   = os.getenv("SDN_GW_IP",   "10.0.0.1")
DHCP_SUBNET  = os.getenv("SDN_SUBNET",  "10.0.0.0/24")

# ── Faucet controller ──────────────────────────────────────────────────────
FAUCET_PORT    = int(os.getenv("SDN_FAUCET_PORT", "6653"))
FAUCET_DP_ID   = int(os.getenv("SDN_DP_ID",       "1"))    # must match OVS datapath ID
FAUCET_DP_NAME = os.getenv("SDN_DP_NAME",          "pi-switch")

# Port numbers inside OVS bridge (must match `ovs-vsctl show` port order)
OVS_PORT_HOTSPOT = int(os.getenv("SDN_OVS_PORT_HOTSPOT", "1"))  # wlan0 port
OVS_PORT_UPLINK  = int(os.getenv("SDN_OVS_PORT_UPLINK",  "2"))  # eth0 port

# ── Security policies ─────────────────────────────────────────────────────
# Increase RATE_LIMIT_KBPS for less aggressive throttling.
RATE_LIMIT_KBPS = int(os.getenv("SDN_RATE_LIMIT_KBPS", "512"))

# ── REST API ──────────────────────────────────────────────────────────────
API_HOST = os.getenv("SDN_API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("SDN_API_PORT", "5000"))

# ── Device discovery ──────────────────────────────────────────────────────
# dnsmasq writes DHCP leases here; the discovery daemon reads this file.
DHCP_LEASES_FILE   = Path(os.getenv("SDN_LEASES_FILE", "/var/lib/misc/dnsmasq.leases"))
DISCOVERY_INTERVAL = int(os.getenv("SDN_DISCOVERY_INTERVAL", "5"))  # seconds

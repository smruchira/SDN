# SDN Gateway — Project Reference

> **This is the single source of truth for the project.**
> Any AI or developer working on this codebase MUST read this file first and
> MUST keep it up to date when making changes. See `.agents/AGENTS.md` for the
> enforcement rule.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Module Reference](#3-module-reference)
4. [REST API Reference](#4-rest-api-reference)
5. [Configuration Reference](#5-configuration-reference)
6. [Data Flow](#6-data-flow)
7. [How to Add New Features](#7-how-to-add-new-features)
8. [Deployment on Raspberry Pi 4](#8-deployment-on-raspberry-pi-4)
9. [Integration with NIDS / HIDS](#9-integration-with-nids--hids)
10. [Known Limitations & Future Work](#10-known-limitations--future-work)
11. [Glossary](#11-glossary)

---

## 1. Project Overview

**Goal:** Convert a Raspberry Pi 4 into an SDN-controlled IoT gateway for
a hospital/medical IoT network (final year research project — SecureMediNet).

**What this module does (SDN layer):**

| Feature | Mechanism |
|---|---|
| Wi-Fi hotspot for IoT devices | `hostapd` on `wlan0` |
| Software switch (L2 forwarding) | Open vSwitch (`br-sdn`) |
| Flow-rule enforcement | Faucet SDN controller (OpenFlow 1.3) |
| Device auto-discovery | Polls dnsmasq DHCP leases |
| Quarantine (drop all traffic) | Faucet ACL `drop` rule |
| Rate-limiting (throttle) | Faucet ACL meter rule |
| Device-to-device isolation | Faucet ACL `segment` rule per IoT pair |
| NIDS / HIDS integration | REST API (`POST /alert`) |
| Persistent state | `config/device_registry.json` |

**Other modules in SecureMediNet (not in this repo):**
- NIDS — network intrusion detection, calls `POST /alert`
- HIDS — host-based intrusion detection
- Hospital network security module

---

## 2. Architecture

```
+----------------------------------------------------------+
|                  Raspberry Pi 4                          |
|                                                          |
|   IoT Device (Wi-Fi)                                     |
|        |                                                 |
|   [wlan0  <--  hostapd AP]                               |
|        |                                                 |
|   [OVS Bridge: br-sdn]  <---- Faucet (port 6653)        |
|        |                       ^ SIGHUP on config change |
|   [eth0 -> Internet / Hospital LAN]                      |
|                                                          |
|   Flask REST API (:5000)  <---- NIDS / HIDS alerts       |
|        |                                                 |
|   FaucetManager                                          |
|        +-- rewrites /etc/faucet/faucet.yaml              |
|        +-- sends SIGHUP -> Faucet hot-reloads            |
|                                                          |
|   DeviceDiscovery (background thread)                    |
|        +-- polls /var/lib/misc/dnsmasq.leases            |
+----------------------------------------------------------+
```

**Technology stack:**

| Component | Technology | Why |
|---|---|---|
| SDN controller | Faucet | Actively maintained, Python 3.10+, OpenFlow 1.3, easy install |
| Software switch | Open vSwitch | Mature, supports OpenFlow 1.3, works with Faucet |
| Wi-Fi AP | hostapd | Standard Linux AP daemon |
| DHCP | dnsmasq | Lightweight, writes lease files for discovery |
| REST API | Flask + flask-cors | Simple, no boilerplate |
| State | JSON file | Survives reboots, human-readable |

---

## 3. Module Reference

### `sdn/config.py`
**Purpose:** Central configuration — all tuneable constants.
Every parameter can be overridden with an environment variable prefixed `SDN_`.
This is the first file to check when changing any setting.
No functions — just module-level constants.

---

### `sdn/acl_rules.py`
**Purpose:** Pure functions that build Faucet ACL rule dicts.
No state, no side effects. Easy to test independently.
`FaucetManager` calls these; they just return Python dicts.

| Function | Returns |
|---|---|
| `drop_rule(mac)` | ACL rule that drops all traffic from `mac` |
| `rate_limit_rule(mac, kbps)` | ACL rule that meters traffic from `mac` |
| `segment_rule(src, dst)` | ACL rule that blocks `src -> dst` |
| `allow_rule()` | Default catch-all allow rule |
| `meter_config(mac, kbps)` | Faucet meter entry for rate limiting |

---

### `sdn/faucet_manager.py`
**Purpose:** Single source of truth for device state and Faucet config.
`FaucetManager` is a thread-safe singleton that:
1. Maintains device registry (`_devices` dict, persisted to JSON)
2. Rebuilds `faucet.yaml` whenever state changes (`_build_faucet_config()`)
3. Sends `SIGHUP` to Faucet so it hot-reloads without downtime

**Key methods:**

| Method | What it does |
|---|---|
| `register(mac, ip, hostname)` | Add device, rebuild config, apply isolation |
| `quarantine(mac)` | Set status=quarantined -> DROP rule in Faucet |
| `rate_limit(mac, kbps)` | Set status=rate_limited -> meter rule in Faucet |
| `unquarantine(mac)` | Set status=active -> remove enforcement rule |
| `get_devices()` | Thread-safe snapshot of all devices |

**ACL rule ordering** (matters — Faucet uses first-match):
1. DROP rules (quarantined MACs)
2. Rate-limit rules (throttled MACs)
3. Segment rules (IoT<->IoT isolation, one per pair)
4. Default allow (always last)

---

### `sdn/device_discovery.py`
**Purpose:** Auto-registers new IoT devices that join the hotspot.
Polls `/var/lib/misc/dnsmasq.leases` every `DISCOVERY_INTERVAL` seconds.
When a new MAC is seen, calls `FaucetManager.register()`.

Can run as:
- A daemon thread inside `alert_api.py` (default)
- A standalone process (managed by systemd)

---

### `sdn/alert_api.py`
**Purpose:** Flask REST API — the integration point for NIDS/HIDS.
Starts `DeviceDiscovery` as a background daemon thread.
All routes share the same `FaucetManager` instance.

---

## 4. REST API Reference

**Base URL:** `http://10.0.0.1:5000`

### `POST /alert` — Apply a security action

**Request:**
```json
{
  "mac":    "aa:bb:cc:dd:ee:ff",
  "action": "drop",
  "score":  0.95,
  "type":   "flood"
}
```

| Field | Type | Required | Values |
|---|---|---|---|
| `mac` | string | YES | any MAC (normalised to lowercase) |
| `action` | string | YES | `"drop"` or `"rate_limit"` |
| `score` | float | NO | threat score from NIDS (logged only) |
| `type` | string | NO | threat label from NIDS (logged only) |

**Response 200:**
```json
{ "status": "quarantined", "mac": "aa:bb:cc:dd:ee:ff" }
```

---

### `DELETE /alert/<mac>` — Unquarantine a device

**Response 200:** `{ "status": "active", "mac": "..." }`
**Response 404:** `{ "error": "device not found" }`

---

### `GET /alert/status` — Health check

**Response 200:**
```json
{ "total": 5, "active": 3, "quarantined": 1, "rate_limited": 1 }
```

---

### `GET /devices` — List all IoT devices

**Response 200:**
```json
{
  "devices": {
    "aa:bb:cc:dd:ee:ff": {
      "ip":         "10.0.0.12",
      "hostname":   "sensor-01",
      "status":     "active",
      "first_seen": "2024-01-01T00:00:00+00:00",
      "last_seen":  "2024-01-01T01:00:00+00:00"
    }
  }
}
```

---

## 5. Configuration Reference

All parameters are in `sdn/config.py`. Override with `SDN_*` env vars.

| Constant | Default | Override env var | Description |
|---|---|---|---|
| `FAUCET_YAML` | `config/faucet.yaml` | `SDN_FAUCET_YAML` | Path Faucet reads/writes |
| `DEVICE_REGISTRY` | `config/device_registry.json` | `SDN_REGISTRY` | Persistent device state |
| `HOTSPOT_IFACE` | `wlan0` | `SDN_HOTSPOT_IFACE` | Wi-Fi AP interface |
| `UPLINK_IFACE` | `eth0` | `SDN_UPLINK_IFACE` | Internet uplink |
| `OVS_BRIDGE` | `br-sdn` | `SDN_OVS_BRIDGE` | OVS bridge name |
| `HOTSPOT_SSID` | `IoT-Gateway` | `SDN_SSID` | Wi-Fi SSID |
| `HOTSPOT_PASS` | `iotgateway123` | `SDN_PASSWORD` | Wi-Fi password |
| `GATEWAY_IP` | `10.0.0.1` | `SDN_GW_IP` | Pi IP on the IoT LAN |
| `FAUCET_PORT` | `6653` | `SDN_FAUCET_PORT` | OpenFlow port |
| `FAUCET_DP_ID` | `1` | `SDN_DP_ID` | OVS datapath ID |
| `OVS_PORT_HOTSPOT` | `1` | `SDN_OVS_PORT_HOTSPOT` | OVS port number for wlan0 |
| `OVS_PORT_UPLINK` | `2` | `SDN_OVS_PORT_UPLINK` | OVS port number for eth0 |
| `RATE_LIMIT_KBPS` | `512` | `SDN_RATE_LIMIT_KBPS` | Default throttle bandwidth |
| `API_HOST` | `0.0.0.0` | `SDN_API_HOST` | Flask bind address |
| `API_PORT` | `5000` | `SDN_API_PORT` | Flask port |
| `DHCP_LEASES_FILE` | `/var/lib/misc/dnsmasq.leases` | `SDN_LEASES_FILE` | dnsmasq leases path |
| `DISCOVERY_INTERVAL` | `5` | `SDN_DISCOVERY_INTERVAL` | Poll interval (seconds) |

---

## 6. Data Flow

### Normal packet (IoT device -> Internet)
```
IoT Device -> wlan0 (hostapd 802.11) -> OVS br-sdn
   -> Faucet checks iot_policy ACL
   -> "allow" rule matches -> forward to eth0 -> Internet
```

### New device joins hotspot
```
Device associates with AP (hostapd)
   -> DHCP request -> dnsmasq assigns IP, writes lease
   -> DeviceDiscovery detects new lease (within DISCOVERY_INTERVAL seconds)
   -> FaucetManager.register(mac, ip, hostname)
   -> Rebuilds faucet.yaml: adds segment rules for isolation
   -> SIGHUP -> Faucet hot-reloads -> new rules active
```

### NIDS triggers quarantine
```
NIDS detects anomaly -> POST /alert {"mac": "...", "action": "drop"}
   -> FaucetManager.quarantine(mac)
   -> Rebuilds faucet.yaml: DROP rule added at top (highest priority)
   -> SIGHUP -> Faucet reloads -> device is immediately blocked
   -> Returns {"status": "quarantined"}
```

---

## 7. How to Add New Features

### Adding a new security action (e.g., redirect to honeypot)

**Step 1** — Add a rule builder in `sdn/acl_rules.py`:
```python
def redirect_rule(mac: str, honeypot_port: int) -> dict:
    """Redirect all traffic from mac to a honeypot port."""
    return {
        "rule": {
            "dl_src": mac,
            "actions": {"output": {"port": honeypot_port}},
        }
    }
```

**Step 2** — Add a new status constant and method in `sdn/faucet_manager.py`:
```python
STATUS_REDIRECTED = "redirected"

def redirect_to_honeypot(self, mac: str, port: int) -> bool:
    mac = _norm_mac(mac)
    with self._lock:
        self._devices[mac]["status"] = STATUS_REDIRECTED
        self._devices[mac]["honeypot_port"] = port
        self._apply()
    return True
```

**Step 3** — Add rules in `_build_faucet_config()` (after rate-limit, before segment).

**Step 4** — Add an API endpoint in `sdn/alert_api.py`.

**Step 5** — Update PROJECT.md: add the new endpoint to the API Reference and document the new status value.

---

### Adding a new discovery source (e.g., passive ARP)

Create a class following the `DeviceDiscovery` pattern:
```python
class ARPDiscovery:
    def __init__(self, manager: FaucetManager) -> None: ...
    def run(self) -> None: ...   # blocking loop, call in a daemon thread
```

---

## 8. Deployment on Raspberry Pi 4

### One-command setup
```bash
git clone <your-repo> /tmp/sdn && cd /tmp/sdn
sudo bash scripts/setup_pi.sh
```

### Post-setup verification
```bash
systemctl status faucet sdn-api hostapd dnsmasq openvswitch-switch
sudo ovs-vsctl show
curl http://10.0.0.1:5000/alert/status
sudo journalctl -u sdn-api -f
```

### Useful debug commands
```bash
# See all OVS flow rules
sudo ovs-ofctl -O OpenFlow13 dump-flows br-sdn

# See current faucet config
cat /etc/faucet/faucet.yaml

# Test quarantine
curl -X POST http://10.0.0.1:5000/alert \
  -H "Content-Type: application/json" \
  -d '{"mac":"aa:bb:cc:dd:ee:ff","action":"drop","score":0.99,"type":"test"}'

# Remove quarantine
curl -X DELETE http://10.0.0.1:5000/alert/aa:bb:cc:dd:ee:ff
```

---

## 9. Integration with NIDS / HIDS

**Example NIDS call (Python):**
```python
import requests

def quarantine_device(mac: str, score: float, threat_type: str):
    resp = requests.post(
        "http://10.0.0.1:5000/alert",
        json={"mac": mac, "action": "drop", "score": score, "type": threat_type},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()
```

**Stable integration contract (do not change without versioning):**

| Endpoint | Stability |
|---|---|
| `POST /alert` with `action: drop/rate_limit` | STABLE |
| `DELETE /alert/<mac>` | STABLE |
| `GET /devices` response structure | STABLE |
| `GET /alert/status` | STABLE |

---

## 10. Known Limitations & Future Work

| # | Limitation | Suggested Fix |
|---|---|---|
| 1 | Rate-limit accuracy depends on OVS meter support | Test with `ovs-ofctl -O OpenFlow13 dump-meters br-sdn` |
| 2 | Device isolation rules grow as O(N^2) pairs | Implement VLAN-per-device isolation for >50 devices |
| 3 | faucet.yaml is rewritten from scratch on every change | Use incremental Faucet config diff |
| 4 | No TLS on REST API | Add Nginx reverse proxy with TLS for production |
| 5 | No authentication on `/alert` endpoint | Add API-key header check |

---

## 11. Glossary

| Term | Meaning |
|---|---|
| ACL | Access Control List — ordered match+action rules in Faucet |
| Datapath (dp) | The OVS switch instance Faucet controls |
| dp_id | Integer ID of OVS bridge (`ovs-vsctl get bridge br-sdn datapath_id`) |
| Faucet | SDN controller — manages flow rules via YAML config |
| Meter | OVS/OpenFlow rate-limiting mechanism |
| OVS | Open vSwitch — software L2 switch on the Pi |
| SIGHUP | Unix signal telling Faucet to reload config without restart |
| SDN | Software-Defined Networking — separates control (Faucet) from data plane (OVS) |
| Segment rule | ACL rule dropping packets between two IoT device MACs |

---

*Last updated: 2026-08-15 | Update this date whenever you edit this file.*

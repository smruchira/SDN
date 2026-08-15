# SDN Gateway — Quick Start

SDN-controlled IoT gateway on Raspberry Pi 4.
All IoT devices that connect to the Pi's Wi-Fi hotspot have their traffic
routed through Open vSwitch, controlled by Faucet.

**Full documentation → [PROJECT.md](./PROJECT.md)**

---

## Setup (Raspberry Pi 4)

```bash
git clone <your-repo> /tmp/sdn && cd /tmp/sdn
sudo bash scripts/setup_pi.sh
```

## Test the API

```bash
# Quarantine a device
curl -X POST http://10.0.0.1:5000/alert \
  -H "Content-Type: application/json" \
  -d '{"mac":"aa:bb:cc:dd:ee:ff","action":"drop"}'

# List all devices
curl http://10.0.0.1:5000/devices

# Restore a device
curl -X DELETE http://10.0.0.1:5000/alert/aa:bb:cc:dd:ee:ff
```

## Project structure

```
sdn/
  config.py          ← all settings (edit this first)
  acl_rules.py       ← Faucet ACL rule builders (pure functions)
  faucet_manager.py  ← device state + faucet.yaml management
  device_discovery.py← auto-discovers hotspot clients
  alert_api.py       ← Flask REST API for NIDS/HIDS
scripts/
  setup_pi.sh        ← full automated Pi setup
systemd/             ← service unit files
config/              ← faucet.yaml + device_registry.json (auto-managed)
PROJECT.md           ← full reference (read this before editing any code)
.agents/AGENTS.md    ← rules for AI assistants working on this project
```

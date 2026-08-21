# SDN Gateway — Quick Start

SDN-controlled IoT gateway on Raspberry Pi 4.  
All IoT devices that connect to the Pi's Wi-Fi hotspot have their traffic
routed through Open vSwitch, controlled by Faucet.

**Full documentation → [PROJECT.md](./PROJECT.md)**

---

## Setup (Raspberry Pi 4)

```bash
<<<<<<< HEAD
git clone https://github.com/smruchira/SDN.git /tmp/sdn && cd /tmp/sdn
=======
git clone https://github.com/smruchira/SDN/tmp/sdn && cd /tmp/sdn
>>>>>>> b0f111d85181e662dee3a74798bfa059d8f3c75d
sudo bash scripts/setup_pi.sh
```

## Test the API

The REST API runs at `http://10.0.0.1:5000`.

```bash
# Quarantine a device (drop all traffic)
curl -X POST http://10.0.0.1:5000/alert \
  -H "Content-Type: application/json" \
  -d '{"mac":"aa:bb:cc:dd:ee:ff","action":"drop"}'

# Rate-limit a device
curl -X POST http://10.0.0.1:5000/alert \
  -H "Content-Type: application/json" \
  -d '{"mac":"aa:bb:cc:dd:ee:ff","action":"rate_limit"}'

# List all discovered devices
curl http://10.0.0.1:5000/devices

# Check status counts (active / quarantined / rate-limited)
curl http://10.0.0.1:5000/alert/status

# Restore a device
curl -X DELETE http://10.0.0.1:5000/alert/aa:bb:cc:dd:ee:ff
```

## Project structure

```
sdn/
  config.py           ← all settings (edit this first)
  acl_rules.py        ← Faucet ACL rule builders (pure functions)
  faucet_manager.py   ← device state + faucet.yaml management
  device_discovery.py ← auto-discovers hotspot clients
  alert_api.py        ← Flask REST API for NIDS/HIDS
scripts/
  setup_pi.sh         ← full automated Pi setup
systemd/
  faucet.service      ← Faucet controller service unit
  sdn-api.service     ← SDN Alert API service unit
config/
  faucet.yaml         ← Faucet dataplane config (auto-managed)
  device_registry.json← persistent device state (auto-managed)
tests/
  test_sdn.py         ← unit tests (run with pytest)
flow_rules.py         ← legacy flow rule helpers
quarantine_api.py     ← legacy quarantine API shim
secure_switch.py      ← legacy secure switch entrypoint
PROJECT.md            ← full reference (read this before editing any code)
.agents/AGENTS.md     ← rules for AI assistants working on this project
```

## Running tests

```bash
pytest tests/
```

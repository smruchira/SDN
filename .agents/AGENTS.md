# SDN Gateway — AI Agent Rules

## MANDATORY: Maintain PROJECT.md

**Every AI working on this codebase MUST update [PROJECT.md](../PROJECT.md)
when making any of the following changes:**

| Change type | What to update in PROJECT.md |
|---|---|
| New file added | Add a section under "Module Reference" (Section 3) |
| New API endpoint | Add a row/section under "REST API Reference" (Section 4) |
| New config constant | Add a row to the "Configuration Reference" table (Section 5) |
| Architecture change | Update the diagram in "Architecture" (Section 2) |
| New security action | Update "How to Add New Features" (Section 7) if it's a pattern |
| Bug fix affecting behavior | Update relevant section + Known Limitations if applicable |
| Deployment change | Update "Deployment" section (Section 8) |

**PROJECT.md is the handoff document. If it is stale, the next developer
(or AI) wastes time reverse-engineering what you already know.**

---

## Code Style Rules

- **One responsibility per file.** `acl_rules.py` builds rules; `faucet_manager.py` applies them. Do not mix concerns.
- **All config goes in `sdn/config.py`.** Never hardcode IPs, ports, paths, or intervals in other files.
- **New rule types go in `acl_rules.py` first** as pure functions, then are used by `faucet_manager.py`.
- **Thread safety:** All public methods on `FaucetManager` must acquire `self._lock` before modifying `_devices`.
- **Docstrings required** on every public function and class. Include what parameters mean and what is returned.
- **Graceful degradation:** Code that calls Linux system tools (`pgrep`, `ovs-vsctl`) must handle failure silently when running on non-Pi systems (Windows dev environment).

---

## What NOT to do

- Do NOT reintroduce Ryu imports (`ryu.*`). The project uses Faucet.
- Do NOT hardcode MAC addresses. Use `device_registry.json` for state.
- Do NOT add new dependencies without updating `scripts/setup_pi.sh` to install them.
- Do NOT change the REST API contract (endpoint URLs, request/response fields) without versioning.
  The NIDS and HIDS modules depend on `POST /alert`, `DELETE /alert/<mac>`,
  `GET /devices`, and `GET /alert/status` remaining stable.

---

## Project Context

This is part of **SecureMediNet**, a final-year university research project.
The SDN module (this repo) is one of three modules:

```
SecureMediNet
├── SDN Gateway (this repo)  ← you are here
├── NIDS                     ← sends POST /alert to this module
└── HIDS                     ← separate host monitoring
```

The SDN module exposes a REST API at `http://10.0.0.1:5000` which NIDS
calls to enforce network-level responses (quarantine / rate-limit) to
detected threats.

Target hardware: **Raspberry Pi 4, Raspberry Pi OS 64-bit Bookworm.**

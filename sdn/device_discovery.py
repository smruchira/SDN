"""
sdn/device_discovery.py — Auto-discovers IoT devices from dnsmasq DHCP leases.

Runs as a background daemon (thread or standalone process).
Polls DHCP_LEASES_FILE every DISCOVERY_INTERVAL seconds.
When a new device is seen, it is registered with FaucetManager which
automatically applies device-to-device isolation in Faucet.

dnsmasq.leases format (one line per lease):
  <expiry_epoch> <mac> <ip> <hostname> <client_id>

Example:
  1893456000 aa:bb:cc:dd:ee:ff 10.0.0.12 sensor-01 *
"""

import logging
import time
from pathlib import Path

from .config import DHCP_LEASES_FILE, DISCOVERY_INTERVAL
from .faucet_manager import FaucetManager

log = logging.getLogger(__name__)


class DeviceDiscovery:
    """
    Polls the dnsmasq leases file and registers newly-seen MACs.

    Usage (as a daemon thread from alert_api.py):
        discovery = DeviceDiscovery(manager)
        thread = threading.Thread(target=discovery.run, daemon=True)
        thread.start()

    Usage (as a standalone process from systemd):
        python3 -m sdn.device_discovery
    """

    def __init__(self, manager: FaucetManager) -> None:
        self.manager = manager
        self._seen: set[str] = set(manager.get_devices().keys())

    def run(self) -> None:
        """Block forever, polling the leases file. Call in a daemon thread."""
        log.info("Discovery daemon started (leases=%s, interval=%ds)",
                 DHCP_LEASES_FILE, DISCOVERY_INTERVAL)
        while True:
            try:
                self._poll()
            except Exception as exc:
                log.warning("Discovery poll error: %s", exc)
            time.sleep(DISCOVERY_INTERVAL)

    def _poll(self) -> None:
        """Read the leases file and register any new MACs."""
        leases_path = Path(DHCP_LEASES_FILE)
        if not leases_path.exists():
            log.debug("Leases file not found: %s (normal on non-Pi systems)", leases_path)
            return

        for line in leases_path.read_text().splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            _expiry, mac, ip, hostname = parts[0], parts[1], parts[2], parts[3]
            mac = mac.lower()

            if mac not in self._seen:
                log.info("New device on hotspot: mac=%s ip=%s host=%s", mac, ip, hostname)
                self._seen.add(mac)
                self.manager.register(mac, ip=ip, hostname=hostname)


# ── Standalone entry-point (for sdn-discovery.service) ────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    manager = FaucetManager()
    DeviceDiscovery(manager).run()

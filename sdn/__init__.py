"""
sdn/__init__.py — Public API surface for the sdn package.

Import from here, not from individual submodules, to keep coupling low.

Example:
    from sdn import FaucetManager, DeviceDiscovery
"""

from .faucet_manager import FaucetManager
from .device_discovery import DeviceDiscovery

__all__ = ["FaucetManager", "DeviceDiscovery"]

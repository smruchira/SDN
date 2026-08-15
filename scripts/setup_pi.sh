#!/usr/bin/env bash
# =============================================================================
# setup_pi.sh — Full Raspberry Pi 4 SDN Gateway Setup
# =============================================================================
# OS:  Raspberry Pi OS 64-bit Desktop (Bookworm / Debian 12)
# Run: sudo bash scripts/setup_pi.sh
#
# What this script does:
#   1. Updates the system
#   2. Installs: openvswitch, hostapd, dnsmasq, python3, pip, iptables
#   3. Configures Wi-Fi AP (hostapd) on wlan0
#   4. Configures DHCP server (dnsmasq) for IoT devices
#   5. Creates OVS bridge br-sdn and attaches wlan0 + eth0
#   6. Points OVS at Faucet controller (tcp:127.0.0.1:6653)
#   7. Installs Faucet controller in a Python venv
#   8. Installs the SDN gateway (Flask API + discovery) in another venv
#   9. Sets up NAT so IoT devices can reach the internet via eth0
#  10. Installs and enables all systemd services
# =============================================================================

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
step()  { echo -e "\n${GREEN}══ $* ══${NC}"; }

[[ $EUID -ne 0 ]] && die "Run as root: sudo bash scripts/setup_pi.sh"

# ── Configuration — edit these before running ─────────────────────────────
SSID="IoT-Gateway"
PASSWORD="iotgateway123"
GATEWAY_IP="10.0.0.1"
DHCP_RANGE="10.0.0.10,10.0.0.200,12h"
WLAN_IFACE="wlan0"
ETH_IFACE="eth0"
OVS_BRIDGE="br-sdn"
SDN_DIR="/opt/sdn"
FAUCET_VENV="/opt/faucet-venv"
SDN_VENV="${SDN_DIR}/venv"
API_PORT="5000"

# ── Step 1: Update system ─────────────────────────────────────────────────
step "System update"
apt-get update -qq
apt-get upgrade -y -qq

# ── Step 2: Install packages ──────────────────────────────────────────────
step "Installing packages"
apt-get install -y -qq \
    openvswitch-switch \
    hostapd \
    dnsmasq \
    python3-pip \
    python3-venv \
    iptables \
    iptables-persistent \
    net-tools \
    curl

info "Packages installed."

# ── Step 3: Configure hostapd (Wi-Fi AP) ─────────────────────────────────
step "Configuring Wi-Fi Access Point"
systemctl stop hostapd 2>/dev/null || true

cat > /etc/hostapd/hostapd.conf << EOF
# Raspberry Pi SDN Gateway — Wi-Fi AP config
interface=${WLAN_IFACE}
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=7
ieee80211n=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

# Tell hostapd where its config is
sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
info "hostapd configured: SSID=${SSID}"

# ── Step 4: Configure dnsmasq (DHCP) ─────────────────────────────────────
step "Configuring DHCP server"
[ -f /etc/dnsmasq.conf ] && mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak

cat > /etc/dnsmasq.conf << EOF
# SDN Gateway DHCP config — serves IoT devices on the OVS bridge
interface=${OVS_BRIDGE}
bind-interfaces
server=8.8.8.8
server=8.8.4.4

# DHCP pool for IoT devices
dhcp-range=${DHCP_RANGE}
dhcp-option=3,${GATEWAY_IP}   # default gateway
dhcp-option=6,8.8.8.8         # DNS

# Log leases (device discovery reads this file)
log-dhcp
dhcp-leasefile=/var/lib/misc/dnsmasq.leases
EOF

info "dnsmasq configured: pool=${DHCP_RANGE}"

# ── Step 5: Set up OVS bridge ─────────────────────────────────────────────
step "Configuring Open vSwitch"
systemctl start openvswitch-switch

# Recreate bridge cleanly
ovs-vsctl --if-exists del-br "${OVS_BRIDGE}"
ovs-vsctl add-br "${OVS_BRIDGE}"
ovs-vsctl add-port "${OVS_BRIDGE}" "${WLAN_IFACE}" || warn "Could not add ${WLAN_IFACE} — add manually after reboot"
ovs-vsctl add-port "${OVS_BRIDGE}" "${ETH_IFACE}"  || warn "Could not add ${ETH_IFACE} — add manually after reboot"

# Point OVS at the Faucet controller
ovs-vsctl set-controller "${OVS_BRIDGE}" "tcp:127.0.0.1:${FAUCET_PORT:-6653}"
ovs-vsctl set bridge     "${OVS_BRIDGE}" protocols=OpenFlow13

# Bring bridge up with gateway IP
ip addr flush dev "${OVS_BRIDGE}" 2>/dev/null || true
ip addr add "${GATEWAY_IP}/24" dev "${OVS_BRIDGE}"
ip link set "${OVS_BRIDGE}" up

# Persist bridge config across reboots
cat > /etc/network/interfaces.d/br-sdn << EOF
auto ${OVS_BRIDGE}
iface ${OVS_BRIDGE} inet static
    address ${GATEWAY_IP}
    netmask 255.255.255.0
EOF

info "OVS bridge ${OVS_BRIDGE} created and configured."

# ── Step 6: IP forwarding + NAT ───────────────────────────────────────────
step "Enabling NAT and IP forwarding"
# Persist across reboots
grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf \
    || echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p /etc/sysctl.conf > /dev/null

# NAT: IoT devices (10.0.0.0/24) → internet via eth0
iptables -t nat -F
iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o "${ETH_IFACE}" -j MASQUERADE
iptables -A FORWARD -i "${OVS_BRIDGE}" -o "${ETH_IFACE}" -j ACCEPT
iptables -A FORWARD -i "${ETH_IFACE}" -o "${OVS_BRIDGE}" -m state --state RELATED,ESTABLISHED -j ACCEPT
netfilter-persistent save
info "NAT enabled: IoT → ${ETH_IFACE} → internet"

# ── Step 7: Install Faucet ────────────────────────────────────────────────
step "Installing Faucet SDN controller"
python3 -m venv "${FAUCET_VENV}"
"${FAUCET_VENV}/bin/pip" install --quiet faucet
mkdir -p /etc/faucet /var/log/faucet
info "Faucet installed in ${FAUCET_VENV}"

# ── Step 8: Install SDN gateway application ───────────────────────────────
step "Installing SDN Gateway application"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

mkdir -p "${SDN_DIR}"
rsync -a --exclude="*.pyc" --exclude="__pycache__" "${PROJECT_DIR}/" "${SDN_DIR}/"
python3 -m venv "${SDN_VENV}"
"${SDN_VENV}/bin/pip" install --quiet flask flask-cors pyyaml
mkdir -p "${SDN_DIR}/config"
info "SDN Gateway installed in ${SDN_DIR}"

# ── Step 9: Write initial faucet.yaml ─────────────────────────────────────
step "Writing initial Faucet config"
# Get the OVS-assigned datapath ID (hex string)
DP_HEX=$(ovs-vsctl get bridge "${OVS_BRIDGE}" datapath_id 2>/dev/null | tr -d '"' || echo "0000000000000001")
DP_ID=$((16#${DP_HEX}))

cat > /etc/faucet/faucet.yaml << EOF
# Generated by setup_pi.sh — managed at runtime by FaucetManager
vlans:
  iot:
    vid: 100
    description: "IoT device VLAN"

acls:
  iot_policy:
    - rule:
        actions:
          allow: true

dps:
  pi-switch:
    dp_id: ${DP_ID}
    hardware: "Open vSwitch"
    interfaces:
      1:
        name: ${WLAN_IFACE}
        description: "IoT Wi-Fi AP"
        native_vlan: iot
        acls_in: [iot_policy]
      2:
        name: ${ETH_IFACE}
        description: "Internet uplink"
        native_vlan: iot
EOF

# Override path so FaucetManager writes to /etc/faucet/faucet.yaml
echo "SDN_FAUCET_YAML=/etc/faucet/faucet.yaml" >> /etc/environment
info "faucet.yaml written (dp_id=${DP_ID})"

# ── Step 10: Install systemd services ────────────────────────────────────
step "Installing systemd services"
cp "${SDN_DIR}/systemd/faucet.service"       /etc/systemd/system/
cp "${SDN_DIR}/systemd/sdn-api.service"      /etc/systemd/system/
cp "${SDN_DIR}/systemd/sdn-discovery.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now openvswitch-switch
systemctl enable --now hostapd
systemctl enable --now dnsmasq
systemctl enable --now faucet
systemctl enable --now sdn-api

info "All services enabled and started."

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         SDN Gateway Setup Complete! 🎉              ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Hotspot SSID : ${SSID}${NC}"
echo -e "${GREEN}║  Password     : ${PASSWORD}${NC}"
echo -e "${GREEN}║  Gateway IP   : ${GATEWAY_IP}${NC}"
echo -e "${GREEN}║  REST API     : http://${GATEWAY_IP}:${API_PORT}${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Logs:                                               ║${NC}"
echo -e "${GREEN}║    sudo journalctl -u faucet    -f                  ║${NC}"
echo -e "${GREEN}║    sudo journalctl -u sdn-api   -f                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"

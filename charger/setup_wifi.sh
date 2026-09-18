#!/usr/bin/env bash
# ==============================================================================
# Setup dedicated Wi-Fi connection for BF Tech (Hexapower) Charger on wlan1
# Run this on sing once the USB Wi-Fi dongle is physically plugged in.
# ==============================================================================
set -e

IFACE="${1:-wlan1}"
DEFAULT_SSID="BF_TECH_419A99"
DEFAULT_PASS="BFKJ1688"
DEFAULT_CHARGER_IP="192.168.4.1"

echo "=========================================================="
echo " Paeraki • BF Tech Charger Wi-Fi Configuration Helper"
echo "=========================================================="

# 1. Verify USB Wi-Fi interface exists
echo "==> Checking network interfaces for $IFACE..."
if ! ip link show "$IFACE" &>/dev/null; then
    echo ""
    echo "[-] Interface '$IFACE' not found!"
    echo "    Currently detected wireless interfaces:"
    ip -br link show type wifi || true
    echo ""
    echo "[!] Please plug in the USB Wi-Fi dongle into sing."
    echo "    If it appears as a different name (e.g. wlan2), run:"
    echo "    $0 <interface_name>"
    exit 1
fi

echo "[+] Found interface '$IFACE' (state: $(ip -br link show "$IFACE" | awk '{print $2}'))"

# 2. Scan for charger AP
echo "==> Scanning for available Wi-Fi access points on $IFACE..."
sudo nmcli device wifi rescan ifname "$IFACE" 2>/dev/null || true
sleep 2
echo "----------------------------------------------------------"
sudo nmcli --fields IN-USE,BSSID,SSID,CHAN,SIGNAL,SECURITY device wifi list ifname "$IFACE" || true
echo "----------------------------------------------------------"

# 3. Prompt for SSID and Password
read -rp "Enter Charger AP SSID [default: $DEFAULT_SSID]: " SSID
SSID="${SSID:-$DEFAULT_SSID}"

read -rp "Enter Charger AP Password [default: $DEFAULT_PASS] (press space+enter or '-' for open): " PASS
PASS="${PASS:-$DEFAULT_PASS}"
[ "$PASS" = "-" ] && PASS=""

CON_NAME="BF_TECH_CHARGER"

# Remove old connection profile if exists
if nmcli connection show "$CON_NAME" &>/dev/null; then
    echo "==> Removing existing connection profile '$CON_NAME'..."
    sudo nmcli connection delete "$CON_NAME"
fi

# 4. Create dedicated connection profile strictly bound to $IFACE
echo "==> Creating connection profile '$CON_NAME' on $IFACE..."
if [ -z "$PASS" ]; then
    sudo nmcli connection add type wifi ifname "$IFACE" con-name "$CON_NAME" ssid "$SSID"
else
    sudo nmcli connection add type wifi ifname "$IFACE" con-name "$CON_NAME" ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PASS"
fi

# 5. CRITICAL: Prevent default route hijacking & enforce high metric
echo "==> Configuring routing rules to prevent Paeraki network interference..."
sudo nmcli connection modify "$CON_NAME" \
    ipv4.never-default true \
    ipv4.route-metric 1000 \
    ipv6.method "ignore" \
    connection.autoconnect true \
    connection.autoconnect-priority 50

# 6. Activate connection
echo "==> Activating connection to '$SSID' on $IFACE..."
sudo nmcli connection up "$CON_NAME" || {
    echo "[-] Failed to connect immediately. The charger may be turned off or out of range."
    echo "    The profile is saved and will auto-connect as soon as the charger AP is in range."
    exit 0
}

# 7. Test ping
echo "==> Testing reachability to charger at $DEFAULT_CHARGER_IP..."
if ping -I "$IFACE" -c 2 -W 2 "$DEFAULT_CHARGER_IP" &>/dev/null; then
    echo "[+] SUCCESS: Charger at $DEFAULT_CHARGER_IP is reachable via $IFACE!"
    echo "    You can now run: python3 charger/probe.py"
else
    echo "[!] Ping to $DEFAULT_CHARGER_IP timed out. Check if charger is powered on."
fi

echo "==> Wi-Fi setup complete. Primary Paeraki network remains 100% untouched."

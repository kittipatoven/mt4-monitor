#!/bin/bash
# MT4 Trading Monitor V1 - remove from the Raspberry Pi.
#   sudo bash uninstall.sh           remove app + service, KEEP settings/API key
#   sudo bash uninstall.sh --purge   also delete /etc/mt4-monitor.env and the key copy
# Tailscale, I2C and installed apt packages are left as they are.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }
PURGE=0; [ "${1:-}" = "--purge" ] && PURGE=1
OWNER_HOME="$(getent passwd "${SUDO_USER:-pi}" | cut -d: -f6)"

systemctl disable --now mt4-monitor mt4-wifi 2>/dev/null || true
nmcli connection delete mt4-setup >/dev/null 2>&1 || true
while iptables -t nat -D PREROUTING -i wlan0 -p tcp --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null; do :; done
rm -f /etc/systemd/system/mt4-monitor.service /etc/systemd/system/mt4-wifi.service \
      /etc/NetworkManager/dnsmasq-shared.d/mt4-captive.conf /usr/local/bin/mt4mon
systemctl daemon-reload
rm -rf /opt/mt4-monitor
id mt4mon >/dev/null 2>&1 && userdel mt4mon || true
echo "removed service, /opt/mt4-monitor, mt4mon command and user"

if [ "$PURGE" -eq 1 ]; then
  rm -f /etc/mt4-monitor.env "$OWNER_HOME/mt4-monitor/api_key.txt"
  echo "removed settings and API key"
else
  echo "kept /etc/mt4-monitor.env (API key) - reinstalling will reuse it"
fi
echo "UNINSTALL DONE"

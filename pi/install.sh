#!/bin/bash
# =====================================================================
#  MT4 Trading Monitor V1 - Raspberry Pi installer (read-only monitor)
#
#  One line, straight from GitHub (nothing to copy first):
#     curl -fsSL https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/pi/install.sh | sudo bash -s -- --ts-key tskey-auth-XXXX
#
#  Or from a copy of the pi/ folder:
#     sudo bash install.sh [options]
#
#  Options:
#     --ts-key KEY        Tailscale auth key: joins with no browser login
#     --no-tailscale      skip Tailscale
#     --lcd-address 0x3F  force the LCD I2C address (default: found automatically)
#
#  Safe to run again (also how you update): keeps the API key and your
#  settings in /etc/mt4-monitor.env, only adds new settings.
# =====================================================================
set -euo pipefail

REPO="kittipatoven/mt4-monitor"
BRANCH="main"
APP=/opt/mt4-monitor
ENV_FILE=/etc/mt4-monitor.env
SERVICE=mt4-monitor
SVC_USER=mt4mon
TS_HOSTNAME=mt4-monitor-pi
SELF="${BASH_SOURCE[0]:-}"
SRC=""
[ -n "$SELF" ] && [ -f "$SELF" ] && SRC="$(cd "$(dirname "$SELF")" && pwd)"
OWNER="${SUDO_USER:-pi}"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
WANT_TS=1
WANT_WIFI=1
DISPLAY_SET=""          # --display lcd1602|tft35 (empty = keep current setting)
TS_KEY="${TS_AUTHKEY:-}"
LCD_ADDR=""
REBOOT_NEEDED=0

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m[OK]\033[0m %s\n' "$*"; }
warn() { printf '   \033[33m[!!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m[ERROR]\033[0m %s\n' "$*"; exit 1; }
trap 'die "stopped at line $LINENO - fix the problem above and run the installer again"' ERR

while [ $# -gt 0 ]; do
  case "$1" in
    --no-tailscale) WANT_TS=0 ;;
    --no-wifi-setup) WANT_WIFI=0 ;;
    --display)      DISPLAY_SET="${2:-}"; shift ;;
    --ts-key)       TS_KEY="${2:-}"; shift ;;
    --lcd-address)  LCD_ADDR="${2:-}"; shift ;;
    -h|--help)      echo "Usage: sudo bash install.sh [--ts-key KEY] [--no-tailscale] [--lcd-address 0x27] [--display lcd1602|tft35]"; exit 0 ;;
    *)              die "unknown option: $1 (see --help)" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "run with sudo:   ... | sudo bash   or   sudo bash install.sh"
case "$DISPLAY_SET" in ""|lcd1602|tft35) ;; *) die "--display must be lcd1602 or tft35" ;; esac
if [ -n "$TS_KEY" ] && ! [[ "$TS_KEY" =~ ^tskey- ]]; then
  die "--ts-key must start with tskey-"
fi

NEEDED="main.py tft.py lcd.py config.py test_sender.py requirements.txt mt4-monitor.service mt4-monitor.env.example mt4mon uninstall.sh wifi_setup.py mt4-wifi.service mt4-captive.conf sshwatch.sh mt4-sshwatch.service mt4-sshwatch.timer"
have_all() { for f in $NEEDED; do [ -f "$1/$f" ] || return 1; done; }
if [ -z "$SRC" ] || ! have_all "$SRC"; then
  # Run through a pipe (curl | bash) or from an incomplete folder: fetch the project.
  TMP="$(mktemp -d)"
  echo "Downloading $REPO ($BRANCH) from GitHub..."
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" | tar -xz -C "$TMP" \
    || die "could not download https://github.com/$REPO - check the internet connection"
  SRC="$TMP/${REPO##*/}-$BRANCH/pi"
  have_all "$SRC" || die "the download is missing files - try again later"
fi
if [ -n "$LCD_ADDR" ] && ! [[ "$LCD_ADDR" =~ ^0x[0-9a-fA-F]{2}$ ]]; then
  die "--lcd-address must look like 0x27 or 0x3F"
fi

echo "MT4 Trading Monitor V1 installer  (source: $SRC)"

# ---------------------------------------------------------------------
step "1/7 Packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq i2c-tools python3-venv curl iptables dnsmasq-base >/dev/null
ok "i2c-tools, python3-venv, curl, iptables, dnsmasq-base"
# Python libraries from apt: much faster than pip on a Pi 3 (pip fills any gap later).
if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-flask python3-waitress python3-smbus2      python3-pil python3-qrcode fonts-dejavu-core >/dev/null 2>&1; then
  ok "python3-flask, python3-waitress, python3-smbus2, python3-pil, python3-qrcode"
else
  warn "some Python packages are not in apt here - pip will install them (slower)"
fi

# ---------------------------------------------------------------------
step "2/7 I2C"
if command -v raspi-config >/dev/null; then
  raspi-config nonint do_i2c 0
else
  CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
  grep -q '^dtparam=i2c_arm=on' "$CFG" || echo 'dtparam=i2c_arm=on' >> "$CFG"
  grep -q '^i2c-dev' /etc/modules || echo 'i2c-dev' >> /etc/modules
fi
modprobe i2c-dev 2>/dev/null || true
if [ -e /dev/i2c-1 ]; then
  ok "I2C bus 1 is on (/dev/i2c-1)"
else
  REBOOT_NEEDED=1
  warn "I2C turns on after a reboot - the installer will remind you at the end"
fi

if [ -z "$LCD_ADDR" ] && [ -e /dev/i2c-1 ]; then
  LCD_ADDR="$(i2cdetect -y 1 2>/dev/null \
    | awk 'NR>1 { for (i = 2; i <= NF; i++) if ($i == "27" || $i == "3f") { print "0x" $i; exit } }' || true)"
  if [ -n "$LCD_ADDR" ]; then
    ok "LCD found at $LCD_ADDR"
  else
    warn "no LCD at 0x27/0x3F - check the wiring (docs/WIRING.md). Using the saved/default address."
  fi
fi

# ---------------------------------------------------------------------
step "3/7 App files ($APP)"
id "$SVC_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin "$SVC_USER"
usermod -aG i2c "$SVC_USER"
mkdir -p "$APP"
for f in config.py lcd.py main.py tft.py test_sender.py requirements.txt uninstall.sh wifi_setup.py sshwatch.sh; do
  tr -d '\r' < "$SRC/$f" > "$APP/$f"
  chmod 644 "$APP/$f"
done
# --system-site-packages: reuse the apt Python libraries, so pip has nothing to download.
[ -x "$APP/venv/bin/python" ] || python3 -m venv --system-site-packages "$APP/venv"
# Older installs made the venv without apt packages; let it see them (Pillow, qrcode...).
sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' "$APP/venv/pyvenv.cfg"
"$APP/venv/bin/pip" install -q --disable-pip-version-check -r "$APP/requirements.txt"
"$APP/venv/bin/python" -c "import flask, waitress, smbus2"
ok "Python packages: flask, waitress, smbus2"
chown -R root:root "$APP"

# ---------------------------------------------------------------------
step "4/7 Settings ($ENV_FILE)"
if [ ! -f "$ENV_FILE" ]; then
  NEW_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
  tr -d '\r' < "$SRC/mt4-monitor.env.example" \
    | sed "s/^MT4MON_API_KEY=.*/MT4MON_API_KEY=$NEW_KEY/" > "$ENV_FILE"
  ok "created, with a new random API key"
else
  ok "keeping existing settings and API key"
  while IFS= read -r line; do          # add settings that are new in this version
    case "$line" in ''|\#*) continue ;; esac
    k="${line%%=*}"
    grep -q "^$k=" "$ENV_FILE" || { echo "$line" >> "$ENV_FILE"; ok "added new setting $k"; }
  done < <(tr -d '\r' < "$SRC/mt4-monitor.env.example")
fi
if [ -n "$LCD_ADDR" ]; then
  sed -i "s/^MT4MON_LCD_ADDRESS=.*/MT4MON_LCD_ADDRESS=$LCD_ADDR/" "$ENV_FILE"
fi
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Hotspot password for Wi-Fi setup mode: "random" = a new one each time setup mode opens
# (shown on the LCD). Older versions stored one fixed auto-generated number: switch that
# to random. A password you typed yourself (not 8 digits) is kept.
SETUP_PASS="$(grep '^MT4MON_SETUP_PASS=' "$ENV_FILE" | cut -d= -f2-)"
if [ -z "$SETUP_PASS" ] || [[ "$SETUP_PASS" =~ ^[2-9]{8}$ ]]; then
  sed -i "s/^MT4MON_SETUP_PASS=.*/MT4MON_SETUP_PASS=random/" "$ENV_FILE"
  SETUP_PASS=random
fi
[ "$SETUP_PASS" = "random" ] && PASS_TXT="new random one each time, shown on the LCD" || PASS_TXT="$SETUP_PASS"
[ "$WANT_WIFI" -eq 0 ] && sed -i 's/^MT4MON_WIFI_SETUP=.*/MT4MON_WIFI_SETUP=0/' "$ENV_FILE"
WIFI_ON="$(grep '^MT4MON_WIFI_SETUP=' "$ENV_FILE" | cut -d= -f2-)"
if [ -n "$DISPLAY_SET" ]; then
  if grep -q '^MT4MON_DISPLAY=' "$ENV_FILE"; then
    sed -i "s/^MT4MON_DISPLAY=.*/MT4MON_DISPLAY=$DISPLAY_SET/" "$ENV_FILE"
  else
    echo "MT4MON_DISPLAY=$DISPLAY_SET" >> "$ENV_FILE"
  fi
fi
DISPLAY_NOW="$(grep '^MT4MON_DISPLAY=' "$ENV_FILE" | cut -d= -f2-)"; DISPLAY_NOW="${DISPLAY_NOW:-lcd1602}"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
TFT_LINE="dtoverlay=piscreen,speed=16000000,rotate=90   # mt4-monitor 3.5in TFT"
if [ "$DISPLAY_NOW" = "tft35" ]; then
  # 3.5" SPI screen (ILI9486 + XPT2046 touch): SPI on + driver overlay, needs a reboot once.
  raspi-config nonint do_spi 0 >/dev/null 2>&1 || true
  if ! grep -q "mt4-monitor 3.5in TFT" "$CFG"; then
    printf '
[all]
%s
' "$TFT_LINE" >> "$CFG"
    REBOOT_NEEDED=1
    ok "3.5in screen driver added to $CFG (reboot needed)"
  fi
  ok "display: 3.5in colour TFT"
else
  if grep -q "mt4-monitor 3.5in TFT" "$CFG"; then
    sed -i '/mt4-monitor 3.5in TFT/d' "$CFG"; REBOOT_NEEDED=1
    ok "3.5in screen driver removed (reboot needed)"
  fi
  ok "display: 16x2 LCD"
fi

KEY="$(grep '^MT4MON_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
[ -n "$KEY" ] && [ "$KEY" != "CHANGE_ME" ] || die "MT4MON_API_KEY in $ENV_FILE is empty"
PORT="$(grep '^MT4MON_PORT=' "$ENV_FILE" | cut -d= -f2-)"; PORT="${PORT:-80}"
LCD_ADDR="$(grep '^MT4MON_LCD_ADDRESS=' "$ENV_FILE" | cut -d= -f2-)"

KEY_COPY="$OWNER_HOME/mt4-monitor/api_key.txt"
mkdir -p "$(dirname "$KEY_COPY")"
printf '%s\n' "$KEY" > "$KEY_COPY"
chown "$OWNER:$OWNER" "$(dirname "$KEY_COPY")" "$KEY_COPY"
chmod 600 "$KEY_COPY"
ok "API key copy for MonitorEA: $KEY_COPY"

# ---------------------------------------------------------------------
step "5/7 Services + mt4mon command"
tr -d '\r' < "$SRC/mt4-monitor.service" > /etc/systemd/system/$SERVICE.service
tr -d '\r' < "$SRC/mt4-wifi.service" > /etc/systemd/system/mt4-wifi.service
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
tr -d '\r' < "$SRC/mt4-captive.conf" > /etc/NetworkManager/dnsmasq-shared.d/mt4-captive.conf
tr -d '\r' < "$SRC/mt4mon" > /usr/local/bin/mt4mon
chmod 755 /usr/local/bin/mt4mon
tr -d '\r' < "$SRC/mt4-sshwatch.service" > /etc/systemd/system/mt4-sshwatch.service
tr -d '\r' < "$SRC/mt4-sshwatch.timer" > /etc/systemd/system/mt4-sshwatch.timer
# Keep system logs across reboots (otherwise a problem's clues vanish when the Pi restarts).
# Raspberry Pi OS forces RAM-only logs (40-rpi-volatile-storage.conf); this drop-in overrides
# it, capped at 50 MB.
JCONF=/etc/systemd/journald.conf.d/50-mt4-persistent.conf
if [ ! -f "$JCONF" ]; then
  mkdir -p /etc/systemd/journald.conf.d /var/log/journal
  printf '[Journal]\nStorage=persistent\nSystemMaxUse=50M\n' > "$JCONF"
  systemd-tmpfiles --create --prefix /var/log/journal >/dev/null 2>&1 || true
  systemctl restart systemd-journald
  journalctl --flush >/dev/null 2>&1 || true
  ok "system logs now kept across reboots (max 50 MB)"
fi
systemctl daemon-reload
systemctl enable -q "$SERVICE" mt4-wifi
systemctl enable -q --now mt4-sshwatch.timer
ok "SSH watchdog: checks every 5 min, restarts SSH if it stops answering"
systemctl restart "$SERVICE"
# Safe while online: setup mode only starts after MT4MON_SETUP_AFTER seconds with no network.
systemctl restart mt4-wifi
if [ "$WIFI_ON" = "0" ]; then ok "Wi-Fi setup mode: off"; else ok "Wi-Fi setup mode: on (hotspot password: $PASS_TXT)"; fi

HEALTH=""
for _ in $(seq 1 20); do
  HEALTH="$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null || true)"
  [ -n "$HEALTH" ] && break
  sleep 1
done
if [ -n "$HEALTH" ]; then
  ok "service running, API answers on port $PORT"
else
  warn "API did not answer on port $PORT. Last log lines:"
  journalctl -u "$SERVICE" --no-pager -n 15 -o cat || true
fi

# ---------------------------------------------------------------------
step "6/7 Tailscale"
TS_IP=""
if [ "$WANT_TS" -eq 1 ]; then
  if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  systemctl enable --now tailscaled >/dev/null 2>&1 || true
  if ! tailscale ip -4 >/dev/null 2>&1; then
    if [ -n "$TS_KEY" ]; then
      tailscale up --hostname="$TS_HOSTNAME" --auth-key="$TS_KEY" \
        || warn "Tailscale did not accept the auth key - make a new one and run: sudo tailscale up --auth-key=..."
    else
      echo "   Open the login link below in a browser, sign in, then press Connect."
      echo "   (If your account needs device approval, approve it on the Machines page.)"
      tailscale up --hostname="$TS_HOSTNAME" || warn "Tailscale login did not finish - run: sudo tailscale up"
    fi
  else
    ok "already logged in"
  fi
  TS_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
  if [ -n "$TS_IP" ]; then ok "Tailscale IP: $TS_IP"; else warn "Tailscale is not logged in yet"; fi
else
  ok "skipped (--no-tailscale)"
fi

# ---------------------------------------------------------------------
step "7/7 Summary"
HOST_PART="${TS_IP:-<tailscale-ip>}"
[ "$PORT" = "80" ] || HOST_PART="$HOST_PART:$PORT"
cat <<EOF

   LCD address        : $LCD_ADDR
   API port           : $PORT   (MT4 WebRequest only allows 80 / 443)
   API key            : $KEY_COPY   (or: sudo mt4mon key)
   Wi-Fi setup        : no network for 90 s -> hotspot MT4-Setup-XXXX, password: $PASS_TXT
                        (shown on the LCD; change Wi-Fi any time: sudo mt4mon wifi)
   Everyday commands  : mt4mon status | mt4mon logs | mt4mon help
EOF
if [ -n "$TS_IP" ]; then
  cat <<EOF

   NEXT - on the Windows VPS, open PowerShell as Administrator and paste this ONE line
   (it sets up Tailscale, MonitorEA and the key; show it again later with: sudo mt4mon vps):

powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/$REPO/$BRANCH/vps/setup_vps.ps1))) -PiIp $HOST_PART -ApiKey $KEY"
EOF
else
  printf '\n   After Tailscale is logged in, run  sudo mt4mon vps  for the VPS setup line.\n'
fi
if [ "$REBOOT_NEEDED" -eq 1 ]; then
  printf '\n   \033[33mReboot once now to switch I2C on:  sudo reboot\033[0m\n'
fi
printf '\n\033[1;32mINSTALL DONE\033[0m\n'

"""MT4 Trading Monitor V1 - Wi-Fi setup mode (runs as root, stdlib only).

When the Pi has had no network for MT4MON_SETUP_AFTER seconds, it starts its
own Wi-Fi hotspot. A phone joins it, the setup page opens by itself (captive
portal), the user picks a Wi-Fi network and types its password, and the Pi
connects to it. The LCD shows what to do (via /run/mt4-wifi/state.json).

Safety:
- Only works through the hotspot: page requests from any other network get 403.
- The hotspot has a WPA2 password, shown only on the LCD (physical access).
- nmcli is always called with argument lists (no shell).
- Networks that cannot be reached yet stay saved; the Pi retries them every
  few minutes, so a phone hotspot can be switched on after setup.

Manual start (also drops the current Wi-Fi):  sudo mt4mon wifi
"""
import html
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENABLED = os.environ.get("MT4MON_WIFI_SETUP", "1").strip() not in ("0", "false", "no", "off")
SETUP_AFTER = int(os.environ.get("MT4MON_SETUP_AFTER", "90") or 90)
# "random" (default) = a new 8-digit hotspot password every time setup mode opens,
# shown on the LCD. Any other value of 8-63 characters = that fixed password.
SETUP_PASS = (os.environ.get("MT4MON_SETUP_PASS", "") or "").strip()
RANDOM_PASS = SETUP_PASS.lower() in ("", "random") or len(SETUP_PASS) < 8


def new_ap_password():
    if not RANDOM_PASS:
        return SETUP_PASS
    return "".join(secrets.choice("23456789") for _ in range(8))   # no 0/1: easy to read
AP_SECONDS = 180           # stay in setup mode this long without page use, then retry saved Wi-Fi
RETRY_SECONDS = 45         # how long to let saved Wi-Fi try before going back to setup mode
IFACE = "wlan0"
AP_CON = "mt4-setup"
AP_IP = "10.42.0.1"        # NetworkManager's default address for a shared hotspot
PORTAL_PORT = 8080         # the API owns port 80; hotspot port 80 is redirected here
STATE_DIR = "/run/mt4-wifi"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
FORCE_FILE = os.path.join(STATE_DIR, "force")
DRYRUN = os.environ.get("MT4MON_WIFI_DRYRUN") == "1"   # PC testing: log nmcli calls only


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def run(args, timeout=60):
    """Run a command (list form). Returns (ok, output)."""
    if DRYRUN:
        log("DRYRUN: " + " ".join(args))
        return True, ""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as exc:  # timeout, missing tool
        return False, str(exc)


def nm_split(line):
    """Split one `nmcli -t` line (':' separated, '\\:' escaped)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


# --------------------------------------------------------------------------
# State shared with the LCD (main.py reads STATE_FILE)
# --------------------------------------------------------------------------
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "normal"          # normal | setup | connecting | connected
        self.ssid_ap = ap_ssid()
        self.target = ""
        self.error = ""
        self.networks = []            # [(ssid, signal, secured)]
        self.last_page_hit = 0.0
        self.pending = None           # (ssid, password) submitted from the page
        self.announce = False         # show the new IP once, after setup mode
        self.ip = ""
        self.until = 0.0              # end of the "connected" IP screen (epoch seconds)
        self.ap_pass = ""             # hotspot password of the current setup session

    def publish(self):
        data = {"mode": self.mode, "ap_ssid": self.ssid_ap, "ap_pass": self.ap_pass,
                "url": f"http://{AP_IP}", "target": self.target, "error": self.error,
                "ip": self.ip, "until": self.until, "time": int(time.time())}
        if DRYRUN:
            return
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o644)
        os.replace(tmp, STATE_FILE)


def ap_ssid():
    try:
        mac = open(f"/sys/class/net/{IFACE}/address").read().strip()
        return "MT4-Setup-" + mac.replace(":", "")[-4:].upper()
    except OSError:
        return "MT4-Setup"


# --------------------------------------------------------------------------
# NetworkManager helpers
# --------------------------------------------------------------------------
def online():
    """True when Wi-Fi (not our hotspot) or Ethernet is connected."""
    ok, out = run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"], timeout=15)
    if not ok:
        return DRYRUN
    for line in out.splitlines():
        typ, st, con = (nm_split(line) + ["", "", ""])[:3]
        if st == "connected" and con != AP_CON and typ in ("wifi", "ethernet"):
            return True
    return False


def wifi_info():
    """(ssid, ipv4) of the current Wi-Fi connection, '' when unknown."""
    if DRYRUN:
        return "Test WiFi", "192.168.1.45"
    ok, out = run(["nmcli", "-g", "GENERAL.CONNECTION,IP4.ADDRESS", "device", "show", IFACE],
                  timeout=15)
    lines = out.splitlines() if ok else []
    ssid = lines[0].strip() if lines else ""
    ip = lines[1].split("/")[0].split("|")[0].strip() if len(lines) > 1 else ""
    return ssid, ip


IP_SCREEN_SECONDS = 10


def announce_connected(st, ssid=""):
    """After setup mode: show the Wi-Fi IP on the LCD once, for 10 seconds."""
    name, ip = wifi_info()
    for _ in range(5):                # DHCP may need a moment after 'connected'
        if ip:
            break
        time.sleep(1)
        name, ip = wifi_info()
    with st.lock:
        st.mode, st.target, st.ip = "connected", ssid or name, ip
        st.until = time.time() + IP_SCREEN_SECONDS
        st.announce = False
        st.publish()
    log(f"connected to {st.target!r}, IP {ip or 'unknown'} - shown on the LCD")


def scan():
    ok, out = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                   "ifname", IFACE, "--rescan", "yes"], timeout=30)
    nets = {}
    for line in out.splitlines() if ok else []:
        ssid, sig, sec = (nm_split(line) + ["", "0", ""])[:3]
        if not ssid or ssid.startswith("MT4-Setup"):
            continue
        sig = int(sig) if sig.isdigit() else 0
        if ssid not in nets or nets[ssid][0] < sig:
            nets[ssid] = (sig, sec not in ("", "--"))
    return sorted(((s, v[0], v[1]) for s, v in nets.items()), key=lambda n: -n[1])[:20]


def redirect(on):
    """Send hotspot clients' port 80 to the portal (the API keeps port 80 elsewhere)."""
    rule = ["PREROUTING", "-i", IFACE, "-p", "tcp", "--dport", "80", "-j", "REDIRECT",
            "--to-ports", str(PORTAL_PORT)]
    exists, _ = run(["iptables", "-t", "nat", "-C"] + rule)
    if on and not exists:
        run(["iptables", "-t", "nat", "-A"] + rule)
    elif not on:
        while exists:
            run(["iptables", "-t", "nat", "-D"] + rule)
            exists, _ = run(["iptables", "-t", "nat", "-C"] + rule)
            if DRYRUN:
                break


def start_ap(st):
    nets = scan()                     # scan first: the radio is busy once the hotspot runs
    password = new_ap_password()      # new one every time (unless a fixed one is set)
    run(["nmcli", "connection", "delete", AP_CON], timeout=20)
    ok, out = run(["nmcli", "device", "wifi", "hotspot", "ifname", IFACE, "con-name", AP_CON,
                   "ssid", st.ssid_ap, "password", password], timeout=40)
    if not ok:
        log(f"hotspot failed: {out}")
        return False
    run(["nmcli", "connection", "modify", AP_CON, "connection.autoconnect", "no"], timeout=20)
    redirect(True)
    with st.lock:
        st.mode, st.networks, st.last_page_hit = "setup", nets, time.time()
        st.ap_pass = password
        st.announce = True            # the next successful connection shows its IP
        st.publish()
    log(f"setup mode: hotspot {st.ssid_ap} on {AP_IP}")
    return True


def stop_ap():
    redirect(False)
    run(["nmcli", "connection", "down", AP_CON], timeout=20)
    run(["nmcli", "connection", "delete", AP_CON], timeout=20)


def save_and_connect(ssid, password):
    """Save the network (kept even if it fails now) and try to join it."""
    # Replace an older profile with the same name, then add it fresh.
    run(["nmcli", "connection", "delete", ssid], timeout=20)
    args = ["nmcli", "connection", "add", "type", "wifi", "ifname", IFACE, "con-name", ssid,
            "ssid", ssid, "connection.autoconnect", "yes"]
    if password:
        args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    ok, out = run(args, timeout=20)
    if not ok:
        return False, out
    return run(["nmcli", "connection", "up", ssid, "ifname", IFACE], timeout=60)


def wait_online(seconds):
    end = time.time() + seconds
    while time.time() < end:
        if online():
            return True
        time.sleep(3)
    return False


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
def controller(st):
    offline_since = time.time()       # counts from boot / service start
    while True:
        try:
            force = os.path.exists(FORCE_FILE)
            if force:
                os.remove(FORCE_FILE)

            if st.mode == "connected":
                if time.time() >= st.until:   # IP screen done -> normal MT4 screen
                    with st.lock:
                        st.mode, st.ip = "normal", ""
                        st.publish()

            elif st.mode == "normal":
                if online() and not force:
                    offline_since = None
                    if st.announce:           # rejoined a saved Wi-Fi after setup mode
                        announce_connected(st)
                    elif st.error:
                        with st.lock:
                            st.error = ""
                            st.publish()
                else:
                    offline_since = offline_since or time.time()
                    if force or time.time() - offline_since >= SETUP_AFTER:
                        if not start_ap(st):
                            time.sleep(20)

            elif st.mode == "setup":
                with st.lock:
                    pending, st.pending = st.pending, None
                if pending:
                    ssid, password = pending
                    with st.lock:
                        st.mode, st.target, st.error = "connecting", ssid, ""
                        st.publish()
                    log(f"connecting to {ssid!r}")
                    time.sleep(3)             # let the page reply reach the phone first
                    stop_ap()
                    ok, out = save_and_connect(ssid, password)
                    if ok and wait_online(20):
                        announce_connected(st, ssid)
                        offline_since = None
                    else:
                        log(f"could not connect to {ssid!r}: {out}")
                        with st.lock:
                            st.mode = "normal"
                            st.error = f"Could not join {ssid}. Check the password, or switch that Wi-Fi on - it is saved and retried."
                            st.publish()
                        offline_since = time.time() - SETUP_AFTER   # back to setup right away
                elif time.time() - st.last_page_hit > AP_SECONDS:
                    log("no one is using the setup page - retrying saved Wi-Fi")
                    stop_ap()
                    with st.lock:
                        st.mode = "normal"
                        st.publish()
                    offline_since = time.time() - SETUP_AFTER + RETRY_SECONDS
        except Exception as exc:
            log(f"controller error: {exc}")
        time.sleep(3)


# --------------------------------------------------------------------------
# Setup page
# --------------------------------------------------------------------------
PAGE = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MT4 Monitor - Wi-Fi</title>
<style>
:root{{color-scheme:light dark;--bg:#f4f6f8;--card:#fff;--ink:#14181c;--muted:#5d6670;--line:#d6dbe0;--accent:#1f6feb;--bad:#c62828}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1214;--card:#191d21;--ink:#eef1f4;--muted:#9aa4ad;--line:#2c3238;--accent:#4c8dff;--bad:#ef6c6c}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:440px;margin:0 auto;padding:20px 16px 40px}}h1{{font-size:21px;margin:4px 0 2px}}
p.sub{{color:var(--muted);margin:0 0 18px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 0;margin-bottom:16px}}
label.net{{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--line);cursor:pointer}}
label.net:last-child{{border-bottom:0}}label.net input{{width:20px;height:20px;accent-color:var(--accent)}}
.name{{flex:1;word-break:break-all}}.meta{{color:var(--muted);font-size:13px;white-space:nowrap}}
.field{{display:block;margin:0 0 14px}}.field span{{display:block;font-size:14px;color:var(--muted);margin-bottom:6px}}
input[type=text],input[type=password]{{width:100%;font:inherit;padding:12px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink)}}
button{{width:100%;font:inherit;font-weight:600;padding:14px;border:0;border-radius:10px;background:var(--accent);color:#fff}}
.err{{border:1px solid var(--bad);color:var(--bad);border-radius:10px;padding:12px;margin-bottom:16px}}
.empty{{padding:14px 16px;color:var(--muted)}}small{{color:var(--muted)}}
</style></head><body><main>
<h1>ตั้งค่า Wi-Fi ให้ MT4 Monitor</h1>
<p class="sub">เลือก Wi-Fi ที่ต้องการให้ Raspberry Pi ใช้ แล้วใส่รหัสผ่าน</p>
{error}
<form method="post" action="/connect">
<div class="card">{networks}</div>
<label class="field"><span>หรือพิมพ์ชื่อ Wi-Fi เอง (กรณีไม่อยู่ในรายการ)</span>
<input type="text" name="ssid_manual" maxlength="32" autocomplete="off" autocapitalize="none"></label>
<label class="field"><span>รหัสผ่าน Wi-Fi (เว้นว่างถ้าไม่มีรหัส)</span>
<input type="password" name="password" maxlength="63" autocomplete="off"></label>
<button type="submit">เชื่อมต่อ</button>
</form>
<p><small>หลังกดเชื่อมต่อ มือถือจะหลุดจาก {ap} เป็นเรื่องปกติ จอบน Pi จะบอกผล
ถ้าเป็นฮอตสปอตของมือถือเครื่องนี้ ให้ออกจาก {ap} แล้วเปิดฮอตสปอต — Pi จะลองเชื่อมเองภายในไม่กี่นาที</small></p>
</main></body></html>"""

DONE = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>MT4 Monitor - Wi-Fi</title>
<style>body{{margin:0;font:16px/1.5 system-ui,sans-serif;background:#f4f6f8;color:#14181c}}
@media (prefers-color-scheme:dark){{body{{background:#0f1214;color:#eef1f4}}}}
main{{max-width:440px;margin:0 auto;padding:28px 16px}}</style></head><body><main>
<h1 style="font-size:21px">กำลังเชื่อมต่อ {ssid}</h1>
<p>Pi กำลังออกจากโหมดตั้งค่า มือถือจะหลุดจาก {ap} ในไม่กี่วินาที</p>
<p>ดูผลที่จอ LCD: ถ้าขึ้นข้อมูล MT4 แสดงว่าสำเร็จ ถ้าขึ้น <b>WIFI SETUP</b> อีกครั้ง ให้เชื่อม {ap} แล้วลองใหม่</p>
</main></body></html>"""


def make_handler(st):
    class Portal(BaseHTTPRequestHandler):
        server_version = "MT4Setup"

        def log_message(self, *a):
            pass

        def _allowed(self):
            return st.mode == "setup" and self.client_address[0].startswith("10.42.0.")

        def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._allowed():
                return self._send(403, "Wi-Fi setup is only available on the setup hotspot.",
                                  "text/plain; charset=utf-8")
            st.last_page_hit = time.time()
            path = urllib.parse.urlsplit(self.path).path
            host = (self.headers.get("Host") or "").split(":")[0]
            if path != "/" or host not in (AP_IP, ""):
                # Phone captive-portal checks and any other site -> our page.
                return self._send(302, "", extra={"Location": f"http://{AP_IP}/"})
            self._send(200, render_page(st))

        def do_POST(self):
            if not self._allowed():
                return self._send(403, "Forbidden", "text/plain; charset=utf-8")
            st.last_page_hit = time.time()
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            ssid = (form.get("ssid_manual", [""])[0] or form.get("ssid", [""])[0]).strip()
            password = form.get("password", [""])[0]
            problem = None
            if not ssid or len(ssid.encode()) > 32:
                problem = "เลือกหรือพิมพ์ชื่อ Wi-Fi ก่อน"
            elif password and not 8 <= len(password) <= 63:
                problem = "รหัสผ่าน Wi-Fi ต้องยาว 8–63 ตัวอักษร (หรือเว้นว่างถ้าไม่มีรหัส)"
            elif any(ord(c) < 32 for c in ssid + password):
                problem = "ชื่อหรือรหัสมีตัวอักษรที่ใช้ไม่ได้"
            if problem:
                return self._send(200, render_page(st, problem))
            with st.lock:
                st.pending = (ssid, password)
            self._send(200, DONE.format(ssid=html.escape(ssid), ap=html.escape(st.ssid_ap)))

    return Portal


def render_page(st, problem=None):
    msg = problem or st.error
    error = f'<div class="err">{html.escape(msg)}</div>' if msg else ""
    rows = []
    for i, (ssid, sig, secured) in enumerate(st.networks):
        bars = "▂▄▆█"[: max(1, min(4, sig // 25 + 1))]
        rows.append(
            f'<label class="net"><input type="radio" name="ssid" value="{html.escape(ssid, True)}"'
            f'{" checked" if i == 0 else ""}><span class="name">{html.escape(ssid)}</span>'
            f'<span class="meta">{"🔒 " if secured else ""}{bars}</span></label>')
    networks = "".join(rows) or '<div class="empty">ไม่พบ Wi-Fi รอบตัว — พิมพ์ชื่อเองด้านล่าง</div>'
    return PAGE.format(error=error, networks=networks, ap=html.escape(st.ssid_ap))


def main():
    if not ENABLED:
        log("Wi-Fi setup mode is off (MT4MON_WIFI_SETUP=0)")
        while True:
            time.sleep(3600)
    st = State()
    st.publish()
    redirect(False)                   # clean up after a crash
    if not DRYRUN:
        run(["nmcli", "connection", "down", AP_CON], timeout=20)
    threading.Thread(target=controller, args=(st,), daemon=True).start()
    log(f"Wi-Fi setup watcher on {IFACE}; setup hotspot after {SETUP_AFTER}s offline; "
        f"password {'random each time' if RANDOM_PASS else 'fixed'}")
    ThreadingHTTPServer(("0.0.0.0", PORTAL_PORT), make_handler(st)).serve_forever()


if __name__ == "__main__":
    main()

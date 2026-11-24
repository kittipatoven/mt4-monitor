"""MT4 Trading Monitor - 3.5" 480x320 colour TFT pages (Pillow).

Renders the same data as the 1602 LCD into full-colour pages:
dashboard (big P/L, cards, 1-hour equity chart), orders table, alert pages,
Wi-Fi setup (with QR code when python3-qrcode is installed), waiting screen.

Output goes to a Linux framebuffer (/dev/fbN, RGB565) or, for previews, to PNG.
Read-only like the rest of the project: nothing here can trade.
"""
import glob
import os
import time

from PIL import Image, ImageDraw, ImageFont

W, H = 480, 320

# --- Theme ---------------------------------------------------------------
BG = (13, 17, 23)
CARD = (24, 31, 40)
LINE = (44, 54, 66)
TEXT = (232, 237, 242)
MUTED = (139, 152, 165)
GREEN = (46, 204, 113)
RED = (255, 92, 92)
AMBER = (245, 176, 65)
BLUE = (76, 154, 255)

# --- Fonts (DejaVu on the Pi, Arial/Segoe on Windows for previews) ---------
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts"]
_FONT_FILES = {
    "bold": ["DejaVuSans-Bold.ttf", "segoeuib.ttf", "arialbd.ttf"],
    "regular": ["DejaVuSans.ttf", "segoeui.ttf", "arial.ttf"],
    "mono": ["DejaVuSansMono-Bold.ttf", "consola.ttf"],
}
_font_cache = {}


def font(kind, size):
    key = (kind, size)
    if key not in _font_cache:
        for d in _FONT_DIRS:
            for name in _FONT_FILES[kind]:
                path = os.path.join(d, name)
                if os.path.exists(path):
                    _font_cache[key] = ImageFont.truetype(path, size)
                    break
            if key in _font_cache:
                break
        else:
            _font_cache[key] = ImageFont.load_default()
    return _font_cache[key]


# --- Helpers -------------------------------------------------------------
def money(v, decimals=2):
    return f"{v:,.{decimals}f}"


def signed(v, decimals=2):
    return ("+" if v >= 0 else "-") + money(abs(v), decimals)


def pl_colour(v):
    return GREEN if v > 0 else RED if v < 0 else TEXT


def text_w(d, s, f):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return r - l


def fit_font(d, s, kind, size, max_w, min_size=18):
    """Largest font size (<= size) that fits s into max_w pixels."""
    while size > min_size and text_w(d, s, font(kind, size)) > max_w:
        size -= 2
    return font(kind, size)


def card(d, box, radius=10, fill=CARD):
    d.rounded_rectangle(box, radius=radius, fill=fill)


def triangle(d, x, y, size, up, fill):
    if up:
        d.polygon([(x, y + size), (x + size, y + size), (x + size / 2, y)], fill=fill)
    else:
        d.polygon([(x, y), (x + size, y), (x + size / 2, y + size)], fill=fill)


def chip(d, x, y, label, ok, f=None):
    """Small status pill: green when ok, red when not. Returns its width."""
    f = f or font("bold", 13)
    colour = GREEN if ok else RED
    w = text_w(d, label, f) + 26
    d.rounded_rectangle((x, y, x + w, y + 22), radius=11, fill=(colour[0] // 5, colour[1] // 5, colour[2] // 5))
    d.ellipse((x + 8, y + 7, x + 16, y + 15), fill=colour)
    d.text((x + 20, y + 3), label, font=f, fill=colour)
    return w


def page_dots(d, index, count):
    if count < 2:
        return
    x0 = W // 2 - (count * 14) // 2
    for i in range(count):
        c = TEXT if i == index else LINE
        d.ellipse((x0 + i * 14, H - 10, x0 + i * 14 + 6, H - 4), fill=c)


def new_page():
    im = Image.new("RGB", (W, H), BG)
    return im, ImageDraw.Draw(im)


# --- Status bar ----------------------------------------------------------
def status_bar(d, data, age, tick):
    acc = data["account"]
    term = data.get("terminal", {})
    d.rectangle((0, 0, W, 34), fill=CARD)
    d.text((12, 8), "MT4 MONITOR", font=font("bold", 15), fill=TEXT)
    login = acc.get("login")
    if login is not None:
        d.text((128, 10), f"#{login}", font=font("regular", 13), fill=MUTED)
    x = W - 12
    clock = time.strftime("%H:%M")
    cw = text_w(d, clock, font("bold", 14))
    d.text((x - cw, 9), clock, font=font("bold", 14), fill=MUTED)
    x -= cw + 10
    for label, ok in (("AUTO", term.get("trade_allowed") is not False),
                      ("BROKER", term.get("connected") is not False)):
        w = text_w(d, label, font("bold", 13)) + 26
        x -= w
        chip(d, x, 6, label, ok)
        x -= 6
    live = f"LIVE {age}s"
    w = text_w(d, live, font("bold", 13)) + 26
    x -= w
    # Blinking dot = data is arriving (same meaning as the heart on the 1602).
    d.rounded_rectangle((x, 6, x + w, 28), radius=11, fill=(9, 41, 23))
    if tick % 2 == 0:
        d.ellipse((x + 8, 13, x + 16, 21), fill=GREEN)
    d.text((x + 20, 9), live, font=font("bold", 13), fill=GREEN)


# --- Equity chart --------------------------------------------------------
def equity_chart(d, box, points):
    """Line + soft fill of equity samples (list of floats, oldest first)."""
    x0, y0, x1, y1 = box
    vals = [p for p in points if p is not None]
    if len(vals) < 2:
        d.text((x0, (y0 + y1) // 2 - 8), "collecting data...", font=font("regular", 13), fill=MUTED)
        return
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    n = len(points)
    xy = []
    for i, p in enumerate(points):
        if p is None:
            continue
        x = x0 + (x1 - x0) * i / (n - 1)
        y = y1 - (y1 - y0) * (p - lo) / span
        xy.append((x, y))
    colour = GREEN if vals[-1] >= vals[0] else RED
    fill = (colour[0] // 6, colour[1] // 6, colour[2] // 6)
    d.polygon(xy + [(xy[-1][0], y1), (xy[0][0], y1)], fill=fill)
    d.line(xy, fill=colour, width=2)
    d.ellipse((xy[-1][0] - 3, xy[-1][1] - 3, xy[-1][0] + 3, xy[-1][1] + 3), fill=colour)


# --- Pages ---------------------------------------------------------------
def render_dashboard(data, age, tick, trend=0, chart=None, index=0, count=2):
    """trend: +1 rising / -1 falling / 0 flat (vs 30 s ago). chart: equity samples."""
    im, d = new_page()
    status_bar(d, data, age, tick)
    acc = data["account"]
    pl, bal, eq = acc["profit"], acc["balance"], acc["equity"]
    orders = data.get("orders", [])
    market = [o for o in orders if o["type"] in (0, 1)]
    lots = sum(o["lots"] for o in market)

    # Big floating P/L
    d.text((16, 44), "FLOATING P/L", font=font("bold", 13), fill=MUTED)
    big = signed(pl)
    bf = fit_font(d, big, "bold", 64, 330)
    d.text((16, 58), big, font=bf, fill=pl_colour(pl))
    bx = 16 + text_w(d, big, bf) + 12
    if trend:
        triangle(d, bx, 82, 22, trend > 0, GREEN if trend > 0 else RED)
    pct = pl / bal * 100 if bal else 0.0
    info = f"{pct:+.2f}% of balance   ·   {len(market)} order{'s' if len(market) != 1 else ''}   ·   {lots:.2f} lots"
    d.text((16, 136), info, font=font("regular", 14), fill=MUTED)

    # Cards: balance / equity / free margin
    margin = acc.get("margin", 0.0)
    cards = [("BALANCE", money(bal)), ("EQUITY", money(eq)),
             ("FREE MARGIN" if margin <= 0 else "MARGIN USED",
              money(acc.get("free_margin", 0.0)) if margin <= 0 else f"{margin / eq * 100:.2f}%" if eq else "-")]
    cw = (W - 16 * 2 - 8 * 2) // 3
    for i, (label, value) in enumerate(cards):
        x = 16 + i * (cw + 8)
        card(d, (x, 164, x + cw, 222))
        d.text((x + 12, 172), label, font=font("bold", 11), fill=MUTED)
        d.text((x + 12, 190), value, font=fit_font(d, value, "bold", 20, cw - 24, 12), fill=TEXT)

    # 1-hour equity chart
    card(d, (16, 230, W - 16, 304))
    d.text((28, 236), "EQUITY  1H", font=font("bold", 11), fill=MUTED)
    vals = [p for p in (chart or []) if p is not None]
    if len(vals) >= 2:
        ch = vals[-1] - vals[0]
        s = signed(ch)
        d.text((W - 28 - text_w(d, s, font("bold", 13)), 234), s, font=font("bold", 13), fill=pl_colour(ch))
    equity_chart(d, (28, 254, W - 28, 296), chart or [])
    page_dots(d, index, count)
    return im


ORDER_TYPES = {0: "BUY", 1: "SELL", 2: "BUY LMT", 3: "SELL LMT", 4: "BUY STP", 5: "SELL STP"}


def render_orders(data, age, tick, index=1, count=2):
    im, d = new_page()
    status_bar(d, data, age, tick)
    orders = data.get("orders", [])
    d.text((16, 44), "OPEN ORDERS", font=font("bold", 13), fill=MUTED)
    total = sum(o["profit"] for o in orders)
    t = signed(total)
    d.text((W - 16 - text_w(d, t, font("bold", 16)), 42), t, font=font("bold", 16), fill=pl_colour(total))
    if not orders:
        d.text((16, 140), "No open orders", font=font("bold", 26), fill=MUTED)
        page_dots(d, index, count)
        return im
    cols = (16, 150, 250, 330)
    y = 70
    for label, x in zip(("SYMBOL", "TYPE", "LOTS"), cols):
        d.text((x, y), label, font=font("bold", 11), fill=MUTED)
    d.text((W - 24 - text_w(d, "P/L", font("bold", 11)), y), "P/L", font=font("bold", 11), fill=MUTED)
    y += 18
    rows = orders[:6]
    for o in rows:
        card(d, (12, y, W - 12, y + 30), radius=8)
        d.text((cols[0] + 6, y + 6), str(o["symbol"])[:10], font=font("bold", 15), fill=TEXT)
        typ = ORDER_TYPES.get(o["type"], "?")
        buy = o["type"] in (0, 2, 4)
        tf = font("bold", 12)
        tw = text_w(d, typ, tf) + 14
        c = GREEN if buy else RED
        d.rounded_rectangle((cols[1], y + 6, cols[1] + tw, y + 24), radius=9, fill=(c[0] // 5, c[1] // 5, c[2] // 5))
        d.text((cols[1] + 7, y + 8), typ, font=tf, fill=c)
        d.text((cols[2], y + 6), f"{o['lots']:.2f}", font=font("regular", 15), fill=TEXT)
        p = signed(o["profit"])
        pf = font("bold", 15)
        d.text((W - 24 - text_w(d, p, pf), y + 6), p, font=pf, fill=pl_colour(o["profit"]))
        y += 36
    if len(orders) > len(rows):
        d.text((16, y + 2), f"+{len(orders) - len(rows)} more", font=font("regular", 13), fill=MUTED)
    page_dots(d, index, count)
    return im


def render_alert(title, detail, sub="", level="critical"):
    """Full-screen alert (no data / broker / AutoTrading / drawdown)."""
    colour = RED if level == "critical" else AMBER
    im = Image.new("RGB", (W, H), (colour[0] // 4, colour[1] // 6, colour[2] // 6))
    d = ImageDraw.Draw(im)
    d.ellipse((W // 2 - 34, 40, W // 2 + 34, 108), fill=colour)
    ef = font("bold", 52)
    d.text((W // 2 - text_w(d, "!", ef) // 2, 44), "!", font=ef, fill=BG)
    tf = fit_font(d, title, "bold", 36, W - 40)
    d.text((W // 2 - text_w(d, title, tf) // 2, 128), title, font=tf, fill=TEXT)
    df = fit_font(d, detail, "regular", 20, W - 40, 12)
    d.text((W // 2 - text_w(d, detail, df) // 2, 182), detail, font=df, fill=TEXT)
    if sub:
        sf = font("regular", 15)
        d.text((W // 2 - text_w(d, sub, sf) // 2, 226), sub, font=sf, fill=MUTED)
    return im


def _qr(ws, size):
    """QR code that joins the setup hotspot (needs python3-qrcode); None if unavailable."""
    try:
        import qrcode
    except ImportError:
        return None
    payload = f"WIFI:T:WPA;S:{ws.get('ap_ssid', '')};P:{ws.get('ap_pass', '')};;"
    q = qrcode.QRCode(border=1, box_size=4)
    q.add_data(payload)
    q.make(fit=True)
    return q.make_image(fill_color="black", back_color="white").convert("RGB").resize((size, size), Image.NEAREST)


def render_wifi(ws, tick=0):
    """Wi-Fi setup / connecting / connected screens from /run/mt4-wifi/state.json."""
    im, d = new_page()
    mode = ws.get("mode")
    if mode == "connected":
        d.ellipse((W // 2 - 36, 46, W // 2 + 36, 118), fill=GREEN)
        d.line([(W // 2 - 16, 82), (W // 2 - 4, 96), (W // 2 + 18, 68)], fill=BG, width=8)
        t = "WI-FI CONNECTED"
        d.text((W // 2 - text_w(d, t, font("bold", 30)) // 2, 136), t, font=font("bold", 30), fill=TEXT)
        net = str(ws.get("target") or "")
        d.text((W // 2 - text_w(d, net, font("regular", 18)) // 2, 180), net, font=font("regular", 18), fill=MUTED)
        ip = "IP  " + str(ws.get("ip") or "no IP yet")
        d.text((W // 2 - text_w(d, ip, font("mono", 30)) // 2, 222), ip, font=font("mono", 30), fill=GREEN)
        return im
    if mode == "connecting":
        t = "CONNECTING..."
        d.text((W // 2 - text_w(d, t, font("bold", 32)) // 2, 110), t, font=font("bold", 32), fill=TEXT)
        net = str(ws.get("target") or "")
        d.text((W // 2 - text_w(d, net, font("regular", 20)) // 2, 160), net, font=font("regular", 20), fill=MUTED)
        dots = "●" * (tick % 4 + 1)
        d.text((W // 2 - 30, 200), dots, font=font("regular", 20), fill=BLUE)
        return im

    # setup mode
    d.rectangle((0, 0, W, 40), fill=BLUE)
    d.text((14, 9), "WI-FI SETUP", font=font("bold", 20), fill=BG)
    qr = _qr(ws, 150)
    tx = 16
    right = W - 16 - (166 if qr else 0)
    d.text((tx, 54), "1  Join this Wi-Fi on your phone", font=font("bold", 14), fill=MUTED)
    ssid = str(ws.get("ap_ssid", ""))
    d.text((tx, 74), ssid, font=fit_font(d, ssid, "bold", 26, right - tx), fill=TEXT)
    d.text((tx, 114), "Password", font=font("bold", 14), fill=MUTED)
    pw = str(ws.get("ap_pass", ""))
    d.text((tx, 132), pw, font=fit_font(d, pw, "mono", 34, right - tx), fill=AMBER)
    d.text((tx, 186), "2  The setup page opens by itself", font=font("bold", 14), fill=MUTED)
    d.text((tx, 206), "or open  " + str(ws.get("url", "http://10.42.0.1")).replace("http://", ""),
           font=font("bold", 20), fill=TEXT)
    d.text((tx, 244), "3  Pick your Wi-Fi + password, tap Connect", font=font("bold", 14), fill=MUTED)
    if ws.get("error"):
        d.text((tx, 274), "Last try failed - check the password", font=font("bold", 14), fill=RED)
    if qr:
        x = W - 16 - 158
        d.rounded_rectangle((x - 4, 54, x + 154, 212), radius=8, fill=(255, 255, 255))
        im.paste(qr, (x, 58))
        d.text((x + 8, 220), "scan to join", font=font("regular", 13), fill=MUTED)
    return im


def render_message(title, sub="", colour=TEXT):
    """Waiting for MT4 / starting / new account."""
    im, d = new_page()
    tf = fit_font(d, title, "bold", 34, W - 40)
    d.text((W // 2 - text_w(d, title, tf) // 2, 118), title, font=tf, fill=colour)
    if sub:
        sf = font("regular", 18)
        d.text((W // 2 - text_w(d, sub, sf) // 2, 170), sub, font=sf, fill=MUTED)
    return im


# --- Touch: a tap anywhere = next page -----------------------------------
def find_touch_device():
    """/dev/input/eventN of the touch controller (ADS7846/XPT2046), or None."""
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    for b in blocks:
        if any(k in b for k in ("ADS7846", "XPT2046", "Touchscreen", "touchscreen")):
            for line in b.splitlines():
                if line.startswith("H: Handlers="):
                    for h in line.split("=", 1)[1].split():
                        if h.startswith("event"):
                            return "/dev/input/" + h
    return None


def watch_touch(on_tap, stop_event, device=None):
    """Call on_tap() once per finger-down (BTN_TOUCH press). Runs until stop_event."""
    import select
    import struct
    fmt = "llHHi"                       # struct input_event (native long size)
    size = struct.calcsize(fmt)
    EV_KEY, BTN_TOUCH = 0x01, 0x14a
    last = 0.0
    while not stop_event.is_set():
        dev = device or find_touch_device()
        if not dev:
            stop_event.wait(10)
            continue
        try:
            with open(dev, "rb", buffering=0) as f:
                while not stop_event.is_set():
                    r, _, _ = select.select([f], [], [], 1.0)
                    if not r:
                        continue
                    data = f.read(size)
                    if len(data) < size:
                        break
                    _, _, typ, code, value = struct.unpack(fmt, data)
                    if typ == EV_KEY and code == BTN_TOUCH and value == 1:
                        now = time.monotonic()
                        if now - last > 0.4:          # ignore bounce
                            last = now
                            on_tap()
        except OSError:
            stop_event.wait(5)


# --- Output: Linux framebuffer -------------------------------------------
def find_fb(preferred=None):
    """The TFT's framebuffer: preferred path, else one whose name is not the HDMI one."""
    if preferred:
        return preferred
    for path in sorted(glob.glob("/sys/class/graphics/fb*")):
        try:
            name = open(os.path.join(path, "name")).read().strip().lower()
        except OSError:
            continue
        if any(k in name for k in ("ili", "fb_", "mipi", "st77", "hx8357", "tft")):
            return "/dev/" + os.path.basename(path)
    return "/dev/fb1" if os.path.exists("/dev/fb1") else "/dev/fb0"


def rgb565(im):
    """Image -> RGB565 little-endian bytes, using Pillow channel ops only.

    (Pillow 11 has no 'BGR;16' raw packer and numpy may be missing.)
    pixel = RRRRRGGG GGGBBBBB -> low byte GGGBBBBB, high byte RRRRRGGG
    """
    from PIL import ImageChops
    r, g, b = im.convert("RGB").split()
    low = ImageChops.add(g.point(lambda x: ((x >> 2) & 0x07) << 5), b.point(lambda x: x >> 3))
    high = ImageChops.add(r.point(lambda x: (x >> 3) << 3), g.point(lambda x: x >> 5))
    return Image.merge("LA", (low, high)).tobytes()


class FramebufferOutput:
    """Write Pillow images to /dev/fbN (RGB565 or 32-bit, read from sysfs)."""

    def __init__(self, device=None, rotate=0):
        self.device = find_fb(device)
        base = "/sys/class/graphics/" + os.path.basename(self.device)
        self.bpp = int(open(base + "/bits_per_pixel").read().strip())
        w, h = open(base + "/virtual_size").read().strip().split(",")
        self.size = (int(w), int(h))
        self.rotate = rotate
        self._last = None

    def show(self, im):
        if self.rotate:
            im = im.rotate(self.rotate, expand=True)
        if im.size != self.size:
            im = im.resize(self.size)
        if self.bpp == 16:
            data = rgb565(im)
        else:
            data = im.convert("RGBA").tobytes("raw", "BGRA")
        if data == self._last:
            return
        with open(self.device, "wb") as fb:
            fb.write(data)
        self._last = data


class PngOutput:
    """Preview: save each frame to a PNG file (PC testing)."""

    def __init__(self, path):
        self.path = path

    def show(self, im):
        im.save(self.path)

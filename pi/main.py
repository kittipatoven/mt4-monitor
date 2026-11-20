"""MT4 Trading Monitor V1 - Raspberry Pi side (read-only).

MonitorEA (on the Windows VPS) POSTs a JSON snapshot to /api/update
over Tailscale. This service keeps the latest snapshot and rotates
pages on the 16x2 LCD.

Nothing here can place, modify or close orders.
"""
import bisect
import collections
import hmac
import json
import logging
import threading
import time

from flask import Flask, jsonify, request

import config
from lcd import (BIG_A, BIG_B, BIG_C, CHECK, CROSS, DOT, DOWN, FULL, HALF, HEART, SPARK, TDN,
                 TUP, UP, ConsoleLcd, I2CLcd)

log = logging.getLogger("mt4mon")

ORDER_TYPES = {0: "BUY", 1: "SELL", 2: "BLMT", 3: "SLMT", 4: "BSTP", 5: "SSTP"}

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_state = {"data": None, "received_at": None, "updates": 0}
# (time, equity, P/L) samples for the sparkline and trend arrow; ~2 h at one per 5 s.
_history = collections.deque(maxlen=1500)


def set_snapshot(data, now=None):
    now = time.monotonic() if now is None else now
    with _state_lock:
        _state["data"] = data
        _state["received_at"] = now
        _state["updates"] += 1
        acc = data["account"]
        _history.append((now, acc["equity"], acc["profit"]))


def get_snapshot():
    with _state_lock:
        return _state["data"], _state["received_at"], _state["updates"]


def get_history():
    with _state_lock:
        return list(_history)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError
    return float(value)


def validate(payload):
    """Return (clean_dict, None) or (None, error_message)."""
    if not isinstance(payload, dict):
        return None, "payload must be a JSON object"
    acc = payload.get("account")
    if not isinstance(acc, dict):
        return None, "missing 'account'"
    try:
        for key in ("balance", "equity"):
            acc[key] = _num(acc.get(key))
        for key in ("margin", "free_margin", "margin_level", "profit"):
            acc[key] = _num(acc.get(key, 0))
    except ValueError:
        return None, "account numbers invalid"

    orders = payload.get("orders", [])
    if not isinstance(orders, list):
        return None, "'orders' must be a list"
    clean_orders = []
    for o in orders:
        if not isinstance(o, dict):
            return None, "order must be an object"
        try:
            clean_orders.append({
                "ticket": int(o.get("ticket", 0)),
                "symbol": str(o.get("symbol", "?")),
                "type": int(o.get("type", -1)),
                "lots": _num(o.get("lots", 0)),
                "profit": _num(o.get("profit", 0)),
                "magic": int(o.get("magic", 0)),
            })
        except (TypeError, ValueError):
            return None, "order fields invalid"
    payload["orders"] = clean_orders

    for key in ("terminal", "capybara", "monitor"):
        if not isinstance(payload.get(key, {}), dict):
            return None, f"'{key}' must be an object"
        payload.setdefault(key, {})
    return payload, None


# ---------------------------------------------------------------------------
# Page building (pure function -> easy to test without hardware)
# ---------------------------------------------------------------------------
def money(v, width):
    """Fit a number into `width` chars: 2 decimals, then 0, then k/M."""
    for text in (f"{v:,.2f}", f"{v:.2f}", f"{v:.0f}"):
        if len(text) <= width:
            return text
    for div, suffix in ((1e3, "k"), (1e6, "M")):
        text = f"{v / div:.1f}{suffix}"
        if len(text) <= width:
            return text
    return "#" * width


def signed(v, width):
    if v < 0:
        return money(v, width)
    return "+" + money(v, width - 1)


def row(label, value_text):
    """Label on the left, value right-aligned in 16 columns."""
    space = 16 - len(label)
    return label + value_text.rjust(space)[-space:]


def arrow(v):
    return UP if v >= 0 else DOWN


def mark(v):
    return CHECK if v else (CROSS if v is not None else "?")


def bar(frac, cells):
    """Gauge with half-cell steps: FULL / HALF / DOT(empty)."""
    frac = max(0.0, min(1.0, frac))
    halves = round(frac * cells * 2)
    out = FULL * (halves // 2) + (HALF if halves % 2 else "")
    return out + DOT * (cells - len(out))


def pct_text(p):
    if p >= 99.5:
        return "100%"
    return f"{p:.2f}%" if p < 10 else f"{p:.1f}%"


# --- Big digits: 3 columns x 2 rows each (F = full block, A/B/C = stripes) ---
_F, _S = FULL, " "
BIG_DIGITS = {
    "0": (_F + BIG_A + _F, _F + BIG_B + _F),
    "1": (BIG_A + _F + _S, BIG_B + _F + BIG_B),
    "2": (BIG_C + BIG_C + _F, _F + BIG_B + BIG_B),
    "3": (BIG_C + BIG_C + _F, BIG_B + BIG_B + _F),
    "4": (_F + BIG_B + _F, _S + _S + _F),
    "5": (_F + BIG_C + BIG_C, BIG_B + BIG_B + _F),
    "6": (_F + BIG_C + BIG_C, _F + BIG_B + _F),
    "7": (BIG_A + BIG_A + _F, _S + _S + _F),
    "8": (_F + BIG_C + _F, _F + BIG_B + _F),
    "9": (_F + BIG_C + _F, BIG_B + BIG_B + _F),
}


def big_pl(pl, beat):
    """P/L as big 2-row digits: arrow + heart on the left, decimals on the right."""
    a = abs(pl)
    whole, dec = f"{a:.2f}".split(".")
    tail1, tail2 = "P/L", "." + dec
    if len(whole) > 4:                       # 10,000+ -> thousands with a small 'k'
        whole, tail2 = str(int(round(a / 1000)))[-4:], "  k"
    top = " ".join(BIG_DIGITS[d][0] for d in whole)
    bottom = " ".join(BIG_DIGITS[d][1] for d in whole)
    if len(whole) == 4:                      # 15 columns: no room for decimals
        return arrow(pl) + top, beat + bottom
    pad = " " * (16 - 1 - len(top) - 3)
    return arrow(pl) + pad + top + tail1, beat + pad + bottom + tail2


def _value_at(times, values, t):
    """Last value recorded at or before time t (None if none yet)."""
    i = bisect.bisect_right(times, t)
    return values[i - 1] if i else None


def trend_char(hist, now, pl, window=30):
    """Thin arrow: is P/L higher or lower than `window` seconds ago?"""
    times = [h[0] for h in hist]
    old = _value_at(times, [h[2] for h in hist], now - window)
    if old is None or abs(pl - old) < 0.005:
        return " "
    return TUP if pl > old else TDN


def sparkline(hist, now, cells=16, span=3600):
    """Equity over the last `span` seconds as `cells` bars. Returns (bars, change)."""
    times, eqs = [h[0] for h in hist], [h[1] for h in hist]
    step = span / cells
    pts = [_value_at(times, eqs, now - span + step * (i + 1)) for i in range(cells)]
    vals = [v for v in pts if v is not None]
    if not vals:
        return " " * cells, None
    if len(vals) < 2:                        # just started: nothing to compare yet
        return "".join(" " if v is None else SPARK[3] for v in pts), None
    lo, hi = min(vals), max(vals)
    out = []
    for v in pts:
        if v is None:
            out.append(" ")
        elif hi - lo < 0.01:
            out.append(SPARK[3])             # flat: a level line in the middle
        else:
            lvl = 1 + round((v - lo) / (hi - lo) * 7)
            out.append(FULL if lvl >= 8 else SPARK[lvl - 1])
    return "".join(out), pts[-1] - vals[0]


def build_pages(data, received_at, now, tick=0, hist=()):
    """Return (pages, alert). Each page is (line1, line2, seconds)."""
    H, P = config.HOME_SECONDS, config.PAGE_SECONDS
    if data is None:
        return [("MT4 MONITOR V1", "Waiting for MT4", P)], False

    age = max(0, int(now - received_at))
    acc = data["account"]
    term = data.get("terminal", {})
    capy = data.get("capybara", {})
    orders = data["orders"]
    cur = str(acc.get("currency", ""))[:3]
    bal, eq, pl = acc["balance"], acc["equity"], acc["profit"]

    if age > config.STALE_SECONDS:
        # Data can no longer be trusted: say so first, then show last values.
        return [
            ("!! MT4 NO DATA", row("last ", f"{age}s ago"), P),
            ("(OLD) BAL " + money(bal, 6), "(OLD) EQ  " + money(eq, 6), P),
        ], True

    alerts = []
    broker = term.get("connected")
    if broker is False:
        alerts.append(("!! BROKER", "DISCONNECTED", P))
    auto = term.get("trade_allowed")
    if auto is False:
        alerts.append(("!! AUTOTRADING", "IS OFF", P))
    dd = -pl / bal * 100 if bal > 0 else 0.0
    if config.DD_ALERT_PCT > 0 and dd >= config.DD_ALERT_PCT:
        alerts.append(("!! DRAWDOWN", row(f"-{dd:.1f}% ", money(pl, 16 - len(f"-{dd:.1f}% "))), P))

    beat = HEART if tick % 2 == 0 else " "

    if config.SINGLE_PAGE:
        # Everything that matters on one screen; alerts alternate with it.
        n_market = sum(1 for o in orders if o["type"] in (0, 1))
        ok = mark(broker is not False and auto is not False)
        right = f"ORD {n_market}{beat}"
        room = 16 - len(right) - 1          # keep one space between the two
        trend = trend_char(hist, now, pl)
        detail = (row(arrow(pl) + signed(pl, room - 2) + trend, right),
                  "EQ " + money(eq, 11).rjust(11) + " " + ok, P)
        big = (*big_pl(pl, beat), config.BIG_SECONDS)
        pages = [big, detail]
        if config.SPARK_SECONDS > 0:          # optional 1-hour equity sparkline page
            bars, change = sparkline(hist, now)
            label = "EQ 1H" if change is None else row("EQ 1H ", arrow(change) + signed(change, 9))
            pages.append((label, bars, config.SPARK_SECONDS))
        return alerts + pages, bool(alerts)

    # Home: P/L with direction arrow, blinking heart = data is live, equity.
    left = f"{arrow(pl)} {signed(pl, 9)}"
    pages = [(row(left, f"{beat}{age}s"), row("EQ ", money(eq, 13)), H)]

    pages.append((row("BAL ", money(bal, 12)), row("FREE ", money(acc["free_margin"], 11)), P))

    used = acc["margin"] / eq * 100 if eq > 0 else 0.0
    pages.append((row("MARGIN ", money(acc["margin"], 9)),
                  "USE" + bar(used / 100, 7) + pct_text(used).rjust(6), P))

    pages.append((row(f"LINK {mark(True)}", f"{age}s {cur}"),
                  f"BROKER{mark(broker)}  AUTO{mark(term.get('trade_allowed'))}", P))

    # Capybara/CapyTrend: never claimed as RUNNING - only magic-number evidence.
    magic = capy.get("magic_filter", -1)
    if isinstance(magic, int) and magic >= 0:
        n = capy.get("magic_orders", 0)
        p = float(capy.get("magic_profit", 0.0))
        lbl = f"ORD {n} "
        pages.append(("CAPY UNVERIFIED", row(lbl, arrow(p) + signed(p, 15 - len(lbl))), P))

    # Orders: only when there are any.
    if orders:
        market = [o for o in orders if o["type"] in (0, 1)]
        buys = sum(1 for o in market if o["type"] == 0)
        lots = sum(o["lots"] for o in market)
        total = sum(o["profit"] for o in orders)
        lbl = f"LOT {lots:.2f} "
        pages.append((f"ORD {len(market)} B{buys} S{len(market) - buys} P{len(orders) - len(market)}",
                      row(lbl, arrow(total) + signed(total, 15 - len(lbl))), P))
        for o in orders[: config.MAX_ORDER_PAGES]:
            typ = ORDER_TYPES.get(o["type"], "?")
            lots_txt = f"{o['lots']:.2f}"
            sym_room = 16 - len(typ) - len(lots_txt) - 2
            lbl = f"{o['ticket']} "
            pages.append((row(f"{o['symbol'][:sym_room]} {typ} ", lots_txt),
                          row(lbl, arrow(o["profit"]) + signed(o["profit"], 15 - len(lbl))), P))
        if len(orders) > config.MAX_ORDER_PAGES:
            pages.append(("ORDERS", f"+{len(orders) - config.MAX_ORDER_PAGES} more not shown", P))

    return alerts + pages, bool(alerts)


def in_night(hour):
    s, e = config.NIGHT_START, config.NIGHT_END
    if s < 0 or e < 0 or s == e:
        return False
    return s <= hour < e if s < e else (hour >= s or hour < e)


def backlight_on(alert, tick, hour):
    if alert:
        return tick % 2 == 0          # blink to get attention, day or night
    return not in_night(hour)


# ---------------------------------------------------------------------------
# LCD worker
# ---------------------------------------------------------------------------
def make_lcd():
    if not config.LCD_ENABLED:
        return ConsoleLcd()
    return I2CLcd(bus=config.I2C_BUS, address=config.LCD_ADDRESS)


WIFI_STATE_FILE = "/run/mt4-wifi/state.json"   # written by wifi_setup.py


def read_wifi_state():
    try:
        with open(WIFI_STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def wifi_pages(ws):
    """LCD pages while the Pi is in Wi-Fi setup mode (None = show MT4 data)."""
    mode = ws.get("mode")
    P = config.PAGE_SECONDS
    if mode == "setup":
        pages = [
            ("WIFI SETUP MODE", "Join on phone:", P),
            (str(ws.get("ap_ssid", ""))[:16], "PASS " + str(ws.get("ap_pass", ""))[:11], P),
            ("THEN OPEN", str(ws.get("url", "http://10.42.0.1"))[7:23] or "10.42.0.1", P),
        ]
        if ws.get("error"):
            pages.insert(0, ("WIFI FAILED", "Try again", P))
        return pages
    if mode == "connecting":
        return [("WIFI CONNECTING", str(ws.get("target", ""))[:16], P)]
    if mode == "connected" and time.time() < float(ws.get("until") or 0):
        # Shown once for 10 s right after joining a Wi-Fi through setup mode.
        ip = str(ws.get("ip") or "no IP yet")
        return [(CHECK + " WIFI CONNECTED", ("IP " + ip) if len(ip) <= 13 else ip[:16], 10)]
    return None


def boot_animation(lcd, stop_event):
    """Title + a loading bar that fills left to right (~1.5 s)."""
    title = "MT4 MONITOR V1".center(16)
    for i in range(17):
        lcd.show(title, FULL * i)
        stop_event.wait(0.08)
    lcd.show(title, "Ready".center(16))
    stop_event.wait(0.6)


def lcd_loop(stop_event):
    """Ticks once a second: heart blink, live age, per-page dwell, backlight."""
    lcd = None
    index, page_started, tick = 0, 0.0, 0
    while not stop_event.is_set():
        try:
            if lcd is None:
                lcd = make_lcd()
                boot_animation(lcd, stop_event)
                page_started = time.monotonic()
            now = time.monotonic()
            data, received_at, _ = get_snapshot()
            pages = wifi_pages(read_wifi_state())
            setup_screen = bool(pages)
            if setup_screen:
                alert = False             # setup instructions: steady light, no blinking
            else:
                pages, alert = build_pages(data, received_at, now, tick, get_history())
            if index >= len(pages):
                index, page_started = 0, now
            elif now - page_started >= pages[index][2]:
                index, page_started = (index + 1) % len(pages), now
            line1, line2, _ = pages[index]
            lcd.show(line1, line2)
            lcd.set_backlight(setup_screen or backlight_on(alert, tick, time.localtime().tm_hour))
            tick += 1
        except OSError as exc:  # I2C glitch / loose wire: retry, don't die
            log.warning("LCD error: %s (retrying)", exc)
            if lcd is not None:
                lcd.close()
            lcd = None
        except Exception:
            log.exception("page render failed")
        stop_event.wait(1)
    if lcd is not None:
        lcd.set_backlight(True)
        lcd.show("MT4 MONITOR V1", "Stopped")
        lcd.close()


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_PAYLOAD_BYTES


def _authorized():
    sent = request.headers.get("X-API-Key", "")
    return bool(config.API_KEY) and hmac.compare_digest(sent, config.API_KEY)


@app.post("/api/update")
def api_update():
    if not _authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    payload = request.get_json(silent=True)
    clean, err = validate(payload)
    if err:
        return jsonify(ok=False, error=err), 400
    set_snapshot(clean)
    return jsonify(ok=True)


@app.get("/api/status")
def api_status():
    if not _authorized():
        return jsonify(ok=False, error="unauthorized"), 401
    data, received_at, updates = get_snapshot()
    age = None if received_at is None else round(time.monotonic() - received_at, 1)
    return jsonify(ok=True, age_seconds=age, updates=updates, data=data)


@app.get("/health")
def health():
    _, received_at, updates = get_snapshot()
    age = None if received_at is None else round(time.monotonic() - received_at, 1)
    stale = age is None or age > config.STALE_SECONDS
    return jsonify(ok=True, mt4_age_seconds=age, mt4_stale=stale, updates=updates)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not config.API_KEY:
        raise SystemExit("MT4MON_API_KEY is not set - refusing to start without an API key.")

    stop = threading.Event()
    worker = threading.Thread(target=lcd_loop, args=(stop,), daemon=True)
    worker.start()

    from waitress import serve

    log.info("Listening on %s:%s (LCD %s)", config.HOST, config.PORT,
             f"0x{config.LCD_ADDRESS:02X}" if config.LCD_ENABLED else "console")
    try:
        serve(app, host=config.HOST, port=config.PORT, threads=4)
    finally:
        stop.set()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()

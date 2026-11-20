"""MT4 Trading Monitor V1 - configuration.

All values can be overridden with environment variables
(the systemd service loads them from /etc/mt4-monitor.env).
"""
import os


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw, 0)  # accepts "39" or "0x27"


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- API ---------------------------------------------------------------
# Shared secret that MonitorEA must send in the X-API-Key header.
API_KEY = os.environ.get("MT4MON_API_KEY", "")
HOST = os.environ.get("MT4MON_HOST", "0.0.0.0")
PORT = _env_int("MT4MON_PORT", 80)  # MT4 WebRequest allows only 80/443
MAX_PAYLOAD_BYTES = 64 * 1024

# --- LCD ---------------------------------------------------------------
LCD_ENABLED = _env_bool("MT4MON_LCD_ENABLED", True)  # False = print to console
I2C_BUS = _env_int("MT4MON_I2C_BUS", 1)
LCD_ADDRESS = _env_int("MT4MON_LCD_ADDRESS", 0x27)  # 0x27 or 0x3F
LCD_COLS = 16
LCD_ROWS = 2

# --- Display behaviour -------------------------------------------------
# One fixed page (P/L, orders, equity, status); alert pages only when needed.
SINGLE_PAGE = _env_bool("MT4MON_SINGLE_PAGE", True)
HOME_SECONDS = _env_int("MT4MON_HOME_SECONDS", 8)   # home page (P/L + equity)
BIG_SECONDS = _env_int("MT4MON_BIG_SECONDS", 6)     # single-page mode: big P/L digits
SPARK_SECONDS = _env_int("MT4MON_SPARK_SECONDS", 0) # 1-hour equity sparkline page (0 = off)
PAGE_SECONDS = _env_int("MT4MON_PAGE_SECONDS", 3)   # every other page
# No update from MT4 for this long -> show "DATA STALE" warning.
STALE_SECONDS = _env_int("MT4MON_STALE_SECONDS", 30)
# Max individual order pages per cycle (the summary page always shows totals).
MAX_ORDER_PAGES = _env_int("MT4MON_MAX_ORDER_PAGES", 5)

# --- Alerts / backlight --------------------------------------------------
# Blink backlight + alert page when floating loss reaches this % of balance (0 = off).
DD_ALERT_PCT = _env_float("MT4MON_DD_ALERT_PCT", 2.0)
# Backlight off between these local hours (alerts still light it). -1 = never off.
NIGHT_START = _env_int("MT4MON_NIGHT_START", -1)
NIGHT_END = _env_int("MT4MON_NIGHT_END", 7)

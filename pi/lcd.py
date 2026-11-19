"""HD44780 1602 LCD driver over a PCF8574 I2C backpack (smbus2).

Backpack pin mapping (the common one):
    P0=RS  P1=RW  P2=EN  P3=Backlight  P4..P7=D4..D7

Custom icons live in the LCD's 8 CGRAM slots. In page text they are the
characters UP, DOWN, HEART, ... below (chr(0)..chr(6)); FULL is the ROM
full-block character (0xFF).

Run directly to test the screen:
    python3 lcd.py --address 0x27
"""
import argparse
import sys
import threading
import time

RS = 0x01
EN = 0x04
BACKLIGHT = 0x08

LINE_ADDR = (0x80, 0xC0)

# --- Icons ---------------------------------------------------------------
UP, DOWN, HEART, CHECK, CROSS, HALF, DOT = (chr(i) for i in range(7))
FULL = "\xff"

GLYPHS = {
    UP:    [0x00, 0x04, 0x0E, 0x1F, 0x1F, 0x00, 0x00, 0x00],
    DOWN:  [0x00, 0x00, 0x1F, 0x1F, 0x0E, 0x04, 0x00, 0x00],
    HEART: [0x00, 0x0A, 0x1F, 0x1F, 0x0E, 0x04, 0x00, 0x00],
    CHECK: [0x00, 0x01, 0x03, 0x16, 0x1C, 0x08, 0x00, 0x00],
    CROSS: [0x00, 0x1B, 0x0E, 0x04, 0x0E, 0x1B, 0x00, 0x00],
    HALF:  [0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0x1C, 0x00],  # half bar cell
    DOT:   [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x15, 0x00],  # empty bar cell
}

# How icons look in the console preview.
PREVIEW = {UP: "▲", DOWN: "▼", HEART: "♥", CHECK: "✓", CROSS: "✗",
           HALF: "▌", DOT: "·", FULL: "█"}


def _clean(text, width):
    """Keep ASCII + our icon codes, pad/cut to width."""
    out = []
    for ch in str(text):
        o = ord(ch)
        out.append(ch if (32 <= o <= 126 or ch in GLYPHS or ch == FULL) else "?")
    return "".join(out)[:width].ljust(width)


class I2CLcd:
    def __init__(self, bus=1, address=0x27, cols=16, rows=2):
        from smbus2 import SMBus  # imported here so console mode works without it

        self.cols = cols
        self.rows = rows
        self.address = address
        self._bus = SMBus(bus)
        self._lock = threading.Lock()
        self._bl = BACKLIGHT
        self._shown = [None] * rows
        self.init()

    # -- low level ------------------------------------------------------
    def _write(self, data):
        self._bus.write_byte(self.address, data | self._bl)

    def _pulse(self, data):
        self._write(data | EN)
        time.sleep(0.0005)
        self._write(data & ~EN)
        time.sleep(0.0001)

    def _write4(self, data):
        self._write(data)
        self._pulse(data)

    def _send(self, value, mode=0):
        self._write4((value & 0xF0) | mode)
        self._write4(((value << 4) & 0xF0) | mode)

    # -- public ---------------------------------------------------------
    def init(self):
        with self._lock:
            time.sleep(0.05)
            for delay in (0.0045, 0.0045, 0.00015):
                self._write4(0x30)
                time.sleep(delay)
            self._write4(0x20)  # 4-bit mode
            self._send(0x28)    # 2 lines, 5x8 font
            self._send(0x0C)    # display on, cursor off
            self._send(0x06)    # entry mode: increment
            self._send(0x01)    # clear
            time.sleep(0.002)
            for ch, rows in GLYPHS.items():   # load icons into CGRAM
                self._send(0x40 | (ord(ch) << 3))
                for r in rows:
                    self._send(r, RS)
            self._send(0x80)
            self._shown = [None] * self.rows

    def show(self, line1, line2=""):
        """Write two lines. Only rewrites lines that changed (no flicker)."""
        lines = [_clean(line1, self.cols), _clean(line2, self.cols)]
        with self._lock:
            for row, text in enumerate(lines[: self.rows]):
                if self._shown[row] == text:
                    continue
                self._send(LINE_ADDR[row])
                for ch in text:
                    self._send(ord(ch), RS)
                self._shown[row] = text

    def set_backlight(self, on):
        bl = BACKLIGHT if on else 0
        if bl != self._bl:
            with self._lock:
                self._bl = bl
                self._bus.write_byte(self.address, self._bl)

    def close(self):
        try:
            self._bus.close()
        except Exception:
            pass


class ConsoleLcd:
    """Stand-in used when LCD is disabled (PC testing). Prints changes only."""

    def __init__(self, cols=16, rows=2, **_):
        self.cols = cols
        self._last = None
        self._bl = True

    def init(self):
        pass

    def show(self, line1, line2=""):
        frame = (_clean(line1, self.cols), _clean(line2, self.cols))
        if frame != self._last:
            print(render_preview(*frame, backlight=self._bl), flush=True)
            self._last = frame

    def set_backlight(self, on):
        if on != self._bl:
            self._bl = on
            print(f"[backlight {'ON' if on else 'OFF'}]", flush=True)

    def close(self):
        pass


def render_preview(line1, line2, backlight=True):
    """Text picture of the LCD, icons shown as Unicode."""
    def p(s):
        return "".join(PREVIEW.get(c, c) for c in _clean(s, 16))
    edge = "+" + "-" * 16 + "+" + ("" if backlight else "  (backlight off)")
    return "\n".join([edge, "|" + p(line1) + "|", "|" + p(line2) + "|", "+" + "-" * 16 + "+"])


def main():
    ap = argparse.ArgumentParser(description="LCD 1602 I2C test")
    ap.add_argument("--bus", type=int, default=1)
    ap.add_argument("--address", default="0x27", help="0x27 or 0x3F (see i2cdetect)")
    args = ap.parse_args()

    try:
        lcd = I2CLcd(bus=args.bus, address=int(args.address, 0))
    except OSError as exc:
        print(f"Cannot open LCD at {args.address} on bus {args.bus}: {exc}")
        print("Check wiring, 'sudo raspi-config' I2C enable, and 'sudo i2cdetect -y 1'.")
        sys.exit(1)

    lcd.show("MT4 MONITOR V1", f"{UP}{DOWN}{HEART}{CHECK}{CROSS} {FULL}{FULL}{HALF}{DOT}{DOT}")
    print("Wrote 'MT4 MONITOR V1' and the icon row.")
    print("Blank screen or only boxes? Turn the blue contrast pot on the backpack.")
    lcd.close()


if __name__ == "__main__":
    main()

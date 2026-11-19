"""Send fake MT4 snapshots to the Pi API (no MT4 needed).

    python3 test_sender.py --url http://127.0.0.1:5000 --key YOUR_KEY
    python3 test_sender.py --url http://100.x.y.z:5000 --key YOUR_KEY --loop 5

Standard library only, so it also runs on the Windows VPS.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request


def fake_payload():
    profit_a = round(random.uniform(-30, 30), 2)
    profit_b = round(random.uniform(-10, 10), 2)
    balance = 10000.00
    margin = 85.40
    equity = round(balance + profit_a + profit_b, 2)
    return {
        "v": 1,
        "sent_at": int(time.time()),
        "monitor": {"version": "1.0-test", "interval": 5},
        "account": {
            "login": 12345678, "currency": "USD", "server": "Demo-Server",
            "balance": balance, "equity": equity, "margin": margin,
            "free_margin": round(equity - margin, 2),
            "margin_level": round(equity / margin * 100, 2),
            "profit": round(profit_a + profit_b, 2), "leverage": 500,
        },
        "terminal": {"connected": True, "trade_allowed": True},
        "capybara": {"magic_filter": 777, "magic_orders": 1,
                     "magic_profit": profit_a, "status": "UNVERIFIED"},
        "orders": [
            {"ticket": 90000001, "symbol": "XAUUSDc", "type": 0, "lots": 0.01,
             "open_price": 2650.12, "profit": profit_a, "magic": 777},
            {"ticket": 90000002, "symbol": "EURUSD", "type": 1, "lots": 0.05,
             "open_price": 1.0812, "profit": profit_b, "magic": 0},
            {"ticket": 90000003, "symbol": "XAUUSDc", "type": 2, "lots": 0.02,
             "open_price": 2600.00, "profit": 0.0, "magic": 777},
        ],
    }


def send(url, key, payload):
    req = urllib.request.Request(
        url.rstrip("/") + "/api/update",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:5000")
    ap.add_argument("--key", required=True)
    ap.add_argument("--loop", type=int, default=0, help="repeat every N seconds")
    args = ap.parse_args()

    while True:
        status, body = send(args.url, args.key, fake_payload())
        print(time.strftime("%H:%M:%S"), status, body.strip())
        if not args.loop:
            break
        time.sleep(args.loop)


if __name__ == "__main__":
    main()

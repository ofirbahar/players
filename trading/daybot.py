"""Minute-by-minute day-trading bot for the Alpaca paper account.

    python -m trading.daybot            # runs until the close, then exits flat
    python -m trading.daybot --dry-run  # computes signals and logs them, sends no orders

Every minute it pulls today's 1-minute bars, computes the strategy's target position
(-1 short, 0 flat, +1 long) per symbol, and trades only when the target changes.
It never forces a trade: the backtest showed that trading every minute loses ~99% to costs.

Risk controls:
  * fixed dollar size per symbol (integer shares, so shorts are allowed)
  * daily loss limit on the bot's own P&L -> flatten everything and stop
  * flat by 15:55 ET, no overnight positions
  * paper endpoint only
"""
import argparse
import json
import math
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from . import config, intraday
from .live import api

LOG = config.ROOT / "reports" / "daybot_log.jsonl"


def strategy(f, enter_z=3.5, exit_z=0.25, start_minute=60, since=None, max_day_er=0.1):
    """VWAP reversion: fade moves stretched 3.5 standard deviations from VWAP; exit back near VWAP.
    Chosen because it was the only intraday strategy with a positive edge before costs in both test periods;
    the strict thresholds keep trading (and costs) low."""
    # Trend-day filter: no new fades when the day so far has moved efficiently in one direction
    # (day_er = net move since the open / total distance travelled). Halved out-of-sample losses.
    calm = f["day_er"] < max_day_er
    fresh = pd.Series(True, index=f.index) if since is None else pd.Series(f.index >= since, index=f.index)
    # only signals that fire after `since` (the bot's start) count, so a mid-day start doesn't chase old trades
    p = intraday._stateful((f["z"] < -enter_z) & fresh & calm, (f["z"] > enter_z) & fresh & calm,
                           (f["z"].abs() < exit_z) | ~fresh, f)
    return p.where(f["minute"] >= start_minute, 0.0)


def log(event, **kw):
    entry = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **kw}
    print(json.dumps(entry), flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def today_bars(symbols):
    """Today's regular-session 1-minute bars (IEX feed: real-time on the free data plan)."""
    today = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    out, token = {s: [] for s in symbols}, None
    while True:
        p = {"symbols": ",".join(symbols), "timeframe": "1Min", "start": f"{today}T09:30:00-05:00",
             "limit": 10000, "feed": "iex"}
        if token:
            p["page_token"] = token
        r = requests.get(f"{config.DATA_URL}/stocks/bars", headers=config.headers(), params=p, timeout=30)
        r.raise_for_status()
        js = r.json()
        for s, rows in js.get("bars", {}).items():
            out[s] += rows
        token = js.get("next_page_token")
        if not token:
            break
    return {s: intraday.to_frame(rows) for s, rows in out.items() if rows}


class Book:
    """Tracks the bot's own cash flows so its P&L excludes the rest of the account."""

    def __init__(self):
        self.cash = 0.0

    def fill(self, order_id, timeout=20):
        for _ in range(timeout):
            o = api("GET", f"/orders/{order_id}")
            if o["status"] in ("filled", "canceled", "rejected", "expired"):
                break
            time.sleep(1)
        qty = float(o.get("filled_qty") or 0)
        px = float(o.get("filled_avg_price") or 0)
        self.cash += (-1 if o["side"] == "buy" else 1) * qty * px
        return o["status"], qty, px

    def pnl(self, positions):
        return self.cash + sum(float(p["market_value"]) for p in positions.values())


def positions_for(symbols):
    return {p["symbol"]: p for p in api("GET", "/positions") if p["symbol"] in symbols}


def submit(symbol, side, qty, book, dry):
    if qty <= 0:
        return
    if dry:
        log("order_dry", symbol=symbol, side=side, qty=qty)
        return
    o = api("POST", "/orders", json={"symbol": symbol, "side": side, "type": "market",
                                     "qty": str(qty), "time_in_force": "day"})
    status, filled, px = book.fill(o["id"])
    log("order", symbol=symbol, side=side, qty=qty, status=status, filled=filled, price=px)


def set_position(symbol, target, price, current_qty, size, book, dry):
    want = int(target) * math.floor(size / price)
    if want == current_qty:
        return
    if current_qty != 0 and (want == 0 or (want > 0) != (current_qty > 0)):
        submit(symbol, "sell" if current_qty > 0 else "buy", abs(current_qty), book, dry)  # close first
        current_qty = 0
    delta = want - current_qty
    submit(symbol, "buy" if delta > 0 else "sell", abs(delta), book, dry)


def flatten(symbols, book, dry, reason):
    for s, p in positions_for(symbols).items():
        q = int(float(p["qty"]))
        submit(s, "sell" if q > 0 else "buy", abs(q), book, dry)
    log("flatten", reason=reason)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=float, default=5000.0, help="dollars per symbol")
    ap.add_argument("--max-loss", type=float, default=750.0, help="stop for the day if bot P&L falls below -this")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if "paper" not in config.BASE_URL:
        raise SystemExit("daybot only runs against the paper endpoint.")

    swing = set(json.loads((config.ROOT / "reports" / "chosen_strategy.json").read_text())["universe"])
    symbols = [s for s in intraday.SYMBOLS if s not in swing]   # never trade the swing portfolio's symbols
    book = Book()
    start_pos = positions_for(symbols)
    if start_pos:
        raise SystemExit(f"Bot symbols already have positions: {list(start_pos)}. Close them first.")
    started = pd.Timestamp.now(tz="America/New_York").tz_localize(None).floor("min")
    log("start", symbols=symbols, size=args.size, max_loss=args.max_loss, dry_run=args.dry_run)

    while True:
        clock = api("GET", "/clock")
        now = pd.Timestamp(clock["timestamp"]).tz_convert("America/New_York")
        if not clock["is_open"]:
            log("market_closed")
            break
        if now.time() >= intraday.FLAT_AT:
            flatten(symbols, book, args.dry_run, "end_of_day")
            break

        pos = positions_for(symbols)
        pnl = book.pnl(pos)
        if pnl <= -args.max_loss:
            flatten(symbols, book, args.dry_run, f"daily_loss_limit pnl={pnl:.2f}")
            break

        try:
            bars = today_bars(symbols)
        except requests.RequestException as e:
            log("data_error", error=str(e))
            time.sleep(20)
            continue
        signals = {}
        for s, df in bars.items():
            df = df[df.index < now.tz_localize(None).floor("min")]   # completed minutes only
            if len(df) < 31:
                continue
            f = intraday.features(df)
            target = float(strategy(f, since=started).iloc[-1])
            signals[s] = {"target": target, "z": round(float(f["z"].iloc[-1]), 2), "price": float(f["close"].iloc[-1])}
            cur = int(float(pos[s]["qty"])) if s in pos else 0
            try:
                set_position(s, target, signals[s]["price"], cur, args.size, book, args.dry_run)
            except RuntimeError as e:
                log("order_error", symbol=s, error=str(e))
        log("tick", pnl=round(pnl, 2), signals=signals)
        time.sleep(max(5, 65 - pd.Timestamp.now().second))   # wake just after each new minute bar

    log("stop", pnl=round(book.pnl(positions_for(symbols)), 2))


if __name__ == "__main__":
    main()

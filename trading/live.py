"""Run a strategy on the Alpaca paper account: compute target weights, rebalance to them.

    python -m trading.live                      # dry run with the strategy chosen by research.py
    python -m trading.live --strategy trend_ensemble
    python -m trading.live --execute            # actually send the orders

Safety: refuses to run against a non-paper endpoint unless --allow-live is given.
Only completed daily bars are used (today's bar is dropped while the market is open).
"""
import argparse
import json
from datetime import datetime, timezone

import pandas as pd
import requests

from . import config, data
from .strategies import STRATEGIES

REPORTS = config.ROOT / "reports"


def api(method, path, **kw):
    r = requests.request(method, f"{config.BASE_URL}{path}", headers=config.headers(), timeout=30, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text}")
    return r.json() if r.text else None


def target_weights(strategy, universe):
    d = data.fetch_universe(universe, refresh=True)
    clock = api("GET", "/clock")
    today = pd.Timestamp(clock["timestamp"][:10])
    if clock["is_open"] or d["close"].index[-1] >= today:
        d = {k: v.loc[v.index < today] for k, v in d.items()}  # completed bars only
    w = STRATEGIES[strategy](d).iloc[-1].fillna(0.0)
    return w[w > 1e-6], d["close"].index[-1].date()


def plan_orders(weights, max_gross=1.0, min_trade_frac=0.005):
    acct = api("GET", "/account")
    equity = float(acct["equity"])
    gross = weights.sum()
    if gross > max_gross:
        weights = weights * max_gross / gross
    positions = {p["symbol"]: float(p["market_value"]) for p in api("GET", "/positions")}
    symbols = sorted(set(weights.index) | set(positions))
    orders = []
    for s in symbols:
        target = float(weights.get(s, 0.0)) * equity
        current = positions.get(s, 0.0)
        delta = target - current
        if target == 0 and current != 0:
            orders.append({"symbol": s, "action": "close", "value": -current})
        elif abs(delta) >= max(25.0, min_trade_frac * equity):
            orders.append({"symbol": s, "action": "buy" if delta > 0 else "sell", "value": round(delta, 2)})
    orders.sort(key=lambda o: o["value"])  # sells first to free up cash
    return equity, positions, orders


def execute(orders):
    results = []
    for o in orders:
        if o["action"] == "close":
            res = api("DELETE", f"/positions/{o['symbol']}")
        else:
            res = api("POST", "/orders", json={
                "symbol": o["symbol"], "side": o["action"], "type": "market",
                "time_in_force": "day", "notional": f"{abs(o['value']):.2f}",
            })
        results.append({**o, "order_id": res.get("id"), "status": res.get("status")})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", help="strategy name (default: reports/chosen_strategy.json)")
    ap.add_argument("--execute", action="store_true", help="send orders (default is dry run)")
    ap.add_argument("--allow-live", action="store_true", help="permit a non-paper endpoint")
    args = ap.parse_args()

    if "paper" not in config.BASE_URL and not args.allow_live:
        raise SystemExit(f"Refusing to trade on {config.BASE_URL} without --allow-live.")
    chosen = json.loads((REPORTS / "chosen_strategy.json").read_text())
    strategy = args.strategy or chosen["strategy"]
    universe = chosen["universe"]

    weights, asof = target_weights(strategy, universe)
    equity, positions, orders = plan_orders(weights)
    print(f"Strategy {strategy}, signals as of close {asof}, account equity ${equity:,.2f}")
    print("Target weights:", ", ".join(f"{s} {w*100:.1f}%" for s, w in weights.items()) or "all cash")
    print("Current positions:", ", ".join(f"{s} ${v:,.0f}" for s, v in positions.items()) or "none")
    for o in orders:
        print(f"  {o['action'].upper():5s} {o['symbol']:5s} ${abs(o['value']):,.2f}")
    if not orders:
        print("Nothing to do: portfolio already matches the targets.")

    entry = {"time": datetime.now(timezone.utc).isoformat(), "strategy": strategy, "signals_asof": str(asof),
             "equity": equity, "weights": weights.round(4).to_dict(), "orders": orders, "executed": False}
    if args.execute and orders:
        entry["orders"] = execute(orders)
        entry["executed"] = True
        for o in entry["orders"]:
            print(f"  sent {o['action']} {o['symbol']}: {o['status']}")
    elif orders:
        print("Dry run: add --execute to send these orders.")
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / "trade_log.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    main()

"""Live scorecard: compare what the paper account actually did with what the backtests expected.

    python -m trading.scorecard

A strategy is only as good as its live record. This flags when live results drift outside what the
backtest says is normal, which is the signal to cut size or stop, not to tweak parameters.
"""
import json

import numpy as np
import pandas as pd

from . import config
from .live import api

REPORTS = config.ROOT / "reports"

# Expectations from out-of-sample backtests (2022 onward), see improvement_log.md
EXPECT = {
    "swing": {"daily_mean": 0.092 / 252, "daily_sd": 0.101 / np.sqrt(252), "max_dd": -0.078},
    "daybot": {"daily_mean_bps": -2.42, "trades_per_symbol_day": 3.2},
}


def account_history():
    h = api("GET", "/account/portfolio/history", params={"period": "1A", "timeframe": "1D"})
    eq = pd.Series(h["equity"], index=pd.to_datetime(h["timestamp"], unit="s").date, dtype=float)
    return eq[eq > 0]


def daybot_days():
    """Per-day bot P&L from Alpaca's fill records between the bot's start and stop (the source of truth)."""
    path = REPORTS / "daybot_log.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    out = {}
    for r in rows:
        day = r["time"][:10]
        o = out.setdefault(day, {"orders": 0, "start": None, "stop": None, "symbols": []})
        if r["event"] == "start":
            o["start"], o["symbols"] = r["time"][:19], r["symbols"]
        elif r["event"] in ("stop", "flatten"):
            o["stop"] = r["time"][:19]
        elif r["event"] == "order":
            o["orders"] += 1
    result = {}
    for day, o in out.items():
        if not o["start"]:
            continue
        stop = o["stop"] or "9999"
        fills = api("GET", "/account/activities/FILL", params={"date": day, "page_size": 100})
        cash = sum((-1 if f["side"] == "buy" else 1) * float(f["qty"]) * float(f["price"])
                   for f in fills if f["symbol"] in o["symbols"] and o["start"] <= f["transaction_time"][:19] <= stop)
        result[day] = {"orders": o["orders"], "pnl": cash if o["stop"] else float("nan")}
    return pd.DataFrame(result).T


GOAL_PER_DAY = 200.0
EXPECTED_ANNUAL = 0.092          # swing blend, out-of-sample 2022 onward
TRADING_DAYS = 252


def goal_section(equity):
    """How far the account is from averaging the daily goal, and how long reinvesting would take."""
    need = GOAL_PER_DAY * TRADING_DAYS / EXPECTED_ANNUAL
    now = equity * EXPECTED_ANNUAL / TRADING_DAYS
    lines = ["", f"## Goal: average ${GOAL_PER_DAY:.0f} a day", "",
             f"At ~{EXPECTED_ANNUAL*100:.1f}% a year the account is expected to average **${now:,.0f} a day** now "
             f"({now/GOAL_PER_DAY*100:.0f}% of the goal).",
             f"Averaging ${GOAL_PER_DAY:.0f} a day takes about **${need:,.0f}** invested. Individual days still swing both ways.",
             "", "| Added each month | Years to reach it (gains reinvested) |", "|---|---|"]
    monthly_r = (1 + EXPECTED_ANNUAL) ** (1 / 12) - 1
    for add in [0, 500, 1000, 2000, 5000]:
        eq, months = equity, 0
        while eq < need and months < 1200:
            eq = eq * (1 + monthly_r) + add
            months += 1
        lines.append(f"| ${add:,} | {months/12:.1f} |" if eq >= need else f"| ${add:,} | 100+ |")
    lines.append("\nShortcuts like heavy leverage were simulated and rejected: 11x leverage averaged −$16 a day "
                 "and wiped out the account (see improvement_log.md).")
    return lines


def main():
    eq = account_history()
    lines = ["# Live scorecard", ""]
    if len(eq) >= 2:
        r = eq.pct_change().dropna()
        n = len(r)
        exp = EXPECT["swing"]
        z = (r.mean() - exp["daily_mean"]) / (exp["daily_sd"] / np.sqrt(n))
        dd = (eq / eq.cummax() - 1).min()
        lines += [f"Account: {n} trading days, equity ${eq.iloc[-1]:,.2f}, total return {(eq.iloc[-1]/eq.iloc[0]-1)*100:+.2f}%,",
                  f"max drawdown {dd*100:.1f}% (backtest worst: {exp['max_dd']*100:.1f}%).",
                  f"Average day vs backtest expectation: z = {z:+.2f} "
                  + ("(within normal range)" if abs(z) < 2 else "(OUTSIDE normal range: review the strategy)"),
                  ""]
        if dd < 1.5 * exp["max_dd"]:
            lines.append("**Drawdown is 1.5x worse than the backtest's worst. Cut size or stop.**")
        if n < 60:
            lines.append(f"Only {n} days of live data: too few to judge skill. Roughly 60+ are needed.")
    else:
        lines.append("Not enough account history yet.")
    equity_now = float(api("GET", "/account")["equity"])
    lines += goal_section(equity_now)
    dbt = daybot_days()
    if len(dbt):
        lines += ["", "## Day bot", "", "| Day | Orders | Bot P&L |", "|---|---|---|"]
        lines += [f"| {d} | {int(r.orders)} | ${r.pnl:,.2f} |" for d, r in dbt.iterrows()]
        lines.append(f"\nBacktest expectation: about {EXPECT['daybot']['daily_mean_bps']} bps a day on capital (a small loss).")
    text = "\n".join(lines)
    (REPORTS / "scorecard.md").write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

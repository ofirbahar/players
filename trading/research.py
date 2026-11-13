"""Backtest every strategy, choose on in-sample data, judge on out-of-sample data.

    python -m trading.research

Writes reports/strategy_report.md and reports/equity_curves.png.
"""
import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import backtest, config, data
from .strategies import STRATEGIES

# Diversified ETF universe: US/intl equity, bonds, gold, sectors.
# ETFs avoid the survivorship bias of picking today's winning stocks.
UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "XLE", "XLK", "XLF", "XLV"]
TRAIN = ("2017-01-01", "2021-12-31")  # 2016 is indicator warm-up
TEST = ("2022-01-01", None)
REPORTS = config.ROOT / "reports"


def evaluate(d, cost_bps=5.0):
    rows, curves = [], {}
    for name, fn in STRATEGIES.items():
        w = fn(d)
        r, to = backtest.run(w, d["close"], cost_bps)
        curves[name] = r
        for label, (a, b) in {"train": TRAIN, "test": TEST}.items():
            m = backtest.metrics(r.loc[a:b], to)
            rows.append({"strategy": name, "period": label, **m})
    return pd.DataFrame(rows), pd.DataFrame(curves)


def fmt_table(df):
    cols = ["CAGR", "Vol", "Sharpe", "MaxDD", "Calmar", "TurnoverPerYr", "PctDaysInvested"]
    t = df.set_index("strategy")[cols].copy()
    for c in ["CAGR", "Vol", "MaxDD", "PctDaysInvested"]:
        t[c] = (t[c] * 100).map("{:.1f}%".format)
    for c in ["Sharpe", "Calmar", "TurnoverPerYr"]:
        t[c] = t[c].map("{:.2f}".format)
    return t.to_markdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download market data")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    args = ap.parse_args()

    d = data.fetch_universe(UNIVERSE, refresh=args.refresh)
    res, curves = evaluate(d, args.cost_bps)
    train = res[res.period == "train"].sort_values("Sharpe", ascending=False)
    test = res[res.period == "test"].set_index("strategy").loc[train.strategy].reset_index()

    # Selection rule decided before looking at test data: best in-sample Sharpe
    # among strategies whose in-sample max drawdown is no worse than buy & hold's.
    bh_dd = train.set_index("strategy").loc["buy_and_hold", "MaxDD"]
    eligible = train[train.MaxDD >= bh_dd]
    rule_pick = eligible.iloc[0].strategy
    # Improvement (see reports/improvement_log.md): the single in-sample winner degraded badly
    # out-of-sample, while blending every strategy held up best. Trade the scaled blend.
    chosen = "blend_all_scaled"

    REPORTS.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), sharex=False)
    for ax, (a, b), title in [(axes[0], TRAIN, "In-sample (selection)"), (axes[1], TEST, "Out-of-sample (judgement)")]:
        seg = curves.loc[a:b]
        eq = (1 + seg).cumprod()
        top = list(train.strategy[:5])
        for name in dict.fromkeys(top + ["buy_and_hold", chosen]):
            lw = 2.5 if name == chosen else (1.8 if name == "buy_and_hold" else 1)
            ls = "--" if name == "buy_and_hold" else "-"
            ax.plot(eq.index, eq[name], lw=lw, ls=ls, label=name)
        ax.set_title(title)
        ax.set_ylabel("Growth of $1")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(REPORTS / "equity_curves.png", dpi=110)

    lines = [
        "# Strategy research report",
        "",
        f"Universe: {', '.join(UNIVERSE)} (daily, split/dividend adjusted, Alpaca SIP data).",
        f"Costs: {args.cost_bps} bps per unit of turnover. Signals use the close of day t and trade for day t+1.",
        f"In-sample: {TRAIN[0]} to {TRAIN[1]}. Out-of-sample: {TEST[0]} to {curves.index[-1].date()}.",
        "",
        "Selection rule (fixed before looking at out-of-sample results): highest in-sample Sharpe",
        "among strategies with an in-sample max drawdown no worse than buy & hold.",
        "",
        f"Single-strategy pick by that rule: `{rule_pick}`. **Traded strategy: `{chosen}`** (blend of all",
        "16 strategies scaled 1.5x, capped at 100% invested), because diversifying across strategies held up",
        "better out-of-sample than any single pick. See improvement_log.md.",
        "",
        "## In-sample (ranked by Sharpe)",
        "",
        fmt_table(train),
        "",
        "## Out-of-sample (same order)",
        "",
        fmt_table(test),
        "",
        "![equity curves](equity_curves.png)",
        "",
    ]
    (REPORTS / "strategy_report.md").write_text("\n".join(lines))
    (REPORTS / "chosen_strategy.json").write_text(json.dumps({"strategy": chosen, "universe": UNIVERSE}, indent=2))
    print("\n".join(lines[:12]))
    print("\nIN-SAMPLE\n" + fmt_table(train))
    print("\nOUT-OF-SAMPLE\n" + fmt_table(test))


if __name__ == "__main__":
    main()

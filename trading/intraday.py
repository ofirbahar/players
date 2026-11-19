"""Intraday (1-minute) strategies, a regime-switching selector, and a minute-bar backtester.

    python -m trading.intraday            # backtest on recent minute data

Positions are decided at the close of minute t and held over minute t+1.
Everything is flat by 15:55 ET (no overnight risk). Costs are charged on every change in position.
"""
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

from . import config

SYMBOLS = ["QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "AMD"]
FLAT_AT = pd.Timestamp("15:55").time()
REPORTS = config.ROOT / "reports"


# ---------- data ----------

def fetch_minutes(symbol, start, end, refresh=False):
    config.CACHE_DIR.mkdir(exist_ok=True)
    cache = config.CACHE_DIR / f"{symbol}_1min_{start}_{end}.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    rows, token = [], None
    while True:
        p = {"symbols": symbol, "timeframe": "1Min", "start": start, "end": end,
             "limit": 10000, "adjustment": "all", "feed": "sip"}
        if token:
            p["page_token"] = token
        r = requests.get(f"{config.DATA_URL}/stocks/bars", headers=config.headers(), params=p, timeout=60)
        r.raise_for_status()
        js = r.json()
        rows += js.get("bars", {}).get(symbol, [])
        token = js.get("next_page_token")
        if not token:
            break
    df = to_frame(rows)
    df.to_csv(cache)
    return df


def to_frame(rows):
    df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vw": "vwap_bar"})
    df.index = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
    df = df[["open", "high", "low", "close", "volume", "vwap_bar"]]
    t = df.index.time
    return df[(t >= pd.Timestamp("09:30").time()) & (t < pd.Timestamp("16:00").time())]


# ---------- per-day features ----------

def features(df):
    """Indicators computed within each trading day only (nothing leaks across days)."""
    out = []
    for _, d in df.groupby(df.index.date):
        d = d.copy()
        pv = (d["vwap_bar"].fillna(d["close"]) * d["volume"]).cumsum()
        d["vwap"] = pv / d["volume"].cumsum().replace(0, np.nan)
        dev = d["close"] - d["vwap"]
        d["z"] = dev / dev.rolling(30, min_periods=15).std()
        d["ema9"] = d["close"].ewm(span=9, adjust=False).mean()
        d["ema21"] = d["close"].ewm(span=21, adjust=False).mean()
        delta = d["close"].diff()
        up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
        n = 30
        d["er"] = (d["close"] - d["close"].shift(n)).abs() / delta.abs().rolling(n).sum()
        d["day_er"] = (d["close"] - d["open"].iloc[0]).abs() / delta.abs().cumsum().replace(0, np.nan)
        first30 = d.iloc[:30]
        d["or_high"], d["or_low"] = first30["high"].max(), first30["low"].min()
        d["minute"] = np.arange(len(d))
        out.append(d)
    return pd.concat(out)


def _stateful(enter_long, enter_short, exit_, f):
    s = pd.Series(np.nan, index=f.index)
    s[exit_.fillna(False)] = 0.0
    s[enter_long.fillna(False)] = 1.0
    s[enter_short.fillna(False)] = -1.0
    s[f["minute"] == 0] = 0.0                      # start every day flat
    return s.groupby(f.index.date).ffill().fillna(0.0)


# ---------- strategies: return position in {-1, 0, 1} per minute ----------

def every_minute(f):
    """Trades every single minute: bet the next minute repeats the last one."""
    return np.sign(f["close"].diff()).fillna(0.0)


def opening_range_breakout(f):
    after = f["minute"] >= 30
    return _stateful(after & (f["close"] > f["or_high"]), after & (f["close"] < f["or_low"]),
                     pd.Series(False, index=f.index), f)


def vwap_reversion(f):
    return _stateful(f["z"] < -2.0, f["z"] > 2.0, f["z"].abs() < 0.25, f)


def ema_momentum(f):
    trend = np.sign(f["ema9"] - f["ema21"])
    agree = np.sign(f["close"] - f["vwap"]) == trend
    return (trend * agree).where(f["minute"] >= 15, 0.0).fillna(0.0)


def rsi_reversion(f):
    return _stateful(f["rsi"] < 25, f["rsi"] > 75, (f["rsi"] - 50).abs() < 5, f)


def adaptive(f, trend_er=0.35, chop_er=0.20):
    """Pick the tool for the market's current state.

    Efficiency ratio (net move / total path over 30 min) measures how 'trendy' price is:
      high -> trending: follow momentum;   low -> choppy: fade stretches from VWAP;
      first hour, no clear regime: trade opening-range breakouts;   otherwise stay flat.
    """
    er = f["er"]
    mom, rev, orb = ema_momentum(f), vwap_reversion(f), opening_range_breakout(f)
    pos = pd.Series(0.0, index=f.index)
    pos[er > trend_er] = mom[er > trend_er]
    pos[er < chop_er] = rev[er < chop_er]
    first_hour = (f["minute"] >= 30) & (f["minute"] < 90) & er.between(chop_er, trend_er)
    pos[first_hour] = orb[first_hour]
    return pos


STRATEGIES = {
    "every_minute": every_minute,
    "opening_range_breakout": opening_range_breakout,
    "vwap_reversion": vwap_reversion,
    "ema_momentum": ema_momentum,
    "rsi_reversion": rsi_reversion,
    "adaptive": adaptive,
}


# ---------- backtest ----------

def run(f, pos, cost_bps):
    pos = pos.copy()
    pos[f.index.time >= FLAT_AT] = 0.0
    same_day = pd.Series(f.index.date, index=f.index)
    ret = f["close"].pct_change().where(same_day == same_day.shift(), 0.0).fillna(0.0)
    held = pos.groupby(f.index.date).shift(1).fillna(0.0)
    change = pos.groupby(f.index.date).diff().abs().fillna(pos.abs())
    pnl = held * ret - change * cost_bps / 1e4
    return pnl, change


def summarize(pnl, change):
    daily = pnl.groupby(pnl.index.date).sum()
    trades = change.groupby(change.index.date).sum()
    eq = (1 + daily).cumprod()
    return {
        "TotalRet": eq.iloc[-1] - 1,
        "AvgDay_bps": daily.mean() * 1e4,
        "Sharpe": daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0,
        "WinDays": (daily > 0).mean(),
        "MaxDD": (eq / eq.cummax() - 1).min(),
        "TradesPerDay": trades.mean(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-11-12T21:00:00Z")
    ap.add_argument("--cost-bps", type=float, default=2.0, help="spread + slippage per side")
    args = ap.parse_args()

    feats = {s: features(fetch_minutes(s, args.start, args.end)) for s in SYMBOLS}
    days = sorted(set(feats[SYMBOLS[0]].index.date))
    split = days[int(len(days) * 0.6)]
    rows, curves = [], {}
    for name, fn in STRATEGIES.items():
        pnls, changes = [], []
        for s, f in feats.items():
            p, c = run(f, fn(f), args.cost_bps)
            pnls.append(p.groupby(p.index.date).sum())
            changes.append(c.groupby(c.index.date).sum())
        daily = pd.concat(pnls, axis=1).fillna(0).mean(axis=1)   # equal capital per symbol
        trades = pd.concat(changes, axis=1).fillna(0).sum(axis=1)
        daily.index = pd.to_datetime(daily.index)
        trades.index = daily.index
        curves[name] = daily
        for label, mask in [("train", daily.index < pd.Timestamp(split)), ("test", daily.index >= pd.Timestamp(split))]:
            m = summarize(daily[mask], trades[mask])
            rows.append({"strategy": name, "period": label, **m})
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    for label in ["train", "test"]:
        t = res[res.period == label].drop(columns="period").set_index("strategy")
        print(f"\n{label.upper()} ({'before' if label == 'train' else 'from'} {split}), cost {args.cost_bps} bps/side")
        print(t.round(3).to_string())

    REPORTS.mkdir(exist_ok=True)
    eq = (1 + pd.DataFrame(curves)).cumprod()
    ax = eq.plot(figsize=(12, 6), title=f"Intraday strategies on {', '.join(SYMBOLS)} ({args.cost_bps} bps/side costs)")
    ax.axvline(pd.Timestamp(split), color="grey", ls="--")
    ax.set_ylabel("Growth of $1")
    ax.grid(alpha=0.3)
    ax.set_yscale("log")
    plt.tight_layout()
    plt.savefig(REPORTS / "intraday_equity.png", dpi=110)
    res.to_csv(REPORTS / "intraday_results.csv", index=False)


if __name__ == "__main__":
    main()

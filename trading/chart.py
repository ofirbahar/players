"""Chart reading: draw a technical chart for a symbol and write out what it shows.

    python -m trading.chart SPY [--days 250]

Produces reports/chart_<SYMBOL>.png and prints a plain-English reading:
trend, momentum, volatility, support/resistance, recent candlestick patterns and signals.
"""
import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config, data
from . import indicators as ind


# ---------- pattern detection ----------

def candle_patterns(df, lookback=5):
    """Classic single/two-candle patterns over the last few bars."""
    o, h, l, c = df.open, df.high, df.low, df.close
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    avg_body = body.rolling(20).mean()
    prior_down = c.shift(1) < c.shift(5)
    prior_up = c.shift(1) > c.shift(5)
    pats = {
        "Doji (indecision)": body / rng < 0.1,
        "Hammer (possible bottom)": (lower > 2 * body) & (upper < body) & prior_down,
        "Shooting star (possible top)": (upper > 2 * body) & (lower < body) & prior_up,
        "Bullish engulfing": (c > o) & (c.shift() < o.shift()) & (c >= o.shift()) & (o <= c.shift()) & prior_down,
        "Bearish engulfing": (c < o) & (c.shift() > o.shift()) & (c <= o.shift()) & (o >= c.shift()) & prior_up,
        "Wide-range bull bar": (c > o) & (body > 2 * avg_body),
        "Wide-range bear bar": (c < o) & (body > 2 * avg_body),
    }
    found = []
    for name, mask in pats.items():
        for dt in mask.iloc[-lookback:][mask.iloc[-lookback:].fillna(False)].index:
            found.append((dt.date(), name))
    return sorted(found)


def support_resistance(df, window=5, tolerance=0.015, max_levels=3):
    """Cluster swing highs/lows into price levels; rank by how often price reacted there."""
    h, l = df.high, df.low
    piv_hi = h[(h == h.rolling(2 * window + 1, center=True).max())]
    piv_lo = l[(l == l.rolling(2 * window + 1, center=True).min())]
    pivots = sorted(list(piv_hi.values) + list(piv_lo.values))
    clusters = []
    for p in pivots:
        if clusters and abs(p - np.mean(clusters[-1])) / np.mean(clusters[-1]) < tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = sorted(((float(np.mean(cl)), len(cl)) for cl in clusters), key=lambda x: -x[1])
    price = df.close.iloc[-1]
    sup = sorted([lv for lv in levels if lv[0] < price], key=lambda x: -x[0])[:max_levels]
    res = sorted([lv for lv in levels if lv[0] > price], key=lambda x: x[0])[:max_levels]
    return sup, res


def divergence(close, osc, lookback=60, window=5):
    """Bearish: higher price high with lower oscillator high. Bullish: the reverse on lows."""
    c, o = close.iloc[-lookback:], osc.iloc[-lookback:]
    hi = c[c == c.rolling(2 * window + 1, center=True, min_periods=window + 1).max()].index
    lo = c[c == c.rolling(2 * window + 1, center=True, min_periods=window + 1).min()].index
    out = []
    if len(hi) >= 2 and c[hi[-1]] > c[hi[-2]] and o[hi[-1]] < o[hi[-2]]:
        out.append("Bearish RSI divergence: price made a higher high, RSI a lower high (momentum fading).")
    if len(lo) >= 2 and c[lo[-1]] < c[lo[-2]] and o[lo[-1]] > o[lo[-2]]:
        out.append("Bullish RSI divergence: price made a lower low, RSI a higher low (selling fading).")
    return out


def crossed(a, b, days=10):
    diff = np.sign(a - b)
    ch = diff.diff().iloc[-days:]
    up = ch[ch > 0].index
    dn = ch[ch < 0].index
    return (up[-1].date() if len(up) else None), (dn[-1].date() if len(dn) else None)


# ---------- reading ----------

def read_chart(df, symbol):
    c = df.close
    s20, s50, s200 = ind.sma(c, 20), ind.sma(c, 50), ind.sma(c, 200)
    r = ind.rsi(c, 14)
    m_line, m_sig, m_hist = ind.macd(c)
    adx, pdi, mdi = ind.adx(df.high, df.low, c)
    bb_lo, bb_mid, bb_hi = ind.bollinger(c)
    atr = ind.atr(df.high, df.low, c)
    vol20 = ind.realized_vol(c, 20)
    price = c.iloc[-1]
    notes, score = [], 0

    # Trend
    if price > s50.iloc[-1] > s200.iloc[-1]:
        notes.append("Trend: UP. Price is above a rising stack of the 50- and 200-day averages."); score += 2
    elif price < s50.iloc[-1] < s200.iloc[-1]:
        notes.append("Trend: DOWN. Price is below the 50-day, which is below the 200-day."); score -= 2
    elif price < min(s50.iloc[-1], s200.iloc[-1]):
        notes.append("Trend: BREAKING DOWN. Price has fallen below both the 50- and 200-day averages."); score -= 1
    elif price > max(s50.iloc[-1], s200.iloc[-1]):
        notes.append("Trend: RECOVERING. Price is back above both the 50- and 200-day averages."); score += 1
    else:
        notes.append("Trend: MIXED. Price sits between the 50- and 200-day averages (range or transition).")
    slope50 = s50.iloc[-1] / s50.iloc[-11] - 1
    notes.append(f"50-day average is {'rising' if slope50 > 0 else 'falling'} ({slope50*100:+.1f}% over two weeks).")
    score += 1 if slope50 > 0 else -1
    slope200 = s200.iloc[-1] / s200.iloc[-21] - 1
    notes.append(f"200-day average is {'rising' if slope200 > 0 else 'falling'} ({slope200*100:+.1f}% over a month).")
    score += 1 if slope200 > 0 else -1
    gx, dx = crossed(s50, s200, 20)
    if gx:
        notes.append(f"Golden cross (50 above 200) on {gx}."); score += 1
    if dx:
        notes.append(f"Death cross (50 below 200) on {dx}."); score -= 1
    a = adx.iloc[-1]
    notes.append(f"ADX {a:.0f}: {'strong' if a > 25 else 'weak' if a < 20 else 'moderate'} trend strength, "
                 f"{'buyers' if pdi.iloc[-1] > mdi.iloc[-1] else 'sellers'} in control (+DI vs -DI).")

    # Momentum
    rv = r.iloc[-1]
    state = "overbought" if rv > 70 else "oversold" if rv < 30 else "neutral"
    notes.append(f"RSI(14) {rv:.0f}: {state}.")
    if rv < 30 and price > s200.iloc[-1]:
        notes.append("Oversold inside a long-term uptrend: historically a dip-buying setup."); score += 1
    if rv > 70 and price < s200.iloc[-1]:
        notes.append("Overbought inside a long-term downtrend: rallies here often fail."); score -= 1
    mu, md = crossed(m_line, m_sig, 5)
    notes.append(f"MACD is {'above' if m_line.iloc[-1] > m_sig.iloc[-1] else 'below'} its signal line, "
                 f"histogram {'growing' if m_hist.iloc[-1] > m_hist.iloc[-2] else 'shrinking'}.")
    score += 1 if m_line.iloc[-1] > m_sig.iloc[-1] else -1
    if mu: notes.append(f"Bullish MACD cross on {mu}.")
    if md: notes.append(f"Bearish MACD cross on {md}.")
    notes += divergence(c, r)

    # Volatility / bands
    pb = (price - bb_lo.iloc[-1]) / (bb_hi.iloc[-1] - bb_lo.iloc[-1])
    width = (bb_hi - bb_lo) / bb_mid
    if width.iloc[-1] < width.iloc[-126:].quantile(0.1):
        notes.append("Bollinger squeeze: volatility is near a 6-month low; a big move often follows.")
    notes.append(f"Price sits at {pb*100:.0f}% of the Bollinger band range (0% = lower band, 100% = upper).")
    notes.append(f"ATR(14) ${atr.iloc[-1]:.2f} ({atr.iloc[-1]/price*100:.1f}% of price); "
                 f"20-day realised volatility {vol20.iloc[-1]*100:.0f}% annualised.")

    # Volume
    v = df.volume
    if v.iloc[-5:].mean() > 1.5 * v.iloc[-60:].mean():
        notes.append("Volume is running 50%+ above its 3-month average: the current move has participation.")
    obv = ind.obv(c, v)
    if (obv.iloc[-1] > obv.iloc[-21]) != (c.iloc[-1] > c.iloc[-21]):
        notes.append("On-balance volume disagrees with price over the last month (watch for a reversal).")

    # Levels
    sup, res = support_resistance(df.iloc[-250:])
    stop = price - 2 * atr.iloc[-1]

    bias = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    return {
        "symbol": symbol, "date": c.index[-1].date(), "price": price, "notes": notes,
        "support": sup, "resistance": res, "patterns": candle_patterns(df),
        "score": score, "bias": bias, "atr_stop": stop,
    }


def plot(df, symbol, reading, days=250, path=None):
    d = df.iloc[-days:]
    c = df.close
    s50, s200 = ind.sma(c, 50).iloc[-days:], ind.sma(c, 200).iloc[-days:]
    lo, mid, hi = (x.iloc[-days:] for x in ind.bollinger(c))
    r = ind.rsi(c).iloc[-days:]
    ml, ms, mh = (x.iloc[-days:] for x in ind.macd(c))
    x = np.arange(len(d))

    fig, ax = plt.subplots(4, 1, figsize=(13, 10), sharex=True,
                           gridspec_kw={"height_ratios": [4, 1, 1.2, 1.2]})
    up = d.close >= d.open
    col = np.where(up, "#2a9d55", "#d64545")
    ax[0].vlines(x, d.low, d.high, color=col, lw=0.8)
    ax[0].bar(x, (d.close - d.open).abs().clip(lower=d.close * 1e-4), bottom=np.minimum(d.open, d.close),
              color=col, width=0.7)
    ax[0].plot(x, s50, color="#e08a00", lw=1.3, label="SMA 50")
    ax[0].plot(x, s200, color="#3060c0", lw=1.6, label="SMA 200")
    ax[0].fill_between(x, lo, hi, color="grey", alpha=0.12, label="Bollinger 20,2")
    for lvl, n in reading["support"]:
        ax[0].axhline(lvl, color="#2a9d55", ls=":", lw=1)
        ax[0].text(x[-1] + 1, lvl, f" S {lvl:.2f}", va="center", fontsize=8, color="#2a9d55")
    for lvl, n in reading["resistance"]:
        ax[0].axhline(lvl, color="#d64545", ls=":", lw=1)
        ax[0].text(x[-1] + 1, lvl, f" R {lvl:.2f}", va="center", fontsize=8, color="#d64545")
    ax[0].set_title(f"{symbol}  {reading['date']}  close {reading['price']:.2f}  bias: {reading['bias']} "
                    f"(score {reading['score']:+d})")
    ax[0].legend(loc="upper left", fontsize=8)
    ax[1].bar(x, d.volume, color=col, width=0.7)
    ax[1].set_ylabel("Volume")
    ax[2].plot(x, r, color="#7040a0")
    ax[2].axhline(70, color="grey", ls="--", lw=0.8)
    ax[2].axhline(30, color="grey", ls="--", lw=0.8)
    ax[2].set_ylabel("RSI 14")
    ax[3].plot(x, ml, label="MACD", color="#3060c0")
    ax[3].plot(x, ms, label="Signal", color="#e08a00")
    ax[3].bar(x, mh, color=np.where(mh >= 0, "#2a9d55", "#d64545"), width=0.7)
    ax[3].legend(loc="upper left", fontsize=8)
    ticks = x[:: max(1, len(x) // 10)]
    ax[3].set_xticks(ticks)
    ax[3].set_xticklabels([d.index[i].strftime("%Y-%m") for i in ticks])
    for a in ax:
        a.grid(alpha=0.25)
    fig.tight_layout()
    path = path or config.ROOT / "reports" / f"chart_{symbol}.png"
    path.parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def format_reading(rd):
    partial = rd["date"] == pd.Timestamp.now(tz="America/New_York").date()
    last = "last price (today's bar is still forming)" if partial else "close"
    out = [f"{rd['symbol']} on {rd['date']}: {last} {rd['price']:.2f}. Overall bias {rd['bias']} (score {rd['score']:+d}).", ""]
    out += [f"- {n}" for n in rd["notes"]]
    out.append("- Support: " + (", ".join(f"{p:.2f} ({n} touches)" for p, n in rd["support"]) or "none nearby"))
    out.append("- Resistance: " + (", ".join(f"{p:.2f} ({n} touches)" for p, n in rd["resistance"]) or "none nearby (at highs)"))
    if rd["patterns"]:
        out.append("- Recent candles: " + "; ".join(f"{d} {p}" for d, p in rd["patterns"]))
    out.append(f"- A 2-ATR protective stop for a long would sit near {rd['atr_stop']:.2f}.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="+")
    ap.add_argument("--days", type=int, default=250)
    args = ap.parse_args()
    for s in args.symbols:
        df = data.fetch_bars(s.upper(), start="2016-01-01")
        rd = read_chart(df, s.upper())
        p = plot(df, s.upper(), rd, args.days)
        print(format_reading(rd))
        print(f"Chart: {p}\n")


if __name__ == "__main__":
    main()

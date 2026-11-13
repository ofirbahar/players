"""Trading strategies.

Every strategy takes the data dict from data.fetch_universe (field -> dates x symbols)
and returns target portfolio weights (dates x symbols), long-only, summing to <= 1.
The weight on day t is decided with information up to day t's close and is held
over day t+1 (the backtester does the shift), so there is no look-ahead.
"""
import numpy as np
import pandas as pd

from . import indicators as ind


def _equal(signal):
    """Per-symbol 0..1 signal -> weights, each symbol gets 1/N of capital."""
    sig = signal.astype(float).fillna(0.0).clip(0, 1)
    return sig / sig.shape[1]


def _hold(entry, exit_):
    """Stateful position: go long on entry, stay long until exit."""
    state = pd.DataFrame(np.nan, index=entry.index, columns=entry.columns)
    state[entry.fillna(False)] = 1.0
    state[exit_.fillna(False) & ~entry.fillna(False)] = 0.0
    return state.ffill().fillna(0.0)


def _month_ends(index):
    s = pd.Series(index, index=index)
    return s.groupby([index.year, index.month]).transform("max") == s


# ---------- benchmarks ----------

def buy_and_hold(d):
    return _equal(d["close"].notna())


# ---------- trend following ----------

def sma_cross(d, fast=50, slow=200):
    c = d["close"]
    return _equal(ind.sma(c, fast) > ind.sma(c, slow))


def price_above_sma(d, n=200):
    c = d["close"]
    return _equal(c > ind.sma(c, n))


def ema_cross(d, fast=12, slow=26):
    c = d["close"]
    return _equal(ind.ema(c, fast) > ind.ema(c, slow))


def macd_trend(d):
    line, sig, _ = ind.macd(d["close"])
    return _equal(line > sig)


def donchian_breakout(d, entry=55, exit_=20):
    """Turtle-style: buy a new 55-day high, sell a new 20-day low."""
    c, h, l = d["close"], d["high"], d["low"]
    _, upper = ind.donchian(h, l, entry)
    lower, _ = ind.donchian(h, l, exit_)
    return _equal(_hold(c > upper.shift(), c < lower.shift()))


def adx_trend(d, n=14, threshold=20):
    adx, pdi, mdi = ind.adx(d["high"], d["low"], d["close"], n)
    return _equal((adx > threshold) & (pdi > mdi))


def ts_momentum(d, lookback=252):
    """Time-series momentum: long if the last 12 months' return is positive."""
    c = d["close"]
    return _equal(c / c.shift(lookback) - 1 > 0)


# ---------- mean reversion ----------

def rsi2_reversion(d):
    """Connors RSI(2): buy deep short-term dips inside a long-term uptrend."""
    c = d["close"]
    entry = (c > ind.sma(c, 200)) & (ind.rsi(c, 2) < 10)
    exit_ = (c > ind.sma(c, 5)) | (c < ind.sma(c, 200))
    return _equal(_hold(entry, exit_))


def bollinger_reversion(d, n=20, k=2.0):
    c = d["close"]
    lower, mid, _ = ind.bollinger(c, n, k)
    return _equal(_hold(c < lower, c > mid))


def stochastic_reversion(d):
    c = d["close"]
    k, _ = ind.stochastic(d["high"], d["low"], c)
    entry = (k < 20) & (c > ind.sma(c, 200))
    exit_ = (k > 80) | (c < ind.sma(c, 200))
    return _equal(_hold(entry, exit_))


# ---------- cross-sectional / rotation ----------

def momentum_rotation(d, lookback=126, top=3, trend_filter=True):
    """Each month, hold the top-N symbols by 6-month return (only if they're in an uptrend)."""
    c = d["close"]
    mom = c / c.shift(lookback) - 1
    rank = mom.rank(axis=1, ascending=False)
    pick = (rank <= top) & (mom > 0)
    if trend_filter:
        pick &= c > ind.sma(c, 200)
    w = pick.astype(float) / top
    me = _month_ends(c.index)
    w[~me.values] = np.nan
    return w.ffill().fillna(0.0)


def dual_momentum(d, lookback=252, top=1):
    """Antonacci-style: hold the strongest asset if its momentum is positive, else cash."""
    return momentum_rotation(d, lookback=lookback, top=top, trend_filter=False)


def low_vol_rotation(d, lookback=63, top=4):
    """Each month, hold the least volatile symbols that are above their 200-day average."""
    c = d["close"]
    vol = c.pct_change().rolling(lookback).std()
    vol = vol.where(c > ind.sma(c, 200))
    pick = vol.rank(axis=1, ascending=True) <= top
    w = pick.astype(float) / top
    w[~_month_ends(c.index).values] = np.nan
    return w.ffill().fillna(0.0)


# ---------- overlays / combinations ----------

def vol_target(weights, d, target=0.15, lookback=20, cap=1.0):
    """Scale exposure so each position targets a given annualised volatility."""
    vol = ind.realized_vol(d["close"], lookback)
    scale = (target / vol).clip(upper=cap).fillna(0)
    return weights * scale


def trend_ensemble(d):
    """Average of several trend signals: smoother and less parameter-dependent."""
    parts = [sma_cross(d), price_above_sma(d), ema_cross(d), donchian_breakout(d), ts_momentum(d)]
    return sum(parts) / len(parts)


def trend_ensemble_voltarget(d):
    return vol_target(trend_ensemble(d), d)


def trend_plus_reversion(d):
    """Half trend ensemble, half RSI(2) dip-buying: two return streams that behave differently."""
    return 0.5 * trend_ensemble(d) + 0.5 * rsi2_reversion(d)


STRATEGIES = {
    "buy_and_hold": buy_and_hold,
    "sma_cross_50_200": sma_cross,
    "price_above_sma200": price_above_sma,
    "ema_cross_12_26": ema_cross,
    "macd_trend": macd_trend,
    "donchian_55_20": donchian_breakout,
    "adx_trend": adx_trend,
    "ts_momentum_12m": ts_momentum,
    "rsi2_reversion": rsi2_reversion,
    "bollinger_reversion": bollinger_reversion,
    "stochastic_reversion": stochastic_reversion,
    "momentum_rotation_top3": momentum_rotation,
    "dual_momentum": dual_momentum,
    "low_vol_rotation": low_vol_rotation,
    "trend_ensemble": trend_ensemble,
    "trend_ensemble_voltarget": trend_ensemble_voltarget,
    "trend_plus_reversion": trend_plus_reversion,
}

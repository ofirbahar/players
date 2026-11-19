"""Technical indicators. All accept pandas Series/DataFrames and return the same shape."""
import numpy as np
import pandas as pd


def sma(x, n):
    return x.rolling(n, min_periods=n).mean()


def ema(x, n):
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100).where(up.notna())


def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(close, n=20, k=2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    return mid - k * sd, mid, mid + k * sd


def true_range(high, low, close):
    pc = close.shift()
    return np.maximum(high - low, np.maximum((high - pc).abs(), (low - pc).abs()))


def atr(high, low, close, n=14):
    return true_range(high, low, close).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def donchian(high, low, n=20):
    return low.rolling(n, min_periods=n).min(), high.rolling(n, min_periods=n).max()


def adx(high, low, close, n=14):
    up, dn = high.diff(), -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    tr = atr(high, low, close, n)
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def stochastic(high, low, close, n=14, d=3):
    ll, hh = low.rolling(n).min(), high.rolling(n).max()
    k = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    return k, k.rolling(d).mean()


def obv(close, volume):
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def realized_vol(close, n=20):
    return close.pct_change().rolling(n).std() * np.sqrt(252)

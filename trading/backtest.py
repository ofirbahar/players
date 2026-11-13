"""Vectorised daily backtester with transaction costs and standard performance metrics."""
import numpy as np
import pandas as pd


def run(weights, close, cost_bps=5.0):
    """Daily portfolio returns. weights[t] is held over day t+1; costs are charged on turnover."""
    rets = close.pct_change().fillna(0.0)
    w = weights.reindex(close.index).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    turnover = (w - w.shift(1).fillna(0.0)).abs().sum(axis=1).shift(1).fillna(0.0)
    port = (held * rets).sum(axis=1) - turnover * cost_bps / 1e4
    return port, turnover


def metrics(r, turnover=None):
    r = r.dropna()
    if len(r) < 2:
        return {}
    eq = (1 + r).cumprod()
    years = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    downside = r[r < 0].std() * np.sqrt(252)
    dd = eq / eq.cummax() - 1
    out = {
        "CAGR": cagr,
        "Vol": vol,
        "Sharpe": sharpe,
        "Sortino": r.mean() * 252 / downside if downside > 0 else np.nan,
        "MaxDD": dd.min(),
        "Calmar": cagr / abs(dd.min()) if dd.min() < 0 else np.nan,
        "TotalRet": eq.iloc[-1] - 1,
        "PctDaysInvested": float((r != 0).mean()),
    }
    if turnover is not None:
        out["TurnoverPerYr"] = turnover.loc[r.index].sum() / years
    return out

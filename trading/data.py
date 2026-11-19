"""Download daily bars from Alpaca market data, with a local CSV cache."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from . import config


def fetch_bars(symbol, start="2016-01-01", end=None, refresh=False):
    """Split/dividend-adjusted daily OHLCV for one symbol, indexed by date."""
    config.CACHE_DIR.mkdir(exist_ok=True)
    cache = config.CACHE_DIR / f"{symbol}_{start}.csv"
    if cache.exists() and not refresh:
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        if len(df) and (pd.Timestamp.now() - df.index[-1]).days < 1:
            return df
    if end is None:  # free plans can query SIP data older than 15 minutes
        end = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, token = [], None
    while True:
        params = {"symbols": symbol, "timeframe": "1Day", "start": start, "end": end,
                  "limit": 10000, "adjustment": "all", "feed": "sip"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{config.DATA_URL}/stocks/bars", headers=config.headers(), params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        rows += js.get("bars", {}).get(symbol, [])
        token = js.get("next_page_token")
        if not token:
            break
    if not rows:
        raise ValueError(f"No data for {symbol}")
    df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df.index = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
    df = df[["open", "high", "low", "close", "volume"]]
    df.to_csv(cache)
    return df


def fetch_universe(symbols, start="2016-01-01", refresh=False):
    """Dict of field -> DataFrame (dates x symbols)."""
    frames = {s: fetch_bars(s, start, refresh=refresh) for s in symbols}
    out = {}
    for field in ["open", "high", "low", "close", "volume"]:
        out[field] = pd.DataFrame({s: f[field] for s, f in frames.items()}).sort_index()
    return out

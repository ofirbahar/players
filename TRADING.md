# Trading research and paper trading (Alpaca)

A small toolkit to test trading strategies honestly, read charts, and trade the result on an
Alpaca **paper** account.

## Setup

```bash
pip install -r requirements.txt
```

Credentials are read from environment variables, or from a local `.env` file (gitignored, never commit it):

```
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2
```

## 1. Strategy research: `python -m trading.research`

Backtests 17 strategies on a 12-ETF universe (US/intl stocks, bonds, gold, sectors) with daily
adjusted data from 2016, 5 bps trading costs and next-day execution (no look-ahead).

| Family | Strategies |
|---|---|
| Benchmark | buy and hold (equal weight) |
| Trend following | 50/200 SMA cross, price above 200-day SMA, 12/26 EMA cross, MACD, Donchian 55/20 breakout (Turtle), ADX trend, 12-month time-series momentum |
| Mean reversion | Connors RSI(2), Bollinger band reversion, stochastic oversold in uptrend |
| Rotation | top-3 momentum rotation, dual momentum, low-volatility rotation |
| Combinations | trend ensemble, ensemble with volatility targeting, trend + mean reversion |

It picks a strategy on **2017–2021** data with a fixed rule (best Sharpe without a worse drawdown than
buy and hold) and then reports how every strategy did on **2022 onward**, data the choice never saw.
Output: `reports/strategy_report.md`, `reports/equity_curves.png`, `reports/chosen_strategy.json`.

## 2. Chart reading: `python -m trading.chart SPY NVDA`

Draws candlesticks with 50/200-day averages, Bollinger bands, volume, RSI and MACD, marks support and
resistance levels, and prints a reading: trend state and slope, golden/death crosses, ADX trend strength,
RSI overbought/oversold and divergences, MACD crosses, Bollinger squeezes, volume confirmation,
candlestick patterns (doji, hammer, shooting star, engulfing, wide-range bars) and a 2-ATR stop level.
Charts go to `reports/chart_<SYMBOL>.png`.

## 3. Paper trading: `python -m trading.live [--strategy NAME] [--execute]`

Computes today's target weights from completed daily bars, compares them with the account's positions
and sends market orders for the difference (sells first). Without `--execute` it only prints the plan.
It refuses to run against a non-paper endpoint unless `--allow-live` is passed. Every run is logged to
`reports/trade_log.jsonl`. Run it once a day after the close (or before the open).

## Caveats

- Backtests are not forecasts. Five years in-sample and ~5 out-of-sample is short; results depend on the universe.
- Testing many strategies inflates the best in-sample result; the out-of-sample table is the honest one.
- Costs are modelled simply (no slippage beyond 5 bps, no taxes, no borrow costs).

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

## 4. Day trading: `python -m trading.intraday` and `python -m trading.daybot`

`trading.intraday` backtests minute-level strategies on 8 liquid names (QQQ, AAPL, MSFT, NVDA, AMZN,
META, TSLA, AMD) over six months: trading every minute, opening-range breakout, VWAP reversion,
EMA momentum, RSI reversion, and an adaptive switcher that picks trend-following or reversion
from the market's efficiency ratio. Results (May–Nov 2026, 2 bps per side for spread and slippage):

- Trading every minute lost about 99%: ~400 round trips a day per stock, each paying the spread.
- Every strategy lost money after costs, in both the first 60% of days and the last 40%.
- Only VWAP reversion was profitable before costs in both periods (~4 bps a day).
- The adaptive switcher was worst of the rest: switching regimes adds trades, and trades cost money.

`trading.daybot` trades the strictest VWAP-reversion setting live on the paper account: every
minute it checks for a move 3.5 standard deviations away from VWAP (after 10:30am) and fades it,
exiting near VWAP. $1,000 per stock, integer shares (so it can short), a $150 daily loss stop,
flat by 15:55 ET, paper endpoint only. Expect it to lose a little on average: it exists to watch
live behaviour, not because it has a proven edge. Logs go to `reports/daybot_log.jsonl`.
It must run on a machine that stays on through the trading day.

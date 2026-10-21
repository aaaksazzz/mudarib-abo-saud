# Standalone Binance USDⓈ-M Futures backtest

This research harness is intentionally isolated from the SMART TRADING PRO runtime. It does not import the app, change app endpoints, or place orders.

## Run outside the website

Use the GitHub Actions workflow **Standalone Futures Backtest** (Actions tab) and select **Run workflow**. It fetches public Binance USD-M USDT perpetual 15m candles for the previous 180 days by default, tests every currently trading USDT perpetual it can fetch, and publishes CSV/Markdown results as a downloadable workflow artifact.

Optional workflow inputs: days (default 180), fee bps per side (default 5), slippage bps per side (default 2). Funding is not included in this first version, so results must not be treated as fully realized futures returns.

## Strategies screened

- Trend pullback (EMA20/50/200)
- Breakout with relative volume
- RSI mean-reversion baseline

Signals are generated from closed candles and positions/returns are applied from the following open. The 70/30 chronological split is reported as train/test. Costs are deducted on position changes. This is a research screen, not a live trading system. Never call a strategy successful from in-sample metrics alone.

## Outputs

- `results/per_symbol.csv`
- `results/summary.csv`
- `results/report.md`

All results include the actual fetched universe and failures. Missing symbols or API errors are reported, not silently treated as tested.

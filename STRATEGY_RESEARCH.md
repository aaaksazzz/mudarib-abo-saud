# Strategy integration and research notes

## What was integrated
The signal builder now requires agreement between its existing method-confluence score and `strategy_engine_v2.evaluate_v2` before publishing a signal. The stricter gate combines:
- Current and higher-timeframe trend alignment (EMA structure).
- Liquidity sweep and close back through the prior 20-candle level.
- ATR-based stop placement and a cap on excessive stop distance.
- Minimum estimated net reward/risk after a configurable round-trip cost assumption.
- A suggested risk budget capped at 0.5% per trade; this is a sizing rule, not a guarantee of maximum realized loss.

The signal side is no longer inverted after the legacy directional score. Conflicting legacy and strategy directions are rejected. Targets are based on the strategy stop distance at 2R, 2.5R and 3R.

## Research inspiration
- Time-series momentum has been documented across asset classes; crypto-specific evidence is mixed and regime-dependent.
- Research on crypto momentum documents severe tail events and momentum crashes, supporting explicit volatility-aware risk controls rather than assuming a trend signal is safe.
- A 2023 study using nearly 3,000 cryptocurrencies found price-based signals more useful at short horizons and volume-based information more useful at longer horizons. This supports using price structure for entry and volume as confirmation, not as a standalone signal.
- The 2025 paper “Cryptocurrency momentum has (not) its moments” highlights severe crash risk in crypto momentum strategies.

References:
- Borgards (2021), “Dynamic time series momentum of cryptocurrencies,” North American Journal of Economics and Finance: https://www.sciencedirect.com/science/article/pii/S1062940821000590
- Grobys et al. (2025), “Cryptocurrency momentum has (not) its moments,” Financial Markets and Portfolio Management: https://link.springer.com/article/10.1007/s11408-025-00474-9
- “Trend-based forecast of cryptocurrency returns” (2023), Economic Modelling: https://www.sciencedirect.com/science/article/pii/S0264999323001359
- CFTC advisory on AI trading bots and guaranteed-return claims: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/AITradingBots.html

## Important limits
These papers do not validate this exact strategy or prove a win rate for it. No historical test has been run by this change. The cost assumption is a placeholder and must be calibrated per market, venue, spread, funding, and timeframe. Yahoo Finance quotes/candles can be delayed. This is signal generation only, not order execution. Run syntax and integration tests, then a fee/slippage-aware walk-forward backtest and paper trading before live use.

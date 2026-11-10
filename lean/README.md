# LEAN research engine (isolated)

This folder is an **offline research/backtest scaffold**, not the production signal service.
It does not place orders, connect to a brokerage, or change the Flask runtime.

## Why it is isolated
The current Northflank web service is 0.2 vCPU / 512 MB. LEAN's documented local workflow runs inside Docker and its local platform documentation recommends at least 4 GB RAM and 60 GB disk. Do not install LEAN inside the web container or add it to the Flask requirements.

## Requirements
- A separate Linux/Windows/macOS machine or a dedicated worker with Docker.
- LEAN CLI: `pip install lean`.
- A QuantConnect organization/workspace for CLI workflows; the current CLI documentation says local backtests require an organization on a paid tier.
- Historical data for each asset class. LEAN does not magically provide free complete data for every exchange. Saudi equities and specific CFD/futures feeds need a verified data source before they can be evaluated.

## Run
From a machine with Docker and LEAN CLI installed:
1. `lean login` and `lean init` (follow QuantConnect's CLI setup).
2. Copy this folder into the LEAN workspace as a project, or run the CLI against this project folder.
3. Run `lean backtest lean` from the repository root (or `lean backtest .` from this folder).
4. Review the generated backtest statistics and trades before considering any signals.

Official instructions:
- https://www.quantconnect.com/docs/v2/lean-cli/key-concepts/getting-started
- https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment

## Strategy baseline
- Closed-bar only.
- SMA(200) directional filter.
- ATR(14) stop distance.
- Three gross targets at 1R, 2R and 3R.
- No order submission; it only records candidate signals.
- The score is a confluence score, **not** a win probability.

## Current limitations
The sample algorithm supports one configured symbol per run and the common Crypto, Equity, and Forex security types. It is not yet wired to SMART TRADING PRO's market universe/API. Futures, Binance Alpha, Tadawul, and broker-specific instruments require separate symbol mapping and validated data subscriptions. Do not present results from this sample as a verified edge or as live recommendations.

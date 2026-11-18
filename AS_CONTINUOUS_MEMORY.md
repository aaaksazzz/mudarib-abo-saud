# AS Continuous Memory

Fingerprint: `AS-CONTINUOUS-MEMORY-DAILY-V2`

The AS application runs its research-memory cycle every 24 hours at **03:07 Saudi time** (00:07 UTC), using the same persistent application database as the paper-trade journal. The scheduler is part of the application process; it is not a separate GitHub Actions cache job.

## What is recorded

- Only paper trades that reach a fully resolved `tp3_hit` or full `stopped` status.
- Unique trade ID, strategy identifier, market, symbol, timeframe, side, resolution status and gross result in R.
- Results are aggregated by strategy, market and timeframe and saved in the application `Setting` store under `as-learning:latest-report`.
- Regime is currently stored as `unknown` because the production trade record does not yet persist a verified regime label; the report does not pretend otherwise.

## Result integrity

- A full TP3 result is calculated as gross R from the trade's actual TP3 distance divided by its entry-to-stop risk.
- A full stop is recorded as `-1R`. Fees, slippage and funding are not currently available in the trade ledger, so these are gross results, not net returns.
- A path that reaches TP1/TP2 and later stops is **not scored yet**. The app does not currently record partial position sizing or actual partial exit fills, so assigning it a profitable R result would be invented.
- Expired, superseded, still-open, or otherwise unresolved trades are never counted as wins or losses.
- A unique database constraint on trade ID prevents duplicate learning records.

## Persistence and schedule

The memory lives in the application's configured database. Production must use a persistent `DATABASE_URL` database or a persistent `DATA_DIR` volume. If the service uses an ephemeral filesystem/database, the memory will not survive a replacement or redeploy; configure persistent storage before relying on long-term learning.

The cycle runs at 00:07 UTC (03:07 Asia/Riyadh). Market scanning remains a separate 15-minute application job and is not replaced by the daily memory cycle.

## Safety boundaries

- Paper/manual records only; no live order execution.
- The worker does not fetch new market data, news, social feeds, order books or options chains.
- It summarizes historical outcomes; it does not train model weights or automatically change production strategy parameters.
- Small samples are descriptive only and do not establish a profitable edge.

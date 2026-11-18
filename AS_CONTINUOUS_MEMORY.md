# AS Continuous Memory

Fingerprint: `AS-CONTINUOUS-MEMORY-HOURLY-V1`

The scheduled GitHub Actions worker runs once per hour (and can be manually dispatched). It keeps a SQLite memory database in the Actions cache and publishes a compact report at `data/as_learning/latest_report.json`.

## What it remembers
- Every uniquely identified, resolved paper-trade experience supplied to `data/as_learning/paper_experiences.jsonl`.
- Strategy, market, timeframe and regime performance aggregates.
- Sample count, wins/losses, net expectancy in R and profit factor.

## Paper experience input
One JSON object per line. Only resolved outcomes are accepted:

```json
{"experience_id":"paper-000001","recorded_at":"2026-11-18T12:00:00Z","strategy_id":"trend_pullback_v1","market":"futures","symbol":"BTCUSDT","timeframe":"15m","regime":"trend","side":"BUY","net_r":1.8,"outcome":"win"}
```

The producer must record actual simulated outcomes after fees/slippage/funding where relevant. Do not insert hypothetical or unresolved trades.

## Important limits
- The hourly worker is a scheduled research-memory cycle, not a continuously running market-data service.
- It does not fetch exchange candles, news, social feeds, options chains or order books.
- It does not train an ML model or automatically modify production strategy parameters.
- SQLite persistence here uses GitHub Actions cache; cache is best-effort and not a substitute for a production persistent database. The deployed app should eventually use its own persistent database volume.
- No live order execution. No strategy can be called profitable from small samples.

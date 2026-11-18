# AS Market Deception & Trap Recognition Academy

**Module fingerprint:** `AS-MARKET-DECEPTION-LAB-V1-20261118`

## Mission
Teach AS to recognize chart-visible deceptive price behaviour and protect its paper signals from common traps. This module is defensive and analytical: it does not generate spoof orders, manipulate markets, coordinate accounts, or advise evading market rules.

## Chart-visible patterns to study

1. **Bull trap / false upside breakout** — price trades above a prior range or swing high, then closes back below it. Evidence: breakout level, close location, upper wick, follow-through failure.
2. **Bear trap / false downside breakout** — price trades below a prior range or swing low, then closes back above it. Evidence: downside excursion, close recovery, lower wick.
3. **Buy-side / sell-side liquidity sweep** — a prior swing or equal-high/low pool is pierced and price rejects the area. A sweep is a price event, not proof of a malicious actor.
4. **Failed breakout / failed breakdown** — a completed close outside a range is followed by a completed close back inside.
5. **Stop-run-shaped move** — rapid penetration of a visible swing level followed by rejection. Treat as a possible liquidity event, not a verified stop-loss hunt.
6. **Wick rejection / exhaustion** — long wick relative to candle range, especially with elevated volume and a small real body.
7. **Absorption proxy** — unusually high volume with limited price progress or a strong rejection wick. OHLCV only provides a proxy; actual absorption requires trades/order-book data.
8. **Pump-and-dump-shaped move** — rapid price/volume expansion followed by a sharp reversal. The chart shape cannot establish coordination, intent, or illegality.
9. **Dump-and-recovery-shaped move** — rapid downside expansion followed by a sharp reversal.
10. **Liquidity inducement / bait level** — repeated or conspicuous highs/lows that may attract breakout entries before a reversal. Requires context and must not be labelled manipulation solely from equal levels.
11. **Range manipulation look-alikes** — repeated false breaks at range edges, compression followed by wick sweeps, and low-volume drift that fails on participation.
12. **News/event whipsaw** — sharp two-sided movement around scheduled or unscheduled news. Requires a timestamped economic/news calendar to attribute event context.
13. **Gap and opening traps** — gap-up/gap-down that fails to hold, opening-range fakeout, and gap fill. Requires session-aware data; do not apply blindly to 24/7 markets.
14. **Derivatives-driven pressure clues** — funding extremes, open-interest expansion/contraction, liquidation clusters, basis dislocations and options gamma/expiry effects. These need market-specific derivatives feeds and are not inferred from candles alone.

## Manipulation mechanisms: what AS must understand, not imitate

- Spoofing and layering: displayed orders placed and cancelled to create a false impression of supply/demand.
- Wash trading: trades that create artificial volume without genuine beneficial ownership change.
- Quote stuffing / fleeting liquidity: excessive message activity that distorts the visible book.
- Momentum ignition / coordinated pump campaigns: activity intended to trigger follow-on trading.
- Marking the close / settlement-window pressure.
- Cross-venue price and volume distortions.

**Evidence boundary:** OHLCV candles cannot prove spoofing, wash trading, account coordination, intent, or who placed/cancelled orders. These require order-book event history, trade-level data, venue surveillance information, and sometimes regulatory investigation. AS must say “not observable from current data” instead of making an accusation.

## Simple extraction policy
- Run the trap detector as an annotation layer alongside the existing entry models.
- Prefer confirmed candle closes over intrabar wicks.
- Add a visible warning and modest quality adjustment when the proposed direction is directly exposed to a fresh trap.
- Do not turn every trap warning into a hard rejection. Preserve valid opportunities and show the evidence.
- Keep the existing structural stop and 1R/2R/3R targets.
- Do not call a quality score a win probability.
- Record the pattern, evidence, market, symbol, timeframe, timestamp, signal direction, and eventual paper outcome for later evaluation.

## Required future data adapters
- Trade prints with aggressor side for delta/CVD and absorption research.
- Order-book snapshots plus event-level add/cancel/execute updates for spoofing/layering research.
- Funding, open interest, liquidation and basis feeds for futures.
- Options chain, implied volatility, gamma and expiry calendar for options-related pressure.
- Timestamped news and economic calendar for event whipsaws.
- Session-aware corporate actions and opening/closing auction data for equities.

## Validation plan
- Label historical examples without look-ahead bias.
- Test across assets, venues, sessions and timeframes.
- Measure precision, recall, false-alarm rate and post-signal adverse excursion.
- Compare signal outcomes with and without the warning layer after fees and slippage.
- Keep a holdout period and walk-forward validation.
- Do not automatically tune thresholds on the same samples used to report performance.

## Current implementation boundary
The V1 code detects chart-visible false breakouts / sweeps, failed range breaks, an absorption/exhaustion proxy and simple pump/dump-shaped reversals using completed OHLCV bars. It annotates candidate signals and does not claim to identify spoofing, wash trading or coordinated manipulation. Those remain unavailable until dedicated data adapters exist.

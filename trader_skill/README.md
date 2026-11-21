# AS Trader Skill Suite

This directory imports the eleven MIT-licensed tools from
[Jakeschincariol/trader-skill](https://github.com/Jakeschincariol/trader-skill).
The upstream license is preserved in `LICENSE`; upstream source files and skill
guides remain under their original skill names.

## Included skills

1. **copycat** — rebuilds a US institutional investor's reported 13F portfolio.
2. **news** — watches Yahoo Finance headlines and SEC company filings.
3. **budget** — allocates a user-provided budget with cash and position caps.
4. **Pelosi / Congress** — parses public House PTR disclosures.
5. **analyst** — reads SEC XBRL company facts and earnings filings.
6. **screener** — filters US company metrics against explicit rules.
7. **risk** — validates proposed stock orders against configured limits.
8. **broker ticket** — formats and logs proposed tickets; AS does not connect it
   to a broker or submit orders.
9. **tax lots** — calculates US-stock cost-basis lots and wash-sale checks.
10. **alerts** — price alerts and NYSE calendar / quote helper.
11. **rebalance** — computes portfolio drift and proposes rebalance orders.

## AS safety policy

- Paper / research only. No Binance, brokerage, wallet or exchange credentials.
- No live broker integration, order submission, cancellation or auto execution.
- The broker ticket tool is retained as a proposal / audit utility only.
- Crypto, futures, FX, Saudi shares and US contracts are **not** supported by
  the upstream US-equity tax, 13F, SEC XBRL or Alpaca order schemas. Do not
  apply those rules to those markets.
- 13F data is delayed, partial and long-only. It is not a live portfolio feed.
- Congress disclosures are delayed public records, not insider information.
- SEC endpoints require a real SEC User-Agent name and email. Never invent
  those values or put secrets in source control.
- US tax lot and wash-sale calculations are US-specific arithmetic, not tax
  advice and not a substitute for a tax professional.

## Market coverage inside AS

| AS market | Applicable modules |
| --- | --- |
| Binance Spot / Futures / Alpha | generic budget math only after asset-aware adaptation; price alerts and risk limits require market-specific rules |
| US stocks | all relevant equity modules; SEC 13F, XBRL, screener, Congress PTR, US tax-lot tools |
| US contracts | price alerts and research only; upstream equity order/risk assumptions do not transfer |
| Saudi shares | generic watchlist / alert concepts only; SEC and US tax modules do not apply |
| Forex & Gold | generic alerts / risk concepts only; upstream stock screener, 13F and US tax modules do not apply |

The imported scripts are kept as isolated research utilities so their US-stock
assumptions cannot silently become universal rules. Integration into AS routes,
market adapters, persistence, and automated scheduling must be done with
market-specific validation before those tools are exposed in the live UI.

## Running a tool manually

Run from the repository root, using Python 3.8+:

```bash
python3 trader_skill/trader-budget/size.py --help
python3 trader_skill/trader-risk/check.py --help
python3 trader_skill/trader-alerts/alerts.py --help
python3 trader_skill/trader-analyst/facts.py --help
python3 trader_skill/trader-screener/screen.py --help
python3 -m unittest discover -s trader_skill/tests -v
```

The last test command becomes usable after the upstream test suite is imported.
Do not run SEC tools until a valid User-Agent is configured locally.

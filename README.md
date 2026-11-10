# SMART TRADING PRO

Clean rebuild of the multi-market research terminal.

## Run

`pip install -r requirements.txt`

`python app.py`

## Markets

Binance Spot and USD-M Futures; US equities; US options underlyings; Saudi equities; FX and metals.

## Method

Weekly direction -> daily confirmation -> 4h confirmation -> 15m entry. Incomplete or unavailable candles do not produce a signal. Performance statistics are based only on user-recorded closed trades.

## Important

This is informational/paper-trading software. It does not place orders. Public market data providers may rate-limit or return incomplete coverage. Validate feeds before relying on them.

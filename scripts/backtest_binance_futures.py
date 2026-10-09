#!/usr/bin/env python3
"""Backtest one BUY-only 15m strategy on all eligible Binance USD-M perpetuals. No orders are submitted."""
import concurrent.futures, csv, datetime as dt, io, json, os, urllib.request, urllib.parse, zipfile

BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com"]
DATA_BASE = "https://data.binance.vision"
DAYS, MIN_VOLUME, FEE, INTERVAL, LOOKBACK, TARGET_LOOKBACK = 30, 1_000_000, 0.0005, "15m", 20, 100

def fetch_url(url, timeout=35):
    req = urllib.request.Request(url, headers={"User-Agent": "SMART-TRADING-PRO-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def api(path, **params):
    query = "?" + urllib.parse.urlencode(params) if params else ""
    errors = []
    for base in BASES:
        try:
            return json.loads(fetch_url(base + path + query).decode())
        except Exception as exc:
            errors.append(base + ": " + str(exc))
    raise RuntimeError("Binance Futures API unavailable: " + " | ".join(errors))

def load_month(symbol, year, month):
    filename = f"{symbol}-{INTERVAL}-{year}-{month:02d}.zip"
    url = f"{DATA_BASE}/data/futures/um/monthly/klines/{symbol}/{INTERVAL}/{filename}"
    try:
        with zipfile.ZipFile(io.BytesIO(fetch_url(url))) as archive:
            csv_name = next(name for name in archive.namelist() if name.endswith(".csv"))
            return list(csv.reader(io.TextIOWrapper(archive.open(csv_name), encoding="utf-8")))
    except Exception:
        return []

def historical_klines(symbol, start_ms, end_ms):
    start = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc)
    end = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc)
    months, cursor = [], start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        months.append((cursor.year, cursor.month))
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    rows = []
    for year, month in months:
        rows.extend(load_month(symbol, year, month))
    parsed = []
    for row in rows:
        try:
            opened = int(row[0])
            if start_ms <= opened <= end_ms:
                parsed.append([opened, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
        except (ValueError, IndexError):
            continue
    unique = {row[0]: row for row in parsed}
    return [unique[key] for key in sorted(unique)]

def backtest_buy_15m(rows):
    # One strategy only: buy after close breaks prior 20-candle high;
    # stop at prior 20-candle low; target at nearest prior high above entry within 100 candles.
    trades, i = [], TARGET_LOOKBACK
    while i < len(rows) - 1:
        prior, broad = rows[i-LOOKBACK:i], rows[i-TARGET_LOOKBACK:i]
        entry = rows[i][4]
        if entry <= max(c[2] for c in prior):
            i += 1
            continue
        stop = min(c[3] for c in prior)
        higher_highs = sorted({c[2] for c in broad if c[2] > entry})
        if stop <= 0 or stop >= entry or not higher_highs or (entry-stop)/entry > 0.15:
            i += 1
            continue
        target = higher_highs[0]
        exit_price, exit_i, outcome = rows[-1][4], len(rows)-1, "period_end"
        for j in range(i+1, len(rows)):
            high, low = rows[j][2], rows[j][3]
            if low <= stop:  # conservative if both levels are touched in one candle
                exit_price, exit_i, outcome = stop, j, "loss"
                break
            if high >= target:
                exit_price, exit_i, outcome = target, j, "win"
                break
        net = (exit_price-entry)/entry - 2*FEE
        trades.append({"entry_time": rows[i][0], "entry": entry, "target": target, "stop": stop,
                       "exit": exit_price, "exit_time": rows[exit_i][0], "outcome": outcome, "net_pct": net*100})
        i = exit_i + 1
    equity = peak = 1.0
    drawdown = 0.0
    for trade in trades:
        equity *= max(0.0, 1 + trade["net_pct"]/100)
        peak = max(peak, equity)
        if peak:
            drawdown = max(drawdown, (peak-equity)/peak)
    wins, count = sum(t["net_pct"] > 0 for t in trades), len(trades)
    return {"trades": count, "wins": wins, "losses": count-wins,
            "win_rate_pct": round(wins*100/count, 2) if count else 0,
            "net_return_compounded_pct": round((equity-1)*100, 2),
            "max_drawdown_pct": round(drawdown*100, 2),
            "avg_trade_net_pct": round(sum(t["net_pct"] for t in trades)/count, 4) if count else 0}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    end_ms, start_ms = int(now.timestamp()*1000), int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    info, tickers = api("/fapi/v1/exchangeInfo"), api("/fapi/v1/ticker/24hr")
    volumes = {x["symbol"]: float(x.get("quoteVolume", 0)) for x in tickers}
    stable = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"}
    symbols = sorted(s["symbol"] for s in info["symbols"]
        if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
        and s.get("quoteAsset") == "USDT" and s.get("baseAsset") not in stable
        and volumes.get(s["symbol"], 0) > MIN_VOLUME)
    report = {"period_days": DAYS, "started_utc": now.isoformat(),
        "market": "Binance USD-M USDT perpetual futures",
        "strategy": "BUY only on 15m; entry after close above prior 20-candle high; stop at prior 20-candle low; target nearest historical high above entry within prior 100 candles",
        "volume_filter": "24h quote volume > 1,000,000 USDT", "timeframe": INTERVAL,
        "fees_each_side_pct": FEE*100, "same_candle_rule": "stop wins if stop and target touch in same candle",
        "eligible_symbols": len(symbols), "symbols_tested": 0, "candles_loaded": 0,
        "aggregate": {"trades": 0, "wins": 0, "losses": 0}, "per_symbol": {}, "failed": []}
    def run(symbol):
        candles = historical_klines(symbol, start_ms, end_ms)
        return symbol, len(candles), backtest_buy_15m(candles)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(run, symbol): symbol for symbol in symbols}
        for future in concurrent.futures.as_completed(futures):
            symbol = futures[future]
            try:
                _, count, stats = future.result()
                report["symbols_tested"] += 1
                report["candles_loaded"] += count
                report["per_symbol"][symbol] = stats
                for key in ("trades", "wins", "losses"):
                    report["aggregate"][key] += stats[key]
            except Exception as exc:
                report["failed"].append({"symbol": symbol, "error": str(exc)[:200]})
    total = report["aggregate"]["trades"]
    report["aggregate"]["win_rate_pct"] = round(report["aggregate"]["wins"]*100/total, 2) if total else 0
    report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results", exist_ok=True)
    with open("backtest-results/latest.json", "w", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({k:v for k,v in report.items() if k != "per_symbol"}, ensure_ascii=False, indent=2))
    print("TOP RESULTS")
    for symbol, stats in sorted(report["per_symbol"].items(),
            key=lambda item: (item[1]["net_return_compounded_pct"], item[1]["win_rate_pct"]), reverse=True)[:25]:
        print(symbol, json.dumps(stats, ensure_ascii=False))

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""30-day Binance Spot backtest for one standalone signal strategy. No live orders."""
import concurrent.futures, csv, datetime as dt, io, json, os, urllib.parse, urllib.request, zipfile

BASES = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com"]
DATA_BASE = "https://data.binance.vision"
DAYS, MIN_VOLUME, FEE, INTERVAL = 30, 1_000_000, 0.001, "15m"
ENTRY_LOOKBACK, TARGET_LOOKBACK = 20, 100
STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "TRY", "BRL", "USDD"}

def fetch_url(url, timeout=35):
    req = urllib.request.Request(url, headers={"User-Agent": "SMART-TRADING-PRO-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()

def api(path, **params):
    query = "?" + urllib.parse.urlencode(params) if params else ""
    errors = []
    for base in BASES:
        try:
            data = json.loads(fetch_url(base + path + query).decode())
            if isinstance(data, dict) and data.get("code") and data.get("msg"):
                errors.append(base + ": " + str(data.get("msg")))
                continue
            return data
        except Exception as exc:
            errors.append(base + ": " + str(exc))
    raise RuntimeError("Binance Spot API unavailable: " + " | ".join(errors))

def load_month(symbol, year, month):
    filename = f"{symbol}-{INTERVAL}-{year}-{month:02d}.zip"
    url = f"{DATA_BASE}/data/spot/monthly/klines/{symbol}/{INTERVAL}/{filename}"
    try:
        with zipfile.ZipFile(io.BytesIO(fetch_url(url))) as archive:
            csv_name = next(name for name in archive.namelist() if name.endswith(".csv"))
            return list(csv.reader(io.TextIOWrapper(archive.open(csv_name), encoding="utf-8")))
    except Exception:
        return []

def historical_klines(symbol, start_ms, end_ms):
    # Prefer the public market-data REST endpoint, paging through the full 30-day window.
    # If the endpoint is unavailable, fall back to official monthly archives.
    parsed = []
    cursor = start_ms
    try:
        while cursor <= end_ms:
            batch = api("/api/v3/klines", symbol=symbol, interval=INTERVAL,
                        startTime=cursor, endTime=end_ms, limit=1000)
            if not batch:
                break
            for row in batch:
                parsed.append([int(row[0]), float(row[1]), float(row[2]),
                               float(row[3]), float(row[4]), float(row[5])])
            next_cursor = int(batch[-1][0]) + 15 * 60 * 1000
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < 1000:
                break
        if parsed:
            unique = {row[0]: row for row in parsed}
            return [unique[key] for key in sorted(unique)]
    except Exception:
        pass
    start = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc)
    end = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc)
    months, cursor = [], start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        months.append((cursor.year, cursor.month))
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    for year, month in months:
        for row in load_month(symbol, year, month):
            try:
                opened = int(row[0])
                if start_ms <= opened <= end_ms:
                    parsed.append([opened, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
            except (ValueError, IndexError):
                continue
    unique = {row[0]: row for row in parsed}
    return [unique[key] for key in sorted(unique)]

def backtest(rows):
    # Pure arithmetic breakout on 15m candles only; symmetric long/short paper test.
    # Signal is confirmed at candle close; entry is next candle open to avoid look-ahead.
    # Stop is the opposite edge of the prior 20-candle range; target is 2R.
    trades, i = [], ENTRY_LOOKBACK
    while i < len(rows) - 1:
        prior = rows[i-ENTRY_LOOKBACK:i]
        upper = max(c[2] for c in prior)
        lower = min(c[3] for c in prior)
        close = rows[i][4]
        direction = "long" if close > upper else ("short" if close < lower else None)
        if direction is None:
            i += 1
            continue
        entry_i = i + 1
        entry = rows[entry_i][1]
        if entry <= 0 or upper <= lower:
            i += 1
            continue
        stop = lower if direction == "long" else upper
        risk = entry - stop if direction == "long" else stop - entry
        if risk <= 0 or risk / entry > 0.15:
            i += 1
            continue
        target = entry + 2*risk if direction == "long" else entry - 2*risk
        exit_price, exit_i, outcome = rows[-1][4], len(rows)-1, "period_end"
        for j in range(entry_i, len(rows)):
            high, low = rows[j][2], rows[j][3]
            if direction == "long":
                # Conservative rule: if target and stop both touched in one candle, count stop first.
                if low <= stop:
                    exit_price, exit_i, outcome = stop, j, "stop"
                    break
                if high >= target:
                    exit_price, exit_i, outcome = target, j, "target"
                    break
            else:
                if high >= stop:
                    exit_price, exit_i, outcome = stop, j, "stop"
                    break
                if low <= target:
                    exit_price, exit_i, outcome = target, j, "target"
                    break
        gross = (exit_price-entry)/entry if direction == "long" else (entry-exit_price)/entry
        net = gross - 2*FEE
        trades.append({"direction": direction, "entry_time": rows[entry_i][0], "entry": entry,
                       "target": target, "stop": stop, "exit": exit_price,
                       "exit_time": rows[exit_i][0], "outcome": outcome, "net_pct": net*100})
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
            "avg_trade_net_pct": round(sum(t["net_pct"] for t in trades)/count, 4) if count else 0,
            "long_trades": sum(t["direction"] == "long" for t in trades),
            "short_trades": sum(t["direction"] == "short" for t in trades)}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    end_ms, start_ms = int(now.timestamp()*1000), int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    info, tickers = api("/api/v3/exchangeInfo"), api("/api/v3/ticker/24hr")
    volumes = {x["symbol"]: float(x.get("quoteVolume", 0)) for x in tickers}
    symbols = sorted(s["symbol"] for s in info["symbols"]
        if s.get("status") == "TRADING" and s.get("isSpotTradingAllowed", True)
        and s.get("quoteAsset") == "USDT" and s.get("baseAsset") not in STABLES
        and volumes.get(s["symbol"], 0) > MIN_VOLUME)
    report = {"period_days": DAYS, "market": "Binance Spot USDT pairs",
        "strategy": "Single standalone math strategy: on 15m close breaks prior 20-candle high/low; enter next candle open; stop opposite edge of prior 20-candle range; target 2R; both long and short paper trades",
        "signal_timeframes": {"buy": "15m", "sell": "15m"}, "entry_rule": "next 15m candle open after breakout close", "risk_reward": "2:1", "change_check_timeframe": "15m",
        "volume_filter": "24h quote volume > 1,000,000 USDT", "timeframe": INTERVAL,
        "fee_each_side_pct": FEE*100, "same_candle_rule": "stop is counted first if both target and stop are touched",
        "eligible_symbols": len(symbols), "symbols_tested": 0, "candles_loaded": 0,
        "aggregate": {"trades": 0, "wins": 0, "losses": 0}, "per_symbol": {}, "failed": []}
    def run(symbol):
        candles = historical_klines(symbol, start_ms, end_ms)
        return symbol, len(candles), backtest(candles)
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

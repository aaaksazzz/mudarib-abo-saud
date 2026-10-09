#!/usr/bin/env python3
"""Standalone 30-day Binance Spot liquidity-sweep / failed-breakout backtest. Paper trades only."""
import concurrent.futures, csv, datetime as dt, io, json, os, urllib.parse, urllib.request, zipfile

BASES = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com"]
DATA_BASE = "https://data.binance.vision"
DAYS, MIN_VOLUME, FEE, INTERVAL, LOOKBACK = 30, 1_000_000, 0.001, "15m", 20
BAR_MS = 15 * 60 * 1000
STABLES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "TRY", "BRL", "USDD", "USTC"}

def fetch_url(url, timeout=35):
    req = urllib.request.Request(url, headers={"User-Agent": "SMART-TRADING-PRO-liquidity-sweep-backtest/1.0"})
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
    parsed = []
    start = dt.datetime.fromtimestamp(start_ms / 1000, dt.timezone.utc)
    end = dt.datetime.fromtimestamp(end_ms / 1000, dt.timezone.utc)
    months, cursor = [], start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= end:
        months.append((cursor.year, cursor.month))
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    current_month_start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for year, month in months:
        if dt.datetime(year, month, 1, tzinfo=dt.timezone.utc) >= current_month_start:
            continue
        for row in load_month(symbol, year, month):
            try:
                opened = int(row[0])
                if start_ms <= opened <= end_ms:
                    parsed.append([opened, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])])
            except (ValueError, IndexError):
                continue
    live_start = max(start_ms, int(current_month_start.timestamp() * 1000))
    if live_start <= end_ms:
        try:
            batch = api("/api/v3/klines", symbol=symbol, interval=INTERVAL, startTime=live_start, endTime=end_ms, limit=1000)
            parsed.extend([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in batch])
        except Exception:
            pass
    unique = {r[0]: r for r in parsed}
    if unique:
        return [unique[k] for k in sorted(unique)]
    parsed, cursor = [], start_ms
    while cursor <= end_ms:
        batch = api("/api/v3/klines", symbol=symbol, interval=INTERVAL, startTime=cursor, endTime=end_ms, limit=1000)
        if not batch:
            break
        parsed.extend([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in batch])
        nxt = int(batch[-1][0]) + BAR_MS
        if nxt <= cursor or len(batch) < 1000:
            break
        cursor = nxt
    unique = {r[0]: r for r in parsed}
    return [unique[k] for k in sorted(unique)]

def backtest(rows):
    trades, i = [], LOOKBACK
    while i < len(rows) - 1:
        window = rows[i-LOOKBACK:i]
        prior_low = min(r[3] for r in window)
        prior_high = max(r[2] for r in window)
        sweep = rows[i]
        # Signal is confirmed only at candle close; enter at the NEXT candle open.
        direction = "long" if sweep[3] < prior_low and sweep[4] > prior_low else (
                    "short" if sweep[2] > prior_high and sweep[4] < prior_high else None)
        if not direction:
            i += 1
            continue
        entry_i = i + 1
        entry = rows[entry_i][1]
        stop = sweep[3] if direction == "long" else sweep[2]
        target = prior_high if direction == "long" else prior_low
        if entry <= 0 or (direction == "long" and not (stop < entry < target)) or (direction == "short" and not (target < entry < stop)):
            i += 1
            continue
        exit_price, exit_i, outcome = rows[-1][4], len(rows)-1, "period_end"
        for j in range(entry_i, len(rows)):
            high, low = rows[j][2], rows[j][3]
            # Conservative: if stop and target touch in the same candle, stop wins.
            if direction == "long":
                if low <= stop:
                    exit_price, exit_i, outcome = stop, j, "stop"; break
                if high >= target:
                    exit_price, exit_i, outcome = target, j, "target"; break
            else:
                if high >= stop:
                    exit_price, exit_i, outcome = stop, j, "stop"; break
                if low <= target:
                    exit_price, exit_i, outcome = target, j, "target"; break
        gross = (exit_price-entry)/entry if direction == "long" else (entry-exit_price)/entry
        net_pct = (gross - 2*FEE)*100
        trades.append({"direction": direction, "signal_time": sweep[0], "entry_time": rows[entry_i][0],
                       "entry": entry, "target": target, "stop": stop, "exit": exit_price,
                       "exit_time": rows[exit_i][0], "outcome": outcome, "net_pct": net_pct})
        i = exit_i + 1
    equity = peak = 1.0
    max_dd = 0.0
    for t in trades:
        equity *= max(0.0, 1+t["net_pct"]/100)
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak-equity)/peak)
    n = len(trades)
    wins = sum(t["net_pct"] > 0 for t in trades)
    return {"trades": n, "wins": wins, "losses": n-wins,
            "win_rate_pct": round(wins*100/n, 2) if n else 0,
            "net_return_compounded_pct": round((equity-1)*100, 2),
            "max_drawdown_pct": round(max_dd*100, 2),
            "avg_trade_net_pct": round(sum(t["net_pct"] for t in trades)/n, 4) if n else 0,
            "long_trades": sum(t["direction"]=="long" for t in trades),
            "short_trades": sum(t["direction"]=="short" for t in trades),
            "targets_hit": sum(t["outcome"]=="target" for t in trades),
            "stops_hit": sum(t["outcome"]=="stop" for t in trades)}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    end_ms, start_ms = int(now.timestamp()*1000), int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    info, tickers = api("/api/v3/exchangeInfo"), api("/api/v3/ticker/24hr")
    volumes = {x["symbol"]: float(x.get("quoteVolume", 0)) for x in tickers}
    symbols = sorted(s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING"
        and s.get("isSpotTradingAllowed", True) and s.get("quoteAsset")=="USDT"
        and s.get("baseAsset") not in STABLES and volumes.get(s["symbol"], 0)>MIN_VOLUME)
    report = {"period_days": DAYS, "market": "Binance Spot USDT pairs", "timeframe": INTERVAL,
        "strategy": "Standalone liquidity sweep: long if candle low sweeps prior 20-candle low and closes back above it; short if high sweeps prior 20-candle high and closes back below it. Entry next candle open; stop at sweep extreme; target opposite edge of prior 20-candle range.",
        "lookback_candles": LOOKBACK, "volume_filter": "current 24h quote volume > 1,000,000 USDT",
        "fee_each_side_pct": FEE*100, "entry_rule": "next 15m candle open after sweep candle closes",
        "same_candle_rule": "stop first if both target and stop are touched", "paper_trading_only": True,
        "eligible_symbols": len(symbols), "symbols_tested": 0, "candles_loaded": 0,
        "aggregate": {"trades":0,"wins":0,"losses":0,"targets_hit":0,"stops_hit":0},
        "per_symbol": {}, "failed": []}
    def run(symbol):
        candles = historical_klines(symbol, start_ms, end_ms)
        return symbol, len(candles), backtest(candles)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(run, s): s for s in symbols}
        for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
            symbol = futures[future]
            try:
                _, count, stats = future.result()
                report["symbols_tested"] += 1; report["candles_loaded"] += count
                report["per_symbol"][symbol] = stats
                for key in ("trades","wins","losses","targets_hit","stops_hit"):
                    report["aggregate"][key] += stats[key]
            except Exception as exc:
                report["failed"].append({"symbol":symbol,"error":str(exc)[:200]})
            if idx % 10 == 0:
                print(f"PROGRESS {idx}/{len(symbols)}; candles={report['candles_loaded']}; failures={len(report['failed'])}", flush=True)
    agg = report["aggregate"]; n = agg["trades"]
    agg["win_rate_pct"] = round(agg["wins"]*100/n,2) if n else 0
    report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results", exist_ok=True)
    with open("backtest-results/liquidity-sweep-15m.json","w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print("SUMMARY",json.dumps({k:v for k,v in report.items() if k!="per_symbol"},ensure_ascii=False))
    print("TOP RESULTS")
    for sym,stats in sorted(report["per_symbol"].items(),key=lambda x:(x[1]["net_return_compounded_pct"],x[1]["win_rate_pct"]),reverse=True)[:25]:
        print(sym,json.dumps(stats,ensure_ascii=False))

if __name__ == "__main__":
    main()

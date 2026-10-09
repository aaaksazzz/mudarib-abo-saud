#!/usr/bin/env python3
"""30-day Binance spot/futures backtest. Volume spikes are only a whale-activity proxy, not wallet-level whale data."""
import concurrent.futures, datetime as dt, json, os, time, urllib.parse, urllib.request

SPOT = "https://api.binance.com"
FUTURES = "https://fapi.binance.com"
DAYS = 30
INTERVAL = "15m"
BAR_MS = 900_000
MIN_QUOTE_VOLUME = 1_000_000
LOOKBACK = 20
VOLUME_MULTIPLE = 2.0
STABLES = {"USDC","BUSD","FDUSD","TUSD","USDP","DAI","EUR","TRY","BRL","USDD","USTC","USDE","PYUSD"}

def candidate_urls(url):
    # Binance may return HTTP 451 from some hosted-runner IP ranges.
    # Use Binance's documented public market-data-only domain for spot and
    # alternate official Futures REST hosts before failing.
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    hosts = [host]
    if host == "api.binance.com":
        hosts += ["data-api.binance.vision", "api1.binance.com", "api2.binance.com", "api3.binance.com", "api4.binance.com"]
    elif host in {"fapi.binance.com", "fapi1.binance.com", "fapi2.binance.com", "fapi3.binance.com", "fapi4.binance.com"}:
        hosts += [h for h in ("fapi1.binance.com", "fapi2.binance.com", "fapi3.binance.com", "fapi4.binance.com", "fapi.binance.com") if h != host]
    seen = set()
    for candidate in hosts:
        if candidate in seen:
            continue
        seen.add(candidate)
        yield urllib.parse.urlunsplit((parsed.scheme, candidate, parsed.path, parsed.query, parsed.fragment))

def get_json(url, timeout=15, tries=2):
    errors = []
    urls = list(candidate_urls(url))
    for candidate in urls:
        for attempt in range(tries):
            try:
                req = urllib.request.Request(candidate, headers={"User-Agent":"SMART-TRADING-PRO-whale-flow-proxy/1.1"})
                with urllib.request.urlopen(req, timeout=timeout) as res:
                    return json.loads(res.read().decode("utf-8"))
            except Exception as exc:
                errors.append(f"{urllib.parse.urlsplit(candidate).netloc}: {exc}")
                time.sleep(0.35 * (attempt + 1))
    raise RuntimeError("All official Binance market-data endpoints failed: " + " | ".join(errors[-8:]))

def candles(market, symbol, start_ms, end_ms):
    base = FUTURES if market == "futures" else SPOT
    path = "/fapi/v1/klines" if market == "futures" else "/api/v3/klines"
    out, cursor = [], start_ms
    while cursor <= end_ms:
        params = urllib.parse.urlencode({"symbol":symbol,"interval":INTERVAL,"startTime":cursor,"endTime":end_ms,"limit":1000})
        batch = get_json(base + path + "?" + params)
        if not batch:
            break
        for r in batch:
            try:
                out.append({"t":int(r[0]),"o":float(r[1]),"h":float(r[2]),"l":float(r[3]),"c":float(r[4]),"v":float(r[5])})
            except (ValueError, TypeError, IndexError):
                continue
        nxt = int(batch[-1][0]) + BAR_MS
        if nxt <= cursor or len(batch) < 1000:
            break
        cursor = nxt
        time.sleep(0.05)
    unique = {r["t"]:r for r in out}
    return [unique[k] for k in sorted(unique)]

def simulate(rows, mode, fee):
    trades = []
    i = LOOKBACK
    while i < len(rows)-1:
        prev = rows[i-LOOKBACK:i]
        bar = rows[i]
        prior_low = min(x["l"] for x in prev)
        prior_high = max(x["h"] for x in prev)
        avg_vol = sum(x["v"] for x in prev) / len(prev)
        swept_low = bar["l"] < prior_low and bar["c"] > prior_low
        swept_high = bar["h"] > prior_high and bar["c"] < prior_high
        if not (swept_low or swept_high):
            i += 1
            continue
        # This is a candle-volume anomaly proxy. Historical candles cannot identify actual whale wallets or order-flow intent.
        if mode in ("volume_confirmed", "reverse_volume_confirmed") and (avg_vol <= 0 or bar["v"] < avg_vol * VOLUME_MULTIPLE):
            i += 1
            continue
        original = "long" if swept_low else "short"
        direction = ("short" if original == "long" else "long") if mode.startswith("reverse") else original
        entry_i = i + 1
        entry = rows[entry_i]["o"]
        stop = bar["l"] if direction == "long" else bar["h"]
        target = prior_high if direction == "long" else prior_low
        if entry <= 0 or (direction == "long" and not stop < entry < target) or (direction == "short" and not target < entry < stop):
            i += 1
            continue
        exit_price, exit_i, outcome = rows[-1]["c"], len(rows)-1, "period_end"
        for j in range(entry_i, len(rows)):
            hi, lo = rows[j]["h"], rows[j]["l"]
            if direction == "long":
                if lo <= stop: exit_price, exit_i, outcome = stop, j, "stop"; break
                if hi >= target: exit_price, exit_i, outcome = target, j, "target"; break
            else:
                if hi >= stop: exit_price, exit_i, outcome = stop, j, "stop"; break
                if lo <= target: exit_price, exit_i, outcome = target, j, "target"; break
        gross = (exit_price-entry)/entry if direction == "long" else (entry-exit_price)/entry
        net = (gross - 2*fee)*100
        trades.append({"direction":direction,"entry_time":rows[entry_i]["t"],"net_pct":net,"outcome":outcome})
        i = exit_i + 1
    equity = peak = 1.0
    max_dd = 0.0
    for tr in trades:
        equity *= max(0.0, 1 + tr["net_pct"]/100)
        peak = max(peak, equity)
        if peak:
            max_dd = max(max_dd, (peak-equity)/peak)
    n = len(trades)
    wins = sum(t["net_pct"] > 0 for t in trades)
    return {"trades":n,"wins":wins,"losses":n-wins,
            "win_rate_pct":round(100*wins/n,2) if n else 0.0,
            "net_return_compounded_pct":round((equity-1)*100,2),
            "max_drawdown_pct":round(max_dd*100,2),
            "avg_trade_net_pct":round(sum(t["net_pct"] for t in trades)/n,4) if n else 0.0,
            "long_trades":sum(t["direction"]=="long" for t in trades),
            "short_trades":sum(t["direction"]=="short" for t in trades),
            "targets_hit":sum(t["outcome"]=="target" for t in trades),
            "stops_hit":sum(t["outcome"]=="stop" for t in trades)}

def market_universe(market):
    base = FUTURES if market == "futures" else SPOT
    path = "/fapi/v1/ticker/24hr" if market == "futures" else "/api/v3/ticker/24hr"
    tickers = get_json(base + path)
    volumes = {x["symbol"]:float(x.get("quoteVolume") or 0) for x in tickers}
    if market == "spot":
        info = get_json(SPOT + "/api/v3/exchangeInfo")
        return sorted(s["symbol"] for s in info["symbols"]
            if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"
            and s.get("baseAsset") not in STABLES and volumes.get(s["symbol"],0)>MIN_QUOTE_VOLUME)
    info = get_json(FUTURES + "/fapi/v1/exchangeInfo")
    return sorted(s["symbol"] for s in info["symbols"]
        if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"
        and s.get("contractType")=="PERPETUAL" and s.get("baseAsset") not in STABLES
        and volumes.get(s["symbol"],0)>MIN_QUOTE_VOLUME)

def main():
    now = dt.datetime.now(dt.timezone.utc)
    end_ms = int(now.timestamp()*1000)
    start_ms = int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    modes = {
        "baseline_sweep":"Liquidity sweep only",
        "volume_confirmed":"Liquidity sweep + candle volume at least 2x prior 20-candle average (proxy)",
        "reverse_volume_confirmed":"Reverse of volume-confirmed sweep"
    }
    report = {"period_days":DAYS,"timeframe":INTERVAL,"lookback_candles":LOOKBACK,
        "minimum_current_24h_quote_volume_usdt":MIN_QUOTE_VOLUME,
        "volume_anomaly_multiple":VOLUME_MULTIPLE,
        "fee_each_side_assumption":{"spot_pct":0.1,"futures_pct":0.05},
        "warning":"No historical wallet-level whale feed is available in this test. Volume-confirmed mode is a candle-volume proxy, not proof of whale trades. Futures use candles and do not model funding, liquidation, slippage, or leverage.",
        "strategy_definitions":modes,"markets":{},"failed_symbols":[]}
    for market in ("spot","futures"):
        symbols = market_universe(market)
        fee = 0.001 if market == "spot" else 0.0005
        result = {"eligible_symbols":len(symbols),"symbols_tested":0,"candles_loaded":0,
                  "strategies":{k:{"trades":0,"wins":0,"losses":0,"long_trades":0,"short_trades":0,
                    "targets_hit":0,"stops_hit":0,"per_symbol":{}} for k in modes}}
        def run(sym):
            bars = candles(market,sym,start_ms,end_ms)
            return sym,bars,{mode:simulate(bars,mode,fee) for mode in modes}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(run,s):s for s in symbols}
            for idx,fut in enumerate(concurrent.futures.as_completed(futures),1):
                sym = futures[fut]
                try:
                    _,bars,stats = fut.result()
                    result["symbols_tested"] += 1
                    result["candles_loaded"] += len(bars)
                    for mode,st in stats.items():
                        result["strategies"][mode]["per_symbol"][sym] = st
                        for key in ("trades","wins","losses","long_trades","short_trades","targets_hit","stops_hit"):
                            result["strategies"][mode][key] += st[key]
                except Exception as exc:
                    report["failed_symbols"].append({"market":market,"symbol":sym,"error":str(exc)[:180]})
                if idx % 20 == 0:
                    print(f"PROGRESS market={market} symbols={idx}/{len(symbols)} candles={result['candles_loaded']} failed={len(report['failed_symbols'])}",flush=True)
        for data in result["strategies"].values():
            n = data["trades"]
            data["win_rate_pct"] = round(100*data["wins"]/n,2) if n else 0.0
            # Portfolio-level result is computed across symbol trades only as an aggregate indicator, not as a synchronized portfolio simulation.
            data["symbols_with_trades"] = sum(1 for s in data["per_symbol"].values() if s["trades"])
            data["positive_symbols"] = sum(1 for s in data["per_symbol"].values() if s["net_return_compounded_pct"]>0)
            data["negative_symbols"] = sum(1 for s in data["per_symbol"].values() if s["net_return_compounded_pct"]<0)
            del data["per_symbol"]
        report["markets"][market] = result
        print("MARKET SUMMARY",market,json.dumps(result,ensure_ascii=False)[:5000],flush=True)
    report["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    path = "backtest-results/whale-flow-proxy-15m.json"
    with open(path,"w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print("FINAL SUMMARY",json.dumps({ "period_days":DAYS,"completed_utc":report["completed_utc"],
        "markets":{m:{"eligible_symbols":v["eligible_symbols"],"symbols_tested":v["symbols_tested"],
        "candles_loaded":v["candles_loaded"],"strategies":{k:{a:b for a,b in s.items() if a not in ("per_symbol",)} for k,s in v["strategies"].items()}}
        for m,v in report["markets"].items()},"failed_symbols":len(report["failed_symbols"])},ensure_ascii=False),flush=True)

if __name__ == "__main__":
    main()

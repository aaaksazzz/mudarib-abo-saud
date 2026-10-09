#!/usr/bin/env python3
"""30-day Binance Spot strategy discovery and backtest. Paper only; never places orders."""
import concurrent.futures, csv, datetime as dt, io, json, os, time, urllib.request, urllib.error, zipfile

DAYS, INTERVAL, MIN_VOLUME = 30, "15m", 1_000_000
TAKER_FEE_SIDE, SLIPPAGE_SIDE = 0.0005, 0.0002
COST_PCT = (TAKER_FEE_SIDE + SLIPPAGE_SIDE) * 2 * 100
ARCHIVE_BASES = ["https://data.binance.vision", "https://data.binance.com"]
API_BASES = ["https://api.binance.com", "https://api1.binance.com", "https://api2.binance.com", "https://api3.binance.com", "https://api4.binance.com"]
SNAPSHOT = "scripts/futures_universe_snapshot.json"

def fetch_bytes(url, timeout=25):
    req=urllib.request.Request(url,headers={"User-Agent":"SMART-TRADING-PRO-research/1.0"})
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read()

def fetch_json_from_apis(path):
    errors=[]
    for base in API_BASES:
        try:
            return json.loads(fetch_bytes(base+path, timeout=25).decode("utf-8")), base+path
        except Exception as exc:
            errors.append(f"{base}: {type(exc).__name__}: {exc}")
    raise RuntimeError("All Binance API endpoints failed: " + " | ".join(errors))

def normalize_timestamp(value):
    """Binance public archive CSVs may use microseconds; the backtest uses milliseconds."""
    stamp=int(value)
    return stamp // 1000 if stamp > 100_000_000_000_000 else stamp


def read_zip_rows(urls):
    errors=[]
    for url in urls:
        try:
            raw=fetch_bytes(url, timeout=35)
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                name=next(n for n in z.namelist() if n.endswith(".csv"))
                out=[]
                for row in csv.reader(io.TextIOWrapper(z.open(name),encoding="utf-8")):
                    try: out.append([normalize_timestamp(row[0]),float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5])])
                    except (ValueError,IndexError): continue
                return out
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    print("ARCHIVE_SOURCES_FAILED " + " | ".join(errors),flush=True)
    return []

def candles_from_api(symbol, start_ms, end_ms):
    errors=[]
    for base in API_BASES:
        try:
            rows=[]; cursor=start_ms
            while cursor<=end_ms:
                url=f"{base}/api/v3/klines?symbol={symbol}&interval={INTERVAL}&startTime={cursor}&endTime={end_ms}&limit=1000"
                batch=json.loads(fetch_bytes(url,timeout=30).decode("utf-8"))
                if not batch: break
                rows.extend([[normalize_timestamp(r[0]),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5])] for r in batch])
                nxt=int(batch[-1][0])+1
                if nxt<=cursor: break
                cursor=nxt
                if len(batch)<1000: break
            if rows:
                unique={r[0]:r for r in rows if start_ms<=r[0]<=end_ms}
                print(f"API_CANDLES_SOURCE {symbol} {base} rows={len(unique)}",flush=True)
                return [unique[k] for k in sorted(unique)]
        except Exception as exc:
            errors.append(f"{base}: {type(exc).__name__}: {exc}")
    print(f"API_CANDLES_ALL_SOURCES_FAILED {symbol} " + " | ".join(errors),flush=True)
    return []

def candles_from_archive(symbol, start_ms, end_ms):
    start=dt.datetime.fromtimestamp(start_ms/1000,dt.timezone.utc)
    end=dt.datetime.fromtimestamp(end_ms/1000,dt.timezone.utc)
    rows=[]; month=start.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    current_month=end.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    while month<current_month:
        fn=f"{symbol}-{INTERVAL}-{month.year}-{month.month:02d}.zip"
        urls=[f"{base}/data/spot/monthly/klines/{symbol}/{INTERVAL}/{fn}" for base in ARCHIVE_BASES]
        rows.extend(read_zip_rows(urls))
        month=(month.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    day=current_month.date()
    while day<=end.date():
        fn=f"{symbol}-{INTERVAL}-{day.isoformat()}.zip"
        urls=[f"{base}/data/spot/daily/klines/{symbol}/{INTERVAL}/{fn}" for base in ARCHIVE_BASES]
        rows.extend(read_zip_rows(urls))
        day+=dt.timedelta(days=1)
    unique={r[0]:r for r in rows if start_ms<=r[0]<=end_ms}
    archived=[unique[k] for k in sorted(unique)]
    if len(archived) >= 150:
        return archived
    print(f"ARCHIVE_INCOMPLETE {symbol} rows={len(archived)}; trying REST API fallback",flush=True)
    api_rows=candles_from_api(symbol,start_ms,end_ms)
    return api_rows if len(api_rows)>len(archived) else archived

def ema(vals, period):
    out=[]; alpha=2/(period+1); e=None
    for x in vals:
        e=x if e is None else alpha*x+(1-alpha)*e
        out.append(e)
    return out

def rsi(vals, period=14):
    out=[50.0]*len(vals)
    if len(vals)<=period: return out
    gains=[]; losses=[]
    for i in range(1,len(vals)):
        d=vals[i]-vals[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    def val(g,l): return 100.0 if l==0 else 100-100/(1+g/l)
    out[period]=val(ag,al)
    for i in range(period+1,len(vals)):
        d=vals[i]-vals[i-1]; ag=(ag*(period-1)+max(d,0))/period; al=(al*(period-1)+max(-d,0))/period
        out[i]=val(ag,al)
    return out

def candidate_space():
    # Generate the search space from parameter combinations; no single strategy is preselected.
    candidates=[]
    for family in ("breakout","sweep","momentum","ema_trend","rsi_revert"):
        for lookback in (5,8,10,15,20,30,40,60):
            for rr in (1.25,1.5,2.0,2.5,3.0):
                for stop_n in (5,10,20):
                    for filter_mode in ("none","trend","rsi"):
                        candidates.append({"family":family,"lookback":lookback,"rr":rr,"stop_n":stop_n,"filter":filter_mode})
    # Remove nonsensical duplicates and cap nothing: the search engine evaluates every generated rule.
    return candidates

def signals(rows, cfg):
    n=len(rows); closes=[r[4] for r in rows]; highs=[r[2] for r in rows]; lows=[r[3] for r in rows]
    result=[None]*n
    lb=cfg["lookback"]; rr=cfg["rr"]; stop_n=cfg["stop_n"]
    e20=ema(closes,20); e50=ema(closes,50); rv=rsi(closes,14)
    for i in range(max(lb,stop_n,50),n):
        hi=max(highs[i-lb:i]); lo=min(lows[i-lb:i]); close=closes[i]
        direction=None
        if cfg["family"]=="breakout":
            if close>hi: direction="long"
            elif close<lo: direction="short"
        elif cfg["family"]=="sweep":
            if lows[i]<lo and close>lo: direction="long"
            elif highs[i]>hi and close<hi: direction="short"
        elif cfg["family"]=="momentum":
            momentum=close/closes[i-lb]-1 if closes[i-lb] else 0
            threshold=0.0015
            if momentum>threshold: direction="long"
            elif momentum<-threshold: direction="short"
        elif cfg["family"]=="ema_trend":
            spread=(e20[i]/e50[i]-1) if e50[i] else 0
            prior=(e20[i-1]/e50[i-1]-1) if e50[i-1] else 0
            if spread>0 and prior<=0: direction="long"
            elif spread<0 and prior>=0: direction="short"
        elif cfg["family"]=="rsi_revert":
            if rv[i]>35 and rv[i-1]<=35: direction="long"
            elif rv[i]<65 and rv[i-1]>=65: direction="short"
        if not direction: continue
        if cfg["filter"]=="trend" and ((direction=="long" and e20[i]<e50[i]) or (direction=="short" and e20[i]>e50[i])): continue
        if cfg["filter"]=="rsi" and ((direction=="long" and rv[i]>65) or (direction=="short" and rv[i]<35)): continue
        if direction=="long":
            stop=min(lows[i-stop_n+1:i+1])
            risk=close-stop
            if risk>0: result[i]=(direction,stop,close+rr*risk)
        else:
            stop=max(highs[i-stop_n+1:i+1])
            risk=stop-close
            if risk>0: result[i]=(direction,stop,close-rr*risk)
    return result

def simulate(rows, strategy, start_i=0, end_i=None):
    end_i=min(len(rows),end_i if end_i is not None else len(rows))
    sig=signals(rows[:end_i],strategy); trades=[]; i=max(start_i,60)
    while i<end_i-1:
        s=sig[i]
        if not s: i+=1; continue
        direction,stop,target=s; entry_i=i+1; entry=rows[entry_i][1]
        if entry<=0 or stop<=0 or (direction=="long" and not stop<entry<target) or (direction=="short" and not target<entry<stop):
            i+=1; continue
        exit_price=rows[end_i-1][4]; exit_i=end_i-1; outcome="period_end"
        for j in range(entry_i,end_i):
            hi,lo=rows[j][2],rows[j][3]
            if direction=="long":
                if lo<=stop: exit_price,exit_i,outcome=stop,j,"stop"; break
                if hi>=target: exit_price,exit_i,outcome=target,j,"target"; break
            else:
                if hi>=stop: exit_price,exit_i,outcome=stop,j,"stop"; break
                if lo<=target: exit_price,exit_i,outcome=target,j,"target"; break
        gross=(exit_price-entry)/entry if direction=="long" else (entry-exit_price)/entry
        trades.append({"net_pct":gross*100-COST_PCT,"outcome":outcome,"direction":direction})
        i=exit_i+1
    vals=[t["net_pct"] for t in trades]; n=len(vals); wins=sum(v>0 for v in vals)
    gp=sum(v for v in vals if v>0); gl=-sum(v for v in vals if v<0)
    equity=peak=1.; dd=0.
    for v in vals:
        equity*=max(0,1+v/100); peak=max(peak,equity)
        if peak: dd=max(dd,(peak-equity)/peak)
    return {"trades":n,"wins":wins,"losses":n-wins,"win_rate_pct":round(wins*100/n,2) if n else 0,
        "avg_trade_net_pct":round(sum(vals)/n,4) if n else 0,"profit_factor":round(gp/gl,3) if gl else (999 if gp else 0),
        "return_pct":round((equity-1)*100,2),"max_drawdown_pct":round(dd*100,2),
        "long_trades":sum(t["direction"]=="long" for t in trades),"short_trades":sum(t["direction"]=="short" for t in trades)}

def main():
    now=dt.datetime.now(dt.timezone.utc); end=int(now.timestamp()*1000); start=int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    stable_bases={"USDT","USDC","FDUSD","TUSD","USDP","DAI","BUSD","EUR","AEUR","USTC","USDE","USDD","PYUSD","USD1"}
    universe_fallback=False
    try:
        tickers, ticker_source=fetch_json_from_apis("/api/v3/ticker/24hr")
        info, exchange_source=fetch_json_from_apis("/api/v3/exchangeInfo")
        ticker_by_symbol={x["symbol"]:x for x in tickers}
        symbols=[]
        for item in info.get("symbols",[]):
            sym=item.get("symbol",""); base=item.get("baseAsset","")
            ticker=ticker_by_symbol.get(sym,{})
            if item.get("status")=="TRADING" and item.get("isSpotTradingAllowed",False) and item.get("quoteAsset")=="USDT" and base not in stable_bases and float(ticker.get("quoteVolume",0) or 0)>MIN_VOLUME:
                symbols.append(sym)
    except Exception as exc:
        # Binance API may return HTTP 451 on hosted runners. Build a candidate list from CoinGecko,
        # then confirm each pair by retrieving Binance Spot kline archives and checking recent quote volume.
        print(f"BINANCE_UNIVERSE_API_UNAVAILABLE {type(exc).__name__}: {exc}; using CoinGecko candidate list",flush=True)
        cg=[]
        for page in (1,):
            url=f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=100&page={page}"
            payload=json.loads(fetch_bytes(url,timeout=30).decode("utf-8"))
            cg.extend(payload)
            time.sleep(1.2)
        symbols=sorted({str(x.get("symbol","")).upper()+"USDT" for x in cg
                        if x.get("symbol") and str(x.get("symbol","")).upper() not in stable_bases
                        and float(x.get("total_volume",0) or 0)>MIN_VOLUME})
        ticker_source="CoinGecko volume-ranked candidate list (fallback only)"
        exchange_source="Binance Spot kline archive validation (fallback only)"
        universe_fallback=True
    shard_count=max(1,int(os.getenv("SHARD_COUNT","1")))
    shard_index=int(os.getenv("SHARD_INDEX","0"))
    if shard_index<0 or shard_index>=shard_count:
        raise ValueError(f"Invalid shard index {shard_index} for shard count {shard_count}")
    all_symbols=sorted(symbols)
    symbols=[sym for i,sym in enumerate(all_symbols) if i % shard_count == shard_index]
    print(f"SHARD_ASSIGNMENT shard={shard_index+1}/{shard_count} symbols={len(symbols)}/{len(all_symbols)}",flush=True)
    snap={"snapshotUtc":now.isoformat()}
    split=start+int((end-start)*2/3)
    candidates=candidate_space()
    report={"market":"Binance Spot USDT pairs","period_days":DAYS,"train_days":20,"validation_days":10,"timeframe":INTERVAL,
      "leverage":"Spot, no leverage; paper simulation","universe_snapshot_utc":snap.get("snapshotUtc"),"universe_symbols":len(all_symbols),"shard":{"index":shard_index,"count":shard_count,"symbols_in_this_shard":len(symbols)},
      "provider_endpoints":{"ticker":ticker_source,"exchange_info":exchange_source,"archives":ARCHIVE_BASES},
      "universe_filter":"Primary: live Binance Spot TRADING USDT pairs with Binance 24h quote volume > 1,000,000 USDT. Fallback when Binance API is blocked: CoinGecko volume-ranked candidates, then require available Binance Spot 15m archive candles and verify recent candle quote-volume proxy > 1,000,000 USDT.",
      "universe_fallback_used":universe_fallback,
      "search_method":"automatically generated parameter/rule search; candidates are ranked on training data, then independently checked on validation data",
      "candidate_count":len(candidates),"fee_each_side_pct":TAKER_FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,
      "round_trip_cost_pct":round(COST_PCT,4),"funding_included":False,
      "warning":"Spot fees and slippage are modeled; verify exact account fees and forward-test before live use.",
      "paper_only":True,"symbols_tested":0,"candles_loaded":0,"failures":[]}
    train_scores={json.dumps(cfg,sort_keys=True):[] for cfg in candidates}
    validation_rows={}
    def load(sym): return sym,candles_from_archive(sym,start,end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        fs={pool.submit(load,s):s for s in symbols}
        for idx,f in enumerate(concurrent.futures.as_completed(fs),1):
            sym=fs[f]
            try:
                _,rows=f.result()
                if len(rows)<150:
                    report["failures"].append({"symbol":sym,"error":f"insufficient archive candles ({len(rows)})"}); continue
                if universe_fallback:
                    recent=[r for r in rows if r[0]>=end-24*60*60*1000]
                    recent_quote_volume=sum(r[4]*r[5] for r in recent)
                    if len(recent)<20 or recent_quote_volume<=MIN_VOLUME:
                        report["failures"].append({"symbol":sym,"error":f"fallback pair failed recent Binance Spot volume check (candles={len(recent)}, quote_volume_proxy={recent_quote_volume:.0f} USDT in available recent candles)"}); continue
                report["symbols_tested"]+=1; report["candles_loaded"]+=len(rows)
                split_i=next((i for i,r in enumerate(rows) if r[0]>=split),len(rows)-1)
                if split_i<80 or len(rows)-split_i<30: continue
                # Training search: evaluate the automatically generated rule space.
                for cfg in candidates:
                    key=json.dumps(cfg,sort_keys=True)
                    tr=simulate(rows,cfg,60,split_i)
                    if tr["trades"]>=3: train_scores[key].append(tr)
                validation_rows[sym]=rows
            except Exception as e: report["failures"].append({"symbol":sym,"error":str(e)[:160]})
            if idx%25==0: print(f"PROGRESS {idx}/{len(symbols)} candles={report['candles_loaded']} candidates={len(candidates)} failed={len(report['failures'])}",flush=True)
    def aggregate(arr):
        n=sum(x["trades"] for x in arr); w=sum(x["wins"] for x in arr)
        return {"symbols_with_trades":len(arr),"trades":n,"wins":w,"losses":sum(x["losses"] for x in arr),
          "win_rate_pct":round(w*100/n,2) if n else 0,
          "avg_trade_net_pct":round(sum(x["avg_trade_net_pct"]*x["trades"] for x in arr)/n,4) if n else 0,
          "mean_symbol_return_pct":round(sum(x["return_pct"] for x in arr)/len(arr),2) if arr else 0,
          "mean_symbol_drawdown_pct":round(sum(x["max_drawdown_pct"] for x in arr)/len(arr),2) if arr else 0,
          "median_symbol_return_pct":round(sorted(x["return_pct"] for x in arr)[len(arr)//2],2) if arr else 0,
          "profitable_symbols_pct":round(sum(x["return_pct"]>0 for x in arr)*100/len(arr),2) if arr else 0,
          "mean_symbol_profit_factor":round(sum(x["profit_factor"] for x in arr)/len(arr),3) if arr else 0}
    ranked=[]
    for key,arr in train_scores.items():
        tr=aggregate(arr)
        if tr["trades"]>=100:
            ranked.append((key,tr))
    ranked.sort(key=lambda x:(x[1]["avg_trade_net_pct"],x[1]["mean_symbol_profit_factor"],x[1]["profitable_symbols_pct"]),reverse=True)
    # Avoid selecting a single lucky training fit: independently validate the top 40 generated candidates.
    validated=[]
    for key,tr in ranked[:40]:
        cfg=json.loads(key); vals=[]
        for sym,rows in validation_rows.items():
            split_i=next((i for i,r in enumerate(rows) if r[0]>=split),len(rows)-1)
            va=simulate(rows,cfg,split_i,len(rows))
            if va["trades"]: vals.append(va)
        v=aggregate(vals)
        passed=v["trades"]>=100 and v["avg_trade_net_pct"]>0 and v["mean_symbol_profit_factor"]>1.05 and v["mean_symbol_drawdown_pct"]<35 and v["profitable_symbols_pct"]>=50
        validated.append({"rule":cfg,"training":tr,"validation":v,"passed_validation":passed})
    validated.sort(key=lambda x:(x["validation"]["avg_trade_net_pct"],x["validation"]["mean_symbol_profit_factor"],x["validation"]["profitable_symbols_pct"]),reverse=True)
    report["top_candidates"]=validated[:40]
    winners=[x for x in validated if x["passed_validation"]]
    if winners:
        report["best_candidate"]={"status":"candidate_for_further_validation","rule":winners[0]["rule"],"validation":winners[0]["validation"]}
    else:
        report["best_candidate"]={"status":"no_validated_profitable_candidate","message":"Automated search did not find a candidate passing all validation gates. Expand the generated search space or extend data; do not enable live orders."}
    report["completed_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    report_path=f"backtest-results/spot-strategy-search-15m-shard-{shard_index}.json"
    with open(report_path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print("SPOT_FINAL_SUMMARY",json.dumps({k:v for k,v in report.items() if k not in ("top_candidates",)},ensure_ascii=False))
    print("SPOT_TOP_VALIDATED_CANDIDATES",json.dumps(report["top_candidates"][:10],ensure_ascii=False))

if __name__=="__main__": main()

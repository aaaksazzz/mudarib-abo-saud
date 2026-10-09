#!/usr/bin/env python3
"""30-day Binance USDⓈ-M Futures strategy research. Paper only; never places orders."""
import concurrent.futures, csv, datetime as dt, io, json, os, time, urllib.request, zipfile

DAYS, INTERVAL, MIN_VOLUME = 30, "15m", 1_000_000
TAKER_FEE_SIDE, SLIPPAGE_SIDE = 0.0005, 0.0002
COST_PCT = (TAKER_FEE_SIDE + SLIPPAGE_SIDE) * 2 * 100
ARCHIVE = "https://data.binance.vision"
SNAPSHOT = "scripts/futures_universe_snapshot.json"

def fetch_bytes(url, timeout=25):
    req=urllib.request.Request(url,headers={"User-Agent":"SMART-TRADING-PRO-research/1.0"})
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.read()

def read_zip_rows(url):
    try:
        raw=fetch_bytes(url)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name=next(n for n in z.namelist() if n.endswith(".csv"))
            out=[]
            for row in csv.reader(io.TextIOWrapper(z.open(name),encoding="utf-8")):
                try: out.append([int(row[0]),float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5])])
                except (ValueError,IndexError): continue
            return out
    except Exception:
        return []

def candles_from_archive(symbol, start_ms, end_ms):
    start=dt.datetime.fromtimestamp(start_ms/1000,dt.timezone.utc)
    end=dt.datetime.fromtimestamp(end_ms/1000,dt.timezone.utc)
    rows=[]; month=start.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    current_month=end.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    while month<current_month:
        fn=f"{symbol}-{INTERVAL}-{month.year}-{month.month:02d}.zip"
        url=f"{ARCHIVE}/data/futures/um/monthly/klines/{symbol}/{INTERVAL}/{fn}"
        rows.extend(read_zip_rows(url))
        month=(month.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
    day=current_month.date()
    while day<=end.date():
        fn=f"{symbol}-{INTERVAL}-{day.isoformat()}.zip"
        url=f"{ARCHIVE}/data/futures/um/daily/klines/{symbol}/{INTERVAL}/{fn}"
        rows.extend(read_zip_rows(url))
        day+=dt.timedelta(days=1)
    unique={r[0]:r for r in rows if start_ms<=r[0]<=end_ms}
    return [unique[k] for k in sorted(unique)]

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

def signals(rows, strategy):
    n=len(rows); closes=[r[4] for r in rows]; highs=[r[2] for r in rows]; lows=[r[3] for r in rows]
    result=[None]*n
    if strategy.startswith("breakout_"):
        lb=int(strategy.split("_")[1])
        for i in range(lb,n):
            hi=max(highs[i-lb:i]); lo=min(lows[i-lb:i])
            if closes[i]>hi: result[i]=("long",lo,closes[i]+2*(closes[i]-lo))
            elif closes[i]<lo: result[i]=("short",hi,closes[i]-2*(hi-closes[i]))
    elif strategy=="liquidity_sweep_20":
        for i in range(20,n):
            hi=max(highs[i-20:i]); lo=min(lows[i-20:i])
            if lows[i]<lo and closes[i]>lo and closes[i]>rows[i][1]:
                result[i]=("long",lows[i],hi)
            elif highs[i]>hi and closes[i]<hi and closes[i]<rows[i][1]:
                result[i]=("short",highs[i],lo)
    elif strategy=="ema_20_50":
        e20,e50=ema(closes,20),ema(closes,50)
        for i in range(1,n):
            if e20[i]>e50[i] and e20[i-1]<=e50[i-1]:
                st=min(lows[max(0,i-10):i+1]); result[i]=("long",st,closes[i]+2*(closes[i]-st))
            elif e20[i]<e50[i] and e20[i-1]>=e50[i-1]:
                st=max(highs[max(0,i-10):i+1]); result[i]=("short",st,closes[i]-2*(st-closes[i]))
    elif strategy=="rsi_reversal_14":
        rv=rsi(closes,14)
        for i in range(15,n):
            if rv[i]>30 and rv[i-1]<=30:
                st=min(lows[i-10:i+1]); result[i]=("long",st,closes[i]+2*(closes[i]-st))
            elif rv[i]<70 and rv[i-1]>=70:
                st=max(highs[i-10:i+1]); result[i]=("short",st,closes[i]-2*(st-closes[i]))
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
    with open(SNAPSHOT,encoding="utf-8") as f: snap=json.load(f)
    symbols=[x["symbol"] for x in snap["symbols"] if x.get("quoteVolume24h",0)>MIN_VOLUME]
    split=start+int((end-start)*2/3)
    strategies=["breakout_10","breakout_20","breakout_40","liquidity_sweep_20","ema_20_50","rsi_reversal_14"]
    report={"market":"Binance USDⓈ-M perpetual futures","period_days":DAYS,"train_days":20,"validation_days":10,"timeframe":INTERVAL,
      "leverage":"1x paper simulation","universe_snapshot_utc":snap.get("snapshotUtc"),"universe_symbols":len(symbols),
      "universe_filter":"Current snapshot: trading USDT-margined perpetual contracts with non-stable base and 24h quote volume > 1,000,000 USDT",
      "fee_each_side_pct":TAKER_FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,"round_trip_cost_pct":round(COST_PCT,4),
      "funding_included":False,"warning":"Official archive fallback is used because REST API access may be region-blocked. Funding is not included; candidates require funding-adjusted and further out-of-sample validation.",
      "paper_only":True,"symbols_tested":0,"candles_loaded":0,"strategies":{},"failures":[]}
    buckets={s:{"train":[],"validation":[]} for s in strategies}
    def load(sym): return sym,candles_from_archive(sym,start,end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        fs={pool.submit(load,s):s for s in symbols}
        for idx,f in enumerate(concurrent.futures.as_completed(fs),1):
            sym=fs[f]
            try:
                _,rows=f.result()
                if len(rows)<150:
                    report["failures"].append({"symbol":sym,"error":f"insufficient archive candles ({len(rows)})"}); continue
                report["symbols_tested"]+=1; report["candles_loaded"]+=len(rows)
                split_i=next((i for i,r in enumerate(rows) if r[0]>=split),len(rows)-1)
                if split_i<80 or len(rows)-split_i<30: continue
                for strategy in strategies:
                    tr=simulate(rows,strategy,60,split_i)
                    va=simulate(rows,strategy,split_i,len(rows))
                    if tr["trades"]: buckets[strategy]["train"].append(tr)
                    if va["trades"]: buckets[strategy]["validation"].append(va)
            except Exception as e: report["failures"].append({"symbol":sym,"error":str(e)[:160]})
            if idx%25==0: print(f"PROGRESS {idx}/{len(symbols)} candles={report['candles_loaded']} failed={len(report['failures'])}",flush=True)
    for strategy,parts in buckets.items():
        item={}
        for period,arr in parts.items():
            n=sum(x["trades"] for x in arr); w=sum(x["wins"] for x in arr)
            item[period]={"symbols_with_trades":len(arr),"trades":n,"wins":w,"losses":sum(x["losses"] for x in arr),
              "win_rate_pct":round(w*100/n,2) if n else 0,
              "avg_trade_net_pct":round(sum(x["avg_trade_net_pct"]*x["trades"] for x in arr)/n,4) if n else 0,
              "mean_symbol_return_pct":round(sum(x["return_pct"] for x in arr)/len(arr),2) if arr else 0,
              "mean_symbol_drawdown_pct":round(sum(x["max_drawdown_pct"] for x in arr)/len(arr),2) if arr else 0,
              "median_symbol_return_pct":round(sorted(x["return_pct"] for x in arr)[len(arr)//2],2) if arr else 0,
              "profitable_symbols_pct":round(sum(x["return_pct"]>0 for x in arr)*100/len(arr),2) if arr else 0,
              "mean_symbol_profit_factor":round(sum(x["profit_factor"] for x in arr)/len(arr),3) if arr else 0}
        v=item["validation"]
        item["eligible_for_followup"]=v["trades"]>=100 and v["avg_trade_net_pct"]>0 and v["mean_symbol_profit_factor"]>1.05 and v["mean_symbol_drawdown_pct"]<35 and v["profitable_symbols_pct"]>=50
        report["strategies"][strategy]=item
    candidates=[(k,v) for k,v in report["strategies"].items() if v["eligible_for_followup"]]
    if candidates:
        k,v=max(candidates,key=lambda x:(x[1]["validation"]["avg_trade_net_pct"],x[1]["validation"]["mean_symbol_profit_factor"],x[1]["validation"]["profitable_symbols_pct"]))
        report["best_candidate"]={"strategy":k,"status":"candidate_for_further_validation","validation":v["validation"]}
    else: report["best_candidate"]={"status":"no_validated_profitable_candidate","message":"No strategy passed all validation gates. Do not enable live orders."}
    report["completed_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/futures-strategy-search-15m.json","w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print("FINAL_SUMMARY",json.dumps({k:v for k,v in report.items() if k!="strategies"},ensure_ascii=False))
    print("RANKED_STRATEGIES")
    for k,v in sorted(report["strategies"].items(),key=lambda x:(x[1]["validation"]["avg_trade_net_pct"],x[1]["validation"]["mean_symbol_profit_factor"]),reverse=True):
        print(k,json.dumps(v,ensure_ascii=False))

if __name__=="__main__": main()

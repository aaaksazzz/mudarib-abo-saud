#!/usr/bin/env python3
"""30-day Binance USDⓈ-M Futures strategy research. Paper only; never places orders."""
import concurrent.futures, datetime as dt, json, math, os, time, urllib.parse, urllib.request

BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com"]
DAYS, MIN_VOLUME, INTERVAL = 30, 1_000_000, "15m"
TAKER_FEE_SIDE, SLIPPAGE_SIDE = 0.0005, 0.0002
COST_PCT = (TAKER_FEE_SIDE + SLIPPAGE_SIDE) * 2 * 100
STABLES = {"USDT","USDC","BUSD","FDUSD","TUSD","USDP","DAI","EUR","TRY","BRL","USDD","USTC"}

def api(path, **params):
    q = "?" + urllib.parse.urlencode(params) if params else ""
    errors = []
    for base in BASES:
        try:
            req = urllib.request.Request(base + path + q, headers={"User-Agent":"SMART-TRADING-PRO-research/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode())
            if isinstance(data, dict) and data.get("code") is not None:
                errors.append(str(data.get("msg", data))); continue
            return data
        except Exception as e:
            errors.append(str(e)[:100])
    raise RuntimeError("Binance Futures public API unavailable: " + " | ".join(errors))

def candles(symbol, start_ms, end_ms):
    out, cursor = [], start_ms
    while cursor < end_ms:
        batch = api("/fapi/v1/klines", symbol=symbol, interval=INTERVAL, startTime=cursor, endTime=end_ms, limit=1500)
        if not batch: break
        out.extend([[int(x[0]),float(x[1]),float(x[2]),float(x[3]),float(x[4]),float(x[5])] for x in batch])
        nxt = int(batch[-1][0]) + 15*60*1000
        if nxt <= cursor or len(batch) < 1500: break
        cursor = nxt
        time.sleep(0.03)
    unique = {r[0]:r for r in out}
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
        lb=20
        for i in range(lb,n):
            hi=max(highs[i-lb:i]); lo=min(lows[i-lb:i])
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
        net=gross*100-COST_PCT
        trades.append({"net_pct":net,"outcome":outcome,"direction":direction})
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
    info,tickers=api("/fapi/v1/exchangeInfo"),api("/fapi/v1/ticker/24hr")
    vols={x["symbol"]:float(x.get("quoteVolume",0)) for x in tickers}
    symbols=sorted(s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT" and s.get("marginAsset")=="USDT" and s.get("baseAsset") not in STABLES and vols.get(s["symbol"],0)>MIN_VOLUME)
    split=start+int((end-start)*2/3)
    strategies=["breakout_10","breakout_20","breakout_40","liquidity_sweep_20","ema_20_50","rsi_reversal_14"]
    report={"market":"Binance USDⓈ-M perpetual futures","period_days":30,"train_days":20,"validation_days":10,"timeframe":INTERVAL,
      "leverage":"1x paper simulation","volume_filter_24h_quote_usdt_gt":MIN_VOLUME,"eligible_symbols":len(symbols),"symbols_tested":0,"candles_loaded":0,
      "fee_each_side_pct":TAKER_FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,"round_trip_cost_pct":round(COST_PCT,4),
      "funding_included":False,"warning":"Funding payments are not included; any candidate requires funding-adjusted and further out-of-sample validation before live consideration.",
      "paper_only":True,"strategies":{},"failures":[]}
    buckets={s:{"train":[],"validation":[]} for s in strategies}
    def load(sym): return sym,candles(sym,start,end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        fs={pool.submit(load,s):s for s in symbols}
        for idx,f in enumerate(concurrent.futures.as_completed(fs),1):
            sym=fs[f]
            try:
                _,rows=f.result()
                if len(rows)<150: continue
                report["symbols_tested"]+=1; report["candles_loaded"]+=len(rows)
                split_i=next((i for i,r in enumerate(rows) if r[0]>=split),len(rows)-1)
                if split_i<80 or len(rows)-split_i<30: continue
                for strategy in strategies:
                    tr=simulate(rows,strategy,60,split_i)
                    # Warm up indicators on training candles; only trades after the split count as validation.
                    va=simulate(rows,strategy,split_i,len(rows))
                    if tr["trades"]: buckets[strategy]["train"].append(tr)
                    if va["trades"]: buckets[strategy]["validation"].append(va)
            except Exception as e: report["failures"].append({"symbol":sym,"error":str(e)[:160]})
            if idx%25==0: print(f"PROGRESS {idx}/{len(symbols)} candles={report['candles_loaded']} failed={len(report['failures'])}",flush=True)
    for strategy,parts in buckets.items():
        item={}
        for period,arr in parts.items():
            n=sum(x["trades"] for x in arr); w=sum(x["wins"] for x in arr)
            gp=sum(x["profit_factor"]*0 for x in arr) # placeholder; aggregate PF is calculated from weighted expectancy below only as a ranking aid
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

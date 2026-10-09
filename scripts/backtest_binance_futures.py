#!/usr/bin/env python3
"""Historical-only Binance USD-M perpetual backtest; never submits orders."""
import concurrent.futures, datetime as dt, json, os, time, urllib.request, urllib.parse
BASE="https://fapi.binance.com"
DAYS=30
MIN_VOLUME=1_000_000
FEE=0.0005

def get(path, **params):
    url=BASE+path+("?" + urllib.parse.urlencode(params) if params else "")
    req=urllib.request.Request(url,headers={"User-Agent":"SMART-TRADING-PRO-backtest"})
    with urllib.request.urlopen(req,timeout=25) as r: return json.loads(r.read().decode())

def history(symbol, interval, start_ms, end_ms):
    rows=[]; cursor=start_ms
    while cursor<end_ms:
        part=get("/fapi/v1/klines",symbol=symbol,interval=interval,startTime=cursor,endTime=end_ms,limit=1000)
        if not part: break
        rows.extend(part); nxt=int(part[-1][0])+1
        if nxt<=cursor: break
        cursor=nxt
        if len(part)<1000: break
        time.sleep(0.04)
    return rows

def backtest(rows, side, lookback=20):
    trades=[]; i=lookback
    while i<len(rows)-1:
        prior=rows[i-lookback:i]
        ph=max(float(c[2]) for c in prior); pl=min(float(c[3]) for c in prior)
        close=float(rows[i][4]); entry=stop=None
        if side=="BUY" and close>ph: entry,stop=close,pl
        elif side=="SELL" and close<pl: entry,stop=close,ph
        if entry is None or stop<=0 or abs(entry-stop)/entry>0.15:
            i+=1; continue
        target=entry+2*(entry-stop) if side=="BUY" else entry-2*(stop-entry)
        exit_price=float(rows[-1][4]); exit_i=len(rows)-1; outcome="end"
        for j in range(i+1,len(rows)):
            hi,lo=float(rows[j][2]),float(rows[j][3])
            stopped=lo<=stop if side=="BUY" else hi>=stop
            hit=hi>=target if side=="BUY" else lo<=target
            if stopped: exit_price,exit_i,outcome=stop,j,"loss"; break
            if hit: exit_price,exit_i,outcome=target,j,"win"; break
        pnl=((exit_price-entry)/entry if side=="BUY" else (entry-exit_price)/entry)-2*FEE
        trades.append({"net_pct":pnl*100,"outcome":outcome})
        i=exit_i+1
    eq=peak=1.0; dd=0.0
    for t in trades:
        eq*=1+t["net_pct"]/100; peak=max(peak,eq); dd=max(dd,(peak-eq)/peak)
    wins=sum(t["net_pct"]>0 for t in trades)
    return {"trades":len(trades),"wins":wins,"losses":len(trades)-wins,
      "win_rate_pct":round(wins*100/len(trades),2) if trades else 0,
      "net_return_compounded_pct":round((eq-1)*100,2),"max_drawdown_pct":round(dd*100,2),
      "avg_trade_net_pct":round(sum(t["net_pct"] for t in trades)/len(trades),4) if trades else 0}

def main():
    now=dt.datetime.now(dt.timezone.utc); end_ms=int(now.timestamp()*1000)
    start_ms=int((now-dt.timedelta(days=DAYS)).timestamp()*1000)
    info=get("/fapi/v1/exchangeInfo"); tickers=get("/fapi/v1/ticker/24hr")
    volumes={x["symbol"]:float(x.get("quoteVolume",0)) for x in tickers}
    symbols=sorted(s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT" and volumes.get(s["symbol"],0)>MIN_VOLUME)
    tasks=[(sym,side,tf) for sym in symbols for side,tf in (("BUY","15m"),("BUY","30m"),("BUY","1h"),("SELL","4h"))]
    report={"period_days":DAYS,"started_utc":now.isoformat(),"market":"Binance USD-M USDT perpetual futures",
      "volume_filter":"24h quote volume > 1,000,000 USDT","target":"2R","lookback_candles":20,
      "fees_each_side_pct":FEE*100,"same_candle_rule":"stop loss wins if both stop and target touch",
      "eligible_symbols":len(symbols),"results":{},"failed":[]}
    def one(task):
        sym,side,tf=task; rows=history(sym,tf,start_ms,end_ms)
        return sym,side,tf,len(rows),backtest(rows,side)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures={pool.submit(one,t):t for t in tasks}
        for f in concurrent.futures.as_completed(futures):
            sym,side,tf=futures[f]; key=side+"_"+tf
            try:
                _,_,_,n,stats=f.result()
                b=report["results"].setdefault(key,{"symbols_tested":0,"candles":0,"trades":0,"wins":0,"losses":0,"per_symbol":{}})
                b["symbols_tested"]+=1; b["candles"]+=n; b["trades"]+=stats["trades"]; b["wins"]+=stats["wins"]; b["losses"]+=stats["losses"]; b["per_symbol"][sym]=stats
            except Exception as e: report["failed"].append({"symbol":sym,"side":side,"timeframe":tf,"error":str(e)[:180]})
    for b in report["results"].values():
        b["win_rate_pct"]=round(b["wins"]*100/b["trades"],2) if b["trades"] else 0
    report["completed_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/latest.json","w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!="results"},ensure_ascii=False,indent=2))
    for key,b in report["results"].items(): print(key,"tested",b["symbols_tested"],"trades",b["trades"],"wins",b["wins"],"win_rate_pct",b["win_rate_pct"])
if __name__=="__main__": main()

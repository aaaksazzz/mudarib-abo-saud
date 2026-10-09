#!/usr/bin/env python3
"""Standalone historical backtest for Binance USD-M perpetual USDT contracts."""
import json, os, time, urllib.request, urllib.parse
BASE = "https://fapi.binance.com"

def get(path, **params):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "SMART-TRADING-PRO-backtest"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

def run(rows, side, lookback=20, fee=0.0005):
    trades=[]; i=lookback
    while i < len(rows)-1:
        prior=rows[i-lookback:i]
        high=max(float(c[2]) for c in prior); low=min(float(c[3]) for c in prior)
        close=float(rows[i][4]); entry=stop=target=None
        if side=="BUY" and close>high: entry,stop=close,low
        elif side=="SELL" and close<low: entry,stop=close,high
        if entry is None or stop<=0 or abs(entry-stop)/entry>0.15:
            i+=1; continue
        target=entry+2*(entry-stop) if side=="BUY" else entry-2*(stop-entry)
        exit_price=float(rows[-1][4]); exit_i=len(rows)-1; outcome="end"
        for j in range(i+1,len(rows)):
            hi,lo=float(rows[j][2]),float(rows[j][3])
            stopped=(lo<=stop if side=="BUY" else hi>=stop)
            hit=(hi>=target if side=="BUY" else lo<=target)
            if stopped: exit_price,exit_i,outcome=stop,j,"loss"; break
            if hit: exit_price,exit_i,outcome=target,j,"win"; break
        pnl=((exit_price-entry)/entry if side=="BUY" else (entry-exit_price)/entry)-2*fee
        trades.append({"outcome":outcome,"net_pct":round(pnl*100,4)})
        i=exit_i+1
    wins=sum(t["net_pct"]>0 for t in trades)
    return {"trades":len(trades),"wins":wins,"losses":len(trades)-wins,
            "win_rate_pct":round(100*wins/len(trades),2) if trades else 0,
            "net_return_compounded_pct":round((__import__("math").prod(1+t["net_pct"]/100 for t in trades)-1)*100,2),
            "trades_detail":trades}

def main():
    info=get("/fapi/v1/exchangeInfo")
    tickers=get("/fapi/v1/ticker/24hr")
    volumes={t["symbol"]:float(t.get("quoteVolume",0)) for t in tickers}
    symbols=[s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT" and volumes.get(s["symbol"],0)>1_000_000]
    report={"eligible_symbols":len(symbols),"filter":"24h quote volume > 1,000,000 USDT","results":{},"failed":[]}
    for side,interval in (("BUY","15m"),("SELL","4h")):
        report["results"][side+"_"+interval]={}
        for symbol in symbols:
            try:
                rows=get("/fapi/v1/klines",symbol=symbol,interval=interval,limit=1000)
                report["results"][side+"_"+interval][symbol]={"candles":len(rows),**run(rows,side)}
            except Exception as e: report["failed"].append({"symbol":symbol,"side":side,"error":str(e)[:160]})
            time.sleep(0.03)
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/latest.json","w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!="results"},ensure_ascii=False,indent=2))
    for side,rows in report["results"].items():
        total=sum(x["trades"] for x in rows.values()); wins=sum(x["wins"] for x in rows.values())
        print(side,"symbols",len(rows),"trades",total,"wins",wins,"win_rate_pct",round(wins/total*100,2) if total else 0)
if __name__=="__main__": main()

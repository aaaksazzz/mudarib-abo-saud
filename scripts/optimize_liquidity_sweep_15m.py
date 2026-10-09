#!/usr/bin/env python3
"""Parameter research for the standalone liquidity-sweep strategy. Paper testing only."""
import importlib.util, json, os, datetime as dt

spec = importlib.util.spec_from_file_location("base_sweep", "scripts/backtest_liquidity_sweep_15m.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

LOOKBACKS = (10, 15, 20, 30, 40)
DIRECTIONS = ("normal", "reversed")

def simulate(rows, lookback, mode, start_index=None):
    trades, i = [], max(lookback, start_index or 0)
    while i < len(rows) - 1:
        window = rows[i-lookback:i]
        lo, hi, bar = min(r[3] for r in window), max(r[2] for r in window), rows[i]
        swept_low = bar[3] < lo and bar[4] > lo
        swept_high = bar[2] > hi and bar[4] < hi
        if mode == "normal":
            direction = "long" if swept_low else ("short" if swept_high else None)
        else:
            direction = "short" if swept_low else ("long" if swept_high else None)
        if not direction:
            i += 1
            continue
        ei, entry = i+1, rows[i+1][1]
        stop = bar[3] if direction == "long" else bar[2]
        target = hi if direction == "long" else lo
        if entry <= 0 or (direction == "long" and not stop < entry < target) or (direction == "short" and not target < entry < stop):
            i += 1
            continue
        exit_price, exit_i, outcome = rows[-1][4], len(rows)-1, "period_end"
        for j in range(ei, len(rows)):
            high, low = rows[j][2], rows[j][3]
            if direction == "long":
                if low <= stop: exit_price, exit_i, outcome = stop, j, "stop"; break
                if high >= target: exit_price, exit_i, outcome = target, j, "target"; break
            else:
                if high >= stop: exit_price, exit_i, outcome = stop, j, "stop"; break
                if low <= target: exit_price, exit_i, outcome = target, j, "target"; break
        gross = (exit_price-entry)/entry if direction == "long" else (entry-exit_price)/entry
        trades.append({"net_pct": (gross-2*base.FEE)*100, "outcome": outcome})
        i = exit_i+1
    n=len(trades); wins=sum(t["net_pct"] > 0 for t in trades)
    vals=[t["net_pct"] for t in trades]
    gross_profit=sum(x for x in vals if x>0); gross_loss=-sum(x for x in vals if x<0)
    equity=peak=1.0; dd=0.0
    for x in vals:
        equity *= max(0, 1+x/100); peak=max(peak,equity)
        if peak: dd=max(dd,(peak-equity)/peak)
    return {"trades":n,"wins":wins,"losses":n-wins,"win_rate_pct":round(100*wins/n,2) if n else 0,
            "avg_trade_net_pct":round(sum(vals)/n,4) if n else 0,
            "profit_factor":round(gross_profit/gross_loss,3) if gross_loss else (999 if gross_profit else 0),
            "trade_sequence_return_pct":round((equity-1)*100,2),"max_drawdown_pct":round(dd*100,2),
            "targets":sum(t["outcome"]=="target" for t in trades),"stops":sum(t["outcome"]=="stop" for t in trades)}

def main():
    now=dt.datetime.now(dt.timezone.utc); end=int(now.timestamp()*1000); start=int((now-dt.timedelta(days=base.DAYS)).timestamp()*1000)
    info, tickers=base.api("/api/v3/exchangeInfo"),base.api("/api/v3/ticker/24hr")
    volumes={x["symbol"]:float(x.get("quoteVolume",0)) for x in tickers}
    symbols=sorted(s["symbol"] for s in info["symbols"] if s.get("status")=="TRADING" and s.get("isSpotTradingAllowed",True) and s.get("quoteAsset")=="USDT" and s.get("baseAsset") not in base.STABLES and volumes.get(s["symbol"],0)>base.MIN_VOLUME)
    split=start+int((end-start)*2/3)
    report={"period_days":30,"train_days":20,"validation_days":10,"timeframe":"15m","symbols_eligible":len(symbols),"symbols_tested":0,"candles_loaded":0,"failed":[],"variants":{},"paper_trading_only":True,
            "method":"Compare lookbacks 10/15/20/30/40 and normal/reversed signals. Select by validation expectancy, with minimum 100 validation trades; no live orders."}
    per_variant={f"{mode}_lb{lb}":{"train":[],"validation":[]} for mode in DIRECTIONS for lb in LOOKBACKS}
    import concurrent.futures
    def load(sym): return sym,base.historical_klines(sym,start,end)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(load,s):s for s in symbols}
        for idx,f in enumerate(concurrent.futures.as_completed(futures),1):
            sym=futures[f]
            try:
                _,rows=f.result()
                if len(rows)<60: continue
                report["symbols_tested"]+=1; report["candles_loaded"]+=len(rows)
                split_i=next((i for i,r in enumerate(rows) if r[0]>=split),len(rows)-1)
                for mode in DIRECTIONS:
                    for lb in LOOKBACKS:
                        key=f"{mode}_lb{lb}"
                        tr=simulate(rows[:split_i],lb,mode)
                        va=simulate(rows[max(0,split_i-lb):],lb,mode,start_index=lb)
                        if tr["trades"]: per_variant[key]["train"].append(tr)
                        if va["trades"]: per_variant[key]["validation"].append(va)
            except Exception as e: report["failed"].append({"symbol":sym,"error":str(e)[:160]})
            if idx%10==0: print(f"PROGRESS {idx}/{len(symbols)}; candles={report['candles_loaded']}; failures={len(report['failed'])}",flush=True)
    for key,parts in per_variant.items():
        item={}
        for period in ("train","validation"):
            arr=parts[period]; n=sum(x["trades"] for x in arr); w=sum(x["wins"] for x in arr)
            # Aggregate arithmetic trade expectancy; do not compound across unrelated coins as one account.
            item[period]={"symbols_with_trades":len(arr),"trades":n,"wins":w,"losses":sum(x["losses"] for x in arr),
                "win_rate_pct":round(100*w/n,2) if n else 0,
                "avg_trade_net_pct":round(sum(x["avg_trade_net_pct"]*x["trades"] for x in arr)/n,4) if n else 0,
                "gross_profit_pct":round(sum(x["gross_profit_pct"] for x in arr),4),
                "gross_loss_pct":round(sum(x["gross_loss_pct"] for x in arr),4),
                "profit_factor":round(sum(x["gross_profit_pct"] for x in arr)/sum(x["gross_loss_pct"] for x in arr),3) if sum(x["gross_loss_pct"] for x in arr)>0 else (999.0 if sum(x["gross_profit_pct"] for x in arr)>0 else 0),
                "mean_symbol_return_pct":round(sum(x["trade_sequence_return_pct"] for x in arr)/len(arr),2) if arr else 0,
                "median_symbol_return_pct":round(sorted(x["trade_sequence_return_pct"] for x in arr)[len(arr)//2],2) if arr else 0,
                "mean_symbol_drawdown_pct":round(sum(x["max_drawdown_pct"] for x in arr)/len(arr),2) if arr else 0}
        item["candidate_for_followup"] = item["validation"]["trades"]>=100 and item["validation"]["avg_trade_net_pct"]>0 and item["validation"]["profit_factor"]>1.05 and item["validation"]["mean_symbol_drawdown_pct"]<35
        report["variants"][key]=item
    candidates=[(k,v) for k,v in report["variants"].items() if v["candidate_for_followup"]]
    if candidates:
        k,v=max(candidates,key=lambda kv:(kv[1]["validation"]["avg_trade_net_pct"],kv[1]["validation"]["profit_factor"],-kv[1]["validation"]["mean_symbol_drawdown_pct"]))
        report["best_candidate"]={"variant":k,"validation":v["validation"],"train":v["train"],"status":"candidate_for_further_out_of_sample_testing"}
    else:
        report["best_candidate"]={"status":"no_validated_profitable_candidate","message":"No tested variant passed minimum trade count, positive validation expectancy, profit factor > 1.05 and drawdown < 35%; do not label any strategy profitable."}
    report["completed_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/liquidity-sweep-optimizer-15m.json","w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print("SUMMARY",json.dumps({k:v for k,v in report.items() if k!="variants"},ensure_ascii=False))
    print("RANKED VARIANTS")
    for key,v in sorted(report["variants"].items(),key=lambda kv:(kv[1]["validation"]["avg_trade_net_pct"],kv[1]["validation"]["profit_factor"]),reverse=True):
        print(key,json.dumps(v,ensure_ascii=False))
if __name__=="__main__": main()

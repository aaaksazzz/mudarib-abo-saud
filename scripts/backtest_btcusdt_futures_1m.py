#!/usr/bin/env python3
"""BTCUSDT USD-M futures 1m research backtest; paper-only, no live orders."""
import csv, datetime as dt, io, json, math, os, time, urllib.request, urllib.error, urllib.parse, zipfile

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
DAYS = 180
FEE_SIDE = 0.0005       # conservative regular-user taker assumption, each side
SLIPPAGE_SIDE = 0.0002  # conservative fixed slippage assumption, each side
LEVERAGES = [1, 2, 3, 5, 10]
START_EQUITY = 100.0
BASE = "https://data.binance.vision"
REST_HOSTS = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com"]
BAR_MS = 60_000

def get_bytes(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "SMART-TRADING-PRO-BTC-1m-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def parse_zip(url, start_ms, end_ms):
    try:
        raw = get_bytes(url)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            out = []
            with z.open(name) as fh:
                for row in csv.reader(io.TextIOWrapper(fh, encoding="utf-8")):
                    try:
                        t = int(float(row[0]))
                        if start_ms <= t <= end_ms:
                            out.append((t, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]), float(row[7]) if len(row) > 7 else 0.0))
                    except (ValueError, IndexError):
                        continue
            return out
    except Exception:
        return []

def month_next(d):
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)

def load_history(start_ms, end_ms):
    start = dt.datetime.fromtimestamp(start_ms/1000, dt.timezone.utc).date()
    end = dt.datetime.fromtimestamp(end_ms/1000, dt.timezone.utc).date()
    today = dt.datetime.now(dt.timezone.utc).date()
    rows, sources, missing = [], [], []
    cur = start
    while cur <= end:
        nxt = month_next(cur)
        month_end = nxt - dt.timedelta(days=1)
        full_month = cur.day == 1 and month_end <= end and month_end < today
        if full_month:
            tag = f"{cur.year}-{cur.month:02d}"
            url = f"{BASE}/data/futures/um/monthly/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{tag}.zip"
            batch = parse_zip(url, start_ms, end_ms)
            if batch:
                rows.extend(batch); sources.append({"type":"monthly_archive","period":tag,"rows":len(batch)})
            else:
                missing.append(tag)
            cur = nxt
        else:
            tag = cur.isoformat()
            url = f"{BASE}/data/futures/um/daily/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{tag}.zip"
            batch = parse_zip(url, start_ms, end_ms)
            if batch:
                rows.extend(batch); sources.append({"type":"daily_archive","period":tag,"rows":len(batch)})
            else:
                missing.append(tag)
            cur += dt.timedelta(days=1)
    # Fill archive gaps with official public Futures REST klines.
    if missing:
        cursor = start_ms
        existing = {r[0] for r in rows}
        errors = []
        while cursor <= end_ms:
            found = False
            params = urllib.parse.urlencode({"symbol":SYMBOL,"interval":INTERVAL,"startTime":cursor,"endTime":end_ms,"limit":1000})
            for host in REST_HOSTS:
                try:
                    req = urllib.request.Request(host+"/fapi/v1/klines?"+params, headers={"User-Agent":"SMART-TRADING-PRO-BTC-1m-backtest/1.0"})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode())
                    if not isinstance(data, list): raise RuntimeError(str(data)[:200])
                    for r in data:
                        t=int(r[0])
                        if t not in existing and start_ms <= t <= end_ms:
                            rows.append((t,float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[5]),float(r[7])))
                            existing.add(t)
                    if not data:
                        cursor=end_ms+BAR_MS
                    else:
                        cursor=int(data[-1][0])+BAR_MS
                    found=True
                    break
                except Exception as e:
                    errors.append(str(e))
            if not found:
                break
            time.sleep(0.08)
    unique = {r[0]:r for r in rows}
    return [unique[k] for k in sorted(unique)], sources, missing

def ema(values, period):
    out=[None]*len(values)
    if len(values)<period: return out
    alpha=2/(period+1)
    cur=sum(values[:period])/period
    out[period-1]=cur
    for i in range(period,len(values)):
        cur=values[i]*alpha+cur*(1-alpha)
        out[i]=cur
    return out

def rsi(values, period=14):
    out=[None]*len(values)
    if len(values)<=period: return out
    gains=[]; losses=[]
    for i in range(1,period+1):
        d=values[i]-values[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/period; al=sum(losses)/period
    out[period]=100 if al==0 else 100-100/(1+ag/al)
    for i in range(period+1,len(values)):
        d=values[i]-values[i-1]
        ag=(ag*(period-1)+max(d,0))/period
        al=(al*(period-1)+max(-d,0))/period
        out[i]=100 if al==0 else 100-100/(1+ag/al)
    return out

def atr(rows, period=14):
    out=[None]*len(rows); trs=[]
    for i,row in enumerate(rows):
        tr=row[2]-row[3] if i==0 else max(row[2]-row[3],abs(row[2]-rows[i-1][4]),abs(row[3]-rows[i-1][4]))
        trs.append(tr)
        if i==period-1: out[i]=sum(trs[:period])/period
        elif i>=period: out[i]=(out[i-1]*(period-1)+tr)/period
    return out

def indicators(rows):
    close=[r[4] for r in rows]
    return {"e20":ema(close,20),"e50":ema(close,50),"e200":ema(close,200),
            "rsi":rsi(close,14),"atr":atr(rows,14)}

def signal_at(i, rows, ind, strategy):
    c=rows[i][4]; prev=rows[i-1][4]
    e20,e50,e200,rv,av=ind["e20"],ind["e50"],ind["e200"],ind["rsi"],ind["atr"]
    if any(x[i] is None for x in (e20,e50,e200,rv,av)) or av[i] <= 0: return None
    if strategy=="ema_pullback":
        # Trend-aligned reclaim of EMA20 after touching it in the prior three closed bars.
        touched_low=min(rows[j][3] for j in range(i-3,i+1)) <= e20[i]
        touched_high=max(rows[j][2] for j in range(i-3,i+1)) >= e20[i]
        if e20[i]>e50[i]>e200[i] and prev<=e20[i-1] and c>e20[i] and 50<=rv[i]<=68 and touched_low:
            return ("long",1.2,1.6)
        if e20[i]<e50[i]<e200[i] and prev>=e20[i-1] and c<e20[i] and 32<=rv[i]<=50 and touched_high:
            return ("short",1.2,1.6)
    elif strategy=="trend_breakout":
        prior=rows[i-20:i]
        high=max(x[2] for x in prior); low=min(x[3] for x in prior)
        avgq=sum(x[5]*x[4] for x in prior)/len(prior)
        q=rows[i][5]*rows[i][4]
        if c>high and e50[i]>e200[i] and rv[i]>=52 and q>avgq*1.2: return ("long",1.0,1.5)
        if c<low and e50[i]<e200[i] and rv[i]<=48 and q>avgq*1.2: return ("short",1.0,1.5)
    elif strategy=="rsi_momentum":
        if e20[i]>e50[i]>e200[i] and rv[i-1] is not None and rv[i-1]<50<=rv[i] and c>e20[i]:
            return ("long",1.1,1.5)
        if e20[i]<e50[i]<e200[i] and rv[i-1] is not None and rv[i-1]>50>=rv[i] and c<e20[i]:
            return ("short",1.1,1.5)
    return None

def simulate(rows, ind, strategy, start_i, end_i):
    trades=[]; i=max(start_i,201)
    end_i=min(end_i,len(rows)-2)
    while i<end_i:
        sig=signal_at(i,rows,ind,strategy)
        if not sig:
            i+=1; continue
        side,stop_atr,target_r=sig
        entry_i=i+1; entry=rows[entry_i][1]; av=ind["atr"][i]
        risk=stop_atr*av
        if entry<=0 or risk<=0:
            i+=1; continue
        stop=entry-risk if side=="long" else entry+risk
        target=entry+target_r*risk if side=="long" else entry-target_r*risk
        exit_p=None; exit_i=None; outcome=None
        for j in range(entry_i,end_i+1):
            hi,lo=rows[j][2],rows[j][3]
            if side=="long":
                if lo<=stop: exit_p,exit_i,outcome=stop,j,"stop"; break
                if hi>=target: exit_p,exit_i,outcome=target,j,"target"; break
            else:
                if hi>=stop: exit_p,exit_i,outcome=stop,j,"stop"; break
                if lo<=target: exit_p,exit_i,outcome=target,j,"target"; break
        if exit_p is None:
            exit_i=end_i; exit_p=rows[end_i][4]; outcome="window_end"
        gross=(exit_p-entry)/entry if side=="long" else (entry-exit_p)/entry
        # Charge fee and slippage on both entry and exit notional, even for stop/target orders.
        net=gross-2*FEE_SIDE-2*SLIPPAGE_SIDE
        trades.append({"entry_i":entry_i,"exit_i":exit_i,"entry_time":rows[entry_i][0],
                       "exit_time":rows[exit_i][0],"side":side,"gross_pct":gross*100,
                       "net_pct":net*100,"outcome":outcome,"risk_pct":risk/entry*100})
        i=exit_i+1
    return trades

def stats(trades):
    n=len(trades); wins=sum(t["net_pct"]>0 for t in trades)
    eq=peak=1.0; dd=0.0; returns=[]
    for t in trades:
        r=t["net_pct"]/100
        returns.append(r)
        eq*=max(0.0,1+r)
        peak=max(peak,eq)
        if peak: dd=max(dd,(peak-eq)/peak)
    gross=sum(t["gross_pct"] for t in trades)
    net=sum(t["net_pct"] for t in trades)
    return {"trades":n,"wins":wins,"losses":n-wins,"win_rate_pct":round(100*wins/n,2) if n else 0.0,
            "net_sum_pct_of_notional":round(net,3),"net_compounded_pct_at_1x":round((eq-1)*100,3),
            "max_drawdown_pct_at_1x":round(dd*100,3),
            "avg_net_pct_per_trade":round(net/n,5) if n else 0.0,
            "profit_factor":round(sum(x for x in returns if x>0)/abs(sum(x for x in returns if x<0)),3) if any(x<0 for x in returns) else None,
            "longs":sum(t["side"]=="long" for t in trades),"shorts":sum(t["side"]=="short" for t in trades),
            "targets":sum(t["outcome"]=="target" for t in trades),"stops":sum(t["outcome"]=="stop" for t in trades)}

def leverage_sensitivity(trades):
    result={}
    for lev in LEVERAGES:
        eq=peak=1.0; dd=0.0; blown=False
        for t in trades:
            # Full-margin sizing: each trade uses current equity as isolated margin.
            # Simple stress approximation, not an exchange liquidation simulator.
            r=t["net_pct"]/100*lev
            if r<=-0.95:
                eq=0.0; blown=True; dd=100.0; break
            eq*=max(0,1+r); peak=max(peak,eq)
            if peak: dd=max(dd,(peak-eq)/peak)
        result[str(lev)+"x"]={"ending_equity_from_100":round(START_EQUITY*eq,2),
                              "return_pct":round((eq-1)*100,2),"max_drawdown_pct":round(dd*100,2),
                              "account_wiped_in_model":blown}
    return result

def main():
    now=dt.datetime.now(dt.timezone.utc)
    # End on the last fully completed UTC minute; avoids partial current candle.
    end_ms=(int(now.timestamp()*1000)//BAR_MS)*BAR_MS-BAR_MS
    start_ms=end_ms-DAYS*24*60*BAR_MS
    rows,sources,missing=load_history(start_ms,end_ms)
    # Drop duplicate timestamps and incomplete OHLC rows.
    rows=[r for r in rows if r[2]>=max(r[1],r[4]) and r[3]<=min(r[1],r[4]) and r[1]>0]
    report={"market":"Binance USD-M perpetual futures","symbol":SYMBOL,"timeframe":INTERVAL,"requested_days":DAYS,
            "start_utc":dt.datetime.fromtimestamp(start_ms/1000,dt.timezone.utc).isoformat(),
            "end_utc":dt.datetime.fromtimestamp(end_ms/1000,dt.timezone.utc).isoformat(),
            "candles_loaded":len(rows),"archive_sources":sources,"archive_periods_missing":missing,
            "fees":{"taker_each_side_pct":FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,
                    "round_trip_cost_pct_of_notional":2*(FEE_SIDE+SLIPPAGE_SIDE)*100},
            "strategies":{"ema_pullback":"EMA20/50/200 aligned trend; EMA20 reclaim after touch; RSI confirmation; stop 1.2 ATR; target 1.6R",
                          "trend_breakout":"20-candle range breakout; EMA50/200 trend; RSI and >1.2x average quote-volume confirmation; stop 1 ATR; target 1.5R",
                          "rsi_momentum":"EMA20/50/200 trend; RSI14 cross of 50; stop 1.1 ATR; target 1.5R"},
            "evaluation":"Chronological 70% research/train window and final 30% untouched holdout; signals at candle close, entry next candle open; stop counted first if stop and target touch in same candle. No live orders.",
            "funding":"Historical funding is not deducted; report is optimistic by this omission. Fees/slippage are fixed conservative assumptions.",
            "leverage_model":"Leverage sensitivity assumes full account equity used as isolated margin per trade; illustrative stress only, not exact Binance liquidation simulation.",
            "results":{}}
    if len(rows)<10_000:
        raise RuntimeError(f"Not enough 1m BTC futures candles: loaded {len(rows)}; refusing to label the backtest strong.")
    ind=indicators(rows); split=int(len(rows)*0.70)
    for name in ("ema_pullback","trend_breakout","rsi_momentum"):
        train=simulate(rows,ind,name,201,split-2)
        hold=simulate(rows,ind,name,split,len(rows)-2)
        full=simulate(rows,ind,name,201,len(rows)-2)
        report["results"][name]={"research_70pct":stats(train),"holdout_30pct":stats(hold),
                                  "full_period":stats(full),"holdout_leverage_sensitivity":leverage_sensitivity(hold)}
    # Candidate is eligible only if the untouched holdout is profitable after costs,
    # profit factor > 1, and at least 100 holdout trades. Otherwise report no validated winner.
    eligible=[]
    for name,res in report["results"].items():
        h=res["holdout_30pct"]
        if h["trades"]>=100 and h["net_sum_pct_of_notional"]>0 and h["profit_factor"] is not None and h["profit_factor"]>1:
            eligible.append((h["net_sum_pct_of_notional"],name))
    report["validated_candidate"]=max(eligible)[1] if eligible else None
    report["conclusion"]="No candidate met the pre-set out-of-sample validation rule." if not eligible else "Candidate passed the minimum out-of-sample profitability rule; this is not a guarantee of future profits."
    report["leverage_guidance"]="No leverage is recommended from this test unless a candidate passes the holdout rule; among tested leverage levels, prefer the lowest one with tolerable drawdown. Leverage does not improve strategy expectancy and magnifies both returns and losses."
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/btcusdt-futures-1m-180d.json","w",encoding="utf-8") as f:
        json.dump(report,f,indent=2,ensure_ascii=False)
    print(json.dumps(report,indent=2,ensure_ascii=False))
if __name__=="__main__":
    main()

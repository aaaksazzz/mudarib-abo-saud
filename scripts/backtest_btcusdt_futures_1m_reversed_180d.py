#!/usr/bin/env python3
"""Reverse-test three strategy signals on BTCUSDT USD-M perpetual 1m candles for 180 days.
Paper backtest only. Uses next-bar-open entries, conservative stop-first same-candle handling,
taker-fee and slippage assumptions, and a chronological holdout. No live orders."""
import csv, datetime as dt, io, json, math, os, time, urllib.parse, urllib.request, urllib.error, zipfile

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
DAYS = 180
BAR_MS = 60_000
FEE_SIDE = 0.0005       # assumed taker fee: 0.05% per side
SLIPPAGE_SIDE = 0.0002  # assumed 0.02% per side
COST_RT = 2 * (FEE_SIDE + SLIPPAGE_SIDE)
LOOKBACK = 20
LEVERS = [1, 2, 3, 5, 10]
BASES = ["https://fapi.binance.com", "https://fapi1.binance.com", "https://fapi2.binance.com", "https://fapi3.binance.com", "https://fapi4.binance.com"]
DATA_BASE = "https://data.binance.vision"

def get_bytes(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent":"SMART-TRADING-PRO-reversal-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def api(path, **params):
    q = urllib.parse.urlencode(params)
    errors = []
    for base in BASES:
        try:
            payload = json.loads(get_bytes(base + path + ("?" + q if q else "")).decode())
            if isinstance(payload, dict) and payload.get("code") and payload.get("msg"):
                errors.append(f"{base}: {payload.get('msg')}")
                continue
            return payload
        except Exception as e:
            errors.append(f"{base}: {e}")
    raise RuntimeError("Binance USD-M Futures API unavailable: " + " | ".join(errors[-3:]))

def month_starts(start, end):
    cur = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = []
    while cur <= end:
        out.append((cur.year, cur.month))
        cur = (cur.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out

def load_archive(year, month):
    fn = f"{SYMBOL}-{INTERVAL}-{year}-{month:02d}.zip"
    url = f"{DATA_BASE}/data/futures/um/monthly/klines/{SYMBOL}/{INTERVAL}/{fn}"
    try:
        with zipfile.ZipFile(io.BytesIO(get_bytes(url))) as z:
            name = next(n for n in z.namelist() if n.endswith(".csv"))
            out = []
            for r in csv.reader(io.TextIOWrapper(z.open(name), encoding="utf-8")):
                try:
                    out.append([int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
                except (ValueError, IndexError):
                    continue
            return out
    except Exception:
        return []

def load_rest(start_ms, end_ms):
    rows, cursor = [], start_ms
    while cursor <= end_ms:
        batch = api("/fapi/v1/klines", symbol=SYMBOL, interval=INTERVAL,
                    startTime=cursor, endTime=end_ms, limit=1000)
        if not batch:
            break
        rows.extend([[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in batch])
        nxt = int(batch[-1][0]) + BAR_MS
        if nxt <= cursor:
            break
        cursor = nxt
        if len(batch) < 1000:
            break
        time.sleep(0.04)
    return rows

def load_data():
    end = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    start = end - dt.timedelta(days=DAYS)
    start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    current_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for y, m in month_starts(start, end):
        month_start = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
        if month_start >= current_month:
            continue
        part = load_archive(y, m)
        rows.extend(r for r in part if start_ms <= r[0] <= end_ms)
        print(f"DATA archive {y}-{m:02d}: {len(part)} rows", flush=True)
    live_start = max(start_ms, int(current_month.timestamp()*1000))
    if live_start <= end_ms:
        try:
            rows.extend(load_rest(live_start, end_ms))
        except Exception as e:
            print("WARN current-month REST fallback:", str(e)[:300], flush=True)
    unique = {r[0]:r for r in rows if start_ms <= r[0] <= end_ms}
    data = [unique[k] for k in sorted(unique)]
    # If archives failed or left a material gap, attempt a complete REST load.
    expected = max(0, (end_ms-start_ms)//BAR_MS)
    if len(data) < expected * 0.90:
        print(f"WARN archive coverage {len(data)}/{expected}; trying full REST history", flush=True)
        try:
            full = load_rest(start_ms, end_ms)
            merged = {r[0]:r for r in data}
            merged.update({r[0]:r for r in full})
            data = [merged[k] for k in sorted(merged)]
        except Exception as e:
            print("WARN full REST fallback failed:", str(e)[:300], flush=True)
    return start_ms, end_ms, data

def stats(trades, start_idx, end_idx):
    subset = [t for t in trades if start_idx <= t["signal_i"] < end_idx]
    equity = peak = 1.0
    dd = 0.0
    for t in subset:
        equity *= max(0.0, 1.0 + t["net_pct"]/100.0)
        peak = max(peak, equity)
        if peak > 0:
            dd = max(dd, (peak-equity)/peak)
    n = len(subset)
    wins = sum(t["net_pct"] > 0 for t in subset)
    return {"trades":n, "wins":wins, "losses":n-wins,
            "win_rate_pct":round(100*wins/n,2) if n else 0.0,
            "net_compounded_return_pct":round((equity-1)*100,2),
            "max_drawdown_pct":round(dd*100,2),
            "avg_net_trade_pct":round(sum(t["net_pct"] for t in subset)/n,4) if n else 0.0,
            "long_trades":sum(t["direction"]=="long" for t in subset),
            "short_trades":sum(t["direction"]=="short" for t in subset),
            "targets":sum(t["outcome"]=="target" for t in subset),
            "stops":sum(t["outcome"]=="stop" for t in subset),
            "time_exits":sum(t["outcome"]=="time" for t in subset)}

def simulate(rows, strategy, reverse=False):
    trades = []
    closes = [r[4] for r in rows]
    for i in range(LOOKBACK, len(rows)-1):
        prior = rows[i-LOOKBACK:i]
        bar = rows[i]
        hi = max(x[2] for x in prior)
        lo = min(x[3] for x in prior)
        sample = closes[i-LOOKBACK:i]
        mean = sum(sample)/LOOKBACK
        sigma = math.sqrt(sum((x-mean)**2 for x in sample)/LOOKBACK)
        if sigma <= 0 or mean <= 0:
            continue
        swept_low = bar[3] < lo and bar[4] > lo
        swept_high = bar[2] > hi and bar[4] < hi
        avg_vol = sum(x[5] for x in prior)/LOOKBACK
        volume_ok = avg_vol > 0 and bar[5] >= 2.0*avg_vol
        z = (bar[4]-mean)/sigma

        # Original directions are explicit, then the reversed variant flips the entry direction.
        if strategy == "liquidity_sweep":
            original = "long" if swept_low else ("short" if swept_high else None)
        elif strategy == "math_extreme":
            original = "long" if z <= -2.0 else ("short" if z >= 2.0 else None)
        elif strategy == "whale_volume_proxy":
            original = ("long" if swept_low else ("short" if swept_high else None)) if volume_ok else None
        else:
            raise ValueError(strategy)
        if original is None:
            continue
        direction = ({"long":"short","short":"long"}[original] if reverse else original)
        entry_i = i+1
        entry = rows[entry_i][1]
        # Common, directionally valid risk model keeps the reversed direction test comparable.
        # ATR proxy is mean high-low range of the prior 20 completed candles.
        atr = sum(x[2]-x[3] for x in prior)/LOOKBACK
        risk = max(atr*1.5, entry*0.0008)
        if entry <= 0 or risk <= 0:
            continue
        stop = entry-risk if direction == "long" else entry+risk
        target = entry+2*risk if direction == "long" else entry-2*risk
        exit_price, exit_i, outcome = rows[-1][4], len(rows)-1, "time"
        # Avoid indefinite holding and avoid using future information at signal time.
        last_i = min(len(rows), entry_i+240)
        for j in range(entry_i, last_i):
            high, low = rows[j][2], rows[j][3]
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
        if outcome == "time" and last_i < len(rows):
            exit_i, exit_price = last_i-1, rows[last_i-1][4]
        gross = (exit_price-entry)/entry if direction == "long" else (entry-exit_price)/entry
        net = gross-COST_RT
        trades.append({"signal_i":i,"signal_time":bar[0],"entry_time":rows[entry_i][0],
                       "direction":direction,"entry":entry,"exit":exit_price,"outcome":outcome,
                       "gross_pct":gross*100,"net_pct":net*100})
    # Ensure trades do not overlap; use the signal list order and skip signals during an open trade.
    nonoverlap = []
    next_allowed = -1
    for t in trades:
        if t["signal_i"] < next_allowed:
            continue
        nonoverlap.append(t)
        exit_idx = next((j for j,r in enumerate(rows) if r[0] >= t["entry_time"] and j >= 0 and r[0] <= rows[-1][0]), None)
        # entry/exit times are timestamps; locate exit timestamp from simulated exit price is not unique,
        # so use entry index + 240 as conservative lockout only for time exits; target/stop trade exits
        # are reconstructed by scanning forward to first matching level in the next loop.
        # Simpler exact lockout is set by the recorded internal exit index below.
        next_allowed = t.get("exit_i", t["signal_i"]+1)
    return trades

def run_strategy(rows, strategy, reverse):
    # Standalone simulator with exact non-overlapping positions.
    trades=[]
    closes=[r[4] for r in rows]
    i=LOOKBACK
    while i < len(rows)-1:
        prior=rows[i-LOOKBACK:i]; bar=rows[i]
        hi=max(x[2] for x in prior); lo=min(x[3] for x in prior)
        sample=closes[i-LOOKBACK:i]; mean=sum(sample)/LOOKBACK
        sigma=math.sqrt(sum((x-mean)**2 for x in sample)/LOOKBACK)
        if sigma <= 0 or mean <= 0:
            i+=1; continue
        swept_low=bar[3]<lo and bar[4]>lo
        swept_high=bar[2]>hi and bar[4]<hi
        avg_vol=sum(x[5] for x in prior)/LOOKBACK
        volume_ok=avg_vol>0 and bar[5]>=2.0*avg_vol
        z=(bar[4]-mean)/sigma
        if strategy in ("liquidity_sweep","whale_volume_proxy"):
            original="long" if swept_low else ("short" if swept_high else None)
            if strategy=="whale_volume_proxy" and not volume_ok: original=None
        else:
            original="long" if z<=-2.0 else ("short" if z>=2.0 else None)
        if original is None:
            i+=1; continue
        direction=({"long":"short","short":"long"}[original] if reverse else original)
        entry_i=i+1; entry=rows[entry_i][1]
        atr=sum(x[2]-x[3] for x in prior)/LOOKBACK
        risk=max(atr*1.5,entry*0.0008)
        if entry<=0 or risk<=0:
            i+=1; continue
        stop=entry-risk if direction=="long" else entry+risk
        target=entry+2*risk if direction=="long" else entry-2*risk
        exit_price=rows[-1][4]; exit_i=len(rows)-1; outcome="time"
        end_i=min(len(rows),entry_i+241)
        for j in range(entry_i,end_i):
            high,low=rows[j][2],rows[j][3]
            if direction=="long":
                if low<=stop: exit_price,exit_i,outcome=stop,j,"stop"; break
                if high>=target: exit_price,exit_i,outcome=target,j,"target"; break
            else:
                if high>=stop: exit_price,exit_i,outcome=stop,j,"stop"; break
                if low<=target: exit_price,exit_i,outcome=target,j,"target"; break
        if outcome=="time" and end_i<len(rows):
            exit_i=end_i-1; exit_price=rows[exit_i][4]
        gross=(exit_price-entry)/entry if direction=="long" else (entry-exit_price)/entry
        net=gross-COST_RT
        trades.append({"signal_i":i,"signal_time":bar[0],"entry_time":rows[entry_i][0],
                       "exit_time":rows[exit_i][0],"direction":direction,"entry":entry,
                       "exit":exit_price,"outcome":outcome,"gross_pct":gross*100,"net_pct":net*100})
        i=exit_i+1
    return trades

def leverage_stats(trades, lev):
    equity=peak=1.0; dd=0.0; blown=False
    for t in trades:
        # Simple isolated-margin return approximation; does not model exchange liquidation/funding.
        trade_roi=(t["net_pct"]/100.0)*lev
        if trade_roi <= -1:
            trade_roi=-1.0; blown=True
        equity *= (1+trade_roi)
        peak=max(peak,equity)
        if peak>0: dd=max(dd,(peak-equity)/peak)
        if equity<=0: equity=0; break
    return {"leverage":f"{lev}x","net_compounded_margin_return_pct":round((equity-1)*100,2),
            "max_drawdown_pct":round(dd*100,2),"equity_wiped_in_model":blown}

def main():
    start_ms,end_ms,rows=load_data()
    expected=max(0,(end_ms-start_ms)//BAR_MS)
    if len(rows)<10000:
        raise RuntimeError(f"Insufficient BTCUSDT futures candles: got {len(rows)}, expected about {expected}; refusing to report a valid test")
    # Need near-continuous data; report missing candles explicitly.
    gaps=sum(1 for a,b in zip(rows,rows[1:]) if b[0]-a[0] > BAR_MS)
    split=int(len(rows)*0.70)
    definitions={
      "liquidity_sweep":"Sweep prior 20-candle extreme then close back inside; reversed mode flips the entry direction.",
      "math_extreme":"20-close z-score >= 2 or <= -2; reversed mode flips mean-reversion direction.",
      "whale_volume_proxy":"Liquidity sweep with current candle volume >= 2x prior 20-candle mean; proxy only, not wallet-level whale data."
    }
    report={"market":"Binance USD-M perpetual futures","symbol":SYMBOL,"timeframe":INTERVAL,
      "requested_period_days":DAYS,"candles_loaded":len(rows),"expected_candles_approx":expected,
      "coverage_pct":round(100*len(rows)/expected,2) if expected else 0,"missing_minute_gaps":gaps,
      "data_start_utc":dt.datetime.fromtimestamp(rows[0][0]/1000,dt.timezone.utc).isoformat(),
      "data_end_utc":dt.datetime.fromtimestamp(rows[-1][0]/1000,dt.timezone.utc).isoformat(),
      "train_holdout_split":"first 70% chronological / final 30% holdout",
      "cost_assumptions":{"taker_fee_each_side_pct":FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,
                          "round_trip_total_pct":COST_RT*100},
      "risk_model":"ATR proxy = mean high-low range of prior 20 candles; stop 1.5x ATR; target 2R; maximum hold 240 minutes; next-candle-open entry; stop wins if stop and target touch same candle.",
      "leverage_caveat":"Leverage table is a simplified compounded margin-return sensitivity. It excludes funding, maintenance margin, fee tiers, exchange liquidation mechanics, and gap/liquidity effects; not a live-trading recommendation.",
      "strategies":{}}
    for key,desc in definitions.items():
      report["strategies"][key]={"definition":desc,"original":{},"reversed":{}}
      for rev,label in ((False,"original"),(True,"reversed")):
        trades=run_strategy(rows,key,rev)
        report["strategies"][key][label]={
          "all_180d":stats(trades,0,len(rows)),
          "train_70pct":stats(trades,0,split),
          "holdout_30pct":stats(trades,split,len(rows)),
          "leverage_sensitivity_holdout":[{"base_unlevered":None,**leverage_stats([t for t in trades if split<=t["signal_i"]<len(rows)],lev)} for lev in LEVERS]
        }
        print("RESULT",key,label,json.dumps(report["strategies"][key][label],ensure_ascii=False),flush=True)
    report["completed_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    os.makedirs("backtest-results",exist_ok=True)
    with open("backtest-results/btcusdt-futures-1m-reversed-180d.json","w",encoding="utf-8") as f:
      json.dump(report,f,ensure_ascii=False,indent=2)
    print("FINAL_SUMMARY",json.dumps({"coverage_pct":report["coverage_pct"],"candles_loaded":len(rows),
      "data_start_utc":report["data_start_utc"],"data_end_utc":report["data_end_utc"],
      "strategies":{k:{v:{"holdout":d[v]["holdout_30pct"],"leverage":d[v]["leverage_sensitivity_holdout"]}
      for v in ("original","reversed")} for k,d in report["strategies"].items()}},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()

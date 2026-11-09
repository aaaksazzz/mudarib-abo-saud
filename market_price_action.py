"""Multi-market classical price-action scanner. No social/news sentiment or indicator strategy."""
import math, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import market_sultan_strategy

TIMEFRAMES=market_sultan_strategy.TIMEFRAMES  # W -> D -> 4h direction; 15m entry.
CACHE_SECONDS=60
_cache={}
_cursor={}
_lock=threading.Lock()
STRATEGY_FINGERPRINT=market_sultan_strategy.FINGERPRINT

def _bars(rows):
    if not isinstance(rows,list) or len(rows)<25: return []
    out=[]
    # Drop the live/incomplete candle returned by public providers.
    for r in rows[:-1]:
        try:
            if len(r)<6: continue
            o,h,l,c,v=map(float,r[1:6])
            if not all(math.isfinite(x) for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or h<max(o,c) or l>min(o,c) or h<l: continue
            out.append((o,h,l,c,v))
        except (TypeError,ValueError,IndexError): continue
    return out

def _pattern(rows):
    b=_bars(rows)
    if len(b)<22: return None
    o,h,l,c,v=zip(*b)
    i=len(b)-1
    prior_hi=max(h[i-20:i]); prior_lo=min(l[i-20:i])
    rng=h[i]-l[i]
    if rng<=0:return None
    body=abs(c[i]-o[i])/rng
    close_pos=(c[i]-l[i])/rng
    avg_vol=sum(v[i-20:i])/20
    vol_ratio=v[i]/avg_vol if avg_vol>0 else 0
    # Sweep is a wick through a prior 20-bar extreme followed by a closed reclaim.
    bull_sweep=l[i]<prior_lo and c[i]>prior_lo and c[i]>o[i] and close_pos>=0.62
    bear_sweep=h[i]>prior_hi and c[i]<prior_hi and c[i]<o[i] and close_pos<=0.38
    # A real breakout must close beyond structure with meaningful body; avoid wick-only breaks.
    bull_break=c[i]>prior_hi and c[i]>o[i] and body>=0.48 and close_pos>=0.72
    bear_break=c[i]<prior_lo and c[i]<o[i] and body>=0.48 and close_pos<=0.28
    if bull_sweep: return {"side":"BUY","kind":"سحب سيولة واسترجاع دعم","entry":c[i],"invalidation":l[i],"strength":2+(vol_ratio>=1.15)}
    if bear_sweep: return {"side":"SELL","kind":"سحب سيولة ورفض مقاومة","entry":c[i],"invalidation":h[i],"strength":2+(vol_ratio>=1.15)}
    if bull_break: return {"side":"BUY","kind":"اختراق مقاومة بإغلاق مؤكد","entry":c[i],"invalidation":prior_hi,"strength":1+(vol_ratio>=1.2)}
    if bear_break: return {"side":"SELL","kind":"كسر دعم بإغلاق مؤكد","entry":c[i],"invalidation":prior_lo,"strength":1+(vol_ratio>=1.2)}
    # Failed breakout/retest: price returns to broken level and closes back in breakout direction.
    resistance=max(h[i-20:i-5]); support=min(l[i-20:i-5])
    prior_bull_break=any(c[j]>resistance and c[j]>o[j] for j in range(i-5,i))
    prior_bear_break=any(c[j]<support and c[j]<o[j] for j in range(i-5,i))
    if prior_bull_break and l[i]<=resistance*1.002 and c[i]>resistance and c[i]>o[i] and close_pos>=0.62:
        return {"side":"BUY","kind":"إعادة اختبار ناجحة للمقاومة","entry":c[i],"invalidation":min(l[i],resistance),"strength":1}
    if prior_bear_break and h[i]>=support*0.998 and c[i]<support and c[i]<o[i] and close_pos<=0.38:
        return {"side":"SELL","kind":"إعادة اختبار ناجحة للدعم","entry":c[i],"invalidation":max(h[i],support),"strength":1}
    return None

def _atr(rows):
    b=_bars(rows)
    if len(b)<16:return 0
    tr=[]
    for i in range(max(1,len(b)-14),len(b)):
        prev=b[i-1][3]
        tr.append(max(b[i][1]-b[i][2],abs(b[i][1]-prev),abs(b[i][2]-prev)))
    return sum(tr)/len(tr) if tr else 0

def _levels(entry,stop,side,rows):
    risk=entry-stop if side=="BUY" else stop-entry
    if risk<=0 or entry<=0 or risk/entry>0.08:return None
    b=_bars(rows)
    if len(b)<20:return None
    highs=[x[1] for x in b[-30:]]; lows=[x[2] for x in b[-30:]]
    sign=1 if side=="BUY" else -1
    # Structural targets where possible; fall back to exact 1R/2R/3R only when no clear swing lies ahead.
    candidates=sorted(set((highs if side=="BUY" else lows)),reverse=(side=="SELL"))
    targets=[]
    for p in candidates:
        reward=(p-entry)*sign
        if reward>=risk*0.9 and (not targets or abs(p-targets[-1])>risk*0.2):
            targets.append(p)
        if len(targets)==3:break
    for mult in (1,2,3):
        p=entry+sign*risk*mult
        if len(targets)<3 and p>0 and (not targets or abs(p-targets[-1])>risk*0.2):targets.append(p)
    targets=sorted(targets[:3],reverse=(side=="SELL"))
    if len(targets)<3 or min(targets)<=0:return None
    return {"stop":stop,"tp1":targets[0],"tp2":targets[1],"tp3":targets[2],"risk_pct":risk/entry*100,
            "reward_risk_tp3":abs(targets[2]-entry)/risk}

def _inspect(item,market,klines_fn):
    """Apply weekly/daily/4h directional alignment and a completed 15m entry."""
    return market_sultan_strategy.inspect(
        item, market, klines_fn, _pattern, _atr, _levels
    )

def scan_market(market,universe,klines_fn,limit=8):
    now=time.time()
    with _lock:
        old=_cache.get(market)
        if old and now-old[0]<CACHE_SECONDS:return dict(old[1],cached=True)
        ordered=sorted(universe,key=lambda x:float(x.get("quote_volume") or 0),reverse=True)
        if not ordered:
            return {"ok":True,"market":market,"engine":"SULTAN_MULTI_TIMEFRAME_V1",
                    "checked_assets":0,"universe_total":0,"scan_offset":0,
                    "signals_found":0,"analysis_errors":0,"signals":[],
                    "updated_at":datetime.now(timezone.utc).isoformat(),"cached":False,
                    "coverage":"لا توجد أصول مؤهلة من مزود السوق حالياً",
                    "strategy_fingerprint":STRATEGY_FINGERPRINT}
        offset=_cursor.get(market,0)%len(ordered)
        take=min(max(1,int(limit)),len(ordered))
        end=offset+take
        batch=ordered[offset:end] if end<=len(ordered) else ordered[offset:]+ordered[:end-len(ordered)]
        _cursor[market]=(offset+take)%len(ordered)
    found=[];failed=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(_inspect,x,market,klines_fn) for x in batch]
        for f in as_completed(jobs):
            try:
                x=f.result()
                if x:found.append(x)
            except Exception:failed+=1
    found.sort(key=lambda x:(x["score"],float(x.get("quote_volume") or 0)),reverse=True)
    # If every requested candle fetch failed, this is a provider outage, not
    # a valid empty-signal scan. Never cache or present it as "no opportunities".
    if failed==len(batch) and batch:
        return {"ok":False,"market":market,"engine":"SULTAN_MULTI_TIMEFRAME_V1",
                "provider_error":True,"error_code":"all_candle_requests_failed",
                "checked_assets":len(batch),"universe_total":len(ordered),"scan_offset":offset,
                "signals_found":0,"analysis_errors":failed,"signals":[],
                "updated_at":datetime.now(timezone.utc).isoformat(),"cached":False,
                "coverage":"تعذر جلب شموع أحد الفريمات المطلوبة من مزود البيانات؛ لم يتم اعتماد نتيجة فحص",
                "strategy_fingerprint":STRATEGY_FINGERPRINT}
    payload={"ok":True,"market":market,"engine":"SULTAN_MULTI_TIMEFRAME_V1",
             "checked_assets":len(batch),"universe_total":len(ordered),"scan_offset":offset,
             "signals_found":len(found),"analysis_errors":failed,"signals":found[:30],
             "updated_at":datetime.now(timezone.utc).isoformat(),"cached":False,
             "coverage":"فحص متناوب لجميع الأصول المؤهلة؛ اتجاه أسبوعي ويومي و4 ساعات مع دخول 15 دقيقة",
             "strategy_fingerprint":STRATEGY_FINGERPRINT}
    with _lock:_cache[market]=(now,payload)
    return payload

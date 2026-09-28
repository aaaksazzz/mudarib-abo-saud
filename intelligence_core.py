"""AI MARKET BRAIN — EMA20 / EMA50 / RSI LEARNING ENGINE

Primary direction is fixed and transparent:
- صاعد: price > EMA20 and EMA50 and RSI14 > 50
- هابط: price < EMA20 and EMA50 and RSI14 < 50
- عرضي: overlapping EMAs / price moving inside their range

Learning is persistent: closed trades are stored and used to calibrate confidence
by market, symbol and timeframe. Learning does not invent a direction or alter
the core rules automatically.

import json, math, statistics, time
from db import rows, execute

MODEL_VERSION = "EMA20_EMA50_RSI_LEARNING_V1"

def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

def _clamp(x,a,b):
    return max(a,min(b,float(x)))

def _pct(a,b):
    """Safe percentage distance between two positive prices."""
    a=_f(a); b=_f(b)
    if not a: return 0.0
    return (b-a)/abs(a)*100.0

def _pattern(k, end, width=28):
    """Convert raw candles into a shape fingerprint. No named indicators."""
    start=max(1,end-width+1)
    if end-start+1 < 16:
        return None
    base=max(abs(_f(k[end][4])),1e-12)
    feats=[]
    for i in range(start,end+1):
        o,h,l,c=map(_f,(k[i][1],k[i][2],k[i][3],k[i][4]))
        prev=_f(k[i-1][4],c)
        rng=max(h-l,base*1e-9)
        feats.extend([
            _clamp((c-o)/rng,-3,3),
            _clamp((max(o,c)-min(o,c))/rng,0,3),
            _clamp((h-max(o,c))/rng,0,3),
            _clamp((min(o,c)-l)/rng,0,3),
            _clamp((c-prev)/base*100,-20,20),
            math.log1p(max(_f(k[i][5]),0))
        ])
    return feats

def _distance(a,b):
    if not a or not b or len(a)!=len(b): return 999.0
    # Shape gets more weight than absolute price.
    d=0.0
    for x,y in zip(a,b):
        scale=1.0+abs(x)+abs(y)
        d += ((x-y)/scale)**2
    return math.sqrt(d/len(a))

def _future_move(k,i,h):
    if i+h>=len(k): return None
    p=_f(k[i][4])
    q=_f(k[i+h][4])
    if p<=0:return None
    return (q-p)/p*100.0

def _analogue_memory(k):
    """Find similar historical raw-price shapes and let their later behaviour vote."""
    end=len(k)-1
    current=_pattern(k,end)
    if not current:return []
    candidates=[]
    # Leave enough candles after each historical pattern for an observed outcome.
    for i in range(40,end-14,3):
        past=_pattern(k,i)
        if not past: continue
        d=_distance(current,past)
        if d>=1.75: continue
        moves=[_future_move(k,i,h) for h in (3,6,12) if _future_move(k,i,h) is not None]
        if not moves: continue
        candidates.append({
            "i":i,"distance":d,
            "m3":_future_move(k,i,3),
            "m6":_future_move(k,i,6),
            "m12":_future_move(k,i,12)
        })
    candidates.sort(key=lambda x:x["distance"])
    return candidates[:18]

def _persistent_memory(market,tf):
    try:
        return rows(
            "SELECT context_json,side,outcome,pnl FROM ai_memory "
            "WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 300",
            (market,tf)
        )
    except Exception:
        return []

def _memory_vote(items):
    if not items:return None
    vals=[]
    for x in items:
        try:
            c=json.loads(x.get("context_json") or "{}")
        except Exception:
            c={}
        vals.append((c.get("pattern"),x.get("side"),x.get("outcome"),_f(x.get("pnl"))))
    return vals


def _brain_state(market, symbol, timeframe):
    """Read persistent server-side knowledge for this exact market/symbol/timeframe."""
    try:
        return rows(
            "SELECT * FROM ai_brain_state WHERE market=? AND symbol=? AND timeframe=? LIMIT 1",
            (market, symbol or "", timeframe)
        )[0]
    except Exception:
        return None


def _memory_profile(market, symbol, timeframe):
    """Build a conservative profile from preserved historical outcomes.
    The tracker reset must never erase this learning memory.
    """
    exact = _brain_state(market, symbol, timeframe) if symbol else None
    try:
        broad = rows(
            "SELECT outcome,pnl,side,ai_model_version,created_at,context_json FROM ai_memory "
            "WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 500",
            (market, timeframe)
        )
    except Exception:
        broad = []
    if not broad and not exact:
        return {"samples":0,"win_rate":0.0,"pnl":0.0,"loss_streak":0,
                "exact_samples":0,"exact_win_rate":0.0,"exact_memory_samples":0,
                "successful_contexts":[],"failed_contexts":[],"source":"empty"}

    wins=sum(1 for x in broad if x.get("outcome")=="win")
    total=len(broad)
    loss_streak=0
    for x in broad:
        if x.get("outcome")=="loss":
            loss_streak+=1
        else:
            break
    # Rebuild exact-symbol learning from ai_memory if the hot state row is missing.
    exact_memory = []
    if symbol:
        try:
            exact_memory = rows(
                "SELECT outcome,pnl,side,context_json FROM ai_memory "
                "WHERE market=? AND symbol=? AND timeframe=? ORDER BY id DESC LIMIT 300",
                (market, symbol, timeframe)
            )
        except Exception:
            exact_memory = []
    exact_wins = sum(1 for x in exact_memory if x.get("outcome") == "win")
    exact_total = len(exact_memory)
    successful = [x for x in exact_memory if x.get("outcome") == "win"]
    failed = [x for x in exact_memory if x.get("outcome") == "loss"]

    return {
        "samples":total,
        "win_rate":wins/max(total,1),
        "pnl":sum(_f(x.get("pnl")) for x in broad),
        "loss_streak":loss_streak,
        "exact_samples":int(exact.get("samples",0)) if exact else 0,
        "exact_win_rate":(
            exact_wins/max(exact_total,1)
            if exact_total else (
                _f(exact.get("wins"))/max(_f(exact.get("samples")),1)
                if exact else 0.0
            )
        ),
        "exact_memory_samples":exact_total,
        "successful_contexts":[x.get("context_json") for x in successful[:5] if x.get("context_json")],
        "failed_contexts":[x.get("context_json") for x in failed[:5] if x.get("context_json")],
        "source":"exact+market_timeframe" if exact or exact_total else "market_timeframe"
    }


def _memory_guard(profile):
    """Return a small confidence/abstention adjustment; memory never invents direction."""
    n=int(profile.get("samples",0))
    if n < 20:
        return {"bonus":0.0,"abstain":False,"reason":"warming_up"}
    streak=int(profile.get("loss_streak",0))
    wr=_f(profile.get("win_rate"))
    bonus=_clamp((wr-0.5)*12,-6,6)
    # A prolonged losing run makes the brain wait for stronger evidence.
    abstain = streak >= 6 and wr < 0.48
    return {"bonus":bonus,"abstain":abstain,"reason":"loss_streak" if abstain else "memory_calibrated"}



def _advanced_context(k):
    """Broad descriptive evidence families derived only from available OHLCV."""
    n=len(k)
    closes=[_f(x[4]) for x in k[-40:]]
    highs=[_f(x[2]) for x in k[-40:]]
    lows=[_f(x[3]) for x in k[-40:]]
    vols=[_f(x[5]) for x in k[-40:]]
    def slope(v):
        if len(v)<3:return 0
        xm=(len(v)-1)/2; ym=sum(v)/len(v); den=sum((i-xm)**2 for i in range(len(v))) or 1
        return sum((i-xm)*(x-ym) for i,x in enumerate(v))/den
    recent_ranges=[max(_f(x[2])-_f(x[3]),0) for x in k[-18:]]
    med_r=statistics.median(recent_ranges) if recent_ranges else 1
    med_v=statistics.median(vols[-12:]) if vols else 1
    last=_candle_raw(k[-1])
    hi=max(highs); lo=min(lows)
    return {
        "structure":{"high":hi,"low":lo,"range_position":(last["c"]-lo)/max(hi-lo,1e-12),
                     "raw_slope":slope(closes)},
        "liquidity":{"upper_rejection":last["upper"]/max(last["range"],1e-12),
                     "lower_rejection":last["lower"]/max(last["range"],1e-12)},
        "volume_price":{"relative_volume":last["v"]/max(med_v,1e-12),
                        "volume_direction":1 if last["c"]>last["o"] else -1},
        "range_behavior":{"expansion":last["range"]/max(med_r,1e-12),
                          "compression":statistics.median(recent_ranges[-6:])/max(statistics.median(recent_ranges),1e-12)},
        "path":{"balance":sum(1 if closes[i]>closes[i-1] else -1 if closes[i]<closes[i-1] else 0 for i in range(1,len(closes)))/max(len(closes)-1,1)},
        "extremes":{"distance_to_high":_pct(hi,last["c"]),"distance_to_low":_pct(last["c"],lo)}
    }

def _manipulation_context(k):
    """Defensive detection of manipulation-like OHLCV footprints."""
    if len(k) < 25:
        return {"risk":"unknown","score":0.0,"signals":[],"action":"wait"}
    def cv(x):
        o,h,l,c=map(_f,(x[1],x[2],x[3],x[4]))
        return o,h,l,c,max(h-l,1e-12),_f(x[5])
    recent=k[-12:]; prior=k[-25:-12]
    pr=[cv(x) for x in prior]; rr=[cv(x) for x in recent]
    hi=max(x[2] for x in pr); lo=min(x[3] for x in pr)
    o,h,l,c,r,v=rr[-1]
    med_v=statistics.median([x[5] for x in pr]) or 1.0
    vr=v/med_v
    up=max(h-max(o,c),0)/r; dn=max(min(o,c)-l,0)/r
    sweep_hi=h>hi and c<hi; sweep_lo=l<lo and c>lo
    score=0.0; signals=[]
    if sweep_hi: score+=.30; signals.append("liquidity_sweep_high")
    if sweep_lo: score+=.30; signals.append("liquidity_sweep_low")
    if vr>=2.0 and abs(c-o)/r<.35:
        score+=.25; signals.append("abnormal_volume_absorption")
    if up>=.55 and c<o:
        score+=.15; signals.append("upper_rejection_trap")
    if dn>=.55 and c>o:
        score+=.15; signals.append("lower_rejection_trap")
    score=_clamp(score,0,1)
    risk="high" if score>=.65 else "elevated" if score>=.35 else "normal"
    action="wait_for_confirmation" if (sweep_hi or sweep_lo) and score>=.35 else "trade_post_event" if score>=.35 else "normal_analysis"
    return {"risk":risk,"score":round(score,3),"signals":signals,
            "liquidity_sweep":bool(sweep_hi or sweep_lo),"volume_ratio":round(vr,2),
            "upper_rejection":round(up,3),"lower_rejection":round(dn,3),
            "action":action,
            "note":"OHLCV cannot prove spoofing; these are footprint detections."}

def _candle_raw(x):
    o,h,l,c=map(_f,(x[1],x[2],x[3],x[4]))
    return {"o":o,"h":h,"l":l,"c":c,"v":_f(x[5]),"range":max(h-l,1e-12),
            "upper":max(h-max(o,c),0),"lower":max(min(o,c)-l,0)}

def _raw_context(k):
    n=len(k)
    o,h,l,c=map(_f,(k[-1][1],k[-1][2],k[-1][3],k[-1][4]))
    prev=_f(k[-2][4],c)
    ranges=[max(_f(x[2])-_f(x[3]),0) for x in k[-12:]]
    recent=[_f(x[4]) for x in k[-20:]]
    hi=max(_f(x[2]) for x in k[-20:])
    lo=min(_f(x[3]) for x in k[-20:])
    avg_range=statistics.median(ranges) if ranges else max(h-l,1e-12)
    body=abs(c-o)
    upper=max(h-max(o,c),0)
    lower=max(min(o,c)-l,0)
    path=sum(1 if recent[i]>recent[i-1] else -1 if recent[i]<recent[i-1] else 0 for i in range(1,len(recent)))
    return {
        "last_return": (c-prev)/prev*100 if prev else 0,
        "body_fraction": body/max(h-l,1e-12),
        "upper_wick_fraction": upper/max(h-l,1e-12),
        "lower_wick_fraction": lower/max(h-l,1e-12),
        "range_vs_recent_median": (h-l)/max(avg_range,1e-12),
        "position_in_recent_range": (c-lo)/max(hi-lo,1e-12),
        "path_balance": path/max(len(recent)-1,1),
        "pattern": _pattern(k,n-1),
    }

def _build_levels(k,side,entry,analog_moves):
    """
    Stop is the only basis for profit targets.
    TP1 = 1R, TP2 = 2R, TP3 = 3R, TP4 = 4R.
    The AI may determine the stop, but targets never use analogue moves,
    indicators, structure, or any other target formula.
    """
    lows=[_f(x[3]) for x in k[-24:]]
    highs=[_f(x[2]) for x in k[-24:]]
    # Put the stop beyond the recent structure plus a volatility buffer.
    # This avoids placing it directly on an obvious swing where normal noise
    # can trigger it. Risk is capped so unusually wide structures are rejected.
    trs=[]
    for i in range(max(1,len(k)-24),len(k)):
        h=_f(k[i][2]); lo=_f(k[i][3]); prev=_f(k[i-1][4])
        trs.append(max(h-lo,abs(h-prev),abs(lo-prev)))
    atr=sum(trs[-14:])/max(len(trs[-14:]),1)
    if atr<=0:
        return None
    buffer=0.55*atr
    if side=="شراء":
        structural=min(lows)
        sl=structural-buffer
        if sl>=entry:
            return None
        risk_pct=abs(entry-sl)/entry
        if risk_pct<=0 or risk_pct>0.15:
            return None
        tp1=entry*(1+risk_pct)
        tp2=entry*(1+risk_pct*2)
        tp3=entry*(1+risk_pct*3)
        tp4=entry*(1+risk_pct*4)
        if not (sl<entry<tp1<tp2<tp3<tp4):
            return None
    else:
        structural=max(highs)
        sl=structural+buffer
        if sl<=entry:
            return None
        risk_pct=abs(sl-entry)/entry
        if risk_pct<=0 or risk_pct>0.15:
            return None
        tp1=entry*(1-risk_pct)
        tp2=entry*(1-risk_pct*2)
        tp3=entry*(1-risk_pct*3)
        tp4=entry*(1-risk_pct*4)
        if not (sl>entry>tp1>tp2>tp3>tp4):
            return None
    return sl,tp1,tp2,tp3,tp4


def _self_improvement_review(market, timeframe):
    """Evaluate recent out-of-sample memory without changing the brain blindly."""
    try:
        items=rows("SELECT context_json,side,outcome,pnl,created_at FROM ai_memory WHERE market=? AND timeframe=? ORDER BY id DESC LIMIT 300",(market,timeframe))
    except Exception:
        return {"status":"unavailable"}
    if len(items)<20:
        return {"status":"warming_up","samples":len(items)}
    wins=sum(1 for x in items if x.get("outcome")=="win")
    pnl=sum(_f(x.get("pnl")) for x in items)
    rate=wins/len(items)
    # Compare recent half with older half: this is monitoring, not self-deception.
    mid=len(items)//2
    recent=items[:mid]; older=items[mid:]
    rr=sum(1 for x in recent if x.get("outcome")=="win")/max(len(recent),1)
    orr=sum(1 for x in older if x.get("outcome")=="win")/max(len(older),1)
    return {
        "status":"evaluated","samples":len(items),"win_rate":round(rate*100,2),
        "pnl":round(pnl,6),"recent_win_rate":round(rr*100,2),
        "older_win_rate":round(orr*100,2),
        "drift":round((rr-orr)*100,2),
        "model_version":MODEL_VERSION,
        "policy":"monitor_only_until_oos_validation"
    }

def self_improvement_cycle(market, timeframe):
    """Safe self-evolution hook: measure performance and market drift; never edits code live."""
    review=_self_improvement_review(market,timeframe)
    return {
        "model_version":MODEL_VERSION,
        "market":market,"timeframe":timeframe,
        "review":review,
        "next_step":"candidate_changes_must_pass_out_of_sample_validation",
        "auto_apply":False
    }


def _ema_series(values, period):
    values=[_f(x) for x in values]
    if len(values)<period:return []
    seed=sum(values[:period])/period
    out=[seed]; alpha=2.0/(period+1); e=seed
    for x in values[period:]:
        e=alpha*x+(1-alpha)*e
        out.append(e)
    return out

def _sma(values, period):
    values=[_f(x) for x in values]
    if len(values)<period:return None
    return sum(values[-period:])/period

def _ema_last(values, period):
    s=_ema_series(values,period)
    return s[-1] if s else None

def _wma(values, period):
    if len(values)<period:return None
    v=[_f(x) for x in values[-period:]]
    den=period*(period+1)/2
    return sum(x*(i+1) for i,x in enumerate(v))/den

def _hull(values, period=9):
    half=max(period//2,1); root=max(int(math.sqrt(period)),1)
    if len(values)<period+root:return None
    raw=[]
    for i in range(half,len(values)+1):
        a=_wma(values[:i],half); b=_wma(values[:i],period)
        if a is not None and b is not None: raw.append(2*a-b)
    return _wma(raw,root) if len(raw)>=root else None

def _rsi_last(values, period=14):
    v=[_f(x) for x in values]
    if len(v)<period+1:return None
    gains=[]; losses=[]
    for i in range(1,len(v)):
        d=v[i]-v[i-1]; gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    return 100.0 if al==0 else 100-100/(1+ag/al)

def _stoch_last(highs,lows,closes,period=14):
    if len(closes)<period:return None
    hi=max(highs[-period:]); lo=min(lows[-period:])
    return (closes[-1]-lo)/max(hi-lo,1e-12)*100

def _cci_last(highs,lows,closes,period=20):
    if len(closes)<period:return None
    tp=[(h+l+c)/3 for h,l,c in zip(highs,lows,closes)]
    mean=sum(tp[-period:])/period
    dev=sum(abs(x-mean) for x in tp[-period:])/period
    return (tp[-1]-mean)/(0.015*max(dev,1e-12))

def _adx_last(highs,lows,closes,period=14):
    if len(closes)<period*2+1:return None
    trs=[]; plus=[]; minus=[]
    for i in range(1,len(closes)):
        tr=max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
        up=highs[i]-highs[i-1]; dn=lows[i-1]-lows[i]
        trs.append(tr); plus.append(up if up>dn and up>0 else 0); minus.append(dn if dn>up and dn>0 else 0)
    atr=sum(trs[:period])/period; ap=sum(plus[:period])/period; am=sum(minus[:period])/period
    dxs=[]
    for i in range(period,len(trs)):
        atr=(atr*(period-1)+trs[i])/period; ap=(ap*(period-1)+plus[i])/period; am=(am*(period-1)+minus[i])/period
        pdi=100*ap/max(atr,1e-12); mdi=100*am/max(atr,1e-12)
        dxs.append(100*abs(pdi-mdi)/max(pdi+mdi,1e-12))
    return sum(dxs[-period:])/period if len(dxs)>=period else None

def _macd_last(closes):
    e12=_ema_series(closes,12); e26=_ema_series(closes,26)
    if not e12 or not e26:return None,None
    start=len(closes)-len(e26); macd=[]
    for j in range(len(e26)):
        idx=start+j; e12_idx=idx-11
        if 0<=e12_idx<len(e12): macd.append(e12[e12_idx]-e26[j])
    if len(macd)<9:return None,None
    return macd[-1],_ema_last(macd,9)

def _stoch_rsi_last(closes):
    v=[_f(x) for x in closes]
    if len(v)<40:return None,None
    rsis=[_rsi_last(v[:i+1],14) for i in range(14,len(v))]
    rsis=[x for x in rsis if x is not None]
    if len(rsis)<14:return None,None
    raw=[]
    for i in range(13,len(rsis)):
        lo=min(rsis[i-13:i+1]); hi=max(rsis[i-13:i+1])
        raw.append((rsis[i]-lo)/max(hi-lo,1e-12)*100)
    if len(raw)<3:return None,None
    return _sma(raw,3),_sma(raw[-3:],3)

def _ultimate_last(highs,lows,closes):
    if len(closes)<29:return None
    bp=[]; tr=[]
    for i in range(1,len(closes)):
        bp.append(closes[i]-min(lows[i],closes[i-1]))
        tr.append(max(highs[i],closes[i-1])-min(lows[i],closes[i-1]))
    def avg(p): return sum(bp[-p:])/max(sum(tr[-p:]),1e-12)
    return 100*(4*avg(7)+2*avg(14)+avg(28))/7

def _trendview_rating(klines):
    """Local reproduction of the published TradingView Technical Ratings methodology."""
    if len(klines)<220:return None
    h=[_f(x[2]) for x in klines]; l=[_f(x[3]) for x in klines]; c=[_f(x[4]) for x in klines]; v=[_f(x[5]) for x in klines]
    if not c or c[-1]<=0:return None
    votes=[]
    def vm(x): return 1 if x is not None and c[-1]>x else -1 if x is not None and c[-1]<x else 0
    for p in (10,20,30,50,100,200): votes.append(vm(_sma(c,p)))
    for p in (10,20,30,50,100,200): votes.append(vm(_ema_last(c,p)))
    votes.append(vm(_hull(c,9)))
    vw=sum(c[i]*v[i] for i in range(len(c)-20,len(c)))/max(sum(v[-20:]),1e-12)
    votes.append(vm(vw))
    conv=(max(h[-9:])+min(l[-9:]))/2; base=(max(h[-26:])+min(l[-26:]))/2; span_b=(max(h[-52:])+min(l[-52:]))/2; span_a=(conv+base)/2
    votes.append(1 if span_a>span_b and base>span_a and conv>base and c[-1]>conv else -1 if span_a<span_b and base<span_a and conv<base and c[-1]<conv else 0)
    ma_score=sum(votes)/len(votes)

    osc=[]
    r=_rsi_last(c,14); rp=_rsi_last(c[:-1],14)
    osc.append(1 if r is not None and rp is not None and r<30 and r>rp else -1 if r is not None and rp is not None and r>70 and r<rp else 0)
    sk=_stoch_last(h,l,c,14); skp=_stoch_last(h[:-1],l[:-1],c[:-1],14)
    osc.append(1 if sk is not None and skp is not None and sk<20 and sk>skp else -1 if sk is not None and skp is not None and sk>80 and sk<skp else 0)
    cc=_cci_last(h,l,c,20); ccp=_cci_last(h[:-1],l[:-1],c[:-1],20)
    osc.append(1 if cc is not None and ccp is not None and cc<-100 and cc>ccp else -1 if cc is not None and ccp is not None and cc>100 and cc<ccp else 0)
    adx=_adx_last(h,l,c,14); adxp=_adx_last(h[:-1],l[:-1],c[:-1],14)
    def di14(hh,ll,cc):
        if len(cc)<29:return None,None
        tr=[];pp=[];mm=[]
        for i in range(1,len(cc)):
            x=max(hh[i]-ll[i],abs(hh[i]-cc[i-1]),abs(ll[i]-cc[i-1])); up=hh[i]-hh[i-1];dn=ll[i-1]-ll[i]
            tr.append(x);pp.append(up if up>dn and up>0 else 0);mm.append(dn if dn>up and dn>0 else 0)
        a=sum(tr[:14])/14;p=sum(pp[:14])/14;m=sum(mm[:14])/14
        for i in range(14,len(tr)):
            a=(a*13+tr[i])/14;p=(p*13+pp[i])/14;m=(m*13+mm[i])/14
        return 100*p/max(a,1e-12),100*m/max(a,1e-12)
    pdi,mdi=di14(h,l,c)
    osc.append(1 if adx is not None and adxp is not None and adx>20 and adx>adxp and pdi is not None and pdi>mdi else -1 if adx is not None and adxp is not None and adx>20 and adx<adxp and pdi is not None and pdi<mdi else 0)
    mid=[(a+b)/2 for a,b in zip(h,l)]
    ao=(_sma(mid,5)-_sma(mid,34)) if len(mid)>=34 else None
    aop=(_sma(mid[:-1],5)-_sma(mid[:-1],34)) if len(mid)>=35 else None
    aop2=(_sma(mid[:-2],5)-_sma(mid[:-2],34)) if len(mid)>=36 else None
    osc.append(1 if ao is not None and ((ao>0 and aop is not None and aop<=0) or (ao>0 and aop is not None and aop>0 and aop2 is not None and aop>aop2)) else -1 if ao is not None and ((ao<0 and aop is not None and aop>=0) or (ao<0 and aop is not None and aop<0 and aop2 is not None and aop<aop2)) else 0)
    m=c[-1]-c[-11] if len(c)>=11 else None; mp=c[-2]-c[-12] if len(c)>=12 else None
    osc.append(1 if m is not None and mp is not None and m>mp else -1 if m is not None and mp is not None and m<mp else 0)
    mac,sig=_macd_last(c); osc.append(1 if mac is not None and sig is not None and mac>sig else -1 if mac is not None and sig is not None and mac<sig else 0)
    srk,srd=_stoch_rsi_last(c); osc.append(1 if srk is not None and srd is not None and srk<20 and srd<20 and srk>srd else -1 if srk is not None and srd is not None and srk>80 and srd>80 and srk<srd else 0)
    wr=(max(h[-14:])-c[-1])/max(max(h[-14:])-min(l[-14:]),1e-12)*-100 if len(c)>=14 else None
    wrp=(max(h[-15:-1])-c[-2])/max(max(h[-15:-1])-min(l[-15:-1]),1e-12)*-100 if len(c)>=15 else None
    osc.append(1 if wr is not None and wrp is not None and wr<-80 and wr>wrp else -1 if wr is not None and wrp is not None and wr>-20 and wr<wrp else 0)
    e13=_ema_last(c,13); e13p=_ema_last(c[:-1],13)
    bull=h[-1]-e13 if e13 is not None else None; bear=l[-1]-e13 if e13 is not None else None; bullp=h[-2]-e13p if e13p is not None else None; bearp=l[-2]-e13p if e13p is not None else None
    osc.append(1 if bull is not None and bear is not None and bull>0 and bear<0 and bearp is not None and bear>bearp else -1 if bull is not None and bear is not None and bear>0 and bull<0 and bullp is not None and bull<bullp else 0)
    uo=_ultimate_last(h,l,c); osc.append(1 if uo is not None and uo>70 else -1 if uo is not None and uo<30 else 0)
    osc_score=sum(osc)/len(osc); score=(ma_score+osc_score)/2
    # Slightly wider neutral band to allow more real monthly signals.
    # Strong ratings remain strict; ordinary Buy/Sell can pass with a small edge.
    rec="شراء قوي" if score>0.5 else "شراء" if score>0.02 else "محايد" if score>=-0.02 else "بيع" if score>=-0.5 else "بيع قوي"
    return {"score":score,"ma_score":ma_score,"osc_score":osc_score,"recommendation":rec,"side":"شراء" if score>0.02 else "بيع" if score<-0.02 else None,"components":26}

def _monthly_price_action_master(klines):
    """Monthly master direction from raw price action only. No indicators."""
    if len(klines) < 40:
        return None
    k=klines
    closes=[_f(x[4]) for x in k]
    highs=[_f(x[2]) for x in k]
    lows=[_f(x[3]) for x in k]
    if not closes or closes[-1] <= 0:
        return None
    # Use multiple raw monthly windows: swing structure, breakouts and candle path.
    recent=24
    prev=24
    cur_h=max(highs[-recent:])
    cur_l=min(lows[-recent:])
    prev_h=max(highs[-recent-prev:-recent])
    prev_l=min(lows[-recent-prev:-recent])
    hh=sum(1 for i in range(max(1,len(k)-12),len(k)) if highs[i]>highs[i-1])
    hl=sum(1 for i in range(max(1,len(k)-12),len(k)) if lows[i]>lows[i-1])
    lh=sum(1 for i in range(max(1,len(k)-12),len(k)) if highs[i]<highs[i-1])
    ll=sum(1 for i in range(max(1,len(k)-12),len(k)) if lows[i]<lows[i-1])
    long_move=(closes[-1]-closes[-13])/max(abs(closes[-13]),1e-12)
    mid_move=(closes[-1]-closes[-25])/max(abs(closes[-25]),1e-12)
    old_ref=closes[-49] if len(closes)>=49 else closes[0]
    long_move_48=(closes[-1]-old_ref)/max(abs(old_ref),1e-12)
    bull=0
    bear=0
    if closes[-1] > closes[-2]: bull += 1
    elif closes[-1] < closes[-2]: bear += 1
    if closes[-1] > max(closes[-13:-1]): bull += 2
    elif closes[-1] < min(closes[-13:-1]): bear += 2
    if cur_h > prev_h: bull += 2
    if cur_l > prev_l: bull += 2
    if cur_h < prev_h: bear += 2
    if cur_l < prev_l: bear += 2
    if hh > lh: bull += 1
    if hl > ll: bull += 1
    if lh > hh: bear += 1
    if ll > hl: bear += 1
    if long_move > 0: bull += 1
    elif long_move < 0: bear += 1
    if mid_move > 0: bull += 1
    elif mid_move < 0: bear += 1
    if long_move_48 > 0: bull += 1
    elif long_move_48 < 0: bear += 1
    total=max(bull+bear,1)
    side="شراء" if bull>bear else "بيع" if bear>bull else None
    if not side:
        return None
    confidence=_clamp(50 + abs(bull-bear)/total*45,50,95)
    recommendation="شراء قوي" if side=="شراء" and confidence>=78 else "شراء" if side=="شراء" else "بيع قوي" if confidence>=78 else "بيع"
    return {
        "side":side,"recommendation":recommendation,"ai":round(confidence,2),
        "strategy_mode":"MONTHLY_RAW_PRICE_ACTION","model_version":MODEL_VERSION,
        "reverse":False,"reverse_applied":False,
        "evidence":{"bullish_price_action_points":bull,"bearish_price_action_points":bear,
                    "monthly_bars":len(k),"method":"raw monthly structure and candle path only"},
        "analysis":{"decision":"monthly master from raw price action only",
                    "indicators_used":False,
                    "structure":"higher/lower highs and lows",
                    "breakout":"raw close versus prior monthly range",
                    "trend":"multi-window raw price movement"}
    }

def _timeframe_regime(klines):
    """Unified timeframe regime using EMA20, EMA50 and RSI14."""
    if len(klines) < 60:
        return {"regime":"غير محدد","label":"غير محدد","ema20":None,"ema50":None,"rsi":None}
    closes=[_f(x[4]) for x in klines]
    price=closes[-1]
    ema20=_ema_last(closes,20)
    ema50=_ema_last(closes,50)
    rsi=_rsi_last(closes,14)
    if ema20 is None or ema50 is None or rsi is None:
        return {"regime":"غير محدد","label":"غير محدد","ema20":ema20,"ema50":ema50,"rsi":rsi}
    if price > ema20 and price > ema50 and rsi > 50:
        regime="صاعد"
    elif price < ema20 and price < ema50 and rsi < 50:
        regime="هابط"
    else:
        gap=abs(ema20-ema50)/max(abs(price),1e-12)
        lo=min(ema20,ema50); hi=max(ema20,ema50)
        regime="عرضي" if gap <= 0.01 and lo <= price <= hi else ("صاعد" if price >= hi and rsi >= 50 else "هابط" if price <= lo and rsi <= 50 else "عرضي")
    return {
        "regime":regime,"label":regime,"price":price,
        "ema20":round(ema20,12),"ema50":round(ema50,12),"rsi":round(rsi,2),
        "rules":{
            "bullish":"السعر فوق EMA20 و EMA50 و RSI فوق 50",
            "bearish":"السعر تحت EMA20 و EMA50 و RSI تحت 50",
            "sideways":"السعر يتذبذب بين دعم ومقاومة والمتوسطات متداخلة"
        }
    }

def intelligence_signal(klines, reverse=False, feedback=None, symbol=None, market="unknown", timeframe="unknown"):
    """Primary strategy: EMA20 + EMA50 + RSI14.
    The learning system calibrates confidence from closed outcomes, but never
    changes the three core direction rules.
    """
    if len(klines) < 60:
        return None
    k=klines
    entry=_f(k[-1][4])
    if entry <= 0:
        return None

    regime=_timeframe_regime(k)
    side={"صاعد":"شراء","هابط":"بيع"}.get(regime.get("regime"))
    if not side:
        return None

    # Learn from closed trades: confidence only. Direction stays rule-based.
    profile=_memory_profile(market,symbol,timeframe)
    samples=int(profile.get("samples",0))
    learned_wr=_f(profile.get("win_rate"),0.5)
    learning_bonus=_clamp((learned_wr-0.5)*20,-10,10) if samples>=10 else 0.0
    exact_wr=_f(profile.get("exact_win_rate"),0.5)
    exact_samples=int(profile.get("exact_memory_samples",0))
    if exact_samples>=10:
        learning_bonus += _clamp((exact_wr-0.5)*10,-5,5)

    base_ai=72.0
    # Distance from the RSI midpoint adds modest confidence, without replacing the rule.
    rsi=_f(regime.get("rsi"),50)
    momentum_bonus=_clamp(abs(rsi-50)*0.45,0,9)
    confidence=_clamp(base_ai+momentum_bonus+learning_bonus,50,97)

    guard=_memory_guard(profile)
    if guard.get("abstain"):
        return None

    levels=_build_levels(k,side,entry,[])
    if not levels:
        return None
    sl,tp1,tp2,tp3,tp4=levels

    recommendation=("شراء قوي" if confidence>=80 else "شراء") if side=="شراء" else ("بيع قوي" if confidence>=80 else "بيع")
    return {
        "side":side,
        "original_side":side,
        "recommendation":recommendation,
        "entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"sl":sl,
        "ai":round(confidence,2),
        "rank_score":round(confidence,2),
        "timeframe_rank_key":round(confidence,2),
        "strategy_mode":"EMA20_EMA50_RSI50_LEARNED",
        "model_version":MODEL_VERSION,
        "reverse":False,"reverse_applied":False,
        "regime":regime["regime"],
        "timeframe_regime":regime,
        "leverage":1,
        "analysis":{
            "decision":"EMA20 + EMA50 + RSI14 regime",
            "direction_rule":"صاعد = السعر فوق EMA20 و EMA50 و RSI فوق 50؛ هابط = السعر تحت EMA20 و EMA50 و RSI تحت 50",
            "sideways_rule":"عرضي = المتوسطات متداخلة والسعر يتذبذب داخل نطاقها",
            "learning":"الثقة تتعاير من نتائج الصفقات المغلقة ولا تغيّر قاعدة الاتجاه"
        },
        "evidence":{
            "learning_samples":samples,
            "learning_win_rate":round(learned_wr*100,2) if samples else None,
            "exact_symbol_samples":exact_samples,
            "exact_symbol_win_rate":round(exact_wr*100,2) if exact_samples else None,
            "learning_bonus":round(learning_bonus,2)
        },
        "context":{
            "timeframe_regime":regime,
            "learning_samples":samples,
            "learning_win_rate":learned_wr
        }
    }

def _learning_diagnostics(trade, ctx):
    pnl=_f(trade.get("pnl"))
    return {
        "result": "win" if pnl>0 else "loss",
        "pnl": pnl,
        "side": trade.get("side"),
        "entry": _f(trade.get("entry")),
        "close_price": _f(trade.get("close_price")),
        "close_reason": str(trade.get("close_reason") or trade.get("status") or ""),
        "ai_at_entry": _f(trade.get("ai")),
        "analysis_context": ctx,
        "lesson": "successful_context" if pnl>0 else "failed_context"
    }

def record_ai_outcome(trade):
    try:
        ctx=json.loads(trade.get("ai_context_json") or "{}")
    except Exception:
        ctx={}
    outcome="win" if _f(trade.get("pnl"))>0 else "loss"
    pnl=_f(trade.get("pnl"))
    market=trade.get("market")
    symbol=trade.get("symbol") or ""
    timeframe=trade.get("timeframe")
    side=trade.get("side")
    model=trade.get("ai_model_version") or MODEL_VERSION
    packed=json.dumps(ctx,ensure_ascii=False,separators=(",",":"))
    execute(
        "INSERT INTO ai_memory(market,symbol,timeframe,context_json,side,outcome,pnl,duration_sec,model_version,created_at,closed_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (market,symbol,timeframe,packed,side,outcome,pnl,None,model,trade.get("created_at"),trade.get("closed_at"))
    )
    # Keep a compact hot-memory row on the server for fast decisions.
    state=_brain_state(market,symbol,timeframe) or {}
    samples=int(_f(state.get("samples"),0))+1
    wins=int(_f(state.get("wins"),0))+(1 if outcome=="win" else 0)
    losses=int(_f(state.get("losses"),0))+(1 if outcome=="loss" else 0)
    old_pnl=_f(state.get("pnl"),0)
    avg_win=_f(state.get("avg_win"),0)
    avg_loss=_f(state.get("avg_loss"),0)
    if outcome=="win":
        avg_win=(avg_win*(wins-1)+pnl)/max(wins,1)
    else:
        avg_loss=(avg_loss*(losses-1)+pnl)/max(losses,1)
    learning_ctx=_learning_diagnostics(trade,ctx)
    key="best_context_json" if outcome=="win" else "failed_context_json"
    execute(
        "INSERT INTO ai_brain_state(market,symbol,timeframe,samples,wins,losses,pnl,avg_win,avg_loss,last_outcome,last_pnl,last_ai,%s,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP) "
        "ON CONFLICT(market,symbol,timeframe) DO UPDATE SET "
        "samples=excluded.samples,wins=excluded.wins,losses=excluded.losses,pnl=excluded.pnl,"
        "avg_win=excluded.avg_win,avg_loss=excluded.avg_loss,last_outcome=excluded.last_outcome,"
        "last_pnl=excluded.last_pnl,last_ai=excluded.last_ai,%s=excluded.%s,updated_at=CURRENT_TIMESTAMP"
        % (key,key,key),
        (market,symbol,timeframe,samples,wins,losses,old_pnl+pnl,avg_win,avg_loss,
         outcome,pnl,_f(trade.get("ai")),json.dumps(learning_ctx,ensure_ascii=False,separators=(",",":")))
    )

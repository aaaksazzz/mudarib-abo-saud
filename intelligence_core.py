"""
AI MARKET BRAIN — RAW MARKET / SELF-DISCOVERY ENGINE

No EMA, RSI, MACD, ATR, Stochastic or fixed technical strategy.

The engine learns from the market itself:
- raw candle geometry and price path
- market structure and swing behaviour
- break / rejection / retest behaviour
- liquidity-style wick behaviour
- volume-price relationship
- compression / expansion of raw ranges
- multi-horizon future movement
- historical analogue matching
- persistent outcomes from the platform's own trades

Important: this is an adaptive research/decision engine, not a guaranteed-profit system.
"""
import json, math, statistics, time
from db import rows, execute

MODEL_VERSION = "RAW_BRAIN_ALL_ANALYSIS_V3"

def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d

def _clamp(x,a,b):
    return max(a,min(b,float(x)))

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
        if d>=1.35: continue
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
    # Levels are derived from actual price structure and analogue excursions.
    lows=[_f(x[3]) for x in k[-16:]]
    highs=[_f(x[2]) for x in k[-16:]]
    if side=="شراء":
        structural=min(lows)
        base_risk=max(entry-structural,entry*0.001)
        fav=[abs(x) for x in analog_moves if x>0]
        adv=[abs(x) for x in analog_moves if x<0]
        fav_q=statistics.median(fav) if fav else base_risk/entry*100*1.5
        adv_q=statistics.median(adv) if adv else base_risk/entry*100
        risk=max(base_risk,entry*adv_q/100)
        sl=min(structural,entry-risk)
        tp1=entry+entry*fav_q/100
        tp2=entry+entry*(statistics.median(fav)*1.6 if fav else fav_q*1.6)/100
        tp3=entry+entry*(statistics.median(fav)*2.2 if fav else fav_q*2.2)/100
    else:
        structural=max(highs)
        base_risk=max(structural-entry,entry*0.001)
        fav=[abs(x) for x in analog_moves if x<0]
        adv=[abs(x) for x in analog_moves if x>0]
        fav_q=statistics.median(fav) if fav else base_risk/entry*100*1.5
        adv_q=statistics.median(adv) if adv else base_risk/entry*100
        risk=max(base_risk,entry*adv_q/100)
        sl=max(structural,entry+risk)
        tp1=entry-entry*fav_q/100
        tp2=entry-entry*(statistics.median(fav)*1.6 if fav else fav_q*1.6)/100
        tp3=entry-entry*(statistics.median(fav)*2.2 if fav else fav_q*2.2)/100
    if side=="شراء" and not (sl<entry<tp1<tp2<tp3): return None
    if side=="بيع" and not (sl>entry>tp1>tp2>tp3): return None
    # Reject absurd structural distance; this is a data-quality guard, not a strategy.
    if abs(sl-entry)/entry>0.15:return None
    return sl,tp1,tp2,tp3

def intelligence_signal(klines, reverse=False, feedback=None, symbol=None, market="unknown", timeframe="unknown"):
    if len(klines)<70:return None
    k=klines
    entry=_f(k[-1][4])
    if entry<=0:return None

    ctx=_raw_context(k)
    analogues=_analogue_memory(k)
    if len(analogues)<5:
        return None

    # Self-discovered forward behaviour. No fixed indicator weights.
    votes=[]
    for a in analogues:
        w=1.0/max(a["distance"],0.05)
        for key in ("m3","m6","m12"):
            if a[key] is not None:
                votes.append((a[key],w))
    if not votes:return None
    weighted=sum(v*w for v,w in votes)/sum(w for _,w in votes)
    pos=sum(w for v,w in votes if v>0)
    neg=sum(w for v,w in votes if v<0)
    total=max(pos+neg,1e-9)
    agreement=max(pos,neg)/total
    side="شراء" if weighted>0 else "بيع" if weighted<0 else None
    if not side:return None

    # Historical platform memory can adjust confidence, but never overrides fresh market evidence.
    mem=_memory_vote(_persistent_memory(market,timeframe))
    memory_bonus=0.0
    if mem:
        same=[x for x in mem if x[1]==side and x[2]=="win"]
        opp=[x for x in mem if x[1]==side and x[2]=="loss"]
        if len(same)+len(opp)>=8:
            memory_bonus=_clamp((len(same)-len(opp))/max(len(same)+len(opp),1)*8,-8,8)

    confidence=_clamp(50 + agreement*35 + min(abs(weighted)*4,10) + memory_bonus,50,97)
    # The brain abstains when evidence is weak rather than forcing a trade.
    if agreement<0.58 or confidence<58:return None

    moves=[a["m12"] for a in analogues if a["m12"] is not None]
    levels=_build_levels(k,side,entry,moves)
    if not levels:return None
    sl,tp1,tp2,tp3=levels

    analyses={
        "price_action":"raw candle path and current price behaviour",
        "market_structure":"raw highs/lows and structural location",
        "breakout_rejection":"historical analogue behaviour after similar breaks/rejections",
        "liquidity":"wick and rejection shape comparison",
        "volume":"raw volume embedded in analogue shape",
        "range_behavior":"raw range expansion/compression comparison",
        "momentum":"direction and persistence of raw price path",
        "multi_horizon":"3/6/12-candle future behaviour of analogues",
        "historical_memory":"platform outcomes for similar contexts",
        "decision":"self-discovery from historical raw-price analogues",
    }
    return {
        "side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "ai":round(confidence,2),"strategy_mode":"AI_RAW_SELF_DISCOVERY",
        "model_version":MODEL_VERSION,"reverse":False,"reverse_applied":False,
        "original_side":side,"leverage":1,"regime":"self_discovered",
        "analysis":dict(analyses, **_advanced_context(k)),
        "evidence":{"analogues":len(analogues),"agreement":round(agreement,4),
                    "forward_move":round(weighted,4),"memory_bonus":round(memory_bonus,3)},
        "context":ctx,
    }

def record_ai_outcome(trade):
    try:
        ctx=json.loads(trade.get("ai_context_json") or "{}")
    except Exception:
        ctx={}
    execute(
        "INSERT INTO ai_memory(market,symbol,timeframe,context_json,side,outcome,pnl,duration_sec,model_version,created_at,closed_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (trade.get("market"),trade.get("symbol"),trade.get("timeframe"),
         json.dumps(ctx,ensure_ascii=False,separators=(",",":")),
         trade.get("side"),"win" if _f(trade.get("pnl"))>0 else "loss",
         _f(trade.get("pnl")),None,trade.get("ai_model_version") or MODEL_VERSION,
         trade.get("created_at"),trade.get("closed_at"))
    )

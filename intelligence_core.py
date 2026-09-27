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

MODEL_VERSION = "RAW_BRAIN_SELF_EVOLVING_V6_TIMEFRAME_RANKED_BUY"

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
        return {"samples":0,"win_rate":0.0,"pnl":0.0,"loss_streak":0,"source":"empty"}

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

def intelligence_signal(klines, reverse=False, feedback=None, symbol=None, market="unknown", timeframe="unknown"):
    if len(klines)<70:return None
    k=klines
    entry=_f(k[-1][4])
    if entry<=0:return None

    ctx=_raw_context(k)
    manipulation=_manipulation_context(k)
    ctx["manipulation"]=manipulation
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
    # Direction is discovered independently for each market/timeframe.
    # Spot/Saudi remain buy-only at the application layer; futures/contracts/forex can be long or short.
    side="شراء" if weighted>0 else "بيع" if weighted<0 else None
    if not side:return None

    # Persistent server memory calibrates confidence and can tell the brain to wait.
    mem=_memory_vote(_persistent_memory(market,timeframe))
    profile=_memory_profile(market,symbol,timeframe)
    guard=_memory_guard(profile)
    memory_bonus=guard["bonus"]
    if mem:
        same=[x for x in mem if x[1]==side and x[2]=="win"]
        opp=[x for x in mem if x[1]==side and x[2]=="loss"]
        if len(same)+len(opp)>=8:
            memory_bonus += _clamp((len(same)-len(opp))/max(len(same)+len(opp),1)*5,-5,5)

    manipulation_penalty=-7 if manipulation["risk"]=="high" else -3 if manipulation["risk"]=="elevated" else 0
    confidence=_clamp(50 + agreement*35 + min(abs(weighted)*4,10) + memory_bonus + manipulation_penalty,50,97)
    # The brain abstains when evidence is weak or recent server memory says to wait.
    if manipulation["action"]=="wait_for_confirmation": return None
    if agreement<0.58 or confidence<58 or guard["abstain"]:return None

    moves=[a["m12"] for a in analogues if a["m12"] is not None]
    levels=_build_levels(k,side,entry,moves)
    if not levels:return None
    rank_score=_clamp(
        confidence*0.55 +
        agreement*100*0.30 +
        min(abs(weighted)*8,15)*0.15,
        0,100
    )
    if side=="شراء":
        recommendation="شراء قوي" if confidence>=78 and agreement>=0.68 else "شراء"
    else:
        recommendation="بيع قوي" if confidence>=78 and agreement>=0.68 else "بيع"
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
        "historical_memory":"preserved wins and losses from the platform's own AI memory",
        "manipulation_detection":"liquidity sweeps, failed breaks, abnormal volume and rejection traps from OHLCV",
        "decision":"self-discovery from historical raw-price analogues",
        "direction":"buy/sell determined from the strongest current timeframe evidence",
        "timeframe_ranking":"recalculate and reorder opportunities within this exact timeframe",
    }
    return {
        "side":side,"recommendation":recommendation,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "ai":round(confidence,2),"rank_score":round(rank_score,2),
        "timeframe_rank_key":round(rank_score,2),"strategy_mode":"AI_RAW_SELF_DISCOVERY",
        "model_version":MODEL_VERSION,"reverse":False,"reverse_applied":False,
        "original_side":side,"leverage":1,"regime":"self_discovered",
        "analysis":dict(analyses, **_advanced_context(k)),
        "evidence":{"analogues":len(analogues),"agreement":round(agreement,4),
                    "forward_move":round(weighted,4),"memory_bonus":round(memory_bonus,3),
                    "memory_samples":profile["samples"],"exact_symbol_samples":profile["exact_samples"],
                    "exact_memory_samples":profile.get("exact_memory_samples",0),
                    "memory_win_rate":round(profile["win_rate"]*100,2),
                    "memory_guard":guard["reason"],"manipulation_risk":manipulation["risk"],"manipulation_score":manipulation["score"]},
        "context":dict(ctx, memory_profile=profile),
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

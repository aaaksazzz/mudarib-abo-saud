"""
TRADING PRO AI — PRICE ACTION ENGINE
No EMA, RSI, MACD, Stochastic, ATR or other technical indicators.

The engine reasons from raw OHLCV only:
- market structure / swing highs and lows
- breakout and retest
- liquidity sweeps
- candle body/wick behaviour
- range expansion
- raw traded volume
- risk/reward and nearby structure

AI% is a confidence score, not a guaranteed win probability.
"""

def _f(x, default=0.0):
    try: return float(x)
    except Exception: return default

def _swing_bias(k, n=6):
    if len(k) < n * 3: return 0, 0
    a,b,c = k[-n*3:-n*2], k[-n*2:-n], k[-n:]
    ah,al=max(_f(x[2]) for x in a),min(_f(x[3]) for x in a)
    bh,bl=max(_f(x[2]) for x in b),min(_f(x[3]) for x in b)
    ch,cl=max(_f(x[2]) for x in c),min(_f(x[3]) for x in c)
    bull=int(bh>ah and bl>=al)+int(ch>bh and cl>=bl)
    bear=int(bl<al and bh<=ah)+int(cl<bl and ch<=bh)
    return bull,bear

def _candle_quality(k):
    o,h,l,c=map(_f,(k[-1][1],k[-1][2],k[-1][3],k[-1][4]))
    size=max(h-l,1e-12)
    body=abs(c-o)/size
    upper=(h-max(o,c))/size
    lower=(min(o,c)-l)/size
    close_pos=(c-l)/size
    return (
        c>o and body>=.50 and close_pos>=.70,
        c<o and body>=.50 and close_pos<=.30,
        body,upper,lower,close_pos
    )

def _raw_volume_score(k):
    if len(k)<21:return 0
    recent=sum(_f(x[5]) for x in k[-5:])/5
    base=sum(_f(x[5]) for x in k[-21:-5])/16
    if base<=0:return 0
    ratio=recent/base
    if ratio>=2.0:return 15
    if ratio>=1.5:return 12
    if ratio>=1.2:return 9
    if ratio>=1.0:return 6
    return 2

def _levels(k):
    p20=k[-21:-1]; p10=k[-11:-1]
    return (
        max(_f(x[2]) for x in p20), min(_f(x[3]) for x in p20),
        max(_f(x[2]) for x in p10), min(_f(x[3]) for x in p10)
    )

def _risk_from_structure(k,side,entry):
    recent=k[-10:-1]
    if side=="شراء":
        structural=min(_f(x[3]) for x in recent)
        risk=entry-structural
        if risk<=0:
            risk=max(entry*.006,(max(_f(x[2]) for x in recent)-structural)*.35)
        sl=entry-risk*1.05
    else:
        structural=max(_f(x[2]) for x in recent)
        risk=structural-entry
        if risk<=0:
            risk=max(entry*.006,(structural-min(_f(x[3]) for x in recent))*.35)
        sl=entry+risk*1.05
    if risk<=entry*.002 or risk>=entry*.08:return None
    return risk,sl

def intelligence_signal(klines, reverse=False, feedback=None, symbol=None):
    """AI-only price-action reasoning. No technical indicator calculations."""
    if len(klines)<80:return None
    k=klines; entry=_f(k[-1][4])
    if entry<=0:return None

    hi20,lo20,hi10,lo10=_levels(k)
    bull_swings,bear_swings=_swing_bias(k)
    bull_candle,bear_candle,body,upper,lower,close_pos=_candle_quality(k)
    vol_score=_raw_volume_score(k)

    last_high,last_low=_f(k[-1][2]),_f(k[-1][3])
    broke_up=last_high>hi20 and entry>hi20
    broke_down=last_low<lo20 and entry<lo20
    sweep_up=last_high>hi20 and entry<hi20 and upper>=.30
    sweep_down=last_low<lo20 and entry>lo20 and lower>=.30
    retest_up=last_low<=hi20*1.004 and entry>hi20
    retest_down=last_high>=lo20*.996 and entry<lo20

    recent_range=max(_f(x[2]) for x in k[-5:])-min(_f(x[3]) for x in k[-5:])
    old_range=max(_f(x[2]) for x in k[-25:-5])-min(_f(x[3]) for x in k[-25:-5])
    expansion=old_range>0 and recent_range>old_range*1.15

    long_score=short_score=0
    if bull_swings>=2: long_score+=30
    elif bull_swings==1: long_score+=18
    if bear_swings>=2: short_score+=30
    elif bear_swings==1: short_score+=18

    if broke_up: long_score+=25
    if retest_up: long_score+=10
    if broke_down: short_score+=25
    if retest_down: short_score+=10

    if bull_candle: long_score+=20
    elif body>=.40 and close_pos>=.60: long_score+=10
    if bear_candle: short_score+=20
    elif body>=.40 and close_pos<=.40: short_score+=10

    long_score+=vol_score; short_score+=vol_score

    if expansion:
        if entry>(hi10+lo10)/2: long_score+=10
        else: short_score+=10

    if sweep_down and bull_candle: long_score+=15
    if sweep_up and bear_candle: short_score+=15

    if long_score==short_score:return None
    side="شراء" if long_score>short_score else "بيع"
    score=min(99.0,float(max(long_score,short_score)))
    if score<82:return None

    risk_data=_risk_from_structure(k,side,entry)
    if not risk_data:return None
    risk,sl=risk_data

    if side=="شراء":
        tp1,tp2,tp3=entry+risk*1.20,entry+risk*2.00,entry+risk*3.00
    else:
        tp1,tp2,tp3=entry-risk*1.20,entry-risk*2.00,entry-risk*3.00

    return {
        "side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "ai":score,"strategy_mode":"AI_PRICE_ACTION_V1","original_side":side,
        "reverse":False,"reverse_applied":False,"strategy_min_score":82,
        "leverage":1,"regime":"price_action",
        "confluence":{
            "market_structure":30 if (bull_swings if side=="شراء" else bear_swings)>=2 else 18,
            "breakout_retest":35 if ((broke_up or retest_up) if side=="شراء" else (broke_down or retest_down)) else 0,
            "candle":20 if (bull_candle if side=="شراء" else bear_candle) else 10,
            "raw_volume":vol_score,
            "liquidity_sweep":15 if (sweep_down if side=="شراء" else sweep_up) else 0,
            "expansion":10 if expansion else 0
        }
    }

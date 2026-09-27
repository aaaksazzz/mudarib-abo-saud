REVERSE_STRATEGY = True

def leverage_for_symbol(symbol):
    s=str(symbol or "").upper().replace("/","").replace("-","")
    if s in {"BTCUSDT","ETHUSDT"}: return 10
    if s in {"BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","LTCUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","TRXUSDT"}: return 7
    if s in {"DOGEUSDT","SHIBUSDT","PEPEUSDT","WIFUSDT","BONKUSDT","FLOKIUSDT","1000PEPEUSDT","1000SHIBUSDT"}: return 3
    return 5

def _ema(values, n):
    if len(values) < n: return sum(values)/len(values) if values else 0.0
    a=2/(n+1); e=sum(values[:n])/n
    for v in values[n:]: e=(v*a)+(e*(1-a))
    return e

def _rsi(values,n=14):
    if len(values)<n+1:return 50.0
    gains=losses=0.0
    for i in range(len(values)-n,len(values)):
        d=values[i]-values[i-1]
        gains+=max(d,0); losses+=max(-d,0)
    if losses==0:return 100.0
    return 100-(100/(1+gains/losses))

def _atr(k,n=14):
    if len(k)<n+1:return 0.0
    tr=[]
    for i in range(len(k)-n,len(k)):
        h=float(k[i][2]); l=float(k[i][3]); pc=float(k[i-1][4])
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr)/len(tr)

def _adx_like(k,n=14):
    if len(k)<n+2:return 0.0
    plus=minus=tr=0.0
    for i in range(len(k)-n,len(k)):
        h=float(k[i][2]);l=float(k[i][3]);ph=float(k[i-1][2]);pl=float(k[i-1][3]);pc=float(k[i-1][4])
        up=h-ph; dn=pl-l
        plus+=up if up>dn and up>0 else 0
        minus+=dn if dn>up and dn>0 else 0
        tr+=max(h-l,abs(h-pc),abs(l-pc))
    if tr<=0:return 0.0
    pdi=100*plus/tr; mdi=100*minus/tr
    return 100*abs(pdi-mdi)/max(pdi+mdi,1e-9)

def _structure(k,n=20):
    if len(k)<n+1:return 0
    highs=[float(x[2]) for x in k[-n-1:-1]]
    lows=[float(x[3]) for x in k[-n-1:-1]]
    h=float(k[-1][2]);l=float(k[-1][3])
    if h>max(highs) and l>=min(lows):return 1
    if l<min(lows) and h<=max(highs):return -1
    return 0

def strategy_profile(feedback=None):
    f=feedback or {}
    closed=int(f.get("closed") or 0); wr=float(f.get("win_rate") or 0)
    p={"min_score":78.0,"volume_ratio":1.35,"mode":"confluence"}
    if closed>=20 and wr<45:p.update(min_score=84,volume_ratio=1.60,mode="defensive")
    elif closed>=20 and wr<52:p.update(min_score=81,volume_ratio=1.50,mode="selective")
    elif closed>=20 and wr>=60:p.update(min_score=76,volume_ratio=1.25,mode="high_selectivity")
    return p

def signal_from_klines(klines, reverse=REVERSE_STRATEGY, feedback=None):
    """
    Multi-factor, regime-aware signal engine.
    It is a quality score, not a guaranteed win probability.
    Uses only candles available at the decision point.
    """
    if len(klines)<80:return None
    closes=[float(x[4]) for x in klines]
    highs=[float(x[2]) for x in klines]
    lows=[float(x[3]) for x in klines]
    vols=[float(x[5] or 0) for x in klines]
    price=closes[-1]; prev=closes[-2]
    e20=_ema(closes,20); e50=_ema(closes,50); e200=_ema(closes,200) if len(closes)>=200 else _ema(closes,len(closes))
    rsi=_rsi(closes,14); atr=_atr(klines,14); adx=_adx_like(klines,14)
    avgvol=sum(vols[-21:-1])/20 if len(vols)>20 else 0
    vr=vols[-1]/avgvol if avgvol else 1.0
    change=(price/prev-1)*100 if prev else 0
    structure=_structure(klines,20)
    atr_pct=(atr/price*100) if price else 0

    bull=price>e20>e50 and price>e200
    bear=price<e20<e50 and price<e200
    original="شراء" if bull else "بيع" if bear else None
    if not original:return None

    trend_strength=min(18,adx*0.28)
    trend_align=16 if ((bull and e20>e50 and e50>=e200) or (bear and e20<e50 and e50<=e200)) else 0
    momentum=10 if ((bull and 52<=rsi<=72) or (bear and 28<=rsi<=48)) else 0
    volume=min(16,max(0,(vr-0.9)*12))
    breakout=8 if ((bull and structure==1) or (bear and structure==-1)) else 0
    candle=6 if ((bull and change>0) or (bear and change<0)) else 0
    volatility=8 if 0.15<=atr_pct<=4.5 else 0

    score=round(min(98,30+trend_strength+trend_align+momentum+volume+breakout+candle+volatility),1)

    p=strategy_profile(feedback)
    if vr < p["volume_ratio"]: return None
    if adx < 14: return None
    if atr<=0:return None
    if score<p["min_score"]:return None

    side=("بيع" if original=="شراء" else "شراء") if reverse else original

    # Volatility-based risk. TP3 is 3R; TP1/TP2 are milestones at 1R/2R.
    risk=max(atr*1.35,price*0.006)
    if side=="شراء":
        sl=price-risk; tp1=price+risk; tp2=price+risk*2; tp3=price+risk*3
    else:
        sl=price+risk; tp1=price-risk; tp2=price-risk*2; tp3=price-risk*3

    return {
        "side":side,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "ai":score,"strategy_mode":p["mode"],"strategy_min_score":p["min_score"],
        "leverage":leverage_for_symbol(None),"regime":"trend",
        "confluence":{"trend":round(trend_align,1),"momentum":round(momentum,1),
                      "volume":round(volume,1),"structure":breakout,"volatility":volatility,
                      "adx":round(trend_strength,1)}
    }

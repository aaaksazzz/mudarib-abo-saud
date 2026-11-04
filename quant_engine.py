"""DIVE QUANT PRO — open-data consensus engine.
Methodology adapted from the MIT-licensed Dive Into Crypto project:
weighted indicator voting, regime adaptation, futures microstructure,
top-trader divergence, explicit data availability and 3R trade levels.
This lightweight Flask integration ports the decision framework, not the
upstream Android/desktop 60-indicator codebase. No API keys are required.
"""
import math
import requests
from statistics import pstdev

FAPI = "https://fapi.binance.com"
HEADERS = {"User-Agent": "SMART-TRADING-PRO/2.0", "Accept": "application/json"}
WEIGHTS = {"ema":1.8,"sma":1.5,"macd":2.0,"rsi":1.5,"stoch":1.2,"cci":1.0,
"williams":1.0,"roc":1.0,"bollinger":1.5,"mfi":1.2,"obv":1.2,"adx_di":1.5,
"ichimoku":2.0,"supertrend":2.0,"cmf":1.5,"vwap":1.8,"vortex":1.5,
"donchian":1.5,"keltner":1.5,"zscore":1.0,"engulfing":1.2}

def _num(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError):
        return None

def _sma(a,n):
    return sum(a[-n:])/n if len(a)>=n else None

def _ema(a,n):
    if len(a)<n: return None
    k=2/(n+1); value=sum(a[:n])/n
    for x in a[n:]: value=x*k+value*(1-k)
    return value

def _rsi(a,n=14):
    if len(a)<n+1: return None
    d=[a[i]-a[i-1] for i in range(len(a)-n,len(a))]
    up=sum(max(0,x) for x in d)/n; dn=sum(max(0,-x) for x in d)/n
    return 100.0 if dn==0 else 100-100/(1+up/dn)

def _atr(h,l,c,n=14):
    if len(c)<n+1: return None
    tr=[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    return sum(tr[-n:])/n

def _micro(symbol,closes):
    out={"available":False,"score":0,"notes":[]}
    try:
        def get(path,params=None):
            r=requests.get(FAPI+path,params=params,headers=HEADERS,timeout=(2.5,4.5))
            r.raise_for_status()
            return r.json()
        p={"symbol":symbol,"period":"15m","limit":5}
        oi=get("/futures/data/openInterestHist",p)
        top=get("/futures/data/topLongShortPositionRatio",p)
        glob=get("/futures/data/globalLongShortAccountRatio",p)
        taker=get("/futures/data/takerlongshortRatio",p)
        premium=get("/fapi/v1/premiumIndex",{"symbol":symbol})
        score=0
        price_change=closes[-1]/closes[-5]-1 if len(closes)>=5 and closes[-5] else 0
        if len(oi)>=2:
            a=_num(oi[-2].get("sumOpenInterestValue")); b=_num(oi[-1].get("sumOpenInterestValue"))
            if a and b and b/a-1>0.003:
                if price_change>0.001: score+=12; out["notes"].append("العقود المفتوحة والسعر يرتفعان")
                elif price_change< -0.001: score-=12; out["notes"].append("العقود المفتوحة ترتفع مع هبوط السعر")
        if taker:
            ratio=_num(taker[-1].get("buySellRatio"))
            if ratio is not None and ratio>=1.08: score+=18; out["notes"].append("ضغط شراء عدواني")
            elif ratio is not None and ratio<=0.92: score-=18; out["notes"].append("ضغط بيع عدواني")
        if len(top)>=2:
            old=_num(top[-2].get("longShortRatio")); new=_num(top[-1].get("longShortRatio"))
            if old is not None and new is not None:
                if price_change>0.002 and new-old< -0.015: score+=15; out["notes"].append("اختلاف تمركز كبار المتداولين مع صعود السعر")
                elif price_change< -0.002 and new-old>0.015: score-=15; out["notes"].append("اختلاف تمركز كبار المتداولين مع هبوط السعر")
                elif new>1.35: score-=8; out["notes"].append("ازدحام مراكز الشراء لدى كبار المتداولين")
                elif new<0.74: score+=8; out["notes"].append("ازدحام مراكز البيع لدى كبار المتداولين")
        if glob:
            crowd=_num(glob[-1].get("longShortRatio"))
            if crowd is not None and crowd>1.8: score-=5; out["notes"].append("ازدحام شراء عام")
            elif crowd is not None and crowd<0.55: score+=5; out["notes"].append("ازدحام بيع عام")
        funding=_num(premium.get("lastFundingRate")) if isinstance(premium,dict) else None
        if funding is not None and funding>0.0005: score-=8; out["notes"].append("تمويل موجب مرتفع")
        elif funding is not None and funding< -0.0005: score+=8; out["notes"].append("تمويل سالب")
        out.update({"available":True,"score":max(-50,min(50,score)),"funding":funding,
                    "open_interest_points":len(oi),"top_trader_points":len(top),"taker_points":len(taker)})
    except Exception as exc:
        out["unavailable_reason"]=str(exc)[:140]
    return out

def analyze(market,symbol,rows,include_micro=False):
    """Analyze closed 15m OHLCV rows [timestamp,open,high,low,close,volume]."""
    if not isinstance(rows,list) or len(rows)<75: return None
    bars=rows[:-1]  # never use the still-forming candle
    try:
        o=[_num(x[1]) for x in bars]; h=[_num(x[2]) for x in bars]
        l=[_num(x[3]) for x in bars]; c=[_num(x[4]) for x in bars]
        v=[_num(x[5]) or 0 for x in bars]
        if any(x is None for q in (o,h,l,c) for x in q) or min(c[-60:])<=0: return None
        close,high,low,op=c[-1],h[-1],l[-1],o[-1]
        atr=_atr(h,l,c)
        if not atr or atr<=0: return None
        votes=[]
        def add(name,score):
            if score: votes.append((name,int(max(-2,min(2,score)))))
        e9,e21=_ema(c,9),_ema(c,21); s20,s50=_sma(c,20),_sma(c,50)
        if e9 is not None and e21 is not None: add("ema",2 if e9>e21*1.001 else -2 if e9<e21*0.999 else 0)
        if s20 is not None and s50 is not None: add("sma",2 if s20>s50*1.001 else -2 if s20<s50*0.999 else 0)
        macd=(_ema(c,12) or close)-(_ema(c,26) or close)
        macd_hist=macd-((_ema([(_ema(c[:i+1],12) or c[i])-(_ema(c[:i+1],26) or c[i]) for i in range(len(c))],9)) or 0)
        add("macd",2 if macd>0 and macd_hist>0 else -2 if macd<0 and macd_hist<0 else 0)
        rsi=_rsi(c)
        if rsi is not None: add("rsi",2 if rsi<30 and close>op else 1 if 52<rsi<70 else -2 if rsi>75 and close<op else -1 if rsi<48 else 0)
        lo14,hi14=min(l[-14:]),max(h[-14:])
        stoch=100*(close-lo14)/(hi14-lo14) if hi14>lo14 else 50
        add("stoch",2 if stoch<15 and close>op else -2 if stoch>85 and close<op else 1 if 55<stoch<85 else -1 if 15<stoch<45 else 0)
        typical=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
        tp20=_sma(typical,20); mad=sum(abs(x-tp20) for x in typical[-20:])/20 if tp20 else 0
        cci=(typical[-1]-tp20)/(0.015*mad) if mad else 0
        add("cci",2 if cci>100 else 1 if cci>25 else -2 if cci< -100 else -1 if cci< -25 else 0)
        wr=-100*(hi14-close)/(hi14-lo14) if hi14>lo14 else -50
        add("williams",2 if wr< -85 and close>op else -2 if wr> -15 and close<op else 1 if -50<wr< -15 else -1 if -85<wr< -50 else 0)
        roc=(close/c[-13]-1)*100 if c[-13] else 0
        add("roc",2 if roc>1 else 1 if roc>0.15 else -2 if roc< -1 else -1 if roc< -0.15 else 0)
        mid=_sma(c,20); sd=pstdev(c[-20:]); upper,lower=mid+2*sd,mid-2*sd
        add("bollinger",2 if close>upper else -2 if close<lower else 1 if close>mid else -1 if close<mid else 0)
        pos_flow=neg_flow=0.0
        for i in range(-14,0):
            flow=typical[i]*v[i]
            if typical[i]>typical[i-1]: pos_flow+=flow
            elif typical[i]<typical[i-1]: neg_flow+=flow
        mfi=100-100/(1+pos_flow/neg_flow) if neg_flow else 100
        add("mfi",2 if mfi<20 and close>op else -2 if mfi>80 and close<op else 1 if 55<mfi<80 else -1 if 20<mfi<45 else 0)
        obv=[0.0]
        for i in range(1,len(c)): obv.append(obv[-1]+(v[i] if c[i]>c[i-1] else -v[i] if c[i]<c[i-1] else 0))
        of,os=_sma(obv,5),_sma(obv,20)
        if of is not None and os is not None: add("obv",1 if of>os else -1 if of<os else 0)
        pdm=[]; mdm=[]; tr=[]
        for i in range(1,len(c)):
            up,dn=h[i]-h[i-1],l[i-1]-l[i]
            pdm.append(max(up,0) if up>dn else 0); mdm.append(max(dn,0) if dn>up else 0)
            tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        tr14=sum(tr[-14:]) or 1; pdi=100*sum(pdm[-14:])/tr14; mdi=100*sum(mdm[-14:])/tr14
        adx=100*abs(pdi-mdi)/(pdi+mdi) if pdi+mdi else 0
        add("adx_di",2 if pdi>mdi and adx>25 else 1 if pdi>mdi else -2 if mdi>pdi and adx>25 else -1 if mdi>pdi else 0)
        tenkan=(max(h[-9:])+min(l[-9:]))/2; kijun=(max(h[-26:])+min(l[-26:]))/2
        spanb=(max(h[-52:])+min(l[-52:]))/2
        add("ichimoku",2 if close>max(kijun,spanb) and tenkan>kijun else -2 if close<min(kijun,spanb) and tenkan<kijun else 1 if close>kijun else -1 if close<kijun else 0)
        add("supertrend",1 if close>(h[-10:][0]+l[-10:][0])/2+2*atr else -1 if close<(h[-10:][0]+l[-10:][0])/2-2*atr else 0)
        mfv=[(((c[i]-l[i])-(h[i]-c[i]))/(h[i]-l[i])*v[i]) if h[i]>l[i] else 0 for i in range(len(c))]
        cmf=sum(mfv[-20:])/(sum(v[-20:]) or 1)
        add("cmf",1 if cmf>0.08 else -1 if cmf< -0.08 else 0)
        vwap=sum(typical[-20+i]*v[-20+i] for i in range(20))/(sum(v[-20:]) or 1)
        add("vwap",1 if close>vwap else -1 if close<vwap else 0)
        vp=sum(abs(h[i]-l[i-1]) for i in range(len(h)-14,len(h)))
        vm=sum(abs(l[i]-h[i-1]) for i in range(len(h)-14,len(h)))
        vip=vp/tr14; vim=vm/tr14
        add("vortex",1 if vip>vim*1.03 else -1 if vim>vip*1.03 else 0)
        dhi,dlo=max(h[-21:-1]),min(l[-21:-1])
        add("donchian",2 if close>dhi else -2 if close<dlo else 1 if close>(dhi+dlo)/2 else -1 if close<(dhi+dlo)/2 else 0)
        km=_ema(c,20) or close
        add("keltner",1 if close>km+1.5*atr else -1 if close<km-1.5*atr else 0)
        z=(close-mid)/sd if sd else 0
        add("zscore",2 if z< -2 and close>op else -2 if z>2 and close<op else 1 if 0.4<z<2 else -1 if -2<z< -0.4 else 0)
        bull=close>op and c[-2]<o[-2] and close>o[-2] and op<c[-2]
        bear=close<op and c[-2]>o[-2] and close<o[-2] and op>c[-2]
        add("engulfing",2 if bull else -2 if bear else 0)
        active=[x for x in votes if x[1]]
        if len(active)<6: return None
        regime="TREND" if adx>=25 else "RANGE" if adx<20 else "MIXED"
        trend={"ema","sma","macd","adx_di","ichimoku","supertrend","vortex","donchian","keltner"}
        oscill={"rsi","stoch","cci","williams","bollinger","mfi","zscore"}
        weighted=total=0.0; buys=sum(1 for _,s in active if s>0); sells=sum(1 for _,s in active if s<0)
        for name,score in votes:
            w=WEIGHTS[name]
            if regime=="TREND" and name in trend: w*=1.35
            elif regime=="TREND" and name in oscill: w*=0.70
            elif regime=="RANGE" and name in oscill: w*=1.30
            elif regime=="RANGE" and name in trend: w*=0.75
            weighted+=score*w; total+=w
        base_score=weighted/(total or 1)
        micro=_micro(symbol,c) if market=="futures" and include_micro else {"available":False,"score":0,"notes":[]}
        final_score=base_score+(micro["score"]/100*0.45 if micro["available"] else 0)
        side="BUY" if final_score>=0.4 else "SELL" if final_score<=-0.4 else None
        if not side: return None
        agreement=max(buys,sells)/len(active)
        if agreement<0.58: return None
        if market in ("spot","alpha","us-stocks","saudi") and side=="SELL": return None
        confidence=min(abs(final_score)/2,1)*70+agreement*20+(len(active)/len(votes))*10
        flags=[]; atr_pct=atr/close*100
        if atr_pct>3: flags.append("تقلب مرتفع")
        if adx<15: flags.append("اتجاه ضعيف")
        if agreement<0.68: flags.append("تعارض جزئي")
        if micro["available"] and abs(micro["score"])>=30 and ((side=="BUY" and micro["score"]<0) or (side=="SELL" and micro["score"]>0)): flags.append("تعارض تمركز العقود")
        if len(flags)>=3: return None
        confidence=max(0,min(98,round(confidence-len(flags)*4,1)))
        if confidence<55: return None
        swinglo=min(l[-10:]); swinghi=max(h[-10:])
        if side=="BUY":
            stop=min(swinglo-0.15*atr,close-0.9*atr); risk=close-stop
            if risk>2.5*atr: stop=close-1.8*atr; risk=close-stop
            if risk<=0: return None
            tps=[close+risk,close+2*risk,close+3*risk]
        else:
            stop=max(swinghi+0.15*atr,close+0.9*atr); risk=stop-close
            if risk>2.5*atr: stop=close+1.8*atr; risk=stop-close
            if risk<=0: return None
            tps=[close-risk,close-2*risk,close-3*risk]
        change=(close/c[-2]-1)*100 if c[-2] else 0
        why="؛ ".join(micro.get("notes",[])[:3]) if micro.get("notes") else "توافق الاتجاه والزخم والحجم"
        return {"side":side,"entry":close,"stop":stop,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],
                "score":confidence,"timeframe":"15m","change_pct":round(change,5),"change_15m_pct":round(change,5),
                "reason":f"DIVE QUANT PRO: {final_score:.3f}; {regime}; {why}",
                "signal_candle_time":int(float(bars[-1][0])),"risk_atr":round(risk/atr,2),
                "reward_risk":3.0,"microstructure":micro,"indicator_count":len(votes),"active_count":len(active)}
    except (IndexError,TypeError,ValueError,ZeroDivisionError,OverflowError):
        return None

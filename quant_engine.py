"""DIVE QUANT PRO — upstream 60-indicator consensus engine with public market overlays.

The indicator, scoring, risk and regime modules are vendored from the MIT-licensed
Dive Into Crypto project. This adapter restricts all markets to closed 15m candles,
adds Binance futures microstructure where available, and builds one-stop 1R/2R/3R
trade plans. No exchange account credentials are used.
"""
import math
import requests
import pandas as pd
from functools import lru_cache
from dive_engine.engine.loader import load_config
from dive_engine.engine.signal_service import SignalService
from dive_engine.engine.consensus.engine import ConsensusEngine
from dive_engine.engine.consensus.regime import evaluate as evaluate_regime

@lru_cache(maxsize=1)
def _engine():
    config=load_config()
    return config, SignalService(config), ConsensusEngine(config)

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
    """Evaluate the upstream 60-vote engine on closed 15m candles and construct 3R levels."""
    if not isinstance(rows,list) or len(rows)<75:
        return None
    bars=rows[:-1]
    try:
        o=[float(x[1]) for x in bars]
        h=[float(x[2]) for x in bars]
        l=[float(x[3]) for x in bars]
        c=[float(x[4]) for x in bars]
        v=[float(x[5] or 0) for x in bars]
        if not all(math.isfinite(z) for seq in (o,h,l,c,v) for z in seq) or min(c[-60:])<=0:
            return None
        atr=_atr(h,l,c,14)
        if not atr or atr<=0:
            return None
        config,service,consensus_engine=_engine()
        frame=pd.DataFrame({"open":o,"high":h,"low":l,"close":c,"volume":v})
        results=service.calculate_all(frame)
        decision=consensus_engine.evaluate(results)
        signal=decision.get("final_signal","NEUTRAL")
        side="BUY" if signal in ("BUY","STRONG_BUY") else "SELL" if signal in ("SELL","STRONG_SELL") else None
        score_data=decision.get("score_data") or {}
        risk_data=decision.get("risk_data") or {}
        if not side or not decision.get("should_trade") or decision.get("risk_level")=="HIGH":
            return None
        if int(decision.get("confidence",0))<55:
            return None
        active=int(score_data.get("active_signals",0))
        total=int(score_data.get("total_signals",0))
        buy=int(score_data.get("buy_count",0)); sell=int(score_data.get("sell_count",0))
        agreement=max(buy,sell)/active if active else 0
        if active<6 or agreement<0.58:
            return None
        if market in ("spot","alpha","us-stocks","saudi") and side=="SELL":
            return None
        regime=evaluate_regime(results,config.get("indicator_weights",{}),config)
        micro=_micro(symbol,c) if market=="futures" and include_micro else {"available":False,"score":0,"notes":[]}
        if micro.get("available") and abs(micro.get("score",0))>=30:
            if (side=="BUY" and micro["score"]<0) or (side=="SELL" and micro["score"]>0):
                return None
        confidence=float(decision["confidence"])
        if micro.get("available") and ((side=="BUY" and micro["score"]>0) or (side=="SELL" and micro["score"]<0)):
            confidence=min(98,confidence+4)
        entry=c[-1]
        if side=="BUY":
            stop=min(min(l[-10:])-0.15*atr,entry-0.9*atr)
            risk=entry-stop
            if risk>2.5*atr:
                stop=entry-1.8*atr
                risk=entry-stop
            if risk<=0: return None
            tp1,tp2,tp3=entry+risk,entry+2*risk,entry+3*risk
        else:
            stop=max(max(h[-10:])+0.15*atr,entry+0.9*atr)
            risk=stop-entry
            if risk>2.5*atr:
                stop=entry+1.8*atr
                risk=stop-entry
            if risk<=0: return None
            tp1,tp2,tp3=entry-risk,entry-2*risk,entry-3*risk
        change=(entry/c[-2]-1)*100 if c[-2] else 0
        notes="؛ ".join(micro.get("notes",[])[:3]) if micro.get("notes") else "توافق محرك المؤشرات الـ60"
        return {
            "side":side,"entry":entry,"stop":stop,"tp1":tp1,"tp2":tp2,"tp3":tp3,
            "score":round(confidence,1),"timeframe":"15m","change_pct":round(change,5),
            "change_15m_pct":round(change,5),
            "reason":f"DIVE QUANT PRO: {signal}; weighted={decision.get('weighted_score',0):.3f}; regime={regime.get('regime','MIXED')}; {notes}",
            "signal_candle_time":int(float(bars[-1][0])),"risk_atr":round(risk/atr,2),
            "reward_risk":3.0,"microstructure":micro,"indicator_count":total,
            "active_count":active,"risk_level":decision.get("risk_level"),
            "regime":regime.get("regime","MIXED")
        }
    except (IndexError,TypeError,ValueError,ZeroDivisionError,OverflowError):
        return None

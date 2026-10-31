"""Rule-based multi-timeframe strategy requested for HAWK QUANT PRO."""
from statistics import mean

TIMEFRAME_RULES = {
    "15m": ("4h", "1d"),
    "1h": ("4h", "1d"),
    "4h": ("1w", "1M"),
    "1d": ("1w", "1M"),
    "1w": ("1w", "1M"),
}
def _state(rows):
    if not isinstance(rows, (list, tuple)) or len(rows) < 12:
        return "INSUFFICIENT"
    try:
        bars=rows[-12:]
        closes=[float(x["close"]) for x in bars]
        highs=[float(x["high"]) for x in bars]
        lows=[float(x["low"]) for x in bars]
        if any(x<=0 for x in closes) or any(h<l for h,l in zip(highs,lows)):
            return "INVALID"
        momentum=closes[-1]/closes[-5]-1
        rh,ph=mean(highs[-4:]),mean(highs[-8:-4])
        rl,pl=mean(lows[-4:]),mean(lows[-8:-4])
        up=rh>ph and rl>pl
        down=rh<ph and rl<pl
        if momentum>0.001 and up: return "BUY"
        if momentum<-0.001 and down: return "SELL"
        return "NEUTRAL"
    except (KeyError,TypeError,ValueError,ZeroDivisionError):
        return "INVALID"

def assess_strategy(histories, entry_timeframe, side=None):
    refs=TIMEFRAME_RULES.get(entry_timeframe)
    if not refs: return {"confirmed":False,"reason":"unsupported_timeframe","states":{}}
    states={tf:_state(histories.get(tf,[])) for tf in refs}
    wanted=side or ("BUY" if all(v=="BUY" for v in states.values()) else
                    "SELL" if all(v=="SELL" for v in states.values()) else None)
    confirmed=bool(wanted and all(v==wanted for v in states.values()))
    return {"confirmed":confirmed,"side":wanted,"states":states,
            "reference_timeframes":list(refs),
            "reason":"confirmed" if confirmed else "reference_timeframes_not_aligned"}

def make_trade(rows, side):
    if not isinstance(rows,(list,tuple)) or len(rows)<20: return None
    try:
        bars=rows[-20:]
        entry=float(bars[-1]["close"])
        ranges=[]
        for i,b in enumerate(bars[-14:]):
            prev=float(bars[-15+i]["close"]) if i else float(bars[-15]["close"])
            hi,lo=float(b["high"]),float(b["low"])
            ranges.append(max(hi-lo,abs(hi-prev),abs(lo-prev)))
        atr=sum(ranges)/len(ranges)
        if entry<=0 or atr<=0: return None
        swing_low=min(float(x["low"]) for x in bars[-8:])
        swing_high=max(float(x["high"]) for x in bars[-8:])
        stop=swing_low-atr*.15 if side=="BUY" else swing_high+atr*.15
        risk=(entry-stop) if side=="BUY" else (stop-entry)
        if risk<=0 or risk/entry>.045: return None
        sign=1 if side=="BUY" else -1
        return {"entry":entry,"stop_loss":stop,"tp1":entry+sign*risk,
                "tp2":entry+sign*risk*2,"tp3":entry+sign*risk*3,
                "risk_percent":round(risk/entry*100,3)}
    except (KeyError,TypeError,ValueError,ZeroDivisionError):
        return None

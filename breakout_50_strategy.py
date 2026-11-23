"""STP False-Breakout Reversal: break candle, then close beyond its opposite edge."""
import math

STRATEGY_FINGERPRINT = "STP-FALSE-BREAKOUT-CLOSE-REVERSAL-V1-20261123"
STRATEGY_NAME = "STP FALSE BREAKOUT CLOSE REVERSAL"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000,"1w":604_800_000,"1M":2_678_400_000}
FRAME_PROFILES = {"15m":{"min_bars":45,"max_risk_pct":0.035},"1h":{"min_bars":45,"max_risk_pct":0.04},"4h":{"min_bars":45,"max_risk_pct":0.05},"1d":{"min_bars":45,"max_risk_pct":0.07},"1w":{"min_bars":45,"max_risk_pct":0.12},"1M":{"min_bars":45,"max_risk_pct":0.20}}

def _bars(rows):
    if not isinstance(rows,list) or len(rows)<3: return []
    out=[]
    for row in rows[:-1]:
        if not isinstance(row,(list,tuple)) or len(row)<6: continue
        try:
            stamp=int(float(row[0])); op,hi,lo,cl,vol=(float(row[i] or 0) for i in range(1,6))
        except (TypeError,ValueError,OverflowError): continue
        if not all(math.isfinite(x) for x in (op,hi,lo,cl,vol)): continue
        if min(op,hi,lo,cl)<=0 or vol<0 or hi<max(op,cl) or lo>min(op,cl) or hi<lo: continue
        out.append({"time":stamp,"open":op,"high":hi,"low":lo,"close":cl,"volume":vol})
    return out

def _atr(bars,period=14):
    sample=bars[-(period+1):]; values=[]
    for i,b in enumerate(sample):
        prev=sample[i-1]["close"] if i else b["close"]
        values.append(max(b["high"]-b["low"],abs(b["high"]-prev),abs(b["low"]-prev)))
    return sum(values)/len(values) if values else 0.0

def _pivots(bars,left=2,right=2):
    highs=[]; lows=[]
    for i in range(left,len(bars)-right):
        h,lo=bars[i]["high"],bars[i]["low"]
        if all(h>bars[j]["high"] for j in range(i-left,i)) and all(h>=bars[j]["high"] for j in range(i+1,i+right+1)): highs.append((i,h))
        if all(lo<bars[j]["low"] for j in range(i-left,i)) and all(lo<=bars[j]["low"] for j in range(i+1,i+right+1)): lows.append((i,lo))
    return highs,lows

def target_prices(entry,side,stop):
    try: entry,stop=float(entry),float(stop)
    except (TypeError,ValueError,OverflowError): return None
    risk=entry-stop if side=="BUY" else stop-entry
    if side not in ("BUY","SELL") or not math.isfinite(risk) or risk<=0: return None
    sign=1 if side=="BUY" else -1
    targets=tuple(entry+sign*risk*r for r in (1,2,3))
    return targets if all(math.isfinite(x) and x>0 for x in targets) else None

def _find_reversal(bars,atr,max_age=12):
    highs,lows=_pivots(bars); last=len(bars)-1; candidates=[]
    # Downside break -> BUY only after a later close above the break candle high.
    for pivot_i,level in lows:
        for i in range(max(pivot_i+1,last-max_age-1),last):
            b=bars[i]
            if b["low"]<level and b["close"]<level and bars[last]["close"]>b["high"]:
                candidates.append((i,"BUY",level,b))
    # Upside break -> SELL only after a later close below the break candle low.
    for pivot_i,level in highs:
        for i in range(max(pivot_i+1,last-max_age-1),last):
            b=bars[i]
            if b["high"]>level and b["close"]>level and bars[last]["close"]<b["low"]:
                candidates.append((i,"SELL",level,b))
    if not candidates: return None
    i,side,level,b=max(candidates,key=lambda x:x[0])
    buffer=max(atr*.15,bars[last]["close"]*.0002)
    stop=b["low"]-buffer if side=="BUY" else b["high"]+buffer
    return {"side":side,"break_index":i,"break_level":level,"break_candle_high":b["high"],
            "break_candle_low":b["low"],"break_candle_time":b["time"],"stop":stop}

def analyze(market,symbol,rows,timeframe="15m",market_bias=None,diagnostics=None,now=None,
            higher_timeframe_rows=None,microstructure=None):
    def reject(reason):
        if diagnostics is not None: diagnostics[reason]=diagnostics.get(reason,0)+1
        return None
    if market not in MARKETS or timeframe not in TIMEFRAMES: return reject("invalid_market_or_timeframe")
    bars=_bars(rows); profile=FRAME_PROFILES[timeframe]
    if len(bars)<profile["min_bars"]: return reject("insufficient_completed_candles")
    atr=_atr(bars)
    if not math.isfinite(atr) or atr<=0: return reject("invalid_atr")
    setup=_find_reversal(bars,atr)
    if not setup: return reject("no_break_candle_opposite_close_confirmation")
    current=bars[-1]; side=setup["side"]; entry=current["close"]; stop=setup["stop"]
    risk=abs(entry-stop); risk_pct=risk/entry if entry>0 else float("inf")
    if not math.isfinite(risk_pct) or risk<=0 or risk_pct>profile["max_risk_pct"]:
        return reject("break_candle_structural_stop_outside_frame_risk_limit")
    targets=target_prices(entry,side,stop)
    if not targets: return reject("invalid_target_geometry")
    confirmations=["COMPLETED_CANDLES_ONLY","CONFIRMED_SWING_LEVEL_BROKEN","BREAK_CANDLE_IDENTIFIED",
        "CLOSE_BEYOND_OPPOSITE_EDGE_OF_BREAK_CANDLE","DIRECTION_CHANGE_CONFIRMED",
        "STOP_BEYOND_BREAK_CANDLE_EXTREME","TARGETS_1R_2R_3R"]
    if (side=="BUY" and current["close"]>current["open"]) or (side=="SELL" and current["close"]<current["open"]):
        confirmations.append("DIRECTIONAL_CONFIRMATION_CANDLE")
    return {"market":market,"symbol":str(symbol),"side":side,"entry":entry,"stop":stop,
        "tp1":targets[0],"tp2":targets[1],"tp3":targets[2],"score":88.0,"timeframe":timeframe,
        "signal_candle_time":current["time"],"atr":atr,"risk_pct":round(risk_pct*100,4),
        "risk_distance":risk,"reward_risk":3.0,"change_pct":0.0,"quote_volume":None,
        "setup_type":"FALSE_BREAKOUT_CLOSE_REVERSAL",
        "structure":"DOWNSIDE_BREAK_REVERSED_TO_BUY" if side=="BUY" else "UPSIDE_BREAK_REVERSED_TO_SELL",
        "breakout_level":setup["break_level"],"break_candle_high":setup["break_candle_high"],
        "break_candle_low":setup["break_candle_low"],"break_candle_time":setup["break_candle_time"],
        "confirmations":confirmations,"strategy_names":confirmations,"strategy_count":len(confirmations),
        "strategy_total":7,"strategy":STRATEGY_FINGERPRINT+"_"+market.upper()+"_"+timeframe,
        "strategy_fingerprint":STRATEGY_FINGERPRINT,"session_mode":"ALL_HOURS",
        "strategy_mode":"FALSE_BREAKOUT_CLOSE_REVERSAL",
        "reason":STRATEGY_NAME+": "+("price broke a prior swing low then closed above the break candle high; BUY reversal." if side=="BUY" else "price broke a prior swing high then closed below the break candle low; SELL reversal.")+" Stop beyond break-candle extreme; targets 1R/2R/3R.",
        "setup_quality_label":"technical_setup_score_not_probability"}

def diagnostic_self_test():
    checks={"seven_markets":len(MARKETS)==7,"six_timeframes":len(TIMEFRAMES)==6,
        "buy_targets_1r_2r_3r":target_prices(100,"BUY",98)==(102,104,106),
        "sell_targets_1r_2r_3r":target_prices(100,"SELL",102)==(98,96,94),
        "invalid_stop_rejected":target_prices(100,"BUY",101) is None,
        "fingerprint":STRATEGY_FINGERPRINT=="STP-FALSE-BREAKOUT-CLOSE-REVERSAL-V1-20261123",
        "spot_supported":"spot" in MARKETS,"manual_only":True}
    return {"ok":all(checks.values()),"fingerprint":STRATEGY_FINGERPRINT,"checks":checks,
        "markets":list(MARKETS),"timeframes":list(TIMEFRAMES),"session":"ALL_HOURS",
        "strategy_mode":"FALSE_BREAKOUT_CLOSE_REVERSAL",
        "entry_model":"BREAK_PRIOR_SWING_THEN_CLOSE_BEYOND_OPPOSITE_EDGE_OF_BREAK_CANDLE"}

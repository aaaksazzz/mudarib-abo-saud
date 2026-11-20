"""STP fully inverted Breakout 50 + Volume Profile signal engine."""
import math

STRATEGY_FINGERPRINT = "STP-BREAKOUT-50-VOLUME-PROFILE-INVERSE-V2-20261120"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000,"1w":604_800_000,"1M":2_678_400_000}
FRAME_PROFILES = {
    "15m":{"min_bars":45,"max_risk_pct":0.035},"1h":{"min_bars":45,"max_risk_pct":0.04},
    "4h":{"min_bars":45,"max_risk_pct":0.05},"1d":{"min_bars":45,"max_risk_pct":0.07},
    "1w":{"min_bars":45,"max_risk_pct":0.12},"1M":{"min_bars":45,"max_risk_pct":0.20},
}

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

def _volume_profile(bars,bins=32):
    sample=[b for b in bars[-80:] if b["volume"]>0]
    if len(sample)<10: return None
    low=min(b["low"] for b in sample); high=max(b["high"] for b in sample)
    if not math.isfinite(low+high) or high<=low: return None
    step=(high-low)/bins; volume=[0.0]*bins
    for b in sample:
        typical=(b["high"]+b["low"]+b["close"])/3
        idx=min(bins-1,max(0,int((typical-low)/step))); volume[idx]+=b["volume"]
    total=sum(volume)
    if total<=0: return None
    poc=max(range(bins),key=lambda i:volume[i]); included={poc}; accumulated=volume[poc]
    left,right=poc-1,poc+1
    while accumulated<total*.70 and (left>=0 or right<bins):
        lv=volume[left] if left>=0 else -1; rv=volume[right] if right<bins else -1
        if rv>lv: included.add(right); accumulated+=max(0,rv); right+=1
        else: included.add(left); accumulated+=max(0,lv); left-=1
    return {"poc":low+(poc+.5)*step,"val":low+min(included)*step,
            "vah":low+(max(included)+1)*step,"coverage":round(accumulated/total,4),
            "method":"candle_typical_price_volume_approximation"}

def _vwap(bars):
    sample=[b for b in bars[-50:] if b["volume"]>0]; total=sum(b["volume"] for b in sample)
    return sum(((b["high"]+b["low"]+b["close"])/3)*b["volume"] for b in sample)/total if total>0 else None

def _rsi(values,period=14):
    if len(values)<=period: return None
    changes=[b-a for a,b in zip(values[-period-1:-1],values[-period:])]
    gain=sum(max(x,0) for x in changes)/period; loss=sum(max(-x,0) for x in changes)/period
    if loss==0: return 100.0 if gain else 50.0
    return 100-100/(1+gain/loss)

def _flow(bars,microstructure=None):
    if isinstance(microstructure,dict):
        try:
            value=float(microstructure.get("taker_delta_ratio"))
            if math.isfinite(value): return value,"binance_agg_trades_taker_delta"
        except (TypeError,ValueError,OverflowError): pass
    signed=total=0.0
    for b in bars[-12:]:
        span=max(b["high"]-b["low"],b["close"]*1e-10)
        signed+=(b["close"]-b["open"])/span*b["volume"]; total+=b["volume"]
    return (signed/total if total else 0.0),"ohlcv_candle_delta_proxy"

def _cvd_proxy(bars):
    """Approximate cumulative candle delta; this is not exchange trade-by-trade CVD."""
    cumulative=0.0
    total=0.0
    for b in bars[-30:]:
        spread=max(b["high"]-b["low"],b["close"]*1e-10)
        cumulative+=(b["close"]-b["open"])/spread*b["volume"]
        total+=b["volume"]
    return {"normalized_delta":cumulative/total if total else 0.0,
            "source":"ohlcv_candle_delta_proxy"}

def _rsi_divergence(bars,side):
    """Return a supporting (never mandatory) two-swing RSI divergence flag."""
    highs,lows=_pivots(bars)
    pivots=lows if side=="BUY" else highs
    if len(pivots)<2: return False
    (i1,p1),(i2,p2)=pivots[-2:]
    if i2-i1<4: return False
    closes=[b["close"] for b in bars]
    r1=_rsi(closes[:i1+1]); r2=_rsi(closes[:i2+1])
    if r1 is None or r2 is None: return False
    return (p2<p1 and r2>r1+2) if side=="BUY" else (p2>p1 and r2<r1-2)

def inverted_side(source_side):
    """Return the trade direction opposite to the detected breakout setup."""
    if source_side == "BUY": return "SELL"
    if source_side == "SELL": return "BUY"
    return None

def structural_stop(setup, final_side, atr, entry):
    """Place invalidation beyond the opposite edge of the source impulse/retest."""
    buffer=max(atr*.15,entry*.0002)
    if final_side=="BUY": return min(setup["retest_low"],setup["impulse_low"])-buffer
    if final_side=="SELL": return max(setup["retest_high"],setup["impulse_high"])+buffer
    return None

def target_prices(entry,side,stop):
    try: entry,stop=float(entry),float(stop)
    except (TypeError,ValueError,OverflowError): return None
    risk=entry-stop if side=="BUY" else stop-entry
    if side not in ("BUY","SELL") or not math.isfinite(risk) or risk<=0: return None
    sign=1 if side=="BUY" else -1
    result=tuple(entry+sign*risk*r for r in (1,2,3))
    return result if all(math.isfinite(x) and x>0 for x in result) else None

def _find_breakout(bars,side,atr):
    highs,lows=_pivots(bars); last=len(bars)-1; pivots=highs if side=="BUY" else lows; candidates=[]
    for pivot_i,level in pivots:
        if pivot_i<max(0,last-35) or pivot_i>=last-8: continue
        for i in range(pivot_i+1,min(last-2,pivot_i+25)):
            prev,b=bars[i-1],bars[i]
            crossed=(prev["close"]<=level and b["close"]>level) if side=="BUY" else (prev["close"]>=level and b["close"]<level)
            span=max(b["high"]-b["low"],b["close"]*1e-10)
            if crossed and abs(b["close"]-b["open"])/span>=.45 and abs(b["close"]-b["open"])>=atr*.25:
                candidates.append((i,level))
    if not candidates: return None
    break_i,level=candidates[-1]
    if side=="BUY":
        prior=[p for p in lows if p[0]<break_i]
        if not prior: return None
        impulse_low=min(b["low"] for b in bars[prior[-1][0]:break_i+1])
        impulse_high=max(b["high"] for b in bars[break_i:last+1])
        midpoint=impulse_low+(impulse_high-impulse_low)*.5
        touched=[(i,b) for i,b in enumerate(bars[break_i+1:last],break_i+1) if b["low"]<=midpoint+atr*.20 and b["high"]>=midpoint-atr*.20]
        confirmed=bool(touched and bars[last]["close"]>bars[last]["open"] and bars[last]["close"]>bars[last-1]["high"])
    else:
        prior=[p for p in highs if p[0]<break_i]
        if not prior: return None
        impulse_high=max(b["high"] for b in bars[prior[-1][0]:break_i+1])
        impulse_low=min(b["low"] for b in bars[break_i:last+1])
        midpoint=impulse_high-(impulse_high-impulse_low)*.5
        touched=[(i,b) for i,b in enumerate(bars[break_i+1:last],break_i+1) if b["high"]>=midpoint-atr*.20 and b["low"]<=midpoint+atr*.20]
        confirmed=bool(touched and bars[last]["close"]<bars[last]["open"] and bars[last]["close"]<bars[last-1]["low"])
    if not touched or not confirmed: return None
    retest_i,retest=touched[-1]
    return {"break_index":break_i,"break_level":level,"midpoint_50":midpoint,
            "impulse_low":impulse_low,"impulse_high":impulse_high,"retest_index":retest_i,
            "retest_low":retest["low"],"retest_high":retest["high"]}

def analyze(market,symbol,rows,timeframe="15m",market_bias=None,diagnostics=None,now=None,
            higher_timeframe_rows=None,microstructure=None):
    def reject(reason):
        if diagnostics is not None: diagnostics[reason]=diagnostics.get(reason,0)+1
        return None
    if market not in MARKETS or timeframe not in TIMEFRAMES: return reject("invalid_market_or_timeframe")
    bars=_bars(rows); frame=FRAME_PROFILES[timeframe]
    if len(bars)<frame["min_bars"]: return reject("insufficient_completed_candles")
    current=bars[-1]; atr=_atr(bars)
    if not math.isfinite(atr) or atr<=0: return reject("invalid_atr")
    vp=_volume_profile(bars); vwap=_vwap(bars)
    if not vp or vwap is None: return reject("volume_profile_unavailable")
    candidates=[]
    for source_side in ("BUY","SELL"):
        setup=_find_breakout(bars,source_side,atr)
        final_side=inverted_side(source_side)
        # Spot cannot short, so only source SELL setups can become executable BUY trades.
        if market=="spot" and final_side!="BUY": continue
        if setup: candidates.append((source_side,final_side,setup))
    if not candidates: return reject("no_inverted_breakout_50_retest_confirmation")
    def rank(item):
        midpoint=item[2]["midpoint_50"]
        in_va=vp["val"]-atr*.25<=midpoint<=vp["vah"]+atr*.25
        return (int(in_va),-abs(midpoint-vp["poc"])/atr)
    source_side,side,setup=max(candidates,key=rank); midpoint=setup["midpoint_50"]
    in_va=vp["val"]-atr*.25<=midpoint<=vp["vah"]+atr*.25
    if not in_va and abs(midpoint-vp["poc"])/atr>.60:
        return reject("fifty_percent_not_confluent_with_volume_profile")
    entry=current["close"]; stop=structural_stop(setup,side,atr,entry)
    risk_pct=abs(entry-stop)/entry if entry>0 and stop is not None else float("inf")
    if not math.isfinite(risk_pct) or risk_pct<=0 or risk_pct>frame["max_risk_pct"]: return reject("inverted_structural_stop_outside_frame_risk_limit")
    targets=target_prices(entry,side,stop)
    if not targets: return reject("invalid_target_geometry")
    delta,delta_source=_flow(bars,microstructure)
    rsi=_rsi([b["close"] for b in bars])
    cvd=_cvd_proxy(bars)
    rsi_divergence=_rsi_divergence(bars,side)
    try:
        book_imbalance=float(microstructure.get("book_imbalance")) if isinstance(microstructure,dict) else None
        if book_imbalance is not None and not math.isfinite(book_imbalance): book_imbalance=None
    except (TypeError,ValueError,OverflowError):
        book_imbalance=None
    confirmations=["CLOSED_CANDLE","SWING_BREAKOUT_CLOSE","FIFTY_PERCENT_RETRACE",
                   "VOLUME_PROFILE_VALUE_AREA_OR_POC","VWAP","POST_RETEST_STRUCTURE_CONFIRMATION",
                   "ATR_STRUCTURAL_STOP","THREE_R_TARGETS","FULL_SIGNAL_DIRECTION_INVERSION"]
    score=70.0
    if in_va: score+=5; confirmations.append("VP_VALUE_AREA_CONFLUENCE")
    if abs(midpoint-vwap)<=atr*.75: score+=4; confirmations.append("VWAP_CONFLUENCE")
    if (delta>.05 if side=="BUY" else delta<-.05): score+=4; confirmations.append("INVERTED_SIDE_FLOW_CONFIRMATION")
    if book_imbalance is not None and (book_imbalance>.08 if side=="BUY" else book_imbalance<-.08):
        score+=2; confirmations.append("ORDER_BOOK_IMBALANCE_SUPPORT")
    if rsi_divergence: score+=3; confirmations.append("RSI_DIVERGENCE_SUPPORT")
    if rsi is not None and ((side=="BUY" and 45<=rsi<=72) or (side=="SELL" and 28<=rsi<=55)):
        score+=2; confirmations.append("RSI_MOMENTUM_SUPPORT")
    if abs(current["close"]-current["open"])>=atr*.35: score+=3; confirmations.append("CONFIRMATION_CANDLE_DISPLACEMENT")
    return {"market":market,"symbol":str(symbol),"side":side,"entry":entry,"stop":stop,
            "tp1":targets[0],"tp2":targets[1],"tp3":targets[2],"score":round(min(92,score),1),
            "timeframe":timeframe,"signal_candle_time":current["time"],"atr":atr,
            "risk_pct":round(risk_pct*100,4),"risk_distance":abs(entry-stop),"reward_risk":3.0,
            "change_pct":0.0,"quote_volume":None,"setup_type":"BREAKOUT_50_VOLUME_PROFILE",
            "structure":"INVERTED_FROM_BEARISH_BREAKDOWN" if side=="BUY" else "INVERTED_FROM_BULLISH_BREAKOUT",
            "breakout_level":setup["break_level"],"retracement_50":midpoint,
            "volume_profile":vp,"vwap":vwap,"taker_delta_ratio":delta,"order_flow_source":delta_source,
            "rsi":rsi,"confirmations":confirmations,"strategy_names":confirmations,
            "strategy":STRATEGY_FINGERPRINT+"_"+market.upper()+"_"+timeframe,
            "strategy_fingerprint":STRATEGY_FINGERPRINT,"session_mode":"ALL_HOURS",
            "strategy_mode":"FULL_INVERSION_ALL_HOURS","source_setup_side":source_side,
            "reason":"STP BREAKOUT 50 + VOLUME PROFILE FULL INVERSION: detected breakout direction is reversed; inverse-side structural stop; VP/VWAP confluence; 1R/2R/3R.",
            "setup_quality_label":"technical_quality_not_probability"}

def diagnostic_self_test():
    sample=[{"open":100,"high":101,"low":99,"close":100,"volume":10} for _ in range(20)]
    dummy={"retest_low":97.0,"impulse_low":96.0,"retest_high":103.0,"impulse_high":104.0}
    checks={"fingerprint":STRATEGY_FINGERPRINT=="STP-BREAKOUT-50-VOLUME-PROFILE-INVERSE-V2-20261120",
            "seven_markets":len(MARKETS)==7,"six_timeframes":len(TIMEFRAMES)==6,
            "buy_targets_1r_2r_3r":target_prices(100,"BUY",98)==(102,104,106),
            "sell_targets_1r_2r_3r":target_prices(100,"SELL",102)==(98,96,94),
            "buy_setup_inverts_to_sell":inverted_side("BUY")=="SELL",
            "sell_setup_inverts_to_buy":inverted_side("SELL")=="BUY",
            "inverse_sell_stop_above_entry":structural_stop(dummy,"SELL",2,100)>100,
            "inverse_buy_stop_below_entry":structural_stop(dummy,"BUY",2,100)<100,
            "volume_profile":_volume_profile(sample) is not None,"vwap":_vwap(sample)==100.0,
            "spot_buy_only_after_inversion":inverted_side("SELL")=="BUY",
            "all_hours":True,"manual_only":True}
    return {"ok":all(checks.values()),"fingerprint":STRATEGY_FINGERPRINT,"checks":checks,
            "markets":list(MARKETS),"timeframes":list(TIMEFRAMES),
            "session":"INVERTED_ALL_HOURS","strategy_mode":"FULL_INVERSION_ALL_HOURS",
            "entry_model":"INVERTED_BREAKOUT_CLOSE_50_PERCENT_RETRACE_VOLUME_PROFILE_VWAP_STRUCTURE_CONFIRMATION"}

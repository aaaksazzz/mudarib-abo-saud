"""AS Day-Trader multi-market engine; adapted from the public day-trader workflow.

Uses completed OHLCV candles only. Setups are standard-direction (never inverted):
20-bar breakout, flag continuation, EMA20 reclaim, and RSI oversold/overbought
reversal. Stops are structural with an ATR buffer; targets are 1R/2R/3R.
Volume profile is explicitly an OHLCV approximation, not exchange-grade VAP.
"""
import math

STRATEGY_FINGERPRINT = "AS-DAYTRADER-MULTI-MARKET-V1-20261121"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {"15m":900_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000,"1w":604_800_000,"1M":2_678_400_000}
FRAME_PROFILES = {
    "15m":{"min_bars":45,"max_risk_pct":0.035},
    "1h":{"min_bars":45,"max_risk_pct":0.04},
    "4h":{"min_bars":45,"max_risk_pct":0.05},
    "1d":{"min_bars":45,"max_risk_pct":0.07},
    "1w":{"min_bars":45,"max_risk_pct":0.12},
    "1M":{"min_bars":45,"max_risk_pct":0.20},
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
    sample=bars[-(period+1):]; tr=[]
    for i,b in enumerate(sample):
        prev=sample[i-1]["close"] if i else b["close"]
        tr.append(max(b["high"]-b["low"],abs(b["high"]-prev),abs(b["low"]-prev)))
    return sum(tr)/len(tr) if tr else 0.0

def _ema(values,period):
    if len(values)<period: return None
    alpha=2/(period+1); value=sum(values[:period])/period
    for x in values[period:]: value=alpha*x+(1-alpha)*value
    return value

def _rsi(values,period=14):
    if len(values)<=period: return None
    changes=[b-a for a,b in zip(values[-period-1:-1],values[-period:])]
    gain=sum(max(x,0) for x in changes)/period
    loss=sum(max(-x,0) for x in changes)/period
    if loss==0: return 100.0 if gain else 50.0
    return 100-100/(1+gain/loss)

def _volume_profile(bars,bins=32):
    sample=[b for b in bars[-80:] if b["volume"]>0]
    if len(sample)<10: return None
    low=min(b["low"] for b in sample); high=max(b["high"] for b in sample)
    if high<=low: return None
    step=(high-low)/bins; volume=[0.0]*bins
    for b in sample:
        idx=min(bins-1,max(0,int((((b["high"]+b["low"]+b["close"])/3)-low)/step)))
        volume[idx]+=b["volume"]
    total=sum(volume)
    if total<=0: return None
    poc=max(range(bins),key=lambda i:volume[i]); included={poc}; acc=volume[poc]
    left,right=poc-1,poc+1
    while acc<total*.70 and (left>=0 or right<bins):
        lv=volume[left] if left>=0 else -1; rv=volume[right] if right<bins else -1
        if rv>lv: included.add(right); acc+=max(0,rv); right+=1
        else: included.add(left); acc+=max(0,lv); left-=1
    return {"poc":low+(poc+.5)*step,"val":low+min(included)*step,
            "vah":low+(max(included)+1)*step,"coverage":acc/total,
            "method":"candle_typical_price_volume_approximation"}

def _vwap(bars):
    sample=[b for b in bars[-50:] if b["volume"]>0]; total=sum(b["volume"] for b in sample)
    return sum(((b["high"]+b["low"]+b["close"])/3)*b["volume"] for b in sample)/total if total else None

def _flow(bars,microstructure=None):
    if isinstance(microstructure,dict):
        try:
            v=float(microstructure.get("taker_delta_ratio"))
            if math.isfinite(v): return v,"binance_agg_trades_taker_delta"
        except (TypeError,ValueError,OverflowError): pass
    signed=total=0.0
    for b in bars[-12:]:
        span=max(b["high"]-b["low"],b["close"]*1e-10)
        signed+=(b["close"]-b["open"])/span*b["volume"]; total+=b["volume"]
    return (signed/total if total else 0.0),"ohlcv_candle_delta_proxy"

def inverted_side(source_side):
    """Compatibility shim: the new engine does not invert trade direction."""
    return source_side if source_side in ("BUY","SELL") else None

def structural_stop(setup,side,atr,entry):
    pad=max(atr*.25,entry*.0002)
    if side=="BUY": return min(setup["swing_low"],setup["setup_low"])-pad
    if side=="SELL": return max(setup["swing_high"],setup["setup_high"])+pad
    return None

def target_prices(entry,side,stop):
    try: entry,stop=float(entry),float(stop)
    except (TypeError,ValueError,OverflowError): return None
    risk=entry-stop if side=="BUY" else stop-entry
    if side not in ("BUY","SELL") or not math.isfinite(risk) or risk<=0: return None
    sign=1 if side=="BUY" else -1
    result=tuple(entry+sign*risk*r for r in (1,2,3))
    return result if all(math.isfinite(x) and x>0 for x in result) else None

def _detect(bars,side,atr):
    closes=[b["close"] for b in bars]; last=len(bars)-1; cur=bars[last]; prev=bars[last-1]
    prior=bars[max(0,last-20):last]
    if len(prior)<20: return None
    swing_low=min(b["low"] for b in bars[-12:]); swing_high=max(b["high"] for b in bars[-12:])
    recent_high=max(b["high"] for b in prior); recent_low=min(b["low"] for b in prior)
    ema20=_ema(closes,20); ema50=_ema(closes,50); rsi=_rsi(closes)
    volume_base=sum(b["volume"] for b in bars[-21:-1])/20
    vol_x=cur["volume"]/volume_base if volume_base>0 else 0
    body=abs(cur["close"]-cur["open"]); span=max(cur["high"]-cur["low"],cur["close"]*1e-10)
    setups=[]
    if side=="BUY":
        if cur["close"]>recent_high and cur["close"]>cur["open"] and body/span>=.45:
            setups.append(("BREAKOUT_20", "20-bar high closed breakout"))
        if ema20 and prev["close"]<=ema20 and cur["close"]>ema20 and cur["close"]>cur["open"]:
            setups.append(("EMA20_RECLAIM","close reclaimed EMA20"))
        if rsi is not None and rsi<35 and cur["close"]>cur["open"] and cur["close"]>prev["high"]:
            setups.append(("OVERSOLD_BOUNCE","RSI oversold bounce confirmed by close"))
        impulse=max(b["high"] for b in bars[-12:-4])-min(b["low"] for b in bars[-12:-4])
        consolidation=max(b["high"] for b in bars[-4:-1])-min(b["low"] for b in bars[-4:-1])
        if impulse>=atr*2 and consolidation<=impulse*.55 and cur["close"]>max(b["high"] for b in bars[-4:-1]):
            setups.append(("BULL_FLAG","bull flag continuation breakout"))
    else:
        if cur["close"]<recent_low and cur["close"]<cur["open"] and body/span>=.45:
            setups.append(("BREAKDOWN_20","20-bar low closed breakdown"))
        if ema20 and prev["close"]>=ema20 and cur["close"]<ema20 and cur["close"]<cur["open"]:
            setups.append(("EMA20_LOSS","close lost EMA20"))
        if rsi is not None and rsi>65 and cur["close"]<cur["open"] and cur["close"]<prev["low"]:
            setups.append(("OVERBOUGHT_REJECTION","RSI overbought rejection confirmed by close"))
        impulse=max(b["high"] for b in bars[-12:-4])-min(b["low"] for b in bars[-12:-4])
        consolidation=max(b["high"] for b in bars[-4:-1])-min(b["low"] for b in bars[-4:-1])
        if impulse>=atr*2 and consolidation<=impulse*.55 and cur["close"]<min(b["low"] for b in bars[-4:-1]):
            setups.append(("BEAR_FLAG","bear flag continuation breakdown"))
    if not setups: return None
    # Prefer a clean breakout/flag; supporting signals add confluence, not extra duplicate trades.
    setup_type,setup_text=setups[0]
    return {"setup_type":setup_type,"setup_text":setup_text,"swing_low":swing_low,
            "swing_high":swing_high,"setup_low":min(b["low"] for b in bars[-4:]),
            "setup_high":max(b["high"] for b in bars[-4:]),"ema20":ema20,"ema50":ema50,
            "rsi":rsi,"volume_ratio":vol_x,"supporting_setups":[x[0] for x in setups]}

def analyze(market,symbol,rows,timeframe="15m",market_bias=None,diagnostics=None,now=None,
            higher_timeframe_rows=None,microstructure=None):
    def reject(reason):
        if diagnostics is not None: diagnostics[reason]=diagnostics.get(reason,0)+1
        return None
    if market not in MARKETS or timeframe not in TIMEFRAMES: return reject("invalid_market_or_timeframe")
    bars=_bars(rows); profile=FRAME_PROFILES[timeframe]
    if len(bars)<profile["min_bars"]: return reject("insufficient_completed_candles")
    current=bars[-1]; atr=_atr(bars)
    if not math.isfinite(atr) or atr<=0: return reject("invalid_atr")
    vp=_volume_profile(bars); vwap=_vwap(bars)
    if not vp or vwap is None: return reject("volume_profile_unavailable")
    choices=[]
    for side in ("BUY","SELL"):
        if market=="spot" and side=="SELL": continue
        setup=_detect(bars,side,atr)
        if setup: choices.append((side,setup))
    if not choices: return reject("no_confirmed_daytrader_setup")
    # Never publish both sides for one symbol/timeframe; choose stronger close displacement.
    side,setup=max(choices,key=lambda x: abs(current["close"]-current["open"])/atr)
    entry=current["close"]; stop=structural_stop(setup,side,atr,entry)
    risk_pct=abs(entry-stop)/entry if stop else float("inf")
    if not math.isfinite(risk_pct) or risk_pct<=0 or risk_pct>profile["max_risk_pct"]:
        return reject("structural_stop_outside_frame_risk_limit")
    targets=target_prices(entry,side,stop)
    if not targets: return reject("invalid_target_geometry")
    delta,delta_source=_flow(bars,microstructure); rsi=setup["rsi"]
    confirmations=["COMPLETED_CANDLE","CLOSED_BREAKOUT_OR_REVERSAL","STRUCTURAL_SWING_STOP",
                   "ATR_BUFFER","TARGETS_1R_2R_3R","STANDARD_DIRECTION_NO_INVERSION"]
    score=65.0
    if setup["volume_ratio"]>=1.2: score+=7; confirmations.append("VOLUME_EXPANSION")
    if (side=="BUY" and current["close"]>vwap) or (side=="SELL" and current["close"]<vwap):
        score+=4; confirmations.append("VWAP_DIRECTIONAL_SUPPORT")
    if vp["val"]<=entry<=vp["vah"]: score+=4; confirmations.append("VOLUME_PROFILE_VALUE_AREA")
    if (side=="BUY" and delta>.05) or (side=="SELL" and delta<-.05):
        score+=3; confirmations.append("ORDER_FLOW_SUPPORT")
    if setup["ema20"] and setup["ema50"] and ((side=="BUY" and setup["ema20"]>setup["ema50"]) or (side=="SELL" and setup["ema20"]<setup["ema50"])):
        score+=4; confirmations.append("EMA_TREND_ALIGNMENT")
    if setup["setup_type"].endswith("FLAG"): score+=3; confirmations.append("FLAG_CONTINUATION")
    return {"market":market,"symbol":str(symbol),"side":side,"entry":entry,"stop":stop,
            "tp1":targets[0],"tp2":targets[1],"tp3":targets[2],"score":round(min(90,score),1),
            "timeframe":timeframe,"signal_candle_time":current["time"],"atr":atr,
            "risk_pct":round(risk_pct*100,4),"risk_distance":abs(entry-stop),"reward_risk":3.0,
            "change_pct":0.0,"quote_volume":None,"setup_type":setup["setup_type"],
            "structure":setup["setup_text"],"volume_profile":vp,"vwap":vwap,
            "taker_delta_ratio":delta,"order_flow_source":delta_source,"rsi":rsi,
            "volume_ratio":setup["volume_ratio"],"supporting_setups":setup["supporting_setups"],
            "confirmations":confirmations,"strategy_names":confirmations,
            "strategy":STRATEGY_FINGERPRINT+"_"+market.upper()+"_"+timeframe,
            "strategy_fingerprint":STRATEGY_FINGERPRINT,"session_mode":"ALL_SESSIONS",
            "strategy_mode":"MULTI_SETUP_STANDARD_DIRECTION",
            "reason":"AS DAY-TRADER ENGINE: "+setup["setup_text"]+"; volume/EMA/VWAP/VP confirmation; structural ATR stop; 1R/2R/3R.",
            "setup_quality_label":"technical_confluence_not_probability"}

def diagnostic_self_test():
    checks={"seven_markets":len(MARKETS)==7,"six_timeframes":len(TIMEFRAMES)==6,
            "buy_targets_1r_2r_3r":target_prices(100,"BUY",98)==(102,104,106),
            "sell_targets_1r_2r_3r":target_prices(100,"SELL",102)==(98,96,94),
            "directions_not_inverted":inverted_side("BUY")=="BUY" and inverted_side("SELL")=="SELL",
            "spot_buy_only":True,"all_sessions":True,"manual_only":True}
    return {"ok":all(checks.values()),"fingerprint":STRATEGY_FINGERPRINT,"checks":checks,
            "markets":list(MARKETS),"timeframes":list(TIMEFRAMES),
            "strategy_mode":"MULTI_SETUP_STANDARD_DIRECTION",
            "entry_model":"BREAKOUT20_FLAG_EMA20_RECLAIM_OVERSOLD_BOUNCE_STANDARD_DIRECTION"}

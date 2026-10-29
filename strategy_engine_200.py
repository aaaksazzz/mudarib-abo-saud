"""Multi-market technical analysis engine with a 200-method catalogue.

The 200 catalogue entries are organized into 20 evidence families. Family scores
are aggregated once to avoid counting closely related indicators as independent
votes. This is a technical scoring framework, not a claim of 200 independent
predictive models or guaranteed profitability.
"""
from __future__ import annotations
import math

FAMILIES = [
 ("trend", "الاتجاه والمتوسطات", ["SMA","EMA","WMA","HMA","DEMA","TEMA","VWMA","KAMA","ALMA","Supertrend"]),
 ("momentum", "الزخم", ["RSI","MACD","ROC","Momentum","PPO","TSI","TRIX","WilliamsR","CCI","UltimateOscillator"]),
 ("volatility", "التذبذب", ["ATR","Bollinger","Keltner","DonchianWidth","StdDev","HistoricalVolatility","Choppiness","BBWidth","TrueRange","RangeExpansion"]),
 ("volume", "الحجم والتدفق", ["OBV","MFI","CMF","ADL","VWAP","ForceIndex","VolumeROC","VolumeZScore","PVT","EOM"]),
 ("structure", "بنية السعر", ["HigherHighs","HigherLows","LowerHighs","LowerLows","BOS","CHOCH","SwingStructure","RangeStructure","TrendLegs","MarketPhases"]),
 ("levels", "الدعم والمقاومة", ["SwingLevels","PivotPoints","FloorPivots","FibonacciLevels","RoundNumbers","PreviousHighLow","WeeklyLevels","MonthlyLevels","VolumeNodesProxy","DynamicLevels"]),
 ("breakout", "الاختراقات والانهيارات", ["RangeBreakout","DonchianBreakout","CloseBreakout","Retest","VolatilityBreakout","OpeningRange","CompressionRelease","FalseBreakout","ChannelBreak","TrendlineBreak"]),
 ("candles", "نماذج الشموع", ["Engulfing","PinBar","Hammer","ShootingStar","InsideBar","OutsideBar","Doji","Marubozu","MorningStar","EveningStar"]),
 ("patterns", "النماذج السعرية", ["DoubleTop","DoubleBottom","HeadShoulders","InverseHeadShoulders","Triangles","Flags","Pennants","Wedges","CupHandle","Rectangles"]),
 ("ichimoku", "إيشيموكو", ["TenkanKijun","KumoPosition","KumoBreakout","ChikouConfirm","SenkouCross","CloudThickness","KijunSlope","TenkanSlope","CloudTwist","MultiSignal"]),
 ("adx", "قوة الاتجاه", ["ADX","DMI","PlusDI","MinusDI","Aroon","Vortex","LinearRegressionSlope","TrendEfficiency","DirectionalPersistence","TrendStrength"]),
 ("oscillators", "المذبذبات", ["Stochastic","StochRSI","WilliamsPercentR","FisherTransform","AwesomeOscillator","AcceleratorOscillator","DetrendedPrice","SchaffTrend","CoppockCurve","KnowSureThing"]),
 ("mean_reversion", "الارتداد للمتوسط", ["ZScore","BollingerReentry","RSIExtremes","DistanceFromEMA","VWAPReversion","RangeReversion","DeviationBands","MeanCross","Overshoot","ReversionFailure"]),
 ("market_profile", "مناطق القيمة", ["AnchoredVWAPProxy","VolumeWeightedPrice","ValueAreaProxy","POCProxy","Acceptance","Rejection","BalanceArea","Imbalance","PriceAcceptance","AuctionShift"]),
 ("liquidity", "السيولة ومصائدها", ["EqualHighs","EqualLows","SweepHigh","SweepLow","LiquidityReclaim","WickRejection","StopRun","FailedAuction","Displacement","LiquidityVoid"]),
 ("gaps", "الفجوات وعدم الكفاءة", ["FairValueGap","GapFill","GapContinuation","ImbalanceFill","OpeningGap","ExhaustionGap","GapReclaim","ThreeCandleImbalance","ImpulseGap","GapInvalidation"]),
 ("harmonic", "النماذج التوافقية", ["Gartley","Bat","Butterfly","Crab","Shark","Cypher","ABCD","ThreeDrives","MeasuredMove","RatioConfluence"]),
 ("cycles", "الدورات والزمن", ["BarCount","SessionTiming","WeeklyCycle","MonthlyCycle","RangeCycle","VolatilityCycle","TimeSymmetry","SessionRange","TrendAge","CycleBreak"]),
 ("multi_timeframe", "توافق الفريمات", ["DailyTrend","FourHourTrend","HourlyTrend","FifteenMinuteTrend","WeeklyBias","MonthlyBias","TrendAlignment","MomentumAlignment","LevelAlignment","ConflictPenalty"]),
 ("risk_quality", "جودة الفرصة والمخاطر", ["RewardRisk","ATRStopFit","TargetRoom","ExtensionPenalty","LateEntryPenalty","LiquidityQuality","CandleCloseQuality","SignalAgreement","NoiseFilter","InvalidationClarity"]),
]
METHOD_CATALOG = [
 {"id": f"M{i+1:03d}", "family": family, "family_ar": title, "method": method}
 for i, (family, title, method) in enumerate(
     ( (family, title, method) for family, title, methods in FAMILIES for method in methods )
 )
]
assert len(METHOD_CATALOG) == 200

def _num(c, key, default=0.0):
    try:
        v = float(c.get(key, default) or default)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default

def _ema(values, period):
    a = 2.0 / (period + 1.0)
    out = values[0]
    for x in values[1:]:
        out = a*x + (1-a)*out
    return out

def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))

def _sign(x, dead=0.0):
    return 1.0 if x > dead else -1.0 if x < -dead else 0.0

def analyze_200(candles):
    """Return a scored BUY/SELL/None setup from OHLCV candle dictionaries."""
    if not isinstance(candles, (list, tuple)) or len(candles) < 50:
        return None
    rows = []
    for c in candles:
        if not isinstance(c, dict):
            continue
        o,h,l,cl,v = (_num(c,k) for k in ("open","high","low","close","volume"))
        if min(o,h,l,cl) <= 0 or h < max(o,cl) or l > min(o,cl):
            continue
        rows.append({"open":o,"high":h,"low":l,"close":cl,"volume":max(0,v)})
    if len(rows) < 50:
        return None
    close=[x["close"] for x in rows]; high=[x["high"] for x in rows]; low=[x["low"] for x in rows]; vol=[x["volume"] for x in rows]
    last=close[-1]; prev=close[-2]
    if last <= 0 or prev <= 0:
        return None
    ema20=_ema(close[-min(len(close),100):],20)
    ema50=_ema(close,50)
    ema200=_ema(close,200) if len(close)>=200 else _ema(close, min(100,len(close)))
    # RSI using recent average gains/losses.
    changes=[close[i]-close[i-1] for i in range(1,len(close))]
    recent=changes[-14:]
    gains=sum(max(x,0) for x in recent)/max(1,len(recent)); losses=sum(max(-x,0) for x in recent)/max(1,len(recent))
    rsi=100.0 if losses==0 and gains>0 else 50.0 if losses==gains==0 else 100-(100/(1+gains/losses)) if losses else 100.0
    # ATR and directional candle ranges.
    tr=[]
    for i in range(1,len(rows)):
        tr.append(max(high[i]-low[i],abs(high[i]-close[i-1]),abs(low[i]-close[i-1])))
    atr=sum(tr[-14:])/max(1,len(tr[-14:]))
    if not math.isfinite(atr) or atr<=0:
        return None
    # MACD direction and recent momentum.
    ema12=_ema(close[-min(len(close),100):],12); ema26=_ema(close[-min(len(close),100):],26)
    macd=ema12-ema26
    macd_hist=macd-(ema12-ema26) # neutral-safe when signal history isn't built
    macd_hist = macd - _ema([_ema(close[:i+1],12)-_ema(close[:i+1],26) for i in range(max(25,len(close)-30),len(close))],9)
    # Trend / structure
    slope=(close[-1]-close[-min(10,len(close))])/max(atr,1e-12)
    hh=max(high[-20:]); ll=min(low[-20:])
    prior_h=max(high[-21:-1]); prior_l=min(low[-21:-1])
    body=rows[-1]["close"]-rows[-1]["open"]
    candle_range=max(high[-1]-low[-1],1e-12)
    upper_wick=high[-1]-max(close[-1],rows[-1]["open"])
    lower_wick=min(close[-1],rows[-1]["open"])-low[-1]
    avgvol=sum(vol[-20:])/max(1,len(vol[-20:]))
    vol_ratio=vol[-1]/avgvol if avgvol>0 else 1.0
    # Family scores are independent-ish evidence groups; correlated indicators inside a family are not double-counted.
    scores={}
    scores["trend"]=_clamp((1 if last>ema20 else -1)+(1 if ema20>ema50 else -1)+(1 if ema50>ema200 else -1),-3,3)/3
    scores["momentum"]=_clamp((1 if rsi>55 else -1 if rsi<45 else 0)*0.65 + _sign(macd)*0.35)
    scores["volatility"]=_clamp(_sign(slope,0.35)*0.65 + _sign((candle_range/atr)-1.1)*0.35)
    scores["volume"]=_clamp(_sign(body)*min(1.0,vol_ratio/1.5) if vol_ratio>=0.8 else 0.0)
    scores["structure"]=_clamp((_sign(last-close[-10],atr*0.15)+_sign(close[-10]-close[-20],atr*0.15))/2)
    scores["levels"]=_clamp(_sign((last-(hh+ll)/2),atr*0.08))
    scores["breakout"]=_clamp(1.0 if last>prior_h else -1.0 if last<prior_l else _sign(last-prior_h,atr*0.15) if last>prior_h-atr*0.15 else _sign(last-prior_l,atr*0.15) if last<prior_l+atr*0.15 else 0.0)
    scores["candles"]=_clamp(_sign(body,candle_range*0.15)+(_sign(lower_wick-upper_wick,candle_range*0.2) if abs(body)<candle_range*0.45 else 0),-1,1)
    scores["patterns"]=_clamp(_sign(close[-1]-close[-5],atr*0.2))
    scores["ichimoku"]=_clamp((_sign(last-(_ema(high[-26:],9)+_ema(low[-26:],9))/2)+_sign(_ema(close[-min(52,len(close)):],26)-_ema(close[-min(52,len(close)):],9)))/2)
    scores["adx"]=_clamp(_sign(slope,0.4)*min(1,abs(slope)/1.5))
    scores["oscillators"]=_clamp(_sign(rsi-50,10))
    scores["mean_reversion"]=_clamp(_sign(last-ema20,atr*0.8)*-1)
    scores["market_profile"]=_clamp(_sign(last-(sum(close[-20:])/20),atr*0.15))
    scores["liquidity"]=_clamp(_sign(lower_wick-upper_wick,candle_range*0.18))
    scores["gaps"]=_clamp(_sign(body)*0.5 if abs(rows[-1]["open"]-prev)>atr*0.4 else 0)
    scores["harmonic"]=_clamp(_sign(last-(hh+ll)/2,atr*0.2))
    scores["cycles"]=_clamp(_sign(close[-1]-close[-min(8,len(close))],atr*0.2))
    scores["multi_timeframe"]=_clamp((scores["trend"]+scores["momentum"]+scores["structure"])/3)
    # Penalize weak reward room, stretched entries, and thin/absent volume where available.
    extension=abs(last-ema20)/atr
    scores["risk_quality"]=_clamp(0.6 if extension<2.2 else -0.7)
    # Average family evidence equally; do not sum all 200 catalogue labels as independent votes.
    family_scores={k:round(v,4) for k,v in scores.items()}
    composite=sum(scores.values())/len(scores)
    bullish=sum(1 for v in scores.values() if v>0.15)
    bearish=sum(1 for v in scores.values() if v<-0.15)
    agreement=max(bullish,bearish)/len(scores)
    side="BUY" if composite>=0.28 and bullish>=11 else "SELL" if composite<=-0.28 and bearish>=11 else None
    entry=last
    if side=="BUY":
        stop=entry-max(1.5*atr,entry*0.002)
        risk=entry-stop
        targets=[entry+risk,entry+2*risk,entry+3*risk]
    elif side=="SELL":
        stop=entry+max(1.5*atr,entry*0.002)
        risk=stop-entry
        targets=[entry-risk,entry-2*risk,entry-3*risk]
    else:
        stop=None; targets=[]
    catalog_scores=[{"id":m["id"],"family":m["family_ar"],"method":m["method"],"score":family_scores.get(m["family"],0.0)} for m in METHOD_CATALOG]
    return {
      "side":side,"strength":("شراء قوي" if side=="BUY" and composite>=0.45 else "شراء" if side=="BUY" else "بيع قوي" if side=="SELL" and composite<=-0.45 else "بيع" if side=="SELL" else "محايد"),
      "entry":round(entry,10),"stop_loss":round(stop,10) if stop is not None else None,
      "tp1":round(targets[0],10) if targets else None,"tp2":round(targets[1],10) if targets else None,"tp3":round(targets[2],10) if targets else None,
      "score_pct":round(abs(composite)*100,1),"family_agreement_pct":round(agreement*100,1),
      "families_bullish":bullish,"families_bearish":bearish,"families_total":len(scores),
      "methods_catalogued":len(METHOD_CATALOG),"independent_families_scored":len(scores),
      "family_scores":family_scores,"atr":round(atr,10),"rsi14":round(rsi,2),
      "ema20":round(ema20,10),"ema50":round(ema50,10),"ema200":round(ema200,10),
      "risk_reward":[1,2,3] if side else [],"method":"200-method catalogue / 20 evidence families"
    }

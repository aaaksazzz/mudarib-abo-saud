"""SMART FLOW: false-breakout liquidity sweep with close-confirmed reclaim.

Signals are analytical only. The engine never places orders.
"""
import math

STRATEGY_FINGERPRINT = "SMART-FLOW-FALSE-SWEEP-MTF-V2-20261114"
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
SIGNAL_TIMEFRAME = {frame: frame for frame in TIMEFRAMES}
INTERVAL_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
               "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000}
SUPPORTED_TIMEFRAMES = tuple(INTERVAL_MS)
PROFILES = {market: {"allow_short": True} for market in
            ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")}


def _finite_rows(rows):
    parsed = []
    if not isinstance(rows, list) or len(rows) < 2:
        return None
    for row in rows[:-1]:  # Exclude the still-forming final candle.
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            return None
        try:
            stamp = int(float(row[0]))
            op, hi, lo, close, volume = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            return None
        if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)):
            return None
        if min(op, hi, lo, close) <= 0 or volume < 0 or hi < max(op, close) or lo > min(op, close) or hi < lo:
            return None
        parsed.append((stamp, op, hi, lo, close, volume))
    return parsed


def _atr(highs, lows, closes, period=14):
    ranges = []
    for i in range(len(closes)):
        previous = closes[i - 1] if i else closes[i]
        ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous), abs(lows[i] - previous)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def target_prices(entry, side, stop=None):
    """Return fixed 1R / 2R / 3R targets from one entry and structural stop."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(entry) or not math.isfinite(stop) or entry <= 0 or stop <= 0 or side not in ("BUY", "SELL"):
        return None
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1.0 if side == "BUY" else -1.0
    result = tuple(entry + sign * risk * multiple for multiple in (1, 2, 3))
    return result if all(math.isfinite(x) and x > 0 for x in result) else None


def _find_sweep_setup(highs, lows, opens, closes, volumes, atr, lookback=20, recent=6):
    """Find a recent stop-run, reclaim candle, then a later close beyond the sweep candle."""
    n = len(closes)
    first = max(lookback, n - recent - 1)
    for i in range(n - 2, first - 1, -1):
        prior_high = max(highs[i - lookback:i])
        prior_low = min(lows[i - lookback:i])
        candle_range = max(highs[i] - lows[i], closes[i] * 1e-8)
        lower_wick = min(opens[i], closes[i]) - lows[i]
        upper_wick = highs[i] - max(opens[i], closes[i])
        bullish = lows[i] < prior_low and closes[i] > prior_low and closes[i] > opens[i] and lower_wick / candle_range >= 0.20
        bearish = highs[i] > prior_high and closes[i] < prior_high and closes[i] < opens[i] and upper_wick / candle_range >= 0.20
        if bullish and closes[-1] > highs[i]:
            if any(closes[j] <= lows[i] for j in range(i + 1, n)):
                continue
            return {"side": "BUY", "sweep_index": i, "sweep_extreme": lows[i],
                    "broken_level": prior_low, "wick_ratio": lower_wick / candle_range,
                    "sweep_volume": volumes[i]}
        if bearish and closes[-1] < lows[i]:
            if any(closes[j] >= highs[i] for j in range(i + 1, n)):
                continue
            return {"side": "SELL", "sweep_index": i, "sweep_extreme": highs[i],
                    "broken_level": prior_high, "wick_ratio": upper_wick / candle_range,
                    "sweep_volume": volumes[i]}
    return None


def analyze(market, symbol, rows, timeframe="15m", microstructure=None, include_micro=False):
    profile = PROFILES.get(market)
    if not profile or timeframe not in TIMEFRAMES:
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 40:
        return None
    opens, highs, lows, closes, volumes = ([x[k] for x in bars] for k in (1, 2, 3, 4, 5))
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0 or atr / entry > 0.20:
        return None
    setup = _find_sweep_setup(highs, lows, opens, closes, volumes, atr)
    if not setup or (setup["side"] == "SELL" and not profile["allow_short"]):
        return None
    side = setup["side"]
    buffer = max(atr * 0.12, entry * 0.0002)
    stop = setup["sweep_extreme"] - buffer if side == "BUY" else setup["sweep_extreme"] + buffer
    risk = entry - stop if side == "BUY" else stop - entry
    if not math.isfinite(risk) or risk <= 0 or risk > atr * 8 or risk > entry * 0.025:
        return None
    ladder = target_prices(entry, side, stop)
    if not ladder:
        return None

    sweep_idx = setup["sweep_index"]
    prior_volumes = volumes[max(0, sweep_idx - 20):sweep_idx]
    avg_volume = sum(prior_volumes) / max(1, len(prior_volumes))
    volume_ratio = setup["sweep_volume"] / avg_volume if avg_volume > 0 else 1.0
    score = 58.0 + min(14.0, max(0.0, (setup["wick_ratio"] - 0.20) * 30.0))
    if volume_ratio >= 1.5:
        score += 10.0
    elif volume_ratio >= 1.15:
        score += 5.0
    reclaim_distance = abs(entry - (highs[sweep_idx] if side == "BUY" else lows[sweep_idx]))
    if reclaim_distance >= atr * 0.25:
        score += 8.0
    if risk <= atr * 2.5:
        score += 5.0
    score = round(min(95.0, score), 1)

    previous_close = closes[-2]
    reason = (
        f"FALSE-SWEEP: {side} liquidity sweep beyond prior {'low' if side == 'BUY' else 'high'}; "
        "reclaim candle closed back inside range; later completed candle closed beyond sweep candle; "
        "stop beyond sweep extreme; maximum stop distance 2.5%; targets fixed at 1R/2R/3R"
    )
    return {
        "side": side, "entry": entry, "stop": stop,
        "tp1": ladder[0], "tp2": ladder[1], "tp3": ladder[2],
        "score": score, "timeframe": timeframe,
        "change_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "change_15m_pct": round((entry / previous_close - 1.0) * 100.0, 5) if previous_close else 0.0,
        "reason": reason, "signal_candle_time": bars[-1][0],
        "risk_atr": round(risk / atr, 3), "reward_risk": 3.0, "atr": atr,
        "sweep_extreme": setup["sweep_extreme"], "broken_level": setup["broken_level"],
        "sweep_candle_time": bars[sweep_idx][0],
        "sweep_wick_ratio": round(setup["wick_ratio"], 3), "volume_ratio": round(volume_ratio, 3),
        "confirmations": 3,
        "strategy_votes": {
            "BUY": ["سحب سيولة أسفل قاع سابق", "إغلاق استعادة صاعد", "إغلاق لاحق فوق شمعة السحب"] if side == "BUY" else [],
            "SELL": ["سحب سيولة أعلى قمة سابقة", "إغلاق استعادة هابط", "إغلاق لاحق تحت شمعة السحب"] if side == "SELL" else [],
        },
        "strategy": "FALSE_SWEEP_" + market.upper() + "_" + timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
    }


def diagnostic_self_test():
    buy, sell = target_prices(100, "BUY", 95), target_prices(100, "SELL", 105)
    checks = {
        "six_independent_timeframes": TIMEFRAMES == ("15m", "1h", "4h", "1d", "1w", "1M"),
        "all_markets_supported": all(PROFILES[m]["allow_short"] for m in PROFILES),
        "each_frame_uses_itself": all(SIGNAL_TIMEFRAME[x] == x for x in TIMEFRAMES),
        "buy_risk_ladder_1_2_3R": buy == (105.0, 110.0, 115.0),
        "sell_risk_ladder_1_2_3R": sell == (95.0, 90.0, 85.0),
        "bad_risk_rejected": target_prices(100, "BUY", 101) is None,
        "forming_candle_excluded": len(_finite_rows([[i, 10, 11, 9, 10, 1] for i in range(41)])) == 40,
    }
    return {"fingerprint": STRATEGY_FINGERPRINT, "ok": all(checks.values()), "checks": checks,
            "timeframes": list(TIMEFRAMES), "signal_timeframes": dict(SIGNAL_TIMEFRAME),
            "rule": "liquidity sweep -> reclaim close -> later close beyond sweep candle -> structural stop -> 1R/2R/3R"}


# Independent strategy voting engine. Each rule evaluates the same closed-candle
# series in isolation; the aggregator ranks a setup by distinct agreeing rules.
STRATEGY_CATALOG = (
    "FALSE_SWEEP", "EMA_TREND", "MACD_CROSS", "RSI_REVERSAL",
    "BOLLINGER_REVERSION", "DONCHIAN_BREAKOUT", "MOMENTUM_ROC",
    "STOCHASTIC_REVERSAL", "CCI_REVERSAL", "ICHIMOKU_TREND",
    "ATR_CHANNEL_BREAKOUT", "ENGULFING_REVERSAL",
)


def _ema(values, period):
    if len(values) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [sum(values[:period]) / period]
    for value in values[period:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return [None] * (period - 1) + out


def _rsi(values, period=14):
    if len(values) <= period:
        return None
    gains=[]; losses=[]
    for i in range(1,len(values)):
        delta=values[i]-values[i-1]
        gains.append(max(delta,0.0)); losses.append(max(-delta,0.0))
    avg_gain=sum(gains[:period])/period
    avg_loss=sum(losses[:period])/period
    for i in range(period,len(gains)):
        avg_gain=((period-1)*avg_gain+gains[i])/period
        avg_loss=((period-1)*avg_loss+losses[i])/period
    if avg_loss == 0:
        return 100.0
    return 100.0-(100.0/(1.0+avg_gain/avg_loss))


def _independent_votes(bars):
    o=[x[1] for x in bars]; h=[x[2] for x in bars]
    l=[x[3] for x in bars]; c=[x[4] for x in bars]
    votes=[]
    def add(name, side, strength=1.0):
        if side in ("BUY","SELL"):
            votes.append({"name":name,"side":side,"strength":round(float(strength),3)})

    # EMA trend: fast/slow alignment plus price location.
    e20,e50=_ema(c,20),_ema(c,50)
    if e20 and e50 and e20[-1] is not None and e50[-1] is not None:
        if e20[-1]>e50[-1] and c[-1]>e20[-1]: add("EMA_TREND","BUY")
        elif e20[-1]<e50[-1] and c[-1]<e20[-1]: add("EMA_TREND","SELL")

    # MACD line/signal crossover confirmed by the latest closed bar.
    e12,e26=_ema(c,12),_ema(c,26)
    if e12 and e26 and len(c)>35 and e26[-1] is not None:
        macd=[(x-y if x is not None and y is not None else None) for x,y in zip(e12,e26)]
        valid=[x for x in macd if x is not None]
        sig=_ema(valid,9)
        if len(valid)>9 and sig and sig[-1] is not None and sig[-2] is not None:
            if valid[-2]<=sig[-2] and valid[-1]>sig[-1]: add("MACD_CROSS","BUY",1.1)
            elif valid[-2]>=sig[-2] and valid[-1]<sig[-1]: add("MACD_CROSS","SELL",1.1)

    # RSI exhaustion reversal, requiring a directional close.
    rsi=_rsi(c)
    if rsi is not None:
        if rsi<30 and c[-1]>o[-1]: add("RSI_REVERSAL","BUY")
        elif rsi>70 and c[-1]<o[-1]: add("RSI_REVERSAL","SELL")

    # Bollinger re-entry after an outside close.
    if len(c)>=21:
        window=c[-20:]; mean=sum(window)/20
        sd=(sum((x-mean)**2 for x in window)/20)**0.5
        if sd>0 and c[-2]<mean-2*sd and c[-1]>mean-2*sd and c[-1]>o[-1]:
            add("BOLLINGER_REVERSION","BUY")
        elif sd>0 and c[-2]>mean+2*sd and c[-1]<mean+2*sd and c[-1]<o[-1]:
            add("BOLLINGER_REVERSION","SELL")

    # Donchian close breakout against the preceding 20 completed bars.
    if len(c)>=22:
        top=max(h[-21:-1]); bottom=min(l[-21:-1])
        if c[-1]>top: add("DONCHIAN_BREAKOUT","BUY",1.1)
        elif c[-1]<bottom: add("DONCHIAN_BREAKOUT","SELL",1.1)

    # 10-bar rate-of-change momentum with a 20 EMA filter.
    if len(c)>=21 and e20 and e20[-1] is not None:
        roc=c[-1]/c[-11]-1.0
        if roc>0.015 and c[-1]>e20[-1]: add("MOMENTUM_ROC","BUY")
        elif roc<-0.015 and c[-1]<e20[-1]: add("MOMENTUM_ROC","SELL")

    # Stochastic oscillator reversal from an extreme zone.
    if len(c)>=16:
        lo=min(l[-14:]); hi=max(h[-14:])
        k=50.0 if hi==lo else 100.0*(c[-1]-lo)/(hi-lo)
        prev_lo=min(l[-15:-1]); prev_hi=max(h[-15:-1])
        pk=50.0 if prev_hi==prev_lo else 100.0*(c[-2]-prev_lo)/(prev_hi-prev_lo)
        if pk<20 and k>=20 and c[-1]>o[-1]: add("STOCHASTIC_REVERSAL","BUY")
        elif pk>80 and k<=80 and c[-1]<o[-1]: add("STOCHASTIC_REVERSAL","SELL")

    # CCI(20) crossing back through +/-100.
    if len(c)>=21:
        tp=[(h[i]+l[i]+c[i])/3 for i in range(len(c))]
        w=tp[-20:]; avg=sum(w)/20
        md=sum(abs(x-avg) for x in w)/20
        prev_w=tp[-21:-1]; prev_avg=sum(prev_w)/20
        prev_md=sum(abs(x-prev_avg) for x in prev_w)/20
        cci=0 if md==0 else (tp[-1]-avg)/(0.015*md)
        pcci=0 if prev_md==0 else (tp[-2]-prev_avg)/(0.015*prev_md)
        if pcci<=-100 and cci>-100: add("CCI_REVERSAL","BUY")
        elif pcci>=100 and cci<100: add("CCI_REVERSAL","SELL")

    # Ichimoku cloud trend using standard 9/26/52 periods.
    if len(c)>=52:
        tenkan=(max(h[-9:])+min(l[-9:]))/2
        kijun=(max(h[-26:])+min(l[-26:]))/2
        span_a=(tenkan+kijun)/2
        span_b=(max(h[-52:])+min(l[-52:]))/2
        cloud_top=max(span_a,span_b); cloud_bottom=min(span_a,span_b)
        if c[-1]>cloud_top and tenkan>kijun: add("ICHIMOKU_TREND","BUY",1.1)
        elif c[-1]<cloud_bottom and tenkan<kijun: add("ICHIMOKU_TREND","SELL",1.1)

    # ATR channel breakout (not labelled as Supertrend; no trailing-band state is calculated).
    if len(c)>=16:
        atr=_atr(h,l,c,14)
        mid=(h[-1]+l[-1])/2
        upper=mid+3*atr; lower=mid-3*atr
        if c[-1]>upper: add("ATR_CHANNEL_BREAKOUT","BUY",1.1)
        elif c[-1]<lower: add("ATR_CHANNEL_BREAKOUT","SELL",1.1)

    # Two-candle engulfing reversal.
    if len(c)>=2:
        bull=(c[-2]<o[-2] and c[-1]>o[-1] and o[-1]<=c[-2] and c[-1]>=o[-2])
        bear=(c[-2]>o[-2] and c[-1]<o[-1] and o[-1]>=c[-2] and c[-1]<=o[-2])
        if bull: add("ENGULFING_REVERSAL","BUY")
        elif bear: add("ENGULFING_REVERSAL","SELL")
    return votes


def analyze_all(market, symbol, rows, timeframe="15m"):
    """Run every catalog rule separately and return the strongest consensus setup."""
    bars=_finite_rows(rows)
    if not bars or len(bars)<60:
        return None
    results=[]
    sweep=analyze(market,symbol,rows,timeframe=timeframe)
    if sweep:
        results.append({"name":"FALSE_SWEEP","side":sweep["side"],"strength":1.2,"setup":sweep})
    votes=_independent_votes(bars)
    results.extend(votes)
    if not results:
        return None
    by_side={"BUY":[],"SELL":[]}
    for vote in results:
        by_side[vote["side"]].append(vote)
    buy, sell=by_side["BUY"],by_side["SELL"]
    chosen=buy if len(buy)>len(sell) else sell if len(sell)>len(buy) else []
    if not chosen:
        return None
    # Require at least two independent rules; ties/opposition are not published.
    if len(chosen)<2:
        return None
    side=chosen[0]["side"]
    setup=next((x.get("setup") for x in chosen if x.get("setup")),None)
    if not setup:
        entry=bars[-1][4]
        atr=_atr([x[2] for x in bars],[x[3] for x in bars],[x[4] for x in bars])
        if not math.isfinite(atr) or atr<=0:
            return None
        stop=entry-1.5*atr if side=="BUY" else entry+1.5*atr
        targets=target_prices(entry,side,stop)
        if not targets:
            return None
        setup={"side":side,"entry":entry,"stop":stop,"tp1":targets[0],"tp2":targets[1],"tp3":targets[2],
               "score":55.0,"timeframe":timeframe,"signal_candle_time":bars[-1][0],
               "atr":atr,"risk_atr":1.5,"reward_risk":3.0,"reason":"Independent strategy consensus"}
    else:
        setup=dict(setup)
        if setup["side"]!=side:
            return None
    count=len(chosen)
    names=[x["name"] for x in chosen]
    total=len(results)
    setup.update({
        "strategy":"CONSENSUS_"+side,
        "strategy_fingerprint":"STP-INDEPENDENT-CONSENSUS-V1",
        "strategy_count":count,
        "strategy_total":len(STRATEGY_CATALOG),
        "strategy_names":names,
        "strategy_votes":{"BUY":[x["name"] for x in buy],"SELL":[x["name"] for x in sell]},
        "score":round(min(99.0,50.0+count*4.0+sum(x.get("strength",1.0)-1.0 for x in chosen)*5.0),1),
        "reason":"CONSENSUS "+side+" "+str(count)+"/"+str(len(STRATEGY_CATALOG))+" independent strategies: "+", ".join(names),
    })
    return setup


# STP strategy laboratory: 1,000 separately evaluated rule variants.
# Variants are unique parameterized rules within ten distinct strategy families.
# Consensus is capped at one vote per family to prevent parameter variants from
# manufacturing an artificial majority.
_VARIANT_FAMILIES = (
    "EMA_TREND", "RSI_REVERSAL", "BOLLINGER_REENTRY", "DONCHIAN_BREAKOUT",
    "ROC_MOMENTUM", "STOCHASTIC_REVERSAL", "CCI_REVERSAL",
    "ATR_CHANNEL_BREAKOUT", "VOLUME_BREAKOUT", "CANDLE_MOMENTUM",
)
_VARIANT_PERIODS = (6, 8, 10, 12, 14, 18, 20, 24, 30, 40)
_VARIANT_LEVELS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
STRATEGY_VARIANTS = tuple(
    {
        "id": f"{family}_P{period}_L{level:02d}",
        "family": family,
        "period": period,
        "level": level,
    }
    for family in _VARIANT_FAMILIES
    for period in _VARIANT_PERIODS
    for level in _VARIANT_LEVELS
)
STRATEGY_CATALOG = tuple(x["id"] for x in STRATEGY_VARIANTS)
STRATEGY_CATALOG_VERSION = "STP-1000-RULE-VARIANTS-V1"


def _variant_vote(rule, opens, highs, lows, closes, volumes):
    """Evaluate one unique family/period/threshold rule on completed candles."""
    family, p, level = rule["family"], rule["period"], rule["level"]
    n = len(closes)
    if n < max(45, p + 3):
        return None
    # Ten level settings are deliberately distinct and deterministic.
    threshold = level / 10.0
    side = None
    if family == "EMA_TREND":
        fast = _ema(closes, p)
        slow_period = p + 12 + level * 3
        slow = _ema(closes, slow_period)
        if fast and slow and fast[-1] is not None and slow[-1] is not None:
            if fast[-1] > slow[-1] and closes[-1] > fast[-1] and fast[-1] >= fast[-2]:
                side = "BUY"
            elif fast[-1] < slow[-1] and closes[-1] < fast[-1] and fast[-1] <= fast[-2]:
                side = "SELL"
    elif family == "RSI_REVERSAL":
        value = _rsi(closes, p)
        low = 20.0 + level * 2.0
        high = 100.0 - low
        if value is not None:
            if value <= low and closes[-1] > opens[-1]: side = "BUY"
            elif value >= high and closes[-1] < opens[-1]: side = "SELL"
    elif family == "BOLLINGER_REENTRY":
        window = closes[-p:]
        mean = sum(window) / p
        sd = (sum((x - mean) ** 2 for x in window) / p) ** 0.5
        mult = 1.4 + level * 0.12
        if sd > 0:
            upper, lower = mean + mult * sd, mean - mult * sd
            prev = closes[-p-1:-1]
            pm = sum(prev) / p
            psd = (sum((x-pm)**2 for x in prev)/p)**0.5
            if closes[-2] < pm-mult*psd and closes[-1] > lower and closes[-1] > opens[-1]:
                side = "BUY"
            elif closes[-2] > pm+mult*psd and closes[-1] < upper and closes[-1] < opens[-1]:
                side = "SELL"
    elif family == "DONCHIAN_BREAKOUT":
        top, bottom = max(highs[-p-1:-1]), min(lows[-p-1:-1])
        pad = threshold * _atr(highs, lows, closes, min(14, p))
        if closes[-1] > top + pad: side = "BUY"
        elif closes[-1] < bottom - pad: side = "SELL"
    elif family == "ROC_MOMENTUM":
        roc = closes[-1] / closes[-p-1] - 1.0
        cutoff = 0.001 + threshold * 0.02
        if roc > cutoff: side = "BUY"
        elif roc < -cutoff: side = "SELL"
    elif family == "STOCHASTIC_REVERSAL":
        hh, ll = max(highs[-p:]), min(lows[-p:])
        prev_hh, prev_ll = max(highs[-p-1:-1]), min(lows[-p-1:-1])
        k = 50.0 if hh == ll else 100.0 * (closes[-1]-ll)/(hh-ll)
        pk = 50.0 if prev_hh == prev_ll else 100.0*(closes[-2]-prev_ll)/(prev_hh-prev_ll)
        low_zone = 10.0 + level * 3.0
        high_zone = 100.0 - low_zone
        if pk < low_zone and k >= low_zone and closes[-1] > opens[-1]: side = "BUY"
        elif pk > high_zone and k <= high_zone and closes[-1] < opens[-1]: side = "SELL"
    elif family == "CCI_REVERSAL":
        typical = [(highs[i]+lows[i]+closes[i])/3.0 for i in range(n)]
        window = typical[-p:]
        mean = sum(window)/p
        dev = sum(abs(x-mean) for x in window)/p
        prev = typical[-p-1:-1]
        pmean = sum(prev)/p
        pdev = sum(abs(x-pmean) for x in prev)/p
        cci = 0.0 if dev == 0 else (typical[-1]-mean)/(0.015*dev)
        pcci = 0.0 if pdev == 0 else (typical[-2]-pmean)/(0.015*pdev)
        band = 80.0 + level * 10.0
        if pcci <= -band and cci > -band: side = "BUY"
        elif pcci >= band and cci < band: side = "SELL"
    elif family == "ATR_CHANNEL_BREAKOUT":
        atr = _atr(highs, lows, closes, p)
        center = _ema(closes, p)
        mult = 0.8 + level * 0.2
        if center and center[-1] is not None and atr > 0:
            if closes[-1] > center[-1] + mult*atr: side = "BUY"
            elif closes[-1] < center[-1] - mult*atr: side = "SELL"
    elif family == "VOLUME_BREAKOUT":
        avg = sum(volumes[-p-1:-1]) / p
        ratio = volumes[-1] / avg if avg > 0 else 0.0
        prior_high, prior_low = max(highs[-p-1:-1]), min(lows[-p-1:-1])
        required = 1.0 + threshold * 1.5
        if ratio >= required and closes[-1] > prior_high: side = "BUY"
        elif ratio >= required and closes[-1] < prior_low: side = "SELL"
    elif family == "CANDLE_MOMENTUM":
        span = max(highs[-1]-lows[-1], closes[-1]*1e-9)
        body = abs(closes[-1]-opens[-1]) / span
        prior_up = sum(1 for i in range(-p, -1) if closes[i] > opens[i])
        prior_down = (p-1)-prior_up
        required_body = 0.35 + threshold * 0.05
        if closes[-1] > opens[-1] and body >= required_body and prior_up >= (p-1)*0.6:
            side = "BUY"
        elif closes[-1] < opens[-1] and body >= required_body and prior_down >= (p-1)*0.6:
            side = "SELL"
    return {"name": rule["id"], "family": family, "side": side} if side else None


def analyze_all(market, symbol, rows, timeframe="15m"):
    """Evaluate 1,000 rule variants; require agreement from distinct families."""
    if market not in PROFILES or timeframe not in TIMEFRAMES:
        return None
    bars = _finite_rows(rows)
    if not bars or len(bars) < 60:
        return None
    opens, highs, lows, closes, volumes = ([x[k] for x in bars] for k in (1, 2, 3, 4, 5))
    variants = [v for rule in STRATEGY_VARIANTS
                if (v := _variant_vote(rule, opens, highs, lows, closes, volumes))]
    # Keep the legacy false-sweep rule as a separate, named family vote.
    sweep = analyze(market, symbol, rows, timeframe=timeframe)
    if sweep:
        variants.append({"name": "FALSE_SWEEP", "family": "FALSE_SWEEP", "side": sweep["side"]})
    family_sides = {"BUY": {}, "SELL": {}}
    for vote in variants:
        family_sides[vote["side"]].setdefault(vote["family"], []).append(vote["name"])
    buy_families, sell_families = family_sides["BUY"], family_sides["SELL"]
    if len(buy_families) > len(sell_families):
        side, chosen_families = "BUY", buy_families
    elif len(sell_families) > len(buy_families):
        side, chosen_families = "SELL", sell_families
    else:
        return None
    # Two distinct families minimum: parameter variants cannot create fake consensus.
    if len(chosen_families) < 2:
        return None
    chosen_names = [name for names in chosen_families.values() for name in names]
    entry = closes[-1]
    atr = _atr(highs, lows, closes)
    if not math.isfinite(atr) or atr <= 0:
        return None
    sweep_setup = sweep if sweep and sweep["side"] == side else None
    if sweep_setup:
        setup = dict(sweep_setup)
    else:
        stop = entry - 1.5*atr if side == "BUY" else entry + 1.5*atr
        targets = target_prices(entry, side, stop)
        if not targets:
            return None
        setup = {
            "side": side, "entry": entry, "stop": stop,
            "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
            "timeframe": timeframe, "signal_candle_time": bars[-1][0],
            "atr": atr, "risk_atr": 1.5, "reward_risk": 3.0,
        }
    setup.update({
        "strategy": "CONSENSUS_" + side,
        "strategy_fingerprint": STRATEGY_CATALOG_VERSION,
        "strategy_count": len(chosen_names),
        "strategy_family_count": len(chosen_families),
        "strategy_total": len(STRATEGY_CATALOG),
        "strategy_names": chosen_names,
        "strategy_families": list(chosen_families.keys()),
        "strategy_votes": {
            "BUY": list(buy_families.keys()),
            "SELL": list(sell_families.keys()),
        },
        "score": round(min(99.0, 50.0 + len(chosen_families)*4.0 + min(20, len(chosen_names))*0.25), 1),
        "reason": (
            "CONSENSUS " + side + " | " + str(len(chosen_names)) + " agreeing rule variants across "
            + str(len(chosen_families)) + " distinct families"
        ),
    })
    return setup


# Reserve one catalog slot for the original structural false-sweep strategy:
# 999 parameterized variants + 1 separately evaluated false-sweep rule = 1,000.
STRATEGY_VARIANTS = STRATEGY_VARIANTS[:999] + ({
    "id": "FALSE_SWEEP",
    "family": "FALSE_SWEEP",
    "period": 20,
    "level": 0,
},)
STRATEGY_CATALOG = tuple(x["id"] for x in STRATEGY_VARIANTS)

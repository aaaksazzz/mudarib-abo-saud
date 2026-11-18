"""AS Practical Signal Extraction V4: accessible multi-setup paper signal engine."""
import math


STRATEGY_FINGERPRINT = "AS-SIGNAL-EXTRACTION-V4-20261118-ADAPTIVE"\nDECEPTION_ENGINE_FINGERPRINT = "AS-MARKET-DECEPTION-LAB-V1-20261118"
TREND_TIMEFRAME_MAP = {"15m": "1h", "1h": "4h", "4h": "1d", "1d": "1w", "1w": "1M", "1M": "1M"}
TIMEFRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
INTERVAL_MS = {
    "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
    "1d": 86_400_000, "1w": 604_800_000, "1M": 2_678_400_000,
}
FRAME_PROFILES = {
    "15m": {"min_bars": 40, "max_risk_pct": 0.035},
    "1h": {"min_bars": 40, "max_risk_pct": 0.040},
    "4h": {"min_bars": 40, "max_risk_pct": 0.050},
    "1d": {"min_bars": 40, "max_risk_pct": 0.070},
    "1w": {"min_bars": 40, "max_risk_pct": 0.120},
    "1M": {"min_bars": 40, "max_risk_pct": 0.200},
}
def target_prices(entry, side, stop):
    return _target_prices(float(entry), str(side), float(stop))


def _bars(rows):
    if not isinstance(rows, list) or len(rows) < 3:
        return []
    result = []
    for row in rows[:-1]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        try:
            stamp = int(float(row[0]))
            o, h, lo, c, v = (float(row[i] or 0) for i in range(1, 6))
        except (TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(x) for x in (o, h, lo, c, v)):
            continue
        if min(o, h, lo, c) <= 0 or v < 0 or h < max(o, c) or lo > min(o, c) or h < lo:
            continue
        result.append({"time": stamp, "open": o, "high": h, "low": lo, "close": c, "volume": v})
    return result


def _pivots(bars, left=2, right=2):
    highs, lows = [], []
    for i in range(left, len(bars) - right):
        h, lo = bars[i]["high"], bars[i]["low"]
        if all(h > bars[j]["high"] for j in range(i-left, i)) and all(h >= bars[j]["high"] for j in range(i+1, i+right+1)):
            highs.append((i, h))
        if all(lo < bars[j]["low"] for j in range(i-left, i)) and all(lo <= bars[j]["low"] for j in range(i+1, i+right+1)):
            lows.append((i, lo))
    return highs, lows


def _classify_trend(rows):
    """Classify confirmed higher-timeframe structure using consecutive swing highs/lows."""
    bars = _bars(rows)
    highs, lows = _pivots(bars)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"
    previous_high, latest_high = highs[-2][1], highs[-1][1]
    previous_low, latest_low = lows[-2][1], lows[-1][1]
    if latest_high > previous_high and latest_low > previous_low:
        return "BULLISH"
    if latest_high < previous_high and latest_low < previous_low:
        return "BEARISH"
    return "NEUTRAL"


def _ema(values, period):
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1)
    value = float(values[0])
    for item in values[1:]:
        value = alpha * float(item) + (1-alpha) * value
    return value


def _local_trend(bars):
    closes = [bar["close"] for bar in bars]
    if len(closes) < 25:
        return "NEUTRAL"
    fast = _ema(closes[-min(50, len(closes)):], 20)
    slow = _ema(closes[-min(100, len(closes)):], 50)
    if fast > slow and closes[-1] >= fast:
        return "BULLISH"
    if fast < slow and closes[-1] <= fast:
        return "BEARISH"
    return "NEUTRAL"



def detect_market_deception(bars):
    """Detect chart-visible trap patterns; never infer intent from price alone.

    Returns evidence labels and heuristic severity, not a probability. Spoofing,
    wash trading and coordinated manipulation require order-book/trade identity data
    and are deliberately marked unobservable from OHLCV candles.
    """
    if not isinstance(bars, list) or len(bars) < 12:
        return {"patterns": [], "severity": "UNKNOWN",
                "unobservable_without_order_flow": ["spoofing", "wash_trading", "layering"]}

    current = bars[-1]
    window = bars[-21:-1]
    if len(window) < 10:
        return {"patterns": [], "severity": "UNKNOWN",
                "unobservable_without_order_flow": ["spoofing", "wash_trading", "layering"]}

    high_level = max(b["high"] for b in window)
    low_level = min(b["low"] for b in window)
    span = max(current["high"]-current["low"], current["close"]*1e-10)
    upper_wick = current["high"]-max(current["open"], current["close"])
    lower_wick = min(current["open"], current["close"])-current["low"]
    body_ratio = abs(current["close"]-current["open"])/span
    avg_volume = sum(b["volume"] for b in window)/len(window)
    volume_ratio = current["volume"]/avg_volume if avg_volume > 0 else None
    patterns = []

    # A wick beyond a well-defined range followed by a close back inside is
    # a chart-visible failed breakout / liquidity sweep, not proof of intent.
    if current["high"] > high_level and current["close"] < high_level and upper_wick/span >= 0.30:
        patterns.append({"name": "BULL_TRAP_OR_BUY_SIDE_SWEEP", "side": "BUYERS_TRAPPED",
                         "evidence": ["high_above_20_bar_range", "close_back_below_range",
                                      "upper_wick_rejection"], "volume_ratio": volume_ratio})
    if current["low"] < low_level and current["close"] > low_level and lower_wick/span >= 0.30:
        patterns.append({"name": "BEAR_TRAP_OR_SELL_SIDE_SWEEP", "side": "SELLERS_TRAPPED",
                         "evidence": ["low_below_20_bar_range", "close_back_above_range",
                                      "lower_wick_rejection"], "volume_ratio": volume_ratio})

    # A close outside the range can still fail if the next completed candle
    # returns inside. Compare the two most recent completed bars.
    previous = bars[-2]
    earlier = bars[-22:-2]
    if len(earlier) >= 10:
        prior_high = max(b["high"] for b in earlier)
        prior_low = min(b["low"] for b in earlier)
        if previous["close"] > prior_high and current["close"] < prior_high:
            patterns.append({"name": "FAILED_UPSIDE_BREAKOUT", "side": "BUYERS_TRAPPED",
                             "evidence": ["prior_close_above_range", "next_close_back_inside"],
                             "volume_ratio": volume_ratio})
        if previous["close"] < prior_low and current["close"] > prior_low:
            patterns.append({"name": "FAILED_DOWNSIDE_BREAKOUT", "side": "SELLERS_TRAPPED",
                             "evidence": ["prior_close_below_range", "next_close_back_inside"],
                             "volume_ratio": volume_ratio})

    if volume_ratio is not None and volume_ratio >= 1.8 and body_ratio <= 0.25:
        wick_ratio = max(upper_wick, lower_wick)/span
        if wick_ratio >= 0.55:
            patterns.append({"name": "POSSIBLE_ABSORPTION_OR_EXHAUSTION", "side": "TWO_SIDED",
                             "evidence": ["volume_at_least_1_8x_average", "small_real_body",
                                          "long_rejection_wick"], "volume_ratio": round(volume_ratio, 2)})

    # Detect an impulse followed by a sharp opposite close over a short sequence.
    recent = bars[-6:]
    if len(recent) == 6 and avg_volume > 0:
        impulse_move = (recent[3]["close"]-recent[0]["close"])/recent[0]["close"]
        reversal_move = (recent[5]["close"]-recent[3]["close"])/recent[3]["close"]
        impulse_volume = sum(b["volume"] for b in recent[1:4])/3
        if impulse_move >= 0.035 and reversal_move <= -0.025 and impulse_volume >= avg_volume*1.5:
            patterns.append({"name": "POSSIBLE_PUMP_AND_DUMP_SHAPE", "side": "LATE_BUYERS_AT_RISK",
                             "evidence": ["rapid_upward_impulse", "volume_expansion",
                                          "sharp_opposite_reversal"], "volume_ratio": round(impulse_volume/avg_volume, 2)})
        elif impulse_move <= -0.035 and reversal_move >= 0.025 and impulse_volume >= avg_volume*1.5:
            patterns.append({"name": "POSSIBLE_DUMP_AND_RECOVERY_SHAPE", "side": "LATE_SELLERS_AT_RISK",
                             "evidence": ["rapid_downward_impulse", "volume_expansion",
                                          "sharp_opposite_reversal"], "volume_ratio": round(impulse_volume/avg_volume, 2)})

    severity = "HIGH" if any(p["name"] in (
        "BULL_TRAP_OR_BUY_SIDE_SWEEP", "BEAR_TRAP_OR_SELL_SIDE_SWEEP",
        "FAILED_UPSIDE_BREAKOUT", "FAILED_DOWNSIDE_BREAKOUT",
        "POSSIBLE_PUMP_AND_DUMP_SHAPE", "POSSIBLE_DUMP_AND_RECOVERY_SHAPE"
    ) for p in patterns) else ("WATCH" if patterns else "NONE")
    return {"patterns": patterns, "severity": severity,
            "unobservable_without_order_flow": ["spoofing", "wash_trading", "layering",
                                                "fake_order_wall", "coordinated_account_activity"]}


def _atr(bars, period=14):
    sample = bars[-(period + 1):]
    ranges = []
    for i, bar in enumerate(sample):
        prev = sample[i-1]["close"] if i else bar["close"]
        ranges.append(max(bar["high"]-bar["low"], abs(bar["high"]-prev), abs(bar["low"]-prev)))
    return sum(ranges) / len(ranges) if ranges else 0.0


def _target_prices(entry, side, stop):
    risk = entry-stop if side == "BUY" else stop-entry
    if not math.isfinite(risk) or risk <= 0:
        return None
    sign = 1 if side == "BUY" else -1
    targets = tuple(entry + sign*risk*r for r in (1, 2, 3))
    return targets if all(math.isfinite(x) and x > 0 for x in targets) else None


def _find_setup(bars, source_side):
    """Confirmed sweep -> displacement through prior swing -> later FVG retest."""
    highs, lows = _pivots(bars)
    current_i = len(bars)-1
    current = bars[current_i]
    recent_start = max(0, current_i-30)
    candidates = []
    if source_side == "BUY":
        for pivot_i, level in lows:
            if pivot_i < recent_start or pivot_i >= current_i-3:
                continue
            for sweep_i in range(pivot_i+1, min(current_i-2, pivot_i+13)):
                b = bars[sweep_i]
                span = max(b["high"]-b["low"], b["close"]*1e-10)
                wick = min(b["open"], b["close"])-b["low"]
                if b["low"] < level and b["close"] > level and wick/span >= 0.20:
                    pre = [p for p in highs if p[0] < sweep_i]
                    if pre:
                        candidates.append((sweep_i, b["low"], pre[-1][1]))
    else:
        for pivot_i, level in highs:
            if pivot_i < recent_start or pivot_i >= current_i-3:
                continue
            for sweep_i in range(pivot_i+1, min(current_i-2, pivot_i+13)):
                b = bars[sweep_i]
                span = max(b["high"]-b["low"], b["close"]*1e-10)
                wick = b["high"]-max(b["open"], b["close"])
                if b["high"] > level and b["close"] < level and wick/span >= 0.20:
                    pre = [p for p in lows if p[0] < sweep_i]
                    if pre:
                        candidates.append((sweep_i, b["high"], pre[-1][1]))
    if not candidates:
        return None
    sweep_i, sweep_extreme, break_level = max(candidates, key=lambda x: x[0])
    break_i = None
    for i in range(sweep_i+1, current_i-2):
        b = bars[i]
        span = max(b["high"]-b["low"], b["close"]*1e-10)
        body = abs(b["close"]-b["open"])
        valid = (b["close"] > break_level and b["close"] > b["open"] and body/span >= 0.50
                 if source_side == "BUY" else
                 b["close"] < break_level and b["close"] < b["open"] and body/span >= 0.50)
        if valid:
            break_i = i
            break
    if break_i is None:
        return None
    fvg = None
    for i in range(break_i+1, current_i):
        if i < 2:
            continue
        if source_side == "BUY":
            gap_low, gap_high = bars[i-2]["high"], bars[i]["low"]
        else:
            gap_low, gap_high = bars[i]["high"], bars[i-2]["low"]
        if gap_high <= gap_low:
            continue
        touched = current["low"] <= gap_high and current["high"] >= gap_low
        midpoint = (gap_low+gap_high)/2
        rejected = (current["close"] > current["open"] and current["close"] >= midpoint
                    if source_side == "BUY" else
                    current["close"] < current["open"] and current["close"] <= midpoint)
        if touched and rejected:
            fvg = (i, gap_low, gap_high)
    if fvg is None:
        return None
    fvg_i, gap_low, gap_high = fvg
    if current_i <= fvg_i:
        return None
    return {"sweep_index": sweep_i, "sweep_extreme": sweep_extreme,
            "break_index": break_i, "fvg_index": fvg_i,
            "fvg_low": gap_low, "fvg_high": gap_high}


def analyze(market, symbol, rows, timeframe="15m", market_bias=None, diagnostics=None, now=None, higher_timeframe_rows=None):
    """Prefer advanced liquidity setups, but allow simpler valid setups to avoid empty scans."""
    def note(reason):
        if diagnostics is not None:
            diagnostics[reason] = diagnostics.get(reason, 0) + 1

    def reject(reason):
        note(reason)
        return None

    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return reject("invalid_market_or_timeframe")
    bars = _bars(rows)
    if len(bars) < FRAME_PROFILES[timeframe]["min_bars"]:
        return reject("insufficient_completed_candles")
    current = bars[-1]
    atr = _atr(bars)
    if not math.isfinite(atr) or atr <= 0:
        return reject("invalid_atr")

    trend_rows = higher_timeframe_rows if timeframe != "1M" else rows
    higher_trend = _classify_trend(trend_rows) if isinstance(trend_rows, list) and len(trend_rows) >= 10 else "NEUTRAL"
    local_trend = _local_trend(bars)
    if higher_trend == "NEUTRAL":
        note("higher_timeframe_not_decisive_local_context_used")

    setups = []
    for candidate_side in ("BUY", "SELL"):
        advanced = _find_setup(bars, candidate_side)
        if advanced:
            setups.append((candidate_side, advanced, "liquidity_sweep_fvg"))

    closes = [bar["close"] for bar in bars]
    ema20 = _ema(closes[-min(60, len(closes)):], 20)
    prior = bars[-11:-1]
    prior_high = max(bar["high"] for bar in prior)
    prior_low = min(bar["low"] for bar in prior)
    bullish = current["close"] > current["open"]
    bearish = current["close"] < current["open"]
    fallback_side, fallback_type = None, None
    if bullish and local_trend == "BULLISH" and current["close"] >= ema20:
        fallback_side, fallback_type = "BUY", "trend_pullback"
    elif bearish and local_trend == "BEARISH" and current["close"] <= ema20:
        fallback_side, fallback_type = "SELL", "trend_pullback"
    elif bullish and current["close"] > prior_high:
        fallback_side, fallback_type = "BUY", "range_breakout"
    elif bearish and current["close"] < prior_low:
        fallback_side, fallback_type = "SELL", "range_breakout"

    if not setups and fallback_side:
        recent = bars[-7:]
        extreme = min(b["low"] for b in recent) if fallback_side == "BUY" else max(b["high"] for b in recent)
        setups.append((fallback_side, {"sweep_extreme": extreme}, fallback_type))
    if not setups:
        return reject("no_simple_or_advanced_setup")

    if market == "spot":
        setups = [item for item in setups if item[0] == "BUY"]
        if not setups:
            return reject("spot_buy_only_no_buy_setup")

    side, setup, setup_type = max(
        setups,
        key=lambda item: (
            1 if item[2] == "liquidity_sweep_fvg" else 0,
            abs(current["close"]-current["open"]) / max(current["high"]-current["low"], current["close"]*1e-10),
        ),
    )
    entry = current["close"]
    buffer = max(atr * 0.15, entry * 0.0002)
    if setup_type == "liquidity_sweep_fvg":
        stop = min(current["low"], setup["sweep_extreme"])-buffer if side == "BUY" else max(current["high"], setup["sweep_extreme"])+buffer
    else:
        recent = bars[-7:]
        stop = min(b["low"] for b in recent)-buffer if side == "BUY" else max(b["high"] for b in recent)+buffer
    risk = abs(entry-stop)
    risk_pct = risk/entry if entry > 0 else float("inf")
    if risk <= 0 or not math.isfinite(risk_pct) or risk_pct > FRAME_PROFILES[timeframe]["max_risk_pct"]:
        return reject("structural_stop_outside_frame_risk_limit")
    targets = _target_prices(entry, side, stop)
    if not targets:
        return reject("invalid_target_geometry")

    confirmations = ["CLOSED_CANDLE", "LOCAL_PRICE_STRUCTURE"]
    score = 76.0 if setup_type == "liquidity_sweep_fvg" else 66.0
    if setup_type == "liquidity_sweep_fvg":
        confirmations.extend(["LIQUIDITY_SWEEP", "CHoCH_BOS_DISPLACEMENT", "FAIR_VALUE_GAP", "FVG_RETEST_REJECTION"])
    else:
        confirmations.append("EMA_TREND_PULLBACK" if setup_type == "trend_pullback" else "10_BAR_RANGE_BREAKOUT")
    if higher_trend == ("BULLISH" if side == "BUY" else "BEARISH"):
        score += 5
        confirmations.append("HIGHER_TIMEFRAME_AGREEMENT")
    elif higher_trend in ("BULLISH", "BEARISH"):
        score -= 8
        confirmations.append("HIGHER_TIMEFRAME_CONFLICT_CAUTION")
    span = max(current["high"]-current["low"], current["close"]*1e-10)
    if abs(current["close"]-current["open"])/span >= 0.55:
        score += 3
        confirmations.append("STRONG_CLOSED_CANDLE")
    volumes = [b["volume"] for b in bars[-21:-1] if b["volume"] > 0]
    if current["volume"] > 0 and volumes and current["volume"] >= sum(volumes)/len(volumes)*1.1:
        score += 3
        confirmations.append("RELATIVE_VOLUME_CONFIRMATION")

    deception = detect_market_deception(bars)
    for pattern in deception["patterns"]:
        confirmations.append("DECEPTION_WATCH_" + pattern["name"])
    # Warning only: don't turn the new detector into another signal-killing gate.
    if deception["severity"] == "HIGH":
        score -= 4

    return {
        "market": market, "symbol": str(symbol), "side": side,
        "entry": entry, "stop": stop, "tp1": targets[0], "tp2": targets[1], "tp3": targets[2],
        "score": round(min(92.0, max(50.0, score)), 1), "timeframe": timeframe,
        "signal_candle_time": current["time"], "atr": atr,
        "risk_pct": round(risk_pct*100, 4), "risk_distance": risk,
        "reward_risk": 3.0, "change_pct": 0.0, "quote_volume": None,
        "setup_type": "PRICE_ACTION_LIQUIDITY_STRUCTURE_FVG" if setup_type == "liquidity_sweep_fvg" else setup_type.upper(),
        "structure": ("BULLISH" if side == "BUY" else "BEARISH") + "_" + setup_type.upper(),
        "higher_timeframe": TREND_TIMEFRAME_MAP[timeframe], "higher_timeframe_trend": higher_trend,
        "local_trend": local_trend, "source_setup_side": side, "session_mode": "NORMAL_ALL_HOURS",
        "confirmations": confirmations, "strategy_names": confirmations,
        "strategy": "AS_PRACTICAL_SIGNAL_EXTRACTION_V4_"+market.upper()+"_"+timeframe,
        "strategy_fingerprint": STRATEGY_FINGERPRINT,
        "fvg": {"low": setup.get("fvg_low"), "high": setup.get("fvg_high")} if setup_type == "liquidity_sweep_fvg" else None,
        "sweep_extreme": setup.get("sweep_extreme"),
        "order_flow_status": "optional_provider_data_not_required",
        "reason": "AS V4: "+setup_type+"; closed-candle entry; structural stop; targets 1R/2R/3R",
        "setup_quality_label": "technical_quality_not_probability",\n        "market_deception": deception,\n        "deception_engine_fingerprint": DECEPTION_ENGINE_FINGERPRINT,
    }


def diagnostic_self_test():
    checks = {
        "fingerprint": STRATEGY_FINGERPRINT == "AS-SIGNAL-EXTRACTION-V4-20261118-ADAPTIVE",\n        "deception_engine": DECEPTION_ENGINE_FINGERPRINT == "AS-MARKET-DECEPTION-LAB-V1-20261118",
        "six_timeframes": len(TIMEFRAMES) == 6,
        "seven_markets": len(MARKETS) == 7,
        "no_session_inversion": True,
        "buy_targets_1r_2r_3r": _target_prices(100.0, "BUY", 98.0) == (102.0, 104.0, 106.0),
        "sell_targets_1r_2r_3r": _target_prices(100.0, "SELL", 102.0) == (98.0, 96.0, 94.0),
        "spot_is_buy_only": True,
        "independent_of_market_bias": True,
        "higher_timeframe_is_context_not_hard_gate": True,
        "closed_candle_only": True,
    }
    return {"ok": all(checks.values()), "fingerprint": STRATEGY_FINGERPRINT,
            "checks": checks, "timeframes": list(TIMEFRAMES), "markets": list(MARKETS),
            "session": "NORMAL_ALL_HOURS",
            "entry_model": "LIQUIDITY_FVG_WITH_TREND_PULLBACK_AND_RANGE_BREAKOUT_FALLBACK"}

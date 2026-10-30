"""Deterministic multi-timeframe strategy engine.

4h and daily candle structure decide trade direction and eligibility.
15m candles are used only to rank eligible opportunities and define execution risk.
Scores describe evidence quality, never probability of profit.
"""
import math
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

FRAME_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
                 "4h": 14400, "1d": 86400, "1w": 604800, "1M": 2592000}
RISK_CAP = {"15m": .018, "30m": .022, "1h": .03, "2h": .04,
            "4h": .055, "1d": .08, "1w": .12, "1M": .18}
_SCAN_CURSORS = {}
_SCAN_CURSOR_LOCK = threading.Lock()


def _ema(values, period):
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out


def _rsi(values, period=14):
    if len(values) < period + 1:
        return 50.0
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    recent = changes[-period:]
    avg_gain = sum(max(0.0, value) for value in recent) / period
    avg_loss = sum(max(0.0, -value) for value in recent) / period
    if avg_loss <= 1e-15:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(candles, period=14):
    if not candles:
        return 0.0
    true_ranges = []
    for index, candle in enumerate(candles):
        previous_close = candles[index - 1]["close"] if index else candle["close"]
        true_ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close)
        ))
    sample = true_ranges[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _adx(candles, period=14):
    if len(candles) < period + 2:
        return 0.0
    plus, minus, true_ranges = [], [], []
    for index in range(1, len(candles)):
        current, previous = candles[index], candles[index - 1]
        up = current["high"] - previous["high"]
        down = previous["low"] - current["low"]
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        ))
    dx_values = []
    for end in range(period, len(true_ranges) + 1):
        p = sum(plus[end - period:end]) / period
        m = sum(minus[end - period:end]) / period
        tr = sum(true_ranges[end - period:end]) / period
        if tr <= 0 or p + m <= 0:
            dx_values.append(0.0)
        else:
            plus_di, minus_di = 100.0 * p / tr, 100.0 * m / tr
            dx_values.append(abs(plus_di - minus_di) / (plus_di + minus_di) * 100.0)
    sample = dx_values[-period:]
    return sum(sample) / len(sample) if sample else 0.0


def _valid_candles(raw):
    rows = []
    for candle in raw[-240:] if isinstance(raw, list) else []:
        try:
            row = {key: float(candle[key]) for key in ("open", "high", "low", "close", "volume")}
            valid = (
                all(math.isfinite(row[key]) and row[key] > 0
                    for key in ("open", "high", "low", "close"))
                and math.isfinite(row["volume"]) and row["volume"] >= 0
                and row["high"] >= max(row["open"], row["close"])
                and row["low"] <= min(row["open"], row["close"])
                and row["high"] >= row["low"]
            )
            if valid:
                rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return rows


def _frame_analysis(candles):
    """Calculate trend, momentum, participation and nearby structure."""
    if len(candles) < 60:
        return None
    closes = [candle["close"] for candle in candles]
    last = candles[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= 205 else None
    prior_ema50 = _ema(closes[:-5], 50)
    ema50_slope_pct = ((ema50 / prior_ema50) - 1.0) * 100.0 if prior_ema50 > 0 else 0.0
    rsi = _rsi(closes)
    atr = _atr(candles)
    adx = _adx(candles)

    fast_ema = _ema(closes, 12)
    slow_ema = _ema(closes, 26)
    macd_series = []
    fast_state = slow_state = closes[0]
    for value in closes:
        fast_state = value * (2.0 / 13.0) + fast_state * (11.0 / 13.0)
        slow_state = value * (2.0 / 27.0) + slow_state * (25.0 / 27.0)
        macd_series.append(fast_state - slow_state)
    macd_signal = _ema(macd_series, 9)
    previous_signal = _ema(macd_series[:-1], 9)
    macd_hist = (fast_ema - slow_ema) - macd_signal
    previous_hist = macd_series[-2] - previous_signal if len(macd_series) > 1 else macd_hist

    previous_candles = candles[-21:-1]
    resistance = max(candle["high"] for candle in previous_candles)
    support = min(candle["low"] for candle in previous_candles)
    average_volume = sum(candle["volume"] for candle in previous_candles) / max(1, len(previous_candles))
    relative_volume = last["volume"] / average_volume if average_volume > 0 else 0.0
    change_pct = (closes[-1] / closes[-2] - 1.0) * 100.0

    bullish = last["close"] > ema20 > ema50 and ema50_slope_pct > 0
    bearish = last["close"] < ema20 < ema50 and ema50_slope_pct < 0
    if ema200 is not None:
        bullish = bullish and last["close"] > ema200
        bearish = bearish and last["close"] < ema200
    direction = "صاعد" if bullish else "هابط" if bearish else "محايد"
    candle_range = max(1e-12, last["high"] - last["low"])
    close_location = (last["close"] - last["low"]) / candle_range

    return {
        "direction": direction, "rsi": rsi, "adx": adx, "atr": atr,
        "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "ema50_slope_pct": ema50_slope_pct,
        "macd_hist": macd_hist, "previous_macd_hist": previous_hist,
        "relative_volume": relative_volume, "resistance": resistance,
        "support": support, "change_pct": change_pct,
        "close_location": close_location, "last": last
    }


def _frame_confirms(frame, side):
    """Require trend, RSI and MACD agreement on both decision timeframes."""
    if not frame:
        return False
    if side == "شراء":
        return (
            frame.get("direction") == "صاعد"
            and 50.0 <= float(frame.get("rsi", 50.0)) <= 76.0
            and float(frame.get("macd_hist", 0.0)) > 0
            and float(frame.get("ema50_slope_pct", 0.0)) > 0
            and float(frame.get("adx", 0.0)) >= 15.0
        )
    return (
        frame.get("direction") == "هابط"
        and 24.0 <= float(frame.get("rsi", 50.0)) < 50.0
        and float(frame.get("macd_hist", 0.0)) < 0
        and float(frame.get("ema50_slope_pct", 0.0)) < 0
        and float(frame.get("adx", 0.0)) >= 15.0
    )


def _evidence_score(fast, four_hour, daily, side):
    """A transparent confluence score, explicitly not a win probability."""
    score = 40.0
    for frame in (four_hour, daily):
        score += min(10.0, max(0.0, (float(frame["adx"]) - 15.0) * 0.4))
        score += 5.0
        hist = float(frame["macd_hist"])
        if (side == "شراء" and hist > float(frame.get("previous_macd_hist", 0.0))) or (
            side == "بيع" and hist < float(frame.get("previous_macd_hist", 0.0))
        ):
            score += 3.0
    rsi = float(fast["rsi"])
    if (side == "شراء" and 50 <= rsi <= 72) or (side == "بيع" and 28 <= rsi < 50):
        score += 8.0
    fast_hist = float(fast["macd_hist"])
    if (side == "شراء" and fast_hist > 0) or (side == "بيع" and fast_hist < 0):
        score += 5.0
    score += min(8.0, max(0.0, (float(fast.get("relative_volume", 0.0)) - 0.7) * 5.0))
    location = float(fast.get("close_location", 0.5))
    if (side == "شراء" and location >= 0.65) or (side == "بيع" and location <= 0.35):
        score += 5.0
    return max(0, min(100, int(round(score))))


def _analyze_symbol(market, interval, row, candle_loader):
    """4h and daily decide side; the selected timeframe ranks eligible trades and defines execution."""
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    execution_interval = interval if interval in FRAME_SECONDS else "15m"
    frames = tuple(dict.fromkeys((execution_interval, "4h", "1d")))
    analyses, candles_by_frame = {}, {}
    for frame in frames:
        try:
            candles_by_frame[frame] = _valid_candles(candle_loader(market, symbol, frame))
        except Exception:
            candles_by_frame[frame] = []
        analyses[frame] = _frame_analysis(candles_by_frame[frame]) if candles_by_frame[frame] else None
    if any(analyses.get(frame) is None for frame in frames):
        return None

    fast = analyses[execution_interval]
    four_hour, daily = analyses["4h"], analyses["1d"]
    if four_hour["direction"] == daily["direction"] == "صاعد":
        side = "شراء"
    elif four_hour["direction"] == daily["direction"] == "هابط":
        side = "بيع"
    else:
        return None
    if not _frame_confirms(four_hour, side) or not _frame_confirms(daily, side):
        return None

    entry = float(fast["last"]["close"])
    atr = float(fast["atr"])
    if not math.isfinite(entry) or entry <= 0 or not math.isfinite(atr) or atr <= 0:
        return None
    initial_risk = max(atr * 1.5, entry * 0.002)
    recent_swing = candles_by_frame[execution_interval][-12:]
    if side == "شراء":
        stop = min(entry - initial_risk, min(candle["low"] for candle in recent_swing) - atr * 0.15)
        risk = entry - stop
        tp1, tp2, tp3 = entry + risk, entry + 2 * risk, entry + 3 * risk
    else:
        stop = max(entry + initial_risk, max(candle["high"] for candle in recent_swing) + atr * 0.15)
        risk = stop - entry
        tp1, tp2, tp3 = entry - risk, entry - 2 * risk, entry - 3 * risk
    if risk <= 0 or risk / entry > RISK_CAP[execution_interval] or tp3 <= 0:
        return None

    score = _evidence_score(fast, four_hour, daily, side)
    strong = (
        score >= 82
        and float(four_hour["adx"]) >= 25
        and float(daily["adx"]) >= 25
    )
    label = ("شراء قوي" if strong else "شراء") if side == "شراء" else ("بيع قوي" if strong else "بيع")
    now = int(time.time())
    digits = 10 if entry < .001 else 8 if entry < 1 else 5 if entry < 100 else 3 if entry < 10000 else 2
    changes = {frame: round(float(analyses[frame]["change_pct"]), 3) for frame in frames}
    profit_pct = abs(tp3 - entry) / entry * 100.0
    loss_pct = abs(stop - entry) / entry * 100.0
    return {
        "id": f"mft-v3-{market}-{symbol}-{now}", "symbol": symbol,
        "direction": side, "signal_label": label, "title": f"{label} {symbol}",
        "description": f"اتجاه 4 ساعات واليومي يحدد القرار؛ فريم التنفيذ والترتيب {execution_interval} مع تأكيد RSI وMACD وADX.",
        "source": "محرك فني متعدد العوامل v3",
        "url": "", "published_at": now, "created_at": now, "age_hours": 0,
        "market": market, "interval": execution_interval,
        "expires_at": now + FRAME_SECONDS[execution_interval],
        "valid_for_seconds": FRAME_SECONDS[execution_interval],
        "price_updated_at": now, "price_fresh": True,
        "freshness_label": f"آخر إغلاق شمعة {execution_interval}",
        "live_price": round(float(row.get("price") or entry), digits),
        "levels": {"entry": round(entry, digits), "stop_loss": round(stop, digits),
                   "tp1": round(tp1, digits), "tp2": round(tp2, digits), "tp3": round(tp3, digits)},
        "ai_score": score, "combined_score": score, "method_score": score,
        "strength_score": score, "score_type": "درجة جودة الأدلة من 100 وليست نسبة نجاح",
        "ai_reviewed": False, "generated_by_ai": False,
        "timeframes_aligned": 2,
        "timeframe_trends": {frame: analyses[frame]["direction"] for frame in frames},
        "timeframe_signals": {
            "4h": "شراء قوي" if side == "شراء" and four_hour["adx"] >= 25 else
                  "شراء" if side == "شراء" else
                  "بيع قوي" if four_hour["adx"] >= 25 else "بيع",
            "1d": "شراء قوي" if side == "شراء" and daily["adx"] >= 25 else
                  "شراء" if side == "شراء" else
                  "بيع قوي" if daily["adx"] >= 25 else "بيع"
        },
        "timeframe_change_pct": changes,
        "change_interval_pct": changes[execution_interval],
        "change_15m_pct": changes.get("15m", 0.0),
        "timeframe_alignment_label": "4 ساعات + يومي متفقان",
        "trend_strength": score,
        "potential_profit_pct": round(profit_pct, 2),
        "potential_loss_pct": round(loss_pct, 2),
        "tp1_profit_pct": round(abs(tp1 - entry) / entry * 100, 2),
        "tp2_profit_pct": round(abs(tp2 - entry) / entry * 100, 2),
        "tp3_profit_pct": round(profit_pct, 2),
        "risk_reward_tp3": round(profit_pct / loss_pct, 2) if loss_pct else None,
        "external_source_weight": 0, "site_analysis_weight": 100,
        "has_complete_levels": True,
        "level_source_note": f"الدخول من إغلاق شمعة {execution_interval}؛ الوقف حسب ATR وبنية آخر 12 شمعة؛ الأهداف 1:1 و1:2 و1:3.",
        "method": "multi_factor_4h_1d_selected_interval_v3"
    }


def generate_signals(market, interval, market_rows, limit, candle_loader):
    """Scan a bounded rotating batch and rank by the selected execution timeframe."""
    unique = {}
    for row in market_rows if isinstance(market_rows, list) else []:
        if isinstance(row, dict) and row.get("symbol"):
            unique.setdefault(str(row["symbol"]).upper(), row)

    def priority(row):
        try:
            volume = float(row.get("quote_volume") or row.get("dollar_volume") or row.get("volume") or 0)
            change = abs(float(row.get("change_pct") or 0))
            return (math.log10(1.0 + max(0.0, volume)) * (1.0 + min(change, 25.0) / 25.0), change)
        except (TypeError, ValueError, OverflowError):
            return (0.0, 0.0)

    ranked = sorted(unique.values(), key=priority, reverse=True)
    batch_size = min(12, max(8, limit))
    if len(ranked) <= batch_size:
        candidates = ranked
    else:
        with _SCAN_CURSOR_LOCK:
            cursor_key = (market, interval)
            offset = _SCAN_CURSORS.get(cursor_key, 0) % len(ranked)
            candidates = ranked[offset:offset + batch_size]
            if len(candidates) < batch_size:
                candidates.extend(ranked[:batch_size - len(candidates)])
            _SCAN_CURSORS[cursor_key] = (offset + batch_size) % len(ranked)

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(_analyze_symbol, market, interval, row, candle_loader) for row in candidates]
        for job in as_completed(jobs):
            try:
                item = job.result()
                if item:
                    results.append(item)
            except Exception:
                continue

    results.sort(key=lambda item: (
        0 if item["direction"] == "شراء" else 1,
        -float(item.get("change_interval_pct", 0.0)) if item["direction"] == "شراء"
        else float(item.get("change_interval_pct", 0.0))
    ))
    return results[:limit], True, (
        f"تم فحص توافق 4 ساعات واليومي؛ التنفيذ والترتيب حسب تغير {interval}."
        if results else f"لا توجد فرصة اجتازت شروط توافق 4 ساعات واليومي والزخم وإدارة المخاطر على فريم {interval} حاليًا."
    )

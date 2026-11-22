"""STP AI Market Analyst: OpenAI Responses API, real market data, and paper-only trade publication."""
from __future__ import annotations

import json
import math
import os
import re
from datetime import timedelta
from flask import Blueprint, jsonify, request, send_from_directory

MODEL_DEFAULT = "gpt-6.2-astra"
FRAMES = ("15m", "1h", "4h", "1d", "1w", "1M")
MARKETS = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
TRADE_PREFIX = "STP AI ANALYST:"
SYSTEM_RULES = """أنت محلل أسواق محترف داخل SMART TRADING PRO. حلل الأدلة فقط ولا تخترع سعراً أو حجماً أو خبراً.
استخدم بيانات OHLCV المرفقة فقط. قارن الفريمات الستة، بنية القمم والقيعان، الزخم، التذبذب، الحجم، مناطق السيولة، الاختراقات الكاذبة، والدعم والمقاومة.
افحص سيناريو BUY وSELL وWAIT؛ لا تجبر صفقة. إذا كانت البيانات ناقصة أو متضاربة أو متأخرة فاختر WAIT.
لا تعتبر confidence احتمال ربح أو نسبة نجاح؛ هو تقييم جودة الأدلة فقط. لا تضمن الأرباح.
لإصدار صفقة BUY يجب أن يكون stop أقل من entry، وللبيع stop أعلى من entry. اذكر سبب الدخول والإبطال والمخاطر بوضوح.
أجب بالعربية السعودية الواضحة. في تحليل الصفقة أعد JSON مطابقاً للمخطط المطلوب فقط."""
ANALYSIS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["BUY", "SELL", "WAIT"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "entry": {"type": ["number", "null"]},
        "stop": {"type": ["number", "null"]},
        "thesis": {"type": "string"},
        "confirmation": {"type": "string"},
        "invalidation": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "wait_reason": {"type": "string"}
    },
    "required": ["action", "confidence", "entry", "stop", "thesis", "confirmation", "invalidation", "risks", "wait_reason"]
}

def _extract_text(payload):
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    return "\n".join(chunks)

def _call_openai(input_text, *, structured=False, instructions=None, schema=None, schema_name="stp_market_analysis"):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY_MISSING")
    model = os.environ.get("OPENAI_MODEL", MODEL_DEFAULT).strip() or MODEL_DEFAULT
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "max").strip()
    body = {
        "model": model,
        "instructions": instructions or SYSTEM_RULES,
        "input": input_text,
        "reasoning": {"effort": effort},
        "max_output_tokens": int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "5000")),
        "store": False
    }
    if structured:
        body["text"] = {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema or ANALYSIS_SCHEMA}}
    import requests
    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        json=body, timeout=(10, 180)
    )
    if response.status_code >= 400:
        try:
            detail = (response.json().get("error") or {}).get("message", "OpenAI API request failed")
        except Exception:
            detail = "OpenAI API request failed"
        raise RuntimeError("OPENAI_API_ERROR: " + str(detail)[:500])
    payload = response.json()
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("OPENAI_EMPTY_RESPONSE")
    return text, model, payload.get("usage") or {}

def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False

def _bar_summary(rows):
    parsed = []
    for row in rows or []:
        try:
            if len(row) < 6:
                continue
            stamp, op, hi, lo, close, volume = int(row[0]), *[float(x) for x in row[1:6]]
            if not all(math.isfinite(x) for x in (op, hi, lo, close, volume)) or min(op, hi, lo, close) <= 0 or hi < lo:
                continue
            parsed.append({"t": stamp, "o": op, "h": hi, "l": lo, "c": close, "v": max(0, volume)})
        except (TypeError, ValueError, OverflowError):
            continue
    if len(parsed) < 25:
        raise ValueError("بيانات الشموع غير كافية على أحد الفريمات")
    closes = [x["c"] for x in parsed]
    latest = parsed[-1]
    previous = parsed[-2]
    changes = {}
    for period in (5, 20):
        changes[str(period)] = round((latest["c"] / parsed[-period-1]["c"] - 1) * 100, 4)
    recent = parsed[-20:]
    return {
        "bars": parsed[-45:],
        "last_close": latest["c"],
        "last_closed_candle_utc_ms": latest["t"],
        "change_pct_5": changes["5"],
        "change_pct_20": changes["20"],
        "range_high_20": max(x["h"] for x in recent),
        "range_low_20": min(x["l"] for x in recent),
        "volume_last_vs_20_avg": round(latest["v"] / (sum(x["v"] for x in parsed[-21:-1]) / 20), 3) if sum(x["v"] for x in parsed[-21:-1]) > 0 else None,
        "last_candle_direction": "bullish" if latest["c"] > latest["o"] else "bearish" if latest["c"] < latest["o"] else "neutral",
        "previous_close": previous["c"]
    }

def register_ai_routes(core):
    bp = Blueprint("stp_ai_analyst", __name__)

    @bp.get("/ai-analyst")
    def ai_page():
        return send_from_directory(core.APP_DIR, "ai-analyst.html")

    @bp.get("/ai-analyst.js")
    def ai_script():
        return send_from_directory(core.APP_DIR, "ai-analyst.js")

    @bp.get("/ai-analyst.css")
    def ai_styles():
        return send_from_directory(core.APP_DIR, "ai-analyst.css")

    @bp.get("/api/ai-analyst/status")
    def ai_status():
        return jsonify({
            "ok": True,
            "configured": bool(os.environ.get("OPENAI_API_KEY")),
            "model": os.environ.get("OPENAI_MODEL", MODEL_DEFAULT),
            "reasoning_effort": os.environ.get("OPENAI_REASONING_EFFORT", "max"),
            "markets": list(MARKETS), "timeframes": list(FRAMES),
            "paper_only": True, "auto_execution": False,
            "authenticated": bool(core.g.user), "csrf_token": core.csrf_token()
        })

    @bp.post("/api/ai-analyst/chat")
    @core.login_required
    @core.limiter.limit("12 per hour")
    def ai_chat():
        body = request.get_json(silent=True) or {}
        message = str(body.get("message") or "").strip()
        if not message or len(message) > 4000:
            return core.json_error("اكتب سؤالك بحد أقصى 4000 حرف", 400)
        history = body.get("history") if isinstance(body.get("history"), list) else []
        safe_history = []
        for item in history[-8:]:
            if not isinstance(item, dict) or item.get("role") not in ("user", "assistant"):
                continue
            content = str(item.get("content") or "")[:2500]
            if content:
                safe_history.append({"role": item["role"], "content": content})
        market = str(body.get("market") or "").strip().lower()
        symbol = str(body.get("symbol") or "").strip().upper()
        timeframe = str(body.get("timeframe") or "15m").strip()
        context = {"market": market or None, "symbol": symbol or None, "timeframe": timeframe}
        if symbol:
            if market not in MARKETS or timeframe not in FRAMES or not re.fullmatch(r"[A-Z0-9._=:-]{2,40}", symbol):
                return core.json_error("بيانات السوق أو الرمز غير صالحة", 400)
            if symbol not in core.market_symbols(market):
                return core.json_error("الرمز غير موجود ضمن رموز هذا السوق", 404)
            frames = {}
            for frame in FRAMES:
                raw = core.klines(market, symbol, frame, 100)
                closed = raw[:-1] if isinstance(raw, list) and len(raw) > 1 else []
                frames[frame] = _bar_summary(closed)
            context["real_market_data"] = {"as_of_utc": core.iso(core.utcnow()), "frames": frames}
        else:
            context["real_market_data"] = "لم يحدد المستخدم رمزاً؛ لا تفترض أسعاراً أو بيانات مباشرة."
        prompt = "سياق الجلسة وبيانات السوق: " + json.dumps(context, ensure_ascii=False) + "\\nالمحادثة السابقة: " + json.dumps(safe_history, ensure_ascii=False) + "\\nسؤال المستخدم: " + message
        try:
            answer, model, usage = _call_openai(prompt)
            return jsonify({"ok": True, "answer": answer, "model": model, "usage": usage})
        except RuntimeError as exc:
            msg = str(exc)
            if msg == "OPENAI_API_KEY_MISSING":
                return core.json_error("المحلل غير مفعّل بعد: أضف OPENAI_API_KEY في أسرار Northflank.", 503)
            return core.json_error(msg.replace("OPENAI_API_ERROR: ", ""), 502)
        except Exception:
            core.app.logger.exception("AI analyst chat failed")
            return core.json_error("تعذر الاتصال بمحلل الذكاء الاصطناعي حالياً", 502)

    @bp.post("/api/ai-analyst/analyze")
    @core.login_required
    @core.limiter.limit("8 per hour")
    def ai_analyze():
        body = request.get_json(silent=True) or {}
        market = str(body.get("market") or "").strip().lower()
        symbol = str(body.get("symbol") or "").strip().upper()
        timeframe = str(body.get("timeframe") or "15m").strip()
        if market not in MARKETS or timeframe not in FRAMES or not re.fullmatch(r"[A-Z0-9._=:-]{2,40}", symbol):
            return core.json_error("السوق أو الرمز أو الفريم غير صالح", 400)
        try:
            allowed = core.market_symbols(market)
            if symbol not in allowed:
                return core.json_error("الرمز غير موجود ضمن رموز هذا السوق", 404)
            frames = {}
            for frame in FRAMES:
                raw = core.klines(market, symbol, frame, 100)
                # Exclude the newest candle because it may still be forming.
                closed = raw[:-1] if isinstance(raw, list) and len(raw) > 1 else []
                frames[frame] = _bar_summary(closed)
            snapshot = core.read_market_snapshot(market) or {}
            prompt_data = {
                "task": "حلل الرمز عبر كل الفريمات، ثم اتخذ قراراً للفريم المطلوب فقط.",
                "market": market, "symbol": symbol, "requested_timeframe": timeframe,
                "analysis_time_utc": core.iso(core.utcnow()),
                "market_breadth_snapshot": {
                    "direction": snapshot.get("direction"), "up": snapshot.get("up"),
                    "down": snapshot.get("down"), "total": snapshot.get("total"),
                    "updated_at": snapshot.get("updated_at"), "stale": snapshot.get("stale")
                },
                "frames": frames,
                "rules": [
                    "لا تستخدم أي سعر غير موجود في البيانات.",
                    "إذا كان التوافق بين الفريمات ضعيفاً اختر WAIT.",
                    "لا تصدر صفقة متأخرة؛ يجب أن يكون الدخول قريباً من آخر إغلاق على الفريم المطلوب.",
                    "إذا اخترت BUY يجب أن يكون وقف الخسارة أسفل الدخول، وإذا SELL فوقه."
                ]
            }
            raw_answer, model, usage = _call_openai(json.dumps(prompt_data, ensure_ascii=False), structured=True)
            try:
                analysis = json.loads(raw_answer)
            except ValueError:
                raise RuntimeError("تعذر قراءة نتيجة التحليل المنظم")
            action = analysis.get("action")
            if market == "spot" and action == "SELL":
                action = "WAIT"
                analysis["action"] = "WAIT"
                analysis["wait_reason"] = "السوق الفوري لا يدعم البيع على المكشوف؛ لا توجد صفقة بيع هنا."
            entry = analysis.get("entry")
            stop = analysis.get("stop")
            paper_trade = None
            if action in ("BUY", "SELL"):
                if not (_finite(entry) and _finite(stop)):
                    return core.json_error("رفضت المنصة الصفقة لأن مستويات الدخول أو الوقف غير صالحة", 422)
                entry, stop = float(entry), float(stop)
                last_close = float(frames[timeframe]["last_close"])
                if entry <= 0 or stop <= 0 or abs(entry / last_close - 1) > 0.02:
                    return core.json_error("رفضت المنصة الصفقة لأن الدخول بعيد عن السعر الفعلي أو غير صالح", 422)
                valid = stop < entry if action == "BUY" else stop > entry
                risk = abs(entry - stop)
                if not valid or risk / entry > 0.10 or risk / entry < 0.0002:
                    return core.json_error("رفضت المنصة الصفقة لأن وقف الخسارة غير منطقي بالنسبة للسعر", 422)
                sign = 1 if action == "BUY" else -1
                targets = [entry + sign * risk * multiple for multiple in (1, 2, 3)]
                duplicate = core.Trade.query.filter(
                    core.Trade.market == market, core.Trade.symbol == symbol,
                    core.Trade.timeframe == timeframe,
                    core.Trade.status.in_(core.OPEN_TRADE_STATUSES),
                    core.Trade.reason.like(TRADE_PREFIX + "%"),
                    core.Trade.expires_at > core.utcnow()
                ).order_by(core.Trade.created_at.desc()).first()
                if duplicate:
                    paper_trade = core.trade_json(duplicate)
                else:
                    reason = (TRADE_PREFIX + " " + str(analysis.get("thesis") or "") +
                              " | تأكيد: " + str(analysis.get("confirmation") or "") +
                              " | إبطال: " + str(analysis.get("invalidation") or "") +
                              " | مخاطر: " + "، ".join(analysis.get("risks") or []))[:2000]
                    trade = core.Trade(
                        market=market, symbol=symbol, side=action, entry=entry, stop=stop,
                        tp1=targets[0], tp2=targets[1], tp3=targets[2],
                        score=float(max(0, min(100, int(analysis.get("confidence") or 0)))),
                        timeframe=timeframe, reason=reason,
                        expires_at=core.utcnow() + timedelta(hours=24)
                    )
                    core.db.session.add(trade)
                    core.db.session.commit()
                    paper_trade = core.trade_json(trade)
            return jsonify({
                "ok": True, "analysis": analysis, "market": market, "symbol": symbol,
                "timeframe": timeframe, "model": model, "usage": usage,
                "paper_trade": paper_trade, "paper_only": True, "frames_analyzed": list(FRAMES)
            })
        except RuntimeError as exc:
            msg = str(exc)
            if msg == "OPENAI_API_KEY_MISSING":
                return core.json_error("المحلل غير مفعّل بعد: أضف OPENAI_API_KEY في أسرار Northflank.", 503)
            return core.json_error(msg.replace("OPENAI_API_ERROR: ", ""), 502)
        except ValueError as exc:
            return core.json_error(str(exc), 422)
        except Exception:
            core.app.logger.exception("AI market analysis failed: %s %s %s", market, symbol, timeframe)
            return core.json_error("تعذر إكمال التحليل بسبب مشكلة في مصدر البيانات أو المحلل", 502)

    core.app.register_blueprint(bp)

"""Bounded 24/7 STP site autopilot: original trading content, AI paper reviews, health and audit trail."""
from __future__ import annotations

import json
import os
import re
import hashlib
from datetime import timedelta
from flask import Blueprint, jsonify, request, send_from_directory

import ai_market_analyst as ai

def install(core):
    class AutopilotRun(core.db.Model):
        __tablename__ = "autopilot_runs"
        id = core.db.Column(core.db.Integer, primary_key=True)
        job = core.db.Column(core.db.String(60), nullable=False, index=True)
        status = core.db.Column(core.db.String(20), nullable=False, index=True)
        summary = core.db.Column(core.db.String(500), nullable=False, default="")
        details = core.db.Column(core.db.Text, nullable=False, default="{}")
        tokens = core.db.Column(core.db.Integer, nullable=False, default=0)
        created_at = core.db.Column(core.db.DateTime, nullable=False, default=core.utcnow, index=True)

    with core.app.app_context():
        core.db.create_all()

    def log_run(job, status, summary, details=None, tokens=0):
        row = AutopilotRun(job=job, status=status, summary=str(summary)[:500],
                           details=json.dumps(details or {}, ensure_ascii=False)[:12000],
                           tokens=max(0, int(tokens or 0)))
        core.db.session.add(row)
        core.db.session.commit()
        return row

    def daily_usage():
        start = core.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = AutopilotRun.query.filter(AutopilotRun.created_at >= start).all()
        return sum(x.tokens for x in rows), sum(1 for x in rows if x.job == "ai_market_review" and x.status == "success")

    def within_budget():
        tokens, scans = daily_usage()
        return (scans < int(os.getenv("AI_AUTOPILOT_MAX_ANALYSES_PER_DAY", "14"))
                and tokens < int(os.getenv("AI_AUTOPILOT_DAILY_TOKEN_LIMIT", "120000")))

    ARTICLE_SCHEMA = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "title": {"type": "string"}, "summary": {"type": "string"},
            "body": {"type": "string"}, "meta_title": {"type": "string"},
            "meta_description": {"type": "string"}
        },
        "required": ["title", "summary", "body", "meta_title", "meta_description"]
    }
    ARTICLE_INSTRUCTIONS = """أنت رئيس تحرير مالي لمنصة تداول عربية. اكتب محتوى عربياً أصلياً مفيداً للمتداولين، لا تنسخ عناوين الأخبار ولا تخترع أحداثاً أو أسعاراً أو أرقاماً. استخدم فقط الوقائع الموجودة في المواد المقدمة، وافصل بوضوح بين الخبر والرأي التعليمي. لا تعط وعود أرباح ولا توصيات شخصية. إذا كانت المصادر لا تكفي لمقال إخباري، ارفض ولا تنشر. المقال منظم بعناوين قصيرة وفقرات مفهومة، بين 500 و800 كلمة للمقال التعليمي و250 إلى 450 كلمة للملخص الإخباري. لا تذكر أنك ذكاء اصطناعي."""

    def create_article(kind, payload, topic_key):
        existing = core.Article.query.filter_by(kind=kind, canonical_slug=topic_key).first()
        if existing:
            return None
        text, model, usage = ai._call_openai(
            json.dumps(payload, ensure_ascii=False),
            structured=True, instructions=ARTICLE_INSTRUCTIONS,
            schema=ARTICLE_SCHEMA, schema_name="stp_trading_article"
        )
        item = json.loads(text)
        title = str(item.get("title") or "").strip()[:220]
        body = str(item.get("body") or "").strip()
        if kind == "news":
            refs = payload.get("headlines") or []
            source_lines = ["مصادر الخبر للتحقق والمتابعة:"] + [str(x.get("publisher") or "مصدر") + " — " + str(x.get("source_url") or "") for x in refs[:8] if str(x.get("source_url") or "").startswith("https://")]
            body += "\n\n" + "\n".join(source_lines)
        summary = str(item.get("summary") or "").strip()[:500]
        if len(title) < 12 or len(body) < 700 or len(summary) < 40:
            raise ValueError("المقال المولّد لم يجتز حد الجودة والطول")
        base = re.sub(r"[^a-z0-9\u0600-\u06ff]+", "-", title.lower()).strip("-")[:180] or hashlib.sha256(topic_key.encode()).hexdigest()[:16]
        slug = base
        if core.Article.query.filter_by(slug=slug).first():
            slug = base + "-" + hashlib.sha256(topic_key.encode()).hexdigest()[:8]
        row = core.Article(
            kind=kind, title=title, slug=slug, summary=summary, body=body,
            published=True, language="ar",
            meta_title=str(item.get("meta_title") or title)[:70],
            meta_description=str(item.get("meta_description") or summary)[:170],
            canonical_slug=topic_key[:240]
        )
        core.db.session.add(row)
        core.db.session.commit()
        return {"id": row.id, "title": row.title, "slug": row.slug, "model": model,
                "tokens": int((usage or {}).get("total_tokens") or 0)}

    def daily_editorial():
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("مفتاح OpenAI غير مضاف")
        day = core.utcnow().date().isoformat()
        feeds = core._cached_google_news("ar", int(core.time.time() // 1800))[:18]
        if not feeds:
            raise RuntimeError("لم تصل أخبار تداول موثوقة؛ لم يتم إنشاء مقال")
        payload = {
            "task": "أنشئ مقالاً تعليمياً أصلياً مرتبطاً بموضوع تداول متكرر في الأخبار، مع تجنب ادعاء أن حدثاً ما وقع إن لم تثبته المصادر.",
            "date_utc": day,
            "headlines": [{"title": x.get("title"), "publisher": x.get("source"),
                           "published_at": x.get("published_at"), "source_url": x.get("link")}
                          for x in feeds[:12]]
        }
        result = create_article("blog", payload, "daily-editorial-" + day)
        if not result:
            return log_run("daily_editorial", "skipped", "مقال اليوم موجود مسبقاً")
        return log_run("daily_editorial", "success", "نُشر مقال تداول جديد", result, result["tokens"])

    def news_digest():
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("مفتاح OpenAI غير مضاف")
        day = core.utcnow().date().isoformat()
        feeds = core._cached_google_news("ar", int(core.time.time() // 900))[:20]
        if len(feeds) < 3:
            raise RuntimeError("عدد الأخبار الحديثة غير كافٍ للنشر")
        fingerprint = hashlib.sha256("|".join(sorted(str(x.get("title","")) for x in feeds[:12])).encode()).hexdigest()[:16]
        topic_key = "news-digest-" + day + "-" + fingerprint
        payload = {
            "task": "اكتب موجز أخبار تداول وأسواق من العناوين التالية فقط. لا تستنتج حركة سعر ولا تصنع أرقاماً. اشرح ما تأكد وما لا يزال مجرد عنوان، وأدرج أسماء المصادر داخل النص دون نسخ صياغة العناوين.",
            "headlines": [{"title": x.get("title"), "publisher": x.get("source"),
                           "published_at": x.get("published_at"), "source_url": x.get("link")}
                          for x in feeds[:15]]
        }
        result = create_article("news", payload, topic_key)
        if not result:
            return log_run("news_digest", "skipped", "موجز الأخبار الحالي منشور مسبقاً")
        return log_run("news_digest", "success", "نُشر موجز أخبار تداول موثق بالمصادر", result, result["tokens"])

    def ai_market_review(market):
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("مفتاح OpenAI غير مضاف")
        if not within_budget():
            return log_run("ai_market_review", "skipped", "وصل الفحص إلى حد الاستخدام اليومي", {"market": market})
        tickers = core.market_tickers(market)
        if not tickers:
            raise ValueError("لا توجد رموز متاحة من مصدر السوق")
        def rank(x):
            return float(x.get("quote_volume") or x.get("turnover") or x.get("volume") or 0)
        candidates = sorted(tickers, key=rank, reverse=True)
        candidate = candidates[0]
        symbol = str(candidate.get("symbol") or "").upper()
        if not symbol or symbol not in core.market_symbols(market):
            raise ValueError("رمز السوق غير صالح")
        frames = {}
        for frame in ai.FRAMES:
            raw = core.klines(market, symbol, frame, 100)
            frames[frame] = ai._bar_summary(raw[:-1] if isinstance(raw, list) and len(raw) > 1 else [])
        prompt = {
            "task": "مراجعة آلية مستقلة للرمز الأعلى سيولة المتاح من السوق. افحص كل الفريمات واختر قراراً واحداً للفريم 15m. لا تجبر صفقة.",
            "market": market, "symbol": symbol, "timeframe": "15m",
            "as_of_utc": core.iso(core.utcnow()),
            "ticker_context": {"last_price": candidate.get("price"), "change_pct": candidate.get("change_pct"),
                               "quote_volume": candidate.get("quote_volume")},
            "frames": frames
        }
        answer, model, usage = ai._call_openai(json.dumps(prompt, ensure_ascii=False), structured=True)
        result = json.loads(answer)
        action = result.get("action")
        if market == "spot" and action == "SELL":
            action = "WAIT"
        trade_json = None
        entry, stop = result.get("entry"), result.get("stop")
        if action in ("BUY", "SELL") and ai._finite(entry) and ai._finite(stop):
            entry, stop = float(entry), float(stop)
            last = float(frames["15m"]["last_close"])
            risk = abs(entry - stop)
            correct = stop < entry if action == "BUY" else stop > entry
            if correct and entry > 0 and stop > 0 and 0.0002 <= risk / entry <= 0.10 and abs(entry / last - 1) <= 0.02:
                reason = (ai.TRADE_PREFIX + " " + str(result.get("thesis") or "") +
                          " | تأكيد: " + str(result.get("confirmation") or "") +
                          " | إبطال: " + str(result.get("invalidation") or ""))[:1900]
                duplicate = core.Trade.query.filter(
                    core.Trade.market == market, core.Trade.symbol == symbol,
                    core.Trade.timeframe == "15m", core.Trade.reason.like(ai.TRADE_PREFIX + "%"),
                    core.Trade.status.in_(core.OPEN_TRADE_STATUSES),
                    core.Trade.expires_at > core.utcnow()
                ).first()
                if not duplicate:
                    sign = 1 if action == "BUY" else -1
                    trade = core.Trade(
                        market=market, symbol=symbol, side=action, entry=entry, stop=stop,
                        tp1=entry + sign*risk, tp2=entry + sign*risk*2, tp3=entry + sign*risk*3,
                        score=max(0, min(100, int(result.get("confidence") or 0))),
                        timeframe="15m", reason=reason, expires_at=core.utcnow()+timedelta(hours=24)
                    )
                    core.db.session.add(trade)
                    core.db.session.commit()
                    trade_json = core.trade_json(trade)
        tokens = int((usage or {}).get("total_tokens") or 0)
        return log_run("ai_market_review", "success",
                       f"{market} · {symbol} · {action}", 
                       {"market": market, "symbol": symbol, "action": action, "analysis": result,
                        "model": model, "paper_trade": trade_json}, tokens)

    def health_review():
        reports = {}
        for market in core.MARKETS:
            runtime = core.read_scan_runtime(market)
            reports[market] = {"status": runtime.get("status", "unknown"),
                               "last_at": runtime.get("last_at"), "error": runtime.get("error_code")}
        old = AutopilotRun.query.filter_by(job="health_review").order_by(AutopilotRun.created_at.desc()).first()
        summary = "فحص صحة المنصة ومصادر الأسواق اكتمل"
        return log_run("health_review", "success", summary, {"markets": reports})

    def safe_job(name, fn, *args):
        with core.app.app_context():
            try:
                fn(*args)
            except Exception as exc:
                core.db.session.rollback()
                core.app.logger.exception("STP autopilot job failed: %s", name)
                try:
                    log_run(name, "error", str(exc)[:450])
                except Exception:
                    core.db.session.rollback()
            finally:
                core.db.session.remove()

    bp = Blueprint("stp_autopilot", __name__)

    @bp.get("/autopilot")
    @core.login_required
    @core.admin_required
    def page():
        return send_from_directory(core.APP_DIR, "autopilot.html")

    @bp.get("/autopilot.js")
    @core.login_required
    @core.admin_required
    def script():
        return send_from_directory(core.APP_DIR, "autopilot.js")

    @bp.get("/autopilot.css")
    @core.login_required
    @core.admin_required
    def styles():
        return send_from_directory(core.APP_DIR, "autopilot.css")

    @bp.get("/api/autopilot/status")
    @core.login_required
    @core.admin_required
    def status():
        tokens, scans = daily_usage()
        scheduler = core.scheduler
        jobs = [{"id": x.id, "next_run": core.iso(x.next_run_time) if x.next_run_time else None}
                for x in scheduler.get_jobs()] if scheduler and scheduler.running else []
        return jsonify({"ok": True, "enabled": bool(scheduler and scheduler.running),
                        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
                        "model": os.getenv("OPENAI_MODEL", ai.MODEL_DEFAULT),
                        "daily_tokens": tokens, "daily_analyses": scans,
                        "daily_token_limit": int(os.getenv("AI_AUTOPILOT_DAILY_TOKEN_LIMIT", "120000")),
                        "daily_analysis_limit": int(os.getenv("AI_AUTOPILOT_MAX_ANALYSES_PER_DAY", "14")),
                        "jobs": jobs, "csrf_token": core.csrf_token()})

    @bp.get("/api/autopilot/runs")
    @core.login_required
    @core.admin_required
    def runs():
        rows = AutopilotRun.query.order_by(AutopilotRun.created_at.desc()).limit(60).all()
        return jsonify({"ok": True, "runs": [{"id": x.id, "job": x.job, "status": x.status,
            "summary": x.summary, "details": json.loads(x.details or "{}"),
            "tokens": x.tokens, "created_at": core.iso(x.created_at)} for x in rows]})

    @bp.post("/api/autopilot/run/<job>")
    @core.login_required
    @core.admin_required
    @core.limiter.limit("4 per hour")
    def run_now(job):
        jobs = {"editorial": daily_editorial, "news": news_digest, "health": health_review}
        if job not in jobs:
            return core.json_error("المهمة غير معروفة", 404)
        safe_job({"editorial":"daily_editorial","news":"news_digest","health":"health_review"}[job], jobs[job])
        return jsonify({"ok": True, "message": "تم تشغيل المهمة؛ راجع سجل التنفيذ"})

    core.app.register_blueprint(bp)

    scheduler = core.scheduler
    if scheduler and scheduler.running:
        existing = {x.id for x in scheduler.get_jobs()}
        if "stp-autopilot-editorial" not in existing:
            scheduler.add_job(lambda: safe_job("daily_editorial", daily_editorial), "cron",
                              hour=9, minute=0, id="stp-autopilot-editorial",
                              max_instances=1, coalesce=True, misfire_grace_time=3600)
        if "stp-autopilot-news" not in existing:
            scheduler.add_job(lambda: safe_job("news_digest", news_digest), "cron",
                              hour=13, minute=0, id="stp-autopilot-news",
                              max_instances=1, coalesce=True, misfire_grace_time=3600)
        if "stp-autopilot-health" not in existing:
            scheduler.add_job(lambda: safe_job("health_review", health_review), "interval",
                              hours=1, id="stp-autopilot-health",
                              max_instances=1, coalesce=True, misfire_grace_time=300)
        for index, market in enumerate(ai.MARKETS):
            job_id = "stp-autopilot-ai-" + market
            if job_id not in existing:
                scheduler.add_job(safe_job, "interval", hours=12, id=job_id,
                                  args=["ai_market_review", ai_market_review, market],
                                  next_run_time=core.utcnow()+timedelta(minutes=5+index*4),
                                  max_instances=1, coalesce=True, misfire_grace_time=1800)

    return {"AutopilotRun": AutopilotRun}

"""Production strategy compatibility layer.

Keeps the existing server intact while enforcing the requested inverse strategy
at the final AI-provider boundary. Local rule-based analysis is already inverted
inside server.py, so only model-returned directions are inverted here.
"""
import json
import logging
import time

log = logging.getLogger("mudarib.strategy_patch")


def _flip_trade(item):
    if not isinstance(item, dict):
        return item
    d = item.get("direction")
    if d not in ("شراء", "بيع"):
        return item

    x = dict(item)
    entry = float(x.get("entry") or 0)
    if entry <= 0:
        return x

    old_sl = float(x.get("sl") or 0)
    old_tps = [float(x.get(k) or 0) for k in ("tp1", "tp2", "tp3")]

    # Preserve the exact risk distances, but mirror the trade around entry.
    # BUY -> SELL: old downside stop becomes the mirrored upside stop.
    # SELL -> BUY: old upside stop becomes the mirrored downside stop.
    risk = abs(entry - old_sl) if old_sl > 0 else 0.0
    distances = sorted(
        [abs(tp - entry) for tp in old_tps if tp > 0 and abs(tp - entry) > 0],
        reverse=False,
    )

    x["direction"] = "بيع" if d == "شراء" else "شراء"
    if x.get("signal"):
        x["signal"] = (
            "بيع قوي" if x["direction"] == "بيع" and float(x.get("confidence") or 0) >= 80
            else "شراء قوي" if x["direction"] == "شراء" and float(x.get("confidence") or 0) >= 80
            else x["direction"]
        )

    if risk > 0:
        if x["direction"] == "شراء":
            x["sl"] = entry - risk
            for k, dist in zip(("tp1", "tp2", "tp3"), distances):
                x[k] = entry + dist
        else:
            x["sl"] = entry + risk
            for k, dist in zip(("tp1", "tp2", "tp3"), distances):
                x[k] = entry - dist

    x["trade_ready"] = bool(x.get("trade_ready", x.get("tradeReady", False)))
    if "tradeReady" in x:
        x["tradeReady"] = x["trade_ready"]
    x["inverseStrategy"] = True
    x["strategyNote"] = "تم عكس إشارة التحليل: شراء ← بيع، بيع ← شراء"
    return x


def install(server):
    # Prevent old cached non-inverted signals from leaking into the website
    # after deployment. New scans rebuild the shared cache through server.ai_batch.
    try:
        c = server.conn()
        c.execute("DELETE FROM signal_cache")
        c.execute("DELETE FROM strong_signal_cache")
        c.commit()
        c.close()
        server.AI_CACHE.clear()
        server.SCAN_CACHE.clear()
        log.info("Inverse strategy: stale signal caches cleared")
    except Exception:
        log.exception("Inverse strategy cache reset failed")

    original_ai_json = server._ai_json

    def inverse_ai_json(prompt):
        result = original_ai_json(prompt)
        if not isinstance(result, dict):
            return result
        rows = result.get("items")
        if not isinstance(rows, list):
            return result
        result = dict(result)
        result["items"] = [_flip_trade(x) for x in rows]
        return result

    server._ai_json = inverse_ai_json

    # Expose an explicit status endpoint so the frontend and monitoring can
    # verify which strategy is active without guessing from a signal.
    @server.app.get("/api/strategy")
    def strategy_status():
        return server.ok(
            mode="inverse",
            buy_becomes="بيع",
            sell_becomes="شراء",
            levels="mirrored_around_entry",
            connected=True,
            updatedAt=server.datetime.now(server.timezone.utc).isoformat(),
        )

    log.info("Inverse strategy layer installed successfully")
    return server.app


app = install(__import__("server"))

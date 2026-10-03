import sys
import threading
import time
from datetime import datetime, timezone

def _auto_paper_futures():
    # تشغيل محرك المحاكاة تلقائياً بعد اكتمال تحميل app.
    mod = None
    for _ in range(1200):
        mod = sys.modules.get("app")
        if mod is not None and hasattr(mod, "app") and hasattr(mod, "_futures_bot_tick") and hasattr(mod, "_futures_bot_start_paper"):
            break
        time.sleep(0.25)
    else:
        print("[AUTO-FUTURES] app was not ready after 300s", flush=True)
        return

    try:
        mod.init_db()
    except Exception as exc:
        print(f"[AUTO-FUTURES] init_db failed: {type(exc).__name__}: {exc}", flush=True)

    try:
        import strategy_override
        strategy_override.apply(mod)
        print("[AUTO-FUTURES] strategy override applied", flush=True)
    except Exception as exc:
        print(f"[AUTO-FUTURES] strategy override failed: {type(exc).__name__}: {exc}", flush=True)

    print("[AUTO-FUTURES] worker started; PAPER mode only", flush=True)

    while True:
        try:
            state = mod._futures_bot_tick()
            status = str(state.get("status") or "idle")
            symbol = str(state.get("symbol") or "")
            print(f"[AUTO-FUTURES] tick status={status} symbol={symbol}", flush=True)

            if status == "open":
                entry = float(state.get("entry") or 0)
                px = float(state.get("last_price") or 0)
                side = str(state.get("side") or "BUY").upper()
                if entry > 0 and px > 0:
                    profit = ((px - entry) / entry * 100) if side == "BUY" else ((entry - px) / entry * 100)
                    if profit >= 10.0:
                        now = datetime.now(timezone.utc).isoformat()
                        mod._futures_bot_write({
                            "status": "closed", "enabled": 0, "auto_enabled": 1,
                            "closed_at": now, "outcome": "win",
                            "realized_pct": profit, "last_price": px,
                            "last_checked_at": now
                        })
                        print(f"[AUTO-FUTURES] PAPER closed TP symbol={symbol} profit={profit:.2f}%", flush=True)
            else:
                timeframe = str(state.get("timeframe") or "15m")
                result = mod._futures_bot_start_paper(timeframe, auto_enable=True)
                bot = result.get("bot") or {}
                print(
                    f"[AUTO-FUTURES] prepare ok={result.get('ok')} "
                    f"status={bot.get('status')} symbol={bot.get('symbol')} "
                    f"message={result.get('message')}",
                    flush=True
                )
                if result.get("ok") and bot.get("status") == "ready":
                    now = datetime.now(timezone.utc).isoformat()
                    mod._futures_bot_write({
                        "enabled": 1, "auto_enabled": 1, "status": "open",
                        "opened_at": now, "closed_at": None, "outcome": None,
                        "realized_pct": None, "peak_profit_pct": 0,
                        "protected_profit_pct": 0, "protection_price": None,
                        "last_price": bot.get("entry"),
                        "last_checked_at": now, "manual_confirmed": 0
                    })
                    print(
                        f"[AUTO-FUTURES] PAPER opened symbol={bot.get('symbol')} "
                        f"side={bot.get('side')} entry={bot.get('entry')}",
                        flush=True
                    )
        except Exception as exc:
            print(f"[AUTO-FUTURES] loop error: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(15)

threading.Thread(target=_auto_paper_futures, daemon=True, name="auto-paper-futures").start()

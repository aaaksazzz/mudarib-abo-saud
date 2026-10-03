import sys
import threading
import time
from datetime import datetime, timezone

def _auto_paper_futures():
    # ينتظر تحميل app ثم يشغل دورة البوت التجريبية تلقائياً.
    for _ in range(120):
        mod=sys.modules.get("app")
        if mod is not None and hasattr(mod,"app") and hasattr(mod,"_scan_spot_strategy"):
            try:
                import strategy_override
                strategy_override.apply(mod)
            except Exception:
                pass
            break
        time.sleep(0.25)
    else:
        return

    while True:
        try:
            state=mod._futures_bot_tick()

            if state.get("status")=="open":
                entry=float(state.get("entry") or 0)
                px=float(state.get("last_price") or 0)
                side=str(state.get("side") or "BUY").upper()
                if entry>0 and px>0:
                    profit=((px-entry)/entry*100) if side=="BUY" else ((entry-px)/entry*100)
                    # الهدف النهائي 10% في المحاكاة.
                    if profit>=10.0:
                        now=datetime.now(timezone.utc).isoformat()
                        mod._futures_bot_write({
                            "status":"closed","enabled":0,"auto_enabled":1,
                            "closed_at":now,"outcome":"win",
                            "realized_pct":profit,"last_price":px,
                            "last_checked_at":now
                        })
            else:
                # اختيار وتجهيز أفضل إشارة تلقائياً ثم فتحها كمركز Paper.
                result=mod._futures_bot_start_paper(
                    str(state.get("timeframe") or "15m"),
                    auto_enable=True
                )
                bot=result.get("bot") or {}
                if result.get("ok") and bot.get("status")=="ready":
                    now=datetime.now(timezone.utc).isoformat()
                    mod._futures_bot_write({
                        "enabled":1,"auto_enabled":1,"status":"open",
                        "opened_at":now,"closed_at":None,"outcome":None,
                        "realized_pct":None,"peak_profit_pct":0,
                        "protected_profit_pct":0,"protection_price":None,
                        "last_price":bot.get("entry"),
                        "last_checked_at":now,"manual_confirmed":0
                    })
        except Exception:
            pass
        time.sleep(15)

threading.Thread(target=_auto_paper_futures,daemon=True,name="auto-paper-futures").start()

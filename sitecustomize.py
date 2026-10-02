import sys
import threading
import time

def _apply():
    for _ in range(120):
        mod=sys.modules.get("app")
        if mod is not None and hasattr(mod,"app") and hasattr(mod,"_scan_spot_strategy"):
            try:
                import strategy_override
                strategy_override.apply(mod)
            except Exception:
                pass
            return
        time.sleep(0.25)

threading.Thread(target=_apply,daemon=True).start()

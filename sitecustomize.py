import sys
import time

def _apply_strategy_override():
    mod = None
    for _ in range(1200):
        mod = sys.modules.get("app")
        if mod is not None and hasattr(mod, "app"):
            break
        time.sleep(0.25)
    if mod is None:
        print("[AUTO-FUTURES] app was not ready after 300s", flush=True)
        return
    try:
        mod.init_db()
    except Exception as exc:
        print(f"[AUTO-FUTURES] init_db failed: {type(exc).__name__}: {exc}", flush=True)
    try:
        import strategy_override
        strategy_override.apply(mod)
        print("[AUTO-FUTURES] strategy override applied; real orders require manual confirmation", flush=True)
    except Exception as exc:
        print(f"[AUTO-FUTURES] strategy override failed: {type(exc).__name__}: {exc}", flush=True)

# This hook only applies strategy configuration. It never scans, opens, or submits orders.
import threading
threading.Thread(target=_apply_strategy_override, daemon=True, name="strategy-override").start()

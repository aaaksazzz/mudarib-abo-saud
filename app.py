"""Application entrypoint for Northflank/Uvicorn.

Keep the FastAPI instance in app_v2.py and load optional integrations only
after the instance exists. This avoids circular-import startup failures.
"""
import importlib

core = importlib.import_module("app_v2")
app = core.app

# Optional integrations register routes/background workers on core.app.
# A failure here must not prevent the web application itself from starting.
try:
    importlib.import_module("bot_spot")
except Exception:
    pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080)

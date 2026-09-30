"""Application entrypoint for Northflank/Uvicorn."""
import importlib

core = importlib.import_module("app_v2")
app = core.app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080)

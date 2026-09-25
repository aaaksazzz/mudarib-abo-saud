import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="المضارب ذكي", docs_url=None, redoc_url=None)

static_dir = ROOT / "static"
templates_dir = ROOT / "templates"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
templates = Jinja2Templates(directory=str(templates_dir))

@app.get("/health")
async def health():
    return {"ok": True, "service": "web", "version": "stable-rebuild"}

@app.get("/api/health")
async def api_health():
    return {"ok": True, "service": "api", "version": "stable-rebuild"}

@app.exception_handler(Exception)
async def errors(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"ok": False, "message": "حدث خطأ مؤقت في الخادم"})

PAGES = ("spot","futures","contracts","scanner","saudi","usmarket","forex","news","subscription","login","register","admin","trades")
for page in PAGES:
    async def handler(request: Request, page_id=page):
        filename = templates.env.loader.get_source(templates.env, f"{page_id}.html")[0]
        return templates.TemplateResponse(request=request, name=f"{page_id}.html", context={"page_id": page_id, "page_title": page_id})
    app.add_api_route(f"/{page}", handler, methods=["GET"], include_in_schema=False)

@app.get("/")
async def home(request: Request):
    name = "index.html"
    if (templates_dir / name).exists():
        return templates.TemplateResponse(request=request, name=name, context={"page_id":"home","page_title":"المضارب ذكي"})
    return {"ok": True, "message": "Stable rebuild is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("stable_rebuild.app.main:app", host="0.0.0.0", port=int(os.getenv("PORT","8080")))

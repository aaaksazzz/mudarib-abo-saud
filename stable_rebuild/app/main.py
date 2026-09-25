import os
import logging
import secrets
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .settings import settings
from .db import init_db
from .auth import bootstrap_admin
from .routers import api

log=logging.getLogger("mudarib-web")
ROOT=Path(__file__).resolve().parents[2]
app=FastAPI(title="المضارب ذكي",docs_url=None,redoc_url=None)
_session_secret=settings.session_secret or secrets.token_urlsafe(48)
app.add_middleware(SessionMiddleware,secret_key=_session_secret,session_cookie="mudarib_session",max_age=60*60*24*30,same_site="lax",https_only=settings.public_base_url.startswith("https://"))
static_dir=ROOT/"static";templates_dir=ROOT/"templates"
if static_dir.exists():app.mount("/static",StaticFiles(directory=str(static_dir)),name="static")
templates=Jinja2Templates(directory=str(templates_dir))
app.include_router(api)

@app.middleware("http")
async def security_headers(request:Request, call_next):
    response=await call_next(request)
    response.headers.setdefault("X-Content-Type-Options","nosniff")
    response.headers.setdefault("X-Frame-Options","DENY")
    response.headers.setdefault("Referrer-Policy","strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy","camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy","same-origin")
    if request.url.scheme=="https":
        response.headers.setdefault("Strict-Transport-Security","max-age=31536000; includeSubDomains")
    return response

@app.get("/health", include_in_schema=False)
def root_health():
    return PlainTextResponse("ok", status_code=200)

@app.get("/health/live", include_in_schema=False)
def root_health_live():
    return JSONResponse({"ok": True, "service": "web"})

@app.on_event("startup")
def startup():
    # Keep the web process alive during temporary PostgreSQL outages.
    if not settings.database_url:
        log.warning("DATABASE_URL is not configured")
        return
    try:
        init_db()
        bootstrap_admin()
    except Exception as exc:
        log.exception("PostgreSQL startup initialization failed: %s", exc)

@app.exception_handler(Exception)
async def errors(request:Request,exc:Exception):
    return JSONResponse(status_code=500,content={"ok":False,"message":"حدث خطأ مؤقت في الخادم"})

PAGES=("spot","futures","contracts","scanner","saudi","usmarket","forex","news","subscription","login","register","admin","trades","blog")
for page in PAGES:
    async def handler(request:Request,page_id=page):
        filename=f"{page_id}.html"
        if not (templates_dir/filename).exists(): return JSONResponse(status_code=404,content={"ok":False,"message":"الصفحة غير موجودة"})
        return templates.TemplateResponse(request=request,name=filename,context={"page_id":page_id,"page_title":page_id,"public_base_url":settings.public_base_url,"request":request})
    app.add_api_route(f"/{page}",handler,methods=["GET"],include_in_schema=False)

@app.get("/analysis/{market}")
async def analysis_market(market:str):
    targets={"crypto":"/spot","futures":"/futures","contracts":"/contracts","saudi":"/saudi","usmarket":"/usmarket","forex":"/forex"}
    from fastapi.responses import RedirectResponse
    target=targets.get(market)
    if not target:return JSONResponse(status_code=404,content={"ok":False,"message":"قسم التحليل غير موجود"})
    return RedirectResponse(target,status_code=307)

@app.get("/")
async def home(request:Request):
    if (templates_dir/"index.html").exists():
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"page_id":"home","page_title":"المضارب ذكي","public_base_url":settings.public_base_url,"request":request},
        )
    return JSONResponse(status_code=500,content={"ok":False,"message":"الصفحة الرئيسية غير موجودة"})


if __name__=="__main__":
    import uvicorn
    uvicorn.run("stable_rebuild.app.main:app",host="0.0.0.0",port=int(os.getenv("PORT","8080")))

@app.get("/robots.txt",include_in_schema=False)
def robots():
    return PlainTextResponse("User-agent: *\\nAllow: /\\nSitemap: "+settings.public_base_url+"/sitemap.xml")
@app.get("/sitemap.xml",include_in_schema=False)
def sitemap():
    pages=["/","/spot","/futures","/contracts","/scanner","/saudi","/usmarket","/forex","/news","/blog","/subscription"]
    body='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join("<url><loc>"+settings.public_base_url+p+"</loc></url>" for p in pages)+"</urlset>"
    return PlainTextResponse(body,media_type="application/xml")
@app.get("/news-sitemap.xml",include_in_schema=False)
def news_sitemap():
    return sitemap()

import os
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .settings import settings
from .db import init_db
from .auth import bootstrap_admin
from .routers import api

ROOT=Path(__file__).resolve().parents[2]
app=FastAPI(title="المضارب ذكي",docs_url=None,redoc_url=None)
app.add_middleware(SessionMiddleware,secret_key=settings.session_secret or "change-me",session_cookie="mudarib_session",max_age=60*60*24*30,same_site="lax",https_only=False)
static_dir=ROOT/"static";templates_dir=ROOT/"templates"
if static_dir.exists():app.mount("/static",StaticFiles(directory=str(static_dir)),name="static")
templates=Jinja2Templates(directory=str(templates_dir))
app.include_router(api)

@app.on_event("startup")
def startup():
    if settings.database_url:
        init_db();bootstrap_admin()

@app.get("/health")
async def health():return {"ok":True,"service":"web","version":"stable-rebuild"}

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
        return templates.TemplateResponse(request=request,name="index.html",context={"page_id":"home","page_title":"المضارب ذكي","public_base_url":settings.public_base_url,"request":request})
    return {"ok":True,"message":"Stable rebuild is running"}

if __name__=="__main__":
    import uvicorn
    uvicorn.run("stable_rebuild.app.main:app",host="0.0.0.0",port=int(os.getenv("PORT","8080")))

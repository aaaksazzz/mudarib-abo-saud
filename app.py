import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE=Path(__file__).resolve().parent
DATA_DIR=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA_DIR.mkdir(parents=True,exist_ok=True)
except PermissionError:
    DATA_DIR=BASE/"data"; DATA_DIR.mkdir(parents=True,exist_ok=True)
DB_PATH=DATA_DIR/"app.db"
SECRET=os.getenv("SESSION_SECRET") or secrets.token_hex(32)
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","us":"السوق الأمريكي","saudi":"السوق السعودي","forex":"الفوركس"}
TIMEFRAMES=["15m","30m","1h","4h","1d","1w","1M"]

app=FastAPI(title="التداول الذكي PRO")
app.add_middleware(SessionMiddleware,secret_key=SECRET,max_age=60*60*24*14)
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,is_admin INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,market TEXT NOT NULL,symbol TEXT NOT NULL,side TEXT NOT NULL,timeframe TEXT NOT NULL,change_pct REAL NOT NULL DEFAULT 0,profit_pct REAL,loss_pct REAL,ai_pct REAL,tag TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,body TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,name TEXT NOT NULL,email TEXT NOT NULL,body TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'new',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    """)
    c.commit(); c.close()

def password_hash(password:str,salt:Optional[str]=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000)
    return salt+"$"+digest.hex()

def password_ok(password,stored):
    try:
        salt,expected=stored.split("$",1)
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),180000).hex()
        return hmac.compare_digest(actual,expected)
    except ValueError: return False

def current_user(request:Request):
    uid=request.session.get("user_id")
    if not uid:return None
    c=db(); row=c.execute("SELECT id,name,email,is_admin FROM users WHERE id=?",(uid,)).fetchone(); c.close()
    return dict(row) if row else None

def page(request:Request,title:str):
    user=current_user(request)
    html=(BASE/"static"/"index.html").read_text(encoding="utf-8")
    boot="<script>window.__PAGE_TITLE__="+repr(title)+";window.__USER__="+repr(user)+";</script>"
    return HTMLResponse(html.replace("</head>",boot+"</head>"))

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health(): return {"status":"ok","service":"trading-pro"}

@app.get("/",response_class=HTMLResponse)
def home(request:Request): return page(request,"الرئيسية")

@app.get("/market/{market}",response_class=HTMLResponse)
def market_page(request:Request,market:str):
    return page(request,MARKETS[market]) if market in MARKETS else RedirectResponse("/",status_code=303)

@app.get("/forum",response_class=HTMLResponse)
def forum(request:Request): return page(request,"المنتدى")

@app.get("/account",response_class=HTMLResponse)
def account(request:Request): return page(request,"حسابي")

@app.get("/admin",response_class=HTMLResponse)
def admin(request:Request):
    u=current_user(request)
    return page(request,"الإدارة") if u and u["is_admin"] else RedirectResponse("/account",status_code=303)

@app.post("/api/register")
def register(request:Request,name:str=Form(...),email:str=Form(...),password:str=Form(...)):
    name=name.strip(); email=email.strip().lower()
    if len(name)<2 or len(password)<6 or "@" not in email:
        return JSONResponse({"ok":False,"message":"تحقق من البيانات وكلمة المرور 6 أحرف على الأقل"},status_code=400)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(name,email,password_hash) VALUES(?,?,?)",(name,email,password_hash(password))); c.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError:
        c.close(); return JSONResponse({"ok":False,"message":"البريد مستخدم مسبقاً"},status_code=409)
    c.close(); request.session["user_id"]=uid
    return {"ok":True,"message":"تم إنشاء الحساب"}

@app.post("/api/login")
def login(request:Request,email:str=Form(...),password:str=Form(...)):
    c=db(); row=c.execute("SELECT * FROM users WHERE email=?",(email.strip().lower(),)).fetchone(); c.close()
    if not row or not password_ok(password,row["password_hash"]):
        return JSONResponse({"ok":False,"message":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
    request.session["user_id"]=row["id"]; return {"ok":True,"message":"تم تسجيل الدخول"}

@app.post("/api/logout")
def logout(request:Request): request.session.clear(); return {"ok":True}

@app.get("/api/me")
def me(request:Request): return {"user":current_user(request)}

@app.get("/api/message")
def active_message():
    c=db(); row=c.execute("SELECT id,title,body FROM messages WHERE active=1 ORDER BY id DESC LIMIT 1").fetchone(); c.close()
    return {"message":dict(row) if row else None}

@app.get("/api/trades/{market}")
def trades(market:str,timeframe:str="15m"):
    if market not in MARKETS or timeframe not in TIMEFRAMES:
        return JSONResponse({"ok":False,"message":"قسم أو فريم غير صالح"},status_code=400)
    c=db()
    rows=c.execute("""SELECT id,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl,status,created_at
    FROM trades WHERE market=? AND timeframe=? AND status='open'
    ORDER BY change_pct DESC,COALESCE(ai_pct,0) DESC,id ASC""",(market,timeframe)).fetchall()
    c.close(); out=[]
    for rank,row in enumerate(rows,1):
        x=dict(row); x["rank"]=rank; x["medal"]="🥇" if rank==1 else "🥈" if rank==2 else "🥉" if rank==3 else ""; out.append(x)
    return {"market":market,"market_name":MARKETS[market],"timeframe":timeframe,"trades":out}

@app.post("/api/support")
def support(request:Request,name:str=Form(...),email:str=Form(...),body:str=Form(...)):
    u=current_user(request); c=db()
    c.execute("INSERT INTO support_messages(user_id,name,email,body) VALUES(?,?,?,?)",(u["id"] if u else None,name.strip(),email.strip().lower(),body.strip()))
    c.commit(); c.close(); return {"ok":True,"message":"تم إرسال رسالتك للدعم"}

def admin_only(request):
    u=current_user(request); return u if u and u["is_admin"] else None

@app.get("/api/admin/summary")
def admin_summary(request:Request):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); a=c.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]; b=c.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]; d=c.execute("SELECT COUNT(*) c FROM support_messages WHERE status='new'").fetchone()["c"]; c.close()
    return {"users":a,"trades":b,"new_support":d}

@app.post("/api/admin/trades")
def admin_trade(request:Request,market:str=Form(...),symbol:str=Form(...),side:str=Form(...),timeframe:str=Form(...),change_pct:float=Form(...),profit_pct:float=Form(...),loss_pct:float=Form(...),ai_pct:float=Form(...),tag:str=Form(""),entry:float=Form(...),tp1:float=Form(...),tp2:float=Form(...),tp3:float=Form(...),sl:float=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    if market not in MARKETS or timeframe not in TIMEFRAMES or side not in {"BUY","SELL"}: return JSONResponse({"ok":False,"message":"بيانات الصفقة غير صالحة"},status_code=400)
    c=db(); c.execute("""INSERT INTO trades(market,symbol,side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(market,symbol.upper(),side,timeframe,change_pct,profit_pct,loss_pct,ai_pct,tag,entry,tp1,tp2,tp3,sl)); c.commit(); c.close()
    return {"ok":True,"message":"تم حفظ الصفقة"}

@app.post("/api/admin/message")
def admin_message(request:Request,title:str=Form(...),body:str=Form(...)):
    if not admin_only(request): return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
    c=db(); c.execute("UPDATE messages SET active=0"); c.execute("INSERT INTO messages(title,body,active) VALUES(?,?,1)",(title,body)); c.commit(); c.close()
    return {"ok":True,"message":"تم نشر الرسالة"}

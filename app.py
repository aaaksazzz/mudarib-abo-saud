from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

app=FastAPI(title="التداول الذكي PRO", version="1.0")\n
# --- Authentication / accounts ---
import sqlite3, hashlib, secrets, hmac, base64
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

DB=BASE/"app.db"
SESSION_DAYS=30

def db():
    c=sqlite3.connect(DB)
    c.row_factory=sqlite3.Row
    return c

def init_db():
    c=db()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        active INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS sessions(
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        created_at INTEGER NOT NULL
    )""")
    c.commit()
    email=os.getenv("ADMIN_EMAIL","").strip().lower()
    password=os.getenv("ADMIN_PASSWORD","")
    if email and password:
        row=c.execute("SELECT id FROM users WHERE email=?",(email,)).fetchone()
        if not row:
            salt=secrets.token_hex(16)
            ph=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),310000).hex()
            c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",
                      (email,ph,salt,"admin",1,int(time.time())))
            c.commit()
        else:
            c.execute("UPDATE users SET role='admin',active=1 WHERE email=?",(email,))
            c.commit()
    c.close()

def hash_password(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt,hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),310000).hex()

def current_user(request:Request):
    token=request.cookies.get("session")
    if not token: return None
    c=db()
    row=c.execute("""SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
                     WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                  (hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    c.close()
    return dict(row) if row else None

def require_user(request):
    u=current_user(request)
    if not u: raise HTTPException(401,"يجب تسجيل الدخول")
    return u

def require_admin(request):
    u=require_user(request)
    if u["role"]!="admin": raise HTTPException(403,"ليس لديك صلاحية الإدارة")
    return u

@app.on_event("startup")
def startup_auth(): init_db()

@app.post("/api/auth/register")
def register(data:dict):
    email=str(data.get("email","")).strip().lower()
    password=str(data.get("password",""))
    if len(email)<5 or "@" not in email: raise HTTPException(400,"البريد غير صحيح")
    if len(password)<8: raise HTTPException(400,"كلمة المرور 8 أحرف على الأقل")
    salt,ph=hash_password(password)
    c=db()
    try:
        cur=c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",
                      (email,ph,salt,"user",1,int(time.time())))
        uid=cur.lastrowid; c.commit()
    except sqlite3.IntegrityError:
        c.close(); raise HTTPException(409,"الحساب موجود مسبقاً")
    c.close()
    return {"ok":True,"user":{"id":uid,"email":email,"role":"user"}}

@app.post("/api/auth/login")
def login(data:dict):
    email=str(data.get("email","")).strip().lower()
    password=str(data.get("password",""))
    c=db()
    row=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
    c.close()
    if not row or not row["active"]: raise HTTPException(401,"بيانات الدخول غير صحيحة")
    _,ph=hash_password(password,row["salt"])
    if not hmac.compare_digest(ph,row["password_hash"]): raise HTTPException(401,"بيانات الدخول غير صحيحة")
    token=secrets.token_urlsafe(48)
    now=int(time.time()); exp=now+SESSION_DAYS*86400
    c=db(); c.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(),row["id"],exp,now)); c.commit(); c.close()
    res=JSONResponse({"ok":True,"user":{"id":row["id"],"email":row["email"],"role":row["role"]}})
    res.set_cookie("session",token,max_age=SESSION_DAYS*86400,httponly=True,samesite="lax",secure=False,path="/")
    return res

@app.post("/api/auth/logout")
def logout(request:Request):
    token=request.cookies.get("session")
    if token:
        c=db(); c.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(token.encode()).hexdigest(),)); c.commit(); c.close()
    res=JSONResponse({"ok":True}); res.delete_cookie("session",path="/"); return res

@app.get("/api/auth/me")
def me(request:Request):
    u=current_user(request)
    return {"authenticated":bool(u),"user":({"id":u["id"],"email":u["email"],"role":u["role"]} if u else None)}

@app.get("/api/admin/users")
def admin_users(request:Request):
    require_admin(request); c=db()
    rows=c.execute("SELECT id,email,role,active,created_at FROM users ORDER BY id DESC").fetchall(); c.close()
    return {"items":[dict(x) for x in rows]}

@app.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id:int,data:dict,request:Request):
    admin=require_admin(request)
    role=data.get("role")
    active=data.get("active")
    c=db(); row=c.execute("SELECT * FROM users WHERE id=?",(user_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,"الحساب غير موجود")
    if user_id==admin["id"] and (role=="user" or active is False):
        c.close(); raise HTTPException(400,"لا يمكنك إلغاء صلاحية حسابك الإداري")
    if role not in ("user","admin") and active is None:
        c.close(); raise HTTPException(400,"تغيير غير صالح")
    if role in ("user","admin"): c.execute("UPDATE users SET role=? WHERE id=?",(role,user_id))
    if active is not None: c.execute("UPDATE users SET active=? WHERE id=?",(1 if active else 0,user_id))
    c.commit(); c.close(); return {"ok":True}

@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id:int,request:Request):
    admin=require_admin(request)
    if user_id==admin["id"]: raise HTTPException(400,"لا يمكنك حذف حسابك الإداري")
    c=db(); c.execute("DELETE FROM sessions WHERE user_id=?",(user_id,)); c.execute("DELETE FROM users WHERE id=?",(user_id,)); c.commit(); c.close()
    return {"ok":True}

BASE=Path(__file__).parent
STORE=BASE/"data.json"
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES=["15m","1h","4h","1d","1w","1M"]
def load():
    try:return json.loads(STORE.read_text())
    except:return {"trades":[]}
def save(x):
    try: STORE.write_text(json.dumps(x,ensure_ascii=False))
    except: pass
def binance(symbol="BTCUSDT", interval="15m", futures=False):
    host="https://fapi.binance.com" if futures else "https://api.binance.com"
    q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":30})
    try:
        with urllib.request.urlopen(host+"/api/v3/klines?"+q if not futures else host+"/fapi/v1/klines?"+q,timeout=3) as r:
            return json.loads(r.read())
    except:return []
def signal(symbol,market,frame):
    futures=market in ("futures","contracts")
    rows=binance(symbol,frame,futures)
    if rows:
        close=float(rows[-1][4]); prev=float(rows[-2][4]); change=(close/prev-1)*100 if prev else 0
        side="BUY" if change>=0 else "SELL"
        if market in ("spot","saudi","us"): side="BUY"
        entry=close; risk=abs(close*0.008)
        if side=="BUY": tp=[entry+risk,entry+risk*2,entry+risk*3]; sl=entry-risk
        else: tp=[entry-risk,entry-risk*2,entry-risk*3]; sl=entry+risk
        ai=max(55,min(92,round(65+abs(change)*8)))
    else:
        entry=100.0; side="BUY" if market not in ("futures","contracts","forex") else "BUY"; risk=.8
        tp=[entry+risk,entry+risk*2,entry+risk*3]; sl=entry-risk; ai=60
    return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"ai":ai,"entry":entry,"tp1":tp[0],"tp2":tp[1],"tp3":tp[2],"sl":sl,"updated":int(time.time())}
def symbols(market):
    if market=="spot": return ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]
    if market in ("futures","contracts"): return ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]
    return ["BTCUSDT","ETHUSDT","SOLUSDT"]
@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","version":"clean-v1","time":datetime.now(timezone.utc).isoformat()}
@app.get("/api/markets")
def markets(): return {"markets":MARKETS,"timeframes":FRAMES,"default":"30m"}
@app.get("/api/trades")
def trades(market:str="spot",timeframe:str="15m"):
    if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid market/timeframe"}
    return {"items":[signal(s,market,timeframe) for s in symbols(market)],"market":market,"timeframe":timeframe}
@app.get("/api/scanner")
def scanner(timeframe:str="15m"):
    if timeframe not in FRAMES: timeframe="15m"
    items=[]
    for m in MARKETS:
        for s in symbols(m)[:3]:
            x=signal(s,m,timeframe); items.append(x)
    items.sort(key=lambda x:x["ai"],reverse=True)
    return {"items":items[:18],"timeframe":timeframe}
@app.get("/api/tracker")
def tracker():
    d=load(); items=d.get("trades",[])
    closed=[x for x in items if x.get("status")=="closed"]
    wins=sum(1 for x in closed if x.get("result")=="win")
    losses=sum(1 for x in closed if x.get("result")=="loss")
    return {"items":items,"stats":{"open":sum(x.get("status")=="open" for x in items),"wins":wins,"losses":losses,"closed":len(closed)}}
@app.post("/api/tracker/add")
def tracker_add(item:dict):
    d=load(); item={**item,"id":int(time.time()*1000),"status":"open","created":int(time.time())}; d.setdefault("trades",[]).append(item); save(d); return item
@app.get("/api/news")
def news(): return {"items":[{"title":"تحديث السوق والتحليل الذكي","time":"الآن"},{"title":"متابعة الأسواق على إطار 30 دقيقة","time":"اليوم"},{"title":"مراقبة الفرص الجديدة","time":"اليوم"}]}
@app.get("/")
def home(): return FileResponse(BASE/"static/index.html")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

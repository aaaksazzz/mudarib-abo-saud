import os,time,hashlib,hmac,secrets,sqlite3
from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse

DB=os.getenv("AUTH_DB", "/data/trading.db" if os.path.isdir("/data") else "trading.db")
router=APIRouter()

def _conn():
    os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
    c=sqlite3.connect(DB,check_same_thread=False)
    c.execute("create table if not exists users(id integer primary key,username text unique not null,password_hash text not null,role text not null default 'user',created real not null)")
    c.execute("create table if not exists sessions(token text primary key,user_id integer not null,role text not null,expires real not null)")
    c.commit()
    return c

def _hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    dk=hashlib.pbkdf2_hmac("sha256",password.encode(),salt.encode(),210000)
    return salt+"$"+dk.hex()

def _verify(password,stored):
    try:
        salt,digest=stored.split("$",1)
        return hmac.compare_digest(_hash(password,salt).split("$",1)[1],digest)
    except Exception:
        return False

def _session(user_id,role):
    token=secrets.token_urlsafe(32)
    c=_conn()
    c.execute("insert into sessions(token,user_id,role,expires) values(?,?,?,?)",(token,user_id,role,time.time()+86400))
    c.commit(); c.close()
    return token

def _current(request):
    token=request.cookies.get("stp_session")
    if not token:return None
    c=_conn(); row=c.execute("select user_id,role,expires from sessions where token=?",(token,)).fetchone()
    if not row or row[2]<time.time():
        if row:c.execute("delete from sessions where token=?",(token,));c.commit()
        c.close();return None
    c.close();return {"user_id":row[0],"role":row[1]}

@router.post("/api/auth/signup")
async def signup(request:Request):
    b=await request.json(); username=str(b.get("username","")).strip().lower(); password=str(b.get("password",""))
    if len(username)<3 or len(username)>40 or len(password)<8:return JSONResponse({"ok":False,"error":"اسم المستخدم 3 أحرف على الأقل وكلمة المرور 8 أحرف على الأقل"},status_code=400)
    c=_conn()
    try:
        cur=c.execute("insert into users(username,password_hash,role,created) values(?,?,?,?)",(username,_hash(password),"user",time.time())); c.commit()
    except sqlite3.IntegrityError:
        c.close();return JSONResponse({"ok":False,"error":"اسم المستخدم مستخدم مسبقاً"},status_code=409)
    uid=cur.lastrowid;c.close()
    token=_session(uid,"user")
    r=JSONResponse({"ok":True,"username":username,"role":"user"});r.set_cookie("stp_session",token,max_age=86400,httponly=True,samesite="lax",secure=False);return r

@router.post("/api/auth/login")
async def login(request:Request):
    b=await request.json(); username=str(b.get("username","")).strip().lower(); password=str(b.get("password",""))
    admin=os.getenv("ADMIN_USERNAME","admin").strip().lower(); admin_pw=os.getenv("ADMIN_PASSWORD","")
    if username==admin and admin_pw and hmac.compare_digest(password,admin_pw):
        token=_session(0,"admin");r=JSONResponse({"ok":True,"username":admin,"role":"admin"});r.set_cookie("stp_session",token,max_age=86400,httponly=True,samesite="lax",secure=False);return r
    c=_conn();row=c.execute("select id,password_hash,role from users where username=?",(username,)).fetchone();c.close()
    if not row or not _verify(password,row[1]):return JSONResponse({"ok":False,"error":"اسم المستخدم أو كلمة المرور غير صحيحة"},status_code=401)
    token=_session(row[0],row[2]);r=JSONResponse({"ok":True,"username":username,"role":row[2]});r.set_cookie("stp_session",token,max_age=86400,httponly=True,samesite="lax",secure=False);return r

@router.post("/api/auth/logout")
async def logout(request:Request):
    token=request.cookies.get("stp_session");c=_conn()
    if token:c.execute("delete from sessions where token=?",(token,));c.commit()
    c.close();r=JSONResponse({"ok":True});r.delete_cookie("stp_session");return r

@router.get("/api/auth/me")
def me(request:Request):
    s=_current(request)
    if not s:return {"ok":True,"authenticated":False,"role":None}
    return {"ok":True,"authenticated":True,"role":s["role"],"user_id":s["user_id"]}

@router.get("/api/admin/status")
def admin_status(request:Request):
    s=_current(request)
    if not s or s["role"]!="admin":return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
    return {"ok":True,"admin":True}

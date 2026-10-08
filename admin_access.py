from datetime import datetime,timedelta,timezone
from fastapi.responses import JSONResponse,RedirectResponse,FileResponse
import os,sys
app=None

MARKET_ACCESS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","us":"الأسهم الأمريكية","saudi":"السوق السعودي","forex":"الفوركس وذهب","gold":"الصفقات الذهبية"}
MARKET_PATHS={"spot":["/fast-spot","/market/spot"],"futures":["/fast-futures","/market/futures"],"contracts":["/fast-contracts","/market/contracts"],"us":["/fast-us","/market/us"],"saudi":["/fast-saudi","/market/saudi"],"forex":["/fast-forex","/market/forex"]}

def ensure():
 c=app.db()
 c.executescript("CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER UNIQUE NOT NULL,plan TEXT NOT NULL,starts_at TEXT NOT NULL,expires_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'active');CREATE TABLE IF NOT EXISTS section_access(key TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1);")
 for k in MARKET_ACCESS:c.execute("INSERT OR IGNORE INTO section_access(key,enabled) VALUES(?,1)",(k,))
 c.commit();c.close()

def sub(uid):
 ensure();c=app.db();r=c.execute("SELECT * FROM subscriptions WHERE user_id=? AND status='active'",(uid,)).fetchone();c.close()
 if not r:return None
 try:
  if datetime.fromisoformat(r["expires_at"])<=datetime.now(timezone.utc):return None
 except:return None
 return dict(r)

def adm(req):
 u=app.current_user(req);return u if u and u.get("is_admin") else None

def install():
 global app
 app=sys.modules.get('app')
 if app is None:return False
 ensure()
 fastapi_app=app.app
 old=app.page
 def page(req,title):
  p=req.url.path
  if p=="/admin":
   if not adm(req):return RedirectResponse("/admin/login",status_code=303)
   return FileResponse(str(app.BASE/"static/admin.html"),headers={"Cache-Control":"no-store"})
  if p in ("/login","/admin/login"):return FileResponse(str(app.BASE/"static/login.html"),headers={"Cache-Control":"no-store"})
  if p=="/register":return FileResponse(str(app.BASE/"static/signup.html"),headers={"Cache-Control":"no-store"})
  for key,paths in MARKET_PATHS.items():
   if p in paths:
    c=app.db();r=c.execute("SELECT enabled FROM section_access WHERE key=?",(key,)).fetchone();c.close()
    if r and not r["enabled"]:return JSONResponse({"ok":False,"message":"القسم مغلق حالياً"},status_code=403)
    u=app.current_user(req)
    if not u:return RedirectResponse("/login",status_code=303)
    if not sub(u["id"]):return RedirectResponse("/?subscription=required",status_code=303)
  return old(req,title)
 app.page=page

 async def login(req):
  d=await req.json();email=str(d.get("email") or d.get("username") or "").strip().lower();pw=str(d.get("password") or "")
  c=app.db();r=c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone();c.close()
  if not r or not app.password_ok(pw,r["password_hash"]):return JSONResponse({"ok":False,"message":"بيانات الدخول غير صحيحة"},status_code=401)
  req.session["user_id"]=r["id"];return {"ok":True,"role":"admin" if r["is_admin"] else "user"}
 async def signup(req):
  d=await req.json();name=str(d.get("username") or "").strip();pw=str(d.get("password") or "")
  if len(name)<3 or len(pw)<8:return JSONResponse({"ok":False,"message":"اسم المستخدم 3 أحرف وكلمة المرور 8 أحرف على الأقل"},status_code=400)
  email=name.lower() if "@" in name else name.lower()+"@local"
  c=app.db()
  try:
   cur=c.execute("INSERT INTO users(name,email,password_hash,is_admin) VALUES(?,?,?,0)",(name,email,app.password_hash(pw)));c.commit();uid=cur.lastrowid
  except Exception:
   c.close();return JSONResponse({"ok":False,"message":"اسم المستخدم مستخدم مسبقاً"},status_code=409)
  c.close();req.session["user_id"]=uid;return {"ok":True,"role":"user"}
 async def logout(req):req.session.clear();return {"ok":True}
 async def status(req):
  u=adm(req);return {"ok":True,"user":u} if u else JSONResponse({"ok":False},status_code=403)
 async def summary(req):
  if not adm(req):return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
  ensure();c=app.db()
  def count_table(name):
   try:
    return int(c.execute("SELECT COUNT(*) AS n FROM "+name).fetchone()["n"])
   except Exception:
    return 0
  users_n=count_table("users")
  trades_n=count_table("trades")
  support_n=0
  try:
   row=c.execute("SELECT COUNT(*) AS n FROM support_messages WHERE status IS NULL OR status != 'read'").fetchone();support_n=int(row["n"])
  except Exception:
   support_n=count_table("support")
  c.close()
  return {"ok":True,"users":users_n,"trades":trades_n,"new_support":support_n}
 async def access(req):
  if not adm(req):return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
  ensure();c=app.db();rs=c.execute("SELECT key,enabled FROM section_access").fetchall();c.close()
  return {"sections":[{"key":r["key"],"name":MARKET_ACCESS[r["key"]],"enabled":bool(r["enabled"])} for r in rs]}
 async def access_set(req):
  if not adm(req):return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
  d=await req.json();key=d.get("key");enabled=1 if d.get("enabled") else 0
  if key not in MARKET_ACCESS:return JSONResponse({"ok":False,"message":"قسم غير صالح"},status_code=400)
  ensure();c=app.db();c.execute("UPDATE section_access SET enabled=? WHERE key=?",(enabled,key));c.commit();c.close();return {"ok":True}
 async def users(req):
  if not adm(req):return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
  ensure();c=app.db();rs=c.execute("SELECT u.id,u.name,u.email,s.plan,s.expires_at,s.status FROM users u LEFT JOIN subscriptions s ON s.user_id=u.id ORDER BY u.id DESC").fetchall();c.close();return {"users":[dict(x) for x in rs]}
 async def grant(req):
  if not adm(req):return JSONResponse({"ok":False,"message":"غير مصرح"},status_code=403)
  f=await req.form();uid=int(f["user_id"]);days=int(f["days"])
  if days not in (7,15,30):return JSONResponse({"ok":False,"message":"اختر 7 أو 15 أو 30 يوم"},status_code=400)
  now=datetime.now(timezone.utc);exp=now+timedelta(days=days);ensure();c=app.db();c.execute("INSERT INTO subscriptions(user_id,plan,starts_at,expires_at,status) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan,starts_at=excluded.starts_at,expires_at=excluded.expires_at,status='active'",(uid,str(days)+"d",now.isoformat(),exp.isoformat(),"active"));c.commit();c.close();return {"ok":True}
 fastapi_fastapi_app.add_api_route("/api/auth/signup",signup,methods=["POST"]);fastapi_app.add_api_route("/api/auth/login",login,methods=["POST"]);fastapi_app.add_api_route("/api/auth/logout",logout,methods=["POST"]);fastapi_app.add_api_route("/api/logout",logout,methods=["POST"]);fastapi_app.add_api_route("/api/admin/status",status,methods=["GET"]);fastapi_app.add_api_route("/api/admin/summary",summary,methods=["GET"]);fastapi_app.add_api_route("/api/admin/access",access,methods=["GET"]);fastapi_app.add_api_route("/api/admin/access",access_set,methods=["POST"]);fastapi_app.add_api_route("/api/admin/users",users,methods=["GET"]);fastapi_app.add_api_route("/api/admin/subscription",grant,methods=["POST"])
 return True

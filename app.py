from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime, timezone
import sqlite3, hashlib, hmac, secrets, os, json, time, urllib.parse, urllib.request

BASE=Path(__file__).parent; DB=BASE/"app.db"; STORE=BASE/"data.json"
app=FastAPI(title="التداول الذكي PRO",version="2.0")
MARKETS={"spot":"السبوت","futures":"الفيوتشر","contracts":"العقود","saudi":"السعودي","us":"الأمريكي","forex":"فوركس وذهب"}
FRAMES=["15m","1h","4h","1d","1w","1M"]; SESSION_DAYS=30; PLANS={"7d":10,"15d":20,"30d":30}

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def hp(p,s=None):
 s=s or secrets.token_hex(16); return s,hashlib.pbkdf2_hmac("sha256",p.encode(),s.encode(),310000).hex()
def init_db():
 c=db(); c.executescript("""
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,salt TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',active INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS articles(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,slug TEXT UNIQUE NOT NULL,excerpt TEXT DEFAULT '',body TEXT NOT NULL,published INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,symbol TEXT NOT NULL,market TEXT NOT NULL,timeframe TEXT NOT NULL,side TEXT NOT NULL,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,ai REAL DEFAULT 0,status TEXT DEFAULT 'open',result TEXT DEFAULT '',pnl REAL DEFAULT 0,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS subscriptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,plan TEXT NOT NULL,amount REAL NOT NULL,method TEXT DEFAULT '',txid TEXT DEFAULT '',status TEXT DEFAULT 'pending',created_at INTEGER NOT NULL);
 """)
 e=os.getenv("ADMIN_EMAIL","").strip().lower(); p=os.getenv("ADMIN_PASSWORD","")
 if e and p:
  r=c.execute("SELECT id FROM users WHERE email=?",(e,)).fetchone()
  if not r:
   s,ph=hp(p); c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",(e,ph,s,"admin",1,int(time.time())))
  else: c.execute("UPDATE users SET role='admin',active=1 WHERE email=?",(e,))
 c.commit(); c.close()
@app.on_event("startup")
def startup(): init_db()
def me(request):
 t=request.cookies.get("session")
 if not t:return None
 c=db(); r=c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",(hashlib.sha256(t.encode()).hexdigest(),int(time.time()))).fetchone(); c.close()
 return dict(r) if r else None
def user(request):
 u=me(request)
 if not u: raise HTTPException(401,"يجب تسجيل الدخول")
 return u
def admin(request):
 u=user(request)
 if u["role"]!="admin": raise HTTPException(403,"ليس لديك صلاحية الإدارة")
 return u

@app.get("/health")
def health(): return {"status":"ok","service":"mudarib-abo-saud","version":"2.0","time":datetime.now(timezone.utc).isoformat()}
@app.post("/api/auth/register")
def register(d:dict):
 e=str(d.get("email","")).strip().lower(); p=str(d.get("password",""))
 if "@" not in e: raise HTTPException(400,"البريد غير صحيح")
 if len(p)<8: raise HTTPException(400,"كلمة المرور 8 أحرف على الأقل")
 s,ph=hp(p); c=db()
 try: cur=c.execute("INSERT INTO users(email,password_hash,salt,role,active,created_at) VALUES(?,?,?,?,?,?)",(e,ph,s,"user",1,int(time.time()))); c.commit(); uid=cur.lastrowid
 except sqlite3.IntegrityError: c.close(); raise HTTPException(409,"الحساب موجود مسبقاً")
 c.close(); return {"ok":True,"user":{"id":uid,"email":e,"role":"user"}}
@app.post("/api/auth/login")
def login(d:dict):
 e=str(d.get("email","")).strip().lower(); p=str(d.get("password","")); c=db(); r=c.execute("SELECT * FROM users WHERE email=?",(e,)).fetchone(); c.close()
 if not r or not r["active"]: raise HTTPException(401,"بيانات الدخول غير صحيحة")
 _,ph=hp(p,r["salt"])
 if not hmac.compare_digest(ph,r["password_hash"]): raise HTTPException(401,"بيانات الدخول غير صحيحة")
 t=secrets.token_urlsafe(48); now=int(time.time()); c=db(); c.execute("INSERT INTO sessions VALUES(?,?,?,?)",(hashlib.sha256(t.encode()).hexdigest(),r["id"],now+SESSION_DAYS*86400,now)); c.commit(); c.close()
 x=JSONResponse({"ok":True,"user":{"id":r["id"],"email":r["email"],"role":r["role"]}}); x.set_cookie("session",t,max_age=SESSION_DAYS*86400,httponly=True,samesite="lax",secure=True,path="/"); return x
@app.post("/api/auth/logout")
def logout(request:Request):
 t=request.cookies.get("session")
 if t:
  c=db(); c.execute("DELETE FROM sessions WHERE token_hash=?",(hashlib.sha256(t.encode()).hexdigest(),)); c.commit(); c.close()
 x=JSONResponse({"ok":True}); x.delete_cookie("session",path="/"); return x
@app.get("/api/auth/me")
def auth_me(request:Request):
 u=me(request); return {"authenticated":bool(u),"user":({"id":u["id"],"email":u["email"],"role":u["role"]} if u else None)}

def binance(symbol,interval,futures=False):
 host="https://fapi.binance.com" if futures else "https://api.binance.com"; path="/fapi/v1/klines" if futures else "/api/v3/klines"; q=urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":30})
 try:
  with urllib.request.urlopen(host+path+"?"+q,timeout=4) as r:return json.loads(r.read())
 except:return []
def signal(symbol,market,frame):
 rows=binance(symbol,frame,market in ("futures","contracts"))
 if rows:
  e=float(rows[-1][4]); prev=float(rows[-2][4]); ch=(e/prev-1)*100 if prev else 0; side="BUY" if ch>=0 else "SELL"
  if market in ("spot","saudi","us"):side="BUY"
  risk=max(abs(e*.008),e*.002); t=[e+risk*i for i in (1,2,3)] if side=="BUY" else [e-risk*i for i in (1,2,3)]
  return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,"ai":max(55,min(92,round(65+abs(ch)*8))),"entry":e,"tp1":t[0],"tp2":t[1],"tp3":t[2],"sl":e-risk if side=="BUY" else e+risk,"updated":int(time.time())}
 return {"symbol":symbol,"market":market,"timeframe":frame,"side":"BUY","ai":60,"entry":100,"tp1":100.8,"tp2":101.6,"tp3":102.4,"sl":99.2,"updated":int(time.time())}
SYMBOL_CACHE={}
SYMBOL_CACHE_TTL=300

def all_binance_symbols(futures=False):
 key="futures" if futures else "spot"; now=time.time()
 cached=SYMBOL_CACHE.get(key)
 if cached and now-cached["time"]<SYMBOL_CACHE_TTL:
  return cached["symbols"]
 host="https://fapi.binance.com" if futures else "https://api.binance.com"
 path="/fapi/v1/exchangeInfo" if futures else "/api/v3/exchangeInfo"
 try:
  with urllib.request.urlopen(host+path,timeout=8) as r:
   data=json.loads(r.read())
  out=[]
  for x in data.get("symbols",[]):
   if x.get("status")!="TRADING": continue
   if x.get("quoteAsset")!="USDT": continue
   if futures and x.get("contractType") not in (None,"PERPETUAL","CURRENT_QUARTER","NEXT_QUARTER"): continue
   out.append(x["symbol"])
  out=sorted(set(out))
  if out:
   SYMBOL_CACHE[key]={"time":now,"symbols":out}
   return out
 except Exception:
  pass
 return cached["symbols"] if cached else ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","DOGEUSDT"]

SYMBOL_LIST_CACHE={}
SYMBOL_LIST_TTL=1800
FOREX_SYMBOLS=["EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD","EURGBP","EURJPY","GBPJPY","AUDJPY","EURAUD","EURCHF","GBPCHF","AUDCAD","AUDCHF","CADJPY","NZDJPY","NZDCHF","GBPAUD","GBPCAD","EURCAD","USDMXN","USDZAR","USDTRY","USDNOK","USDSEK","USDSGD","USDHKD","USDCNH","USDPLN","USDHUF","USDCZK"]

def all_us_stocks():
 key="us_stocks"; now=time.time(); cached=SYMBOL_LIST_CACHE.get(key)
 if cached and now-cached["time"]<SYMBOL_LIST_TTL:return cached["symbols"]
 urls=["https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt","https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"]
 out=set()
 try:
  for url in urls:
   with urllib.request.urlopen(url,timeout=10) as r: txt=r.read().decode("utf-8","ignore")
   lines=txt.splitlines()
   for line in lines[1:]:
    if not line or line.startswith("File Creation Time"):continue
    parts=line.split("|")
    sym=parts[1].strip() if len(parts)>1 else ""
    test=parts[-1].strip() if parts else ""
    if sym and sym not in ("Symbol","File Creation Time") and not sym.startswith("$") and "test" not in test.lower():
     if "^" not in sym and "/" not in sym: out.add(sym.replace(".","-"))
  vals=sorted(out)
  if vals: SYMBOL_LIST_CACHE[key]={"time":now,"symbols":vals}; return vals
 except Exception:
  pass
 return cached["symbols"] if cached else ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA"]

def symbols(m):
 if m=="spot": return all_binance_symbols(False)
 if m in ("futures","contracts"): return all_binance_symbols(True)
 if m=="us": return all_us_stocks()
 if m=="forex": return FOREX_SYMBOLS
 return ["BTCUSDT","ETHUSDT","SOLUSDT"]
@app.get("/api/markets")
def markets():return {"markets":MARKETS,"timeframes":FRAMES,"default":"15m"}
TICKER_CACHE={}
TICKER_CACHE_TTL=30

def binance_tickers(futures=False):
 key="futures" if futures else "spot"; now=time.time(); cached=TICKER_CACHE.get(key)
 if cached and now-cached["time"]<TICKER_CACHE_TTL:return cached["data"]
 host="https://fapi.binance.com" if futures else "https://api.binance.com"
 path="/fapi/v1/ticker/24hr" if futures else "/api/v3/ticker/24hr"
 try:
  with urllib.request.urlopen(host+path,timeout=8) as r:data=json.loads(r.read())
  data={x["symbol"]:x for x in data if x.get("symbol")}
  TICKER_CACHE[key]={"time":now,"data":data}; return data
 except Exception:
  return cached["data"] if cached else {}

def yahoo_tickers(symbols_list,forex=False):
 out={}
 for i in range(0,len(symbols_list),100):
  chunk=symbols_list[i:i+100]
  qs=",".join((s+"=X") if forex else s for s in chunk)
  try:
   url="https://query1.finance.yahoo.com/v7/finance/quote?"+urllib.parse.urlencode({"symbols":qs})
   with urllib.request.urlopen(url,timeout=10) as r:data=json.loads(r.read())
   for x in data.get("quoteResponse",{}).get("result",[]): out[x.get("symbol","").replace("=X","")]=x
  except Exception: continue
 return out

def fast_signal(symbol,market,frame,tickers):
 x=tickers.get(symbol,{})
 try:
  e=float(x.get("lastPrice") or x.get("regularMarketPrice") or 0)
  ch=float(x.get("priceChangePercent") or x.get("regularMarketChangePercent") or 0)
 except:e=0; ch=0
 if e<=0:return signal(symbol,market,frame)
 side="BUY" if ch>=0 else "SELL"
 if market in ("spot","saudi","us"):side="BUY"
 risk=max(abs(e*.008),e*.002)
 t=[e+risk*i for i in (1,2,3)] if side=="BUY" else [e-risk*i for i in (1,2,3)]
 return {"symbol":symbol,"market":market,"timeframe":frame,"side":side,
         "ai":max(55,min(92,round(65+abs(ch)*8))),"entry":e,
         "tp1":t[0],"tp2":t[1],"tp3":t[2],
         "sl":e-risk if side=="BUY" else e+risk,"updated":int(time.time())}

@app.get("/api/trades")
def trades(market="spot",timeframe="15m"):
 if market not in MARKETS or timeframe not in FRAMES:return {"items":[],"error":"invalid market/timeframe"}
 syms=symbols(market)
 if market in ("spot","futures","contracts"):
  tickers=binance_tickers(market in ("futures","contracts"))
 elif market in ("us","forex"):
  tickers=yahoo_tickers(syms,market=="forex")
 else:
  tickers={}
 items=[fast_signal(s,market,timeframe,tickers) for s in syms if s in tickers or market not in ("us","forex")]
 return {"items":items,"market":market,"timeframe":timeframe,"count":len(items)}
@app.get("/api/scanner")
def scanner(timeframe="15m"):
 if timeframe not in FRAMES:timeframe="15m"
 a=[signal(s,m,timeframe) for m in MARKETS for s in symbols(m)[:3]]; a.sort(key=lambda x:x["ai"],reverse=True); return {"items":a[:18],"timeframe":timeframe}

@app.get("/api/tracker")
def tracker(request:Request):
 u=user(request); c=db(); a=c.execute("SELECT * FROM trades WHERE user_id=? ORDER BY id DESC",(u["id"],)).fetchall(); c.close()
 return {"items":[dict(x) for x in a],"stats":{"open":sum(x["status"]=="open" for x in a),"wins":sum(x["result"]=="win" for x in a),"losses":sum(x["result"]=="loss" for x in a),"closed":sum(x["status"]=="closed" for x in a)}}
@app.post("/api/tracker/add")
def tracker_add(d:dict,request:Request):
 u=user(request); c=db(); cur=c.execute("INSERT INTO trades(user_id,symbol,market,timeframe,side,entry,tp1,tp2,tp3,sl,ai,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(u["id"],d.get("symbol",""),d.get("market","spot"),d.get("timeframe","15m"),d.get("side","BUY"),d.get("entry"),d.get("tp1"),d.get("tp2"),d.get("tp3"),d.get("sl"),d.get("ai",0),"open",int(time.time()))); c.commit(); tid=cur.lastrowid; c.close(); return {"ok":True,"id":tid}

@app.get("/api/blog")
def blog():
 c=db(); a=c.execute("SELECT * FROM articles WHERE published=1 ORDER BY id DESC").fetchall(); c.close(); return {"items":[dict(x) for x in a]}
@app.get("/api/blog/{slug}")
def blog_one(slug:str):
 c=db(); r=c.execute("SELECT * FROM articles WHERE slug=? AND published=1",(slug,)).fetchone(); c.close()
 if not r:raise HTTPException(404,"المقال غير موجود")
 return dict(r)
@app.get("/api/admin/blog/all")
def admin_blog(request:Request):
 admin(request); c=db(); a=c.execute("SELECT * FROM articles ORDER BY id DESC").fetchall(); c.close(); return {"items":[dict(x) for x in a]}
@app.post("/api/admin/blog")
def blog_add(d:dict,request:Request):
 admin(request); title=str(d.get("title","")).strip(); body=str(d.get("body","")).strip(); slug=str(d.get("slug") or title).strip().lower().replace(" ","-")
 if not title or not body:raise HTTPException(400,"العنوان والمحتوى مطلوبان")
 c=db()
 try: cur=c.execute("INSERT INTO articles(title,slug,excerpt,body,published,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",(title,slug,d.get("excerpt",""),body,1 if d.get("published",True) else 0,int(time.time()),int(time.time()))); c.commit(); aid=cur.lastrowid
 except sqlite3.IntegrityError:c.close();raise HTTPException(409,"الرابط موجود مسبقاً")
 c.close();return {"ok":True,"id":aid}
@app.put("/api/admin/blog/{aid}")
def blog_edit(aid:int,d:dict,request:Request):
 admin(request); c=db(); r=c.execute("SELECT * FROM articles WHERE id=?",(aid,)).fetchone()
 if not r:c.close();raise HTTPException(404,"المقال غير موجود")
 c.execute("UPDATE articles SET title=?,slug=?,excerpt=?,body=?,published=?,updated_at=? WHERE id=?",(d.get("title",r["title"]),d.get("slug",r["slug"]),d.get("excerpt",r["excerpt"]),d.get("body",r["body"]),1 if d.get("published",bool(r["published"])) else 0,int(time.time()),aid));c.commit();c.close();return {"ok":True}
@app.delete("/api/admin/blog/{aid}")
def blog_delete(aid:int,request:Request):
 admin(request);c=db();c.execute("DELETE FROM articles WHERE id=?",(aid,));c.commit();c.close();return {"ok":True}

@app.get("/api/admin/users")
def admin_users(request:Request):
 admin(request);c=db();a=c.execute("SELECT id,email,role,active,created_at FROM users ORDER BY id DESC").fetchall();c.close();return {"items":[dict(x) for x in a]}
@app.patch("/api/admin/users/{uid}")
def admin_user(uid:int,d:dict,request:Request):
 a=admin(request);c=db();r=c.execute("SELECT id FROM users WHERE id=?",(uid,)).fetchone()
 if not r:c.close();raise HTTPException(404,"الحساب غير موجود")
 if uid==a["id"] and (d.get("role")=="user" or d.get("active") is False):c.close();raise HTTPException(400,"لا يمكنك تعطيل حسابك")
 if d.get("role") in ("user","admin"):c.execute("UPDATE users SET role=? WHERE id=?",(d["role"],uid))
 if d.get("active") is not None:c.execute("UPDATE users SET active=? WHERE id=?",(1 if d["active"] else 0,uid))
 c.commit();c.close();return {"ok":True}

PLANS={"7d":10,"15d":20,"30d":30}
@app.get("/api/subscriptions/plans")
def plans():return {"plans":[{"id":k,"days":int(k[:-1]),"price":v,"currency":"USDT"} for k,v in PLANS.items()]}
@app.post("/api/subscriptions/request")
def sub(d:dict,request:Request):
 u=user(request);p=str(d.get("plan",""))
 if p not in PLANS:raise HTTPException(400,"الباقة غير صحيحة")
 c=db();cur=c.execute("INSERT INTO subscriptions(user_id,plan,amount,method,txid,status,created_at) VALUES(?,?,?,?,?,?,?)",(u["id"],p,PLANS[p],d.get("method",""),d.get("txid",""),"pending",int(time.time())));c.commit();sid=cur.lastrowid;c.close();return {"ok":True,"id":sid,"status":"pending"}
@app.get("/api/admin/subscriptions")
def admin_subs(request:Request):
 admin(request);c=db();a=c.execute("SELECT s.*,u.email FROM subscriptions s JOIN users u ON u.id=s.user_id ORDER BY s.id DESC").fetchall();c.close();return {"items":[dict(x) for x in a]}
@app.patch("/api/admin/subscriptions/{sid}")
def admin_sub(sid:int,d:dict,request:Request):
 admin(request);st=d.get("status")
 if st not in ("pending","approved","rejected"):raise HTTPException(400,"حالة غير صحيحة")
 c=db();c.execute("UPDATE subscriptions SET status=? WHERE id=?",(st,sid));c.commit();c.close();return {"ok":True}
@app.get("/api/admin/stats")
def stats(request:Request):
 admin(request);c=db();r={"users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],"articles":c.execute("SELECT COUNT(*) n FROM articles").fetchone()["n"],"trades":c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"],"pending_subscriptions":c.execute("SELECT COUNT(*) n FROM subscriptions WHERE status='pending'").fetchone()["n"]};c.close();return r
@app.post("/api/admin/telegram/test")
def telegram(request:Request):
 admin(request);token=os.getenv("TELEGRAM_BOT_TOKEN","");chat=os.getenv("TELEGRAM_CHAT_ID","@tadol1")
 if not token:raise HTTPException(503,"ضع TELEGRAM_BOT_TOKEN في Northflank")
 data=urllib.parse.urlencode({"chat_id":chat,"text":"✅ اختبار اتصال التداول الذكي PRO"}).encode()
 try:
  with urllib.request.urlopen("https://api.telegram.org/bot"+token+"/sendMessage",data=data,timeout=8) as r:return {"ok":True,"telegram":json.loads(r.read())}
 except:raise HTTPException(502,"تعذر إرسال الاختبار")
@app.get("/api/news")
def news():return {"items":[{"title":"تحديث السوق والتحليل الذكي","time":"الآن"},{"title":"متابعة الأسواق على إطار 15 دقيقة","time":"اليوم"}]}
@app.get("/")
def home():return FileResponse(BASE/"static/index.html")
app.mount("/static",StaticFiles(directory=BASE/"static"),name="static")

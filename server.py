import os, sqlite3, secrets, time, urllib.parse, xml.etree.ElementTree as ET, html
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, send_from_directory

app=Flask(__name__,template_folder="templates",static_folder=None)
app.secret_key=os.getenv("SECRET_KEY",secrets.token_hex(32))
DB=os.getenv("SQLITE_FILE","mudarib.db")
STATIC=os.path.join(os.path.dirname(os.path.abspath(__file__)),"static")
PLANS={"7d":{"name":"7 أيام","days":7,"amount":10},"30d":{"name":"30 يوم","days":30,"amount":20},"90d":{"name":"90 يوم","days":90,"amount":30}}
MARKETS={"saudi":[("2222.SR","أرامكو"),("1120.SR","الراجحي"),("2010.SR","سابك"),("1180.SR","الأهلي السعودي"),("7010.SR","STC"),("1211.SR","معادن"),("1150.SR","الإنماء"),("2380.SR","بترو رابغ"),("4003.SR","إكسترا"),("4200.SR","الدريس")],"usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("GOOGL","Alphabet"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("XAUUSD=X","Gold")]}
H=requests.Session(); H.headers["User-Agent"]="Mudarib-Abo-Saud/1.0"
NEWS_CACHE={"at":0,"items":[]}
NEWS_QUERIES=[("🇸🇦 السعودية","السعودية سوق الأسهم تاسي أرامكو الراجحي اقتصاد"),("🇺🇸 الأسواق الأمريكية","الأسواق الأمريكية ناسداك داو جونز الأسهم"),("₿ العملات الرقمية","بيتكوين إيثريوم العملات الرقمية كريبتو"),("🛢️ النفط والذهب","النفط الذهب أسعار الأسواق"),("🌍 الاقتصاد العالمي","الاقتصاد العالمي الفائدة الدولار الأسواق المالية")]

@app.get("/static/<path:name>")
def static_file(name): return send_from_directory(STATIC,name,max_age=0)

def conn():
 c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; return c
def init():
 c=conn(); c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,email TEXT UNIQUE,name TEXT,password TEXT,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT,plan TEXT,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,content TEXT,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);"""); c.commit(); c.close()
def ok(**x): return jsonify(ok=True,**x)
def fail(m,code=400): return jsonify(ok=False,message=m),code
def yahoo(sym,interval,range_):
 r=H.get("https://query1.finance.yahoo.com/v8/finance/chart/"+sym,params={"interval":interval,"range":range_},timeout=12);r.raise_for_status();z=r.json()["chart"]["result"][0];q=z["indicators"]["quote"][0];out=[]
 for i,t in enumerate(z.get("timestamp",[])):
  try: out.append({"time":t,"open":float(q["open"][i]),"high":float(q["high"][i]),"low":float(q["low"][i]),"close":float(q["close"][i]),"volume":float((q.get("volume") or [0]*len(z["timestamp"]))[i] or 0)})
  except: pass
 return out
def okx(inst,bar):
 r=H.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":100},timeout=12);r.raise_for_status();out=[]
 for x in reversed(r.json().get("data",[])):
  try: out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
  except: pass
 return out
def signal(c,symbol,market,interval,name=""):
 if len(c)<10:return None
 p=c[-1]["close"]; prev=c[-2]["close"]; high=max(x["high"] for x in c[-20:]); low=min(x["low"] for x in c[-20:]); avg=sum(x["volume"] for x in c[-20:])/20; vol=c[-1]["volume"]; move=(p-prev)/prev
 up=sum(x["close"]>x["open"] for x in c[-8:]); down=8-up
 buy=50+min(35,max(-20,move*500))+(up-down)*2+(8 if p>high*.985 else 0)+(7 if vol>avg*1.2 else 0)
 sell=50-min(35,max(-20,move*500))+(down-up)*2+(8 if p<low*1.015 else 0)+(7 if vol>avg*1.2 else 0)
 direction="شراء" if buy>sell+8 else "بيع" if sell>buy+8 else "حيادي"; confidence=round(min(99,max(50,max(buy,sell))),1)
 ready=direction!="حيادي" and confidence>=60
 risk=p*.02
 if direction=="شراء": t=[p+risk,p+risk*2,p+risk*3]; sl=p-risk
 elif direction=="بيع": t=[p-risk,p-risk*2,p-risk*3]; sl=p+risk
 else: t=[p,p,p];sl=p
 return {"symbol":symbol,"displayName":name or symbol,"market":market,"interval":interval,"signal":("شراء قوي" if direction=="شراء" and confidence>=80 else "بيع قوي" if direction=="بيع" and confidence>=80 else direction),"direction":direction,"tradeReady":ready,"confidence":confidence,"price":p,"entry":p,"tp1":t[0],"tp2":t[1],"tp3":t[2],"sl":sl,"rr":2.0,"updatedAt":datetime.now(timezone.utc).isoformat()}
def scan(market,interval):
 bars={"5m":"5m","15m":"15m","30m":"30m","1H":"1H","4H":"4H","1D":"1D"}; bar=bars.get(interval,"15m")
 if market=="crypto" or market=="futures":
  typ="SPOT" if market=="crypto" else "SWAP"; r=H.get("https://www.okx.com/api/v5/market/tickers",params={"instType":typ},timeout=12);r.raise_for_status(); items=[x for x in r.json().get("data",[]) if x["instId"].endswith("-USDT" if market=="crypto" else "-USDT-SWAP")][:50]
  with ThreadPoolExecutor(max_workers=6) as ex:
   fs={ex.submit(okx,x["instId"],bar):x["instId"] for x in items}; out=[]
   for f in as_completed(fs):
    try: out.append(signal(f.result(),fs[f].replace("-",""),market,interval))
    except: pass
 else:
  yi={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d"}.get(interval,"1d"); rg="5d" if yi=="5m" else "1mo" if yi in ("15m","30m") else "1y"
  with ThreadPoolExecutor(max_workers=5) as ex:
   fs={ex.submit(yahoo,s,yi,rg):(s,n) for s,n in MARKETS[market]};out=[]
   for f in as_completed(fs):
    try: out.append(signal(f.result(),fs[f][0],market,interval,fs[f][1]))
    except: pass
 return sorted([x for x in out if x],key=lambda x:x["confidence"],reverse=True)
def fetch_news_feed(label,query):
 sources=[
  ("https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":query,"hl":"ar","gl":"SA","ceid":"SA:ar"})),
  ("https://www.bing.com/news/search?"+urllib.parse.urlencode({"q":query,"format":"rss","setlang":"ar-SA"}))
 ]
 for url in sources:
  try:
   r=H.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0","Accept":"application/rss+xml, application/xml, text/xml, */*"})
   r.raise_for_status()
   root=ET.fromstring(r.content)
   items=[]
   for item in root.findall("./channel/item")[:10]:
    title=html.unescape((item.findtext("title") or "").strip())
    link=(item.findtext("link") or "").strip()
    pub=(item.findtext("pubDate") or "").strip()
    source=html.unescape((item.findtext("source") or "").strip()) or label
    desc=html.unescape((item.findtext("description") or "").strip())
    if title and link:
     items.append({"title":title,"link":link,"published":pub,"source":source,"category":label,"description":desc})
   if items:
    return items
  except Exception as e:
   app.logger.warning("News source failed for %s: %s",label,e)
 fallback_urls={
  "🇸🇦 السعودية":"https://sa.investing.com/markets/saudi-arabia",
  "🇺🇸 الأسواق الأمريكية":"https://sa.investing.com/markets/united-states",
  "₿ العملات الرقمية":"https://sa.investing.com/news/cryptocurrency-news",
  "🛢️ النفط والذهب":"https://sa.investing.com/commodities-news",
  "🌍 الاقتصاد العالمي":"https://sa.investing.com/news/economy"
 }
 link=fallback_urls.get(label,"https://sa.investing.com/")
 clean_label=label.split(" ",1)[1] if " " in label else label
 return [{
  "title":"أحدث أخبار "+clean_label,
  "link":link,
  "published":datetime.now(timezone.utc).isoformat(),
  "source":"مصدر الأخبار",
  "category":label,
  "description":"تعذر جلب العناوين المباشرة حالياً؛ افتح المصدر لمتابعة آخر التحديثات."
 }]

@app.get("/api/live-news")
def live_news():
 global NEWS_CACHE
 now=time.time()
 if now-NEWS_CACHE["at"]<60 and NEWS_CACHE["items"]:
  return ok(news=NEWS_CACHE["items"],updatedAt=datetime.now(timezone.utc).isoformat())
 with ThreadPoolExecutor(max_workers=5) as ex:
  fs=[ex.submit(fetch_news_feed,*q) for q in NEWS_QUERIES]
  items=[]
  for f in fs:
   try:items.extend(f.result())
   except:pass
 seen=set();clean=[]
 for x in items:
  key=x["link"]
  if key in seen:continue
  seen.add(key);clean.append(x)
 clean.sort(key=lambda x:x.get("published",""),reverse=True)
 NEWS_CACHE={"at":now,"items":clean[:30]}
 return ok(news=clean[:30],updatedAt=datetime.now(timezone.utc).isoformat())

@app.get("/")
def home(): return render_template("index.html",page_id="dashboard",page_title="المضارب ذكي")

@app.get("/api/home/overview")
def home_overview():
 try:
  configs=[("crypto","15m"),("futures","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]
  def one(cfg):
   market,interval=cfg
   rows=scan(market,interval)
   up=sum(1 for x in rows if x["direction"]=="شراء")
   down=sum(1 for x in rows if x["direction"]=="بيع")
   neutral=sum(1 for x in rows if x["direction"]=="حيادي")
   top=rows[0] if rows else None
   return {"market":market,"interval":interval,"total":len(rows),"up":up,"down":down,"neutral":neutral,"top":(top.get("displayName") or top.get("symbol")) if top else "لا توجد","confidence":top.get("confidence",0) if top else 0}
  with ThreadPoolExecutor(max_workers=5) as ex:
   data=list(ex.map(one,configs))
  return ok(markets=data,updatedAt=datetime.now(timezone.utc).isoformat())
 except Exception as e:
  app.logger.exception("home overview failed")
  return fail("تعذر جلب ملخص الأسواق حالياً",502)
@app.get("/<page>")
def pages(page):
 allowed={"spot":"spot","futures":"futures","contracts":"contracts","scanner":"scanner","saudi":"saudi","usmarket":"usmarket","forex":"forex","news":"news","subscription":"subscription","login":"login","register":"register","admin":"admin"}
 if page in allowed:return render_template(allowed[page]+".html",page_id=page,page_title=page)
 return ("غير موجود",404)
@app.get("/api/ai/signals")
def signals():
 try:
  market=request.args.get("market","crypto"); interval=request.args.get("interval","15m"); limit=min(20,max(1,int(request.args.get("limit",20))))
  if market not in ("crypto","futures","saudi","usmarket","forex"):return fail("السوق غير معروف")
  return ok(results=scan(market,interval)[:limit],market=market,interval=interval)
 except Exception as e:return fail("تعذر جلب بيانات السوق حالياً",502)
@app.get("/health")
def health():return ok(status="healthy",time=datetime.now(timezone.utc).isoformat())
@app.get("/api/me")
def me():
 u=session.get("user"); 
 if not u:return ok(user=None,admin=False)
 c=conn();r=c.execute("SELECT id,username,email,name,is_admin,subscription_until,created_at FROM users WHERE username=?",(u,)).fetchone();c.close()
 return ok(user=dict(r) if r else None,admin=bool(r and r["is_admin"]))
@app.post("/api/auth/register")
def register():
 d=request.get_json(silent=True) or {}; name=str(d.get("name","")).strip();email=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 if not name or "@" not in email or len(pw)<6:return fail("أدخل الاسم والبريد وكلمة مرور 6 أحرف على الأقل")
 username=email.split("@")[0][:30]
 c=conn()
 try:c.execute("INSERT INTO users(username,email,name,password) VALUES(?,?,?,?)",(username,email,name,__import__("werkzeug.security",fromlist=["generate_password_hash"]).generate_password_hash(pw)));c.commit()
 except sqlite3.IntegrityError:c.close();return fail("البريد مستخدم مسبقاً")
 c.close();session["user"]=username;return ok(user=username)
@app.post("/api/auth/login")
def login():
 d=request.get_json(silent=True) or {};identity=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 from werkzeug.security import check_password_hash
 c=conn();u=c.execute("SELECT * FROM users WHERE email=? OR username=?",(identity,identity)).fetchone();c.close()
 if not u or not check_password_hash(u["password"],pw):return fail("بيانات الدخول غير صحيحة",401)
 session["user"]=u["username"];session["admin"]=bool(u["is_admin"]);return ok(user=u["username"],admin=bool(u["is_admin"]))
@app.post("/api/auth/logout")
def logout():session.clear();return ok()
@app.get("/api/subscription")
def subscription():return ok(plans=PLANS,payment={"trc20":os.getenv("TRC20_ADDRESS",""),"binancePay":os.getenv("BINANCE_PAY_ID","")})
@app.post("/api/subscription/request")
def sub_request():
 if not session.get("user"):return fail("سجل الدخول أولاً",401)
 d=request.get_json(silent=True) or {};plan=d.get("plan");txid=str(d.get("txid","")).strip()
 if plan not in PLANS or not txid:return fail("اختر الباقة وأدخل رقم العملية")
 c=conn();c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(session["user"],plan,txid));c.commit();c.close();return ok()
def admin():return bool(session.get("admin"))
@app.post("/api/admin/login")
def admin_login():
 d=request.get_json(silent=True) or {}
 if d.get("username")==os.getenv("ADMIN_USERNAME","aaaksazzz") and d.get("password")==os.getenv("ADMIN_PASSWORD","4573261aA"):session["admin"]=True;session["user"]=d.get("username");return ok()
 return fail("بيانات الإدارة غير صحيحة",401)
@app.get("/api/admin/stats")
def stats():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],c.execute("SELECT COUNT(*) n FROM payments WHERE status='pending'").fetchone()["n"],c.execute("SELECT COUNT(*) n FROM users WHERE subscription_until>?",(datetime.now(timezone.utc).isoformat(),)).fetchone()["n"]];c.close();return ok(users=r[0],pending_payments=r[1],active_subscriptions=r[2])
@app.get("/api/admin/users")
def users():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[dict(x) for x in c.execute("SELECT id,username,email,name,subscription_until,created_at FROM users ORDER BY id DESC").fetchall()];c.close();return ok(users=r)
@app.get("/api/admin/payments")
def payments():
 if not admin():return fail("غير مصرح",403)
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM payments ORDER BY id DESC").fetchall()];c.close();return ok(payments=r)
@app.post("/api/admin/payments/approve")
def approve():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();p=c.execute("SELECT * FROM payments WHERE id=?",(d.get("id"),)).fetchone()
 if not p:c.close();return fail("الطلب غير موجود",404)
 u=c.execute("SELECT * FROM users WHERE username=?",(p["username"],)).fetchone();base=datetime.now(timezone.utc)
 if u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=PLANS[p["plan"]]["days"])).isoformat();c.execute("UPDATE users SET subscription_until=? WHERE username=?",(until,p["username"]));c.execute("UPDATE payments SET status='approved' WHERE id=?",(p["id"],));c.commit();c.close();return ok()
@app.post("/api/admin/payments/reject")
def reject():
 if not admin():return fail("غير مصرح",403)
 c=conn();c.execute("UPDATE payments SET status='rejected' WHERE id=?",(request.get_json(silent=True) or {}).get("id"));c.commit();c.close();return ok()
@app.post("/api/admin/users/delete")
def delete_user():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {}; uid=d.get("id")
 c=conn();u=c.execute("SELECT username,is_admin FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 if u["is_admin"]:c.close();return fail("لا يمكن حذف حساب الإدارة",400)
 c.execute("DELETE FROM payments WHERE username=?",(u["username"],));c.execute("DELETE FROM users WHERE id=?",(uid,));c.commit();c.close();return ok()

@app.post("/api/admin/users/extend")
def extend_user():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {}; uid=d.get("id"); days=max(1,min(365,int(d.get("days",30))))
 c=conn();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 base=datetime.now(timezone.utc)
 if u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=days)).isoformat()
 c.execute("UPDATE users SET subscription_until=? WHERE id=?",(until,uid));c.commit();c.close();return ok(subscription_until=until)

@app.post("/api/admin/logout")
def admin_logout():
 session.pop("admin",None);session.pop("user",None);return ok()

@app.get("/api/news")
def news():
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 50").fetchall()];c.close();return ok(news=r)
@app.post("/api/admin/news")
def add_news():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();c.execute("INSERT INTO news(title,content,source) VALUES(?,?,?)",(d.get("title",""),d.get("content",""),d.get("source","")));c.commit();c.close();return ok()
init()
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))

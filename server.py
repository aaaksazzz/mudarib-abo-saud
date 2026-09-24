import os, sqlite3, secrets, time, hmac, threading, urllib.parse, xml.etree.ElementTree as ET, html
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, send_from_directory

app=Flask(__name__,template_folder="templates",static_folder=None)
try:
 from werkzeug.middleware.proxy_fix import ProxyFix
 app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1,x_host=1)
except Exception:
 pass
BASE_DIR=os.path.dirname(os.path.abspath(__file__))
STATIC=os.path.join(BASE_DIR,"static")
_db_env=os.getenv("SQLITE_FILE","mudarib.db").strip()
DB=_db_env if os.path.isabs(_db_env) else os.path.join(BASE_DIR,_db_env)
def _load_secret_key():
    configured=os.getenv("SECRET_KEY","").strip()
    if configured:return configured
    path=os.path.join(os.path.dirname(DB) or ".", "session_secret.key")
    try:
        os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
        if os.path.exists(path):
            with open(path,"r",encoding="utf-8") as f:return f.read().strip()
        value=secrets.token_hex(32)
        with open(path,"w",encoding="utf-8") as f:f.write(value)
        return value
    except Exception:return secrets.token_hex(32)
app.secret_key=_load_secret_key()
_session_secure_env=os.getenv("SESSION_COOKIE_SECURE","").strip().lower()
_session_secure=_session_secure_env in ("1","true","yes") if _session_secure_env else False
app.config.update(
 SESSION_COOKIE_HTTPONLY=True,
 SESSION_COOKIE_SAMESITE="Lax",
 SESSION_COOKIE_SECURE=_session_secure,
 SESSION_COOKIE_PATH="/",
 SESSION_REFRESH_EACH_REQUEST=True
)
PAID_MARKETS={"contracts":[("ES=F","S&P 500 E-mini"),("NQ=F","Nasdaq 100 E-mini"),("YM=F","Dow Jones E-mini"),("RTY=F","Russell 2000 E-mini"),("CL=F","Crude Oil WTI"),("GC=F","Gold Futures"),("SI=F","Silver Futures")],"saudi":[],"usmarket":[],"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("EURGBP=X","EUR/GBP"),("EURJPY=X","EUR/JPY"),("GBPJPY=X","GBP/JPY"),("AUDJPY=X","AUD/JPY"),("NZDJPY=X","NZD/JPY"),("USDMXN=X","USD/MXN"),("USDZAR=X","USD/ZAR"),("USDTRY=X","USD/TRY"),("USDSGD=X","USD/SGD"),("USDHKD=X","USD/HKD"),("XAUUSD=X","Gold"),("XAGUSD=X","Silver")]}

MARKETS=dict(PAID_MARKETS)
PLANS={"7d":{"days":7,"price":10},"30d":{"days":30,"price":20},"90d":{"days":90,"price":30}}
ADMIN_RATE_LOCK=threading.Lock()
ADMIN_RATE={}
ADMIN_WINDOW=300
ADMIN_MAX_FAILURES=8

def _log_admin_env_status():
    admin_user_present=bool(os.getenv("ADMIN_USERNAME","").strip())
    admin_pass_present=bool(os.getenv("ADMIN_PASSWORD","").strip())
    app.logger.info("Admin environment status: ADMIN_USERNAME=%s ADMIN_PASSWORD=%s",admin_user_present,admin_pass_present)

_log_admin_env_status()
H=requests.Session(); H.headers["User-Agent"]="Mudarib-Abo-Saud/1.0"
NEWS_CACHE={"at":0,"items":[]}
NEWS_QUERIES=[("🇸🇦 السعودية","السعودية سوق الأسهم تاسي أرامكو الراجحي اقتصاد"),("🇺🇸 الأسواق الأمريكية","الأسواق الأمريكية ناسداك داو جونز الأسهم"),("₿ العملات الرقمية","بيتكوين إيثريوم العملات الرقمية كريبتو"),("🛢️ النفط والذهب","النفط الذهب أسعار الأسواق"),("🌍 الاقتصاد العالمي","الاقتصاد العالمي الفائدة الدولار الأسواق المالية")]

@app.get("/static/<path:name>")
def static_file(name): return send_from_directory(STATIC,name,max_age=0)

def conn():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
 c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; return c
def init():
 c=conn(); c.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,email TEXT UNIQUE,name TEXT,password TEXT,is_admin INTEGER DEFAULT 0,subscription_until TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT,plan TEXT,txid TEXT,status TEXT DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,content TEXT,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blog_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,slug TEXT UNIQUE,title TEXT NOT NULL,excerpt TEXT DEFAULT '',content TEXT NOT NULL,category TEXT DEFAULT 'عام',cover_url TEXT DEFAULT '',author TEXT DEFAULT 'المضارب ذكي',published INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS telegram_sent(signal_key TEXT PRIMARY KEY,sent_at TEXT DEFAULT CURRENT_TIMESTAMP,message_id INTEGER);"""); c.commit(); c.close()

def _seed_beginner_blog():
 slug="dalil-al-tadawul-lilmubtadien"
 c=conn()
 try:
  if c.execute("SELECT 1 FROM blog_posts WHERE slug=?",(slug,)).fetchone(): return
  path=os.path.join(BASE_DIR,"content","blog_beginner_trading.txt")
  with open(path,"r",encoding="utf-8") as f: content=f.read().strip()
  lines=content.split("\n",1)
  title=lines[0].strip()
  excerpt="دليل عملي للمبتدئين لفهم التداول وقراءة السوق وإدارة رأس المال والمخاطر."
  c.execute("INSERT INTO blog_posts(slug,title,excerpt,content,category,author,published) VALUES(?,?,?,?,?,?,1)",(slug,title,excerpt,content,"تعليم التداول","المضارب ذكي"))
  c.commit()
  app.logger.info("Beginner trading blog article seeded: %s",slug)
 except Exception:
  app.logger.exception("Beginner trading guide seed failed")
 finally:
  c.close()

def ok(**x): return jsonify(ok=True,**x)
def fail(m,code=400): return jsonify(ok=False,message=m),code
def current_user():
    username=session.get("user")
    if not username:return None
    c=conn();u=c.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone();c.close()
    return u

def has_active_subscription():
    u=current_user()
    if not u or not u["subscription_until"]:return False
    try:return datetime.fromisoformat(u["subscription_until"])>datetime.now(timezone.utc)
    except:return False

def require_market_access(market):
    if market not in PAID_MARKETS:return None
    if session.get("admin"):return None
    if not current_user():return fail("سجل الدخول أولاً للوصول لهذا القسم",401)
    if not has_active_subscription():return fail("هذا القسم يتطلب اشتراكاً فعالاً",403)
    return None

def yahoo(sym,interval,range_):
 last=None
 lookup={"XAUUSD=X":"GC=F"}
 symbols=[lookup.get(sym,sym)]
 for symbol in symbols:
  for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
   try:
    r=H.get("https://"+host+"/v8/finance/chart/"+urllib.parse.quote(symbol,safe=""),params={"interval":interval,"range":range_,"includePrePost":"true"},timeout=15)
    r.raise_for_status()
    payload=r.json()
    result=(payload.get("chart") or {}).get("result")
    if not result: raise ValueError((payload.get("chart") or {}).get("error") or "Yahoo returned no data")
    z=result[0];q=z["indicators"]["quote"][0];out=[]
    timestamps=z.get("timestamp",[])
    volumes=q.get("volume") or [0]*len(timestamps)
    for i,t in enumerate(timestamps):
     try:
      o,h,l,cl=q["open"][i],q["high"][i],q["low"][i],q["close"][i]
      if None in (o,h,l,cl): continue
      out.append({"time":t,"open":float(o),"high":float(h),"low":float(l),"close":float(cl),"volume":float(volumes[i] or 0)})
     except Exception: pass
    if out:return out
    raise ValueError("Yahoo returned empty candles")
   except Exception as e:
    last=e
    app.logger.warning("Yahoo source failed %s %s %s: %s",symbol,interval,range_,e)
 raise RuntimeError("تعذر جلب بيانات "+sym+" من Yahoo Finance: "+str(last))
def okx(inst,bar):
 r=H.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":100},timeout=12);r.raise_for_status();out=[]
 for x in reversed(r.json().get("data",[])):
  try: out.append({"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])})
  except: pass
 return out
AI_CACHE={}
AI_CACHE_TTL=45
AI_MODEL=os.getenv("OPENAI_MODEL","gpt-5.6-luna").strip()

def _ai_json(prompt):
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key: raise RuntimeError("OPENAI_API_KEY غير مضبوط")
    body={"model":AI_MODEL,"input":[{"role":"system","content":[{"type":"input_text","text":"أنت محلل أسواق مالي آلي. حلل بيانات OHLCV الخام فقط. لا تستخدم مؤشرات جاهزة. لا تضمن الربح. إذا كانت البيانات غير كافية أو الإشارة ضعيفة أعد حيادي. أعد JSON فقط بالمفاتيح: items، وكل عنصر يحتوي symbol,direction,confidence,trade_ready,entry,tp1,tp2,tp3,sl,rr,reason."}]},{"role":"user","content":[{"type":"input_text","text":prompt}]}],"text":{"format":{"type":"json_object"}}}
    r=H.post("https://api.openai.com/v1/responses",headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},json=body,timeout=60)
    r.raise_for_status(); data=r.json(); txt=data.get("output_text")
    if not txt:
        for item in data.get("output",[]):
            for content in item.get("content",[]):
                if content.get("type")=="output_text": txt=content.get("text"); break
            if txt: break
    if not txt: raise RuntimeError("AI لم يرجع نتيجة")
    return __import__("json").loads(txt)

def _local_batch(candles_by_symbol,market,interval,names):
    items=[]
    for symbol,candles in candles_by_symbol.items():
        if len(candles)<12: continue
        recent=candles[-12:]; last=recent[-1]; prev=recent[-2]
        close=float(last["close"]); prev_close=float(prev["close"])
        if close<=0 or prev_close<=0: continue
        change=(close/prev_close-1.0)*100.0
        ranges=[max(0.0,float(x["high"])-float(x["low"])) for x in recent]
        avg_range=sum(ranges[:-1])/max(1,len(ranges)-1)
        recent_closes=[float(x["close"]) for x in recent]; mid=(max(recent_closes)+min(recent_closes))/2.0
        direction="حيادي"; confidence=50.0; trade_ready=False
        if change>=0.35 and close>=mid:
            direction="شراء"; confidence=min(90.0,60.0+abs(change)*8.0)
        elif change<=-0.35 and close<=mid:
            direction="بيع"; confidence=min(90.0,60.0+abs(change)*8.0)
        if direction!="حيادي" and avg_range>0:
            entry=close; risk=max(avg_range*1.25,close*0.004)
            if direction=="شراء":
                sl=max(0.0,entry-risk); tp1=entry+risk*1.5; tp2=entry+risk*2.0; tp3=entry+risk*2.5
            else:
                sl=entry+risk; tp1=max(0.0,entry-risk*1.5); tp2=max(0.0,entry-risk*2.0); tp3=max(0.0,entry-risk*2.5)
            rr=2.0; trade_ready=confidence>=65
        else: entry=tp1=tp2=tp3=sl=rr=0.0
        items.append({"symbol":symbol,"direction":direction,"confidence":round(confidence,1),"trade_ready":trade_ready,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"rr":rr,"reason":"تحليل محلي لحركة السعر الخام بدون مؤشرات أو مفتاح OpenAI."})
    return items

def ai_batch(candles_by_symbol,market,interval,names):
    now=time.time(); cache_key=market+"|"+interval+"|"+",".join(sorted(candles_by_symbol.keys())); cached=AI_CACHE.get(cache_key)
    if cached and now-cached["at"]<AI_CACHE_TTL:return cached["items"]
    if not os.getenv("OPENAI_API_KEY","").strip():
        items=_local_batch(candles_by_symbol,market,interval,names); AI_CACHE[cache_key]={"at":now,"items":items}; return items
    payload=[{"symbol":symbol,"name":names.get(symbol,symbol),"candles":candles[-40:]} for symbol,candles in candles_by_symbol.items()]
    prompt="السوق: "+market+"\nالفريم: "+interval+"\nحلل كل أصل بشكل مستقل اعتماداً على OHLCV الخام المرفق. لا تستخدم RSI/MACD/EMA/SMA أو أي مؤشر تقني جاهز، ولا تعتمد على نظام نقاط برمجي. إذا وجدت صفقة واضحة أعد شراء أو بيع، وإلا حيادي. للصفقة: اجعل الدخول قريباً من آخر سعر، وحدد TP/SL من بنية الحركة والمخاطرة، وليس كنسبة ثابتة. trade_ready=true فقط عند وجود أفضلية واضحة. البيانات:\n"+__import__("json").dumps(payload,ensure_ascii=False,separators=(",",":"))
    try: result=_ai_json(prompt); items=result.get("items",[])
    except Exception as e: app.logger.warning("OpenAI unavailable; using local analysis: %s",e); items=_local_batch(candles_by_symbol,market,interval,names)
    AI_CACHE[cache_key]={"at":now,"items":items}; return items

def _decorate_ai(item,market,interval,name):
    d=item.get("direction","حيادي"); conf=round(float(item.get("confidence",0) or 0),1)
    return {"symbol":item.get("symbol",""),"displayName":name or item.get("symbol",""),"market":market,"interval":interval,"signal":"شراء قوي" if d=="شراء" and conf>=80 else "بيع قوي" if d=="بيع" and conf>=80 else d,"direction":d,"tradeReady":bool(item.get("trade_ready",False)) and d!="حيادي" and conf>=60,"confidence":conf,"price":float(item.get("entry",0) or 0),"entry":float(item.get("entry",0) or 0),"tp1":float(item.get("tp1",0) or 0),"tp2":float(item.get("tp2",0) or 0),"tp3":float(item.get("tp3",0) or 0),"sl":float(item.get("sl",0) or 0),"rr":float(item.get("rr",0) or 0),"reason":item.get("reason",""),"ai":True,"updatedAt":datetime.now(timezone.utc).isoformat()}

def _yahoo_universe(market):
    static=dict(MARKETS.get(market,[]))
    region="sa" if market=="saudi" else "us" if market=="usmarket" else None
    if not region:return list(static.items())
    try:
        url="https://query1.finance.yahoo.com/v1/finance/screener"
        params={"formatted":"false","lang":"en-US","region":"US","corsDomain":"finance.yahoo.com"}
        payload={"offset":0,"size":250,"sortType":"DESC","sortField":"dayvolume","quoteType":"EQUITY","query":{"operator":"and","operands":[{"operator":"eq","operands":["region",region]}]},"userId":"","userIdType":"guid"}
        found={}
        for offset in range(0,2500,250):
            payload["offset"]=offset
            r=H.post(url,params=params,json=payload,timeout=20);r.raise_for_status()
            quotes=((r.json().get("finance") or {}).get("result") or [{}])[0].get("quotes") or []
            if not quotes:break
            for q in quotes:
                s=str(q.get("symbol","")).strip()
                if s:found[s]=str(q.get("shortName") or q.get("longName") or s)
            if len(quotes)<250:break
        if found:return list(found.items())
    except Exception as e:app.logger.warning("Yahoo universe discovery failed %s: %s",market,e)
    return list(static.items())

def _scan_yahoo_symbols(symbols,market,interval,limit):
    universe=_yahoo_universe(market) if market in ("saudi","usmarket") else list(symbols)
    yi={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d"}.get(interval,"1d")
    rg="5d" if yi=="5m" else "1mo" if yi in ("15m","30m") else "1y"
    max_symbols=int(os.getenv("MARKET_SCAN_SYMBOLS","1000"))
    universe=universe[:max_symbols];candles={};names=dict(universe)
    with ThreadPoolExecutor(max_workers=min(12,len(universe) or 1)) as ex:
        fs={ex.submit(yahoo,s,yi,rg):s for s,n in universe}
        for f in as_completed(fs):
            s=fs[f]
            try:
                cc=f.result()
                if len(cc)>=12:candles[s]=cc
            except Exception as e:app.logger.warning("AI data failed %s: %s",s,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol"))) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

def binance_exchange_symbols(market):
    endpoint="/api/v3/exchangeInfo" if market=="crypto" else "/fapi/v1/exchangeInfo"
    data=H.get("https://api.binance.com"+endpoint,timeout=20).json()
    return [s["symbol"] for s in data.get("symbols",[]) if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT"]

def binance_candles(symbol,interval,market):
    endpoint="/api/v3/klines" if market=="crypto" else "/fapi/v1/klines"
    r=H.get("https://api.binance.com"+endpoint,params={"symbol":symbol,"interval":interval,"limit":100},timeout=15);r.raise_for_status()
    return [{"time":int(x[0])//1000,"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5])} for x in r.json()]

def _scan_binance(market,interval,limit):
    symbols=binance_exchange_symbols(market)
    endpoint="/api/v3/ticker/24hr" if market=="crypto" else "/fapi/v1/ticker/24hr"
    tickers=H.get("https://api.binance.com"+endpoint,timeout=20).json()
    volumes={x.get("symbol"):float(x.get("quoteVolume",0) or 0) for x in tickers}
    symbols=sorted(symbols,key=lambda s:volumes.get(s,0),reverse=True)
    max_symbols=int(os.getenv("BINANCE_SCAN_SYMBOLS","500"));symbols=symbols[:max_symbols]
    candles={};names={s:s for s in symbols}
    with ThreadPoolExecutor(max_workers=16) as ex:
        fs={ex.submit(binance_candles,s,interval,market):s for s in symbols}
        for f in as_completed(fs):
            s=fs[f]
            try:
                cc=f.result()
                if len(cc)>=12:candles[s]=cc
            except Exception as e:app.logger.warning("Binance data failed %s: %s",s,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,s) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

def _scan_okx(market,interval,limit):
    bar={"5m":"5m","15m":"15m","30m":"30m","1H":"1H","4H":"4H","1D":"1D"}.get(interval,"15m"); typ="SPOT" if market=="crypto" else "SWAP"; suffix="-USDT" if market=="crypto" else "-USDT-SWAP"
    r=H.get("https://www.okx.com/api/v5/market/tickers",params={"instType":typ},timeout=12);r.raise_for_status()
    items=[x for x in r.json().get("data",[]) if x.get("instId","").endswith(suffix)]; items=sorted(items,key=lambda x:float(x.get("volCcy24h",0) or 0),reverse=True)[:limit]
    candles={}; names={x["instId"]:x["instId"] for x in items}
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs={ex.submit(okx,x["instId"],bar):x["instId"] for x in items}
        for f in as_completed(fs):
            sym=fs[f]
            try:
                c=f.result()
                if len(c)>=12:candles[sym]=c
            except Exception as e:app.logger.warning("AI data failed %s: %s",sym,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol"))) for x in ai if x.get("symbol") in candles],key=lambda x:x["confidence"],reverse=True)

MONTH_CODES={3:"H",6:"M",9:"U",12:"Z",1:"F",2:"G",4:"J",5:"K",7:"N",8:"Q",10:"V",11:"X"}
MONTH_NAMES={1:"يناير",2:"فبراير",3:"مارس",4:"أبريل",5:"مايو",6:"يونيو",7:"يوليو",8:"أغسطس",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}

def _business_days_before(dt,n):
    d=dt; left=n
    while left>0:
        d-=timedelta(days=1)
        if d.weekday()<5:left-=1
    return d

def _third_friday(year,month):
    d=datetime(year,month,1,tzinfo=timezone.utc)
    while d.weekday()!=4:d+=timedelta(days=1)
    return d+timedelta(days=14)

def _next_quarterly_contract(now=None):
    now=now or datetime.now(timezone.utc)
    for add in range(0,8):
        month=((now.month-1)//3)*3+3+add*3
        year=now.year+(month-1)//12
        month=((month-1)%12)+1
        expiry=_third_friday(year,month)
        if expiry>now:
            return {"year":year,"month":month,"expiry":expiry}
    return None

def _contract_specs():
    return [{"symbol":"ES=F","name":"S&P 500 E-mini","exchange":"CME","type":"Index Futures"},{"symbol":"NQ=F","name":"Nasdaq 100 E-mini","exchange":"CME","type":"Index Futures"},{"symbol":"YM=F","name":"Dow Jones E-mini","exchange":"CBOT","type":"Index Futures"},{"symbol":"RTY=F","name":"Russell 2000 E-mini","exchange":"CME","type":"Index Futures"},{"symbol":"CL=F","name":"Crude Oil WTI","exchange":"NYMEX","type":"Commodity Futures"},{"symbol":"GC=F","name":"Gold Futures","exchange":"COMEX","type":"Commodity Futures"},{"symbol":"SI=F","name":"Silver Futures","exchange":"COMEX","type":"Commodity Futures"}]

def _contract_calendar():
    now=datetime.now(timezone.utc);q=_next_quarterly_contract(now); rows=[]
    for spec in _contract_specs():
        symbol=spec["symbol"]; rows.append({**spec,"contract_month":q["month"],"contract_year":q["year"],"contract_code":MONTH_CODES[q["month"]]+str(q["year"]%100),"expiry":q["expiry"].date().isoformat(),"roll_watch":(_business_days_before(q["expiry"],5).date().isoformat())})
    return rows

def scan(market,interval):
    limit=80
    if market in ("crypto","futures"):return _scan_binance(market,interval,limit)
    if market=="contracts":return _scan_yahoo_symbols(PAID_MARKETS["contracts"],market,interval,limit)
    return _scan_yahoo_symbols(PAID_MARKETS.get(market,[]),market,interval,limit)

@app.get("/")
def index():return render_template("index.html",page_id="home",page_title="المضارب ذكي",meta_description="منصة تحليل الأسواق بالذكاء الاصطناعي: العملات الرقمية، العقود الآجلة، الأسهم السعودية والأمريكية، والفوركس.")

@app.get("/api/home/opportunities")
def home_opportunities():
    try:
        all_items=[]
        jobs=[("crypto","15m"),("futures","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]
        for market,interval in jobs:
            try:
                access=require_market_access(market)
                if access and getattr(access,"status_code",200)!=200: continue
                all_items.extend([x for x in scan(market,interval) if x.get("tradeReady") and x.get("direction") in ("شراء","بيع")])
            except Exception as e: app.logger.warning("Homepage scan failed %s: %s",market,e)
        all_items.sort(key=lambda x:(x.get("confidence",0),x.get("rr",0)),reverse=True)
        selected=all_items[:5]
        try:_telegram_opportunities(selected)
        except Exception as e:app.logger.warning("Telegram opportunity alert failed: %s",e)
        return ok(opportunities=selected,updatedAt=datetime.now(timezone.utc).isoformat())
    except Exception as e:return fail("تعذر تحديث الفرص الآن: "+str(e),502)

def _telegram_opportunities(items):
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip(); chat_id=os.getenv("TELEGRAM_CHAT_ID","").strip()
    if not token or not chat_id or not items:return
    sent_keys=[]
    for x in items:
        key="|".join([str(x.get("market","")),str(x.get("symbol","")),str(x.get("direction","")),str(round(float(x.get("entry",0) or 0),8))])
        if key in sent_keys:continue
        sent_keys.append(key)
        c=conn()
        if c.execute("SELECT 1 FROM telegram_sent WHERE signal_key=?",(key,)).fetchone():c.close();continue
        msg=(f"{x.get('symbol','')} | {'LONG' if x.get('direction')=='شراء' else 'SHORT'}\n"
             f"ENTRY: {x.get('entry',0)}\nTP1: {x.get('tp1',0)}\nTP2: {x.get('tp2',0)}\nTP3: {x.get('tp3',0)}\n"
             f"SL: {x.get('sl',0)}\nCONFIDENCE: {x.get('confidence',0)}%")
        try:
            r=H.post("https://api.telegram.org/bot"+token+"/sendMessage",json={"chat_id":chat_id,"text":msg,"disable_web_page_preview":True},timeout=15);r.raise_for_status();data=r.json()
            if data.get("ok"):
                c.execute("INSERT INTO telegram_sent(signal_key,message_id) VALUES(?,?)",(key,int(data["result"]["message_id"])));c.commit()
        except Exception as e:app.logger.warning("Telegram send failed: %s",e)
        finally:c.close()

SEO_MARKETS={
 "crypto":{"title":"تحليل العملات الرقمية اليوم","description":"تحليل العملات الرقمية بالذكاء الاصطناعي مع إشارات السوق الحالية ومستويات الدخول والأهداف ووقف الخسارة عند توفر فرصة.","intro":"صفحة مخصصة لتحليل سوق العملات الرقمية وعرض الفرص التي تستوفي شروط التحليل الحالية.","interval":"15m"},
 "futures":{"title":"تحليل كريبتو فيوتشر اليوم","description":"تحليل سوق عقود العملات الرقمية الآجلة والفرص الحالية مع ENTRY وTP وSL وCONFIDENCE.","intro":"تُعرض هنا إشارات عقود العملات الرقمية الآجلة بناءً على بيانات السوق الحالية، مع مستويات الدخول والأهداف ووقف الخسارة.","interval":"15m"},
 "contracts":{"title":"تحليل العقود الآجلة الأمريكية","description":"تحليل S&P 500 وNasdaq وDow Jones والسلع والعقود الآجلة المتاحة في الموقع.","intro":"صفحة تجمع تحليلات العقود الآجلة المتاحة مثل المؤشرات الرئيسية والذهب والنفط، مع تحديثات السوق الحالية.","interval":"15m"},
 "saudi":{"title":"تحليل السوق السعودي اليوم","description":"تحليل الأسهم السعودية وسوق تداول مع قراءة الاتجاه والفرص المتاحة عند توفر البيانات.","intro":"هذا القسم مخصص للسوق السعودي ويعرض إشارات التحليل والاتجاهات من بيانات السوق المتاحة.","interval":"1D"},
 "usmarket":{"title":"تحليل الأسهم الأمريكية اليوم","description":"تحليل الأسواق والأسهم الأمريكية والفرص الحالية مع مستويات الدخول والأهداف ووقف الخسارة عند توفرها.","intro":"صفحة تحليل للأسواق الأمريكية تعرض الفرص التي تستوفي شروط النظام من بيانات السوق الحالية.","interval":"1D"},
 "forex":{"title":"تحليل الفوركس والذهب اليوم","description":"تحليل أزواج الفوركس والذهب والفضة مع الاتجاه والفرص الحالية عند توفر بيانات السوق.","intro":"قسم الفوركس والسلع يعرض تحليلات أزواج العملات والذهب والفضة مع مستويات الصفقة عند توفر إشارة قابلة للتنفيذ.","interval":"1H"}
}
@app.get("/robots.txt")
def robots_txt():
    host=request.host_url.rstrip("/")
    return "User-agent: *\nAllow: /\nAllow: /analysis/\nDisallow: /admin\nDisallow: /api/\nDisallow: /login\nDisallow: /register\nSitemap: "+host+"/sitemap.xml\n",200,{"Content-Type":"text/plain; charset=utf-8"}

@app.get("/sitemap.xml")
def sitemap_xml():
    host=request.host_url.rstrip("/")
    paths=["/","/blog","/spot","/futures","/contracts","/scanner","/saudi","/usmarket","/forex","/news","/analysis/crypto","/analysis/futures","/analysis/contracts","/analysis/saudi","/analysis/usmarket","/analysis/forex","/subscription"]
    now=datetime.now(timezone.utc).date().isoformat()
    urls="".join("<url><loc>"+host+p+"</loc><lastmod>"+now+"</lastmod></url>" for p in paths)
    return "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"+urls+"</urlset>",200,{"Content-Type":"application/xml; charset=utf-8"}

@app.get("/analysis/<market>")
def market_analysis_page(market):
    cfg=SEO_MARKETS.get(market)
    if not cfg:return ("غير موجود",404)
    return render_template("market_seo.html",page_id="analysis-"+market,page_title=cfg["title"],market_title=cfg["title"],market_description=cfg["description"],market_intro=cfg["intro"],market_key=market,market_interval=cfg["interval"],meta_description=cfg["description"],canonical_url=request.base_url)

@app.get("/<page>")
def pages(page):
 allowed={"spot":"spot","futures":"futures","contracts":"contracts","scanner":"scanner","saudi":"saudi","usmarket":"usmarket","forex":"forex","news":"news","subscription":"subscription","login":"login","register":"register","admin":"admin"}
 if page in allowed:return render_template(allowed[page]+".html",page_id=page,page_title=page)
 return ("غير موجود",404)

@app.get("/api/ai/signals")
def signals():
 try:
  market=request.args.get("market","crypto");interval=request.args.get("interval","15m");limit=min(20,max(1,int(request.args.get("limit",20))))
  if market not in ("crypto","futures","contracts","saudi","usmarket","forex"):return fail("السوق غير معروف")
  access=require_market_access(market)
  if access:return access
  return ok(results=scan(market,interval)[:limit],market=market,interval=interval)
 except Exception:return fail("تعذر جلب بيانات السوق حالياً",502)

@app.get("/health")
def health():return jsonify(ok=True,status="healthy",service="mudarib-abo-saud",time=datetime.now(timezone.utc).isoformat()),200
@app.get("/api/me")
def me():
 u=session.get("user");session_admin=bool(session.get("admin"))
 if not u:return ok(user=None,admin=session_admin,subscription_active=False,paid_markets=sorted(PAID_MARKETS))
 c=conn();r=c.execute("SELECT id,username,email,name,is_admin,subscription_until,created_at FROM users WHERE username=?",(u,)).fetchone();c.close()
 return ok(user=dict(r) if r else None,admin=session_admin or bool(r and r["is_admin"]),subscription_active=has_active_subscription(),paid_markets=sorted(PAID_MARKETS))

@app.post("/api/auth/register")
def register():
 d=request.get_json(silent=True) or {};name=str(d.get("name","")).strip();email=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 if not name or "@" not in email or len(pw)<8:return fail("أدخل الاسم والبريد وكلمة مرور 8 أحرف على الأقل")
 username=email.split("@")[0][:30];c=conn()
 try:c.execute("INSERT INTO users(username,email,name,password) VALUES(?,?,?,?)",(username,email,name,__import__("werkzeug.security",fromlist=["generate_password_hash"]).generate_password_hash(pw)));c.commit()
 except sqlite3.IntegrityError:c.close();return fail("البريد مستخدم مسبقاً")
 c.close();session["user"]=username;return ok(user=username)

@app.post("/api/auth/login")
def login():
 d=request.get_json(silent=True) or {};identity=str(d.get("email","")).strip().lower();pw=str(d.get("password",""));from werkzeug.security import check_password_hash
 c=conn();u=c.execute("SELECT * FROM users WHERE email=? OR username=?",(identity,identity)).fetchone();c.close()
 if not u or not check_password_hash(u["password"],pw):return fail("بيانات الدخول غير صحيحة",401)
 session["user"]=u["username"];session["admin"]=bool(u["is_admin"]);return ok(user=u["username"],admin=bool(u["is_admin"]))

@app.post("/api/auth/logout")
def logout():session.clear();return ok()

@app.get("/api/subscription")
def subscription():return ok(plans=PLANS,payment={"trc20":os.getenv("TRC20_ADDRESS","").strip(),"binancePay":os.getenv("BINANCE_PAY_ID","").strip()})

@app.post("/api/subscription/request")
def sub_request():
 if not session.get("user"):return fail("سجل الدخول أولاً",401)
 d=request.get_json(silent=True) or {};plan=d.get("plan");txid=str(d.get("txid","")).strip()
 if plan not in PLANS or not txid:return fail("اختر الباقة وأدخل رقم العملية")
 if len(txid)<6 or len(txid)>200:return fail("رقم العملية غير صالح")
 c=conn()
 if c.execute("SELECT id FROM payments WHERE txid=? AND status IN ('pending','approved')",(txid,)).fetchone():c.close();return fail("رقم العملية مستخدم مسبقاً",409)
 c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(session["user"],plan,txid));c.commit();c.close();return ok()

def admin():return bool(session.get("admin"))
@app.post("/api/admin/login")
def admin_login():
 d=request.get_json(silent=True) or {};admin_user=os.getenv("ADMIN_USERNAME","").strip();admin_pass=os.getenv("ADMIN_PASSWORD","")
 missing=[]
 if not admin_user:missing.append("ADMIN_USERNAME")
 if not admin_pass:missing.append("ADMIN_PASSWORD")
 app.logger.info("Admin login environment check: ADMIN_USERNAME=%s ADMIN_PASSWORD=%s",bool(admin_user),bool(admin_pass))
 if missing:
  app.logger.error("Admin login blocked: missing environment variables: %s",",".join(missing))
  return fail("إعدادات دخول المشرف غير مكتملة في بيئة التشغيل",503)
 ip=request.headers.get("X-Forwarded-For",request.remote_addr or "unknown").split(",")[0].strip();now=time.time()
 with ADMIN_RATE_LOCK:
  state=ADMIN_RATE.get(ip,{"at":now,"failures":0})
  if now-state["at"]>ADMIN_WINDOW:state={"at":now,"failures":0}
  if state["failures"]>=ADMIN_MAX_FAILURES:return fail("محاولات دخول كثيرة، حاول بعد 5 دقائق",429)
  valid=hmac.compare_digest(str(d.get("username","")),admin_user) and hmac.compare_digest(str(d.get("password","")),admin_pass)
  if not valid:state["failures"]+=1;state["at"]=now;ADMIN_RATE[ip]=state;return fail("بيانات الإدارة غير صحيحة",401)
  ADMIN_RATE.pop(ip,None)
 session.clear()
 session["admin"]=True
 session["admin_user"]=admin_user
 session.permanent=True
 session.modified=True
 app.logger.info("Admin login successful; session established")
 return ok(admin=True)

@app.get("/api/admin/session")
def admin_session():
 return ok(admin=admin(),user=session.get("admin_user") if admin() else None)

@app.post("/api/admin/telegram/test")
def telegram_test():
 if not admin():return fail("غير مصرح",403)
 token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
 chat_id=os.getenv("TELEGRAM_CHAT_ID","").strip()
 if not token or not chat_id:return fail("إعدادات تيليجرام غير مكتملة: أضف TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID",503)
 msg="<b>✅ اختبار تيليجرام — المضارب ذكي</b>\n\nتم إرسال هذه الرسالة بنجاح من لوحة الإدارة.\n📡 القناة: "+html.escape(chat_id)
 try:
  resp=H.post("https://api.telegram.org/bot"+token+"/sendMessage",json={"chat_id":chat_id,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15)
  resp.raise_for_status()
  data=resp.json()
  if not data.get("ok"):return fail("تيليجرام رفض الرسالة",502)
  return ok(message="تم إرسال رسالة الاختبار إلى تيليجرام")
 except Exception as e:
  app.logger.warning("Telegram test failed: %s",e)
  return fail("فشل إرسال اختبار تيليجرام: "+str(e),502)

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
 if p["status"]!="pending":c.close();return fail("تمت معالجة الطلب مسبقاً",409)
 if p["plan"] not in PLANS:c.close();return fail("الباقة غير صالحة",400)
 u=c.execute("SELECT * FROM users WHERE username=?",(p["username"],)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 base=datetime.now(timezone.utc)
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
 d=request.get_json(silent=True) or {};uid=d.get("id");c=conn();u=c.execute("SELECT username,is_admin FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 if u["is_admin"]:c.close();return fail("لا يمكن حذف حساب الإدارة",400)
 c.execute("DELETE FROM payments WHERE username=?",(u["username"],));c.execute("DELETE FROM users WHERE id=?",(uid,));c.commit();c.close();return ok()

@app.post("/api/admin/users/extend")
def extend_user():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};uid=d.get("id");days=max(1,min(365,int(d.get("days",30))));c=conn();u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
 if not u:c.close();return fail("المستخدم غير موجود",404)
 base=datetime.now(timezone.utc)
 if u["subscription_until"]:
  try:base=max(base,datetime.fromisoformat(u["subscription_until"]))
  except:pass
 until=(base+timedelta(days=days)).isoformat();c.execute("UPDATE users SET subscription_until=? WHERE id=?",(until,uid));c.commit();c.close();return ok(subscription_until=until)

@app.post("/api/admin/logout")
def admin_logout():session.pop("admin",None);session.pop("admin_user",None);session.pop("user",None);return ok()

@app.get("/blog")
def blog():
 c=conn();posts=[dict(x) for x in c.execute("SELECT id,slug,title,excerpt,content,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE published=1 ORDER BY id DESC LIMIT 50").fetchall()];c.close()
 return render_template("blog.html",page_id="blog",page_title="المدونة",meta_description="مدونة المضارب ذكي: تحليلات الأسواق والعملات الرقمية والأسهم والفوركس والعقود الآجلة.",posts=posts)

@app.get("/blog/<slug>")
def blog_post(slug):
 c=conn();post=c.execute("SELECT * FROM blog_posts WHERE slug=? AND published=1",(slug,)).fetchone();c.close()
 if not post:return ("المقال غير موجود",404)
 return render_template("blog_post.html",page_id="blog-post",page_title=post["title"],meta_description=post["excerpt"] or post["title"],canonical_url=request.base_url,post=dict(post))

@app.get("/api/blog")
def blog_api():
 c=conn();posts=[dict(x) for x in c.execute("SELECT id,slug,title,excerpt,category,cover_url,author,created_at,updated_at FROM blog_posts WHERE published=1 ORDER BY id DESC LIMIT 50").fetchall()];c.close();return ok(posts=posts)

@app.post("/api/admin/blog")
def add_blog_post():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};title=str(d.get("title","")).strip();content=str(d.get("content","")).strip();excerpt=str(d.get("excerpt","")).strip();category=str(d.get("category","عام")).strip() or "عام";cover_url=str(d.get("cover_url","")).strip();author=str(d.get("author","المضارب ذكي")).strip() or "المضارب ذكي";slug=str(d.get("slug","")).strip().lower()
 import re
 if not slug:slug=re.sub(r"[^a-z0-9\u0600-\u06ff]+","-",title).strip("-") or "article-"+str(int(time.time()))
 if not title or len(title)>180 or not content:return fail("العنوان والمحتوى مطلوبان")
 if len(slug)>180:return fail("الرابط طويل")
 c=conn()
 try:c.execute("INSERT INTO blog_posts(slug,title,excerpt,content,category,cover_url,author) VALUES(?,?,?,?,?,?,?)",(slug,title,excerpt,content,category,cover_url,author));c.commit()
 except sqlite3.IntegrityError:c.close();return fail("رابط المقال مستخدم مسبقاً",409)
 c.close();return ok()

@app.get("/api/admin/blog")
def admin_blog_posts():
 if not admin():return fail("غير مصرح",403)
 c=conn();posts=[dict(x) for x in c.execute("SELECT * FROM blog_posts ORDER BY id DESC").fetchall()];c.close();return ok(posts=posts)

@app.put("/api/admin/blog/<int:post_id>")
def update_blog_post(post_id):
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};title=str(d.get("title","")).strip();content=str(d.get("content","")).strip();excerpt=str(d.get("excerpt","")).strip();category=str(d.get("category","عام")).strip() or "عام";cover_url=str(d.get("cover_url","")).strip();author=str(d.get("author","المضارب ذكي")).strip() or "المضارب ذكي";published=1 if d.get("published",True) else 0
 if not title or not content:return fail("العنوان والمحتوى مطلوبان")
 c=conn();row=c.execute("SELECT id FROM blog_posts WHERE id=?",(post_id,)).fetchone()
 if not row:c.close();return fail("المقال غير موجود",404)
 c.execute("UPDATE blog_posts SET title=?,excerpt=?,content=?,category=?,cover_url=?,author=?,published=?,updated_at=? WHERE id=?",(title,excerpt,content,category,cover_url,author,published,datetime.now(timezone.utc).isoformat(),post_id));c.commit();c.close();return ok()

@app.delete("/api/admin/blog/<int:post_id>")
def delete_blog_post(post_id):
 if not admin():return fail("غير مصرح",403)
 c=conn();cur=c.execute("DELETE FROM blog_posts WHERE id=?",(post_id,));c.commit();c.close()
 return ok() if cur.rowcount else fail("المقال غير موجود",404)

@app.get("/api/news")
def news():
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 50").fetchall()];c.close();return ok(news=r)
@app.post("/api/admin/news")
def add_news():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();c.execute("INSERT INTO news(title,content,source) VALUES(?,?,?)",(d.get("title",""),d.get("content",""),d.get("source","")));c.commit();c.close();return ok()

try:
    init()
    _seed_beginner_blog()
except Exception:
    app.logger.exception("Database initialization failed; continuing so health checks can respond")

if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))

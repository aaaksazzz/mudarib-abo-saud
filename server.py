import os, sqlite3, secrets, time, hmac, threading, urllib.parse, xml.etree.ElementTree as ET, html
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, render_template, request, jsonify, session, send_from_directory

app=Flask(__name__,template_folder="templates",static_folder=None)
BASE_DIR=os.path.dirname(os.path.abspath(__file__))
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
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE","0").strip().lower() in ("1","true","yes"))
PAID_MARKETS={x.strip() for x in os.getenv("PAID_MARKETS","futures,contracts,saudi,usmarket,forex").split(",") if x.strip()}
ADMIN_RATE={}
ADMIN_RATE_LOCK=threading.Lock()
ADMIN_MAX_FAILURES=5
ADMIN_WINDOW=300

STATIC=os.path.join(os.path.dirname(os.path.abspath(__file__)),"static")
PLANS={"7d":{"name":"7 أيام","days":7,"amount":10},"30d":{"name":"30 يوم","days":30,"amount":20},"90d":{"name":"90 يوم","days":90,"amount":30}}
MARKETS={"contracts":[("ES=F","S&P 500 E-mini"),("NQ=F","Nasdaq 100 E-mini"),("YM=F","Dow Jones E-mini"),("RTY=F","Russell 2000 E-mini"),("CL=F","Crude Oil WTI"),("GC=F","Gold Futures"),("SI=F","Silver Futures")],"saudi":[("2222.SR","أرامكو"),("1120.SR","الراجحي"),("2010.SR","سابك"),("1180.SR","الأهلي السعودي"),("7010.SR","STC"),("1211.SR","معادن"),("1150.SR","الإنماء"),("2380.SR","بترو رابغ"),("4003.SR","إكسترا"),("4200.SR","الدريس")],"usmarket":[("AAPL","Apple"),("MSFT","Microsoft"),("NVDA","NVIDIA"),("AMZN","Amazon"),("META","Meta"),("TSLA","Tesla"),("GOOGL","Alphabet"),("AMD","AMD"),("NFLX","Netflix"),("JPM","JPMorgan")],"forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("AUDUSD=X","AUD/USD"),("USDCAD=X","USD/CAD"),("USDCHF=X","USD/CHF"),("NZDUSD=X","NZD/USD"),("GC=F","Gold")]}
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
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,content TEXT,source TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);"""); c.commit(); c.close()
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
    if not current_user():return fail("سجل الدخول أولاً للوصول لهذا القسم",401)
    if not has_active_subscription():return fail("هذا القسم يتطلب اشتراكاً فعالاً",403)
    return None

def yahoo(sym,interval,range_):
 last=None
 # Yahoo sometimes rejects XAUUSD=X. Gold is handled with the futures symbol GC=F.
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
    if not key:
        raise RuntimeError("OPENAI_API_KEY غير مضبوط")
    body={
        "model":AI_MODEL,
        "input":[
            {"role":"system","content":[{"type":"input_text","text":
                "أنت محلل أسواق مالي آلي. حلل بيانات OHLCV الخام فقط. لا تستخدم مؤشرات جاهزة. "
                "لا تضمن الربح. إذا كانت البيانات غير كافية أو الإشارة ضعيفة أعد حيادي. "
                "أعد JSON فقط بالمفاتيح: items، وكل عنصر يحتوي symbol,direction,confidence,trade_ready,entry,tp1,tp2,tp3,sl,rr,reason."
            }]},
            {"role":"user","content":[{"type":"input_text","text":prompt}]}
        ],
        "text":{"format":{"type":"json_object"}}
    }
    r=H.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
        json=body,
        timeout=60
    )
    r.raise_for_status()
    data=r.json()
    txt=data.get("output_text")
    if not txt:
        for item in data.get("output",[]):
            for content in item.get("content",[]):
                if content.get("type")=="output_text":
                    txt=content.get("text")
                    break
            if txt:
                break
    if not txt:
        raise RuntimeError("AI لم يرجع نتيجة")
    return __import__("json").loads(txt)

def _local_batch(candles_by_symbol,market,interval,names):
    # تحليل محلي من حركة السعر الخام فقط؛ لا يحتاج OpenAI API.
    items=[]
    for symbol,candles in candles_by_symbol.items():
        if len(candles)<12:
            continue
        recent=candles[-12:]
        last=recent[-1]
        prev=recent[-2]
        close=float(last["close"])
        prev_close=float(prev["close"])
        if close<=0 or prev_close<=0:
            continue
        change=(close/prev_close-1.0)*100.0
        ranges=[max(0.0,float(x["high"])-float(x["low"])) for x in recent]
        avg_range=sum(ranges[:-1])/max(1,len(ranges)-1)
        recent_closes=[float(x["close"]) for x in recent]
        mid=(max(recent_closes)+min(recent_closes))/2.0
        direction="حيادي"
        confidence=50.0
        trade_ready=False
        if change>=0.35 and close>=mid:
            direction="شراء"
            confidence=min(90.0,60.0+abs(change)*8.0)
        elif change<=-0.35 and close<=mid:
            direction="بيع"
            confidence=min(90.0,60.0+abs(change)*8.0)
        if direction!="حيادي" and avg_range>0:
            entry=close
            risk=max(avg_range*1.25,close*0.004)
            if direction=="شراء":
                sl=max(0.0,entry-risk)
                tp1=entry+risk*1.5
                tp2=entry+risk*2.0
                tp3=entry+risk*2.5
            else:
                sl=entry+risk
                tp1=max(0.0,entry-risk*1.5)
                tp2=max(0.0,entry-risk*2.0)
                tp3=max(0.0,entry-risk*2.5)
            rr=2.0
            trade_ready=confidence>=65
        else:
            entry=tp1=tp2=tp3=sl=rr=0.0
        items.append({
            "symbol":symbol,"direction":direction,"confidence":round(confidence,1),
            "trade_ready":trade_ready,"entry":entry,"tp1":tp1,"tp2":tp2,
            "tp3":tp3,"sl":sl,"rr":rr,
            "reason":"تحليل محلي لحركة السعر الخام بدون مؤشرات أو مفتاح OpenAI."
        })
    return items

def ai_batch(candles_by_symbol,market,interval,names):
    now=time.time()
    cache_key=market+"|"+interval+"|"+",".join(sorted(candles_by_symbol.keys()))
    cached=AI_CACHE.get(cache_key)
    if cached and now-cached["at"]<AI_CACHE_TTL:
        return cached["items"]
    # إذا لم يوجد مفتاح OpenAI، استخدم التحليل المحلي بدل إرجاع 502.
    if not os.getenv("OPENAI_API_KEY","").strip():
        items=_local_batch(candles_by_symbol,market,interval,names)
        AI_CACHE[cache_key]={"at":now,"items":items}
        return items
    payload=[]
    for symbol,candles in candles_by_symbol.items():
        payload.append({
            "symbol":symbol,
            "name":names.get(symbol,symbol),
            "candles":candles[-40:]
        })
    prompt=(
        "السوق: "+market+"\\nالفريم: "+interval+"\\n"
        "حلل كل أصل بشكل مستقل اعتماداً على OHLCV الخام المرفق. "
        "لا تستخدم RSI/MACD/EMA/SMA أو أي مؤشر تقني جاهز، ولا تعتمد على نظام نقاط برمجي. "
        "إذا وجدت صفقة واضحة أعد شراء أو بيع، وإلا حيادي. "
        "للصفقة: اجعل الدخول قريباً من آخر سعر، وحدد TP/SL من بنية الحركة والمخاطرة، وليس كنسبة ثابتة. "
        "trade_ready=true فقط عند وجود أفضلية واضحة. "
        "البيانات:\\n"+__import__("json").dumps(payload,ensure_ascii=False,separators=(",",":"))
    )
    try:
        result=_ai_json(prompt)
        items=result.get("items",[])
    except Exception as e:
        app.logger.warning("OpenAI unavailable; using local analysis: %s",e)
        items=_local_batch(candles_by_symbol,market,interval,names)
    AI_CACHE[cache_key]={"at":now,"items":items}
    return items

def _decorate_ai(item,market,interval,name):
    d=item.get("direction","حيادي")
    conf=round(float(item.get("confidence",0) or 0),1)
    return {
        "symbol":item.get("symbol",""),
        "displayName":name or item.get("symbol",""),
        "market":market,"interval":interval,
        "signal":"شراء قوي" if d=="شراء" and conf>=80 else "بيع قوي" if d=="بيع" and conf>=80 else d,
        "direction":d,
        "tradeReady":bool(item.get("trade_ready",False)) and d!="حيادي" and conf>=60,
        "confidence":conf,
        "price":float(item.get("entry",0) or 0),
        "entry":float(item.get("entry",0) or 0),
        "tp1":float(item.get("tp1",0) or 0),
        "tp2":float(item.get("tp2",0) or 0),
        "tp3":float(item.get("tp3",0) or 0),
        "sl":float(item.get("sl",0) or 0),
        "rr":float(item.get("rr",0) or 0),
        "reason":item.get("reason",""),
        "ai":True,
        "updatedAt":datetime.now(timezone.utc).isoformat()
    }

def _scan_yahoo_symbols(symbols,market,interval,limit):
    yi={"5m":"5m","15m":"15m","30m":"30m","1H":"1h","4H":"1h","1D":"1d"}.get(interval,"1d")
    rg="5d" if yi=="5m" else "1mo" if yi in ("15m","30m") else "1y"
    candles={}; names=dict(symbols)
    with ThreadPoolExecutor(max_workers=min(8,len(symbols) or 1)) as ex:
        fs={ex.submit(yahoo,s,yi,rg):s for s,n in symbols[:limit]}
        for f in as_completed(fs):
            sym=fs[f]
            try:
                c=f.result()
                if len(c)>=12:candles[sym]=c
            except Exception as e:app.logger.warning("AI data failed %s: %s",sym,e)
    ai=ai_batch(candles,market,interval,names)
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol"))) for x in ai if x.get("symbol") in candles],
                  key=lambda x:x["confidence"],reverse=True)

def _scan_okx(market,interval,limit):
    bar={"5m":"5m","15m":"15m","30m":"30m","1H":"1H","4H":"4H","1D":"1D"}.get(interval,"15m")
    typ="SPOT" if market=="crypto" else "SWAP"
    suffix="-USDT" if market=="crypto" else "-USDT-SWAP"
    r=H.get("https://www.okx.com/api/v5/market/tickers",params={"instType":typ},timeout=12);r.raise_for_status()
    items=[x for x in r.json().get("data",[]) if x.get("instId","").endswith(suffix)]
    items=sorted(items,key=lambda x:float(x.get("volCcy24h",0) or 0),reverse=True)[:limit]
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
    return sorted([_decorate_ai(x,market,interval,names.get(x.get("symbol"),x.get("symbol"))) for x in ai if x.get("symbol") in candles],
                  key=lambda x:x["confidence"],reverse=True)


MONTH_CODES={3:"H",6:"M",9:"U",12:"Z",1:"F",2:"G",4:"J",5:"K",7:"N",8:"Q",10:"V",11:"X"}
MONTH_NAMES={1:"يناير",2:"فبراير",3:"مارس",4:"أبريل",5:"مايو",6:"يونيو",7:"يوليو",8:"أغسطس",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}

def _business_days_before(dt,n):
    d=dt
    left=n
    while left>0:
        d-=timedelta(days=1)
        if d.weekday()<5:left-=1
    return d

def _third_friday(year,month):
    d=datetime(year,month,1,tzinfo=timezone.utc)
    while d.weekday()!=4:d+=timedelta(days=1)
    return d+timedelta(days=14)

def _next_quarter_after(dt):
    for year in range(dt.year,dt.year+2):
        for month in (3,6,9,12):
            if (year,month)>(dt.year,dt.month):
                return year,month
    return dt.year+1,3

def _quarter_contracts(now):
    # CME's customary U.S. equity-index roll is the Monday before the
    # third Friday of the expiration month.
    cy,cm=_next_quarter_after(now)
    exp=_third_friday(cy,cm)
    roll=exp-timedelta(days=4)
    if now.date()>=roll.date():
        current=(cy,cm); current_exp=exp; current_roll=roll
        ny,nm=_next_quarter_after(exp)
        next_exp=_third_friday(ny,nm)
        next_roll=next_exp-timedelta(days=4)
        nxt=(ny,nm)
    else:
        py,pm=cy,cm
        # previous quarter is the current lead month before the roll.
        prev_month={3:12,6:3,9:6,12:9}[pm]
        prev_year=py-1 if pm==3 else py
        current=(prev_year,prev_month)
        current_exp=_third_friday(prev_year,prev_month)
        current_roll=current_exp-timedelta(days=4)
        nxt=(cy,cm); next_exp=exp; next_roll=roll
    return current,current_roll,current_exp,nxt,next_roll,next_exp

def _monthly_contract(base,now,rule):
    # Pick the first contract whose official-style termination has not passed.
    # Exact exchange holidays can move a date by one business day; CME's
    # expiration calendar remains the authority for final settlement dates.
    y,m=now.year,now.month
    for _ in range(15):
        if rule=="CL":
            # CL terminates on the third business day before the 25th of
            # the month preceding delivery.
            py,pm=y,m-1
            if pm==0: py,pm=y-1,12
            anchor=datetime(py,pm,25,tzinfo=timezone.utc)
            term=_business_days_before(anchor,3)
            # The delivery month is y,m.
            if term.date()>=now.date():
                cur=(y,m); cur_exp=term
                break
        elif rule=="GC":
            # GC terminates on the third-last business day of delivery month.
            last=datetime(y,m+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m<12 else datetime(y,12,31,tzinfo=timezone.utc)
            # Find last three business days; third-last is the termination.
            business=[last]
            while len([x for x in business if x.weekday()<5])<3:
                business.append(business[-1]-timedelta(days=1))
            bs=sorted([x for x in business if x.weekday()<5])
            term=bs[0]
            if term.date()>=now.date():
                cur=(y,m); cur_exp=term
                break
        elif rule=="SI":
            last=datetime(y,m+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m<12 else datetime(y,12,31,tzinfo=timezone.utc)
            d=last; count=0; term=None
            while d>=last-timedelta(days=10):
                if d.weekday()<5:
                    count+=1
                    if count==3: term=d; break
                d-=timedelta(days=1)
            if term and term.date()>=now.date():
                cur=(y,m); cur_exp=term
                break
        m+=1
        if m>12:y,m=y+1,1
    else:
        cur=(now.year,now.month); cur_exp=now
    # For commodities, use the next listed/nearby month after current.
    if rule=="SI":
        allowed=(3,5,7,9,12)
        candidates=[]
        yy,mm=cur
        for k in range(1,15):
            nm=mm+k
            ny=yy+(nm-1)//12; nm=((nm-1)%12)+1
            if nm in allowed:candidates.append((ny,nm))
        nxt=candidates[0]
    else:
        ny,nm=cur[0],cur[1]+1
        if nm>12:ny,nm=ny+1,1
        nxt=(ny,nm)
    if rule=="CL":
        py,nm=nxt[0],nxt[1]-1
        if nm==0:py,nm=py-1,12
        anchor=datetime(py,nm,25,tzinfo=timezone.utc)
        next_exp=_business_days_before(anchor,3)
    elif rule in ("GC","SI"):
        y2,m2=nxt
        last=datetime(y2,m2+1,1,tzinfo=timezone.utc)-timedelta(days=1) if m2<12 else datetime(y2,12,31,tzinfo=timezone.utc)
        d=last; count=0; next_exp=None
        while d>=last-timedelta(days=10):
            if d.weekday()<5:
                count+=1
                if count==3:next_exp=d;break
            d-=timedelta(days=1)
    roll=_business_days_before(cur_exp,5)
    return cur,roll,cur_exp,nxt,_business_days_before(next_exp,5),next_exp

def _contract_row(name,sym,rule,now):
    if rule=="quarter":
        cur,roll,exp,nxt,nroll,nexp=_quarter_contracts(now)
    else:
        cur,roll,exp,nxt,nroll,nexp=_monthly_contract(sym,now,rule)
    def label(pair):
        yy,mm=pair
        return f"{sym}{MONTH_CODES[mm]}{str(yy)[-2:]} — {MONTH_NAMES[mm]} {yy}"
    return {
        "name":name,"symbol":sym,
        "current":label(cur),"next":label(nxt),
        "currentCode":sym+MONTH_CODES[cur[1]]+str(cur[0])[-2:],
        "nextCode":sym+MONTH_CODES[nxt[1]]+str(nxt[0])[-2:],
        "roll":roll.strftime("%Y-%m-%d"),
        "expiry":exp.strftime("%Y-%m-%d"),
        "nextRoll":nroll.strftime("%Y-%m-%d"),
        "nextExpiry":nexp.strftime("%Y-%m-%d"),
        "rollNote":"تاريخ Roll مخصص للمؤشرات حسب جدول CME؛ للسلع هو تاريخ آلي قبل آخر تداول."
    }

CONTRACT_SPECS=[
    ("S&P 500 E-mini","ES","quarter"),
    ("Nasdaq 100 E-mini","NQ","quarter"),
    ("Dow Jones E-mini","YM","quarter"),
    ("Russell 2000 E-mini","RTY","quarter"),
    ("WTI النفط","CL","CL"),
    ("الذهب","GC","GC"),
    ("الفضة","SI","SI"),
]

@app.get("/api/contracts/calendar")
def contracts_calendar():
    now=datetime.now(timezone.utc)
    rows=[_contract_row(*x,now) for x in CONTRACT_SPECS]
    return ok(contracts=rows,source="CME rules + automatic calculation",updatedAt=now.isoformat())

def scan(market,interval):
    if market=="crypto": return _scan_okx(market,interval,25)
    if market=="futures": return _scan_okx(market,interval,20)
    if market=="contracts": return _scan_yahoo_symbols(MARKETS["contracts"],market,interval,7)
    if market in ("saudi","usmarket","forex"): return _scan_yahoo_symbols(MARKETS[market],market,interval,len(MARKETS[market]))
    raise ValueError("السوق غير معروف")

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

HOME_CACHE={"at":0,"data":None}
HOME_CACHE_TTL=60

@app.get("/api/home/overview")
def home_overview():
 global HOME_CACHE
 try:
  now=time.time()
  if HOME_CACHE["data"] is not None and now-HOME_CACHE["at"]<HOME_CACHE_TTL:
   return ok(markets=HOME_CACHE["data"],updatedAt=datetime.now(timezone.utc).isoformat())
  configs=[("crypto","15m"),("contracts","15m"),("saudi","1D"),("usmarket","1D"),("forex","1H")]
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
  HOME_CACHE={"at":time.time(),"data":data}
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
  if market not in ("crypto","futures","contracts","saudi","usmarket","forex"):return fail("السوق غير معروف")
  access=require_market_access(market)
  if access:return access
  return ok(results=scan(market,interval)[:limit],market=market,interval=interval)
 except Exception as e:return fail("تعذر جلب بيانات السوق حالياً",502)
@app.get("/health")
def health():
 return jsonify(ok=True,status="healthy",service="mudarib-abo-saud",time=datetime.now(timezone.utc).isoformat()),200
@app.get("/api/me")
def me():
 u=session.get("user")
 session_admin=bool(session.get("admin"))
 if not u:return ok(user=None,admin=session_admin,subscription_active=False,paid_markets=sorted(PAID_MARKETS))
 c=conn();r=c.execute("SELECT id,username,email,name,is_admin,subscription_until,created_at FROM users WHERE username=?",(u,)).fetchone();c.close()
 return ok(user=dict(r) if r else None,admin=session_admin or bool(r and r["is_admin"]),subscription_active=has_active_subscription(),paid_markets=sorted(PAID_MARKETS))
@app.post("/api/auth/register")
def register():
 d=request.get_json(silent=True) or {}; name=str(d.get("name","")).strip();email=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
 if not name or "@" not in email or len(pw)<8:return fail("أدخل الاسم والبريد وكلمة مرور 8 أحرف على الأقل")
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
 if len(txid)<6 or len(txid)>200:return fail("رقم العملية غير صالح")
 c=conn()
 if c.execute("SELECT id FROM payments WHERE txid=? AND status IN ('pending','approved')",(txid,)).fetchone():
  c.close();return fail("رقم العملية مستخدم مسبقاً",409)
 c.execute("INSERT INTO payments(username,plan,txid) VALUES(?,?,?)",(session["user"],plan,txid));c.commit();c.close();return ok()
def admin():return bool(session.get("admin"))
@app.post("/api/admin/login")
def admin_login():
 d=request.get_json(silent=True) or {}
 admin_user=os.getenv("ADMIN_USERNAME","").strip()
 admin_pass=os.getenv("ADMIN_PASSWORD","")
 if not admin_user or not admin_pass:return fail("إعدادات دخول المشرف غير مكتملة في بيئة التشغيل",503)
 ip=request.headers.get("X-Forwarded-For",request.remote_addr or "unknown").split(",")[0].strip()
 now=time.time()
 with ADMIN_RATE_LOCK:
  state=ADMIN_RATE.get(ip,{"at":now,"failures":0})
  if now-state["at"]>ADMIN_WINDOW:state={"at":now,"failures":0}
  if state["failures"]>=ADMIN_MAX_FAILURES:return fail("محاولات دخول كثيرة، حاول بعد 5 دقائق",429)
  valid=hmac.compare_digest(str(d.get("username","")),admin_user) and hmac.compare_digest(str(d.get("password","")),admin_pass)
  if not valid:
   state["failures"]+=1;state["at"]=now;ADMIN_RATE[ip]=state
   return fail("بيانات الإدارة غير صحيحة",401)
  ADMIN_RATE.pop(ip,None)
 session["admin"]=True;session["admin_user"]=admin_user;return ok()
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
 session.pop("admin",None);session.pop("admin_user",None);session.pop("user",None);return ok()

@app.get("/api/news")
def news():
 c=conn();r=[dict(x) for x in c.execute("SELECT * FROM news ORDER BY id DESC LIMIT 50").fetchall()];c.close();return ok(news=r)
@app.post("/api/admin/news")
def add_news():
 if not admin():return fail("غير مصرح",403)
 d=request.get_json(silent=True) or {};c=conn();c.execute("INSERT INTO news(title,content,source) VALUES(?,?,?)",(d.get("title",""),d.get("content",""),d.get("source","")));c.commit();c.close();return ok()
# Never let database initialization prevent Gunicorn from starting.
# Health checks must be able to reach the Flask app even if the DB has a startup problem.
try:
    init()
except Exception:
    app.logger.exception("Database initialization failed; continuing so health checks can respond")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","8080")))

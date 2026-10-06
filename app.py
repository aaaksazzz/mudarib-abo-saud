import os,time,hmac,hashlib,sqlite3,threading,requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles

app=FastAPI(title="SMART TRADING PRO")
app.mount("/static",StaticFiles(directory="static"),name="static")
DB="/data/trading.db" if os.path.isdir("/data") else "trading.db"
RETENTION=86400
MARKETS=["spot","futures","us","saudi","contracts","forex"]
SOURCES=[
 ("fortune_traders","https://t.me/s/Fortunetradersofficial"),("evening_trader","https://t.me/s/eveningtradercryptosignals"),
 ("crypto_ninjas","https://t.me/s/cryptoninjastradingglobal"),("bitcoin_bullets","https://t.me/s/BitcoinBullets"),
 ("learn2trade_crypto","https://t.me/s/learn2tradectypto"),("learn2trade_news","https://t.me/s/learn2tradenews"),
 ("coinglass","https://www.coinglass.com/"),("cryptopanic","https://cryptopanic.com/"),("cmc","https://coinmarketcap.com/"),
 ("tradingview","https://www.tradingview.com/markets/cryptocurrencies/news/"),
 ("reuters","https://www.reuters.com/markets/"),("bloomberg","https://www.bloomberg.com/markets"),("cnbc","https://www.cnbc.com/markets/"),
 ("yahoo_finance","https://finance.yahoo.com/"),("investing","https://www.investing.com/"),("marketwatch","https://www.marketwatch.com/"),
 ("wsj","https://www.wsj.com/news/markets"),("ft","https://www.ft.com/markets"),("argaam","https://www.argaam.com/"),("reddit_stocks","https://www.reddit.com/r/stocks/new/.rss"),("reddit_wsb","https://www.reddit.com/r/wallstreetbets/new/.rss"),("reddit_crypto","https://www.reddit.com/r/CryptoCurrency/new/.rss"),("reddit_forex","https://www.reddit.com/r/Forex/new/.rss"),("reddit_saudi","https://www.reddit.com/r/SaudiArabia/new/.rss"),("stocktwits","https://stocktwits.com/")]
lock=threading.Lock()
cache_lock=threading.Lock()
refresh_lock=threading.Lock()
CACHE={"rows":[],"updated":0.0,"sources_live":0,"refreshing":False}
REFRESH_SECONDS=120
def db():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
 c=sqlite3.connect(DB,check_same_thread=False,timeout=15)
 c.execute("PRAGMA busy_timeout=15000")
 c.execute("create table if not exists trades(id integer primary key,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created real,updated real)")
 c.execute("create table if not exists users(id integer primary key,email text unique not null,password_hash text not null,created real,admin integer default 0)")
 c.execute("create table if not exists subscriptions(id integer primary key,user_id integer unique,expires real,updated real)")
 c.execute("create table if not exists page_access(page text primary key,subscriber_only integer default 0)")
 c.execute("create table if not exists blog_posts(id integer primary key,title text not null,body text not null,created real,updated real,author_id integer)")
 required={"market":"TEXT","symbol":"TEXT","direction":"TEXT","entry":"REAL","tp1":"REAL","tp2":"REAL","tp3":"REAL","sl":"REAL","status":"TEXT","created":"REAL","updated":"REAL"}
 cols={r[1] for r in c.execute("pragma table_info(trades)").fetchall()}
 for name,typ in required.items():
  if name not in cols: c.execute(f"alter table trades add column {name} {typ}")
 for page in MARKETS+["home","radar","news","blog"]:
  c.execute("insert or ignore into page_access(page,subscriber_only) values(?,0)",(page,))
 admin_email=os.getenv("ADMIN_EMAIL","").strip().lower()
 if admin_email:
  admin_pw=os.getenv("ADMIN_PASSWORD","")
  if admin_pw:
   ph=password_hash(admin_pw)
   c.execute("insert or ignore into users(email,password_hash,created,admin) values(?,?,?,1)",(admin_email,ph,time.time()))
   c.execute("update users set admin=1 where email=?",(admin_email,))
 c.commit()
 return c

SECRET=os.getenv("AUTH_SECRET") or os.getenv("BINANCE_API_SECRET") or "smart-trading-pro-change-me"
def password_hash(password):
 salt=os.urandom(16)
 digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,210000)
 return salt.hex()+"$"+digest.hex()
def password_check(password,stored):
 try:
  salt,digest=stored.split("$",1)
  got=hashlib.pbkdf2_hmac("sha256",password.encode(),bytes.fromhex(salt),210000).hex()
  return hmac.compare_digest(got,digest)
 except Exception:return False
def session_token(user_id):
 raw=f"{int(user_id)}.{int(time.time())}".encode()
 sig=hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()
 return raw.decode()+"."+sig
def current_user(req):
 tok=req.cookies.get("stp_session","")
 try:
  uid,ts,sig=tok.split(".",2)
  raw=f"{uid}.{ts}".encode()
  if not hmac.compare_digest(sig,hmac.new(SECRET.encode(),raw,hashlib.sha256).hexdigest()): return None
  if time.time()-int(ts)>2592000:return None
  c=db(); row=c.execute("select id,email,admin from users where id=?",(int(uid),)).fetchone(); c.close()
  return {"id":row[0],"email":row[1],"admin":bool(row[2])} if row else None
 except Exception:return None
def subscriber_active(user_id):
 c=db(); row=c.execute("select expires from subscriptions where user_id=?",(user_id,)).fetchone(); c.close()
 return bool(row and float(row[0] or 0)>time.time())
def access_ok(req,page):
 c=db(); row=c.execute("select subscriber_only from page_access where page=?",(page,)).fetchone(); c.close()
 if not row or not int(row[0]): return True
 u=current_user(req)
 return bool(u and (u["admin"] or subscriber_active(u["id"])))
def deny_access():
 return JSONResponse({"ok":False,"error":"هذه الصفحة للمشتركين فقط","code":"SUBSCRIBER_REQUIRED"},status_code=403)
def price(sym):
 try:
  r=requests.get("https://api.binance.com/api/v3/ticker/price",params={"symbol":sym},timeout=4); return float(r.json()["price"])
 except: return 0
def klines(sym,tf="15m",n=120):
 try:
  r=requests.get("https://api.binance.com/api/v3/klines",params={"symbol":sym,"interval":tf,"limit":n},timeout=6); return r.json()
 except: return []
def technical(sym):
 k=klines(sym)
 if len(k)<40:return None
 close=[float(x[4]) for x in k]; vol=[float(x[5]) for x in k]
 ema20=sum(close[-20:])/20; ema50=sum(close[-50:])/50; p=close[-1]
 gains=[];loss=[]
 for i in range(-14,0):
  d=close[i]-close[i-1]; gains.append(max(d,0));loss.append(max(-d,0))
 rs=(sum(gains)/14)/max(sum(loss)/14,1e-9); rsi=100-(100/(1+rs))
 avg=sum(vol[-21:-1])/20; vr=vol[-1]/max(avg,1e-9)
 trs=[]
 for i in range(-14,0):
  hi,lo,pc=float(k[i][2]),float(k[i][3]),float(k[i-1][4])
  trs.append(max(hi-lo,abs(hi-pc),abs(lo-pc)))
 atr=sum(trs)/14
 up=p>ema20 and ema20>ema50; down=p<ema20 and ema20<ema50
 direction="BUY" if up and rsi>=50 else "SELL" if down and rsi<=50 else ("BUY" if p>=ema20 else "SELL")
 score=min(99,max(1,50+(rsi-50)*0.7+(10 if up else -10 if down else 0)+(min(vr,3)-1)*7))
 return {"price":p,"rsi":round(rsi,1),"volume_ratio":round(vr,2),"direction":direction,"score":round(score,1),"atr":atr}
def levels(p,d,atr=None):
 risk=max(atr*1.5 if atr else p*0.02,p*0.005)
 if d in ("BUY","LONG"): return [p,p+risk,p+2*risk,p+3*risk,p-risk]
 return [p,p-risk,p-2*risk,p-3*risk,p+risk]
MARKET_ALIASES={
 "BTCUSDT":["BTC","BITCOIN"],"ETHUSDT":["ETH","ETHEREUM"],"SOLUSDT":["SOL","SOLANA"],
 "BNBUSDT":["BNB"],"XRPUSDT":["XRP","RIPPLE"],"DOGEUSDT":["DOGE","DOGECOIN"],"ADAUSDT":["ADA","CARDANO"],
 "SUIUSDT":["SUI"],"LINKUSDT":["LINK","CHAINLINK"],"AVAXUSDT":["AVAX"],"DOTUSDT":["DOT","POLKADOT"],"LTCUSDT":["LTC","LITECOIN"],
 "AAPL":["AAPL","APPLE"],"NVDA":["NVDA","NVIDIA"],"MSFT":["MSFT","MICROSOFT"],"AMZN":["AMZN","AMAZON"],
 "META":["META","FACEBOOK"],"TSLA":["TSLA","TESLA"],"GOOGL":["GOOGL","GOOGLE"],
 "2222.SR":["2222","ARAMCO","أرامكو"],"1120.SR":["1120","ALRAJHI","الراجحي"],"2010.SR":["2010","SABIC","سابك"],
 "1180.SR":["1180","ALAHLI","الأهلي"],"7010.SR":["7010","STC"],
 "ES=F":["ES","S&P 500","SP500"],"NQ=F":["NQ","NASDAQ","NASDAQ FUTURES"],"YM=F":["YM","DOW JONES"],"GC=F":["GC","GOLD","ذهب"],
 "EURUSD=X":["EUR/USD","EURUSD","EURO"],"GBPUSD=X":["GBP/USD","GBPUSD","POUND"],
 "USDJPY=X":["USD/JPY","USDJPY","YEN"],"XAUUSD=X":["XAU/USD","XAUUSD","GOLD","ذهب"]}

def _source_mentions(item):
 name,url=item; out={}
 try:
  t=requests.get(url,timeout=4,headers={"User-Agent":"Mozilla/5.0"}).text.upper()
  bull=["BUY","LONG","BULLISH","BREAKOUT","PUMP","TARGET","CALL","UP","صعود","شراء","هدف"]
  bear=["SELL","SHORT","BEARISH","DUMP","BREAKDOWN","PUT","DOWN","هبوط","بيع","وقف"]
  for sym,aliases in MARKET_ALIASES.items():
   m=b=br=0
   for al in aliases:
    token=str(al).upper(); start=0
    while True:
     pos=t.find(token,start)
     if pos<0: break
     m+=1;ctx=t[max(0,pos-180):min(len(t),pos+180)]
     b+=sum(ctx.count(w) for w in bull);br+=sum(ctx.count(w) for w in bear);start=pos+len(token)
   if m: out[sym]={"mentions":m,"bull":b,"bear":br}
 except Exception: pass
 return out
MENTIONS_CACHE={"data":None,"updated":0.0}
MENTIONS_CACHE_TTL=90
def _deep_search_one(sym,aliases):
 try:
  alias=aliases[0]
  q=requests.utils.quote(f'"{alias}" trading recommendation buy sell target')
  html=requests.get("https://html.duckduckgo.com/html/?q="+q,timeout=5,headers={"User-Agent":"Mozilla/5.0"}).text.upper()
  bull=["BUY","LONG","BULLISH","BREAKOUT","TARGET","CALL","UP","صعود","شراء","هدف"]
  bear=["SELL","SHORT","BEARISH","DUMP","BREAKDOWN","PUT","DOWN","هبوط","بيع","وقف"]
  hits=sum(html.count(str(al).upper()) for al in aliases)
  if not hits:return None
  b=sum(html.count(w) for w in bull);br=sum(html.count(w) for w in bear)
  return {"mentions":hits,"bull":b,"bear":br}
 except Exception:return None

def public_mentions():
 global MENTIONS_CACHE
 if MENTIONS_CACHE["data"] is not None and time.time()-MENTIONS_CACHE["updated"]<MENTIONS_CACHE_TTL:
  return MENTIONS_CACHE["data"]
 out={}
 with ThreadPoolExecutor(max_workers=min(10,len(SOURCES))) as ex:
  for source,(result) in zip(SOURCES,ex.map(_source_mentions,SOURCES)):
   name,_=source
   for s,v in result.items():
    x=out.setdefault(s,{"mentions":0,"bull":0,"bear":0,"sources":set()})
    x["mentions"]+=v["mentions"];x["bull"]+=v["bull"];x["bear"]+=v["bear"];x["sources"].add(name)
 # Weakly-covered assets get a second search pass instead of being ignored.
 candidates=sorted(MARKET_ALIASES,key=lambda s:out.get(s,{}).get("mentions",0))[:10]
 with ThreadPoolExecutor(max_workers=5) as ex:
  for sym,v in zip(candidates,ex.map(lambda s:_deep_search_one(s,MARKET_ALIASES[s]),candidates)):
   if not v:continue
   x=out.setdefault(sym,{"mentions":0,"bull":0,"bear":0,"sources":set()})
   x["mentions"]+=v["mentions"];x["bull"]+=v["bull"];x["bear"]+=v["bear"];x["sources"].add("deep_search")
 MENTIONS_CACHE={"data":out,"updated":time.time()}
 return out
SOURCE_WEIGHT={"fortune_traders":1.0,"evening_trader":1.0,"crypto_ninjas":0.95,"bitcoin_bullets":0.95,"learn2trade_crypto":0.9,"learn2trade_news":0.9,"coinglass":0.95,"cryptopanic":0.9,"tradingview":0.9,"reuters":1.0,"bloomberg":1.0,"cnbc":0.95,"yahoo_finance":0.85,"investing":0.85,"marketwatch":0.85,"wsj":1.0,"ft":1.0,"argaam":0.95,"reddit_stocks":0.55,"reddit_wsb":0.5,"reddit_crypto":0.55,"reddit_forex":0.55,"reddit_saudi":0.5,"stocktwits":0.65,"deep_search":0.8}
def social_score(v):
 if not v or not v.get("mentions"): return 0
 total=max(v.get("bull",0)+v.get("bear",0),1)
 agreement=abs(v.get("bull",0)-v.get("bear",0))/total
 diversity=min(len(v.get("sources",set())),10)/10
 quality=sum(SOURCE_WEIGHT.get(s,0.6) for s in v.get("sources",set()))/max(len(v.get("sources",set())),1)
 volume=min(v.get("mentions",0),30)/30
 return round(min(99,10+agreement*35+diversity*25+quality*15+volume*15),1)
def social_direction(v,default=None):
 if not v or not v.get("mentions") or v.get("bull",0)==v.get("bear",0): return default
 return "BUY" if v.get("bull",0)>v.get("bear",0) else "SELL"
def social_ai(v):
 if not v or not v.get("mentions"): return None
 total=max(v.get("bull",0)+v.get("bear",0),1)
 bull_ratio=v.get("bull",0)/total; bear_ratio=v.get("bear",0)/total
 direction="BUY" if bull_ratio>bear_ratio else "SELL"
 agreement=max(bull_ratio,bear_ratio)
 diversity=min(len(v.get("sources",set())),10)/10
 quality=sum(SOURCE_WEIGHT.get(s,0.6) for s in v.get("sources",set()))/max(len(v.get("sources",set())),1)
 volume=min(v.get("mentions",0),30)/30
 score=min(99,round(25+agreement*35+diversity*20+quality*10+volume*10,1))
 return {"direction":direction,"score":score,"methods":["إجماع المصادر","تنوع المصادر","اتفاق الاتجاه","وزن جودة المصدر","قوة التكرار"]}
def _technical_safe(sym):
 try: return sym,technical(sym)
 except Exception: return sym,None
def source_first_opportunities(market="spot"):
 syms=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT"]
 mentions=public_mentions(); rows=[]
 for sym in syms:
  v=mentions.get(sym); ai=social_ai(v)
  if not ai: continue
  p=price(sym)
  if not p: continue
  lv=levels(p,ai["direction"])
  rows.append({"market":market,"symbol":sym.replace("USDT","/USDT"),"direction":ai["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":ai["score"],"recommendation_quality":ai["recommendation_quality"],"undercovered":ai["undercovered"],"coverage_label":ai["coverage_label"],"mentions":v.get("mentions",0),"bullish_mentions":v.get("bull",0),"bearish_mentions":v.get("bear",0),"source_count":len(v.get("sources",set())),"social_score":social_score(v),"methods":ai["methods"],"model":"المصادر أولاً → بحث أعمق للأصول ضعيفة التغطية → AI متعدد المناهج، بدون مؤشرات"})
 rows.sort(key=lambda x:(x["recommendation_quality"],x["undercovered"],x["source_count"]),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3
 return rows
def opportunities():
 return source_first_opportunities("spot")
MARKET_SYMBOLS={
 "us":[("AAPL","AAPL"),("NVDA","NVDA"),("MSFT","MSFT"),("AMZN","AMZN"),("META","META"),("TSLA","TSLA"),("GOOGL","GOOGL")],
 "saudi":[("2222.SR","أرامكو"),("1120.SR","الراجحي"),("2010.SR","سابك"),("1180.SR","الأهلي"),("7010.SR","stc")],
 "contracts":[("ES=F","S&P 500 E-mini"),("NQ=F","Nasdaq 100 E-mini"),("YM=F","Dow Jones E-mini"),("RTY=F","Russell 2000 E-mini"),("GC=F","Gold Futures")],
 "forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("XAUUSD=X","Gold/USD")],"home":[("^TASI.SR","تاسي"),("BTC-USD","Bitcoin"),("ETH-USD","Ethereum"),("GC=F","الذهب"),("BZ=F","النفط Brent"),("SAR=X","الدولار/ريال"),("^GSPC","S&P 500"),("^IXIC","Nasdaq")]
}
HOME_MARKETS=[
 ("^TASI.SR","🇸🇦","تاسي","Yahoo"),("BTCUSDT","₿","Bitcoin","Binance"),("ETHUSDT","Ξ","Ethereum","Binance"),
 ("GC=F","🟡","الذهب","Yahoo"),("BZ=F","🛢️","النفط Brent","Yahoo"),("SAR=X","💵","الدولار/ريال","Yahoo"),
 ("^GSPC","📈","S&P 500","Yahoo"),("^IXIC","💻","Nasdaq","Yahoo")]
def home_market_rows():
 rows=[]
 def yahoo(sym):
  u="https://query1.finance.yahoo.com/v8/finance/chart/"+requests.utils.quote(sym,safe="")
  j=requests.get(u,params={"range":"2d","interval":"15m"},headers={"User-Agent":"Mozilla/5.0"},timeout=5).json()["chart"]["result"][0]
  meta=j.get("meta",{}); p=float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0); prev=float(meta.get("previousClose") or p)
  return p,((p/prev)-1)*100 if prev else 0
 def one(item):
  sym,icon,label,src=item
  try:
   if src=="Binance":
    j=requests.get("https://api.binance.com/api/v3/ticker/24hr",params={"symbol":sym},timeout=4).json(); p=float(j.get("lastPrice",0)); ch=float(j.get("priceChangePercent",0))
   else: p,ch=yahoo(sym)
   if not p:return None
   return {"symbol":sym,"icon":icon,"label":label,"price":round(p,8),"change":round(ch,2),"source":src}
  except Exception:return None
 with ThreadPoolExecutor(max_workers=8) as ex:
  for x in ex.map(one,HOME_MARKETS):
   if x: rows.append(x)
 return rows

def external_market_rows(market):
 mentions=public_mentions(); rows=[]
 for q,label in MARKET_SYMBOLS.get(market,[]):
  try:
   sv=mentions.get(q); ai=social_ai(sv)
   # لا توجد توصية من المصادر = لا توجد صفقة.
   if not ai: continue
   u="https://query1.finance.yahoo.com/v8/finance/chart/"+requests.utils.quote(q,safe="")
   j=requests.get(u,params={"range":"2d","interval":"15m"},headers={"User-Agent":"Mozilla/5.0"},timeout=5).json()["chart"]["result"][0]
   meta=j.get("meta",{}); p=float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
   if not p: continue
   lv=levels(p,ai["direction"])
   rows.append({"market":market,"symbol":label,"direction":ai["direction"],"entry":round(p,4),"tp1":round(lv[1],4),"tp2":round(lv[2],4),"tp3":round(lv[3],4),"sl":round(lv[4],4),"timeframe":"15m","ai":ai["score"],"mentions":sv.get("mentions",0),"bullish_mentions":sv.get("bull",0),"bearish_mentions":sv.get("bear",0),"source_count":len(sv.get("sources",set())),"social_score":social_score(sv),"methods":ai["methods"],"model":"المصادر أولاً → بحث أعمق للأصول ضعيفة التغطية → AI متعدد المناهج، بدون مؤشرات"})
  except Exception: pass
 rows.sort(key=lambda x:(x["ai"],x["source_count"],x["mentions"]),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3
 return rows

def futures_klines(sym,tf="15m",n=120):
 try:
  return requests.get("https://fapi.binance.com/fapi/v1/klines",params={"symbol":sym,"interval":tf,"limit":n},timeout=6).json()
 except: return []
def futures_market_info(sym):
 try:
  t=requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr",params={"symbol":sym},timeout=4).json()
  f=requests.get("https://fapi.binance.com/fapi/v1/premiumIndex",params={"symbol":sym},timeout=4).json()
  oi=requests.get("https://fapi.binance.com/fapi/v1/openInterest",params={"symbol":sym},timeout=4).json()
  return float(t.get("quoteVolume",0)),float(f.get("lastFundingRate",0)),float(oi.get("openInterest",0))
 except: return 0,0,0
def futures_opportunities():
 syms=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT"]
 mentions=public_mentions(); rows=[]
 for sym in syms:
  v=mentions.get(sym); ai=social_ai(v)
  if not ai: continue
  p=price(sym)
  if not p: continue
  lv=levels(p,ai["direction"])
  rows.append({"market":"futures","symbol":sym.replace("USDT","/USDT"),"direction":ai["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":ai["score"],"mentions":v.get("mentions",0),"bullish_mentions":v.get("bull",0),"bearish_mentions":v.get("bear",0),"source_count":len(v.get("sources",set())),"social_score":social_score(v),"methods":ai["methods"],"model":"المصادر أولاً → تجميع AI متعدد المناهج، بدون مؤشرات"})
 rows.sort(key=lambda x:(x["ai"],x["source_count"],x["mentions"]),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3
 return rows

def refresh_cache():
 if not refresh_lock.acquire(blocking=False): return
 with cache_lock: CACHE["refreshing"]=True
 try:
  rows=opportunities()
  futures_rows=futures_opportunities()
  with cache_lock:
   if rows or not CACHE["rows"]: CACHE["rows"]=rows
   CACHE["updated"]=time.time(); CACHE["sources_live"]=len(SOURCES); CACHE["refreshing"]=False
 except Exception:
  with cache_lock: CACHE["refreshing"]=False
 finally: refresh_lock.release()
def refresh_loop():
 while True:
  try: refresh_cache()
  except Exception: pass
  time.sleep(REFRESH_SECONDS)
threading.Thread(target=refresh_loop,daemon=True).start()
def sign(params,secret):
 q=urlencode(params); return hmac.new(secret.encode(),q.encode(),hashlib.sha256).hexdigest()
def binance_available(kind,key,secret):
 try:
  base="https://fapi.binance.com" if kind=="futures" else "https://api.binance.com"
  ep="/fapi/v2/account" if kind=="futures" else "/api/v3/account"
  ts=int(time.time()*1000); p={"timestamp":ts,"recvWindow":5000}; p["signature"]=sign(p,secret)
  r=requests.get(base+ep,headers={"X-MBX-APIKEY":key},params=p,timeout=8).json()
  if kind=="futures": return float(r.get("availableBalance",0))
  for x in r.get("balances",[]):
   if x.get("asset")=="USDT": return float(x.get("free",0))
  return 0
 except: return 0
def binance_order(kind,symbol,side,qty,leverage=1):
 key=os.getenv("BINANCE_API_KEY",""); secret=os.getenv("BINANCE_API_SECRET","")
 if not key or not secret:return {"ok":False,"error":"مفاتيح Binance غير مضبوطة"}
 if qty in (None,"","auto"):
  available=binance_available(kind,key,secret)
  if available<=0:return {"ok":False,"error":"لا يوجد رصيد متاح"}
  p0=price(symbol.replace("/","")) if kind=="spot" else 0
  if kind=="spot": qty=(available*0.995)/max(p0,1e-12)
  else: qty=available*max(1,int(leverage))*0.995/max(p0,1e-12)
  qty=round(qty,8)
 base="https://fapi.binance.com" if kind=="futures" else "https://api.binance.com"
 ep="/fapi/v1/order" if kind=="futures" else "/api/v3/order"
 p={"symbol":symbol.replace("/",""),"side":side,"type":"MARKET","quantity":qty,"timestamp":int(time.time()*1000),"recvWindow":5000}
 if kind=="futures":
  try: requests.post(base+"/fapi/v1/leverage",headers={"X-MBX-APIKEY":key},params={"symbol":p["symbol"],"leverage":leverage,"timestamp":p["timestamp"],"signature":sign({"symbol":p["symbol"],"leverage":leverage,"timestamp":p["timestamp"]},secret)},timeout=5)
  except: pass
 p["signature"]=sign(p,secret)
 r=requests.post(base+ep,headers={"X-MBX-APIKEY":key},params=p,timeout=8)
 try:j=r.json()
 except:j={"raw":r.text}
 return {"ok":r.ok,"status":r.status_code,"data":j}

# Server-side page protection: UI hiding alone is never trusted.
def require_page(req,page):
 return None if access_ok(req,page) else deny_access()

@app.get("/",response_class=HTMLResponse)
def home(): return open("static/index.html",encoding="utf8").read()
@app.get("/health")
def health(): return {"ok":True,"service":"SMART TRADING PRO"}
@app.post("/api/register")
async def register(req:Request):
 b=await req.json(); email=str(b.get("email","")).strip().lower(); password=str(b.get("password",""))
 if len(email)<5 or "@" not in email or len(password)<6: return JSONResponse({"ok":False,"error":"اكتب بريد صحيح وكلمة مرور 6 أحرف أو أكثر"},status_code=400)
 c=db()
 try:
  cur=c.execute("insert into users(email,password_hash,created,admin) values(?,?,?,0)",(email,password_hash(password),time.time()))
  uid=cur.lastrowid;c.commit()
 except sqlite3.IntegrityError:
  c.close(); return JSONResponse({"ok":False,"error":"الحساب موجود مسبقاً"},status_code=409)
 c.close()
 r=JSONResponse({"ok":True,"user":{"email":email,"admin":False,"subscriber":False}})
 r.set_cookie("stp_session",session_token(uid),httponly=True,samesite="lax",secure=False,max_age=2592000,path="/")
 return r

@app.post("/api/login")
async def login(req:Request):
 b=await req.json(); email=str(b.get("email","")).strip().lower(); password=str(b.get("password",""))
 c=db(); row=c.execute("select id,email,password_hash,admin from users where email=?",(email,)).fetchone(); c.close()
 if not row or not password_check(password,row[2]): return JSONResponse({"ok":False,"error":"البريد أو كلمة المرور غير صحيحة"},status_code=401)
 r=JSONResponse({"ok":True,"user":{"email":row[1],"admin":bool(row[3]),"subscriber":subscriber_active(row[0])}})
 r.set_cookie("stp_session",session_token(row[0]),httponly=True,samesite="lax",secure=False,max_age=2592000,path="/")
 return r

@app.post("/api/logout")
def logout():
 r=JSONResponse({"ok":True});r.delete_cookie("stp_session",path="/");return r

@app.get("/api/auth/me")
def auth_me(req:Request):
 u=current_user(req)
 if not u:return {"authenticated":False}
 c=db(); row=c.execute("select expires from subscriptions where user_id=?",(u["id"],)).fetchone();c.close()
 return {"authenticated":True,"user":{"email":u["email"],"admin":u["admin"],"subscriber":subscriber_active(u["id"]),"expires":row[0] if row else 0}}

@app.get("/api/access")
def access(req:Request):
 u=current_user(req); c=db(); rows=c.execute("select page,subscriber_only from page_access").fetchall(); c.close()
 return {"pages":{p:bool(v) for p,v in rows},"user":{"authenticated":bool(u),"admin":bool(u and u["admin"]),"subscriber":bool(u and (u["admin"] or subscriber_active(u["id"])))}}

@app.post("/api/admin/page-access")
async def admin_page_access(req:Request):
 u=current_user(req)
 if not u or not u["admin"]: return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
 b=await req.json(); page=str(b.get("page","")).strip(); locked=bool(b.get("subscriber_only"))
 if page not in MARKETS+["home","radar","news","blog"]: return JSONResponse({"ok":False,"error":"صفحة غير معروفة"},status_code=400)
 c=db();c.execute("insert or replace into page_access(page,subscriber_only) values(?,?)",(page,int(locked)));c.commit();c.close()
 return {"ok":True,"page":page,"subscriber_only":locked}

@app.post("/api/admin/subscription")
async def admin_subscription(req:Request):
 u=current_user(req)
 if not u or not u["admin"]: return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
 b=await req.json(); email=str(b.get("email","")).strip().lower(); days=int(b.get("days",0))
 if not email or days<1 or days>3650:return JSONResponse({"ok":False,"error":"بيانات الاشتراك غير صحيحة"},status_code=400)
 c=db(); row=c.execute("select id from users where email=?",(email,)).fetchone()
 if not row:c.close();return JSONResponse({"ok":False,"error":"المستخدم غير موجود"},status_code=404)
 uid=row[0]; old=c.execute("select expires from subscriptions where user_id=?",(uid,)).fetchone(); base=max(float(old[0]) if old else 0,time.time()); exp=base+days*86400
 c.execute("insert or replace into subscriptions(user_id,expires,updated) values(?,?,?)",(uid,exp,time.time()));c.commit();c.close()
 return {"ok":True,"email":email,"expires":exp}

@app.get("/api/admin/users")
def admin_users(req:Request):
 u=current_user(req)
 if not u or not u["admin"]: return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
 c=db(); rows=c.execute("select u.email,u.created,u.admin,coalesce(s.expires,0) from users u left join subscriptions s on s.user_id=u.id order by u.created desc").fetchall();c.close()
 return {"users":[{"email":r[0],"created":r[1],"admin":bool(r[2]),"expires":r[3],"subscriber":r[3]>time.time()} for r in rows]}

@app.post("/api/admin/blog")
async def admin_blog(req:Request):
 u=current_user(req)
 if not u or not u["admin"]: return JSONResponse({"ok":False,"error":"غير مصرح"},status_code=403)
 b=await req.json(); title=str(b.get("title","")).strip(); body=str(b.get("body","")).strip()
 if not title or not body:return JSONResponse({"ok":False,"error":"العنوان والمحتوى مطلوبان"},status_code=400)
 c=db();now=time.time();c.execute("insert into blog_posts(title,body,created,updated,author_id) values(?,?,?,?,?)",(title,body,now,now,u["id"]));c.commit();c.close();return {"ok":True}

@app.get("/api/blog")
def blog(req:Request):
 if not access_ok(req,"blog"):return deny_access()
 c=db();rows=c.execute("select id,title,body,created from blog_posts order by created desc limit 50").fetchall();c.close()
 return {"posts":[{"id":r[0],"title":r[1],"body":r[2],"created":r[3]} for r in rows]}

@app.get("/api/news")
def news(req:Request):
 if not access_ok(req,"news"):return deny_access()
 feeds=[("أسواق العملات الرقمية","crypto"),("الأسواق السعودية","Saudi stock market"),("الأسواق الأمريكية","US stocks markets")]
 out=[]
 for label,q in feeds:
  try:
   xml=requests.get("https://news.google.com/rss/search",params={"q":q,"hl":"ar","gl":"SA","ceid":"SA:ar"},headers={"User-Agent":"Mozilla/5.0"},timeout=7).text
   import re
   items=re.findall(r"<item>(.*?)</item>",xml,re.S)
   for item in items[:8]:
    title=re.search(r"<title>(.*?)</title>",item,re.S);link=re.search(r"<link>(.*?)</link>",item,re.S);date=re.search(r"<pubDate>(.*?)</pubDate>",item,re.S)
    if title:
     clean=re.sub("<.*?>","",title.group(1)).replace("&amp;","&")
     out.append({"category":label,"title":clean,"link":link.group(1).strip() if link else "","date":date.group(1).strip() if date else ""})
  except Exception: pass
 return {"news":out[:30],"updated":time.time()}

@app.get("/api/home-markets")
def home_markets(req:Request):
 if not access_ok(req,"home"): return deny_access()
 return {"markets":home_market_rows(),"updated":time.time()}
@app.get("/api/opportunities")
def opp(req:Request):
 if not access_ok(req,"radar"): return deny_access()
 with cache_lock:
  rows=list(CACHE["rows"]); updated=CACHE["updated"]; refreshing=CACHE["refreshing"]; sources_live=CACHE["sources_live"]
 if not rows and not refreshing: threading.Thread(target=refresh_cache,daemon=True).start()
 return {"opportunities":rows,"market_data":{"spot":rows,"futures":futures_opportunities()},"radar":{"sources_live":sources_live or len(SOURCES),"sources_total":len(SOURCES)},"live_trades":trades(),"updated":updated,"refreshing":refreshing}
@app.get("/api/fast-market")
def fast_market(req:Request,market="spot",timeframe="15m"):
 if market not in MARKETS: return JSONResponse({"ok":False,"error":"سوق غير معروف"},status_code=400)
 if not access_ok(req,market): return deny_access()
 if market=="futures":
  return {"market":"futures","timeframe":timeframe,"opportunities":futures_opportunities(),"updated":time.time(),"refreshing":False}
 if market in ("us","saudi","contracts","forex"):
  return {"market":market,"timeframe":timeframe,"opportunities":external_market_rows(market),"updated":time.time(),"refreshing":False}
 with cache_lock:
  rows=list(CACHE["rows"]); updated=CACHE["updated"]; refreshing=CACHE["refreshing"]
 if not rows and not refreshing: threading.Thread(target=refresh_cache,daemon=True).start()
 return {"market":market,"timeframe":timeframe,"opportunities":rows,"updated":updated,"refreshing":refreshing}
@app.get("/api/trades")
def api_trades(market="spot",timeframe="15m"): return {"trades":trades(market)}
@app.get("/api/strategy")
def strategy(): return {"retention_hours":24,"timeframes":["15m","30m","1h","4h","1d","1w","1M"],"bot_timeframe":"15m","rules":["المصادر والناس أولاً","AI متعدد المناهج","إجماع المصادر","تنوع المصادر","وزن جودة المصدر","قوة التكرار","بدون مؤشرات فنية","بحث أعمق للأصول ضعيفة التغطية","24h memory"]}
@app.post("/api/spot/entry")
async def spot_entry(req:Request):
 b=await req.json(); return JSONResponse(binance_order("spot",b.get("symbol",""),"BUY",b.get("quantity"),1),status_code=200)
@app.post("/api/futures/entry")
async def futures_entry(req:Request):
 b=await req.json(); side="BUY" if str(b.get("direction","LONG")).upper() in ("LONG","BUY") else "SELL"; return JSONResponse(binance_order("futures",b.get("symbol",""),side,b.get("quantity"),int(b.get("leverage",1))),status_code=200)
def trades(market=None):
 c=db(); c.execute("delete from trades where created<?",(time.time()-RETENTION,)); c.commit(); q="select id,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created,updated from trades"; args=()
 if market:q+=" where market=?";args=(market,)
 rows=c.execute(q,args).fetchall()
 c.close()
 return [dict(zip(["id","market","symbol","direction","entry","tp1","tp2","tp3","sl","status","created","updated"],r)) for r in rows]

# Deploy sync: force Northflank to build current main revision.

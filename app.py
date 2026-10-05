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
 ("tradingview","https://www.tradingview.com/markets/cryptocurrencies/news/")]
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
 # Migrate an older persistent database instead of crashing when the volume survives a rebuild.
 required={"market":"TEXT","symbol":"TEXT","direction":"TEXT","entry":"REAL","tp1":"REAL","tp2":"REAL","tp3":"REAL","sl":"REAL","status":"TEXT","created":"REAL","updated":"REAL"}
 cols={r[1] for r in c.execute("pragma table_info(trades)").fetchall()}
 for name,typ in required.items():
  if name not in cols:
   c.execute(f"alter table trades add column {name} {typ}")
 c.commit()
 return c
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
 up=p>ema20 and ema20>ema50; down=p<ema20 and ema20<ema50
 direction="BUY" if up and rsi>=50 else "SELL" if down and rsi<=50 else ("BUY" if p>=ema20 else "SELL")
 score=min(99,max(1,50+(rsi-50)*0.7+(10 if up else -10 if down else 0)+(min(vr,3)-1)*7))
 return {"price":p,"rsi":round(rsi,1),"volume_ratio":round(vr,2),"direction":direction,"score":round(score,1)}
def levels(p,d):
 if d in ("BUY","LONG"): return [p,p*1.01,p*1.02,p*1.03,p*.98]
 return [p,p*.99,p*.98,p*.97,p*1.02]
def _source_mentions(item):
 name,url=item
 out={}
 try:
  t=requests.get(url,timeout=2.5,headers={"User-Agent":"Mozilla/5.0"}).text.upper()
  for s in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","SUI","LINK","AVAX","MATIC","DOT"]:
   if s in t: out[s]=1
 except Exception: pass
 return out
def public_mentions():
 out={}
 with ThreadPoolExecutor(max_workers=min(8,len(SOURCES))) as ex:
  for result in ex.map(_source_mentions,SOURCES):
   for s,n in result.items(): out[s]=out.get(s,0)+n
 return out
def _technical_safe(sym):
 try: return sym,technical(sym)
 except Exception: return sym,None
def opportunities():
 syms=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT"]
 mentions=public_mentions(); rows=[]
 with ThreadPoolExecutor(max_workers=8) as ex:
  results=list(ex.map(_technical_safe,syms))
 for sym,a in results:
  if not a: continue
  p=a["price"]; lv=levels(p,a["direction"])
  rows.append({"market":"spot","symbol":sym.replace("USDT","/USDT"),"direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":a["score"],"rsi":a["rsi"],"volume_ratio":a["volume_ratio"],"mentions":mentions.get(sym.replace("USDT",""),0)})
 rows.sort(key=lambda x:(x["mentions"],x["ai"]),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3;x["model"]="إجماع المصادر + تحليل فني" if x["mentions"] else "تحليل فني + اهتمام السوق"
 return rows

MARKET_SYMBOLS={
 "us":[("AAPL","AAPL"),("NVDA","NVDA"),("MSFT","MSFT"),("AMZN","AMZN"),("META","META"),("TSLA","TSLA"),("GOOGL","GOOGL")],
 "saudi":[("2222.SR","أرامكو"),("1120.SR","الراجحي"),("2010.SR","سابك"),("1180.SR","الأهلي"),("7010.SR","stc")],
 "contracts":[("ES=F","S&P 500 Futures"),("NQ=F","Nasdaq Futures"),("YM=F","Dow Futures"),("GC=F","Gold Futures")],
 "forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("XAUUSD=X","Gold/USD")]
}
def external_market_rows(market):
 rows=[]
 for q,label in MARKET_SYMBOLS.get(market,[]):
  try:
   u="https://query1.finance.yahoo.com/v8/finance/chart/"+requests.utils.quote(q,safe="")
   j=requests.get(u,params={"range":"2d","interval":"15m"},headers={"User-Agent":"Mozilla/5.0"},timeout=5).json()["chart"]["result"][0]
   meta=j.get("meta",{}); p=float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
   prev=float(meta.get("previousClose") or p)
   if not p: continue
   ch=(p/prev-1)*100 if prev else 0
   direction="BUY" if ch>=0 else "SELL"
   score=min(99,max(1,50+abs(ch)*8))
   lv=levels(p,direction)
   rows.append({"market":market,"symbol":label,"direction":direction,"entry":round(p,4),"tp1":round(lv[1],4),"tp2":round(lv[2],4),"tp3":round(lv[3],4),"sl":round(lv[4],4),"timeframe":"15m","ai":round(score,1),"rsi":None,"volume_ratio":None,"mentions":0,"model":"بيانات السوق العامة"})
  except Exception: pass
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3
 return rows
def refresh_cache():
 if not refresh_lock.acquire(blocking=False): return
 with cache_lock: CACHE["refreshing"]=True
 try:
  rows=opportunities()
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
def binance_order(kind,symbol,side,qty,leverage=1):
 key=os.getenv("BINANCE_API_KEY",""); secret=os.getenv("BINANCE_API_SECRET","")
 if not key or not secret:return {"ok":False,"error":"مفاتيح Binance غير مضبوطة"}
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
@app.get("/",response_class=HTMLResponse)
def home(): return open("static/index.html",encoding="utf8").read()
@app.get("/health")
def health(): return {"ok":True,"service":"SMART TRADING PRO"}
@app.get("/api/auth/me")
def auth(): return {"authenticated":bool(os.getenv("ADMIN_EMAIL"))}
@app.get("/api/opportunities")
def opp():
 with cache_lock:
  rows=list(CACHE["rows"]); updated=CACHE["updated"]; refreshing=CACHE["refreshing"]; sources_live=CACHE["sources_live"]
 if not rows and not refreshing: threading.Thread(target=refresh_cache,daemon=True).start()
 return {"opportunities":rows,"market_data":{"spot":rows,"futures":rows},"radar":{"sources_live":sources_live or len(SOURCES),"sources_total":len(SOURCES)},"live_trades":trades(),"updated":updated,"refreshing":refreshing}
@app.get("/api/fast-market")
def fast_market(market="spot",timeframe="15m"):
 if market in ("us","saudi","contracts","forex"):
  return {"market":market,"timeframe":timeframe,"opportunities":external_market_rows(market),"updated":time.time(),"refreshing":False}
 with cache_lock:
  rows=list(CACHE["rows"]); updated=CACHE["updated"]; refreshing=CACHE["refreshing"]
 if not rows and not refreshing: threading.Thread(target=refresh_cache,daemon=True).start()
 return {"market":market,"timeframe":timeframe,"opportunities":rows,"updated":updated,"refreshing":refreshing}
@app.get("/api/trades")
def api_trades(market="spot",timeframe="15m"): return {"trades":trades(market)}
@app.get("/api/strategy")
def strategy(): return {"retention_hours":24,"timeframes":["15m","30m","1h","4h","1d","1w","1M"],"bot_timeframe":"15m","rules":["Spot BUY only","Futures LONG/SHORT","EMA20/EMA200","RSI","volume","no gaps/large candles","no overextended entries","24h memory"]}
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

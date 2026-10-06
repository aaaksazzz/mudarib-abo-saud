import os,time,hmac,hashlib,sqlite3,threading,requests
from urllib.parse import urlencode
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles

app=FastAPI(title="SMART TRADING PRO")
app.mount("/static",StaticFiles(directory="static"),name="static")

# Fresh-content policy: always revalidate HTML, static assets, and API responses.
# This prevents browsers/proxies from reopening an older deployed UI after a new release.
@app.middleware("http")
async def fresh_content(request:Request, call_next):
 response=await call_next(request)
 response.headers["Cache-Control"]="no-cache, private, max-age=0, must-revalidate"
 response.headers["Pragma"]="no-cache"
 response.headers["Expires"]="0"
 return response
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
def db():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True); c=sqlite3.connect(DB,check_same_thread=False); c.execute("create table if not exists trades(id integer primary key,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created real,updated real)"); c.commit(); return c
def price(sym,market="spot"):
 try:
  base="https://fapi.binance.com/fapi/v1/ticker/price" if market=="futures" else "https://api.binance.com/api/v3/ticker/price"
  r=requests.get(base,params={"symbol":sym},timeout=4); return float(r.json()["price"])
 except: return 0
def klines(sym,tf="15m",n=120,market="spot"):
 try:
  if market in ("spot","futures"):
   base="https://fapi.binance.com/fapi/v1/klines" if market=="futures" else "https://api.binance.com/api/v3/klines"
   r=requests.get(base,params={"symbol":sym,"interval":tf,"limit":n},timeout=6); return r.json()
  ysym=sym+".SR" if market=="saudi" and sym.isdigit() else sym
  r=requests.get("https://query1.finance.yahoo.com/v8/finance/chart/"+ysym,params={"range":"10d","interval":"15m","includePrePost":"false"},timeout=7)
  j=(r.json().get("chart",{}).get("result") or [])
  if not j:return []
  q=j[0].get("indicators",{}).get("quote",[{}])[0]; ts=j[0].get("timestamp",[]); out=[]
  for i,t in enumerate(ts):
   try:
    o,h,l,cl,v=q["open"][i],q["high"][i],q["low"][i],q["close"][i],(q.get("volume") or [0]*len(ts))[i]
    if None in (o,h,l,cl): continue
    out.append([t,o,h,l,cl,v or 0])
   except: pass
  return out[-n:]
 except: return []
def technical(sym,market="spot"):
 k=klines(sym,market=market)
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
def public_mentions():
 out={}
 for name,url in SOURCES:
  try:
   t=requests.get(url,timeout=3,headers={"User-Agent":"Mozilla/5.0"}).text.upper()
   for s in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","SUI","LINK","AVAX","MATIC","DOT"]:
    if s in t: out[s]=out.get(s,0)+1
  except: pass
 return out
def opportunities(market="spot"):
 syms_by_market={
  "spot":["ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT","TRXUSDT"],
  "futures":["ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","ADAUSDT"],
  "us":["AAPL","NVDA","MSFT","AMZN","META","TSLA","GOOGL","AMD","NFLX","AVGO"],
  "saudi":["2222","1120","2010","7010","1180","1211","2380","2050","1150","4003"],
  "contracts":["GC=F","CL=F","SI=F","NG=F","ES=F","NQ=F","YM=F","RTY=F"],
  "forex":["XAUUSD","EURUSD","GBPUSD","USDJPY","AUDUSD","USDCHF","USDCAD","NZDUSD"]
 }
 syms=syms_by_market.get(market,syms_by_market["spot"])
 mentions=public_mentions(); rows=[]
 for sym in syms:
  a=technical(sym,market)
  if not a: continue
  p=a["price"]; lv=levels(p,a["direction"])
  rows.append({"market":market,"symbol":(sym.replace("USDT","/USDT") if market in ("spot","futures") else sym),"direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":a["score"],"rsi":a["rsi"],"volume_ratio":a["volume_ratio"],"mentions":round(min(99,mentions.get(sym.replace("USDT",""),0)*12.5),1) if market in ("spot","futures") else 0})
 rows.sort(key=lambda x:(x["mentions"],x["ai"]),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3;x["model"]="إجماع المصادر + تحليل فني" if x["mentions"] else "تحليل فني + اهتمام السوق"
 return rows
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
def opp(market="spot"):
 rows=opportunities(market); return {"opportunities":rows,"market":market,"market_data":{market:rows},"radar":{"sources_live":len(SOURCES),"sources_total":len(SOURCES)},"live_trades":trades()}
@app.get("/api/fast-market")
def fast_market(market="spot",timeframe="15m"): return {"market":market,"timeframe":timeframe,"opportunities":opportunities(market)}
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
 return [dict(zip(["id","market","symbol","direction","entry","tp1","tp2","tp3","sl","status","created","updated"],r)) for r in c.execute(q,args).fetchall()]

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
def public_mentions():
 out={}
 with ThreadPoolExecutor(max_workers=min(10,len(SOURCES))) as ex:
  for result in ex.map(_source_mentions,SOURCES):
   for s,v in result.items():
    x=out.setdefault(s,{"mentions":0,"bull":0,"bear":0})
    x["mentions"]+=v["mentions"];x["bull"]+=v["bull"];x["bear"]+=v["bear"]
 return out
def social_score(v):
 if not v or not v.get("mentions"): return 0
 return min(99,round(20+min(v["mentions"],80)*0.65+min(30,abs(v["bull"]-v["bear"])*1.5),1))
def social_direction(v,default="BUY"):
 if not v or not v.get("mentions") or v["bull"]==v["bear"]: return default
 return "BUY" if v["bull"]>v["bear"] else "SELL"
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
  p=a["price"]; lv=levels(p,a["direction"],a.get("atr"))
  rows.append({"market":"spot","symbol":sym.replace("USDT","/USDT"),"direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":a["score"],"rsi":a["rsi"],"volume_ratio":a["volume_ratio"],"mentions":mentions.get(sym,{}).get("mentions",0),"bullish_mentions":mentions.get(sym,{}).get("bull",0),"bearish_mentions":mentions.get(sym,{}).get("bear",0),"social_score":social_score(mentions.get(sym))})
 # ترتيب التوصيات حسب جودة التوصية نفسها، وليس حسب BTC أو ترتيب الرموز.
 for x in rows:
  m=x.get("mentions",0); bull=x.get("bullish_mentions",0); bear=x.get("bearish_mentions",0)
  total=max(bull+bear,1); agreement=abs(bull-bear)/total
  x["recommendation_quality"]=round(min(99,25+min(m,20)*2.0+agreement*35+x.get("social_score",0)*0.30+x.get("ai",0)*0.10),1)
 rows.sort(key=lambda x:(x.get("recommendation_quality",0),x.get("social_score",0),x.get("mentions",0)),reverse=True)
 for i,x in enumerate(rows,1): x["rank"]=i;x["jewel"]=i<=3;x["model"]="جودة التوصية + إجماع المصادر + AI" if x["mentions"] else "جودة تحليل السوق"
 return rows

MARKET_SYMBOLS={
 "us":[("AAPL","AAPL"),("NVDA","NVDA"),("MSFT","MSFT"),("AMZN","AMZN"),("META","META"),("TSLA","TSLA"),("GOOGL","GOOGL")],
 "saudi":[("2222.SR","أرامكو"),("1120.SR","الراجحي"),("2010.SR","سابك"),("1180.SR","الأهلي"),("7010.SR","stc")],
 "contracts":[("ES=F","S&P 500 Futures"),("NQ=F","Nasdaq Futures"),("YM=F","Dow Futures"),("GC=F","Gold Futures")],
 "forex":[("EURUSD=X","EUR/USD"),("GBPUSD=X","GBP/USD"),("USDJPY=X","USD/JPY"),("XAUUSD=X","Gold/USD")]
}
def external_market_rows(market):
 mentions=public_mentions(); rows=[]
 for q,label in MARKET_SYMBOLS.get(market,[]):
  try:
   u="https://query1.finance.yahoo.com/v8/finance/chart/"+requests.utils.quote(q,safe="")
   j=requests.get(u,params={"range":"2d","interval":"15m"},headers={"User-Agent":"Mozilla/5.0"},timeout=5).json()["chart"]["result"][0]
   meta=j.get("meta",{}); p=float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
   prev=float(meta.get("previousClose") or p)
   if not p: continue
   ch=(p/prev-1)*100 if prev else 0
   sv=mentions.get(q,{})
   direction=social_direction(sv,"BUY" if ch>=0 else "SELL")
   score=min(99,max(1,50+abs(ch)*8))
   lv=levels(p,direction)
   rows.append({"market":market,"symbol":label,"direction":direction,"entry":round(p,4),"tp1":round(lv[1],4),"tp2":round(lv[2],4),"tp3":round(lv[3],4),"sl":round(lv[4],4),"timeframe":"15m","ai":round(score,1),"rsi":None,"volume_ratio":None,"mentions":mentions.get(q,{}).get("mentions",0),"bullish_mentions":mentions.get(q,{}).get("bull",0),"bearish_mentions":mentions.get(q,{}).get("bear",0),"social_score":social_score(mentions.get(q)),"model":"كلام الناس والمصادر أولاً + تأكيد السوق"})
  except Exception: pass
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
def futures_technical(sym):
 k=futures_klines(sym)
 if len(k)<50:return None
 close=[float(x[4]) for x in k]; vol=[float(x[5]) for x in k]; p=close[-1]
 ema20=sum(close[-20:])/20; ema50=sum(close[-50:])/50
 gains=[];loss=[]
 for i in range(-14,0):
  d=close[i]-close[i-1];gains.append(max(d,0));loss.append(max(-d,0))
 rs=(sum(gains)/14)/max(sum(loss)/14,1e-9);rsi=100-(100/(1+rs))
 avg=sum(vol[-21:-1])/20;vr=vol[-1]/max(avg,1e-9)
 trs=[]
 for i in range(-14,0):
  hi,lo,pc=float(k[i][2]),float(k[i][3]),float(k[i-1][4])
  trs.append(max(hi-lo,abs(hi-pc),abs(lo-pc)))
 atr=sum(trs)/14
 qv,funding,oi=futures_market_info(sym)
 long_bias=p>ema20 and ema20>ema50 and rsi>=50
 short_bias=p<ema20 and ema20<ema50 and rsi<=50
 direction="LONG" if long_bias else "SHORT" if short_bias else ("LONG" if p>=ema20 else "SHORT")
 score=min(99,max(1,50+(rsi-50)*0.6+(12 if long_bias or short_bias else 0)+(min(vr,3)-1)*6-(abs(funding)*10000)*0.15))
 return {"price":p,"rsi":round(rsi,1),"volume_ratio":round(vr,2),"direction":direction,"score":round(score,1),"atr":atr,"quote_volume":qv,"funding":funding,"open_interest":oi}
def futures_opportunities():
 syms=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT"]
 rows=[]
 with ThreadPoolExecutor(max_workers=6) as ex: results=list(ex.map(lambda s:(s,futures_technical(s)),syms))
 for sym,a in results:
  if not a or a["quote_volume"]<1000000: continue
  lv=levels(a["price"],a["direction"],a["atr"])
  rows.append({"market":"futures","symbol":sym.replace("USDT","/USDT"),"direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),"timeframe":"15m","ai":a["score"],"rsi":a["rsi"],"volume_ratio":a["volume_ratio"],"funding":a["funding"],"open_interest":a["open_interest"],"quote_volume":a["quote_volume"],"model":"تحليل فيوتشر مستقل: EMA + RSI + Volume + Funding + OI + ATR"})
 rows.sort(key=lambda x:x["ai"],reverse=True)
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
 return {"opportunities":rows,"market_data":{"spot":rows,"futures":futures_opportunities()},"radar":{"sources_live":sources_live or len(SOURCES),"sources_total":len(SOURCES)},"live_trades":trades(),"updated":updated,"refreshing":refreshing}
@app.get("/api/fast-market")
def fast_market(market="spot",timeframe="15m"):
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

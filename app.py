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
 # Do not allow conditional requests for static assets: some mobile browsers keep
 # an old ETag/Last-Modified representation and return 304 with stale JS/CSS.
 if request.url.path.startswith("/static/"):
  request.scope["headers"]=[(k,v) for k,v in request.scope["headers"] if k.lower() not in (b"if-none-match",b"if-modified-since")]
 response=await call_next(request)
 response.headers["Cache-Control"]="no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0"
 response.headers["Pragma"]="no-cache"
 response.headers["Expires"]="0"
 if request.url.path.startswith("/static/"):
  response.headers.pop("ETag",None)
  response.headers.pop("Last-Modified",None)
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
def _ohlcv(k):
 close=[float(x[4]) for x in k]; high=[float(x[2]) for x in k]; low=[float(x[3]) for x in k]; vol=[float(x[5]) for x in k]
 return close,high,low,vol

def _swings(close,high,low):
 highs=[]; lows=[]
 for i in range(2,len(close)-2):
  if high[i]>=max(high[i-2:i]+high[i+1:i+3]): highs.append((i,high[i]))
  if low[i]<=min(low[i-2:i]+low[i+1:i+3]): lows.append((i,low[i]))
 return highs[-8:],lows[-8:]

def price_analysis(sym,market="spot"):
 k=klines(sym,market=market)
 if len(k)<50:return None
 close,high,low,vol=_ohlcv(k); p=close[-1]; prev=close[-2]
 sh,sl=_swings(close,high,low)
 recent_hi=max(high[-30:]); recent_lo=min(low[-30:])
 change3=(p/close[-4]-1)*100; change12=(p/close[-13]-1)*100
 ranges=[high[i]-low[i] for i in range(max(0,len(k)-20),len(k))]
 avg_range=sum(ranges[:-1])/max(1,len(ranges)-1); last_range=high[-1]-low[-1]
 body=abs(close[-1]-float(k[-1][1])); upper=high[-1]-max(close[-1],float(k[-1][1])); lower=min(close[-1],float(k[-1][1]))-low[-1]
 score=50; reasons=[]; schools=[]

 # Classical / market structure
 if len(sh)>=2 and sh[-1][1]>sh[-2][1] and len(sl)>=2 and sl[-1][1]>sl[-2][1]:
  score+=14; direction="BUY"; reasons.append("قمم وقيعان صاعدة"); schools.append("كلاسيكي")
 elif len(sh)>=2 and sh[-1][1]<sh[-2][1] and len(sl)>=2 and sl[-1][1]<sl[-2][1]:
  score-=14; direction="SELL"; reasons.append("قمم وقيعان هابطة"); schools.append("كلاسيكي")
 else:
  direction="BUY" if change3>=0 else "SELL"; reasons.append("نطاق/انتقال"); schools.append("كلاسيكي")

 # Price action / candles
 if lower>body*1.5 and close[-1]>float(k[-1][1]):
  score+=8; direction="BUY"; reasons.append("رفض سعري من الأسفل"); schools.append("Price Action")
 if upper>body*1.5 and close[-1]<float(k[-1][1]):
  score-=8; direction="SELL"; reasons.append("رفض سعري من الأعلى"); schools.append("Price Action")
 if last_range>avg_range*1.7 and body/max(last_range,1e-9)>.65:
  score += 7 if close[-1]>float(k[-1][1]) else -7
  reasons.append("شمعة اندفاعية"); schools.append("Price Action")

 # Breakout / support resistance
 if p>recent_hi*0.998 and change3>0:
  score+=8; direction="BUY"; reasons.append("اختبار/اختراق قمة قريبة"); schools.append("مقاومة ودعم")
 elif p<recent_lo*1.002 and change3<0:
  score-=8; direction="SELL"; reasons.append("كسر قاع قريب"); schools.append("مقاومة ودعم")

 # Wyckoff / effort-result using raw volume and candle result
 avg_vol=sum(vol[-21:-1])/20; vr=vol[-1]/max(avg_vol,1e-9)
 if vr>1.5 and last_range<avg_range*.65:
  reasons.append("جهد مرتفع ونتيجة ضعيفة"); schools.append("Wyckoff")
 elif vr>1.5 and last_range>avg_range*1.3:
  reasons.append("جهد ونتيجة متوافقان"); schools.append("Wyckoff")

 # Harmonic candidate heuristic: AB=CD-like proportional swings, only report when geometry is plausible
 if len(sh)>=2 and len(sl)>=2:
  a=abs(sh[-2][1]-sl[-2][1]); b=abs(sh[-1][1]-sl[-1][1])
  if a and .75<=b/a<=1.35:
   reasons.append("هندسة موجية قريبة من AB=CD"); schools.append("هارمونيك")

 # Elliott-style impulse/correction heuristic
 if len(sh)>=3 and len(sl)>=3:
  upseq=sh[-1][1]>sh[-2][1]>sh[-3][1] and sl[-1][1]>sl[-2][1]>sl[-3][1]
  dnseq=sh[-1][1]<sh[-2][1]<sh[-3][1] and sl[-1][1]<sl[-2][1]<sl[-3][1]
  if upseq: reasons.append("تسلسل موجي صاعد"); schools.append("Elliott")
  if dnseq: reasons.append("تسلسل موجي هابط"); schools.append("Elliott")

 # SMC / liquidity-style structure from visible highs/lows
 if recent_hi and abs(p-recent_hi)/recent_hi<.003:
  reasons.append("السعر قرب سيولة قمة"); schools.append("Structure/SMC")
 if recent_lo and abs(p-recent_lo)/recent_lo<.003:
  reasons.append("السعر قرب سيولة قاع"); schools.append("Structure/SMC")

 # Statistical context: repeated direction over recent raw closes, not an indicator
 wins=sum(1 for i in range(max(1,len(close)-12),len(close)) if close[i]>close[i-1])
 losses=11-wins
 if wins>=8: score+=6; reasons.append("غلبة صعودية حديثة"); schools.append("إحصائي")
 if losses>=8: score-=6; reasons.append("غلبة هبوطية حديثة"); schools.append("إحصائي")

 score=max(1,min(99,score))
 return {"price":p,"direction":direction,"score":round(score,1),"volume_ratio":round(vr,2),
         "schools":list(dict.fromkeys(schools)),"reasons":list(dict.fromkeys(reasons)),
         "change3":round(change3,2),"change12":round(change12,2)}

def source_consensus(sym,market="spot"):
 aliases={"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","BNB":"BNBUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","SUI":"SUIUSDT","LINK":"LINKUSDT","AVAX":"AVAXUSDT"}
 base=sym.replace("/USDT","").replace("USDT","")
 keys=[base]
 if base in aliases: keys.append(aliases[base])
 if market=="saudi": keys += [base]
 if market in ("us","contracts","forex"): keys += [base.upper()]
 buy_words=("BUY","LONG","ENTRY","TARGET","ACCUMULATE","شراء","صعود","هدف")
 sell_words=("SELL","SHORT","STOP","DUMP","بيع","هبوط")
 count=0; buy=sell=0
 for name,url in SOURCES:
  try:
   t=requests.get(url,timeout=2,headers={"User-Agent":"Mozilla/5.0"}).text.upper()
   if not any(x in t for x in keys): continue
   count+=1; window=t[-30000:]
   if any(w in window for w in buy_words): buy+=1
   if any(w in window for w in sell_words): sell+=1
  except: pass
 total=max(1,len(SOURCES)); consensus=max(buy,sell)
 direction="BUY" if buy>sell else "SELL" if sell>buy else None
 strength=min(100,count/total*55+consensus/total*45)
 return {"source_count":count,"source_buy":buy,"source_sell":sell,"source_direction":direction,"recommendation":round(strength,1),"freshness":100 if count else 0}

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
  "forex":["XAUUSD=X","EURUSD=X","GBPUSD=X","JPY=X","AUDUSD=X","CHF=X","CAD=X","NZDUSD=X"]
 }
 syms=syms_by_market.get(market,syms_by_market["spot"]); rows=[]
 for sym in syms:
  a=price_analysis(sym,market)
  if not a: continue
  p=a["price"]; lv=levels(p,a["direction"])
  src=source_consensus(sym,market)
  # Recommendation quality is primary; raw price-analysis agreement is secondary.
  agreement=100 if not src["source_direction"] or src["source_direction"]==a["direction"] else 35
  rank_score=.42*src["recommendation"]+.28*a["score"]+.18*agreement+.12*src["freshness"]
  rows.append({"market":market,"symbol":(sym.replace("USDT","/USDT") if market in ("spot","futures") else sym.replace("=X","")),
   "direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),
   "timeframe":"15m","ai":round(rank_score,1),"recommendation_score":round(rank_score,1),"source_count":src["source_count"],
   "freshness":src["freshness"],"mentions":round(src["recommendation"],1),"analysis_score":a["score"],
   "schools":a["schools"],"reasons":a["reasons"],"model":" + ".join(a["schools"]) if a["schools"] else "تحليل حركة السعر",
   "source_direction":src["source_direction"]})
 rows.sort(key=lambda x:(x["recommendation_score"],x["freshness"],x["analysis_score"]),reverse=True)
 for i,x in enumerate(rows,1):
  x["rank"]=i; x["jewel"]=i<=3
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
def strategy(): return {"retention_hours":24,"timeframes":["15m","30m","1h","4h","1d","1w","1M"],"bot_timeframe":"15m","rules":["لا مؤشرات","تحليل الناس والمصادر العامة","كلاسيكي","Price Action","هارمونيك","Elliott","Wyckoff","Structure/SMC","نماذج سعرية","إحصائي","أخبار وأحداث","24h memory"]}
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

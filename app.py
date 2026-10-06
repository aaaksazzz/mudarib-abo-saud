import os,time,hmac,hashlib,sqlite3,threading,requests
from concurrent.futures import ThreadPoolExecutor, as_completed
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
SOURCE_CACHE={"at":0.0,"texts":{}}
SOURCE_TTL=60
MARKET_CACHE={}
MARKET_CACHE_TTL=45
OPPORTUNITY_MIN_SCORE=52
OPPORTUNITY_STATE={}
FORTUNE_CACHE={"at":0.0,"signals":[]}
FORTUNE_TTL=60
FORTUNE_SOURCES=[
 ("Fortune Traders","https://t.me/s/Fortunetradersofficial"),
 ("Fortune Results","https://t.me/s/BITCOIN_RESULTS")
]
FORTUNE_RETENTION=86400

def _fortune_clean(html):
 import re
 text=re.sub(r"<br\s*/?>","\n",html or "",flags=re.I)
 text=re.sub(r"<[^>]+>"," ",text)
 text=re.sub(r"&nbsp;"," ",text,flags=re.I)
 text=re.sub(r"&amp;","&",text,flags=re.I)
 text=re.sub(r"\s+"," ",text)
 return text.strip()

def fortune_signals(force=False):
 now=time.time()
 with lock:
  if not force and now-FORTUNE_CACHE["at"]<FORTUNE_TTL:
   return list(FORTUNE_CACHE["signals"])
 def fetch(item):
  name,url=item
  try:
   r=requests.get(url,timeout=8,headers={"User-Agent":"Mozilla/5.0"})
   return name,r.text if r.ok else ""
  except Exception:
   return name,""
 posts=[]
 with ThreadPoolExecutor(max_workers=2) as ex:
  fs=[ex.submit(fetch,x) for x in FORTUNE_SOURCES]
  for f in as_completed(fs):
   name,html=f.result()
   if not html: continue
   import re
   chunks=re.split(r'<div class="tgme_widget_message_wrap',html,flags=re.I)
   for chunk in chunks[1:]:
    body=_fortune_clean(chunk)
    if not body: continue
    dm=re.search(r'<time[^>]+datetime="([^"]+)"',chunk,re.I)
    published=dm.group(1) if dm else ""
    pm=re.search(r'(?:data-post|t.me/)[^>]*?([A-Za-z0-9_]+/\d+)',chunk,re.I|re.S)
    post_id=pm.group(1).split("/")[-1] if pm else ""
    posts.append((name,post_id,published,body))
 signals=[]
 import re
 for source,post_id,published,body in posts:
  u=body.upper()
  if not re.search(r"\b(?:BUY|SELL|LONG|SHORT)\b|شراء|بيع|لونج|شورت",u): continue
  sm=re.search(r"\b(XAUUSD|XAU|[A-Z0-9]{2,18}\s*/?\s*USDT)\b",u)
  if not sm: continue
  symbol=sm.group(1).replace(" ","")
  if symbol=="XAU": symbol="XAUUSD"
  if symbol.endswith("USDT") and "/" not in symbol and symbol!="XAUUSD":
   symbol=symbol[:-4]+"/USDT"
  bm=re.search(r"\b(?:BUY|LONG|شراء|لونج)\b",u)
  smd=re.search(r"\b(?:SELL|SHORT|بيع|شورت)\b",u)
  direction="BUY" if bm and (not smd or bm.start()<smd.start()) else "SELL" if smd else None
  if not direction: continue
  def val(patterns):
   for p in patterns:
    z=re.search(p,u,re.I)
    if z: return z.group(1).strip()
   return None
  entry=val([
   r"(?:ENTRY|ENTRY PRICE|ENTRY ZONE|ENTRY RANGE)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–]\s*[0-9]+(?:\.[0-9]+)?)?)",
   r"ENTRY\s*(?:ZONE|RANGE)?\s*([0-9]+(?:\.[0-9]+)?(?:\s*[-–]\s*[0-9]+(?:\.[0-9]+)?)?)"
  ])
  tps=[]
  for n in range(1,7):
   z=val([rf"(?:TP\s*{n}|TARGET\s*{n}|TAKE\s*PROFIT\s*{n})\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"])
   if z: tps.append(z)
  if not tps:
   tps=re.findall(r"(?:TP|TARGET)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)",u)
  sl=val([r"(?:SL|STOP\s*LOSS|STOP)\s*[:=@-]\s*([0-9]+(?:\.[0-9]+)?)"])
  if not entry or not tps: continue
  key=(symbol,direction,entry,"|".join(tps),sl or "")
  if any((x["symbol"],x["direction"],x["entry"],"|".join(x["targets"]),x.get("sl") or "")==key for x in signals): continue
  signals.append({"symbol":symbol,"direction":direction,"entry":entry,"targets":tps[:6],
   "tp1":tps[0],"tp2":tps[1] if len(tps)>1 else None,"tp3":tps[2] if len(tps)>2 else None,
   "tp4":tps[3] if len(tps)>3 else None,"tp5":tps[4] if len(tps)>4 else None,"tp6":tps[5] if len(tps)>5 else None,
   "sl":sl,"source":source,"published":published,"post_id":post_id,"detected_at":now,
   "source_type":"fortune_public"})
 signals.sort(key=lambda x:x.get("published") or "",reverse=True)
 # Attach independent analysis to the newest public Fortune setups only; keep the feed lightweight.
 for i,sig in enumerate(signals[:20]):
  sig["analysis"]=fortune_trade_analysis(sig)
 with lock: FORTUNE_CACHE.update({"at":now,"signals":signals[:40]})
 return list(signals[:40])


def db():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True); c=sqlite3.connect(DB,check_same_thread=False); c.execute("create table if not exists trades(id integer primary key,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created real,updated real)"); c.commit(); return c
def price(sym,market="spot"):
 try:
  base="https://fapi.binance.com/fapi/v1/ticker/price" if market=="futures" else "https://api.binance.com/api/v3/ticker/price"
  r=requests.get(base,params={"symbol":sym},timeout=4); return float(r.json()["price"])
 except: return 0
def _yahoo_symbols(sym,market):
 if market=="saudi": return [sym+".SR" if sym.isdigit() else sym]
 return [sym]
def klines(sym,tf="15m",n=120,market="spot"):
 key=(market,sym,tf,n); now=time.time()
 cached=MARKET_CACHE.get(key)
 if cached and now-cached[0]<MARKET_CACHE_TTL: return cached[1]
 try:
  if market in ("spot","futures"):
   base="https://fapi.binance.com/fapi/v1/klines" if market=="futures" else "https://api.binance.com/api/v3/klines"
   r=requests.get(base,params={"symbol":sym,"interval":tf,"limit":n},timeout=6,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
   if not r.ok: return []
   data=r.json()
   if not isinstance(data,list): return []
   MARKET_CACHE[key]=(now,data); return data
  headers={"User-Agent":"Mozilla/5.0 (SMART-TRADING-PRO)"}
  for ysym in _yahoo_symbols(sym,market):
   r=requests.get("https://query1.finance.yahoo.com/v8/finance/chart/"+ysym,params={"range":"5d","interval":tf,"includePrePost":"false"},timeout=8,headers=headers)
   if not r.ok: continue
   chart=r.json().get("chart",{})
   if chart.get("error"): continue
   j=(chart.get("result") or [])
   if not j: continue
   result=j[0]; q=(result.get("indicators",{}).get("quote") or [{}])[0]; ts=result.get("timestamp") or []
   out=[]; opens=q.get("open") or []; highs=q.get("high") or []; lows=q.get("low") or []; closes=q.get("close") or []; vols=q.get("volume") or []
   for i,t in enumerate(ts):
    try:
     o,h,l,cl=opens[i],highs[i],lows[i],closes[i]; v=vols[i] if i<len(vols) and vols[i] is not None else 0
     if None in (o,h,l,cl): continue
     out.append([t,o,h,l,cl,v])
    except (IndexError,TypeError): continue
   if len(out)>=20:
    data=out[-n:]; MARKET_CACHE[key]=(now,data); return data
  return []
 except Exception: return []
def _ohlcv(k):
 close=[float(x[4]) for x in k]; high=[float(x[2]) for x in k]; low=[float(x[3]) for x in k]; vol=[float(x[5]) for x in k]
 return close,high,low,vol

def _swings(close,high,low):
 highs=[]; lows=[]
 for i in range(2,len(close)-2):
  if high[i]>=max(high[i-2:i]+high[i+1:i+3]): highs.append((i,high[i]))
  if low[i]<=min(low[i-2:i]+low[i+1:i+3]): lows.append((i,low[i]))
 return highs[-8:],lows[-8:]

def price_analysis(sym,market="spot",tf="15m"):
 k=klines(sym,tf=tf,market=market)
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

def _source_context_direction(text, keys):
 # Only count a source when an explicit directional call is close to the symbol.
 # A generic BUY/SELL elsewhere on the page must never become a signal for this coin.
 buy_terms=(r"\\bBUY\\b",r"\\bLONG\\b",r"BUY\\s*ZONE",r"BUY\\s*NOW",r"\\bشراء\\b",r"\\bصاعد\\b",r"\\bصعود\\b")
 sell_terms=(r"\\bSELL\\b",r"\\bSHORT\\b",r"SELL\\s*ZONE",r"SELL\\s*NOW",r"\\bبيع\\b",r"\\bهابط\\b",r"\\bهبوط\\b")
 positions=[]
 for key in keys:
  start=0
  while True:
   pos=text.find(key,start)
   if pos<0: break
   positions.append(pos); start=pos+len(key)
 if not positions: return None
 for pos in positions:
  lo=max(0,pos-350); hi=min(len(text),pos+350)
  ctx=text[lo:hi]
  if any(__import__("re").search(p,ctx) for p in buy_terms): return "BUY"
  if any(__import__("re").search(p,ctx) for p in sell_terms): return "SELL"
 return None

def source_consensus(sym,market="spot"):
 aliases={"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","BNB":"BNBUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","SUI":"SUIUSDT","LINK":"LINKUSDT","AVAX":"AVAXUSDT"}
 base=sym.replace("/USDT","").replace("USDT","")
 keys=[base]
 if base in aliases: keys.append(aliases[base])
 if market=="saudi": keys += [base]
 if market in ("us","contracts","forex"): keys += [base.upper()]
 source_results=[]
 for name,t in source_snapshot().items():
  if not t: continue
  d=_source_context_direction(t,keys)
  if d: source_results.append((name,d))
 buy=sum(1 for _,d in source_results if d=="BUY")
 sell=sum(1 for _,d in source_results if d=="SELL")
 count=len(source_results)
 direction="BUY" if buy>sell else "SELL" if sell>buy else None
 agreement=max(buy,sell)
 # Recommendation is based only on explicit, symbol-linked source calls.
 # Mere mentions, generic BUY/SELL words, or unrelated calls score zero.
 recommendation=round((agreement/max(1,count))*100,1) if count else 0
 now=time.time()
 with lock:
  snapshot_age=max(0,now-SOURCE_CACHE.get("at",0))
 if snapshot_age<=30: freshness=100
 elif snapshot_age<=90: freshness=85
 elif snapshot_age<=300: freshness=60
 elif snapshot_age<=900: freshness=30
 else: freshness=0
 return {"source_count":count,"source_buy":buy,"source_sell":sell,
         "source_direction":direction,"recommendation":recommendation,
         "freshness":freshness}

def multi_timeframe_analysis(sym,market="spot"):
 # 15m is the execution/entry timeframe; higher timeframes provide directional context.
 frames=("15m","30m","1h","4h")
 analyses={}
 for tf in frames:
  a=price_analysis(sym,market,tf)
  if a: analyses[tf]=a
 entry=analyses.get("15m")
 if not entry: return None
 directions=[a["direction"] for tf,a in analyses.items() if tf!="15m"]
 higher_buys=sum(1 for d in directions if d=="BUY")
 higher_sells=sum(1 for d in directions if d=="SELL")
 higher_total=len(directions)
 higher_direction="BUY" if higher_buys>higher_sells else "SELL" if higher_sells>higher_buys else None
 # Weight context without overriding the actual 15m entry direction.
 context_score=50
 if higher_direction==entry["direction"] and higher_total:
  context_score=50+50*(max(higher_buys,higher_sells)/higher_total)
 elif higher_direction and higher_total:
  context_score=50*(1-(max(higher_buys,higher_sells)/higher_total))
 alignment=round(context_score,1)
 final_direction=entry["direction"]
 # If the higher-timeframe picture is unanimously opposite, mark the 15m setup as weak.
 conflict=(higher_total>=3 and higher_direction and higher_direction!=entry["direction"] and max(higher_buys,higher_sells)>=3)
 combined_score=round(entry["score"]*.65+alignment*.35,1)
 return {"entry":entry,"frames":analyses,"higher_direction":higher_direction,
         "higher_buys":higher_buys,"higher_sells":higher_sells,
         "alignment":alignment,"conflict":conflict,"score":combined_score,
         "direction":final_direction}

def levels(p,d):
 if d in ("BUY","LONG"): return [p,p*1.01,p*1.02,p*1.03,p*.98]
 return [p,p*.99,p*.98,p*.97,p*1.02]
def public_mentions():
 out={}
 for t in source_snapshot().values():
  for s in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","SUI","LINK","AVAX","MATIC","DOT"]:
   if s in t: out[s]=out.get(s,0)+1
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
 source_snapshot()
 # Expand crypto coverage from Binance 24h universe instead of a fixed handful of coins.
 if market in ("spot","futures"):
  try:
   base="https://fapi.binance.com/fapi/v1/ticker/24hr" if market=="futures" else "https://api.binance.com/api/v3/ticker/24hr"
   rr=requests.get(base,timeout=8,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
   if rr.ok:
    universe=rr.json()
    if isinstance(universe,list):
     candidates=[]
     for z in universe:
      s=str(z.get("symbol","")); q=str(z.get("quoteAsset",""))
      try: vol=float(z.get("quoteVolume",0) or 0)
      except: vol=0
      if s.endswith("USDT") and q=="USDT" and vol>=1000000 and not any(x in s for x in ("USDC","FDUSD","USDP","TUSD","DAI","USDE","USDS")):
       candidates.append((vol,s))
     candidates.sort(reverse=True)
     # First pass ranks the liquid universe; deep multi-timeframe analysis follows for the leaders.
     syms=[s for _,s in candidates[:80]]
  except Exception: pass
 def analyze(sym):
  mtf=multi_timeframe_analysis(sym,market)
  if not mtf: return None
  a=mtf["entry"]
  p=a["price"]; lv=levels(p,a["direction"]); src=source_consensus(sym,market)
  agreement=100 if not src["source_direction"] or src["source_direction"]==a["direction"] else 35
  rank_score=.35*src["recommendation"]+.23*a["score"]+.16*agreement+.10*src["freshness"]+.16*mtf["alignment"]
  if mtf["conflict"]: rank_score=min(rank_score,59)
  return {"market":market,"symbol":(sym.replace("USDT","/USDT") if market in ("spot","futures") else sym.replace("=X","")),
   "direction":a["direction"],"entry":round(lv[0],8),"tp1":round(lv[1],8),"tp2":round(lv[2],8),"tp3":round(lv[3],8),"sl":round(lv[4],8),
   "timeframe":"15m","entry_timeframe":"15m","analysis_timeframes":list(mtf["frames"].keys()),"higher_direction":mtf["higher_direction"],
   "higher_buys":mtf["higher_buys"],"higher_sells":mtf["higher_sells"],"timeframe_alignment":mtf["alignment"],"timeframe_conflict":mtf["conflict"],
   "ai":round(rank_score,1),"recommendation_score":round(rank_score,1),"source_count":src["source_count"],
   "freshness":src["freshness"],"mentions":round(src["recommendation"],1),"analysis_score":a["score"],
   "schools":a["schools"],"reasons":a["reasons"],"model":" + ".join(a["schools"]) if a["schools"] else "تحليل حركة السعر",
   "source_direction":src["source_direction"]}
 with ThreadPoolExecutor(max_workers=min(6,len(syms))) as ex:
  futures=[ex.submit(analyze,sym) for sym in syms]
  for f in as_completed(futures):
   try:
    row=f.result()
    if row: rows.append(row)
   except Exception: pass
 rows.sort(key=lambda x:(x["recommendation_score"],x["freshness"],x["analysis_score"]),reverse=True)
 now=time.time()
 fresh=[]
 for x in rows:
  if x["recommendation_score"] < OPPORTUNITY_MIN_SCORE:
   continue
  key=(market,x["symbol"],x["direction"])
  fp=(round(float(x["entry"]),8),round(float(x["tp1"]),8),round(float(x["sl"]),8))
  prev=OPPORTUNITY_STATE.get(key)
  if prev and prev["fp"]==fp and now-prev["seen"]<900:
   continue
  x["new_opportunity"]=True
  x["detected_at"]=now
  OPPORTUNITY_STATE[key]={"fp":fp,"seen":now}
  fresh.append(x)
 if not fresh:
  fresh=rows[:12]
 for i,x in enumerate(fresh,1):
  x["rank"]=i; x["jewel"]=i<=3
 return fresh

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
def fast_market(market="spot",timeframe="15m"): return {"market":market,"timeframe":"15m","entry_timeframe":"15m","analysis_timeframes":["15m","30m","1h","4h"],"opportunities":opportunities(market)}
def _fortune_price_symbol(symbol):
 symbol=(symbol or "").replace(" ","")
 if symbol in ("XAU","XAUUSD"): return "XAUUSD=X","forex"
 if symbol.endswith("/USDT"): return symbol.replace("/",""),"spot"
 if symbol.endswith("USDT"): return symbol,"spot"
 return symbol,"forex"

def _fortune_num(value):
 try:
  m=__import__("re").search(r"-?\d+(?:\.\d+)?",str(value or ""))
  return float(m.group(0)) if m else None
 except Exception:
  return None

def fortune_trade_analysis(signal):
 try:
  sym,market=_fortune_price_symbol(signal.get("symbol"))
  analyses={}
  for tf in ("15m","1h","4h"):
   a=price_analysis(sym,market,tf)
   if a: analyses[tf]=a
  if not analyses:
   return {"status":"unavailable","verdict":"تعذر التحليل الآن"}
  sig_dir=signal.get("direction","BUY")
  dirs=[a["direction"] for a in analyses.values()]
  agree=sum(1 for d in dirs if d==sig_dir)
  align=round(agree/max(1,len(dirs))*100,1)
  base=analyses.get("15m") or next(iter(analyses.values()))
  current=float(base["price"])
  entry=_fortune_num(signal.get("entry"))
  targets=[_fortune_num(x) for x in signal.get("targets",[])]
  targets=[x for x in targets if x is not None]
  sl=_fortune_num(signal.get("sl"))
  if entry is None: entry=current
  rr=None
  if sl is not None:
   risk=abs(entry-sl)
   valid_t=[t for t in targets if (t>entry if sig_dir=="BUY" else t<entry)]
   reward=abs(valid_t[-1]-entry) if valid_t else 0
   rr=round(reward/risk,2) if risk>0 else None
  dist=round((current/entry-1)*100,2) if entry else None
  score=base["score"]*.55+align*.30+(min(100,max(0,base["volume_ratio"]*50))*.15)
  if sig_dir!=base["direction"]: score-=18
  score=max(1,min(99,round(score,1)))
  if align>=66 and sig_dir==base["direction"] and score>=70: verdict="قوية"
  elif align>=50 and sig_dir==base["direction"] and score>=58: verdict="مقبولة"
  elif sig_dir!=base["direction"]: verdict="متعارضة"
  else: verdict="ضعيفة"
  reasons=list(base.get("reasons",[]))
  if align>=66: reasons.append("توافق زمني جيد")
  elif align<50: reasons.append("تعارض بين الاتجاهات")
  if rr is not None: reasons.append("مخاطرة/عائد "+str(rr)+"R")
  if dist is not None and abs(dist)>5: reasons.append("السعر ابتعد عن Entry")
  return {"status":"ok","score":score,"verdict":verdict,"current_price":current,
   "signal_direction":sig_dir,"market_direction":base["direction"],"alignment":align,
   "volume_ratio":base.get("volume_ratio"),"change3":base.get("change3"),"change12":base.get("change12"),
   "rr":rr,"distance_from_entry_pct":dist,"reasons":list(dict.fromkeys(reasons))[:6],
   "methods":list(dict.fromkeys(base.get("schools",[]))),
   "timeframes":{tf:{"direction":a["direction"],"score":a["score"],"volume_ratio":a["volume_ratio"]} for tf,a in analyses.items()}}
 except Exception:
  return {"status":"unavailable","verdict":"تعذر التحليل الآن"}

@app.get("/api/fortune-signals")
def api_fortune_signals():
 return {"signals":fortune_signals(),"source_count":len(FORTUNE_SOURCES),"scanned_at":time.time(),"source":"Fortune only"}

@app.get("/api/gold-signals")
def api_gold_signals():
 return api_fortune_signals()
@app.get("/api/trades")
def api_trades(market="spot",timeframe="15m"): return {"trades":trades(market)}
@app.get("/api/strategy")
def strategy(): return {"retention_hours":24,"timeframes":["15m","30m","1h","4h","1d","1w","1M"],"entry_timeframe":"15m","analysis_timeframes":["15m","30m","1h","4h"],"bot_timeframe":"15m","rules":["15m للدخول","30m لتأكيد الحركة","1h لتحديد الاتجاه","4h لتأكيد الاتجاه الأكبر","لا مؤشرات","تحليل الناس والمصادر العامة","كلاسيكي","Price Action","هارمونيك","Elliott","Wyckoff","Structure/SMC","نماذج سعرية","إحصائي","أخبار وأحداث","24h memory"]}
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

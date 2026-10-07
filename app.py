import os,time,hmac,hashlib,sqlite3,threading,requests,json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles

app=FastAPI(title="SMART TRADING PRO")
from pages import register_pages
register_pages(app)
from auth import router as auth_router
app.include_router(auth_router)
from content import router as content_router
app.include_router(content_router)
from results import router as results_router
app.include_router(results_router)
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
# Displayed trade opportunities are rebuilt after deployment; source-performance learning stays separate.
MARKETS=["spot","futures","us","saudi","contracts","forex"]
# Source trust tiers: institutional/official sources carry more weight than community feeds.
SOURCE_TRUST={"reuters_markets":100,"bloomberg_markets":100,"sec_data":100,"saudi_exchange":100,"nasdaq_market":95,"investing_analysis":85,"coinglass":85,"tradingview":80,"fxnewstoday_saudi":78,"fxleaders_signals":82,"fxleaders_gold":82,"coindesk_news":80,"cointelegraph_news":75,"dj_markets_news":80,"cnbc_markets_news":80,"cryptopanic":70,"cmc":70,"fortune_traders":65,"evening_trader":60,"crypto_ninjas":55,"bitcoin_bullets":55,"learn2trade_crypto":55,"learn2trade_news":55,"smart_crypto_signals":70,"free_crypto_signals":45,"raven_signals":75,"coin_signals":65,"quant_gold_signals":70,"tradinggain_crypto":75,"tradingpoint_crypto":65,"primal_signals":55,"gold_free_signals":55,"sureshot_gold":75,"gold_forex_signals":60,"fx_gold_free":65,"oracle_easy":70,"darwin_lab":70}
SOURCE_AUDIENCE={
 # Public audience/engagement is only a secondary signal; it can never
 # override poor measured trade performance.
 "fortune_traders":90,"smart_crypto_signals":80,"raven_signals":90,"coin_signals":85,"quant_gold_signals":80,"tradinggain_crypto":95,"tradingpoint_crypto":75,"primal_signals":45,"gold_free_signals":45,"sureshot_gold":85,"gold_forex_signals":70,"fx_gold_free":75,"oracle_easy":60,"darwin_lab":70,
}
def source_audience(name):
 return float(SOURCE_AUDIENCE.get(name,50))

def source_trust(name):
 return float(SOURCE_TRUST.get(name,50))

SOURCES=[
 ("reuters_markets","https://www.reuters.com/business/"),
 ("bloomberg_markets","https://www.bloomberg.com/markets"),
 ("investing_analysis","https://www.investing.com/rss-feeds"),
 ("nasdaq_market","https://www.nasdaq.com/market-activity"),
 ("sec_data","https://www.sec.gov/data-research"),
 ("saudi_exchange","https://www.saudiexchange.sa/"),
 ("mubasher_ksa","https://english-old.mubasher.info/news/rss"),
 ("argaam","https://www.argaam.com/en"),
 ("saudi_cma","https://cma.org.sa/en/MediaCenter/News/Pages/default.aspx"),
 ("saudi_tadawul_group","https://www.saudiexchange.sa/wps/portal/saudiexchange/home/"),
 ("saudi_stock_news","https://www.alarabiya.net/aswaq"),
 ("saudi_economy","https://www.aleqt.com/"),
 ("saudi_business","https://www.argaam.com/"),
 ("saudi_market_news","https://www.mubasher.info/countries/sa"),
 ("fxnewstoday_saudi","https://www.fxnewstoday.ae/investing/signals/"),
 ("fxleaders_signals","https://www.fxleaders.com/forex-signals/"),
 ("fxleaders_gold","https://www.fxleaders.com/news/gold-news/"),
 ("tradingview_saudi","https://www.tradingview.com/markets/stocks-ksa/ideas/"),
 ("tradingview_us","https://www.tradingview.com/markets/stocks-usa/ideas/"),

 ("fortune_traders","https://t.me/s/Fortunetradersofficial"),("evening_trader","https://t.me/s/eveningtradercryptosignals"),
 ("crypto_ninjas","https://t.me/s/cryptoninjastradingglobal"),("bitcoin_bullets","https://t.me/s/BitcoinBullets"),
 ("learn2trade_crypto","https://t.me/s/learn2tradectypto"),("learn2trade_news","https://t.me/s/learn2tradenews"),
 ("smart_crypto_signals","https://t.me/s/smartcrytptsignals"),("free_crypto_signals","https://t.me/s/free_crypto_signal_orginal"),
 ("raven_signals","https://t.me/s/ravensignalspro"),("coin_signals","https://tg.me/coin_signals"),
 ("quant_gold_signals","https://quantroomx.com/"),
 ("tradinggain_crypto","https://t.me/s/TradingGainX"),
 ("tradingpoint_crypto","https://t.me/s/tradingpointviewx"),
 ("primal_signals","https://t.me/s/primalsignalslite"),
 ("gold_free_signals","https://t.me/s/Freesignalpro"),
 ("sureshot_gold","https://t.me/s/ssfgold"),
 ("gold_forex_signals","https://t.me/s/goldforexsignalsoriginal"),
 ("fx_gold_free","https://t.me/s/fx_gold_xauusd_signals1"),
 ("oracle_easy","https://t.me/s/oracle_easy"),
 ("darwin_lab","https://t.me/s/DarwinLabSignals"),
 ("coinglass","https://www.coinglass.com/"),("cryptopanic","https://cryptopanic.com/"),("cmc","https://coinmarketcap.com/"),
 ("tradingview","https://www.tradingview.com/markets/cryptocurrencies/news/"),
 ("coindesk_news","https://www.coindesk.com/arc/outboundfeeds/rss/"),
 ("cointelegraph_news","https://cointelegraph.com/rss"),
 ("dj_markets_news","https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
 ("cnbc_markets_news","https://www.cnbc.com/id/100003114/device/rss/rss.html"),
 ("marketwatch_news","https://feeds.marketwatch.com/marketwatch/topstories"),
 ("seeking_alpha","https://seekingalpha.com/feed.xml"),
 ("seeking_alpha_market","https://seekingalpha.com/market_currents.xml"),
 ("benzinga","https://www.benzinga.com/feed"),
 ("financial_times_markets","https://www.ft.com/markets?format=rss"),
 ("economist_finance","https://www.economist.com/finance-and-economics/rss.xml"),
 ("fxstreet","https://www.fxstreet.com/rss/news"),
 ("cme_commentary","https://www.cmegroup.com/rss/commentary-home-insights-analysis.rss"),
 ("federal_reserve","https://www.federalreserve.gov/feeds/press_all.xml"),
 ("ecb_press","https://www.ecb.europa.eu/rss/press.html"),
 ("the_block","https://www.theblock.co/rss.xml"),
 ("decrypt","https://decrypt.co/feed"),
 ("bitcoin_magazine","https://bitcoinmagazine.com/feed"),
 ("cryptoslate","https://cryptoslate.com/feed/"),
 ("the_defiant","https://thedefiant.io/feed/"),
 ("protos","https://protos.com/feed"),
 ("bbc_world","https://feeds.bbci.co.uk/news/world/rss.xml"),
 ("aljazeera","https://www.aljazeera.com/xml/rss/all.xml")]
lock=threading.Lock()
SOURCE_CACHE={"at":0.0,"texts":{}}
SOURCE_TTL=60
MARKET_CACHE={}
MARKET_CACHE_TTL=21600
MARKET_UNIVERSE_CACHE={}
MARKET_UNIVERSE_TTL=21600
OPPORTUNITY_MIN_SCORE=52
OPPORTUNITY_RETENTION=21600  # never serve a market opportunity older than 6 hours
OPPORTUNITY_STATE={}
OPPORTUNITY_CACHE={}
SCAN_WORKERS=3
MAX_CRYPTO_SCAN_SYMBOLS=80
MAX_US_SCAN_SYMBOLS=60
MAX_SAUDI_SCAN_SYMBOLS=60

# Source performance memory: each market is scored independently and kept for 24h.
def _source_perf_init():
 try:
  c=db()
  c.execute("create table if not exists source_performance(id integer primary key,market text,source text,symbol text,direction text,entry real,created real,outcome integer default 0,outcome_at real)")
  c.execute("delete from source_performance where created<?",(time.time()-RETENTION,))
  c.commit(); c.close()
 except Exception: pass

def _source_perf_update(market,source,symbol,direction,entry,price_now):
 try:
  _source_perf_init(); c=db(); now=time.time(); cutoff=now-RETENTION
  rows=c.execute("select id,entry,direction,outcome from source_performance where market=? and source=? and symbol=? and created>=?",(market,source,symbol,cutoff)).fetchall()
  for rid,e,d,o in rows:
   if o: continue
   e=float(e or 0); p=float(price_now or 0)
   if not e or not p: continue
   move=(p/e-1)*100 if d=="BUY" else (e/p-1)*100
   threshold=1.0 if market in ("spot","futures") else 0.5
   stop=threshold*0.6
   outcome=1 if move>=threshold else -1 if move<=-stop else 0
   if outcome: c.execute("update source_performance set outcome=?,outcome_at=? where id=?",(outcome,now,rid))
  recent=c.execute("select 1 from source_performance where market=? and source=? and symbol=? and direction=? and created>?",(market,source,symbol,direction,now-3600)).fetchone()
  if not recent and entry:
   c.execute("insert into source_performance(market,source,symbol,direction,entry,created) values(?,?,?,?,?,?)",(market,source,symbol,direction,float(entry),now))
  c.execute("delete from source_performance where created<?",(cutoff,))
  c.commit(); c.close()
 except Exception: pass

def _source_perf_score(market,source,symbol=None):
 try:
  _source_perf_init(); c=db(); cutoff=time.time()-RETENTION
  q="select outcome from source_performance where market=? and source=? and created>=?"; args=[market,source,cutoff]
  if symbol: q+=" and symbol=?"; args.append(symbol)
  vals=[int(r[0]) for r in c.execute(q,args).fetchall() if int(r[0])!=0]; c.close()
  if not vals: return {"score":50.0,"samples":0,"wins":0,"losses":0}
  wins=sum(1 for x in vals if x>0); losses=sum(1 for x in vals if x<0); total=wins+losses
  return {"score":round(100*wins/total,1),"samples":total,"wins":wins,"losses":losses}
 except Exception: return {"score":50.0,"samples":0,"wins":0,"losses":0}

OPPORTUNITY_RUNNING=set()
# Stale trade cleanup is invoked only after its helper is defined; startup must not call it early.
# Continuous market scanning: 24h is retention only, never a waiting period.
SCAN_INTERVAL=60  # rotate the worker every minute; one market at a time to protect the small service
FORTUNE_CACHE={"at":0.0,"signals":[]}
FORTUNE_TTL=45
FORTUNE_SOURCES=[
 # Public feeds only. The app itself may contain gated/private data; this collector never bypasses it.
 ("Fortune Traders","https://t.me/s/Fortunetradersofficial"),
 ("Fortune Gold","https://t.me/s/FORTUNETRADERS1"),
 ("Fortune Results","https://t.me/s/BITCOIN_RESULTS"),
 # Public signal feed that republishes signals linked to the second app.
 ("Crypto Forex public feed","https://t.me/s/crypto_signals_bitcoin_signals")
]
FORTUNE_RETENTION=21600  # only fresh public signals from the last 6 hours

def _fortune_clean(html):
 import re,html as _html
 text=re.sub(r"<br\s*/?>","\n",html or "",flags=re.I)
 text=re.sub(r"<[^>]+>"," ",text)
 text=_html.unescape(text)
 text=text.replace("\xa0"," ")
 return re.sub(r"\s+"," ",text).strip()

def _fortune_value(text,labels):
 import re
 nums=r"(-?\d+(?:[.,]\d+)?(?:\s*[-–—]\s*-?\d+(?:[.,]\d+)?)?)"
 for label in labels:
  p=rf"(?:{label})\s*(?:[:=@#-]|\bis\b)?\s*{nums}"
  m=re.search(p,text,re.I)
  if m:
   return m.group(1).replace(",","").strip()
 return None

def _fortune_targets(text):
 import re
 out=[]
 # Prefer explicitly numbered targets, preserving the publisher's order.
 for n in range(1,13):
  v=_fortune_value(text,[rf"(?:TP|TARGET|TAKE\s*PROFIT)\s*[-# ]*{n}"])
  if v and v not in out: out.append(v)
 # Also collect any additional TP/TARGET values (including TP13+) that
 # the publisher actually wrote. Never calculate or extrapolate targets.
 for m in re.finditer(r"(?:TP|TARGET|TAKE\s*PROFIT)\s*[-# ]*(?:\d+)?\s*[:=@-]?\s*(-?\d+(?:[.,]\d+)?)",text,re.I):
  v=m.group(1).replace(",","")
  if v not in out: out.append(v)
 return out

def fortune_signals(force=False):
 now=time.time()
 with lock:
  if not force and now-FORTUNE_CACHE["at"]<FORTUNE_TTL:
   return list(FORTUNE_CACHE["signals"])

 def fetch(item):
  name,url=item
  try:
   r=requests.get(url,timeout=5,headers={"User-Agent":"Mozilla/5.0 SMART-TRADING-PRO"})
   return name,r.text if r.ok else ""
  except Exception:
   return name,""

 posts=[]
 with ThreadPoolExecutor(max_workers=min(3,len(FORTUNE_SOURCES))) as ex:
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
    pm=re.search(r'data-post="[^"]*/(\d+)"',chunk,re.I)
    post_id=pm.group(1) if pm else ""
    posts.append((name,post_id,published,body))

 signals=[]
 import re
 for source,post_id,published,body in posts:
  u=body.upper()

  # Accept the actual public signal formats: NEW FUTURES/SPOT SIGNAL,
  # explicit BUY/SELL/LONG/SHORT, and symbol hashtags.
  direction=None
  bm=re.search(r"\b(?:BUY|LONG|شراء|لونج)\b",u)
  smd=re.search(r"\b(?:SELL|SHORT|بيع|شورت)\b",u)
  if bm and (not smd or bm.start()<smd.start()): direction="BUY"
  elif smd: direction="SELL"
  elif re.search(r"\b(?:NEW\s+)?SPOT\s+SIGNAL\b|\bSPOT\s+TRADE\b",u): direction="BUY"

  # Do not discard a real signal merely because the public post hides prices.
  if not direction: continue

  sm=re.search(r"(?:#|\b)(XAUUSD|XAU|GOLD|[A-Z0-9]{2,18}\s*/?\s*USDT)(?:\b|(?=[^A-Z0-9]))",u)
  if not sm:
   if re.search(r"\bGOLD\b",u) and direction:
    symbol="XAUUSD"
   else:
    continue
  else:
   symbol=sm.group(1).replace(" ","")
   if symbol in ("XAU","GOLD"): symbol="XAUUSD"
  if symbol.endswith("USDT") and "/" not in symbol and symbol!="XAUUSD":
   symbol=symbol[:-4]+"/USDT"

  entry=_fortune_value(u,[
   r"ENTRY(?:\s+(?:PRICE|ZONE|RANGE))?",
   r"OPEN(?:\s+PRICE)?",
   r"(?:BUY|SELL|LONG|SHORT)\s*(?:NOW)?\s*@?",
   r"(?:GOLD|XAUUSD)\s+(?:BUY|SELL|LONG|SHORT)\s*(?:NOW)?"
  ])
  targets=_fortune_targets(u)
  sl=_fortune_value(u,[r"SL",r"STOP\s*LOSS",r"STOPLOSS",r"STOP"])

  # Only publish complete externally supplied trade data.
  # No entry/target/stop is invented or calculated inside the site.
  is_setup=bool(re.search(r"NEW\s+(?:TRADE|SIGNAL)|SIGNAL\s+AVAILABLE|NEW\s+TRADE\s+OPEN|ENTRY\s*[:=@]|(?:BUY|SELL|LONG|SHORT)\s*@",u,re.I))
  if not is_setup and not entry and not targets:
   continue
  # Incomplete public posts (locked/missing prices) are never shown as trades.
  if not entry or not targets or not sl:
   continue

  key=(symbol,direction,entry or "", "|".join(targets),sl or "")
  if any((x["symbol"],x["direction"],x["entry"],"|".join(x["targets"]),x.get("sl") or "")==key for x in signals):
   continue

  signals.append({
   "symbol":symbol,"direction":direction,"entry":entry,"targets":targets,
   "tp1":targets[0] if len(targets)>0 else None,"tp2":targets[1] if len(targets)>1 else None,
   "tp3":targets[2] if len(targets)>2 else None,"tp4":targets[3] if len(targets)>3 else None,
   "tp5":targets[4] if len(targets)>4 else None,"tp6":targets[5] if len(targets)>5 else None,
   "sl":sl,"source":source,"published":published,"post_id":post_id,
   "detected_at":now,"source_type":"fortune_public"
  })

 signals.sort(key=lambda x:x.get("published") or "",reverse=True)
 # Keep the signal exactly as published: entry, targets and stop only.
 with lock:
  FORTUNE_CACHE.update({"at":now,"signals":signals[:40]})
 return list(signals[:40])


def db():
 os.makedirs(os.path.dirname(DB) or ".",exist_ok=True); c=sqlite3.connect(DB,check_same_thread=False); c.execute("create table if not exists trades(id integer primary key,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created real,updated real)"); c.commit(); return c


def _clear_stale_trade_displays():
 try:
  c=db()
  c.execute("delete from trades")
  if c.execute("select 1 from sqlite_master where type='table' and name='market_cache'").fetchone(): c.execute("delete from market_cache")
  if c.execute("select 1 from sqlite_master where type='table' and name='gold_signals'").fetchone(): c.execute("delete from gold_signals")
  if c.execute("select 1 from sqlite_master where type='table' and name='recommendation_results'").fetchone(): c.execute("delete from recommendation_results where created<?",(time.time()-OPPORTUNITY_RETENTION,))
  c.commit(); c.close()
  with lock: OPPORTUNITY_CACHE.clear()
 except Exception: pass
def price(sym,market="spot"):
 try:
  base="https://fapi.binance.com/fapi/v1/ticker/price" if market=="futures" else "https://api.binance.com/api/v3/ticker/price"
  r=requests.get(base,params={"symbol":sym},timeout=4); return float(r.json()["price"])
 except: return 0
def _yahoo_symbols(sym,market):
 if market=="saudi": return [sym+".SR" if sym.isdigit() else sym]
 # XAUUSD intraday is not consistently available from Yahoo. Use the
 # continuous gold futures feed only as a DATA fallback; the displayed
 # market/symbol remains Forex & Gold and never leaks contracts into results.
 if market=="forex" and sym=="XAUUSD=X":
  return ["XAUUSD=X","GC=F"]
 return [sym]
def klines(sym,tf="15m",n=120,market="spot"):
 key=(market,sym,tf,n); now=time.time()
 cached=MARKET_CACHE.get(key)
 if cached and now-cached[0]<MARKET_CACHE_TTL: return cached[1]
 try:
  if market in ("spot","futures"):
   # Binance can transiently reject one hostname/route from a cloud region.
   # Try both public API hosts before declaring the symbol unavailable.
   bases=(["https://fapi.binance.com/fapi/v1/klines","https://fapi1.binance.com/fapi/v1/klines"]
          if market=="futures" else
          ["https://api.binance.com/api/v3/klines","https://api1.binance.com/api/v3/klines"])
   for base in bases:
    try:
     r=requests.get(base,params={"symbol":sym,"interval":tf,"limit":n},timeout=7,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
     if not r.ok: continue
     data=r.json()
     if isinstance(data,list) and len(data)>=30:
      MARKET_CACHE[key]=(now,data); return data
    except Exception:
     continue
   return []
  headers={"User-Agent":"Mozilla/5.0 (SMART-TRADING-PRO)"}
  for ysym in _yahoo_symbols(sym,market):
   r=None
   # Yahoo occasionally serves XAUUSD differently across chart hosts.
   # Try both hosts and a longer intraday window before declaring gold unavailable.
   for host in ("query1.finance.yahoo.com","query2.finance.yahoo.com"):
    for attempt in range(3):
     try:
      r=requests.get("https://"+host+"/v8/finance/chart/"+ysym,
       params={"range":"10d","interval":tf,"includePrePost":"false"},
       timeout=8,headers=headers)
      if r.ok: break
     except Exception:
      r=None
     time.sleep(0.35*(attempt+1))
    if r is not None and r.ok: break
   if not r or not r.ok: continue
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
 if len(k)<30:return None
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
 buy_terms=(r"\bBUY\b",r"\bLONG\b",r"BUY\s*ZONE",r"BUY\s*NOW",r"\bشراء\b",r"\bصاعد\b",r"\bصعود\b")
 sell_terms=(r"\bSELL\b",r"\bSHORT\b",r"SELL\s*ZONE",r"SELL\s*NOW",r"\bبيع\b",r"\bهابط\b",r"\bهبوط\b")
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

def _source_allowed_for_market(name,market):
 # Strict market isolation: each section only consumes sources relevant to that market.
 name=str(name or "").lower()
 if market=="saudi":
  return name in {"saudi_exchange","mubasher_ksa","argaam","saudi_cma","saudi_tadawul_group","saudi_stock_news","saudi_economy","saudi_business","saudi_market_news","fxnewstoday_saudi","tradingview_saudi"}
 if market=="us":
  return name in {"reuters_markets","bloomberg_markets","nasdaq_market","sec_data","investing_analysis","cnbc_markets_news","marketwatch_news","seeking_alpha","seeking_alpha_market","benzinga","financial_times_markets","tradingview_us","fxleaders_signals"}
 if market=="forex":
  return name in {"reuters_markets","bloomberg_markets","investing_analysis","tradingview","fxstreet","cme_commentary","federal_reserve","ecb_press","fxleaders_signals","fxleaders_gold","quant_gold_signals","gold_free_signals","sureshot_gold","gold_forex_signals","fx_gold_free","oracle_easy","darwin_lab"}
 if market=="contracts":
  return name in {"reuters_markets","bloomberg_markets","investing_analysis","tradingview","cme_commentary","dj_markets_news","cnbc_markets_news","fxleaders_signals","fxleaders_gold"}
 if market in ("spot","futures"):
  return name in {"fortune_traders","evening_trader","crypto_ninjas","bitcoin_bullets","learn2trade_crypto","learn2trade_news","smart_crypto_signals","free_crypto_signals","raven_signals","coin_signals","tradinggain_crypto","tradingpoint_crypto","primal_signals","coinglass","cryptopanic","cmc","tradingview","coindesk_news","cointelegraph_news","the_block","decrypt","bitcoin_magazine","cryptoslate","the_defiant","protos"}
 return True

def external_trade_signal(sym,market="spot"):
 # External-first: the site never invents Entry/TP/SL. A signal must contain
 # a real public direction plus complete published levels before it can appear.
 import re
 base=sym.replace("/USDT","").replace("USDT","").replace("=X","").replace("=F","").upper()
 aliases=[base]
 if base=="XAU": aliases += ["GOLD","XAUUSD"]
 if market in ("spot","futures") and base: aliases += [base+"USDT"]
 texts=source_snapshot()
 found=[]
 for name,t in texts.items():
  if not t or not _source_allowed_for_market(name,market): continue
  u=re.sub(r"\s+"," ",t.upper())
  hit=None
  for alias in aliases:
   m=re.search(r"(?<![A-Z0-9])"+re.escape(alias)+r"(?![A-Z0-9])",u)
   if m: hit=m; break
  if not hit: continue
  window=u[max(0,hit.start()-600):min(len(u),hit.end()+1400)]
  bd=re.search(r"\b(?:BUY|LONG|شراء|لونج|BULLISH|BULL|صاعد|صعود)\b",window)
  sd=re.search(r"\b(?:SELL|SHORT|بيع|شورت|BEARISH|BEAR|هابط|هبوط)\b",window)
  direction="BUY" if bd and (not sd or bd.start()<sd.start()) else "SELL" if sd else None
  if not direction: continue
  def val(labels):
   for lab in labels:
    mm=re.search(r"(?:%s)\s*(?:[:=@-]|\bis\b)?\s*(-?\d+(?:[.,]\d+)?)"%lab,window,re.I)
    if mm:
     try:return float(mm.group(1).replace(",",""))
     except Exception:return None
   return None
  entry=val([r"ENTRY(?:\s+(?:PRICE|ZONE|RANGE))?",r"OPEN(?:\s+PRICE)?",r"(?:BUY|SELL|LONG|SHORT)\s*@"])
  sl=val([r"SL",r"STOP\s*LOSS",r"STOPLOSS"])
  tps=[]
  for n in range(1,13):
   v=val([rf"(?:TP|TARGET|TAKE\s*PROFIT)\s*[-# ]*{n}"])
   if v is not None and v not in tps: tps.append(v)
  # Always scan for extra targets so TP7+ is retained when TP1-6 exist.
  for mm in re.finditer(r"(?:TP|TARGET|TAKE\s*PROFIT)\s*[-# ]*(?:\d+)?\s*[:=@-]?\s*(-?\d+(?:[.,]\d+)?)",window,re.I):
   v=float(mm.group(1).replace(",",""))
   if v not in tps: tps.append(v)
  # Bootstrap performance from genuine published entries. The old code updated
  # performance only after the minimum-sample gate, so sources could never
  # accumulate their first 3 observations.
  if entry is not None:
   try:
    live_price=price(sym.replace("/USDT","USDT"),market) if market in ("spot","futures") else price(sym,market)
    _source_perf_update(market,name,base,direction,entry,live_price)
   except Exception:
    pass
  perf=_source_perf_score(market,name,base)
  complete=entry is not None and sl is not None and len(tps)>0
  # New sources are allowed to bootstrap only when they publish a complete setup
  # and have reasonable source trust. Once 3+ outcomes exist, measured results
  # become the gate and override popularity/reach.
  trust_score=source_trust(name)
  if not complete: continue
  if perf["samples"]>=3 and perf["score"]<60: continue
  if perf["samples"]>=5 and perf["score"]<65: continue
  setup_weight=1.0
  performance_factor=(0.75 + 0.25*(perf["score"]/100.0)) if perf["samples"] else 0.80
  found.append({"source":name,"direction":direction,"entry":entry,"sl":sl,"targets":tps,
                "weight":round(setup_weight*(trust_score/100.0)*performance_factor,3),
                "trust":trust_score,"performance":perf})
 if not found:return None
 buys=sum(x["weight"] for x in found if x["direction"]=="BUY")
 sells=sum(x["weight"] for x in found if x["direction"]=="SELL")
 direction="BUY" if buys>sells else "SELL" if sells>buys else None
 if not direction:return None
 agreeing=[x for x in found if x["direction"]==direction]
 best=max(agreeing,key=lambda x:(x["performance"]["score"],x["trust"],x["performance"]["samples"]))
 targets=best.get("targets") or []
 return {"direction":direction,"entry":best.get("entry"),"tp1":targets[0] if len(targets)>0 else None,
         "tp2":targets[1] if len(targets)>1 else None,"tp3":targets[2] if len(targets)>2 else None,
         "tp4":targets[3] if len(targets)>3 else None,"tp5":targets[4] if len(targets)>4 else None,"tp6":targets[5] if len(targets)>5 else None,
         "targets":targets,"target_count":len(targets),
         "sl":best.get("sl"),"sources":found,"source":best.get("source"),"source_count":len(agreeing),
         "agreement":round(100*sum(x["weight"] for x in agreeing)/max(0.01,sum(x["weight"] for x in found)),1),
         "complete":True,"complete_sources":len(agreeing)}

def source_consensus(sym,market="spot"):
 aliases={"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT","BNB":"BNBUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","SUI":"SUIUSDT","LINK":"LINKUSDT","AVAX":"AVAXUSDT"}
 base=sym.replace("/USDT","").replace("USDT","")
 keys=[base]
 if base in aliases: keys.append(aliases[base])
 if market=="saudi": keys += [base]
 if market in ("us","contracts","forex"): keys += [base.upper()]
 source_results=[]
 mention_count=0
 snap=source_snapshot()
 for name,t in snap.items():
  if not t: continue
  d=_source_context_direction(t,keys)
  try:
   mention_count += len(re.findall(r"(?<![A-Z0-9])"+re.escape(base)+r"(?:USDT)?(?![A-Z0-9])",str(t),re.I))
  except Exception:
   pass
  if d: source_results.append((name,d))
 buy=sum(1 for _,d in source_results if d=="BUY")
 sell=sum(1 for _,d in source_results if d=="SELL")
 count=len(source_results)
 direction="BUY" if buy>sell else "SELL" if sell>buy else None
 agreement=max(buy,sell)
 # Recommendation is based only on explicit, symbol-linked source calls.
 # Mere mentions, generic BUY/SELL words, or unrelated calls score zero.
 recommendation=round((agreement/max(1,count))*100,1) if count else 0
 trust_vals=[source_trust(n) for n,_ in source_results]
 source_trust_score=round(sum(trust_vals)/len(trust_vals),1) if trust_vals else 50.0
 now=time.time()
 with lock:
  snapshot_age=max(0,now-SOURCE_CACHE.get("at",0))
 if snapshot_age<=30: freshness=100
 elif snapshot_age<=90: freshness=85
 elif snapshot_age<=300: freshness=60
 elif snapshot_age<=900: freshness=30
 else: freshness=0
 # Performance is updated only when the public source supplied a real entry.
 # This prevents the site's live price from being recorded as the source's entry.
 perf=[_source_perf_score(market,name,base) for name,d in source_results]
 perf_score=round(sum(x["score"] for x in perf)/len(perf),1) if perf else 50.0
 return {"source_count":count,"source_buy":buy,"source_sell":sell,
         "source_direction":direction,"recommendation":recommendation,
         "freshness":freshness,"performance_score":perf_score,
         "performance_samples":sum(x["samples"] for x in perf),
         "performance_wins":sum(x["wins"] for x in perf),
         "performance_losses":sum(x["losses"] for x in perf)}

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
def source_snapshot():
 now=time.time()
 with lock:
  if now-SOURCE_CACHE.get("at",0)<SOURCE_TTL and SOURCE_CACHE.get("texts"):
   return dict(SOURCE_CACHE.get("texts",{}))
 def fetch(item):
  name,url=item
  try:
   r=requests.get(url,timeout=2,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
   return name,r.text if r.ok else ""
  except Exception:
   return name,""
 texts={}
 with ThreadPoolExecutor(max_workers=min(4,len(SOURCES))) as ex:
  futures=[ex.submit(fetch,item) for item in SOURCES]
  for future in as_completed(futures):
   try:
    name,text=future.result()
    if text: texts[name]=text
   except Exception:
    pass
 with lock:
  if texts:
   SOURCE_CACHE.update({"at":now,"texts":texts})
  else:
   SOURCE_CACHE["at"]=now
  return dict(SOURCE_CACHE.get("texts",{}))

def public_mentions():
 out={}
 for t in source_snapshot().values():
  for s in ["BTC","ETH","SOL","BNB","XRP","DOGE","ADA","SUI","LINK","AVAX","MATIC","DOT"]:
   if s in t: out[s]=out.get(s,0)+1
 return out
def _yahoo_volume_universe(region="US",min_volume=1000000):
 key=("yahoo_volume",region,int(min_volume)); now=time.time()
 cached=MARKET_UNIVERSE_CACHE.get(key)
 if cached and now-cached[0]<MARKET_UNIVERSE_TTL: return cached[1]
 out=[]; headers={"User-Agent":"Mozilla/5.0 (SMART-TRADING-PRO)"}
 try:
  body={"query":{"operator":"AND","operands":[{"operator":"EQ","operands":["region",region.lower()]},{"operator":"GT","operands":["dayvolume",int(min_volume)]}]},"offset":0,"size":250,"sortField":"dayvolume","sortType":"DESC"}
  offset=0; total=0
  while True:
   body["offset"]=offset
   r=requests.post("https://query2.finance.yahoo.com/v1/finance/screener",json=body,params={"corsDomain":"finance.yahoo.com","formatted":"false","lang":"en-US","region":region},timeout=6,headers=headers)
   if not r.ok: break
   result=((r.json().get("finance") or {}).get("result") or [])
   if not result: break
   block=result[0]; quotes=block.get("quotes") or []; total=int(block.get("total") or 0)
   for q in quotes:
    sym=str(q.get("symbol") or "").strip()
    try: vol=float(q.get("regularMarketVolume") or q.get("dayvolume") or 0)
    except: vol=0
    if sym and vol>=min_volume: out.append((vol,sym))
   offset+=len(quotes)
   if not quotes or offset>=total or offset>=5000: break
 except Exception: out=[]
 if not out:
  try:
   r=requests.get("https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved",params={"scrIds":"most_actives","count":250,"formatted":"false","lang":"en-US","region":region,"corsDomain":"finance.yahoo.com"},timeout=6,headers=headers)
   if r.ok:
    result=((r.json().get("finance") or {}).get("result") or [])
    for q in (result[0].get("quotes") if result else []) or []:
     sym=str(q.get("symbol") or "").strip()
     try: vol=float(q.get("regularMarketVolume") or 0)
     except: vol=0
     if sym and vol>=min_volume: out.append((vol,sym))
  except Exception: pass
 best={}
 for vol,sym in out: best[sym]=max(vol,best.get(sym,0))
 result=sorted(((v,k) for k,v in best.items()),reverse=True)
 MARKET_UNIVERSE_CACHE[key]=(now,result)
 return result

def _information_count_for_trade(symbol, market, source_snapshot=None):
    """Count only collected public information tied to this exact symbol/trade."""
    try:
        snap = source_snapshot or {}
        total = 0
        for _, value in snap.items():
            if isinstance(value, (list, tuple)):
                total += len(value)
            elif isinstance(value, dict):
                total += len(value)
            elif value:
                total += 1
        return max(1, int(total))
    except Exception:
        return 1

def _published_trade_candidates(market, texts=None, limit=60):
 # Source-first discovery: find symbols that appear next to a real public trade setup.
 # This does not create levels; external_trade_signal() still validates Entry/SL/TP.
 import re
 texts=texts or source_snapshot()
 found=[]; seen=set()
 patterns={
  "spot":r"\b[A-Z0-9]{2,15}USDT\b",
  "futures":r"\b[A-Z0-9]{2,15}USDT\b",
  "us":r"\$([A-Z]{1,5})\b",
  "saudi":r"(?<!\d)(\d{3,5})(?!\d)",
  "contracts":r"\b(?:GC|CL|SI|NG|ES|NQ|YM|RTY)(?:=F)?\b",
  "forex":r"\b(?:XAUUSD|EURUSD|GBPUSD|USDJPY|AUDUSD|USDCHF|USDCAD|NZDUSD)(?:=X)?\b"
 }
 pat=patterns.get(market,patterns["spot"])
 for name,raw in texts.items():
  if not raw or not _source_allowed_for_market(name,market): continue
  u=re.sub(r"\s+"," ",str(raw).upper())
  for m in re.finditer(pat,u):
   token=(m.group(1) if m.lastindex else m.group(0)).upper()
   if market in ("spot","futures") and not token.endswith("USDT"): continue
   # Only promote a symbol if a complete-looking trade vocabulary is nearby.
   window=u[max(0,m.start()-900):min(len(u),m.end()+1600)]
   if not re.search(r"\b(?:BUY|SELL|LONG|SHORT|شراء|بيع|ENTRY|OPEN|SL|STOP\s*LOSS|TP\s*[-#]?\d*|TARGET\s*[-#]?\d*)\b",window,re.I):
    continue
   key=token
   if key in seen: continue
   seen.add(key)
   found.append(key)
   if len(found)>=limit: return found
 return found

def _scan_opportunities(market="spot"):
 cache_key=market
 syms_by_market={
  "spot":["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","LTCUSDT"],
  "futures":["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","SUIUSDT","LINKUSDT","AVAXUSDT","ADAUSDT"],
  "us":["AAPL","NVDA","MSFT","AMZN","META","TSLA","GOOGL","AMD","NFLX","AVGO"],
  "saudi":["2222","1120","2010","7010","1180","1211","2380","2050","1150","4003"],
  "contracts":["GC=F","CL=F","SI=F","NG=F","ES=F","NQ=F","YM=F","RTY=F"],
  "forex":["XAUUSD=X","EURUSD=X","GBPUSD=X","JPY=X","AUDUSD=X","CHF=X","CAD=X","NZDUSD=X"]
 }
 texts=source_snapshot()
 # Source-first: candidates from actual public trade pages get priority before broad market scanning.
 source_candidates=_published_trade_candidates(market,texts,limit=60)
 discovered_source="public_sources"
 discovery_error=None
 syms=list(syms_by_market.get(market,syms_by_market["spot"])); rows=[]
 # Put source-published candidates first; the rest are fallback market discovery only.
 if source_candidates:
  syms=list(dict.fromkeys(source_candidates+syms))
 if market=="contracts":
  syms=[x for x in syms if x.endswith("=F")]
 elif market=="us":
  syms=[x for x in syms if not x.endswith("=F") and not x.endswith("=X")]
 elif market=="forex":
  syms=[x for x in syms if x.endswith("=X")]
 if market=="forex":
  gold="XAUUSD=X"
  syms=[gold]+[x for x in syms if x!=gold]

 if market in ("spot","futures"):
  # Discover the complete Binance USDT universe first. Try both public hosts so a
  # temporary block on one hostname never makes the whole crypto market disappear.
  bases=(["https://fapi.binance.com/fapi/v1/ticker/24hr","https://fapi1.binance.com/fapi/v1/ticker/24hr"]
         if market=="futures" else
         ["https://api.binance.com/api/v3/ticker/24hr","https://api1.binance.com/api/v3/ticker/24hr"])
  universe=None
  for base in bases:
   try:
    rr=requests.get(base,timeout=8,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
    if rr.ok:
     data=rr.json()
     if isinstance(data,list) and data:
      universe=data
      break
   except Exception:
    continue
  if universe is not None:
   candidates=[]
   for z in universe:
    s=str(z.get("symbol","")).strip().upper()
    q=str(z.get("quoteAsset","")).strip().upper()
    try: vol=float(z.get("quoteVolume",0) or 0)
    except Exception: vol=0
    if (s.endswith("USDT") and q=="USDT" and vol>=1000000
        and not any(x in s for x in ("USDC","FDUSD","USDP","TUSD","DAI","USDE","USDS"))):
     candidates.append((vol,s))
   candidates.sort(reverse=True)
   syms=[s for _,s in candidates[:MAX_CRYPTO_SCAN_SYMBOLS]] or syms[:MAX_CRYPTO_SCAN_SYMBOLS]
   discovered_source="binance"
  else:
   discovery_error="تعذر جلب قائمة Binance الكاملة، تم استخدام القائمة الاحتياطية"
 elif market=="us":
  discovered=_yahoo_volume_universe("US",250000)
  if discovered:
   # Do not attempt thousands of Yahoo intraday requests on every background scan.
   # Keep a practical liquid US universe and always retain the built-in majors.
   liquid=[s for _,s in discovered][:MAX_US_SCAN_SYMBOLS]
   syms=list(dict.fromkeys(syms+liquid))[:MAX_US_SCAN_SYMBOLS]
   discovered_source="yahoo"
  else:
   # The built-in US universe remains usable even when Yahoo's screener is unavailable.
   syms=list(dict.fromkeys(syms))
   discovery_error="تعذر جلب قائمة الأسهم الأمريكية بالحجم، تم استخدام القائمة الاحتياطية"
 elif market=="saudi":
  discovered=_yahoo_volume_universe("SA",250000)
  # Yahoo's SA screener can occasionally return non-Saudi symbols. Never let
  # those leak into the Saudi page: only Saudi Exchange tickers ending in .SR
  # (or their numeric form) are valid here.
  if discovered:
   saudi_only=[]
   for _, raw in discovered:
    sym=str(raw).strip().upper()
    if sym.endswith(".SR") and sym[:-3].isdigit():
     saudi_only.append(sym[:-3])
    elif sym.isdigit() and 3 <= len(sym) <= 5:
     saudi_only.append(sym)
   syms=list(dict.fromkeys(saudi_only+syms))
   # Keep the safety net Saudi-only too; no AAPL/NVDA/etc can enter this page.
   syms=[s for s in syms if str(s).strip().upper().isdigit()][:MAX_SAUDI_SCAN_SYMBOLS]
   discovered_source="yahoo_saudi"
  else:
   syms=[s for s in syms if str(s).strip().isdigit()][:MAX_SAUDI_SCAN_SYMBOLS]
   discovery_error="تعذر جلب قائمة الأسهم السعودية بالحجم، تم استخدام القائمة الاحتياطية"

 discovered_count=len(syms)
 failed=[]

 def analyze(sym):
  try:
   # INTERNET-ONLY: display only a real setup published publicly with Entry/TP/SL.
   # Never generate or infer trade levels from the site's own price analysis.
   ext=external_trade_signal(sym,market)
   src=source_consensus(sym,market)
   if not ext or not ext.get("complete"):
    return None, "no_complete_external_trade"
   direction=ext.get("direction")
   entry=ext.get("entry")
   sl=ext.get("sl")
   targets=ext.get("targets") or []
   if not direction or entry is None or sl is None or not targets:
    return None, "incomplete_external_trade"

   source_direction=src.get("source_direction")
   source_alignment=100 if source_direction==direction else 45
   external_agreement=float(ext.get("agreement") or 0)
   trust_values=[float(x.get("trust",50)) for x in ext.get("sources",[])]
   trust_score=(sum(trust_values)/len(trust_values)) if trust_values else 50.0
   source_name=ext.get("source","")
   audience_score=source_audience(source_name)
   performance_score=float(src.get("performance_score",50))
   chatter=min(100.0, float(src.get("mention_count",0))*4.0 + float(src.get("source_count",0))*8.0)
   external_score=.38*performance_score+.18*external_agreement+.12*trust_score+.08*audience_score+.08*src["freshness"]+.16*chatter

   return {
    "market":market,
    "symbol":(sym.replace("USDT","/USDT") if market in ("spot","futures") else sym.replace("=X","")),
    "direction":direction,
    "entry":round(float(entry),8),
    "tp1":round(float(targets[0]),8),
    "tp2":round(float(targets[1]),8) if len(targets)>1 else None,
    "tp3":round(float(targets[2]),8) if len(targets)>2 else None,
    "targets":[round(float(v),8) for v in targets],
    "sl":round(float(sl),8),
    "timeframe":"15m","entry_timeframe":"15m","analysis_timeframes":["15m"],
    "higher_direction":None,"higher_buys":0,"higher_sells":0,
    "timeframe_alignment":source_alignment,"timeframe_conflict":False,
    "ai":round(external_score,1),"recommendation_score":round(external_score,1),
    "source_count":src["source_count"],"external_sources":src["source_count"],"mention_count":src.get("mention_count",0),
    "external_score":round(external_score,1),"freshness":src["freshness"],
    "external_agreement":external_agreement,"external_complete":True,
    "levels_source":"external",
    "mentions":round(src["recommendation"],1),
    "source_performance":performance_score,"source_trust":round(trust_score,1),
    "source_audience":round(audience_score,1),
    "performance_samples":src["performance_samples"],
    "performance_wins":src["performance_wins"],"performance_losses":src["performance_losses"],
    "analysis_score":0,"schools":[],"reasons":["صفقة منشورة فعلياً على الإنترنت"],
    "model":"صفقات الإنترنت فقط",
    "source_direction":source_direction,"new_opportunity":True
   }, None
  except Exception as e:
   return None, type(e).__name__

 workers=min(SCAN_WORKERS,max(1,len(syms)))
 for start in range(0,len(syms),workers):
  batch=syms[start:start+workers]
  with ThreadPoolExecutor(max_workers=workers) as ex:
   futures={ex.submit(analyze,sym):sym for sym in batch}
   for f in as_completed(futures):
    sym=futures[f]
    try:
     row,reason=f.result()
    except Exception as e:
     row,reason=None,type(e).__name__
    if row:
     rows.append(row)
    else:
     failed.append({"symbol":sym,"reason":reason or "unknown"})

 rows.sort(key=lambda x:(x.get("mention_count",0),x.get("source_count",0),x.get("recommendation_score",0),x.get("source_performance",50)),reverse=True)
 now=time.time()
 stats={
  "market":market,
  "discovered":discovered_count,
  "analyzed":discovered_count,
  "valid_15m":len(rows),
  "failed":len(failed),
  "source":discovered_source,
  "min_daily_volume":250000 if market in ("spot","futures","us","saudi") else None,
  "timeframe":"15m",
  "failed_symbols":[x["symbol"] for x in failed[:100]],
  "failed_reasons":{},
  "discovery_error":discovery_error,
  "updated_at":now
 }
 for x in failed:
  stats["failed_reasons"][x["reason"]]=stats["failed_reasons"].get(x["reason"],0)+1

 if not rows:
  with lock:
   cached=OPPORTUNITY_CACHE.get(cache_key,{})
   cached_rows=list(cached.get("rows",[]))
   cached_stats=dict(cached.get("stats",{}))
  if cached_rows:
   stats["using_cached_rows"]=True
   stats["cached_valid_15m"]=len(cached_rows)
   with lock:
    OPPORTUNITY_CACHE[cache_key]={"at":now,"rows":cached_rows,"stats":stats}
   _save_opportunity_store(cache_key,cached_rows,stats)
   return cached_rows

 fresh=rows
 for i,x in enumerate(fresh,1):
  x["rank"]=i
  x["jewel"]=i<=3
  x["detected_at"]=now
 with lock:
  OPPORTUNITY_CACHE[cache_key]={"at":now,"rows":fresh,"stats":stats}
 _save_opportunity_store(cache_key,fresh,stats)
 return fresh

def _trade_outcome(row):
 # Live outcome display: never invent a win. Compare current public price with
 # the publisher's actual Entry/TP/SL levels. Profit is the theoretical move
 # from entry to the current price, while target percentages are fixed from
 # the published setup.
 try:
  market=str(row.get("market") or "").lower()
  raw=str(row.get("symbol") or "").replace("/USDT","USDT").replace("/","")
  price=None
  if market in ("spot","futures") and raw.endswith("USDT"):
   host="https://fapi.binance.com/fapi/v1/ticker/price" if market=="futures" else "https://api.binance.com/api/v3/ticker/price"
   rr=requests.get(host,params={"symbol":raw},timeout=2,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
   if rr.ok: price=float((rr.json() or {}).get("price"))
  if price is None: return row
  entry=float(row.get("entry")); direction=str(row.get("direction") or "BUY").upper()
  levels=[row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("tp4"),row.get("tp5"),row.get("tp6")]
  levels=[float(x) for x in levels if x not in (None,"")]
  sl=float(row.get("sl"))
  if direction=="SELL":
   profit=(entry-price)/entry*100
   hit_sl=price>=sl
   hit=[i+1 for i,x in enumerate(levels) if price<=x]
  else:
   profit=(price-entry)/entry*100
   hit_sl=price<=sl
   hit=[i+1 for i,x in enumerate(levels) if price>=x]
  target_pcts=[]
  for x in levels:
   target_pcts.append(round(((entry-x)/entry*100 if direction=="SELL" else (x-entry)/entry*100),2))
  sl_pct=round(((sl-entry)/entry*100),2) if direction=="SELL" else round(((sl-entry)/entry*100),2)
  row["live_price"]=round(price,10)
  row["profit_pct"]=round(profit,2)
  row["target_profit_pcts"]=target_pcts
  row["sl_pct"]=sl_pct
  row["hit_targets"]=hit
  row["highest_target_hit"]=max(hit) if hit else 0
  row["outcome"]="SL" if hit_sl else ("TP"+str(max(hit)) if hit else "OPEN")
  row["outcome_live"]=True
  return row
 except Exception:
  return row

def _decorate_trade_outcomes(rows):
 # Keep the operation bounded: only decorate the displayed rows.
 out=[]
 for row in rows[:20]:
  out.append(_trade_outcome(dict(row)))
 return out

def _load_opportunity_store(market):
 # Persist the latest successful market scan for 24h so a fresh browser/app
 # process can render immediately instead of showing an endless loading state.
 try:
  c=db()
  c.execute("create table if not exists market_cache(market text primary key, rows text, stats text, updated real)")
  cutoff=time.time()-OPPORTUNITY_RETENTION
  c.execute("delete from market_cache where updated<?",(cutoff,))
  row=c.execute("select rows,stats,updated from market_cache where market=?",(market,)).fetchone()
  c.commit(); c.close()
  if not row or not row[0]: return None
  rows=json.loads(row[0]); stats=json.loads(row[1] or "{}")
  if not isinstance(rows,list): return None
  stats["updated_at"]=float(row[2] or stats.get("updated_at") or 0)
  return {"rows":rows,"stats":stats,"at":float(row[2] or 0)}
 except Exception:
  return None

def _save_opportunity_store(market,rows,stats):
 try:
  c=db()
  c.execute("create table if not exists market_cache(market text primary key, rows text, stats text, updated real)")
  now=time.time()
  c.execute("insert into market_cache(market,rows,stats,updated) values(?,?,?,?) "
            "on conflict(market) do update set rows=excluded.rows,stats=excluded.stats,updated=excluded.updated",
            (market,json.dumps(rows,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),now))
  c.execute("delete from market_cache where updated<?",(now-OPPORTUNITY_RETENTION,))
  c.commit(); c.close()
 except Exception:
  pass

@app.get("/api/radar")
def radar_api():
 out=[]
 for market in MARKETS:
  try:
   out.extend(opportunities(market))
  except Exception:
   pass
 out.sort(key=lambda x:(float(x.get("recommendation_score") or 0),float(x.get("external_agreement") or 0),float(x.get("source_performance") or 0)),reverse=True)
 return {"opportunities":_decorate_trade_outcomes(out[:20]),"markets":MARKETS,"external_first":True,"generated_at":time.time()}

def opportunities(market="spot"):
 # Load only the fresh 6h snapshot; stale opportunities are never shown.
 # The first request triggers a fresh public-source scan in the background.
 now=time.time()
 with lock:
  cached=OPPORTUNITY_CACHE.get(market,{})
  rows=list(cached.get("rows",[]))
  if not rows:
   stored=_load_opportunity_store(market)
   if stored:
    rows=list(stored.get("rows",[]))
    OPPORTUNITY_CACHE[market]=stored
  running=market in OPPORTUNITY_RUNNING
  if not running:
   OPPORTUNITY_RUNNING.add(market)
   threading.Thread(target=_scan_market_background,args=(market,),daemon=True).start()
 return rows

def _scan_market_background(market):
 try:
  _scan_opportunities(market)
 except Exception as e:
  with lock:
   cached=OPPORTUNITY_CACHE.get(market,{})
   stats=dict(cached.get("stats",{}))
   stats["background_error"]=type(e).__name__
   stats["updated_at"]=time.time()
   OPPORTUNITY_CACHE[market]={"at":time.time(),"rows":list(cached.get("rows",[])),"stats":stats}
 finally:
  with lock:
   OPPORTUNITY_RUNNING.discard(market)


def _continuous_market_scan():
 # One worker rotates through the markets instead of scanning every market at once.
 # Empty/stale sections get priority; populated fresh sections wait their turn.
 # This makes the service keep looking for real public trades without exhausting 512MB RAM.
 cursor=0
 while True:
  try:
   now=time.time()
   candidates=[]
   with lock:
    for m in MARKETS:
     cached=OPPORTUNITY_CACHE.get(m,{})
     rows=list(cached.get("rows",[]))
     at=float(cached.get("at") or 0)
     age=now-at if at else 10**9
     # Empty sections are always high priority. Otherwise refresh after retention.
     priority=0 if not rows else (1 if age>=OPPORTUNITY_RETENTION else 2)
     candidates.append((priority,age,m))
   candidates.sort(key=lambda x:(x[0],-x[1]))
   market=candidates[cursor % len(candidates)][2] if candidates else MARKETS[0]
   cursor+=1
   with lock:
    running=bool(OPPORTUNITY_RUNNING)
    if not running: OPPORTUNITY_RUNNING.add(market)
   if not running:
    try:
     _scan_opportunities(market)
    except Exception:
     pass
    finally:
     with lock: OPPORTUNITY_RUNNING.discard(market)
  except Exception:
   with lock: OPPORTUNITY_RUNNING.clear()
  time.sleep(max(90,SCAN_INTERVAL))

# Keep the rotating scanner available; startup can launch it only through the normal app lifecycle.

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
def home(): return open("static/home.html",encoding="utf8").read()
@app.get("/health")
def health(): return {"ok":True,"service":"SMART TRADING PRO"}
@app.get("/api/opportunities")
def opp(market="spot"):
 try:
  rows=opportunities(market)
 except Exception:
  with lock:
   cached=OPPORTUNITY_CACHE.get(market,{})
   rows=list(cached.get("rows",[]))
 stats=OPPORTUNITY_CACHE.get(market,{}).get("stats",{})
 try: live=trades(market)
 except Exception: live=[]
 return {"ok":True,"opportunities":rows,"market":market,"market_data":{market:rows},
         "scan_stats":stats,
         "radar":{"sources_live":len(SOURCES),"sources_total":len(SOURCES)},
         "live_trades":live}
@app.get("/api/fast-market")
def fast_market(market="spot",timeframe="15m"):
 try:
  rows=opportunities(market)
 except Exception:
  with lock:
   rows=list(OPPORTUNITY_CACHE.get(market,{}).get("rows",[]))
 return {"ok":True,"market":market,"timeframe":"15m","entry_timeframe":"15m",
         "analysis_timeframes":["15m","30m","1h","4h"],"opportunities":rows,
         "scan_stats":OPPORTUNITY_CACHE.get(market,{}).get("stats",{})}
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
 return {"signals":fortune_signals(),"source_count":len(FORTUNE_SOURCES),"scanned_at":time.time(),"source":"golden_trades_public_feeds"}

def _load_gold_store():
 try:
  c=db()
  c.execute("create table if not exists gold_signals(id integer primary key,skey text unique,data text,created real,updated real)")
  cutoff=time.time()-RETENTION
  c.execute("delete from gold_signals where updated<?",(cutoff,))
  rows=c.execute("select data from gold_signals where updated>=? order by updated desc",(cutoff,)).fetchall()
  c.commit(); c.close()
  out=[]
  for (raw,) in rows:
   try:
    x=json.loads(raw)
    if isinstance(x,dict): out.append(x)
   except Exception: pass
  return out
 except Exception:
  return []

def _save_gold_store(signals):
 try:
  c=db()
  c.execute("create table if not exists gold_signals(id integer primary key,skey text unique,data text,created real,updated real)")
  now=time.time(); cutoff=now-RETENTION
  for x in signals:
   skey="|".join([str(x.get("symbol") or ""),str(x.get("direction") or ""),str(x.get("entry") or ""),str(x.get("sl") or ""),"|".join(map(str,x.get("targets") or []))])
   c.execute("insert into gold_signals(skey,data,created,updated) values(?,?,?,?) on conflict(skey) do update set data=excluded.data,updated=excluded.updated",
             (skey,json.dumps(x,ensure_ascii=False),float(x.get("detected_at") or now),now))
  c.execute("delete from gold_signals where updated<?",(cutoff,))
  c.commit(); c.close()
 except Exception:
  pass

@app.get("/api/gold-signals")
def api_gold_signals():
 signals=[]
 for x in fortune_signals():
  sym=str(x.get("symbol") or "").upper()
  if sym in ("XAUUSD","XAGUSD"):
   signals.append(dict(x))
 if signals:
  _save_gold_store(signals)
 stored=_load_gold_store()
 merged=[]
 seen=set()
 for x in signals+stored:
  key="|".join([str(x.get("symbol") or ""),str(x.get("direction") or ""),str(x.get("entry") or ""),str(x.get("sl") or ""),"|".join(map(str,x.get("targets") or []))])
  if key in seen: continue
  seen.add(key)
  a=fortune_trade_analysis(x)
  x["ai"]=a.get("score",0) if a.get("status")=="ok" else 0
  x["analysis_score"]=x["ai"]
  x["verdict"]=a.get("verdict","غير متاح")
  x["alignment"]=a.get("alignment",0)
  x["source_count"]=0
  x["external_sources"]=0
  merged.append(x)
 merged.sort(key=lambda x:x.get("published") or x.get("detected_at") or "",reverse=True)
 return {"signals":merged[:20],"source_count":0,"scanned_at":time.time()}
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


# Start one lightweight rotating public-signal worker after the full app is loaded.
# It gives empty/stale market sections priority and never runs more than one scan at once.
@app.on_event("startup")
def _start_public_signal_worker():
 try:
  t=threading.Thread(target=_continuous_market_scan,name="public-signal-rotator",daemon=True)
  t.start()
 except Exception:
  pass

def trades(market=None):
 c=db(); c.execute("delete from trades where created<?",(time.time()-RETENTION,)); c.commit(); q="select id,market,symbol,direction,entry,tp1,tp2,tp3,sl,status,created,updated from trades"; args=()
 if market:q+=" where market=?";args=(market,)
 return [dict(zip(["id","market","symbol","direction","entry","tp1","tp2","tp3","sl","status","created","updated"],r)) for r in c.execute(q,args).fetchall()]

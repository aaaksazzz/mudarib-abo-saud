import time,sqlite3,threading
from fastapi import APIRouter
router=APIRouter()
DB="/data/trading.db" if __import__("os").path.isdir("/data") else "trading.db"
RETENTION=86400  # results and closed outcomes are retained for 24 hours only
MARKETS=["spot","futures","contracts","us","saudi","forex","alpha"]
# Serialize result collection inside the single Uvicorn process. The endpoint both reads and writes
# the same SQLite file, so overlapping refreshes can otherwise contend on the writer lock.
RESULTS_LOCK=threading.RLock()
def db():
 c=sqlite3.connect(DB,timeout=60,check_same_thread=False)
 c.execute("pragma busy_timeout=60000")
 try: c.execute("pragma journal_mode=WAL")
 except sqlite3.OperationalError: pass
 c.execute("pragma synchronous=NORMAL")
 c.execute("""create table if not exists recommendation_results(id integer primary key,market text,symbol text,direction text,entry real,tp1 real,tp2 real,tp3 real,sl real,created real,updated real,status text default 'OPEN',hit_target integer default 0,result_price real,result_at real,timeframe text default '15m',strategy_key text default 'technical-confluence',method_votes text default '{}',base_score real default 0)""")
 for col,ddl in (
  ("timeframe","ALTER TABLE recommendation_results ADD COLUMN timeframe text DEFAULT '15m'"),
  ("strategy_key","ALTER TABLE recommendation_results ADD COLUMN strategy_key text DEFAULT 'technical-confluence'"),
  ("method_votes","ALTER TABLE recommendation_results ADD COLUMN method_votes text DEFAULT '{}'"),
  ("base_score","ALTER TABLE recommendation_results ADD COLUMN base_score real DEFAULT 0"),
 ):
  try: c.execute("SELECT "+col+" FROM recommendation_results LIMIT 1")
  except Exception:
   try: c.execute(ddl)
   except Exception: pass
 c.execute("create table if not exists app_migrations(key text primary key,value text)")
 # One-time clean reset: remove stale historical counters/cards and only count recommendations
 # published after this reset point. The marker persists across restarts.
 reset_key="results_reset_20261012"
 marker=c.execute("select value from app_migrations where key=?",(reset_key,)).fetchone()
 if not marker:
  reset_at=time.time()
  c.execute("delete from recommendation_results")
  c.execute("insert into app_migrations(key,value) values(?,?)",(reset_key,str(reset_at)))
 c.commit(); return c
def _num(v):
 try:return float(v)
 except:return None
def _eval(c,row,p):
 rid,market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,result_price,result_at=row[:15]
 if status in ("WIN","LOSS","EXPIRED"): return status
 p=_num(p); e=_num(entry)
 if not p or not e:return "OPEN"
 if direction=="BUY":
  if sl is not None and p<=float(sl): c.execute("update recommendation_results set status='LOSS',updated=?,result_price=?,result_at=? where id=?",(time.time(),p,time.time(),rid)); return "LOSS"
  hits=[i+1 for i,t in enumerate([tp1,tp2,tp3]) if t is not None and p>=float(t)]
 else:
  if sl is not None and p>=float(sl): c.execute("update recommendation_results set status='LOSS',updated=?,result_price=?,result_at=? where id=?",(time.time(),p,time.time(),rid)); return "LOSS"
  hits=[i+1 for i,t in enumerate([tp1,tp2,tp3]) if t is not None and p<=float(t)]
 if hits:
  h=max(hits); c.execute("update recommendation_results set status='WIN',hit_target=?,updated=?,result_price=?,result_at=? where id=?",(h,time.time(),p,time.time(),rid)); return "WIN"
 if time.time()-float(created or 0)>=RETENTION:
  c.execute("update recommendation_results set status='EXPIRED',updated=?,result_price=?,result_at=? where id=?",(time.time(),p,time.time(),rid)); return "EXPIRED"
 return "OPEN"
_RESULTS_REFRESHING=False
_RESULTS_REFRESH_LOCK=threading.Lock()

@router.get("/api/results")
def results():
 # Respond quickly from SQLite; never make the browser wait for market scans
 # and dozens of live quotes. Refresh runs once in the background.
 global _RESULTS_REFRESHING
 with _RESULTS_REFRESH_LOCK:
  if not _RESULTS_REFRESHING:
   _RESULTS_REFRESHING=True
   threading.Thread(target=_refresh_worker,daemon=True,name="results-refresh").start()
 return _snapshot()

def _refresh_worker():
 global _RESULTS_REFRESHING
 try:
  import app as core
  with RESULTS_LOCK:
   _results_locked(core)
 except Exception as exc:
  print("[RESULTS] background refresh failed:",str(exc)[:200],flush=True)
 finally:
  with _RESULTS_REFRESH_LOCK:
   _RESULTS_REFRESHING=False

def _snapshot():
 c=db(); now=time.time(); cutoff=now-RETENTION
 c.execute("delete from recommendation_results where created<?",(cutoff,))
 rows=c.execute("select id,market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,result_price,result_at,timeframe,strategy_key,method_votes,base_score from recommendation_results where created>=? order by created desc",(cutoff,)).fetchall()
 c.commit(); c.close()
 out=[]
 for row in rows:
  out.append({"id":row[0],"market":row[1],"symbol":row[2],"direction":row[3],"entry":row[4],
   "tp1":row[5],"tp2":row[6],"tp3":row[7],"sl":row[8],"created":row[9],
   "status":row[11],"hit_target":row[12],"result_price":row[13],"result_at":row[14], "timeframe":row[15] or "15m","strategy_key":row[16] or "technical-confluence","method_votes":row[17] or "{}","base_score":row[18] or 0})
 wins=sum(x["status"]=="WIN" for x in out); losses=sum(x["status"]=="LOSS" for x in out)
 expired=sum(x["status"]=="EXPIRED" for x in out); opened=sum(x["status"]=="OPEN" for x in out)
 closed=wins+losses
 stats={"total":len(out),"wins":wins,"losses":losses,"expired":expired,"open":opened,
  "win_rate":round(wins/closed*100,1) if closed else 0}
 by={}
 for m in MARKETS:
  a=[x for x in out if x["market"]==m]; w=sum(x["status"]=="WIN" for x in a); l=sum(x["status"]=="LOSS" for x in a)
  by[m]={"total":len(a),"wins":w,"losses":l,"open":sum(x["status"]=="OPEN" for x in a),
   "win_rate":round(w/(w+l)*100,1) if w+l else 0}
 return {"ok":True,"stats":stats,"by_market":by,"results":out[:200],"updated":now,"refreshing":_RESULTS_REFRESHING}

def _results_locked(core):
 c=db(); now=time.time(); cutoff=now-RETENTION; c.execute("delete from recommendation_results where created<?",(cutoff,))
 # Public results must come only from published external recommendations.
 # Remove legacy internally-generated technical signals so they cannot inflate stats.
 c.execute("delete from recommendation_results where strategy_key IS NULL OR strategy_key!='public-trade'")
 # Clean previously cached crypto rows whose symbols are not real contracts on the matching exchange.
 allowed_symbols={}
 for mk in ("spot","futures"):
  try:
   tickers=core._binance24(mk=="futures")
   allowed_symbols[mk]={str(t.get("symbol") or "").upper() for t in tickers if str(t.get("symbol") or "").upper().endswith("USDT")}
  except Exception:
   allowed_symbols[mk]=set()
  if allowed_symbols[mk]:
   existing=c.execute("select id,symbol from recommendation_results where market=? and created>=? and strategy_key='public-trade'",(mk,cutoff)).fetchall()
   bad_ids=[int(rid) for rid,symbol in existing if str(symbol or "").upper() not in allowed_symbols[mk]]
   if bad_ids:
    c.executemany("delete from recommendation_results where id=?",[(rid,) for rid in bad_ids])
 # Track the exact public trade cards too, not only the internal technical scanner.
 try:
  import public_trades as public
  with public._lock:
   public_rows=sorted(public._cache.get("trades",[]),key=lambda x:float(x.get("created_at") or 0),reverse=True)[:700]
 except Exception:
  public_rows=[]
 reset_row=c.execute("select value from app_migrations where key='results_reset_20261012'").fetchone()
 reset_at=float(reset_row[0]) if reset_row else 0
 for x in public_rows:
  market=str(x.get("market") or "").lower()
  if market=="gold": market="forex"
  if market not in MARKETS: continue
  symbol=str(x.get("symbol") or "").strip().upper()
  if market in ("spot","futures") and allowed_symbols.get(market) and symbol not in allowed_symbols[market]: continue
  direction=str(x.get("direction") or "").strip().upper()
  entry=_num(x.get("entry")); created=_num(x.get("created_at")) or now
  if created>100000000000: created/=1000.0
  if created>now+300 or now-created>RETENTION or created<reset_at: continue
  if not symbol or direction not in ("BUY","SELL") or entry is None or entry<=0: continue
  tp1,tp2,tp3,sl=(_num(x.get(k)) for k in ("tp1","tp2","tp3","sl"))
  if not tp1 or not tp2 or not tp3 or not sl: continue
  timeframe=str(x.get("timeframe") or "15m")
  tolerance=max(abs(entry)*0.0025,1e-8)
  # Never keep two simultaneously-open recommendations for the same asset and market,
  # especially opposite directions; let the current one resolve first.
  active=c.execute("select id from recommendation_results where market=? and symbol=? and created>=? and status='OPEN' and strategy_key='public-trade' limit 1",(market,symbol,cutoff)).fetchone()
  duplicate=c.execute("select id from recommendation_results where market=? and symbol=? and direction=? and created>=? and entry between ? and ? and strategy_key='public-trade' limit 1",(market,symbol,direction,cutoff,entry-tolerance,entry+tolerance)).fetchone()
  if active or duplicate: continue
  votes={"origin":"public-trade","estimated":bool(x.get("is_estimated")),"source_count":int(x.get("source_count") or 0),"source_url":str(x.get("source_url") or "")}
  c.execute("insert into recommendation_results(market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,timeframe,strategy_key,method_votes,base_score) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(market,symbol,direction,entry,tp1,tp2,tp3,sl,created,now,timeframe,"public-trade",__import__("json").dumps(votes,separators=(",",":")),_num(x.get("ai_pct") or x.get("source_quality")) or 0))
 c.commit()
 rows=c.execute("select id,market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,result_price,result_at,timeframe,strategy_key,method_votes,base_score from recommendation_results where created>=? order by created desc",(cutoff,)).fetchall()
 # Fetch one quote per unique market/symbol concurrently; serial network calls made this
 # endpoint wait several minutes when the result history contained many open trades.
 from concurrent.futures import ThreadPoolExecutor
 def _quote(key):
  market,symbol=key; raw=str(symbol or "").replace("/USDT","USDT").replace("/","")
  try:
   if market=="spot":
    q=core._binance_json("https://api.binance.com/api/v3/ticker/price?symbol="+raw,timeout=3,timeframe="15m",spot_fallback=True)
    return float(q.get("price") or 0)
   if market=="futures":
    q=core._binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/price?symbol="+raw,timeout=3)
    return float(q.get("price") or 0)
   import research_engine as engine
   candles=engine._yahoo(symbol,market,"15m",4)
   return float(candles[-1].get("close") or 0) if candles else 0
  except Exception:
   return 0
 keys=list(dict.fromkeys((row[1],row[2]) for row in rows if row[11]=="OPEN"))
 quotes={}
 if keys:
  with ThreadPoolExecutor(max_workers=min(12,len(keys))) as pool:
   for key,px in zip(keys,pool.map(_quote,keys)):
    quotes[key]=px
 out=[]
 for row in rows:
  key=(row[1],row[2]); px=quotes.get(key,0) if row[11]=="OPEN" else row[13]
  out.append({"id":row[0],"market":row[1],"symbol":row[2],"direction":row[3],"entry":row[4],"tp1":row[5],"tp2":row[6],"tp3":row[7],"sl":row[8],"created":row[9],"status":_eval(c,row,px),"hit_target":row[12],"result_price":row[13],"result_at":row[14]})
 c.commit(); c.close()
 wins=sum(x["status"]=="WIN" for x in out); losses=sum(x["status"]=="LOSS" for x in out); expired=sum(x["status"]=="EXPIRED" for x in out); opened=sum(x["status"]=="OPEN" for x in out); closed=wins+losses
 stats={"total":len(out),"wins":wins,"losses":losses,"expired":expired,"open":opened,"win_rate":round(wins/closed*100,1) if closed else 0}
 by={}
 for m in MARKETS:
  a=[x for x in out if x["market"]==m]; w=sum(x["status"]=="WIN" for x in a); l=sum(x["status"]=="LOSS" for x in a); by[m]={"total":len(a),"wins":w,"losses":l,"open":sum(x["status"]=="OPEN" for x in a),"win_rate":round(w/(w+l)*100,1) if w+l else 0}
 return {"ok":True,"stats":stats,"by_market":by,"results":out[:200],"updated":now}

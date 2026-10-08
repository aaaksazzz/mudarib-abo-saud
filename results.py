import time,sqlite3,threading
from fastapi import APIRouter
router=APIRouter()
DB="/data/trading.db" if __import__("os").path.isdir("/data") else "trading.db"
RETENTION=21600  # results shown for 6 hours only
MARKETS=["spot","futures","contracts","us","saudi","forex"]
# Serialize result collection inside the single Uvicorn process. The endpoint both reads and writes
# the same SQLite file, so overlapping refreshes can otherwise contend on the writer lock.
RESULTS_LOCK=threading.RLock()
def db():
 c=sqlite3.connect(DB,timeout=60,check_same_thread=False)
 c.execute("pragma busy_timeout=60000")
 try: c.execute("pragma journal_mode=WAL")
 except sqlite3.OperationalError: pass
 c.execute("pragma synchronous=NORMAL")
 c.execute("""create table if not exists recommendation_results(id integer primary key,market text,symbol text,direction text,entry real,tp1 real,tp2 real,tp3 real,sl real,created real,updated real,status text default 'OPEN',hit_target integer default 0,result_price real,result_at real)"""); c.commit(); return c
def _num(v):
 try:return float(v)
 except:return None
def _eval(c,row,p):
 rid,market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,result_price,result_at=row
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
@router.get("/api/results")
def results():
 import app as core
 with RESULTS_LOCK:
  return _results_locked(core)

def _results_locked(core):
 c=db(); now=time.time(); cutoff=now-RETENTION; c.execute("delete from recommendation_results where created<?",(cutoff,))
 for market in MARKETS:
  try: rows=core.opportunities(market)
  except Exception: rows=[]
  for x in rows or []:
   created=float(x.get("detected_at") or now); sig=(market,str(x.get("symbol") or ""),str(x.get("direction") or ""),str(x.get("entry") or ""))
   if c.execute("select id from recommendation_results where market=? and symbol=? and direction=? and entry=? and created>=?",(*sig,cutoff)).fetchone(): continue
   c.execute("insert into recommendation_results(market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated) values(?,?,?,?,?,?,?,?,?,?)",(market,x.get("symbol"),x.get("direction"),_num(x.get("entry")),_num(x.get("tp1")),_num(x.get("tp2")),_num(x.get("tp3")),_num(x.get("sl")),created,now))
 c.commit()
 rows=c.execute("select id,market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,result_price,result_at from recommendation_results where created>=? order by created desc",(cutoff,)).fetchall()
 out=[]
 for row in rows:
  market,symbol=row[1],row[2]; raw=symbol.replace("/USDT","USDT")
  try:
   if market=="spot":
    q=core._binance_json("https://api.binance.com/api/v3/ticker/price?symbol="+raw,timeout=5,timeframe="15m",spot_fallback=True)
    px=float(q.get("price") or 0)
   elif market=="futures":
    q=core._binance_futures_json("https://fapi.binance.com/fapi/v1/ticker/price?symbol="+raw,timeout=5)
    px=float(q.get("price") or 0)
   else:
    candles=core._yahoo_chart(symbol,"15m","60d","15m")
    px=float(candles[-1][0]) if candles else 0
  except Exception: px=0
  out.append({"id":row[0],"market":market,"symbol":symbol,"direction":row[3],"entry":row[4],"tp1":row[5],"tp2":row[6],"tp3":row[7],"sl":row[8],"created":row[9],"status":_eval(c,row,px),"hit_target":row[12],"result_price":row[13],"result_at":row[14]})
 c.commit(); c.close()
 wins=sum(x["status"]=="WIN" for x in out); losses=sum(x["status"]=="LOSS" for x in out); expired=sum(x["status"]=="EXPIRED" for x in out); opened=sum(x["status"]=="OPEN" for x in out); closed=wins+losses
 stats={"total":len(out),"wins":wins,"losses":losses,"expired":expired,"open":opened,"win_rate":round(wins/closed*100,1) if closed else 0}
 by={}
 for m in MARKETS:
  a=[x for x in out if x["market"]==m]; w=sum(x["status"]=="WIN" for x in a); l=sum(x["status"]=="LOSS" for x in a); by[m]={"total":len(a),"wins":w,"losses":l,"open":sum(x["status"]=="OPEN" for x in a),"win_rate":round(w/(w+l)*100,1) if w+l else 0}
 return {"ok":True,"stats":stats,"by_market":by,"results":out[:200],"updated":now}

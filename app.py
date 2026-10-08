  profit=(price-entry)/entry*100
  hit.update(live_hit); hit_sl=hit_sl or live_sl
  hit_sorted=sorted(hit)
  target_pcts=[round(((entry-x)/entry*100 if direction=="SELL" else (x-entry)/entry*100),2) for x in levels]
  row["live_price"]=round(price,10)
  row["profit_pct"]=round(profit,2)
  row["target_profit_pcts"]=target_pcts
  row["sl_pct"]=round((sl-entry)/entry*100,2)
  row["hit_targets"]=hit_sorted
  row["highest_target_hit"]=max(hit_sorted) if hit_sorted else 0
  row["outcome"]="SL" if hit_sl else ("TP"+str(max(hit_sorted)) if hit_sorted else "OPEN")
  row["outcome_live"]=True
  row["price_checked_before_display"]=True
  row["ended"]=bool(hit_sl or (levels and len(levels) in hit))
  return row
 except Exception:
  return row

def _outcome_key(row):
 return "|".join([
  str(row.get("market") or ""),str(row.get("symbol") or ""),
  str(row.get("direction") or ""),str(row.get("entry") or ""),
  str(row.get("sl") or ""), "|".join(str(x) for x in (
   row.get("targets") or [row.get("tp1"),row.get("tp2"),row.get("tp3"),
   row.get("tp4"),row.get("tp5"),row.get("tp6")]
  ) if x not in (None,""))
 ])

def _checked_trade(row):
 key=_outcome_key(row); now=time.time()
 with lock:
  cached=OUTCOME_CACHE.get(key)
  if cached and now-cached[0]<OUTCOME_CACHE_TTL:
   return dict(cached[1])
 checked=_trade_outcome(dict(row))
 with lock:
  OUTCOME_CACHE[key]=(now,dict(checked))
 return checked

def _check_trade_batch(rows,limit=20):
 items=list(rows[:limit])
 if not items: return []
 # Live price/history checks are independent; run them concurrently so one
 # slow market-data request cannot block the whole page for tens of seconds.
 workers=min(6,len(items))
 with ThreadPoolExecutor(max_workers=workers) as ex:
  futures=[ex.submit(_checked_trade,row) for row in items]
  return [f.result() for f in futures]

def _active_trade_rows(rows):
 active=[]
 for checked in _check_trade_batch(rows,20):
  if not checked.get("ended"):
   active.append(checked)
 return active

def _live_price_for_recommendation(row):
 # Price tracking only: never filters, changes, or rejects the published setup.
 try:
  market=str(row.get("market") or "").lower()
  sym=str(row.get("symbol") or "").strip().upper()
  if market in ("spot","futures"):
   raw=sym.replace("/USDT","").replace("/","")
   if not raw.endswith("USDT"): return None
   host="https://fapi.binance.com/fapi/v1/ticker/price" if market=="futures" else "https://api.binance.com/api/v3/ticker/price"
   r=requests.get(host,params={"symbol":raw},timeout=2,headers={"User-Agent":"SMART-TRADING-PRO/1.0"})
   if r.ok: return float((r.json() or {}).get("price"))
  elif market=="us":
   r=requests.get("https://query1.finance.yahoo.com/v8/finance/chart/"+sym,params={"range":"1d","interval":"1m"},timeout=3,headers={"User-Agent":"Mozilla/5.0"})
   if r.ok:
    j=r.json().get("chart",{}).get("result") or []
    if j:
     meta=j[0].get("meta") or {}
     return float(meta.get("regularMarketPrice") or meta.get("previousClose"))
  else:
   ys=sym
   if market=="saudi" and not ys.endswith(".SR"): ys=ys+".SR"
   if market=="contracts" and not ys.endswith("=F"): ys=ys+"=F"
   if market=="forex" and not ys.endswith("=X"): ys=ys+"=X"
   r=requests.get("https://query1.finance.yahoo.com/v8/finance/chart/"+ys,params={"range":"1d","interval":"5m"},timeout=3,headers={"User-Agent":"Mozilla/5.0"})
   if r.ok:
    j=r.json().get("chart",{}).get("result") or []
    if j:
     meta=j[0].get("meta") or {}
     return float(meta.get("regularMarketPrice") or meta.get("previousClose"))
 except Exception:
  pass
 return None

def _decorate_trade_outcomes(rows):
 # Track the live market price only. Published Entry/TP/SL stay untouched.
 out=[]
 for row in rows or []:
  x=dict(row)
  price=_live_price_for_recommendation(x)
  x["current_price"]=price
  x["price_tracking"]=True
  x["price_status"]="غير متاح"
  try:
   entry=float(x.get("entry")); sl=float(x.get("sl"))
   tps=[float(v) for v in (x.get("targets") or [x.get("tp1"),x.get("tp2"),x.get("tp3")]) if v not in (None,"")]
   direction=str(x.get("direction") or "").upper()
   if price is not None:
    if direction in ("BUY","LONG"):
     if price<=sl: status="ضرب SL"
     elif tps and price>=tps[-1]: status="وصل آخر هدف"
     elif tps and price>=tps[0]: status="وصل TP1"
     elif price>=entry: status="فوق Entry"
     else: status="تحت Entry"
    else:
     if price>=sl: status="ضرب SL"
     elif tps and price<=tps[-1]: status="وصل آخر هدف"
     elif tps and price<=tps[0]: status="وصل TP1"
     elif price<=entry: status="تحت Entry"
     else: status="فوق Entry"
    x["price_status"]=status
    x["distance_from_entry_pct"]=round((price/entry-1)*100,2) if entry else None
  except Exception:
   pass
  if not x.get("ended"):
   out.append(x)
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
  c.execute("create table if not exists signal_archive(id integer primary key, market text, symbol text, direction text, entry real, tp1 real, tp2 real, tp3 real, sl real, source text, detected real, payload text, unique_key text unique)")
  now=time.time()
  for row in rows or []:
   key="|".join(str(row.get(k) or "") for k in ("market","symbol","direction","entry","tp1","tp2","tp3","sl","source"))
   try:
    c.execute("insert or ignore into signal_archive(market,symbol,direction,entry,tp1,tp2,tp3,sl,source,detected,payload,unique_key) values(?,?,?,?,?,?,?,?,?,?,?,?)",
      (market,row.get("symbol"),row.get("direction"),row.get("entry"),row.get("tp1"),row.get("tp2"),row.get("tp3"),row.get("sl"),row.get("source") or "",now,json.dumps(row,ensure_ascii=False),key))
   except Exception:
    pass
  c.execute("insert into market_cache(market,rows,stats,updated) values(?,?,?,?) on conflict(market) do update set rows=excluded.rows,stats=excluded.stats,updated=excluded.updated",
            (market,json.dumps(rows,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),now))
  c.execute("delete from market_cache where updated<?",(now-OPPORTUNITY_RETENTION,))
  c.execute("delete from signal_archive where detected<?",(now-OPPORTUNITY_RETENTION,))
  c.commit(); c.close()
 except Exception:
  pass

@app.get("/api/radar")
def radar_api():
 # Radar is a read-only aggregate view. Never start six market scanners from
 # one browser request: the 512MB service must keep scanning serialized.
 out=[]
 for market in MARKETS:
  try:
   rows,_stats=_instant_market_rows(market)
   out.extend(rows)
  except Exception:
   pass
 out.sort(key=lambda x:(float(x.get("recommendation_score") or 0),float(x.get("external_agreement") or 0),float(x.get("source_performance") or 0)),reverse=True)
 return {"opportunities":out[:20],"markets":MARKETS,"external_first":True,"generated_at":time.time()}

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
  rows=_decorate_trade_outcomes(rows)
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

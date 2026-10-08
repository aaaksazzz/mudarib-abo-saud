import threading,time,sys

def _install():
 try:
  app=sys.modules.get("app")
  if app is None: return False
  if not getattr(app,"_ADMIN_ACCESS_PATCHED",False):
   import admin_access
   if admin_access.install(): app._ADMIN_ACCESS_PATCHED=True
  if getattr(app,"_WEB_RESEARCH_PATCHED",False):
   return bool(getattr(app,"_ADMIN_ACCESS_PATCHED",False))
  import research_engine

  original_scan=getattr(app,"_scan_opportunities",None)
  if original_scan:
   def scan_with_research(market,*args,**kwargs):
    result=original_scan(market,*args,**kwargs)
    try:
     fresh=research_engine.decide(research_engine.discover(market))
     if fresh:
      with app.lock:
       cached=app.OPPORTUNITY_CACHE.get(market,{})
       base=list(cached.get("rows",[]))
       # Keep existing rows, then add research decisions without duplicates.
       seen={(str(x.get("market")),str(x.get("symbol")),str(x.get("direction")),str(x.get("entry")),str(x.get("sl"))) for x in base}
       for x in fresh:
        k=(str(x.get("market")),str(x.get("symbol")),str(x.get("direction")),str(x.get("entry")),str(x.get("sl")))
        if k not in seen:
         base.append(x); seen.add(k)
       base.sort(key=lambda x:(float(x.get("recommendation_score") or 0),float(x.get("research_agreement") or 0)),reverse=True)
       stats=dict(cached.get("stats") or {})
       stats["research_mode"]=True
       stats["research_candidates"]=len(fresh)
       stats["decision_engine"]="web research + source consensus"
       app.OPPORTUNITY_CACHE[market]={"at":time.time(),"rows":base[:100],"stats":stats}
       try: app._save_opportunity_store(market,base[:100],stats)
       except Exception: pass
    except Exception:
     pass
    return result
   app._scan_opportunities=scan_with_research

  original_instant=getattr(app,"_instant_market_rows",None)
  if original_instant:
   def instant_with_research(market,*args,**kwargs):
    rows,stats=original_instant(market,*args,**kwargs)
    try:
     extra=research_engine.decide(research_engine.discover(market))
     if extra:
      seen={(str(x.get("symbol")),str(x.get("direction")),str(x.get("entry")),str(x.get("sl"))) for x in rows}
      for x in extra:
       k=(str(x.get("symbol")),str(x.get("direction")),str(x.get("entry")),str(x.get("sl")))
       if k not in seen: rows.append(x); seen.add(k)
      rows.sort(key=lambda x:(float(x.get("recommendation_score") or 0),float(x.get("external_agreement") or 0)),reverse=True)
    except Exception: pass
    return rows,stats
   app._instant_market_rows=instant_with_research

  app._WEB_RESEARCH_PATCHED=True
  return True
 except Exception:
  return False

def _wait():
 for _ in range(120):
  if _install(): return
  time.sleep(.25)

threading.Thread(target=_wait,daemon=True).start()

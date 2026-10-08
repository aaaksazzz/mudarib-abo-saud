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
  import news_engine\n  news_engine.install(app)\n  import research_engine

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

  # Restore the market APIs expected by the current frontend. Older deployments
  # exposed /api/opportunities and /api/radar; the current app kept the scanners
  # but lost those compatibility routes, causing the UI to show a generic fetch error.
  if not getattr(app,"_MARKET_API_ALIASES_PATCHED",False):
   def _market_rows(market,timeframe):
    if market not in getattr(app,"MARKETS",{}): return [],False
    if timeframe not in getattr(app,"TIMEFRAMES",[]): timeframe="15m"
    if market=="spot":
     return app._cached_scan("spot",timeframe,lambda:app._scan_spot_strategy(timeframe,20))
    if market=="futures":
     return app._cached_scan("futures",timeframe,lambda:app._scan_binance_futures(timeframe))
    return app._cached_scan(market,timeframe,lambda:app._scan_yahoo_market(market,timeframe))
   def _public_row(x,market):
    d=dict(x)
    side=str(d.get("side") or d.get("direction") or "").upper()
    d["direction"]="SELL" if side=="SELL" else "BUY" if side=="BUY" else side
    d["market"]=market
    d["source_count"]=int(d.get("source_count") or d.get("research_sources") or 0)
    d["recommendation_score"]=float(d.get("recommendation_score") or d.get("ai_pct") or d.get("score") or 0)
    d["targets"]=[d[k] for k in ("tp1","tp2","tp3") if d.get(k) not in (None,"")]
    d["detected_at"]=d.get("detected_at") or time.time()
    return d
   def opportunities(request,market="spot",timeframe="15m"):
    try:
     rows,scanning=_market_rows(market,timeframe)
     out=[_public_row(x,market) for x in (rows or [])]
     out.sort(key=lambda x:float(x.get("recommendation_score") or 0),reverse=True)
     return {"ok":True,"market":market,"timeframe":timeframe,"opportunities":out[:50],
             "scan_stats":{"analyzed":len(out),"valid_15m":sum(1 for x in out if str(x.get("timeframe"))=="15m"),
                           "updated_at":time.time(),"scanning":bool(scanning)}}
    except Exception as exc:
     return JSONResponse({"ok":False,"message":"تعذر جلب بيانات هذا السوق حالياً","detail":str(exc)[:160]},status_code=502)
   def radar(request):
    try:
     all_rows=[]
     for market in ("saudi","spot","futures","us","contracts","forex"):
      try:
       rows,_=_market_rows(market,"15m")
       all_rows.extend(_public_row(x,market) for x in (rows or []))
      except Exception:
       continue
     all_rows.sort(key=lambda x:float(x.get("recommendation_score") or 0),reverse=True)
     return {"ok":True,"opportunities":all_rows[:100],"updated_at":time.time()}
    except Exception:
     return JSONResponse({"ok":False,"message":"تعذر تحديث الرادار حالياً"},status_code=502)
   app.add_api_route("/api/opportunities",opportunities,methods=["GET"])
   app.add_api_route("/api/radar",radar,methods=["GET"])
   app._MARKET_API_ALIASES_PATCHED=True

  app._WEB_RESEARCH_PATCHED=True
  return True
 except Exception:
  return False

def _wait():
 for _ in range(120):
  if _install(): return
  time.sleep(.25)

threading.Thread(target=_wait,daemon=True).start()

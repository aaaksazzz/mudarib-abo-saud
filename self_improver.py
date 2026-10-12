"""Hourly, bounded self-improvement loop for SMART TRADING PRO.
Tunes ranking/method weights from closed recommendation outcomes. Never edits code
or places live orders. State and audit data share the results database.
"""
import json, os, sqlite3, threading, time

DB="/data/trading.db" if os.path.isdir("/data") else "trading.db"
RETENTION=86400
MIN_SAMPLE=8
_lock=threading.Lock()
_started=False
_status={"ok":True,"enabled":True,"state":"starting","last_run":None,"next_run":None,
         "markets_checked":0,"methods_evaluated":0,"weights_updated":0,"closed_samples":0,
         "message":"بانتظار أول دورة تحسين"}

def _db():
    c=sqlite3.connect(DB,timeout=8)
    c.row_factory=sqlite3.Row
    c.execute("pragma busy_timeout=8000")
    c.execute("""create table if not exists recommendation_results(
      id integer primary key,market text,symbol text,direction text,entry real,tp1 real,tp2 real,tp3 real,sl real,
      created real,updated real,status text default 'OPEN',hit_target integer default 0,result_price real,result_at real,
      timeframe text default '15m',strategy_key text default 'technical-confluence',method_votes text default '{}',base_score real default 0)""")
    for col,ddl in (
      ("timeframe","alter table recommendation_results add column timeframe text default '15m'"),
      ("strategy_key","alter table recommendation_results add column strategy_key text default 'technical-confluence'"),
      ("method_votes","alter table recommendation_results add column method_votes text default '{}'"),
      ("base_score","alter table recommendation_results add column base_score real default 0"),
    ):
        try: c.execute("select "+col+" from recommendation_results limit 1")
        except Exception:
            try: c.execute(ddl)
            except Exception: pass
    c.execute("""create table if not exists self_improver_weights(
        market text not null,timeframe text not null,method text not null,
        weight real not null default 1.0,sample integer not null default 0,
        mean_net_r real not null default 0,win_rate real not null default 0,
        updated real not null,primary key(market,timeframe,method))""")
    c.execute("""create table if not exists self_improver_runs(
        id integer primary key,started real,finished real,state text,
        markets_checked integer,methods_evaluated integer,weights_updated integer,
        closed_samples integer,summary text)""")
    c.commit()
    return c

def status():
    with _lock:
        result=dict(_status)
    try:
        c=_db()
        row=c.execute("select started,finished,state,markets_checked,methods_evaluated,weights_updated,closed_samples,summary from self_improver_runs order by id desc limit 1").fetchone()
        if row:
            result.update({"last_run":row["finished"],"state":row["state"],
              "markets_checked":row["markets_checked"],"methods_evaluated":row["methods_evaluated"],
              "weights_updated":row["weights_updated"],"closed_samples":row["closed_samples"]})
            try: result["summary"]=json.loads(row["summary"] or "{}")
            except Exception: result["summary"]={}
        c.close()
    except Exception as exc:
        result["database_error"]=str(exc)[:120]
    return result

def record_signals(market, timeframe, rows):
    """Persist the site's visible market signals as independent learning samples."""
    if not rows:
        return 0
    c=_db()
    saved=0
    now=time.time()
    try:
        for row in rows[:20]:
            try:
                symbol=str(row.get("symbol") or "").strip().upper()
                side=str(row.get("direction") or row.get("side") or "").upper()
                entry=float(row.get("entry") or 0)
                sl=float(row.get("sl") or 0)
                targets=[float(row.get(k) or 0) for k in ("tp1","tp2","tp3")]
                tf=str(row.get("timeframe") or timeframe or "15m")
                if not symbol or side not in ("BUY","SELL") or entry<=0 or sl<=0 or entry==sl or not all(x>0 for x in targets):
                    continue
                if side=="BUY" and not (sl<entry<targets[0]<targets[1]<targets[2]): continue
                if side=="SELL" and not (targets[2]<targets[1]<targets[0]<entry<sl): continue
                votes=row.get("methods") or row.get("method_votes") or {}
                if not isinstance(votes,dict) or not votes:
                    label=str(row.get("strategy_mode") or row.get("strategy_label") or row.get("tag") or "market-signal")
                    votes={label:1 if side=="BUY" else -1}
                candle=str(row.get("candle_start") or row.get("candleStart") or "")
                strategy=str(row.get("strategy_mode") or row.get("strategy_label") or row.get("tag") or "market-signal")
                # Stable key prevents the same visible signal being counted repeatedly on page refresh.
                minutes={"1m":1,"3m":3,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440,"1w":10080,"1M":43200}.get(tf,15)
                key_created=float(int(now//(minutes*60))*(minutes*60))
                if candle:
                    try:
                        from datetime import datetime
                        key_created=datetime.fromisoformat(candle.replace("Z","+00:00")).timestamp()
                    except Exception: pass
                exists=c.execute("""select id from recommendation_results
                    where market=? and symbol=? and direction=? and timeframe=? and created>=? limit 1""",
                    (str(market),symbol,side,tf,key_created)).fetchone()
                if exists: continue
                c.execute("""insert into recommendation_results
                    (market,symbol,direction,entry,tp1,tp2,tp3,sl,created,updated,status,hit_target,timeframe,strategy_key,method_votes,base_score)
                    values(?,?,?,?,?,?,?,?,?,?, 'OPEN',0,?,?,?,?)""",
                    (str(market),symbol,side,entry,*targets,sl,now,now,tf,strategy,
                     json.dumps(votes,ensure_ascii=False,separators=(",",":")),
                     float(row.get("recommendation_score") or row.get("ai_pct") or row.get("score") or 0)))
                saved+=1
            except Exception:
                continue
        c.commit()
        return saved
    finally:
        c.close()


def _market_price(market, symbol):
    """Read-only current quote for outcome tracking; never places an order."""
    try:
        if market in ("spot","alpha"):
            import urllib.parse
            q=urllib.parse.urlencode({"symbol":symbol.replace("/","")})
            from urllib.request import Request, urlopen
            with urlopen(Request("https://api.binance.com/api/v3/ticker/price?"+q,headers={"User-Agent":"mudarib-pro-learning/1.0"}),timeout=4) as resp:
                return float(json.loads(resp.read().decode()).get("price") or 0)
        if market=="futures":
            import urllib.parse
            from urllib.request import Request, urlopen
            q=urllib.parse.urlencode({"symbol":symbol.replace("/","")})
            with urlopen(Request("https://fapi.binance.com/fapi/v1/ticker/price?"+q,headers={"User-Agent":"mudarib-pro-learning/1.0"}),timeout=4) as resp:
                return float(json.loads(resp.read().decode()).get("price") or 0)
        import app as core
        candles=core._yahoo_chart(symbol,"15m","5d","15m")
        return float(candles[-1][0]) if candles else 0.0
    except Exception:
        return 0.0


def refresh_open_outcomes(limit=24):
    """Close tracked paper recommendations from observed market prices, with stop checked first."""
    c=_db()
    closed=0
    try:
        cutoff=time.time()-RETENTION
        rows=c.execute("""select id,market,symbol,direction,entry,sl,tp1,tp2,tp3,created
            from recommendation_results where status='OPEN' and created>=? order by created asc limit ?""",
            (cutoff,max(1,min(int(limit),40)))).fetchall()
        for row in rows:
            price=_market_price(str(row["market"]),str(row["symbol"]))
            if price<=0: continue
            side=str(row["direction"]).upper()
            entry=float(row["entry"]); stop=float(row["sl"])
            status="OPEN"; hit=0; result_price=None
            if (side=="BUY" and price<=stop) or (side=="SELL" and price>=stop):
                status="LOSS"; result_price=stop
            else:
                targets=[row["tp1"],row["tp2"],row["tp3"]]
                hit_indices=[i+1 for i,t in enumerate(targets) if t is not None and
                    ((side=="BUY" and price>=float(t)) or (side=="SELL" and price<=float(t)))]
                if hit_indices:
                    hit=max(hit_indices); status="WIN"; result_price=float(targets[hit-1])
                elif time.time()-float(row["created"])>=RETENTION:
                    status="EXPIRED"; result_price=price
            if status!="OPEN":
                c.execute("update recommendation_results set status=?,hit_target=?,result_price=?,result_at=?,updated=? where id=? and status='OPEN'",
                          (status,hit,result_price,time.time(),time.time(),row["id"]))
                closed+=1
        c.commit()
        return closed
    finally:
        c.close()


def run_once():
    started=time.time()
    try:
        refresh_open_outcomes(24)
    except Exception as exc:
        print("[SELF-IMPROVER] outcome refresh skipped:",str(exc)[:120],flush=True)
    cutoff=started-RETENTION
    stats={}
    checked=set()
    c=_db()
    try:
        cols={r["name"] for r in c.execute("pragma table_info(recommendation_results)")}
        needed={"market","timeframe","direction","entry","sl","tp1","tp2","tp3","status","hit_target","method_votes","created"}
        if not needed.issubset(cols):
            raise RuntimeError("نتائج الصفقات لا تحتوي كل حقول التعلم المطلوبة")
        rows=c.execute("""select market,timeframe,direction,entry,sl,tp1,tp2,tp3,status,hit_target,method_votes
          from recommendation_results where created>=? and status in ('WIN','LOSS')""",(cutoff,)).fetchall()
        # AZO keeps its independently tracked outcomes in the same trading.db.
        # Feed those real closed results into the same market/timeframe learner;
        # otherwise the hourly learner can run forever while its input table stays empty.
        azo_rows=[]
        try:
            azo_rows=c.execute("""select market,timeframe,direction,entry,sl,tp1,tp2,tp3,status,hit_target,method_votes,result_r
              from azo_signals where created>=? and status in ('WIN','LOSS')""",(cutoff,)).fetchall()
        except sqlite3.OperationalError:
            pass
        for row in rows:
            try:
                market=str(row["market"]); timeframe=str(row["timeframe"] or "15m")
                side=str(row["direction"] or "").upper()
                entry=float(row["entry"]); stop=float(row["sl"])
                risk=abs(entry-stop)
                if risk<=0: continue
                if row["status"]=="LOSS":
                    net_r=-1.0
                else:
                    hit=max(1,min(3,int(row["hit_target"] or 1)))
                    target=row[["tp1","tp2","tp3"][hit-1]]
                    if target is None: continue
                    gross_r=abs(float(target)-entry)/risk
                    friction=max(0.0,float(os.getenv("SELF_IMPROVER_ROUNDTRIP_COST_PCT","0.002")))
                    net_r=gross_r-(entry*friction/risk)
                votes=json.loads(row["method_votes"] or "{}")
                checked.add((market,timeframe))
                for method,vote in votes.items():
                    try: vote=float(vote)
                    except Exception: continue
                    if vote == 0 or side not in ("BUY","SELL"): continue
                    aligned=(side=="BUY" and vote>0) or (side=="SELL" and vote<0)
                    stats.setdefault((market,timeframe,str(method)),[]).append(net_r if aligned else -net_r)
            except Exception:
                continue
        for row in azo_rows:
            try:
                market=str(row["market"]); timeframe=str(row["timeframe"] or "15m")
                side=str(row["direction"] or "").upper()
                net_r=float(row["result_r"])
                votes=json.loads(row["method_votes"] or "{}")
                if side not in ("BUY","SELL") or not votes: continue
                checked.add((market,timeframe))
                for method,vote in votes.items():
                    try: vote=float(vote)
                    except Exception: continue
                    if vote == 0 or side not in ("BUY","SELL"): continue
                    aligned=(side=="BUY" and vote>0) or (side=="SELL" and vote<0)
                    stats.setdefault((market,timeframe,str(method)),[]).append(net_r if aligned else -net_r)
            except Exception:
                continue
        changed=0
        summary={}
        for (market,timeframe,method),values in stats.items():
            n=len(values)
            mean=sum(values)/n
            wins=sum(1 for v in values if v>0)
            rate=wins/n
            # No tuning below the minimum sample. Bounded direct estimate avoids compounding hourly.
            if n<MIN_SAMPLE:
                continue
            raw=1.0+(mean*0.10)
            weight=max(0.75,min(1.25,raw))
            c.execute("""insert into self_improver_weights(market,timeframe,method,weight,sample,mean_net_r,win_rate,updated)
                values(?,?,?,?,?,?,?,?) on conflict(market,timeframe,method) do update set
                weight=excluded.weight,sample=excluded.sample,mean_net_r=excluded.mean_net_r,
                win_rate=excluded.win_rate,updated=excluded.updated""",
                (market,timeframe,method,weight,n,mean,rate,started))
            changed+=1
            summary.setdefault(market,[]).append({"timeframe":timeframe,"method":method,
              "weight":round(weight,3),"sample":n,"mean_net_r":round(mean,3),"win_rate":round(rate*100,1)})
        finished=time.time()
        state="updated" if changed else "observing"
        message=("تم تحديث أوزان المناهج بناءً على نتائج مغلقة كافية" if changed
                 else "مراقبة فقط: لا توجد عينة كافية لتغيير الأوزان")
        payload={"markets_checked":len(checked),"methods_evaluated":len(stats),
                 "weights_updated":changed,"closed_samples":len(rows),"summary":summary}
        c.execute("insert into self_improver_runs(started,finished,state,markets_checked,methods_evaluated,weights_updated,closed_samples,summary) values(?,?,?,?,?,?,?,?)",
            (started,finished,state,payload["markets_checked"],payload["methods_evaluated"],changed,len(rows),json.dumps(summary,ensure_ascii=False)))
        # Keep a compact audit trail; weights remain bounded and recent outcome history is already 24h.
        c.execute("delete from self_improver_runs where finished<?",(finished-30*86400,))
        c.commit()
        with _lock:
            _status.update({"ok":True,"enabled":True,"state":state,"last_run":finished,
                "next_run":finished+3600,"markets_checked":payload["markets_checked"],
                "methods_evaluated":payload["methods_evaluated"],"weights_updated":changed,
                "closed_samples":len(rows),"message":message,"summary":summary})
        print("[SELF-IMPROVER]",message,"closed",len(rows),"weights",changed,flush=True)
        return {"ok":True,**payload,"state":state,"message":message}
    except Exception as exc:
        try:
            c.rollback()
            finished=time.time()
            c.execute("insert into self_improver_runs(started,finished,state,markets_checked,methods_evaluated,weights_updated,closed_samples,summary) values(?,?,?,?,?,?,?,?)",
                (started,finished,"error",0,0,0,0,json.dumps({"error":str(exc)[:180]},ensure_ascii=False)))
            c.commit()
        except Exception: pass
        with _lock:
            _status.update({"ok":False,"enabled":True,"state":"error","last_run":time.time(),
                "next_run":time.time()+3600,"message":str(exc)[:180]})
        print("[SELF-IMPROVER] failed:",str(exc)[:180],flush=True)
        return {"ok":False,"error":str(exc)[:180]}
    finally:
        c.close()

def _loop():
    # Outcome checks run in small batches; weight fitting remains hourly to protect the small instance.
    time.sleep(60)
    last_learning=0.0
    while True:
        try:
            if time.time()-last_learning>=3600:
                run_once()
                last_learning=time.time()
            else:
                refresh_open_outcomes(6)
        except Exception as exc:
            print("[SELF-IMPROVER] loop error:",str(exc)[:160],flush=True)
        time.sleep(120)

def start_worker():
    global _started
    with _lock:
        if _started: return
        _started=True
    threading.Thread(target=_loop,daemon=True,name="self-improver-hourly").start()
    print("[SELF-IMPROVER] hourly learning enabled; live orders remain manual",flush=True)

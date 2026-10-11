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

def run_once():
    started=time.time()
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
                    # Conservative round-trip friction assumption; configurable by deployment.
                    friction=max(0.0,float(os.getenv("SELF_IMPROVER_ROUNDTRIP_COST_PCT","0.002")))
                    net_r=gross_r-(entry*friction/risk)
                votes=json.loads(row["method_votes"] or "{}")
                checked.add((market,timeframe))
                for method,vote in votes.items():
                    try: vote=float(vote)
                    except Exception: continue
                    aligned=(side=="BUY" and vote>0) or (side=="SELL" and vote<0)
                    if not aligned: continue
                    key=(market,timeframe,str(method))
                    stats.setdefault(key,[]).append(net_r)
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
    # Wait until the web app is fully started; then run immediately and every hour.
    time.sleep(60)
    while True:
        try: run_once()
        except Exception as exc: print("[SELF-IMPROVER] loop error:",str(exc)[:160],flush=True)
        time.sleep(3600)

def start_worker():
    global _started
    with _lock:
        if _started: return
        _started=True
    threading.Thread(target=_loop,daemon=True,name="self-improver-hourly").start()
    print("[SELF-IMPROVER] hourly learning enabled; live orders remain manual",flush=True)

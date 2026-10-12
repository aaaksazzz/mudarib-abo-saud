"""Rolling 24-hour strategy feedback from closed recommendation outcomes.
This changes ranking only after a minimum sample; it never places orders.
"""
import json, os, sqlite3, time

DB="/data/trading.db" if os.path.isdir("/data") else "trading.db"
RETENTION=86400
MIN_SAMPLE=8

def _connect():
    c=sqlite3.connect(DB,timeout=3)
    c.execute("pragma busy_timeout=3000")
    return c

def apply_feedback(market,timeframe,rows):
    """Adjust scores using recent R-multiples of methods that aligned with each signal."""
    try:
        c=_connect()
        columns={r[1] for r in c.execute("pragma table_info(recommendation_results)")}
        required={"method_votes","timeframe","status","created","hit_target","entry","sl","tp1","tp2","tp3","direction","market"}
        if not required.issubset(columns):
            c.close()
            return rows
        cutoff=time.time()-RETENTION
        records=c.execute("""select market,timeframe,direction,entry,sl,tp1,tp2,tp3,status,hit_target,method_votes
          from recommendation_results where created>=? and status in ('WIN','LOSS')""",(cutoff,)).fetchall()
        c.close()
        stats={}
        for m,tf,side,entry,sl,tp1,tp2,tp3,status,hit,votes_json in records:
            try:
                entry=float(entry); sl=float(sl)
                risk=abs(entry-sl)
                if risk<=0: continue
                if status=="LOSS": r_value=-1.0
                else:
                    target=[tp1,tp2,tp3][max(1,min(3,int(hit or 1)))-1]
                    target=float(target)
                    r_value=abs(target-entry)/risk
                votes=json.loads(votes_json or "{}")
                side= str(side or "").upper()
                for method,vote in votes.items():
                    try: vote=float(vote)
                    except Exception: continue
                    if vote == 0 or side not in ("BUY","SELL"): continue
                    aligned=(side=="BUY" and vote>0) or (side=="SELL" and vote<0)
                    # Include opposing votes: a method is rewarded only when its own direction worked.
                    method_r = r_value if aligned else -r_value
                    key=(m,tf,str(method))
                    stats.setdefault(key,[]).append(method_r)
            except Exception:
                continue
        out=[]
        for original in rows or []:
            row=dict(original)
            base=float(row.get("recommendation_score") or row.get("ai_pct") or 0)
            votes=row.get("methods") or {}
            side=str(row.get("direction") or row.get("side") or "").upper()
            adjustments=[]
            for method,vote in votes.items():
                try: v=float(vote)
                except Exception: continue
                if v == 0 or side not in ("BUY","SELL"): continue
                aligned=(side=="BUY" and v>0) or (side=="SELL" and v<0)
                values=stats.get((market,timeframe,str(method)),[])
                if len(values)<MIN_SAMPLE: continue
                # A historically reliable method that disagrees with this signal lowers its score.
                mean=max(-1.5,min(3.0,sum(values)/len(values)))
                confidence=len(values)/(len(values)+20.0)
                adjustments.append((1.0 if aligned else -1.0)*mean*8.0*confidence)
            adjustment=(sum(adjustments)/len(adjustments)) if adjustments else 0.0
            row["base_score"]=round(base,2)
            row["learning_adjustment"]=round(adjustment,2)
            row["learning_sample"]=max((len(stats.get((market,timeframe,str(k)),[])) for k,v in votes.items()),default=0)
            row["recommendation_score"]=round(max(0,min(100,base+adjustment)),2)
            row["ai_pct"]=row["recommendation_score"]
            out.append(row)
        return out
    except Exception as exc:
        print("[STRATEGY-LEARNING] feedback unavailable:",str(exc)[:160],flush=True)
        return rows


def get_method_weights(market,timeframe):
    """Read safe, bounded hourly weights; fall back to neutral weights on any issue."""
    try:
        c=_connect()
        rows=c.execute("select method,weight from self_improver_weights where market=? and timeframe=?",(str(market),str(timeframe))).fetchall()
        c.close()
        return {str(k):max(0.75,min(1.25,float(v))) for k,v in rows}
    except Exception:
        return {}

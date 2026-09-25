from .db import connection

def _expiry_interval(interval):
    return {"5m":"5 minutes","15m":"15 minutes","30m":"30 minutes","1H":"1 hour","4H":"4 hours","1D":"1 day","1W":"7 days"}.get(interval,"15 minutes")

def register_signals(items):
    with connection() as conn:
        for x in items or []:
            if not x.get("tradeReady") or x.get("direction") not in ("شراء","بيع"):continue
            if conn.execute("SELECT id FROM signals WHERE market=%s AND interval=%s AND symbol=%s AND status='open' LIMIT 1",(x["market"],x["interval"],x["symbol"])).fetchone():continue
            conn.execute("""INSERT INTO signals(market,interval,symbol,direction,signal,entry,tp1,tp2,tp3,sl,confidence,rr,trade_ready,candle_expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW()+(%s::interval))""",
                (x["market"],x["interval"],x["symbol"],x["direction"],x.get("signal",""),x.get("entry",0),x.get("tp1",0),x.get("tp2",0),x.get("tp3",0),x.get("sl",0),x.get("confidence",0),x.get("rr",0),_expiry_interval(x["interval"])))

def list_trades():
    with connection() as conn:
        rows=conn.execute("""SELECT id,market,interval,symbol,direction,signal,entry,tp1,tp2,tp3,sl,confidence,rr,trade_ready AS "tradeReady",status,result,pnl_percent AS "pnlPercent",created_at AS "createdAt",resolved_at AS "resolvedAt" FROM signals ORDER BY created_at DESC LIMIT 1000""").fetchall()
    return [dict(x) for x in rows]

def stats():
    out={}
    with connection() as conn:
        for key,seconds in {"today":86400,"week":604800,"month":2592000,"year":31536000,"all":None}.items():
            where="status='closed'";args=[]
            if seconds:where+=" AND resolved_at >= NOW() - (%s * INTERVAL '1 second')";args=[seconds]
            r=conn.execute(f"SELECT COUNT(*) total,COUNT(*) FILTER (WHERE result IN ('tp1','tp2','tp3')) wins,COUNT(*) FILTER (WHERE result='sl') losses,COALESCE(SUM(pnl_percent),0) pnl FROM signals WHERE {where}",args).fetchone()
            total=int(r["total"] or 0);wins=int(r["wins"] or 0)
            out[key]={"total":total,"wins":wins,"losses":int(r["losses"] or 0),"pnl":round(float(r["pnl"] or 0),2),"winRate":round(wins/total*100,2) if total else 0}
    return out

from datetime import datetime,timezone
from .db import connection

def ema(values,period):
    if len(values)<period:return None
    k=2/(period+1);v=sum(values[:period])/period
    for x in values[period:]:v=x*k+v*(1-k)
    return v

def sma(values,period):
    return sum(values[-period:])/period if len(values)>=period else None

def rsi(values,period=14):
    if len(values)<=period:return None
    gains=[];losses=[]
    for i in range(1,len(values)):
        d=values[i]-values[i-1];gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[:period])/period;al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period;al=(al*(period-1)+losses[i])/period
    return 100 if al==0 else 100-(100/(1+ag/al))

def atr(candles,period=14):
    if len(candles)<=period:return None
    tr=[]
    for i in range(1,len(candles)):
        h=float(candles[i]["high"]);l=float(candles[i]["low"]);pc=float(candles[i-1]["close"])
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(tr[-period:])/period if len(tr)>=period else None

def memory_stats(market,interval,symbol,direction):
    try:
        with connection() as c:
            rows=c.execute("""SELECT result,created_at,confidence FROM signals
                              WHERE market=%s AND interval=%s AND symbol=%s AND direction=%s
                              AND status='closed' ORDER BY created_at DESC LIMIT 250""",
                           (market,interval,symbol,direction)).fetchall()
        if not rows:return 0,0
        wins=sum(1 for x in rows if x["result"] in ("tp1","tp2","tp3"))
        return len(rows),wins/len(rows)*100
    except Exception:return 0,0

def historical_pattern(candles,direction,lookback=180,pattern_len=8,forward=6):
    try:
        n=len(candles)
        if n<pattern_len+forward+30:return {"samples":0,"hitRate":0,"similarity":0}
        def feat(seq):
            closes=[float(x["close"]) for x in seq]
            highs=[float(x["high"]) for x in seq];lows=[float(x["low"]) for x in seq]
            base=max(abs(closes[0]),1e-12)
            return [((x/base)-1)*100 for x in closes]+[((h-l)/max(abs(cl),1e-12))*100 for h,l,cl in zip(highs,lows,closes)]
        cur=feat(candles[-pattern_len:]);hits=[];start=max(pattern_len,n-lookback);end=n-forward-pattern_len
        for i in range(start,end):
            past=feat(candles[i-pattern_len:i]);dist=sum((a-b)**2 for a,b in zip(cur,past))**0.5
            sim=max(0,1-min(1,dist/8))
            if sim<.55:continue
            entry=float(candles[i-1]["close"]);future=[float(x["close"]) for x in candles[i:i+forward]]
            if not future or entry<=0:continue
            move=((max(future) if direction=="شراء" else min(future))/entry-1)*100
            if direction=="بيع":move=-move
            hits.append((sim,move>.15))
        if not hits:return {"samples":0,"hitRate":0,"similarity":0}
        hits=sorted(hits,key=lambda x:x[0],reverse=True)[:12];w=sum(x[0] for x in hits)
        return {"samples":len(hits),"hitRate":round(sum(s for s,win in hits if win)/w*100,1),"similarity":round(sum(s for s,_ in hits)/len(hits)*100,1)}
    except Exception:return {"samples":0,"hitRate":0,"similarity":0}

def analyze(candles,symbol,market,interval,name=None):
    if len(candles)<80:return None
    closed=candles[:-1] if len(candles)>1 else candles
    last,prev,prev2=closed[-1],closed[-2],closed[-3]
    close=float(last["close"]);prev_close=float(prev["close"]);high=float(last["high"]);low=float(last["low"])
    ph=float(prev["high"]);pl=float(prev["low"]);op=float(prev["open"])
    closes=[float(x["close"]) for x in closed];highs=[float(x["high"]) for x in closed];lows=[float(x["low"]) for x in closed];vols=[float(x.get("volume",0) or 0) for x in closed]
    e20=ema(closes,20);e50=ema(closes,50);e200=ema(closes,200);a=atr(closed,14)
    if None in (e20,e50,e200,a) or a<=0:return None
    avgvol=sum(vols[-21:-1])/max(1,len(vols[-21:-1]));relvol=vols[-1]/avgvol if avgvol else 0
    body=abs(close-op);rng=max(high-low,1e-12);body_ratio=body/rng;close_pos=(close-low)/rng
    change=(close/prev_close-1)*100;change3=(close/float(closed[-4]["close"])-1)*100
    recent_low=min(lows[-6:-1]);recent_high=max(highs[-6:-1])
    up=e20>e50>e200 and close>e20;down=e20<e50<e200 and close<e20
    lp=recent_low<=e20*1.003 or pl<=e20*1.006;sp=recent_high>=e20*.997 or ph>=e20*.994
    lr=close>ph and close>op and close>e20;sr=close<prev["low"] and close<op and close<e20
    lc=close>op and close_pos>=.68 and body_ratio>=.45;sc=close<op and close_pos<=.32 and body_ratio>=.45
    extension=abs(close-e20)/a;normal=abs(change)<=3;not_ext=extension<=1.8;volume_ok=relvol>=1.15
    bullish=up and lp and lr and lc and volume_ok and normal and not_ext
    bearish=down and sp and sr and sc and volume_ok and normal and not_ext
    direction="بيع" if bullish and not bearish else "شراء" if bearish and not bullish else "حيادي"
    confidence=45;research={"samples":0,"hitRate":0,"similarity":0}
    if direction!="حيادي":
        confidence=70+(6 if relvol>=1.5 else 3)+(5 if body_ratio>=.65 else 2)+(5 if extension<=1.2 else 0)+(4 if abs(change3)>=.4 else 0)
        n,hist=memory_stats(market,interval,symbol,direction)
        if n>=5:confidence+=max(-10,min(10,(hist-50)*.2));confidence+=-8 if hist<45 else 4 if hist>=65 else 0
        research=historical_pattern(closed,direction,240,8,6)
        if research["samples"]>=4:
            confidence+=max(-10,min(10,(research["hitRate"]-50)*.22));confidence+=-8 if research["hitRate"]<45 else 4 if research["hitRate"]>=70 else 0
    confidence=round(max(0,min(100,confidence)),1)
    if direction!="حيادي":
        if direction=="شراء":
            swing=min(lows[-6:]);risk=min(max(close-swing,a*.75),a*1.35);sl=close-risk;tps=[close+risk*1.2,close+risk*1.8,close+risk*2.4]
        else:
            swing=max(highs[-6:]);risk=min(max(swing-close,a*.75),a*1.35);sl=close+risk;tps=[close-risk*1.2,close-risk*1.8,close-risk*2.4]
        n,hist=memory_stats(market,interval,symbol,direction)
        memory_ok=n<8 or hist>=52
        research_ok=research["samples"]>=4 and research["hitRate"]>=52
        ready=confidence>=82 and memory_ok and research_ok
    else:sl=0;tps=[0,0,0];ready=False
    ind={"rsi":rsi(closes),"ema20":e20,"ema50":e50,"ema200":e200,"sma20":sma(closes,20),"sma50":sma(closes,50),"sma200":sma(closes,200),"atr":a,"relVolume":round(relvol,2),"change":round(change,2),"change5":round((close/closes[-6]-1)*100,2),"change20":round((close/closes[-21]-1)*100,2),"price":close}
    return {"symbol":symbol,"displayName":name or symbol,"market":market,"interval":interval,
            "signal":"شراء قوي" if direction=="شراء" and confidence>=80 else "بيع قوي" if direction=="بيع" and confidence>=80 else direction,
            "direction":direction,"tradeReady":ready,"confidence":confidence,"researchScore":round(confidence*.65+research["hitRate"]*.25+research["similarity"]*.1,1),
            "historicalSamples":research["samples"],"historicalHitRate":research["hitRate"],"patternSimilarity":research["similarity"],
            "price":close,"entry":close if direction!="حيادي" else 0,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"rr":1.8 if direction!="حيادي" else 0,
            "reason":"اتجاه + سحب + استعادة + حجم، مع عكس الإشارة","change":round(change,2),"volume":vols[-1],"high":high,"low":low,
            "indicators":ind,"ai":True,"updatedAt":datetime.now(timezone.utc).isoformat()}

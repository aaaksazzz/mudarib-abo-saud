import math, time, statistics
from itertools import product

REVERSE_STRATEGY=True
STRATEGY_VERSION="REVERSE_V3"

CANDIDATES=[
    {"name":"Trend-RSI","ma":50,"vol":1.20,"move":0.25,"atr":1.6,"rr":2.5,"rsi":True,"reverse":REVERSE_STRATEGY},
    {"name":"Trend-Breakout","ma":50,"vol":1.50,"move":0.35,"atr":1.8,"rr":3.0,"rsi":False,"reverse":True},
    {"name":"Fast-Momentum","ma":20,"vol":1.30,"move":0.40,"atr":1.5,"rr":2.5,"rsi":True,"reverse":True},
    {"name":"Conservative-Trend","ma":100,"vol":1.60,"move":0.20,"atr":2.0,"rr":2.0,"rsi":True,"reverse":True},
    {"name":"Mean-Reversion","ma":50,"vol":1.10,"move":0.15,"atr":1.7,"rr":2.0,"rsi":True,"reverse":True},
    {"name":"Breakout-Strict","ma":100,"vol":2.00,"move":0.50,"atr":1.8,"rr":3.0,"rsi":False,"reverse":True},
]

def _rsi(closes,n=14):
    if len(closes)<=n:return 50.0
    gains=[];losses=[]
    for i in range(len(closes)-n,len(closes)):
        d=closes[i]-closes[i-1]
        gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains)/n; al=sum(losses)/n
    if al==0:return 100.0
    return 100-(100/(1+ag/al))

def _atr(k,n=14):
    if len(k)<n+2:return 0.0
    trs=[]
    for i in range(len(k)-n,len(k)):
        h=float(k[i][2]);l=float(k[i][3]);pc=float(k[i-1][4])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs)/len(trs)

def candidate_signal(k,p):
    if len(k)<max(120,p["ma"]+5):return None
    closes=[float(x[4]) for x in k]
    vols=[float(x[5] or 0) for x in k]
    price=closes[-1]; prev=closes[-2]
    ma=sum(closes[-p["ma"]:])/p["ma"]
    avgvol=sum(vols[-21:-1])/20 if len(vols)>20 else 0
    vr=vols[-1]/avgvol if avgvol else 1
    move=(price/prev-1)*100 if prev else 0
    trend=price>=ma
    if vr<p["vol"] or abs(move)<p["move"]: return None
    rsi=_rsi(closes)
    if p["rsi"]:
        if trend and rsi<52:return None
        if (not trend) and rsi>48:return None
    original="شراء" if trend else "بيع"
    # Final tester direction is always inverted: AI شراء -> بيع, AI بيع -> شراء.
    side="بيع" if original=="شراء" else "شراء"
    atr=_atr(k)
    if atr<=0:return None
    risk=atr*p["atr"]
    entry=price
    sl=entry-risk if side=="شراء" else entry+risk
    tp=entry+risk*p["rr"] if side=="شراء" else entry-risk*p["rr"]
    return side,entry,sl,tp

def evaluate(k,p):
    # Walk-forward only: signal at i uses k[:i+1], then future candles are used solely for exit.
    trades=[];i=max(120,p["ma"]+5)
    while i<len(k)-1:
        sig=candidate_signal(k[:i+1],p)
        if not sig:i+=1;continue
        side,entry,sl,tp=sig;out=None;exit_i=None
        for j in range(i+1,len(k)):
            hi=float(k[j][2]);lo=float(k[j][3])
            hit_sl=(lo<=sl) if side=="شراء" else (hi>=sl)
            hit_tp=(hi>=tp) if side=="شراء" else (lo<=tp)
            if hit_sl and hit_tp: out=-1.0;exit_i=j;break
            if hit_sl: out=-1.0;exit_i=j;break
            if hit_tp: out=abs(tp-entry)/abs(entry-sl);exit_i=j;break
        if out is None: break
        trades.append(out);i=exit_i+1
    wins=sum(1 for x in trades if x>0);losses=sum(1 for x in trades if x<=0)
    gross=sum(x for x in trades if x>0);gloss=abs(sum(x for x in trades if x<0))
    eq=0;peak=0;dd=0
    for x in trades:
        eq+=x;peak=max(peak,eq);dd=min(dd,eq-peak)
    return {"trades":len(trades),"wins":wins,"losses":losses,
            "win_rate":round(wins/len(trades)*100,2) if trades else None,
            "r":round(sum(trades),3),"profit_factor":round(gross/gloss,3) if gloss else None,
            "max_drawdown_r":round(abs(dd),3)}

def quality(train,test):
    if test["trades"]<15 or test["profit_factor"] is None:return -999
    if train["profit_factor"] is None:return -999
    # Favor positive OOS expectancy, PF, and stability; penalize drawdown.
    stability=max(0,1-abs((test["win_rate"] or 0)-(train["win_rate"] or 0))/30)
    return round(test["r"]*0.5+test["profit_factor"]*10+stability*5-test["max_drawdown_r"]*0.25,4)

def candidates():return CANDIDATES

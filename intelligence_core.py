"""
MUDARIB INTELLIGENCE CORE
Regime-aware multi-factor market reasoning engine.
No single indicator decides a trade. Every decision must survive
trend, momentum, structure, volume, volatility and risk gates.
"""

def _ema(v,n):
    if not v:return 0.0
    n=min(n,len(v)); a=2/(n+1); e=sum(v[:n])/n
    for x in v[n:]: e=x*a+e*(1-a)
    return e

def _rsi(v,n=14):
    if len(v)<n+1:return 50.0
    g=l=0.0
    for i in range(len(v)-n,len(v)):
        d=v[i]-v[i-1]; g+=max(d,0); l+=max(-d,0)
    return 100.0 if l==0 else 100-(100/(1+g/l))

def _atr(k,n=14):
    if len(k)<n+1:return 0.0
    out=[]
    for i in range(len(k)-n,len(k)):
        h,l,pc=float(k[i][2]),float(k[i][3]),float(k[i-1][4])
        out.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(out)/len(out)

def _adx(k,n=14):
    if len(k)<n+2:return 0.0
    plus=minus=tr=0.0
    for i in range(len(k)-n,len(k)):
        h,l,ph,pl,pc=map(float,(k[i][2],k[i][3],k[i-1][2],k[i-1][3],k[i-1][4]))
        up=h-ph; dn=pl-l
        plus+=up if up>dn and up>0 else 0
        minus+=dn if dn>up and dn>0 else 0
        tr+=max(h-l,abs(h-pc),abs(l-pc))
    if tr<=0:return 0.0
    p=100*plus/tr; m=100*minus/tr
    return 100*abs(p-m)/max(p+m,1e-9)

def _structure(k,n=20):
    if len(k)<n+2:return 0
    hs=[float(x[2]) for x in k[-n-1:-1]]
    ls=[float(x[3]) for x in k[-n-1:-1]]
    h,l=float(k[-1][2]),float(k[-1][3])
    return 1 if h>max(hs) else -1 if l<min(ls) else 0

def _risk(price,atr):
    return max(atr*1.35,price*0.006)

def _leverage(symbol):
    s=str(symbol or "").upper()
    if s in {"BTCUSDT","ETHUSDT"}: return 10
    if s in {"BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","LTCUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","TRXUSDT"}: return 7
    if s in {"DOGEUSDT","SHIBUSDT","PEPEUSDT","WIFUSDT","BONKUSDT","FLOKIUSDT"}: return 3
    return 5

def intelligence_signal(klines, reverse=True, feedback=None, symbol=None):
    if len(klines)<100:return None
    c=[float(x[4]) for x in klines]; v=[float(x[5] or 0) for x in klines]
    p=c[-1]; prev=c[-2]
    e20,e50,e200=_ema(c,20),_ema(c,50),_ema(c,200)
    rsi=_rsi(c); atr=_atr(klines); adx=_adx(klines); st=_structure(klines)
    av=sum(v[-21:-1])/20 if len(v)>20 else 0
    vr=v[-1]/av if av else 0
    move=(p/prev-1)*100 if prev else 0
    volpct=atr/p*100 if p else 0

    bull=p>e20>e50>e200
    bear=p<e20<e50<e200
    if not bull and not bear:return None
    original="شراء" if bull else "بيع"

    # Independent evidence buckets. Score is a model quality score, NOT win probability.
    trend=20 if bull or bear else 0
    alignment=12 if ((bull and e20>e50 and e50>e200) or (bear and e20<e50 and e50<e200)) else 0
    momentum=12 if ((bull and 52<=rsi<=72) or (bear and 28<=rsi<=48)) else 0
    volume=min(16,max(0,(vr-1.0)*10))
    structure=10 if ((bull and st==1) or (bear and st==-1)) else 0
    strength=min(14,adx*0.35)
    volatility=6 if .15<=volpct<=4.5 else 0
    candle=5 if ((bull and move>0) or (bear and move<0)) else 0
    score=round(min(98,35+trend+alignment+momentum+volume+structure+strength+volatility+candle),1)

    # Live opportunity gate: keep the engine selective, but do not make the
    # live scanner disappear during normal low-volume/transition regimes.
    # The score remains a model-quality/confluence score, never a win probability.
    if adx<12 or vr<1.05 or atr<=0 or score<72:return None
    if bull and rsi>78:return None
    if bear and rsi<22:return None

    side=("بيع" if original=="شراء" else "شراء") if reverse else original
    risk=_risk(p,atr)
    if side=="شراء": sl,tp1,tp2,tp3=p-risk,p+risk,p+risk*2,p+risk*3
    else: sl,tp1,tp2,tp3=p+risk,p-risk,p-risk*2,p-risk*3

    return {
        "side":side,"entry":p,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "ai":score,"strategy_mode":"MUDARIB_INTELLIGENCE_CORE",
        "strategy_min_score":72,"leverage":_leverage(symbol),"regime":"trend",
        "confluence":{"trend":trend,"alignment":alignment,"momentum":momentum,
                      "volume":round(volume,1),"structure":structure,
                      "strength":round(strength,1),"volatility":volatility,"candle":candle}
    }

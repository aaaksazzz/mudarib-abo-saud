import math, statistics
from datetime import datetime, timezone

def _f(x,d=0.0):
    try:
        x=float(x); return x if math.isfinite(x) else d
    except: return d

def _softmax(z):
    m=max(z); e=[math.exp(max(-30,min(30,x-m))) for x in z]; s=sum(e) or 1
    return [v/s for v in e]

def features(c,i):
    q=c[i]; o=_f(q.get("o")); h=_f(q.get("h")); l=_f(q.get("l")); p=_f(q.get("c"))
    if p<=0:return None
    r=max(h-l,p*1e-8); body=(p-o)/p
    up=max(0,h-max(o,p))/r; dn=max(0,min(o,p)-l)/r
    def ret(n):
        b=_f(c[i-n].get("c")) if i>=n else p
        return p/b-1 if b>0 else 0
    rs=[]
    for k in range(max(0,i-19),i):
        cc=_f(c[k].get("c"))
        if cc>0: rs.append((_f(c[k].get("h"))-_f(c[k].get("l")))/cc)
    avgr=sum(rs)/len(rs) if rs else r/p
    vs=[_f(c[k].get("v")) for k in range(max(0,i-20),i)]
    avgv=sum(vs)/len(vs) if vs else _f(q.get("v"))
    v=_f(q.get("v"))
    return [body,r/p,up,dn,(p-l)/r,body*p/r,ret(1),ret(2),ret(3),ret(5),ret(8),ret(13),ret(20),avgr,math.log1p(v/avgv) if avgv>0 else 0,(v-avgv)/(avgv or 1)]

def label(c,i,horizon=6):
    p=_f(c[i].get("c"))
    if p<=0 or i+horizon>=len(c): return 2
    rs=[]
    for k in range(max(0,i-13),i+1):
        cc=_f(c[k].get("c"))
        if cc>0: rs.append((_f(c[k].get("h"))-_f(c[k].get("l")))/cc)
    v=max(.0025,min(statistics.median(rs) if rs else .01,.06))
    tp=max(.0075,min(v*1.8,.05)); sl=max(.005,min(v*.9,.03))
    lu=ls=su=ss=None
    for k in range(i+1,min(len(c),i+horizon+1)):
        hi=_f(c[k].get("h")); lo=_f(c[k].get("l"))
        if lu is None:
            if hi>=p*(1+tp) and lo<=p*(1-sl): lu=0
            elif hi>=p*(1+tp): lu=1
            elif lo<=p*(1-sl): lu=0
        if su is None:
            if lo<=p*(1-tp) and hi>=p*(1+sl): su=0
            elif lo<=p*(1-tp): su=1
            elif hi>=p*(1+sl): su=0
    if lu==1 and su!=1:return 0
    if su==1 and lu!=1:return 1
    return 2

def train(X,y,epochs=90,lr=.07,l2=.002):
    means=[]; stds=[]
    for j in range(len(X[0])):
        a=[r[j] for r in X]; m=sum(a)/len(a); s=math.sqrt(sum((z-m)**2 for z in a)/len(a)) or 1
        means.append(m);stds.append(s)
    Z=[[(v-means[j])/stds[j] for j,v in enumerate(r)]+[1] for r in X]
    W=[[0.0]*len(Z[0]) for _ in range(3)]
    for ep in range(epochs):
        g=[[0.0]*len(Z[0]) for _ in range(3)]
        for r,t in zip(Z,y):
            p=_softmax([sum(W[k][j]*r[j] for j in range(len(r))) for k in range(3)])
            for k in range(3):
                e=p[k]-(1 if t==k else 0)
                for j in range(len(r)):g[k][j]+=e*r[j]
        rate=lr*(1-.5*ep/max(1,epochs-1))
        for k in range(3):
            for j in range(len(r)):W[k][j]-=rate*(g[k][j]/len(Z)+l2*W[k][j])
    return W,means,stds

def analyze(candles,symbol="",market="",interval="15m"):
    c=[x for x in candles if _f(x.get("c"))>0 and _f(x.get("h"))>0 and _f(x.get("l"))>0]
    if len(c)>70:c=c[:-1]
    if len(c)<60:raise RuntimeError("بيانات AI غير كافية")
    X=[];y=[]
    for i in range(22,len(c)-7):
        f=features(c,i)
        if f:X.append(f);y.append(label(c,i))
    if len(X)<40:raise RuntimeError("عينات AI غير كافية")
    rf=max(0,len(X)-45); model=train(X+X[rf:]+X[rf:],y+y[rf:]+y[rf:])
    W,M,S=model; z=[(v-M[j])/S[j] for j,v in enumerate(features(c,len(c)-1))]+[1]
    p=_softmax([sum(W[k][j]*z[j] for j in range(len(z))) for k in range(3)])
    buy,sell,neutral=p; price=_f(c[-1].get("c"))
    rr=[(_f(x.get("h"))-_f(x.get("l")))/_f(x.get("c")) for x in c[-14:] if _f(x.get("c"))>0]
    vr=max(.003,min(statistics.median(rr) if rr else .01,.06)); risk=price*max(.005,min(vr*.9,.025)); reward=risk*2
    direction="شراء" if buy>=sell and buy>=neutral else "بيع" if sell>=buy and sell>=neutral else "حيادي"
    conf={"شراء":buy,"بيع":sell,"حيادي":neutral}[direction]
    edge=max(buy,sell)-max(neutral,min(buy,sell))
    ready=direction!="حيادي" and conf>=.60 and edge>=.10
    if direction=="شراء":tp,sl=price+reward,price-risk
    elif direction=="بيع":tp,sl=price-reward,price+risk
    else:tp=sl=price
    if not ready:direction="حيادي";tp=sl=price
    signal=("شراء قوي" if ready and direction=="شراء" and conf>=.75 else "شراء" if ready and direction=="شراء" else "بيع قوي" if ready and direction=="بيع" and conf>=.75 else "بيع" if ready and direction=="بيع" else "حيادي")
    return {"ok":True,"ai":True,"engine":"Mudarib AI Price-Action ML v1","symbol":symbol,"market":market,"interval":interval,"signal":signal,"direction":direction,"tradeReady":ready,"confidence":round(conf*100,1),"score":round(max(p)*100,1),"score10":round(max(p)*10,1),"probabilities":{"buy":round(buy*100,1),"sell":round(sell*100,1),"neutral":round(neutral*100,1)},"price":price,"entry":price,"tp":tp,"tp1":tp,"sl":sl,"rr":2.0,"sampleCount":len(X),"updatedAt":datetime.now(timezone.utc).isoformat()}

import math, statistics
from datetime import datetime, timezone

def _f(x,d=0.0):
    try:
        x=float(x); return x if math.isfinite(x) else d
    except: return d

def _softmax(z):
    m=max(z); e=[math.exp(max(-30,min(30,x-m))) for x in z]; s=sum(e) or 1; return [v/s for v in e]

def _ret(c,i,n):
    if i<n:return 0
    a=_f(c[i-n].get("c")); b=_f(c[i].get("c")); return b/a-1 if a>0 else 0

def _features(c,i):
    q=c[i]; o=_f(q.get("o")); h=_f(q.get("h")); l=_f(q.get("l")); p=_f(q.get("c")); r=max(h-l,p*1e-8)
    ranges=[(_f(c[k].get("h"))-_f(c[k].get("l")))/max(_f(c[k].get("c")),1e-12) for k in range(max(0,i-20),i)]
    vols=[_f(c[k].get("v")) for k in range(max(0,i-20),i)]; avgr=sum(ranges)/len(ranges) if ranges else .01; avgv=sum(vols)/len(vols) if vols else _f(q.get("v")); v=_f(q.get("v"))
    return [(p-o)/p,r/p,max(0,h-max(o,p))/r,max(0,min(o,p)-l)/r,(p-l)/r,_ret(c,i,1),_ret(c,i,2),_ret(c,i,3),_ret(c,i,5),_ret(c,i,8),_ret(c,i,13),_ret(c,i,20),avgr,math.log1p(v/avgv) if avgv else 0,(v-avgv)/(avgv or 1)]

def _label(c,i,horizon=8):
    p=_f(c[i].get("c")); rs=[(_f(c[k].get("h"))-_f(c[k].get("l")))/max(_f(c[k].get("c")),1e-12) for k in range(max(0,i-14),i)]; vol=max(.003,min(statistics.median(rs) if rs else .01,.05)); tp=max(.008,vol*1.6)
    up=dn=False
    for k in range(i+1,min(len(c),i+horizon+1)):
        hi=_f(c[k].get("h")); lo=_f(c[k].get("l")); up=up or hi>=p*(1+tp); dn=dn or lo<=p*(1-tp)
        if up or dn: break
    return 0 if up and not dn else 1 if dn and not up else 2

def _train(X,y):
    m=[sum(r[j] for r in X)/len(X) for j in range(len(X[0]))]; s=[math.sqrt(sum((r[j]-m[j])**2 for r in X)/len(X)) or 1 for j in range(len(X[0]))]; Z=[[(v-m[j])/s[j] for j,v in enumerate(r)]+[1] for r in X]; W=[[0.0]*len(Z[0]) for _ in range(3)]
    for ep in range(70):
        g=[[0.0]*len(Z[0]) for _ in range(3)]
        for r,t in zip(Z,y):
            p=_softmax([sum(W[k][j]*r[j] for j in range(len(r))) for k in range(3)])
            for k in range(3):
                e=p[k]-(1 if t==k else 0)
                for j in range(len(r)):g[k][j]+=e*r[j]
        lr=.06*(1-.45*ep/69)
        for k in range(3):
            for j in range(len(Z[0])):W[k][j]-=lr*g[k][j]/len(Z)
    return W,m,s

def _levels(c,p,d):
    rs=[(_f(x.get("h"))-_f(x.get("l")))/max(_f(x.get("c")),1e-12) for x in c[-20:]]; vol=max(.003,min(statistics.median(rs) if rs else .01,.045)); risk=p*max(.006,min(vol*.9,.025))
    return ([p+risk,p+1.6*risk,p+2.2*risk],p-risk) if d=="شراء" else ([p-risk,p-1.6*risk,p-2.2*risk],p+risk)

def analyze(candles,symbol="",market="",interval="15m"):
    c=[x for x in candles if _f(x.get("c"))>0 and _f(x.get("h"))>0 and _f(x.get("l"))>0]
    if len(c)>70:c=c[:-1]
    if len(c)<70:raise RuntimeError("بيانات AI غير كافية")
    X=[];y=[]
    for i in range(25,len(c)-9):X.append(_features(c,i));y.append(_label(c,i))
    W,M,S=_train(X,y); z=[(v-M[j])/S[j] for j,v in enumerate(_features(c,len(c)-1))]+[1]; pr=_softmax([sum(W[k][j]*z[j] for j in range(len(z))) for k in range(3)]); buy,sell,neutral=pr; p=_f(c[-1].get("c")); d="شراء" if buy>=sell and buy>=neutral else "بيع" if sell>=buy and sell>=neutral else "حيادي"; conf=max(buy,sell) if d!="حيادي" else neutral; ready=d!="حيادي" and conf>=.68 and max(buy,sell)-neutral>=.12
    if not ready:d="حيادي"
    tps,sl=_levels(c,p,d) if ready else ([p,p,p],p); signal="شراء قوي" if d=="شراء" and conf>=.78 else "شراء" if d=="شراء" else "بيع قوي" if d=="بيع" and conf>=.78 else "بيع" if d=="بيع" else "حيادي"
    return {"ok":True,"ai":True,"engine":"Mudarib AI Trader v2","symbol":symbol,"market":market,"interval":interval,"signal":signal,"direction":d,"tradeReady":ready,"confidence":round(conf*100,1),"probabilities":{"buy":round(buy*100,1),"sell":round(sell*100,1),"neutral":round(neutral*100,1)},"price":p,"entry":p,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"sl":sl,"rr":2.2,"sampleCount":len(X),"updatedAt":datetime.now(timezone.utc).isoformat()}

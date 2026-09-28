"""Classical multi-method market analysis engine.
Each method is isolated: selecting one method never mixes evidence from another.
All decisions use OHLCV only; no external chart widgets or indicator libraries.
"""
import math, statistics

METHODS = {
    "classic":"كلاسيكي",
    "harmonic":"هارمونيك",
    "supply_demand":"طلب وعرض",
    "price_action":"Price Action",
    "candlestick":"شموع يابانية",
    "fibonacci":"فيبوناتشي",
    "elliott":"موجات إليوت",
    "patterns":"نماذج سعرية",
}

def f(x,d=0.0):
    try:return float(x)
    except:return d

def pivots(k, look=3):
    out=[]
    for i in range(look,len(k)-look):
        h=f(k[i][2]); l=f(k[i][3])
        if h>=max(f(k[j][2]) for j in range(i-look,i+look+1)):out.append(("H",i,h))
        if l<=min(f(k[j][3]) for j in range(i-look,i+look+1)):out.append(("L",i,l))
    return out

def levels(k,side,entry):
    ps=pivots(k[-100:],3)
    hs=[x[2] for x in ps if x[0]=="H"]; ls=[x[2] for x in ps if x[0]=="L"]
    if side=="شراء":
        candidates=[x for x in ls if x<entry]
        sl=(min(candidates[-3:]) if candidates else min(f(x[3]) for x in k[-30:]))
        risk=entry-sl
        if risk<=0 or risk/entry>0.12:return None
        return sl,entry+risk,entry+2*risk,entry+3*risk,entry+4*risk
    candidates=[x for x in hs if x>entry]
    sl=(max(candidates[-3:]) if candidates else max(f(x[2]) for x in k[-30:]))
    risk=sl-entry
    if risk<=0 or risk/entry>0.12:return None
    return sl,entry-risk,entry-2*risk,entry-3*risk,entry-4*risk

def result(method,name,side,entry,k,evidence,confidence):
    lv=levels(k,side,entry)
    if not lv:return None
    sl,tp1,tp2,tp3,tp4=lv
    return {"side":side,"original_side":side,"entry":entry,"tp1":tp1,"tp2":tp2,"tp3":tp3,"tp4":tp4,"sl":sl,
            "ai":round(max(50,min(97,confidence)),2),"strategy_mode":method,"analysis_method":method,
            "analysis_name":name,"reverse":False,"reverse_applied":False,
            "analysis":{"method":METHODS.get(method,method),"model":name,"evidence":evidence}}

def classic(k):
    if len(k)<30:return None
    p=f(k[-1][4]); ps=pivots(k[-60:],3)
    highs=[x for x in ps if x[0]=="H"]; lows=[x for x in ps if x[0]=="L"]
    if len(highs)<2 or len(lows)<2:return None
    hh=highs[-1][2]>highs[-2][2]; hl=lows[-1][2]>lows[-2][2]
    lh=highs[-1][2]<highs[-2][2]; ll=lows[-1][2]<lows[-2][2]
    recent_h=highs[-1][2]; recent_l=lows[-1][2]
    if hh and hl:
        return result("classic","اتجاه صاعد + قمم وقيعان أعلى","شراء",p,k,{"structure":"HH + HL","resistance":recent_h,"support":recent_l},84)
    if lh and ll:
        return result("classic","اتجاه هابط + قمم وقيعان أدنى","بيع",p,k,{"structure":"LH + LL","resistance":recent_h,"support":recent_l},84)
    return None

def patterns(k):
    if len(k)<45:return None
    ps=pivots(k[-80:],3)
    hs=[x for x in ps if x[0]=="H"]; ls=[x for x in ps if x[0]=="L"]
    p=f(k[-1][4])
    if len(hs)>=3:
        a,b,c=hs[-3][2],hs[-2][2],hs[-1][2]
        if abs(a-c)/max(a,1e-12)<0.025 and b>a*1.02 and p<b:
            return result("patterns","رأس وكتفين","بيع",p,k,{"left_shoulder":a,"head":b,"right_shoulder":c},90)
    if len(ls)>=3:
        a,b,c=ls[-3][2],ls[-2][2],ls[-1][2]
        if abs(a-c)/max(a,1e-12)<0.025 and b<a*0.98 and p>b:
            return result("patterns","رأس وكتفين مقلوب","شراء",p,k,{"left_shoulder":a,"head":b,"right_shoulder":c},90)
    if len(hs)>=2:
        a,b=hs[-2][2],hs[-1][2]
        if abs(a-b)/max(a,1e-12)<0.015 and p<min(a,b)*0.995:
            return result("patterns","قمة مزدوجة","بيع",p,k,{"tops":[a,b]},87)
    if len(ls)>=2:
        a,b=ls[-2][2],ls[-1][2]
        if abs(a-b)/max(a,1e-12)<0.015 and p>max(a,b)*1.005:
            return result("patterns","قاع مزدوج","شراء",p,k,{"bottoms":[a,b]},87)
    return None

def price_action(k):
    if len(k)<25:return None
    p=f(k[-1][4]); prev=f(k[-2][4]); hi=max(f(x[2]) for x in k[-21:-1]); lo=min(f(x[3]) for x in k[-21:-1])
    if p>hi:
        return result("price_action","اختراق مقاومة","شراء",p,k,{"breakout_level":hi,"close_confirmed":True},88)
    if p<lo:
        return result("price_action","كسر دعم","بيع",p,k,{"breakdown_level":lo,"close_confirmed":True},88)
    return None

def supply_demand(k):
    if len(k)<30:return None
    p=f(k[-1][4]); ranges=[max(f(x[2])-f(x[3]),0) for x in k[-15:]]
    med=statistics.median(ranges) or 1
    for i in range(len(k)-4,len(k)-1):
        o,h,l,c=map(f,(k[i][1],k[i][2],k[i][3],k[i][4]))
        if h-l>=1.8*med:
            if c>o and p>=l and p<=c:
                return result("supply_demand","منطقة طلب + اندفاع صاعد","شراء",p,k,{"zone_low":l,"zone_high":c,"impulse_range":h-l},86)
            if c<o and p>=c and p<=h:
                return result("supply_demand","منطقة عرض + اندفاع هابط","بيع",p,k,{"zone_low":c,"zone_high":h,"impulse_range":h-l},86)
    return None

def candlestick(k):
    if len(k)<10:return None
    o,h,l,c=map(f,(k[-1][1],k[-1][2],k[-1][3],k[-1][4]))
    r=max(h-l,1e-12); body=abs(c-o); up=h-max(o,c); dn=min(o,c)-l
    prev_o,prev_c=map(f,(k[-2][1],k[-2][4]))
    if dn/r>=.55 and c>o:
        return result("candlestick","مطرقة صاعدة","شراء",c,k,{"lower_wick_ratio":dn/r,"body_ratio":body/r},82)
    if up/r>=.55 and c<o:
        return result("candlestick","شهاب هابط","بيع",c,k,{"upper_wick_ratio":up/r,"body_ratio":body/r},82)
    if c>o and prev_c<prev_o and c>=prev_o and o<=prev_c:
        return result("candlestick","ابتلاع شرائي","شراء",c,k,{"engulfing":True},88)
    if c<o and prev_c>prev_o and c<=prev_o and o>=prev_c:
        return result("candlestick","ابتلاع بيعي","بيع",c,k,{"engulfing":True},88)
    return None

def fibonacci(k):
    if len(k)<35:return None
    ps=pivots(k[-80:],3)
    hs=[x[2] for x in ps if x[0]=="H"]; ls=[x[2] for x in ps if x[0]=="L"]
    if not hs or not ls:return None
    hi,lo=hs[-1],ls[-1]; p=f(k[-1][4]); span=hi-lo
    if span<=0:return None
    r=(p-lo)/span
    if .382<=r<=.618 and p>lo+span*.382:
        return result("fibonacci","تصحيح فيبوناتشي 38.2–61.8%","شراء",p,k,{"swing_low":lo,"swing_high":hi,"retracement":round(r*100,2)},84)
    if .382<=1-r<=.618 and p<hi-span*.382:
        return result("fibonacci","تصحيح فيبوناتشي هابط 38.2–61.8%","بيع",p,k,{"swing_low":lo,"swing_high":hi,"retracement":round((1-r)*100,2)},84)
    return None

def harmonic(k):
    if len(k)<60:return None
    ps=pivots(k[-120:],3)
    if len(ps)<5:return None
    z=ps[-5:]; vals=[x[2] for x in z]
    # Alternating pivots are required; ratio tolerances are deliberately explicit.
    if any(z[i][0]==z[i+1][0] for i in range(4)):return None
    X,A,B,C,D=vals
    xa=abs(A-X); ab=abs(B-A); bc=abs(C-B); cd=abs(D-C)
    if min(xa,ab,bc,cd)<=0:return None
    rAB=ab/xa; rBC=bc/ab; rCD=cd/bc; p=f(k[-1][4])
    patterns=[
        ("Gartley",.618,.382,.886,.786,92),
        ("Bat",.5,.382,.886,.886,91),
        ("Butterfly",.786,.382,.886,1.618,90),
        ("Crab",.618,.382,1.0,1.618,90),
        ("Cypher",.382,.382,.786,1.272,88),
    ]
    for name,abx,bcx,adx,cdx,conf in patterns:
        if abs(rAB-abx)<=.08 and .382<=rBC<=.886 and abs(rCD-cdx)<=.22:
            side="شراء" if D<C else "بيع"
            return result("harmonic",name,side,p,k,{"X":X,"A":A,"B":B,"C":C,"D":D,"AB_XA":round(rAB,3),"BC_AB":round(rBC,3),"CD_BC":round(rCD,3)},conf)
    return None

def elliott(k):
    if len(k)<70:return None
    ps=pivots(k[-100:],3)
    if len(ps)<7:return None
    z=ps[-7:]
    vals=[x[2] for x in z]
    ups=sum(vals[i]>vals[i-1] for i in range(1,len(vals)))
    dns=sum(vals[i]<vals[i-1] for i in range(1,len(vals)))
    p=f(k[-1][4])
    if ups>=5:
        return result("elliott","تسلسل موجي صاعد محتمل","شراء",p,k,{"pivot_sequence":vals,"higher_steps":ups},78)
    if dns>=5:
        return result("elliott","تسلسل موجي هابط محتمل","بيع",p,k,{"pivot_sequence":vals,"lower_steps":dns},78)
    return None

def analyze(k,method):
    if not k:return None
    fn={"classic":classic,"harmonic":harmonic,"supply_demand":supply_demand,"price_action":price_action,
        "candlestick":candlestick,"fibonacci":fibonacci,"elliott":elliott,"patterns":patterns}.get(method)
    if not fn:return None
    return fn(k)

def apply_reverse(signal):
    if not signal:return None
    s=dict(signal); original=s.get("side")
    if original in ("شراء","بيع"):
        s["original_side"]=original
        s["side"]="بيع" if original=="شراء" else "شراء"
        s["reverse_applied"]=True
        s["reverse"]=True
        s["recommendation"]=s["side"]
    return s

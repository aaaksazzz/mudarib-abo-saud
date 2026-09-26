def signal_from_klines(klines, reverse=True):
    if len(klines)<25:return None
    closes=[float(x[4]) for x in klines]; vols=[float(x[5]) for x in klines]
    price=closes[-1]; prev=closes[-2]; ma20=sum(closes[-20:])/20
    ma200=sum(closes[-200:])/200 if len(closes)>=200 else sum(closes)/len(closes)
    avgvol=sum(vols[-21:-1])/20 if len(vols)>20 else 0
    change=(price/prev-1)*100 if prev else 0; vr=vols[-1]/avgvol if avgvol else 0
    if price>ma20 and price>ma200 and vr>=1.5 and .5<=abs(change)<=4:
        original="شراء";score=min(99,60+vr*10+min(15,max(0,change)))
    elif price<ma20 and price<ma200 and vr>=1.5 and .5<=abs(change)<=4:
        original="بيع";score=min(99,60+vr*10+min(15,max(0,-change)))
    else:
        # Keep the same trend direction but allow a lighter fallback so the market pages
        # are not empty when the strict volume/move filter has no current match.
        if not (price>ma20 and price>ma200 or price<ma20 and price<ma200): return None
        if vr < 1.05 or abs(change) < .2 or abs(change) > 4.5: return None
        original="شراء" if price>ma20 and price>ma200 else "بيع"
        score=min(88,52+vr*8+min(12,abs(change)*2))
    side=("بيع" if original=="شراء" else "شراء") if reverse else original
    risk=price*.02
    if side=="شراء":sl=price-risk;tp1=price+risk;tp2=price+risk*1.7;tp3=price+risk*2.4
    else:sl=price+risk;tp1=price-risk;tp2=price-risk*1.7;tp3=price-risk*2.4
    return {"side":side,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"ai":round(score,1)}

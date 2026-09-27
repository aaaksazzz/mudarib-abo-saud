REVERSE_STRATEGY = True\n\ndef signal_from_klines(klines, reverse=REVERSE_STRATEGY):
    """Generate a stable technical signal so the UI does not go blank between rare breakouts."""
    if len(klines) < 25:
        return None
    closes=[float(x[4]) for x in klines if x[4] is not None]
    vols=[float(x[5] or 0) for x in klines]
    if len(closes) < 25:
        return None
    price=closes[-1]
    prev=closes[-2] if len(closes) > 1 else price
    ma20=sum(closes[-20:])/20
    ma200=sum(closes[-200:])/200 if len(closes) >= 200 else sum(closes)/len(closes)
    avgvol=sum(vols[-21:-1])/20 if len(vols) > 20 else 0
    change=(price/prev-1)*100 if prev else 0
    vr=vols[-1]/avgvol if avgvol else 1.0
    bullish=price >= ma20 and price >= ma200
    original="شراء" if bullish else "بيع"
    if ((bullish and vr >= 1.5 and change >= 0.5) or
        (not bullish and vr >= 1.5 and change <= -0.5)):
        score=60 + min(25, vr*8) + min(10, abs(change)*1.5)
    else:
        trend_gap=abs(price/ma20-1)*100 + abs(price/ma200-1)*100 if ma20 and ma200 else 0
        vol_bonus=min(8, max(0, vr-0.5)*6)
        move_bonus=min(7, abs(change)*1.2)
        score=58 + min(12, trend_gap*2) + vol_bonus + move_bonus
    score=round(min(92, max(58, score)),1)
    side=("بيع" if original=="شراء" else "شراء") if reverse else original
    risk=price*0.02
    if side=="شراء":
        sl=price-risk; tp1=price+risk; tp2=price+risk*1.7; tp3=price+risk*2.4
    else:
        sl=price+risk; tp1=price-risk; tp2=price-risk*1.7; tp3=price-risk*2.4
    return {"side":side,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,"ai":score}

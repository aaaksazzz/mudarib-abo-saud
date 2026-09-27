REVERSE_STRATEGY = True  # Full strategy inversion: BUY↔SELL

def leverage_for_symbol(symbol):
    """Conservative futures leverage shown per symbol/card."""
    s=str(symbol or "").upper().replace("/","").replace("-","")
    major={"BTCUSDT","ETHUSDT"}
    liquid={"BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT","LTCUSDT","LINKUSDT","AVAXUSDT","DOTUSDT","TRXUSDT"}
    high_vol={"DOGEUSDT","SHIBUSDT","PEPEUSDT","WIFUSDT","BONKUSDT","FLOKIUSDT","1000PEPEUSDT","1000SHIBUSDT"}
    if s in major:
        return 10
    if s in liquid:
        return 7
    if s in high_vol:
        return 3
    return 5

def strategy_profile(feedback=None):
    """
    Adaptive profile driven only by trades that have already closed.
    It tightens signal quality after losses and relaxes gradually after
    the rolling win rate recovers. It never uses future candles.
    """
    f=feedback or {}
    closed=int(f.get("closed") or 0)
    win_rate=float(f.get("win_rate") or 0)
    losses=int(f.get("losses") or 0)

    profile={
        "min_score":58.0,
        "volume_ratio":1.50,
        "move_pct":0.50,
        "mode":"تعلم"
    }

    if closed >= 10:
        if win_rate < 45:
            profile.update(min_score=72.0,volume_ratio=2.00,move_pct=0.80,mode="تشديد قوي")
        elif win_rate < 50:
            profile.update(min_score=67.0,volume_ratio=1.80,move_pct=0.65,mode="تشديد")
        elif win_rate < 55:
            profile.update(min_score=62.0,volume_ratio=1.60,move_pct=0.55,mode="توازن")
        else:
            profile.update(min_score=58.0,volume_ratio=1.45,move_pct=0.45,mode="أداء إيجابي")

    if losses >= 3:
        profile["min_score"]=min(78.0,profile["min_score"]+2.0)
        profile["volume_ratio"]=min(2.20,profile["volume_ratio"]+0.10)

    return profile

def signal_from_klines(klines, reverse=REVERSE_STRATEGY, feedback=None):
    # Pipeline: technical analysis -> quality filter -> full signal reversal -> 1R/3R risk model.

    """Generate a reversed technical signal with adaptive quality filtering."""
    if len(klines) < 25:
        return None
    closes=[float(x[4]) for x in klines if x[4] is not None]
    vols=[float(x[5] or 0) for x in klines]
    if len(closes) < 25:
        return None

    profile=strategy_profile(feedback)
    price=closes[-1]
    prev=closes[-2] if len(closes)>1 else price
    ma20=sum(closes[-20:])/20
    ma200=sum(closes[-200:])/200 if len(closes)>=200 else sum(closes)/len(closes)
    avgvol=sum(vols[-21:-1])/20 if len(vols)>20 else 0
    change=(price/prev-1)*100 if prev else 0
    vr=vols[-1]/avgvol if avgvol else 1.0

    bullish=price>=ma20 and price>=ma200
    original="شراء" if bullish else "بيع"

    breakout=((bullish and vr>=profile["volume_ratio"] and change>=profile["move_pct"]) or
              (not bullish and vr>=profile["volume_ratio"] and change<=-profile["move_pct"]))

    if breakout:
        score=60 + min(25,vr*8) + min(10,abs(change)*1.5)
    else:
        trend_gap=(abs(price/ma20-1)*100 + abs(price/ma200-1)*100) if ma20 and ma200 else 0
        vol_bonus=min(8,max(0,vr-0.5)*6)
        move_bonus=min(7,abs(change)*1.2)
        score=58 + min(12,trend_gap*2) + vol_bonus + move_bonus

    score=round(min(92,max(0,score)),1)
    if score < profile["min_score"]:
        return None

    side=("بيع" if original=="شراء" else "شراء") if reverse else original
    risk=price*0.02
    if side=="شراء":
        sl=price-risk; tp1=price+risk*3; tp2=price+risk*3; tp3=price+risk*3
    else:
        sl=price+risk; tp1=price-risk*3; tp2=price-risk*3; tp3=price-risk*3

    return {
        "side":side,"entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,
        "sl":sl,"ai":score,"strategy_mode":profile["mode"],
        "strategy_min_score":profile["min_score"],"leverage":leverage_for_symbol(symbol) if "symbol" in locals() else 5
    }

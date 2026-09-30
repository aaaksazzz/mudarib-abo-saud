import os,time,sqlite3,asyncio
from pathlib import Path
from contextlib import closing
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

ROOT=Path(__file__).parent
STATIC=ROOT/"static"
DATA=Path(os.getenv("DATA_DIR","/data"))
try:
    DATA.mkdir(parents=True,exist_ok=True)
except Exception:
    DATA=ROOT/"data"; DATA.mkdir(exist_ok=True)
DB=DATA/"trading.db"

app=FastAPI(title="Whale Flow PRO",version="5.1")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

MIN_VOL=1_000_000
WHALE_USD=25_000
STABLE={"USDCUSDT","FDUSDUSDT","TUSDUSDT","USDPUSDT","DAIUSDT","USDEUSDT","EURUSDT","USDTUSDT"}

MARKETS={
 "contracts":[("ES=F","ES","S&P 500"),("NQ=F","NQ","Nasdaq 100"),("YM=F","YM","Dow Jones"),("RTY=F","RTY","Russell 2000"),("GC=F","GC","Gold"),("SI=F","SI","Silver"),("CL=F","CL","Crude Oil"),("NG=F","NG","Natural Gas")],
 "us":[("AAPL","AAPL","Apple"),("MSFT","MSFT","Microsoft"),("NVDA","NVDA","NVIDIA"),("AMZN","AMZN","Amazon"),("META","META","Meta"),("TSLA","TSLA","Tesla"),("GOOGL","GOOGL","Alphabet"),("AMD","AMD","AMD")],
 "saudi":[("2222.SR","2222","أرامكو"),("1120.SR","1120","الراجحي"),("2010.SR","2010","سابك"),("1180.SR","1180","الأهلي"),("7010.SR","7010","STC"),("1211.SR","1211","معادن"),("1150.SR","1150","الإنماء"),("2082.SR","2082","ACWA Power")],
 "forex":[("EURUSD=X","EUR/USD","اليورو دولار"),("GBPUSD=X","GBP/USD","الجنيه دولار"),("USDJPY=X","USD/JPY","الدولار ين"),("AUDUSD=X","AUD/USD","الأسترالي دولار"),("USDCAD=X","USD/CAD","الدولار كندي"),("USDCHF=X","USD/CHF","الدولار فرنك"),("GC=F","GOLD","الذهب"),("CL=F","OIL","النفط")]
}

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
with closing(conn()) as c:
    c.execute("CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE,market TEXT NOT NULL,created_at REAL)")
    c.commit()

async def get_json(url,params=None,headers=None):
    async with httpx.AsyncClient(timeout=12,headers=headers or {"User-Agent":"Mozilla/5.0"}) as x:
        r=await x.get(url,params=params); r.raise_for_status(); return r.json()

async def bn(path,params=None,base="https://api.binance.com"):
    return await get_json(base+path,params)

async def tickers():
    a=await bn("/api/v3/ticker/24hr"); out=[]
    for x in a:
        s=x.get("symbol","")
        if not s.endswith("USDT") or s in STABLE: continue
        v=float(x.get("quoteVolume",0) or 0)
        if v<MIN_VOL: continue
        out.append({"symbol":s,"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":v})
    return sorted(out,key=lambda x:x["volume24h"],reverse=True)

def stats(trades):
    total=buy=sell=large=lb=ls=0.0; n=ln=0; prices=[]
    for t in trades:
        p=float(t.get("p",0)); q=float(t.get("q",0)); usd=p*q
        total+=usd; prices.append(p); n+=1
        is_buy=not bool(t.get("m",False))
        if is_buy: buy+=usd
        else: sell+=usd
        if usd>=WHALE_USD:
            large+=usd; ln+=1
            if is_buy: lb+=usd
            else: ls+=usd
    pressure=(buy-sell)/total*100 if total else 0
    wp=(lb-ls)/large*100 if large else 0
    return total,buy,sell,pressure,large,lb,ls,wp,n,ln,prices

async def liquidity(symbol):
    trades=await bn("/api/v3/aggTrades",{"symbol":symbol,"limit":1000})
    z=stats(trades); mid=max(1,len(trades)//2); a=stats(trades[:mid]); b=stats(trades[mid:])
    move=(z[10][-1]/z[10][0]-1)*100 if len(z[10])>1 and z[10][0] else 0
    accel=(b[0]/a[0]-1)*100 if a[0] else 0
    wacc=(b[4]/a[4]-1)*100 if a[4] else (100 if b[4]>0 else 0)
    flags={"whale_activity":z[9]>=3,"buy_pressure":z[7]>=8,"liquidity_acceleration":accel>=15,"whale_acceleration":wacc>=15,"not_chasing":abs(move)<=2.5}
    score=round(sum(flags.values())*20,1)
    status="EARLY" if score>=80 and z[7]>=8 and abs(move)<=2.5 else "WATCH" if score>=60 else "QUIET"
    label={"EARLY":"إنذار مبكر","WATCH":"مراقبة حيتان","QUIET":"سيولة هادئة"}[status]
    return {"symbol":symbol,"price":z[10][-1] if z[10] else 0,"move":round(move,2),"flow":round(z[0],2),"buy_flow":round(z[1],2),"sell_flow":round(z[2],2),"pressure":round(z[3],2),"whale_flow":round(z[4],2),"whale_buy":round(z[5],2),"whale_sell":round(z[6],2),"whale_pressure":round(z[7],2),"trades":z[8],"whale_trades":z[9],"acceleration":round(accel,2),"whale_acceleration":round(wacc,2),"score":score,"status":status,"label":label,"updated_at":int(time.time())}

async def yahoo(symbols):
    async with httpx.AsyncClient(timeout=12,headers={"User-Agent":"Mozilla/5.0"}) as x:
        async def one(s,code,name):
            try:
                r=await x.get("https://query1.finance.yahoo.com/v8/finance/chart/"+s,params={"range":"1d","interval":"5m"})
                r.raise_for_status(); j=r.json()["chart"]["result"][0]; q=j["indicators"]["quote"][0]
                closes=[v for v in q.get("close",[]) if v is not None]; vols=[v for v in q.get("volume",[]) if v is not None]
                price=closes[-1] if closes else 0; first=closes[0] if closes else price
                move=(price/first-1)*100 if first else 0
                vol=sum(vols) if vols else 0
                return {"symbol":code,"name":name,"price":price,"change":move,"volume":vol,"source":"Yahoo Finance public chart"}
            except Exception as e:
                return {"symbol":code,"name":name,"error":str(e),"source":"Yahoo Finance public chart"}
        return await asyncio.gather(*[one(*v) for v in symbols])

@app.get("/health")
async def health(): return {"ok":True,"version":"5.0","service":"whale-flow-pro","time":int(time.time())}

@app.get("/api/liquidity")
async def liquidity_scan(limit:int=20):
    try:
        markets=(await tickers())[:30]; out=[]
        for m in markets:
            try:
                x=await liquidity(m["symbol"]); x.update(volume24h=m["volume24h"],change24h=m["change"]); out.append(x)
            except Exception: pass
        out.sort(key=lambda x:(x["score"],x["whale_pressure"],x["whale_flow"]),reverse=True)
        return {"items":out[:max(1,min(limit,30))],"source":"Binance spot aggTrades","whale_threshold":WHALE_USD}
    except Exception as e: return {"items":[],"error":str(e)}


# Timeframe liquidity radar: 15m and above only.
RADAR_INTERVALS=("15m","30m","1h","4h","1d","1w","1M")

async def radar_klines(symbol, interval, limit=8):
    rows=await bn("/api/v3/klines",{"symbol":symbol,"interval":interval,"limit":limit})
    if not rows: return None
    candles=[]
    for k in rows:
        quote=float(k[7] or 0)
        taker_buy=float(k[10] or 0)
        candles.append({"open":float(k[1]),"close":float(k[4]),"quote":quote,"buy":taker_buy,"sell":max(0,quote-taker_buy)})
    cur=candles[-1]
    base=candles[0]["open"] or cur["open"] or cur["close"]
    move=(cur["close"]/base-1)*100 if base else 0
    total=sum(x["quote"] for x in candles)
    buy=sum(x["buy"] for x in candles)
    sell=sum(x["sell"] for x in candles)
    pressure=(buy-sell)/total*100 if total else 0
    recent=sum(x["quote"] for x in candles[-2:])
    previous=sum(x["quote"] for x in candles[:-2])
    accel=(recent/(previous/max(1,len(candles)-2)*2)-1)*100 if previous and len(candles)>2 else 0
    return {"move":move,"volume":total,"buy":buy,"sell":sell,"pressure":pressure,"acceleration":accel,"price":cur["close"]}

async def radar_symbol(m):
    symbol=m["symbol"]
    async def one(iv):
        try:return iv,await radar_klines(symbol,iv,8 if iv!="1M" else 6)
        except Exception:return iv,None
    pairs=await asyncio.gather(*[one(iv) for iv in RADAR_INTERVALS])
    tf={k:v for k,v in pairs if v}
    if "15m" not in tf:return None
    weights={"15m":30,"30m":20,"1h":18,"4h":14,"1d":10,"1w":5,"1M":3}
    score=0
    for iv,w in weights.items():
        x=tf.get(iv)
        if not x: continue
        p=max(0,min(100,50+x["pressure"]*2))
        if x["move"]>4: p-=15
        score+=p*w/100
    x15=tf["15m"]
    first_push=x15["pressure"]>=8 and x15["acceleration"]>=5 and abs(x15["move"])<=2.5
    persistent=sum(1 for iv in ("30m","1h","4h","1d") if iv in tf and tf[iv]["pressure"]>=3)
    score=min(100,score+(12 if first_push else 0)+persistent*4)
    status="أول بول" if first_push else "تجميع" if x15["pressure"]>=5 and persistent>=2 else "تدفق إيجابي" if score>=55 else "مراقبة"
    return {"symbol":symbol,"price":x15["price"],"volume24h":m["volume24h"],"change24h":m["change"],"score":round(score,1),"status":status,"first_push":first_push,"persistent":persistent,"timeframes":tf,"updated_at":int(time.time())}

@app.get("/api/radar")
async def radar(limit:int=12):
    try:
        markets=(await tickers())[:24]
        items=[]
        for i in range(0,len(markets),6):
            batch=await asyncio.gather(*[radar_symbol(m) for m in markets[i:i+6]])
            items.extend(x for x in batch if x)
        items.sort(key=lambda x:(x["first_push"],x["score"],x["timeframes"]["15m"]["pressure"]),reverse=True)
        return {"items":items[:max(1,min(limit,20))],"intervals":RADAR_INTERVALS,"source":"Binance Spot Klines","note":"الرادار يبدأ من 15 دقيقة ولا يستخدم بيانات لحظية."}
    except Exception as e:
        return {"items":[],"intervals":RADAR_INTERVALS,"error":str(e)}


async def yahoo_radar(symbols):
    async with httpx.AsyncClient(timeout=15,headers={"User-Agent":"Mozilla/5.0"}) as x:
        async def one(s,code,name):
            try:
                r=await x.get("https://query1.finance.yahoo.com/v8/finance/chart/"+s,params={"range":"1mo","interval":"1h"})
                r.raise_for_status()
                j=r.json()["chart"]["result"][0]; q=j["indicators"]["quote"][0]
                closes=[v for v in q.get("close",[]) if v is not None]
                vols=[v for v in q.get("volume",[]) if v is not None]
                if not closes:return None
                def calc(n):
                    vv=vols[-n:] if len(vols)>=n else vols
                    cc=closes[-n:] if len(closes)>=n else closes
                    volume=sum(vv) if vv else 0
                    half=max(1,len(vv)//2)
                    a=sum(vv[:half]) if vv else 0; b=sum(vv[half:]) if vv else 0
                    pressure=((cc[-1]/cc[0]-1)*100) if len(cc)>1 and cc[0] else 0
                    accel=((b/max(a,1))-1)*100 if a else 0
                    return {"volume":volume,"pressure":pressure,"acceleration":accel,"price":cc[-1]}
                # 1h native, 4h/1d/1w/1M derived from the 1h history.
                out={"1h":calc(1),"4h":calc(4),"1d":calc(24),"1w":calc(24*7),"1M":calc(min(24*30,len(closes)))}
                out["15m"]=None; out["30m"]=None
                score=0
                for iv,w in (("1h",25),("4h",25),("1d",25),("1w",15),("1M",10)):
                    z=out[iv]; score+=max(0,min(100,50+z["pressure"]*3))*w/100
                early=out["1h"]["acceleration"]>=20 and out["1h"]["pressure"]>0 and abs(out["1h"]["pressure"])<=3
                status="أول بول" if early else "تدفق إيجابي" if score>=58 else "مراقبة"
                return {"symbol":code,"name":name,"price":out["1h"]["price"],"change24h":out["1d"]["pressure"],"volume":out["1d"]["volume"],"score":round(score,1),"status":status,"first_push":early,"timeframes":out,"flow_type":"حجم/سعر","source":"Yahoo Finance public chart"}
            except Exception:return None
        return [z for z in await asyncio.gather(*[one(*v) for v in symbols]) if z]

async def market_radar(market):
    if market=="spot":
        d=await radar(12)
        return d
    if market=="futures":
        a=await bn("/fapi/v1/ticker/24hr")
        syms=[(x["symbol"],x["symbol"],x["symbol"]) for x in a if x["symbol"].endswith("USDT") and float(x.get("quoteVolume",0))>=MIN_VOL][:24]
        # Use Binance futures klines directly.
        async def one(m):
            symbol=m[0]
            async def iv(x):
                try:return x,await get_json("https://fapi.binance.com/fapi/v1/klines",{"symbol":symbol,"interval":x,"limit":8})
                except Exception:return x,None
            ps=await asyncio.gather(*[iv(x) for x in RADAR_INTERVALS])
            tf={}
            for ivv,rows in ps:
                if not rows:continue
                qs=[float(k[7]) for k in rows]; buy=[float(k[10]) for k in rows]
                total=sum(qs); b=sum(buy); pressure=((b-(total-b))/total*100) if total else 0
                tf[ivv]={"volume":total,"buy":b,"sell":max(0,total-b),"pressure":pressure,"acceleration":0,"price":float(rows[-1][4])}
            if "15m" not in tf:return None
            score=sum(max(0,min(100,50+tf[i]["pressure"]*2))*w/100 for i,w in {"15m":30,"30m":20,"1h":18,"4h":14,"1d":10,"1w":5,"1M":3}.items() if i in tf)
            early=tf["15m"]["pressure"]>=8 and abs((tf["15m"]["price"]/float(rows[0][1])-1)*100)<=2.5
            return {"symbol":symbol,"price":tf["15m"]["price"],"change24h":0,"volume":tf["1d"]["volume"] if "1d" in tf else 0,"score":round(score,1),"status":"أول بول" if early else "تدفق إيجابي" if score>=55 else "مراقبة","first_push":early,"timeframes":tf,"flow_type":"Taker Buy/Sell","source":"Binance Futures"}
        out=await asyncio.gather(*[one(m) for m in syms])
        return {"items":sorted([x for x in out if x],key=lambda x:(x["first_push"],x["score"]),reverse=True)[:12],"intervals":RADAR_INTERVALS,"source":"Binance Futures Klines"}
    if market in MARKETS:
        return {"items":sorted(await yahoo_radar(MARKETS[market]),key=lambda x:(x["first_push"],x["score"]),reverse=True)[:12],"intervals":RADAR_INTERVALS,"source":"Yahoo Finance public chart","note":"للأسهم والعقود والفوركس لا تتوفر بيانات Taker Buy/Sell عامة؛ المعروض مؤشر حجم/سعر وليس تدفق أوامر مؤكد."}
    raise HTTPException(404,"market not found")

@app.get("/api/radar-market/{market}")
async def radar_market(market:str):
    try:return await market_radar(market)
    except Exception as e:return {"items":[],"intervals":RADAR_INTERVALS,"error":str(e)}

@app.get("/api/radar/{symbol}")
async def radar_one(symbol:str):
    m={"symbol":symbol.upper(),"volume24h":0,"change":0}
    try:
        for x in await tickers():
            if x["symbol"]==symbol.upper(): m=x; break
        r=await radar_symbol(m)
        return r or {"error":"لا توجد بيانات كافية"}
    except Exception as e:return {"error":str(e)}

@app.get("/api/liquidity/{symbol}")
async def liquidity_one(symbol:str):
    try: return await liquidity(symbol.upper())
    except Exception as e: return {"error":str(e)}

@app.get("/api/markets")
async def markets(limit:int=80):
    try: return {"items":(await tickers())[:max(1,min(limit,100))],"source":"Binance Spot 24h"}
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/futures")
async def futures():
    try:
        a=await bn("/fapi/v1/ticker/24hr")
        out=[{"symbol":x["symbol"],"price":float(x["lastPrice"]),"change":float(x["priceChangePercent"]),"volume24h":float(x.get("quoteVolume",0))} for x in a if x["symbol"].endswith("USDT") and x["symbol"] not in STABLE and float(x.get("quoteVolume",0))>=MIN_VOL]
        return {"items":sorted(out,key=lambda x:x["volume24h"],reverse=True)[:100],"source":"Binance Futures"}
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/{market}")
async def other_market(market:str):
    if market not in MARKETS: raise HTTPException(404,"market not found")
    items=await yahoo(MARKETS[market])
    return {"market":market,"items":items,"source":"Yahoo Finance public chart","note":"البيانات العامة لا توفر صفقات حيتان حقيقية؛ يتم عرض السعر والحجم فقط."}

@app.get("/api/tracker")
async def tracker():
    with closing(conn()) as c:return {"items":[dict(x) for x in c.execute("SELECT * FROM watchlist ORDER BY id DESC").fetchall()]}

@app.post("/api/tracker/{market}/{symbol}")
async def add_tracker(market:str,symbol:str):
    with closing(conn()) as c:
        c.execute("INSERT OR IGNORE INTO watchlist(symbol,market,created_at) VALUES(?,?,?)",(symbol.upper(),market,time.time())); c.commit()
    return {"ok":True}

@app.delete("/api/tracker/{market}/{symbol}")
async def del_tracker(market:str,symbol:str):
    with closing(conn()) as c:
        c.execute("DELETE FROM watchlist WHERE symbol=? AND market=?",(symbol.upper(),market)); c.commit()
    return {"ok":True}

@app.get("/api/platform/summary")
async def summary():
    try:
        a=(await liquidity_scan(10))["items"]
        return {"early":sum(x["status"]=="EARLY" for x in a),"watch":sum(x["status"]=="WATCH" for x in a),"tracked":len(a),"min_volume":MIN_VOL,"whale_threshold":WHALE_USD}
    except Exception:return {"early":0,"watch":0,"tracked":0}

@app.get("/api/news")
async def news(): return {"items":[],"message":"مصدر الأخبار غير مفعّل حتى لا نعرض أخبار وهمية."}
@app.get("/api/blog")
async def blog(): return {"items":[],"message":"قسم المقالات جاهز للنشر."}
@app.get("/api/auth/me")
async def me(): return {"authenticated":False,"user":None,"message":"تسجيل الحساب يحتاج مزود هوية قبل تفعيله."}

@app.get("/")
async def root(): return FileResponse(STATIC/"index.html")
@app.get("/{path:path}")
async def files(path:str):
    p=STATIC/path
    return FileResponse(p if p.is_file() else STATIC/"index.html")

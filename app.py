import os,time,sqlite3,asyncio,json
from pathlib import Path
from contextlib import closing
import httpx
import websockets
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

app=FastAPI(title="Whale Flow PRO",version="5.2")
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
    # Keep existing persistent databases compatible with the newer tracker schema.
    c.execute("CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,symbol TEXT UNIQUE,market TEXT,created_at REAL)")
    cols={row[1] for row in c.execute("PRAGMA table_info(watchlist)").fetchall()}
    if "market" not in cols:
        c.execute("ALTER TABLE watchlist ADD COLUMN market TEXT")
    if "created_at" not in cols:
        c.execute("ALTER TABLE watchlist ADD COLUMN created_at REAL")
    # Old rows may predate the market column; default them to spot so they remain visible.
    c.execute("UPDATE watchlist SET market='spot' WHERE market IS NULL OR market=''")
    c.execute("CREATE TABLE IF NOT EXISTS radar_cache(market TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at REAL NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS radar_history(id INTEGER PRIMARY KEY,market TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL)")
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
async def health(): return {"ok":True,"version":"5.2","service":"whale-flow-pro","time":int(time.time())}

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
RADAR_CACHE_TTL=900
RADAR_HISTORY_TTL=604800

def radar_cached(market):
    now=time.time()
    with closing(conn()) as c:
        row=c.execute("SELECT payload,updated_at FROM radar_cache WHERE market=?",(market,)).fetchone()
        if not row or now-float(row["updated_at"])>=RADAR_CACHE_TTL:return None
        try:return json.loads(row["payload"])
        except Exception:return None

def radar_store(market,payload):
    now=time.time(); raw=json.dumps(payload,ensure_ascii=False,separators=(",",":"))
    with closing(conn()) as c:
        c.execute("INSERT INTO radar_cache(market,payload,updated_at) VALUES(?,?,?) ON CONFLICT(market) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",(market,raw,now))
        c.execute("INSERT INTO radar_history(market,payload,created_at) VALUES(?,?,?)",(market,raw,now))
        c.execute("DELETE FROM radar_history WHERE created_at<?",(now-RADAR_HISTORY_TTL,))
        c.commit()

async def cached_radar(market,builder):
    cached=radar_cached(market)
    if cached:
        cached["cached"]=True
        cached["next_refresh_in"]=max(0,int(RADAR_CACHE_TTL-(time.time()-cached.get("cache_updated_at",time.time()))))
        return cached
    payload=await builder(); payload["cached"]=False; payload["cache_updated_at"]=int(time.time()); payload["next_refresh_in"]=RADAR_CACHE_TTL
    radar_store(market,payload)
    return payload

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

async def liquidity_destinations(limit:int=12):
    markets=await tickers()
    # BTC is a reference flow gauge, not the destination. Compare BTC pressure with the rest of the liquid market.
    btc=next((m for m in markets if m["symbol"]=="BTCUSDT"),None)
    btc15=await radar_klines("BTCUSDT","15m",8) if btc else None
    btc_pressure=float(btc15["pressure"]) if btc15 else 0.0
    btc_move=float(btc15["move"]) if btc15 else 0.0
    candidates=[m for m in markets if m["symbol"]!="BTCUSDT"][:40]
    async def one(m):
        try:
            z=await radar_klines(m["symbol"],"15m",8)
            if not z:return None
            # Destination score: positive when alt liquidity strengthens while BTC flow weakens/flatlines.
            pressure=float(z["pressure"])
            relative=pressure-btc_pressure
            acceleration=float(z["acceleration"])
            score=max(0,min(100,50+relative*3+acceleration*0.25))
            incoming=relative>=2 and pressure>0
            outgoing=relative<=-2 and pressure<0
            return {"symbol":m["symbol"],"price":z["price"],"volume24h":m["volume24h"],"change24h":m["change"],"pressure15m":pressure,"relative_to_btc":relative,"acceleration":acceleration,"score":round(score,1),"direction":"دخول السيولة" if incoming else "خروج السيولة" if outgoing else "مراقبة","destination":incoming,"btc_pressure15m":btc_pressure,"btc_move15m":btc_move}
        except Exception:return None
    out=[]
    for i in range(0,len(candidates),10):
        out.extend(x for x in await asyncio.gather(*[one(m) for m in candidates[i:i+10]]) if x)
    incoming=sorted([x for x in out if x["destination"]],key=lambda x:(x["score"],x["relative_to_btc"]),reverse=True)
    return {"items":incoming[:max(1,min(limit,20))],"btc_reference":{"pressure15m":btc_pressure,"move15m":btc_move},"total_scanned":len(out),"source":"Binance Spot 15m liquidity rotation"}

LIVE_FLOW={}
LIVE_FLOW_LOCK=asyncio.Lock()
LIVE_FLOW_STARTED=False

async def _live_aggtrade_worker(symbols):
    global LIVE_FLOW_STARTED
    streams="/".join(s.lower()+"@aggTrade" for s in symbols[:200])
    url="wss://stream.binance.com:9443/stream?streams="+streams
    while True:
        try:
            async with websockets.connect(url,ping_interval=120,ping_timeout=30,max_size=2**20) as ws:
                async for raw in ws:
                    try:
                        e=json.loads(raw).get("data",{})
                        s=e.get("s",""); p=float(e.get("p",0) or 0); q=float(e.get("q",0) or 0); usd=p*q
                        if not s or usd<=0: continue
                        async with LIVE_FLOW_LOCK:
                            z=LIVE_FLOW.setdefault(s,{"buy":0.0,"sell":0.0,"whale_buy":0.0,"whale_sell":0.0,"trades":0,"whales":0,"last":0})
                            is_buy=not bool(e.get("m",False))
                            key="buy" if is_buy else "sell"; wk="whale_buy" if is_buy else "whale_sell"
                            z[key]+=usd; z["trades"]+=1; z["last"]=time.time()
                            if usd>=WHALE_USD: z[wk]+=usd; z["whales"]+=1
                            # keep only the latest rolling flow window in memory
                            if z["trades"]>5000:
                                z["buy"]*=0.5; z["sell"]*=0.5; z["whale_buy"]*=0.5; z["whale_sell"]*=0.5; z["trades"]=2500; z["whales"]=max(0,int(z["whales"]*.5))
                    except Exception:
                        continue
        except Exception:
            await asyncio.sleep(2)

async def start_live_flow():
    global LIVE_FLOW_STARTED
    if LIVE_FLOW_STARTED:return
    LIVE_FLOW_STARTED=True
    try:
        ms=await tickers()
        symbols=[x["symbol"] for x in ms[:200]]
        asyncio.create_task(_live_aggtrade_worker(symbols))
    except Exception:
        LIVE_FLOW_STARTED=False

@app.on_event("startup")
async def _start_live_flow():
    await start_live_flow()

@app.get("/api/live-flow")
async def live_flow(limit:int=12):
    await start_live_flow()
    async with LIVE_FLOW_LOCK:
        rows=[]
        for s,z in LIVE_FLOW.items():
            total=z["buy"]+z["sell"]; pressure=(z["buy"]-z["sell"])/total*100 if total else 0
            whale_total=z["whale_buy"]+z["whale_sell"]; whale_pressure=(z["whale_buy"]-z["whale_sell"])/whale_total*100 if whale_total else 0
            if total<=0:continue
            rows.append({"symbol":s,"flow":round(total,2),"buy_flow":round(z["buy"],2),"sell_flow":round(z["sell"],2),"pressure":round(pressure,2),"whale_flow":round(whale_total,2),"whale_pressure":round(whale_pressure,2),"whales":z["whales"],"last":z["last"]})
    rows.sort(key=lambda x:(x["whale_flow"],x["pressure"],x["flow"]),reverse=True)
    return {"items":rows[:max(1,min(limit,30))],"live":True,"window":"rolling_live","source":"Binance aggTrade WebSocket"}

@app.get("/api/flow-destinations")
async def flow_destinations(limit:int=12):
    try:return await liquidity_destinations(limit)
    except Exception as e:return {"items":[],"error":str(e)}

@app.get("/api/radar")
async def radar(limit:int=12):
    try:
        # Scan every Spot USDT pair with 24h quote volume >= $1M.
        # Use 15m as the first-pass for all coins, then calculate 30m+ on the strongest 80
        # to keep the service inside Binance rate limits while still covering the full universe.
        markets=await tickers()
        async def first_pass(m):
            try:
                x=await radar_klines(m["symbol"],"15m",8)
                if not x:return None
                first=x["pressure"]>=8 and x["acceleration"]>=5 and abs(x["move"])<=2.5
                score=max(0,min(100,50+x["pressure"]*2))
                return {"symbol":m["symbol"],"price":x["price"],"volume24h":m["volume24h"],"change24h":m["change"],
                        "score":round(score,1),"status":"أول بول" if first else "مراقبة","first_push":first,
                        "persistent":0,"timeframes":{"15m":x},"updated_at":int(time.time())}
            except Exception:return None
        items=[]
        for i in range(0,len(markets),12):
            batch=await asyncio.gather(*[first_pass(m) for m in markets[i:i+12]])
            items.extend(x for x in batch if x)
        items.sort(key=lambda x:(x["first_push"],x["score"],x["timeframes"]["15m"]["pressure"]),reverse=True)
        deep=items[:80]
        by_symbol={m["symbol"]:m for m in markets}
        async def deep_one(x):
            m=by_symbol.get(x["symbol"])
            if not m:return x
            y=await radar_symbol(m)
            return y or x
        for i in range(0,len(deep),8):
            batch=await asyncio.gather(*[deep_one(x) for x in deep[i:i+8]])
            for j,y in enumerate(batch):
                deep[i+j]=y
        deep_by={x["symbol"]:x for x in deep}
        final=[deep_by.get(x["symbol"],x) for x in items]
        final.sort(key=lambda x:(x["first_push"],x["score"],x["timeframes"]["15m"]["pressure"]),reverse=True)
        # Diversify the radar so one mega-cap such as BTC does not permanently occupy the whole feed.
        # Keep the strongest candidates first, but rotate the tail inside the current 15m candle bucket.
        n=max(1,min(limit,100))
        bucket=int(time.time()//900)
        ranked=final[:]
        if len(ranked)>n:
            head=ranked[:min(3,n)]
            pool=ranked[min(3,n):]
            if pool:
                shift=(bucket*7)%len(pool)
                pool=pool[shift:]+pool[:shift]
            ranked=(head+pool)[:n]
        else:
            ranked=ranked[:n]
        return {"items":ranked,"total_pairs_scanned":len(markets),"min_volume_24h":MIN_VOL,
                "intervals":RADAR_INTERVALS,"source":"Binance Spot Klines","note":"تم فحص كل أزواج USDT فوق $1M يومياً؛ 15د لكل العملات ثم تحليل أعمق لأقوى 80."}
    except Exception as e:
        return {"items":[],"intervals":RADAR_INTERVALS,"total_pairs_scanned":0,"error":str(e)}


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
                out={"1h":calc(8),"4h":calc(4),"1d":calc(24),"1w":calc(24*7),"1M":calc(min(24*30,len(closes)))}
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
        return await radar(12)
    if market=="futures":
        async def build():
            a=await bn("/fapi/v1/ticker/24hr")
            syms=[(x["symbol"],x["symbol"],x["symbol"]) for x in a if x["symbol"].endswith("USDT") and float(x.get("quoteVolume",0))>=MIN_VOL][:24]
            async def one(m):
                symbol=m[0]
                async def iv(x):
                    try:return x,await get_json("https://fapi.binance.com/fapi/v1/klines",{"symbol":symbol,"interval":x,"limit":8})
                    except Exception:return x,None
                ps=await asyncio.gather(*[iv(x) for x in RADAR_INTERVALS]); tf={}; raw15=None
                for ivv,rows in ps:
                    if not rows:continue
                    if ivv=="15m":raw15=rows
                    qs=[float(k[7]) for k in rows]; buy=[float(k[10]) for k in rows]
                    total=sum(qs); bb=sum(buy); pressure=((bb-(total-bb))/total*100) if total else 0
                    tf[ivv]={"volume":total,"buy":bb,"sell":max(0,total-bb),"pressure":pressure,"acceleration":0,"price":float(rows[-1][4])}
                if "15m" not in tf:return None
                score=sum(max(0,min(100,50+tf[i]["pressure"]*2))*w/100 for i,w in {"15m":30,"30m":20,"1h":18,"4h":14,"1d":10,"1w":5,"1M":3}.items() if i in tf)
                early=tf["15m"]["pressure"]>=8 and raw15 and abs((tf["15m"]["price"]/float(raw15[0][1])-1)*100)<=2.5
                return {"symbol":symbol,"price":tf["15m"]["price"],"change24h":0,"volume":tf["1d"]["volume"] if "1d" in tf else 0,"score":round(score,1),"status":"أول بول" if early else "تدفق إيجابي" if score>=55 else "مراقبة","first_push":bool(early),"timeframes":tf,"flow_type":"Taker Buy/Sell","source":"Binance Futures"}
            out=await asyncio.gather(*[one(m) for m in syms])
            return {"items":sorted([x for x in out if x],key=lambda x:(x["first_push"],x["score"]),reverse=True)[:12],"intervals":RADAR_INTERVALS,"source":"Binance Futures Klines"}
        return await cached_radar("futures",build)
    if market in MARKETS:
        async def build():
            return {"items":sorted(await yahoo_radar(MARKETS[market]),key=lambda x:(x["first_push"],x["score"]),reverse=True)[:12],"intervals":RADAR_INTERVALS,"source":"Yahoo Finance public chart","note":"للأسهم والعقود والفوركس لا تتوفر بيانات Taker Buy/Sell عامة؛ المعروض مؤشر حجم/سعر وليس تدفق أوامر مؤكد."}
        return await cached_radar(market,build)
    raise HTTPException(404,"market not found")

@app.get("/api/radar-market/{market}")
async def radar_market(market:str):
    try:return await market_radar(market)
    except Exception as e:return {"items":[],"intervals":RADAR_INTERVALS,"error":str(e)}

# Convert strong liquidity flow into a visible trade idea.
# Spot is BUY-only; futures/contracts/forex may generate BUY or SELL.
def make_signal(x,market):
    tf=x.get("timeframes") or {}
    q=tf.get("15m") or tf.get("1h") or {}
    pressure=float(q.get("pressure",0) or 0)
    score=float(x.get("score",0) or 0)
    early=bool(x.get("first_push"))
    if market=="spot":
        side="BUY" if pressure>=2 and (early or score>=52) else None
    else:
        side="BUY" if pressure>=1 and (early or score>=51) else "SELL" if pressure<=-1 and score<=49 else None
    if not side:return None
    price=float(x.get("price",0) or q.get("price",0) or 0)
    if price<=0:return None
    risk=0.01
    if side=="BUY":
        sl=price*(1-risk); tp1=price*(1+risk); tp2=price*(1+2*risk); tp3=price*(1+3*risk)
    else:
        sl=price*(1+risk); tp1=price*(1-risk); tp2=price*(1-2*risk); tp3=price*(1-3*risk)
    confidence=min(99,round(max(50,score)+(8 if early else 0),1))
    return {
        "signal":side,"direction":"شراء" if side=="BUY" else "بيع",
        "entry":price,"tp1":tp1,"tp2":tp2,"tp3":tp3,"sl":sl,
        "confidence":confidence,"flow_pressure":pressure,
        "flow_label":"دخول السيولة" if side=="BUY" else "خروج/ضغط بيعي",
        "signal_tf":"15m","generated_at":int(time.time())
    }

@app.get("/api/signals/{market}")
async def signals_market(market:str):
    try:
        data=await market_radar(market)
        items=[]
        for x in data.get("items",[]):
            s=make_signal(x,market)
            if s:
                y=dict(x); y["trade"]=s; items.append(y)
        items.sort(key=lambda x:(x["trade"]["confidence"],abs(x["trade"]["flow_pressure"])),reverse=True)
        return {
            "items":items[:20],
            "market":market,
            "interval":"15m",
            "generated_from":"liquidity",
            "note":"الصفقات تتولد تلقائياً من ضغط السيولة؛ ليست أوامر تنفيذ حقيقية."
        }
    except Exception as e:
        return {"items":[],"market":market,"error":str(e)}

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

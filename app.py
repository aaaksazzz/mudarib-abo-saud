import os,time,json,hmac,hashlib,urllib.parse,urllib.request,threading
from decimal import Decimal,ROUND_DOWN
from fastapi import FastAPI,HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app=FastAPI(title="Binance Futures Bot")
KEY=os.getenv("BINANCE_API_KEY","");SECRET=os.getenv("BINANCE_API_SECRET","")
LIVE=os.getenv("BINANCE_LIVE","false").lower()=="true";TEST=os.getenv("BINANCE_TESTNET","true").lower()=="true"
BASE="https://testnet.binancefuture.com" if TEST else "https://fapi.binance.com"
SCAN=int(os.getenv("SCAN_SECONDS","60"));USD=Decimal(os.getenv("USD_PER_TRADE","10"));TP=Decimal("0.01")
STATE_FILE=os.getenv("BOT_STATE_FILE","bot_state.json");STATE={"running":False,"last_scan":0,"positions":{},"trades":[]};THREAD=None

class Settings(BaseModel):
    api_key:str
    api_secret:str
    live:bool=False
    testnet:bool=True

def save():
    with open(STATE_FILE+".tmp","w",encoding="utf-8") as f:json.dump(STATE,f,ensure_ascii=False)
    os.replace(STATE_FILE+".tmp",STATE_FILE)
def load():
    global STATE
    try:
        with open(STATE_FILE,encoding="utf-8") as f:STATE.update(json.load(f))
    except Exception:pass
    STATE.setdefault("positions",{});STATE.setdefault("trades",[])

def public(path,p=None):
    q=urllib.parse.urlencode(p or {})
    req=urllib.request.Request(BASE+path+(("?"+q) if q else ""),headers={"User-Agent":"mudarib-bot"})
    with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read())

def signed(method,path,p=None):
    if not KEY or not SECRET:raise RuntimeError("Binance API credentials missing")
    p=dict(p or {});p["timestamp"]=int(time.time()*1000);p["recvWindow"]=10000
    q=urllib.parse.urlencode(p);sig=hmac.new(SECRET.encode(),q.encode(),hashlib.sha256).hexdigest()
    req=urllib.request.Request(BASE+path+"?"+q+"&signature="+sig,method=method,headers={"X-MBX-APIKEY":KEY})
    with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read())

def ema(v,n):
    if len(v)<n:return None
    e=sum(v[:n])/Decimal(n);k=Decimal(2)/Decimal(n+1)
    for x in v[n:]:e=x*k+e*(1-k)
    return e
def rsi(v,n=14):
    if len(v)<=n:return Decimal(50)
    g=[max(v[i]-v[i-1],Decimal(0)) for i in range(1,len(v))];l=[max(v[i-1]-v[i],Decimal(0)) for i in range(1,len(v))]
    ag=sum(g[:n])/Decimal(n);al=sum(l[:n])/Decimal(n)
    for i in range(n,len(g)):ag=(ag*(n-1)+g[i])/Decimal(n);al=(al*(n-1)+l[i])/Decimal(n)
    return Decimal(100) if al==0 else Decimal(100)-Decimal(100)/(1+ag/al)
def klines(s,i,n=300):
    x=public("/fapi/v1/klines",{"symbol":s,"interval":i,"limit":n});return x[:-1]
def info():
    out={}
    for s in public("/fapi/v1/exchangeInfo")["symbols"]:
        if s.get("status")=="TRADING" and s.get("quoteAsset")=="USDT" and s.get("contractType")=="PERPETUAL":
            f=next((x for x in s["filters"] if x["filterType"]=="LOT_SIZE"),{})
            out[s["symbol"]]=(Decimal(f.get("stepSize","1")),Decimal(f.get("minQty","0")))
    return out
def setup(s):
    a,b=klines(s,"15m"),klines(s,"1h")
    if len(a)<220 or len(b)<220:return None
    c=[Decimal(str(x[4])) for x in a];v=[Decimal(str(x[7])) for x in a];h=[Decimal(str(x[4])) for x in b]
    p=c[-1];avg=sum(v[-21:-1])/Decimal(20)
    if h[-1]<ema(h,200) and p<ema(c,20) and rsi(c)<50 and p<ema(c,200) and v[-1]>avg:return p
def market(s,side,q):
    if LIVE:signed("POST","/fapi/v1/order",{"symbol":s,"side":side,"type":"MARKET","quantity":str(q)})
def take_profit(s,p):
    if LIVE:signed("POST","/fapi/v1/order",{"symbol":s,"side":"SELL","type":"TAKE_PROFIT_MARKET","stopPrice":str(p),"closePosition":"true","workingType":"MARK_PRICE","priceProtect":"TRUE"})
def adopt():
    if not LIVE or not KEY or not SECRET:return
    try:
        for p in signed("GET","/fapi/v2/positionRisk"):
            s=p.get("symbol");q=Decimal(str(p.get("positionAmt","0")))
            if not s or q<=0 or s in STATE["positions"]:continue
            e=Decimal(str(p.get("entryPrice","0")));tp=e*(1+TP);take_profit(s,tp)
            STATE["positions"][s]={"symbol":s,"position":"LONG","original":"MANUAL","qty":str(q),"entry":str(e),"tp":str(tp)}
        save()
    except Exception as e:print("ADOPT_ERROR",e,flush=True)
def scan():
    inf=info();c=[]
    for t in public("/fapi/v1/ticker/24hr"):
        s=t["symbol"]
        if s not in inf or Decimal(str(t.get("quoteVolume","0")))<1000000 or s in STATE["positions"]:continue
        try:
            p=setup(s)
            if p:
                x=klines(s,"15m",3);ch=(Decimal(str(x[-1][4]))-Decimal(str(x[-2][4])))/Decimal(str(x[-2][4]))*100;c.append((ch,s,p))
        except Exception as e:print("SCAN_ERROR",s,e,flush=True)
    c.sort(reverse=True)
    if c:
        _,s,p=c[0];step,mn=inf[s];q=(USD/p/step).to_integral_value(rounding=ROUND_DOWN)*step
        if q>=mn and q>0:
            market(s,"BUY",q);tp=p*(1+TP);take_profit(s,tp);STATE["positions"][s]={"symbol":s,"position":"LONG","original":"BOT","qty":str(q),"entry":str(p),"tp":str(tp)};STATE["trades"].append(STATE["positions"][s].copy())
    STATE["last_scan"]=int(time.time());save()
def loop():
    load();STATE["running"]=True;save()
    while True:
        try:adopt();scan()
        except Exception as e:print("BOT_ERROR",e,flush=True)
        time.sleep(SCAN)
@app.on_event("startup")
def startup():
    global THREAD
    if not THREAD or not THREAD.is_alive():THREAD=threading.Thread(target=loop,daemon=True);THREAD.start()

@app.get("/health")
def health():return {"ok":True,"bot":"running","live":LIVE,"testnet":TEST}
@app.get("/status")
def status():return {"running":STATE["running"],"live":LIVE,"testnet":TEST,"last_scan":STATE["last_scan"],"positions":STATE["positions"]}
@app.post("/api/binance/settings")
def settings(x:Settings):
    global KEY,SECRET,LIVE,TEST,BASE
    old=(KEY,SECRET,LIVE,TEST,BASE);KEY=x.api_key.strip();SECRET=x.api_secret.strip();LIVE=x.live;TEST=x.testnet;BASE="https://testnet.binancefuture.com" if TEST else "https://fapi.binance.com"
    try:signed("GET","/fapi/v2/account")
    except Exception:
        KEY,SECRET,LIVE,TEST,BASE=old;raise HTTPException(400,"بيانات Binance غير صحيحة أو الاتصال فشل")
    return {"ok":True,"message":"تم الاتصال بـ Binance","live":LIVE,"testnet":TEST}

@app.get("/bot",response_class=HTMLResponse)
def bot():
    return HTMLResponse("""<!doctype html><html lang="ar" dir="rtl"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font-family:Arial;background:#111;color:#fff;max-width:600px;margin:auto;padding:20px}.c{background:#1c1c1c;padding:18px;border-radius:14px;margin:12px 0}input,button{width:100%;padding:13px;margin:6px 0;box-sizing:border-box;border-radius:9px}input{background:#222;color:#fff}button{background:#f0b90b;border:0;font-weight:bold}</style><h1>🤖 قسم البوت</h1><div class="c">الحالة: <b id="s">...</b><br><small>يبدأ تلقائياً مع تشغيل السيرفر</small></div><div class="c"><input id="k" placeholder="Binance API Key"><input id="z" type="password" placeholder="Binance API Secret"><label><input id="l" type="checkbox" style="width:auto"> Live حقيقي</label><label><input id="n" type="checkbox" checked style="width:auto"> Testnet</label><button onclick="go()">🔗 اختبار اتصال Binance</button><p id="m"></p></div><script>async function st(){let x=await(await fetch('/status')).json();s.textContent=x.running?'🟢 البوت يعمل':'🔴 متوقف'}async function go(){m.textContent='جاري الاختبار...';let r=await fetch('/api/binance/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:k.value,api_secret:z.value,live:l.checked,testnet:n.checked})});let x=await r.json();m.textContent=x.message||x.detail||'تم'}st();setInterval(st,5000)</script></html>""")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8080)

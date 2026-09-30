import os, json, time, urllib.parse, urllib.request, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="رادار الحركة المبكرة")
CACHE, LOCK = {}, threading.Lock()
TTL = int(os.getenv("RADAR_CACHE_TTL", "45"))
INTERNAL_TFS = ("15m", "1h", "4h")

YAHOO_SYMBOLS = {
 "american":["NVDA","AMD","TSLA","AAPL","MSFT","AMZN","META","GOOGL","AVGO","NFLX","PLTR","MSTR","SMCI","MU","QCOM","ARM","COIN","HOOD","SHOP","CRWD","ORCL","CRM","UBER","JPM","BAC"],
 "saudi":["2222.SR","1120.SR","2010.SR","7010.SR","7020.SR","1211.SR","1180.SR","1150.SR","1060.SR","4030.SR","2380.SR","4200.SR","2280.SR","2080.SR","2050.SR","3050.SR","4001.SR","4003.SR","4007.SR","4013.SR","5110.SR","7200.SR","7202.SR","7203.SR","7204.SR"],
 "forex":["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X","USDCAD=X","AUDUSD=X","NZDUSD=X","EURGBP=X","EURJPY=X","GBPJPY=X","GC=F","SI=F","CL=F","BZ=F","HG=F"]
}

def cached_json(url, ttl=TTL):
    now=time.time()
    with LOCK:
        h=CACHE.get(url)
        if h and now-h[0]<ttl:return h[1]
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 EarlyRadar/1.0"})
    with urllib.request.urlopen(req,timeout=12) as r:d=json.loads(r.read().decode())
    with LOCK:CACHE[url]=(now,d)
    return d

def ema(v,n):
    if not v:return 0.0
    if len(v)<n:return sum(v)/len(v)
    k=2/(n+1);e=sum(v[:n])/n
    for x in v[n:]:e=x*k+e*(1-k)
    return e

def pct(a,b):return ((a/b)-1)*100 if b else 0.0

def yahoo(symbol,interval):
    u="https://query1.finance.yahoo.com/v8/finance/chart/"+urllib.parse.quote(symbol)+"?"+urllib.parse.urlencode({"interval":interval,"range":{"15m":"60d","1h":"2y","4h":"2y"}[interval]})
    j=cached_json(u);r=(j.get("chart",{}).get("result") or [None])[0]
    if not r:return []
    q=(r.get("indicators",{}).get("quote") or [{}])[0];cl=q.get("close") or [];vo=q.get("volume") or []
    return [(float(x),float(vo[i] or 0) if i<len(vo) else 0.0) for i,x in enumerate(cl) if x is not None]

def binance_klines(symbol,market,interval):
    base="https://api.binance.com" if market=="spot" else ("https://fapi.binance.com" if market=="futures" else "https://dapi.binance.com")
    path="/api/v3/klines" if market=="spot" else ("/fapi/v1/klines" if market=="futures" else "/dapi/v1/klines")
    j=cached_json(base+path+"?"+urllib.parse.urlencode({"symbol":symbol,"interval":interval,"limit":220}))
    return [(float(x[4]),float(x[7])) for x in j[:-1]]

def binance_universe(market):
    base="https://api.binance.com" if market=="spot" else ("https://fapi.binance.com" if market=="futures" else "https://dapi.binance.com")
    ip="/api/v3/exchangeInfo" if market=="spot" else ("/fapi/v1/exchangeInfo" if market=="futures" else "/dapi/v1/exchangeInfo")
    tp="/api/v3/ticker/24hr" if market=="spot" else ("/fapi/v1/ticker/24hr" if market=="futures" else "/dapi/v1/ticker/24hr")
    allowed=set()
    for x in cached_json(base+ip).get("symbols",[]):
        if x.get("status")!="TRADING":continue
        if market=="contracts":
            if x.get("contractType")!="PERPETUAL":continue
        elif x.get("quoteAsset")!="USDT":continue
        allowed.add(x.get("symbol"))
    rows=[]
    for x in cached_json(base+tp):
        if x.get("symbol") in allowed:
            try:rows.append((x["symbol"],float(x.get("quoteVolume") or 0)))
            except:pass
    rows.sort(key=lambda x:x[1],reverse=True)
    return [x[0] for x in rows[:35]]

def score_asset(symbol,market):
    s={}
    for tf in INTERNAL_TFS:
        try:s[tf]=binance_klines(symbol,market,tf) if market in ("spot","futures","contracts") else yahoo(symbol,tf)
        except:s[tf]=[]
    c=s["15m"]
    if len(c)<40:return None
    closes=[x[0] for x in c];vol=[x[1] for x in c];price=closes[-1]
    avg=sum(vol[-21:-1])/20 if len(vol)>=21 else 0
    vr=vol[-1]/avg if avg else 0
    ch15=pct(price,closes[-2]);ch3=pct(price,closes[-4])
    high20=max(closes[-21:-1]) if len(closes)>=22 else max(closes[:-1])
    breakout=price>=high20*.997
    e20=ema(closes,20);e200=ema(closes,200)
    confirms=sum(1 for tf in ("1h","4h") if len(s[tf])>=25 and s[tf][-1][0]>ema([x[0] for x in s[tf]],20))
    score=20;reasons=[]
    if vr>=3:score+=24;reasons.append("حجم غير طبيعي")
    elif vr>=2:score+=18;reasons.append("حجم مرتفع")
    elif vr>=1.5:score+=11;reasons.append("الحجم يتسارع")
    if breakout:score+=18;reasons.append("قرب اختراق قمة حديثة")
    elif price>=high20*.985:score+=10;reasons.append("قريب من الاختراق")
    if ch15>.25:score+=10;reasons.append("تسارع سعري")
    if ch3>.8:score+=7;reasons.append("زخم متزايد")
    if price>e20:score+=5
    if price>e200:score+=5;reasons.append("اتجاه داعم")
    if confirms==2:score+=8;reasons.append("تأكيد 1س و4س")
    elif confirms==1:score+=4
    if abs(ch3)>6:score-=18;reasons.append("الحركة متقدمة")
    if abs(ch15)>4:score-=12;reasons.append("تأخر نسبي")
    score=max(0,min(100,round(score)))
    if score<55:return None
    low=min(x[0] for x in c[-20:]);risk=max(price*.012,price-low if price>low else price*.012)
    return {"market":market,"symbol":symbol,"price":price,"score":score,"change15":ch15,"volume_ratio":round(vr,2),"breakout":breakout,"reason":" + ".join(reasons[:4]) or "زخم مبكر","entry":price,"stop":price-risk,"tp1":price+risk*1.5,"tp2":price+risk*2.5,"tp3":price+risk*4}

def radar():
    assets=[]
    for m in ("spot","futures","contracts"):
        try:assets += [(m,s) for s in binance_universe(m)]
        except:pass
    for m,syms in YAHOO_SYMBOLS.items():assets += [(m,s) for s in syms]
    out=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        jobs=[pool.submit(score_asset,*a) for a in assets]
        for j in as_completed(jobs):
            try:
                x=j.result()
                if x:out.append(x)
            except:pass
    out.sort(key=lambda x:(x["score"],x["volume_ratio"],abs(x["change15"])),reverse=True)
    return out[:80]

HTML="""<!doctype html><html lang='ar-SA' dir='rtl'><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>رادار الحركة المبكرة</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#050b14;color:#edf6ff;font-family:Tahoma,Arial,sans-serif}.wrap{max-width:1450px;margin:auto;padding:16px}.top{position:sticky;top:0;z-index:5;background:#050b14ee;border-bottom:1px solid #1b3045;backdrop-filter:blur(14px)}.head{display:flex;justify-content:space-between;align-items:center}.brand{font-size:24px;font-weight:950}.sub,.muted{color:#8196ad}.sub{font-size:12px;margin-top:4px}.live{color:#4ade80;font-weight:900;font-size:12px}.hero{margin-top:16px;padding:24px;border:1px solid #203b55;border-radius:24px;background:linear-gradient(135deg,#0b1b2d,#07101c)}h1{margin:0 0 8px;font-size:clamp(28px,5vw,48px)}.muted{line-height:1.8}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.stat{padding:14px;border:1px solid #1a334b;border-radius:16px;background:#091523}.stat b{display:block;font-size:24px;margin-top:5px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.filter{padding:9px 13px;border-radius:999px;border:1px solid #24425d;background:#091624;color:#a9bdd0;cursor:pointer;font-weight:800}.filter.active{background:#14532d;border-color:#22c55e;color:#d9ffe5}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:13px}.card{padding:16px;border:1px solid #1b344b;border-radius:19px;background:linear-gradient(145deg,#0b1928,#07111c);box-shadow:0 12px 35px #0004}.row{display:flex;justify-content:space-between;align-items:center;gap:8px}.symbol{font-size:19px;font-weight:950}.score{font-size:20px;font-weight:950;color:#4ade80}.tag{display:inline-block;padding:5px 8px;border-radius:999px;background:#10253a;color:#9fc0da;font-size:11px;font-weight:900}.reason{margin:12px 0;color:#b8c8d7;line-height:1.7}.prices{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.box{padding:9px;background:#06101b;border:1px solid #152b40;border-radius:11px}.box small{display:block;color:#71879d;font-size:10px}.box b{font-size:12px}.green{color:#4ade80}.red{color:#fb7185}.note{margin:20px 0;padding:13px;border-radius:14px;background:#081522;border:1px solid #1c3449;color:#8399ad;font-size:12px}@media(max-width:700px){.wrap{padding:11px}.stats{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.prices{grid-template-columns:repeat(2,1fr)}.brand{font-size:20px}}
</style></head><body><header class='top'><div class='wrap head'><div><div class='brand'>⚡ رادار الحركة المبكرة</div><div class='sub'>نبحث عن العلامات التي تظهر قبل الحركة الكبيرة قدر الإمكان</div></div><div class='live'>● LIVE</div></div></header>
<main class='wrap'><section class='hero'><h1>وش اللي يتحرك قبل الناس؟</h1><p class='muted'>المحرك يراقب العملات والأسهم والعقود والفيوتشر والفوركس والذهب داخليًا، ويجمع الحجم والسيولة والزخم والاختراق واتجاه السوق. ما فيه اختيار فريم ولا إعدادات مزعجة.</p></section>
<div class='stats'><div class='stat'><span class='muted'>الفرص الحالية</span><b id='count'>—</b></div><div class='stat'><span class='muted'>أعلى درجة</span><b id='top'>—</b></div><div class='stat'><span class='muted'>آخر تحديث</span><b id='updated'>—</b></div><div class='stat'><span class='muted'>الأسواق</span><b>6</b></div></div>
<div class='filters'><button class='filter active' data-m='all'>الكل</button><button class='filter' data-m='spot'>عملات Spot</button><button class='filter' data-m='futures'>Futures</button><button class='filter' data-m='contracts'>العقود</button><button class='filter' data-m='american'>أسهم أمريكية</button><button class='filter' data-m='saudi'>أسهم سعودية</button><button class='filter' data-m='forex'>فوركس وذهب</button></div>
<div id='grid' class='grid'><div class='card'>جاري البحث عن الفرص المبكرة…</div></div><div class='note'>⚠️ درجة الرادار ترتيب تحليلي وليست نسبة نجاح أو ضمان صعود. الهدف اكتشاف إشارات مبكرة، وليس مطاردة أصل تحرك بالفعل.</div></main>
<script>
let all=[],market='all',grid=document.getElementById('grid');function n(v){if(v>=100)return v.toLocaleString('en-US',{maximumFractionDigits:2});if(v>=1)return v.toLocaleString('en-US',{maximumFractionDigits:4});return v.toFixed(8)}
function render(){let rows=all.filter(x=>market==='all'||x.market===market);document.getElementById('count').textContent=rows.length;document.getElementById('top').textContent=rows[0]?rows[0].score+'/100':'—';grid.innerHTML=rows.map((x,i)=>`<article class='card'><div class='row'><div><span class='tag'>#${i+1} · ${x.market}</span><div class='symbol'>${x.symbol}</div></div><div class='score'>${x.score}</div></div><div class='reason'>${x.reason}</div><div class='row'><span class='muted'>السعر</span><b>${n(x.price)}</b><span class='${x.change15>=0?'green':'red'}'>${x.change15>=0?'+':''}${x.change15.toFixed(2)}%</span></div><div class='prices'><div class='box'><small>دخول مرجعي</small><b>${n(x.entry)}</b></div><div class='box'><small>وقف مرجعي</small><b class='red'>${n(x.stop)}</b></div><div class='box'><small>TP1</small><b class='green'>${n(x.tp1)}</b></div><div class='box'><small>TP2 / TP3</small><b class='green'>${n(x.tp2)} / ${n(x.tp3)}</b></div></div><div class='muted' style='margin-top:10px'>الحجم: ${x.volume_ratio}× · ${x.breakout?'قريب من اختراق':'قبل الاختراق'}</div></article>`).join('')||'<div class="card">حالياً ما ظهرت فرصة تستوفي شروط الرادار.</div>'}
async function load(){try{let r=await fetch('/api/radar',{cache:'no-store'}),j=await r.json();all=j.items||[];document.getElementById('updated').textContent=new Date().toLocaleTimeString('ar-SA');render()}catch(e){grid.innerHTML='<div class="card">تعذر جلب البيانات الآن، المحرك بيحاول مرة ثانية.</div>'}}
document.querySelectorAll('.filter').forEach(b=>b.onclick=()=>{document.querySelectorAll('.filter').forEach(x=>x.classList.remove('active'));b.classList.add('active');market=b.dataset.m;render()});load();setInterval(load,60000);
</script></body></html>"""

@app.get("/",response_class=HTMLResponse)
def home():return HTML

@app.get("/api/radar")
def api_radar():
    try:return JSONResponse({"ok":True,"items":radar(),"generated_at":time.time()})
    except Exception as e:return JSONResponse({"ok":False,"items":[],"error":str(e)[:200]})

@app.get("/health")
def health():return {"ok":True,"service":"early-move-radar","markets":["spot","futures","contracts","american","saudi","forex"]}

@app.get("/robots.txt")
def robots():return HTMLResponse("User-agent: *\nAllow: /",media_type="text/plain")

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")))

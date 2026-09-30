import os,asyncio,time,httpx
from fastapi import FastAPI
from app import MARKETS,TFS,independent_scan

MARKET=os.getenv("WORKER_MARKET","")
TF=os.getenv("WORKER_TF","")
ROLE=os.getenv("WORKER_ROLE","PRIMARY").upper()
CENTRAL=os.getenv("CENTRAL_API_URL","").rstrip("/")
INTERVAL=int(os.getenv("WORKER_INTERVAL","60"))

worker_app=FastAPI(title="Mudarib PRO Worker")

async def run_once():
    if MARKET not in MARKETS or TF not in TFS:
        return {"ok":False,"error":"invalid_worker_scope","market":MARKET,"tf":TF}
    symbols=MARKETS[MARKET]["symbols"]
    if MARKET=="crypto_spot" or MARKET=="crypto_futures":
        from app import universe
        rows=await universe(MARKET=="crypto_futures")
        symbols=[x["symbol"] for x in rows]
    out=[]
    sem=asyncio.Semaphore(8)
    async def one(symbol):
        async with sem:
            try:
                d=await independent_scan(MARKET,symbol)
                return [x for x in d if x.get("tf")==TF]
            except Exception:
                return []
    for chunk_start in range(0,len(symbols),40):
        rows=await asyncio.gather(*[one(s) for s in symbols[chunk_start:chunk_start+40]])
        for row in rows: out.extend(row)
    payload={"market":MARKET,"tf":TF,"role":ROLE,"updated":int(time.time()),"items":out}
    if CENTRAL:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r=await client.post(CENTRAL+"/api/worker/ingest",json=payload)
                payload["ingested"]=r.status_code<300
        except Exception:
            payload["ingested"]=False
    return payload

@worker_app.on_event("startup")
async def startup():
    worker_app.state.data={"updated":0,"items":[],"role":ROLE,"market":MARKET,"tf":TF}
    async def loop():
        while True:
            try:
                worker_app.state.data=await run_once()
            except Exception as e:
                worker_app.state.data={"ok":False,"error":str(e),"market":MARKET,"tf":TF,"role":ROLE}
            await asyncio.sleep(INTERVAL)
    asyncio.create_task(loop())

@worker_app.get("/health")
async def health():
    d=worker_app.state.data
    return {"ok":True,"service_role":ROLE,"market":MARKET,"tf":TF,"updated":d.get("updated",0),"items":len(d.get("items",[]))}

@worker_app.get("/signals")
async def signals():
    return worker_app.state.data

app=worker_app

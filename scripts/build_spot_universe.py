#!/usr/bin/env python3
"""Build one shared volume-ranked crypto candidate universe for all strategy specialists."""
import datetime as dt
import json
import os
import time
import urllib.request

MIN_VOLUME = 1_000_000
MAX_PAGES = 20
PER_PAGE = 250
STABLE_BASES = {"USDT","USDC","FDUSD","TUSD","USDP","DAI","BUSD","EUR","AEUR","USTC","USDE","USDD","PYUSD","USD1"}

def fetch_page(page):
    url = ("https://api.coingecko.com/api/v3/coins/markets"
           f"?vs_currency=usd&order=volume_desc&per_page={PER_PAGE}&page={page}")
    req=urllib.request.Request(url,headers={"User-Agent":"SMART-TRADING-PRO-research/1.0"})
    with urllib.request.urlopen(req,timeout=35) as response:
        return json.loads(response.read().decode("utf-8"))

def main():
    markets=[]
    pages_read=0
    for page in range(1,MAX_PAGES+1):
        payload=fetch_page(page)
        pages_read=page
        markets.extend(payload)
        volumes=[float(x.get("total_volume",0) or 0) for x in payload]
        print(f"UNIVERSE_PAGE {page} rows={len(payload)} lowest_volume={min(volumes) if volumes else 0:.0f}",flush=True)
        # Results are sorted by 24h volume; stop once this page is entirely below the threshold.
        if not payload or max(volumes,default=0)<=MIN_VOLUME:
            break
        if min(volumes,default=0)<=MIN_VOLUME:
            break
        time.sleep(2.2)
    symbols=sorted({str(x.get("symbol","")).upper()+"USDT" for x in markets
                    if x.get("symbol") and str(x.get("symbol","")).upper() not in STABLE_BASES
                    and float(x.get("total_volume",0) or 0)>MIN_VOLUME})
    if not symbols:
        raise RuntimeError("Universe builder returned zero symbols; refusing to launch empty tests")
    os.makedirs("backtest-results",exist_ok=True)
    report={"snapshotUtc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "source":"CoinGecko markets sorted by 24h volume; Binance Spot archives validate each pair",
            "ticker_source":f"CoinGecko paginated volume-ranked candidate list ({pages_read} pages)",
            "exchange_source":"Binance Spot 15m archive validation",
            "pages_read":pages_read,"markets_scanned":len(markets),
            "minimum_volume_usd":MIN_VOLUME,"symbols":symbols}
    with open("backtest-results/spot-crypto-universe.json","w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(f"UNIVERSE_READY pages={pages_read} markets={len(markets)} candidates={len(symbols)} minimum_volume_usd={MIN_VOLUME}",flush=True)

if __name__=="__main__":
    main()

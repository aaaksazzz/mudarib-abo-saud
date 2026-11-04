import math
import requests
from functools import lru_cache

YAHOO="https://query1.finance.yahoo.com"
BINANCE_ALPHA="https://www.binance.com"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; SMART-TRADING-PRO/1.0)","Accept":"application/json"}
US_CONTRACTS=["ES=F","NQ=F","YM=F","RTY=F","CL=F","BZ=F","NG=F","GC=F","SI=F","HG=F","ZC=F","ZW=F","ZS=F","6E=F","6B=F","6J=F","6A=F","6C=F","6S=F","ZB=F","ZN=F","ZF=F","ZT=F"]
FX_SYMBOLS=["EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X","EURJPY=X","GBPJPY=X","EURGBP=X","AUDJPY=X","CADJPY=X","CHFJPY=X","NZDJPY=X","XAUUSD=X","XAGUSD=X"]

def _get(url,params=None):
    response=requests.get(url,params=params,headers=HEADERS,timeout=(3.05,10))
    response.raise_for_status()
    payload=response.json()
    if not isinstance(payload,dict): raise ValueError("Invalid market-data response")
    return payload

def _chart(symbol,interval="15m",period=None):
    periods={"15m":"5d","30m":"1mo","60m":"3mo","1d":"2y","1wk":"5y","1mo":"10y"}
    period=period or periods.get(interval,"5d")
    payload=_get(YAHOO+"/v8/finance/chart/"+symbol,{"interval":interval,"range":period})
    chart=payload.get("chart") or {}
    if chart.get("error"): raise ValueError(str(chart["error"]))
    results=chart.get("result") or []
    if not results: raise ValueError("No Yahoo candles for "+symbol)
    result=results[0]
    quote=((result.get("indicators") or {}).get("quote") or [{}])[0]
    rows=[]
    for i,stamp in enumerate(result.get("timestamp") or []):
        try:
            vals=[(quote.get(k) or [])[i] for k in ("open","high","low","close","volume")]
            op,hi,lo,cl,vol=vals
            if None in (op,hi,lo,cl): continue
            if not all(math.isfinite(float(v)) for v in (op,hi,lo,cl)): continue
            rows.append([int(stamp)*1000,float(op),float(hi),float(lo),float(cl),float(vol or 0)])
        except (IndexError,TypeError,ValueError): continue
    if not rows: raise ValueError("No valid Yahoo candles for "+symbol)
    return rows

def _screener(region):
    payload=_get(YAHOO+"/v1/finance/screener/predefined/saved",{"scrIds":"most_actives","count":250,"start":0,"region":region,"formatted":"false","lang":"en-US"})
    result=((payload.get("finance") or {}).get("result") or [])
    if not result: raise ValueError("Yahoo screener has no results for "+region)
    return result[0].get("quotes") or []

def _row(symbol,price,change,volume,currency=None):
    try:
        p,c,v=float(price or 0),float(change or 0),float(volume or 0)
        if not all(math.isfinite(x) for x in (p,c,v)) or p<=0: return None
        return {"symbol":str(symbol),"price":p,"change_pct":c,"quote_volume":max(0,p*v),"volume":v,"currency":currency}
    except (TypeError,ValueError): return None

@lru_cache(maxsize=1)
def _alpha_symbols():
    payload=_get(BINANCE_ALPHA+"/bapi/defi/v1/public/alpha-trade/get-exchange-info")
    data=payload.get("data") or {}
    symbols=data.get("symbols",[]) if isinstance(data,dict) else data
    found=set()
    for item in symbols or []:
        if not isinstance(item,dict): continue
        symbol=item.get("symbol") or item.get("s")
        quote=item.get("quoteAsset") or item.get("quoteCurrency") or "USDT"
        if symbol and quote=="USDT" and str(symbol).endswith("USDT"): found.add(str(symbol))
    if not found: raise ValueError("Binance Alpha returned no USDT symbols")
    return found

def market_symbols(market):
    if market=="alpha": return _alpha_symbols()
    if market=="us-stocks": return {x["symbol"] for x in _screener("US") if x.get("symbol")}
    if market=="saudi": return {x["symbol"] for x in _screener("SA") if str(x.get("symbol","")).endswith(".SR")}
    if market=="us-contracts": return set(US_CONTRACTS)
    if market=="forex": return set(FX_SYMBOLS)
    return set()

def market_tickers(market):
    if market in ("us-stocks","saudi"):
        out=[]
        for x in _screener("US" if market=="us-stocks" else "SA"):
            symbol=x.get("symbol")
            if not symbol or (market=="saudi" and not str(symbol).endswith(".SR")): continue
            row=_row(symbol,x.get("regularMarketPrice"),x.get("regularMarketChangePercent"),x.get("regularMarketVolume"),x.get("currency"))
            if row and (market=="saudi" or row["volume"]>=1000000): out.append(row)
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    if market in ("us-contracts","forex"):
        out=[]
        for symbol in sorted(market_symbols(market)):
            try:
                rows=_chart(symbol)
                if len(rows)<2: continue
                last=rows[-1]; prev=rows[-97] if len(rows)>=97 else rows[0]
                change=(last[4]/prev[4]-1)*100 if prev[4] else 0
                volume=sum(max(0,x[5]) for x in rows[-96:])
                row=_row(symbol,last[4],change,volume)
                if row: out.append(row)
            except Exception: continue
        if not out: raise ValueError("Yahoo returned no live market quotes")
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    if market=="alpha":
        out=[]
        for symbol in sorted(market_symbols("alpha"))[:100]:
            try:
                payload=_get(BINANCE_ALPHA+"/bapi/defi/v1/public/alpha-trade/ticker",{"symbol":symbol})
                data=payload.get("data") or {}
                if isinstance(data,list): data=data[0] if data else {}
                row=_row(symbol,data.get("lastPrice") or data.get("price"),data.get("priceChangePercent") or data.get("priceChange"),data.get("volume") or data.get("quoteVolume"))
                if row and row["quote_volume"]>=1000000: out.append(row)
            except Exception: continue
        if not out: raise ValueError("Binance Alpha returned no eligible live tickers")
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    raise ValueError("Unsupported external market "+str(market))

def _aggregate_4h(hourly):
    buckets={}
    for row in hourly:
        try:
            stamp=int(row[0])
            bucket=(stamp//14400000)*14400000
            item=buckets.get(bucket)
            if item is None:
                buckets[bucket]=[bucket,float(row[1]),float(row[2]),float(row[3]),float(row[4]),float(row[5] or 0)]
            else:
                item[2]=max(item[2],float(row[2]))
                item[3]=min(item[3],float(row[3]))
                item[4]=float(row[4])
                item[5]+=float(row[5] or 0)
        except (IndexError,TypeError,ValueError):
            continue
    return [buckets[key] for key in sorted(buckets)]
def klines(market,symbol,interval="15m",limit=100):
    supported=("15m","30m","1h","4h","1d","1w","1M")
    if interval not in supported:
        raise ValueError("Unsupported timeframe "+str(interval))
    if market=="alpha":
        alpha_map={"15m":"INTERVAL_15M","30m":"INTERVAL_30M","1h":"INTERVAL_1HOUR","4h":"INTERVAL_4HOUR","1d":"INTERVAL_1DAY","1w":"INTERVAL_1WEEK","1M":"INTERVAL_1MONTH"}
        payload=_get(BINANCE_ALPHA+"/bapi/defi/v1/public/alpha-trade/klines",{"symbol":symbol,"interval":alpha_map[interval],"limit":limit})
        data=payload.get("data") or []
        rows=[]
        for item in data:
            vals=[item.get(k) for k in ("openTime","open","high","low","close","volume")] if isinstance(item,dict) else item
            if vals and len(vals)>=6:
                rows.append([int(float(vals[0])),*[float(v or 0) for v in vals[1:6]]])
        return rows[-limit:]
    yahoo_map={"15m":"15m","30m":"30m","1h":"60m","1d":"1d","1w":"1wk","1M":"1mo"}
    if interval=="4h":
        return _aggregate_4h(_chart(symbol,"60m","3mo"))[-limit:]
    return _chart(symbol,yahoo_map[interval])[-limit:]

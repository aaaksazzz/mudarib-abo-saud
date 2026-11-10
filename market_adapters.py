import csv
import io
import math
import time
from concurrent.futures import ThreadPoolExecutor
import requests
from functools import lru_cache
from saudi_market_data import official_saudi_quotes

YAHOO_HOSTS=("https://query1.finance.yahoo.com","https://query2.finance.yahoo.com")
YAHOO=YAHOO_HOSTS[0]
BINANCE_ALPHA="https://www.binance.com"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; SMART-TRADING-PRO/1.0)","Accept":"application/json"}
US_CONTRACTS=["ES=F","MES=F","NQ=F","MNQ=F","YM=F","MYM=F","RTY=F","M2K=F","CL=F","MCL=F","BZ=F","NG=F","RB=F","HO=F","GC=F","MGC=F","SI=F","SIL=F","HG=F","ZC=F","ZW=F","ZS=F","ZM=F","ZL=F","ZO=F","ZR=F","LE=F","HE=F","GF=F","6E=F","6B=F","6J=F","6A=F","6C=F","6S=F","6N=F","6M=F","ZB=F","UB=F","ZN=F","ZF=F","ZT=F"]
# USD notional per Yahoo price unit and traded contract. Agricultural prices
# quoted in cents are normalized in the multiplier (e.g. 5,000 bushels / 100).
US_CONTRACT_MULTIPLIERS={
    "ES=F":50,"MES=F":5,"NQ=F":20,"MNQ=F":2,"YM=F":5,"MYM=F":0.5,
    "RTY=F":50,"M2K=F":5,"CL=F":1000,"MCL=F":100,"BZ=F":1000,
    "NG=F":10000,"RB=F":42000,"HO=F":42000,"GC=F":100,"MGC=F":10,
    "SI=F":5000,"SIL=F":1000,"HG=F":25000,"ZC=F":50,"ZW=F":50,
    "ZS=F":50,"ZM=F":100,"ZL=F":600,"ZO=F":50,"ZR=F":2000,
    "LE=F":400,"HE=F":400,"GF=F":500,"6E=F":125000,"6B=F":62500,
    "6J=F":12500000,"6A=F":100000,"6C=F":100000,"6S=F":125000,
    "6N=F":100000,"6M=F":500000,"ZB=F":1000,"UB=F":1000,
    "ZN=F":1000,"ZF=F":1000,"ZT=F":2000,
}


def contract_notional_usd(symbol, price, contracts):
    try:
        price=float(price)
        contracts=float(contracts)
        multiplier=US_CONTRACT_MULTIPLIERS.get(str(symbol))
        if multiplier is None or not all(math.isfinite(x) for x in (price,contracts,multiplier)):
            return None
        if price<=0 or contracts<0:
            return None
        return price*contracts*multiplier
    except (TypeError,ValueError,OverflowError):
        return None

FX_SYMBOLS=[
    "EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X","NZDUSD=X",
    "EURJPY=X","GBPJPY=X","EURGBP=X","AUDJPY=X","CADJPY=X","CHFJPY=X","NZDJPY=X",
    "EURAUD=X","EURCAD=X","EURCHF=X","EURNZD=X","GBPAUD=X","GBPCAD=X","GBPCHF=X",
    "GBPNZD=X","AUDCAD=X","AUDCHF=X","AUDNZD=X","CADCHF=X","NZDCAD=X","NZDCHF=X",
    "USDNOK=X","USDSEK=X","USDHKD=X","USDSGD=X","USDCNH=X","USDINR=X","USDMXN=X",
    "USDZAR=X","USDTRY=X","USDBRL=X","USDKRW=X","USDTHB=X","EURSEK=X","EURNOK=X",
    "EURDKK=X","EURPLN=X","EURHUF=X","EURCZK=X","EURTRY=X","GBPSEK=X","GBPNOK=X",
    "AUDSGD=X","AUDHKD=X","CADSGD=X","CHFSGD=X","SGDJPY=X","NOKSEK=X",
    "XAUUSD=X","XAGUSD=X"
]

def _get(url,params=None):
    response=requests.get(url,params=params,headers=HEADERS,timeout=(2,6))
    response.raise_for_status()
    payload=response.json()
    if not isinstance(payload,dict): raise ValueError("Invalid market-data response")
    return payload

def _chart(symbol,interval="15m",period=None):
    periods={"1m":"7d","5m":"60d","15m":"60d","30m":"1mo","60m":"6mo","1d":"2y","1wk":"5y","1mo":"max"}
    period=period or periods.get(interval,"5d")
    errors=[]
    for host in YAHOO_HOSTS:
        try:
            payload=_get(host+"/v8/finance/chart/"+symbol,{"interval":interval,"range":period})
            chart=payload.get("chart") or {}
            if chart.get("error"):
                raise ValueError(str(chart["error"]))
            results=chart.get("result") or []
            if not results:
                raise ValueError("No Yahoo candles returned")
            result=results[0]
            quote=((result.get("indicators") or {}).get("quote") or [{}])[0]
            rows=[]
            for i,stamp in enumerate(result.get("timestamp") or []):
                try:
                    vals=[(quote.get(k) or [])[i] for k in ("open","high","low","close","volume")]
                    op,hi,lo,cl,vol=vals
                    if None in (op,hi,lo,cl):
                        continue
                    if not all(math.isfinite(float(v)) for v in (op,hi,lo,cl)):
                        continue
                    rows.append([int(stamp)*1000,float(op),float(hi),float(lo),float(cl),float(vol or 0)])
                except (IndexError,TypeError,ValueError):
                    continue
            if not rows:
                raise ValueError("No valid Yahoo candles returned")
            return rows
        except Exception as exc:
            errors.append(host+": "+str(exc))
    raise ValueError("Yahoo chart failed for "+symbol+": "+"; ".join(errors))

def _screener(region,scr_id="most_actives",start=0):
    # Yahoo screener pages are capped; request successive pages and retry
    # the secondary public host before treating a page as unavailable.
    errors=[]
    params={"scrIds":scr_id,"count":250,"start":int(start),"region":region,
            "formatted":"false","lang":"en-US"}
    for host in YAHOO_HOSTS:
        try:
            payload=_get(host+"/v1/finance/screener/predefined/saved",params)
            finance=payload.get("finance") or {}
            if finance.get("error"):
                raise ValueError(str(finance["error"]))
            result=finance.get("result") or []
            if not result:
                raise ValueError("empty screener result")
            return result[0].get("quotes") or []
        except Exception as exc:
            errors.append(host+": "+str(exc))
    raise ValueError("Yahoo screener failed for "+region+"/"+scr_id+" offset "+str(start)+" ("+"; ".join(errors)+")")

@lru_cache(maxsize=4)
def _screener_quotes_cached(region,cache_bucket):
    # Merge independent public universes so the scan is not limited to the
    # first 250 most-active names. US lists are paged; Saudi lists are merged.
    screeners=("most_actives","day_gainers","day_losers",
               "small_cap_gainers","aggressive_small_caps") if region=="US" else (
               "most_actives","day_gainers","day_losers")
    page_limit=2 if region=="US" else 1
    quotes={}
    errors=[]
    for scr_id in screeners:
        for page in range(page_limit):
            try:
                batch=_screener(region,scr_id) if page==0 else _screener(region,scr_id,page*250)
                for item in batch:
                    symbol=str(item.get("symbol") or "")
                    if symbol:
                        quotes.setdefault(symbol,item)
                if len(batch)<250:
                    break
            except Exception as exc:
                errors.append(f"{scr_id}[{page}]: {exc}")
                break
    if not quotes and errors:
        raise ValueError("Yahoo returned no screener quotes for "+region+" ("+"; ".join(errors)+")")
    return tuple(quotes.values())

def _screener_quotes(region):
    # Refresh the merged universe every ten minutes while avoiding duplicate
    # screener bursts from the scanner and snapshot endpoints.
    return list(_screener_quotes_cached(region,int(time.time()//600)))

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

def _saudi_symbol(value):
    symbol=str(value or "").strip().upper()
    if symbol.endswith(".SR") and symbol[:-3].isdigit():
        return symbol
    # Yahoo's Saudi screener sometimes returns the Tadawul code without
    # the Yahoo exchange suffix. Normalize valid four-digit stock codes.
    if len(symbol)==4 and symbol.isdigit():
        return symbol+".SR"
    return None

def _tradingview_saudi_quotes():
    """Public TASI equity universe fallback when Yahoo's SA screener is empty."""
    body={
        "columns":["name","close","change","volume"],
        "filter":[{"left":"type","operation":"equal","right":"stock"}],
        "options":{"lang":"en"},
        "range":[0,500],
        "sort":{"sortBy":"volume","sortOrder":"desc"},
    }
    errors=[]
    for host in ("https://scanner.tradingview.com",):
        try:
            response=requests.post(host+"/sa/scan",json=body,headers=HEADERS,timeout=(4,12))
            response.raise_for_status()
            payload=response.json()
            data=payload.get("data") if isinstance(payload,dict) else None
            rows=[]
            for item in data or []:
                ticker=str(item.get("s") or "").split(":")[-1].strip()
                values=item.get("d") or []
                if len(values)<4 or not ticker.isdigit() or len(ticker)!=4:
                    continue
                row=_row(ticker+".SR",values[1],values[2],values[3],"SAR")
                if row:
                    rows.append(row)
            if rows:
                return rows
            errors.append("TradingView returned no valid TASI equity rows")
        except Exception as exc:
            errors.append(str(exc))
    raise ValueError("TASI universe unavailable from Yahoo and TradingView ("+"; ".join(errors)+")")



@lru_cache(maxsize=2)
def _saudi_exchange_symbols_cached(cache_bucket):
    """Fetch the official Saudi Exchange listed-equity universe (TASI)."""
    url="https://www.saudiexchange.sa/tadawul.eportal.theme.helper/ThemeSearchUtilityServlet"
    response=requests.get(url,headers={**HEADERS,"Referer":"https://www.saudiexchange.sa/"},timeout=(5,15))
    response.raise_for_status()
    payload=response.json()
    if isinstance(payload,dict):
        payload=payload.get("data") or payload.get("results") or payload.get("companies") or []
    if not isinstance(payload,list):
        raise ValueError("Saudi Exchange returned an unexpected securities payload")
    symbols=set()
    for item in payload:
        if not isinstance(item,dict):
            continue
        code=str(item.get("symbol") or item.get("companySymbol") or item.get("company_symbol") or "").strip()
        market_type=str(item.get("market_type") or item.get("marketType") or "M").upper()
        if market_type in ("M","MAIN","TASI") and code.isdigit() and len(code)==4:
            symbols.add(code+".SR")
    if not symbols:
        raise ValueError("Saudi Exchange returned no TASI equity symbols")
    return tuple(sorted(symbols))


def _saudi_exchange_symbols():
    return set(_saudi_exchange_symbols_cached(int(time.time()//1800)))


@lru_cache(maxsize=2)
def _saudi_dataset_symbols_cached(cache_bucket):
    """Fallback TASI universe from a public CC0 ticker dataset; no API key."""
    url = (
        "https://huggingface.co/datasets/"
        "kjhq/Saudi-Arabia-Stock-Symbols-and-Metadata/resolve/main/ksa.csv"
    )
    response = requests.get(
        url, headers={**HEADERS, "Accept": "text/csv,*/*"}, timeout=(5, 20)
    )
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text))
    symbols = set()
    for item in reader:
        if str(item.get("market") or "").strip().upper() != "TADAWUL":
            continue
        ticker = str(item.get("ticker") or "").strip()
        # 9xxx symbols belong to the parallel market (Nomu), not TASI.
        if len(ticker) == 4 and ticker.isdigit() and not ticker.startswith("9"):
            symbols.add(ticker + ".SR")
    if not symbols:
        raise ValueError("Public Saudi ticker dataset returned no main-market symbols")
    return tuple(sorted(symbols))


def _saudi_dataset_symbols():
    # Dataset publisher updates the directory weekly; cache it for six hours.
    return set(_saudi_dataset_symbols_cached(int(time.time() // 21600)))


def _saudi_chart_quotes(symbols):
    def fetch(symbol):
        try:
            candles=_chart(symbol,"1d","5d")
            if not candles:
                return None
            last=candles[-1]
            previous=candles[-2] if len(candles)>1 else last
            change=(last[4]/previous[4]-1)*100 if previous[4] else 0.0
            return _row(symbol,last[4],change,last[5],"SAR")
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        return [row for row in pool.map(fetch,sorted(symbols)) if row]


def market_symbols(market):
    if market=="alpha": return _alpha_symbols()
    if market=="us-stocks": return {x["symbol"] for x in _screener_quotes("US") if x.get("symbol")}
    if market=="saudi":
        symbols=set()
        try:
            symbols={normalized for x in _screener_quotes("SA") if (normalized:=_saudi_symbol(x.get("symbol")))}
        except Exception:
            pass
        try:
            symbols.update(_saudi_exchange_symbols())
        except Exception:
            pass
        if not symbols:
            try:
                symbols.update(_saudi_dataset_symbols())
            except Exception as exc:
                print("Saudi public ticker directory unavailable: " + str(exc))
        if symbols:
            return symbols
        return {row["symbol"] for row in _tradingview_saudi_quotes()}
    if market=="us-contracts": return set(US_CONTRACTS)
    if market=="forex": return set(FX_SYMBOLS)
    return set()

def market_tickers(market):
    if market in ("us-stocks","saudi"):
        out=[]
        if market=="saudi":
            # Prefer the Saudi Exchange's own public market-watch feed. Keep
            # Yahoo and TradingView as fallbacks so a vendor outage is isolated.
            try:
                try:
                    allowed_symbols=_saudi_exchange_symbols()
                except Exception:
                    allowed_symbols=None
                official_rows=official_saudi_quotes(allowed_symbols)
                if official_rows:
                    return sorted(official_rows,key=lambda x:x["quote_volume"],reverse=True)
            except Exception as exc:
                print("Saudi Exchange live feed unavailable; trying fallbacks: "+str(exc))
        if market=="us-stocks":
            source_rows=_screener_quotes("US")
        else:
            try:
                source_rows=_screener_quotes("SA")
            except Exception:
                source_rows=[]
        if market=="saudi" and not source_rows:
            # Yahoo's SA predefined screeners can return an empty universe with HTTP 200.
            # Use the official Saudi Exchange equity list, then obtain quotes from Yahoo charts.
            errors=[]
            try:
                symbols=_saudi_exchange_symbols()
                out=_saudi_chart_quotes(symbols)
                if out:
                    return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
                errors.append("Saudi Exchange symbols were found but Yahoo returned no chart quotes")
            except Exception as exc:
                errors.append("Saudi Exchange: "+str(exc))
            try:
                symbols=_saudi_dataset_symbols()
                out=_saudi_chart_quotes(symbols)
                if out:
                    print("Saudi quotes loaded from Yahoo charts using public TASI directory: "
                          + str(len(out)) + "/" + str(len(symbols)))
                    return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
                errors.append("Public TASI directory loaded but Yahoo returned no chart quotes")
            except Exception as exc:
                errors.append("Public TASI directory: "+str(exc))
            try:
                fallback=_tradingview_saudi_quotes()
                return sorted(fallback,key=lambda x:x["quote_volume"],reverse=True)
            except Exception as exc:
                errors.append("TradingView: "+str(exc))
            raise ValueError("Saudi market data unavailable ("+"; ".join(errors)+")")
        for x in source_rows:
            symbol=_saudi_symbol(x.get("symbol")) if market=="saudi" else x.get("symbol")
            if not symbol: continue
            row=_row(symbol,x.get("regularMarketPrice"),x.get("regularMarketChangePercent"),x.get("regularMarketVolume"),x.get("currency"))
            if row and (market=="saudi" or row["quote_volume"]>=1000000): out.append(row)
        if market=="saudi" and out:
            # Complete Yahoo's partial screener with the official TASI equity universe.
            try:
                known={row["symbol"] for row in out}
                missing=_saudi_exchange_symbols()-known
                if missing:
                    out.extend(_saudi_chart_quotes(missing))
            except Exception:
                pass
        if market=="saudi" and not out:
            # Yahoo's Saudi screener can return symbols without regularMarketPrice
            # (or transiently omit quote fields). Recover prices from the public
            # chart endpoint rather than aborting the entire scheduled TASI scan.
            candidates=sorted({_saudi_symbol(x.get("symbol")) for x in source_rows
                               if _saudi_symbol(x.get("symbol"))})
            def fetch_saudi_chart_quote(symbol):
                try:
                    candles=_chart(symbol,"1d","5d")
                    if not candles:
                        return None
                    last=candles[-1]
                    previous=candles[-2] if len(candles)>1 else last
                    change=(last[4]/previous[4]-1)*100 if previous[4] else 0.0
                    volume=max(0.0,float(last[5] or 0))
                    return _row(symbol,last[4],change,volume,"SAR")
                except Exception:
                    return None
            if candidates:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    out=[row for row in pool.map(fetch_saudi_chart_quote,candidates) if row]
            if not out:
                # A populated Yahoo symbol list can still have unusable chart quotes.
                # Retry the official TASI universe before using the legacy TradingView fallback.
                try:
                    out=_saudi_chart_quotes(_saudi_exchange_symbols())
                except Exception:
                    out=[]
            if not out:
                try:
                    out=_saudi_chart_quotes(_saudi_dataset_symbols())
                except Exception:
                    out=[]
            if not out:
                out=_tradingview_saudi_quotes()
            if not out:
                raise ValueError(
                    "Yahoo Saudi screener returned no priced TASI symbols; "
                    f"chart fallback checked {len(candidates)} symbols"
                )
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    if market in ("us-contracts","forex"):
        symbols=sorted(market_symbols(market))
        def fetch_quote(symbol):
            try:
                rows=_chart(symbol)
                if len(rows)<2: return None
                last=rows[-1]
                prev=rows[-97] if len(rows)>=97 else rows[0]
                change=(last[4]/prev[4]-1)*100 if prev[4] else 0
                # Use the last 96 fifteen-minute bars as a rolling daily
                # activity window. Apply the 1M notional proxy floor to US
                # futures contracts; keep FX/metals quotes unrestricted.
                volume=sum(max(0,x[5]) for x in rows[-96:])
                row=_row(symbol,last[4],change,volume)
                if market=="us-contracts":
                    notional=contract_notional_usd(symbol,last[4],volume)
                    # Yahoo volume is a count of futures contracts, not shares.
                    # Apply the exchange contract multiplier before the $1M floor.
                    if not row or notional is None or notional<1_000_000:
                        return None
                    row["quote_volume"]=notional
                    row["notional_basis"]="contract_multiplier_usd"
                return row
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            out=[row for row in pool.map(fetch_quote,symbols) if row]
        if not out: raise ValueError("Yahoo returned no live market quotes")
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    if market=="alpha":
        symbols=sorted(market_symbols("alpha"))
        def fetch_alpha_quote(symbol):
            try:
                payload=_get(BINANCE_ALPHA+"/bapi/defi/v1/public/alpha-trade/ticker",{"symbol":symbol})
                data=payload.get("data") or {}
                if isinstance(data,list): data=data[0] if data else {}
                # quoteVolume is already quote-denominated; do not multiply it by price again.
                if data.get("quoteVolume") not in (None,""):
                    quote_volume=float(data["quoteVolume"])
                    price=float(data.get("lastPrice") or data.get("price") or 0)
                    change=float(data.get("priceChangePercent") or data.get("priceChange") or 0)
                    if price>0 and all(math.isfinite(x) for x in (price,change,quote_volume)) and quote_volume>=1000000:
                        return {"symbol":symbol,"price":price,"change_pct":change,"quote_volume":quote_volume}
                    return None
                row=_row(symbol,data.get("lastPrice") or data.get("price"),data.get("priceChangePercent") or data.get("priceChange"),data.get("volume"))
                return row if row and row["quote_volume"]>=1000000 else None
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=8) as pool:
            out=[row for row in pool.map(fetch_alpha_quote,symbols) if row]
        if not out: raise ValueError("Binance Alpha returned no eligible live tickers")
        return sorted(out,key=lambda x:x["quote_volume"],reverse=True)
    raise ValueError("Unsupported external market "+str(market))


@lru_cache(maxsize=256)
def _binance_microstructure_cached(market,symbol,cache_bucket):
    """Public Binance trade-flow and depth snapshot; no account credentials."""
    if market not in ("spot","futures"):
        return None
    base="https://fapi.binance.com" if market=="futures" else "https://api.binance.com"
    prefix="/fapi/v1" if market=="futures" else "/api/v3"
    try:
        trades=_get(base+prefix+"/aggTrades",{"symbol":symbol,"limit":100})
        depth=_get(base+prefix+"/depth",{"symbol":symbol,"limit":20})
        if not isinstance(trades,list) or not isinstance(depth,dict):
            return None
        buyer=seller=0.0
        for trade in trades:
            qty=float(trade.get("q") or 0)
            if qty<=0 or not math.isfinite(qty):
                continue
            # m=True means buyer was maker, so the seller was the taker.
            if trade.get("m") is True:
                seller+=qty
            else:
                buyer+=qty
        total=buyer+seller
        bids=depth.get("bids") or []
        asks=depth.get("asks") or []
        bid_notional=sum(float(level[0])*float(level[1]) for level in bids if len(level)>=2)
        ask_notional=sum(float(level[0])*float(level[1]) for level in asks if len(level)>=2)
        book_total=bid_notional+ask_notional
        if total<=0 or book_total<=0:
            return None
        return {"taker_delta_ratio":(buyer-seller)/total,
                "book_imbalance":(bid_notional-ask_notional)/book_total,
                "trade_count":len(trades),"depth_levels":min(len(bids),len(asks)),
                "source":"Binance public aggTrades and depth"}
    except Exception:
        return None


def microstructure(market,symbol):
    # A one-minute cache avoids repeating requests for each timeframe.
    return _binance_microstructure_cached(market,symbol,int(time.time()//60))


def _aggregate_4h(rows):
    """Aggregate four consecutive hourly bars without crossing session gaps.

    UTC four-hour buckets split US cash sessions at arbitrary boundaries and
    can produce partial or misaligned bars. Consecutive grouping preserves
    chronological OHLCV and resets across overnight/weekend/provider gaps.
    """
    aggregated=[]
    group=[]
    for row in sorted(rows,key=lambda item:int(item[0])):
        stamp=int(row[0])
        if group and stamp-int(group[-1][0])>5_400_000:
            group=[]
        group.append(row)
        if len(group)==4:
            aggregated.append([
                int(group[0][0]),
                float(group[0][1]),
                max(float(x[2]) for x in group),
                min(float(x[3]) for x in group),
                float(group[-1][4]),
                sum(float(x[5] or 0) for x in group),
            ])
            group=[]
    return aggregated


def klines(market,symbol,interval="15m",limit=250):
    yahoo_map={"1m":"1m","15m":"15m","1h":"60m","1d":"1d","1w":"1wk","1M":"1mo"}
    alpha_map={"1m":"1m","15m":"15m","1h":"1h","4h":"4h",
               "1d":"1d","1w":"1w","1M":"1M"}
    if interval not in ("1m","15m","1h","4h","1d","1w","1M"):
        raise ValueError("Unsupported timeframe "+str(interval))
    if market=="alpha":
        payload=_get(BINANCE_ALPHA+"/bapi/defi/v1/public/alpha-trade/klines",{"symbol":symbol,"interval":alpha_map[interval],"limit":limit})
        data=payload.get("data") or []
        rows=[]
        for item in data:
            vals=[item.get(k) for k in ("openTime","open","high","low","close","volume")] if isinstance(item,dict) else item
            if vals and len(vals)>=6:
                rows.append([int(float(vals[0])),*[float(v or 0) for v in vals[1:6]]])
        return rows[-limit:]
    if market in ("spot","futures"):
        base=BINANCE_FUTURES if market=="futures" else BINANCE_SPOT
        path="/fapi/v1/klines" if market=="futures" else "/api/v3/klines"
        return fetch_json(base+path,{"symbol":symbol,"interval":interval,"limit":limit})
    if interval=="4h":
        return _aggregate_4h(_chart(symbol,"60m","6mo"))[-limit:]
    return _chart(symbol,yahoo_map[interval])[-limit:]

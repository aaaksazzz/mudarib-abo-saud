import os,requests
from flask import Flask,jsonify,request,send_from_directory
app=Flask(__name__,static_folder='static',static_url_path='/static');BASE='https://api.binance.com'
def get(path,params=None):
 r=requests.get(BASE+path,params=params,timeout=15);r.raise_for_status();return r.json()
@app.get('/')
def home(): return send_from_directory('.','index.html')
@app.get('/health')
def health(): return jsonify(ok=True)
@app.get('/api/binance/markets')
def markets():
 info=get('/api/v3/exchangeInfo');allowed={s['symbol'] for s in info['symbols'] if s.get('status')=='TRADING' and s.get('quoteAsset')=='USDT' and s.get('isSpotTradingAllowed',True)};out=[]
 for t in get('/api/v3/ticker/24hr'):
  if t['symbol'] in allowed:out.append({'symbol':t['symbol'],'price':float(t['lastPrice']),'change':float(t['priceChangePercent']),'quoteVolume':float(t['quoteVolume'])})
 out.sort(key=lambda x:x['quoteVolume'],reverse=True);return jsonify(out)
@app.get('/api/binance/analysis')
def analysis():
 s=request.args.get('symbol','BTCUSDT').upper();interval=request.args.get('interval','15m');allowed={'1m','3m','5m','15m','30m','1h','2h','4h','6h','8h','12h','1d','3d','1w','1M'}
 if interval not in allowed:return jsonify(error='فريم غير مدعوم'),400
 k=get('/api/v3/klines',{'symbol':s,'interval':interval,'limit':250})
 if len(k)<30:return jsonify(error='بيانات غير كافية'),400
 close=[float(x[4]) for x in k];price=close[-1];change=(price/close[-2]-1)*100
 def ema(a,n):
  z=a[0];q=2/(n+1)
  for v in a[1:]:z=v*q+z*(1-q)
  return z
 def rsi(a,n=14):
  g=[max(a[i]-a[i-1],0) for i in range(1,len(a))];l=[max(a[i-1]-a[i],0) for i in range(1,len(a))];ag=sum(g[:n])/n;al=sum(l[:n])/n
  for j in range(n,len(g)):ag=(ag*(n-1)+g[j])/n;al=(al*(n-1)+l[j])/n
  return 100 if al==0 else 100-100/(1+ag/al)
 e20,e50,e200=ema(close,20),ema(close,50),ema(close,200);rv=rsi(close);score=(1 if price>e20 else -1)+(1 if price>e50 else -1)+(1 if price>e200 else -1)+(1 if rv>=55 else -1 if rv<=45 else 0);sig='شراء قوي' if score>=3 else 'شراء' if score==2 else 'بيع قوي' if score<=-3 else 'بيع' if score==-2 else 'حيادي'
 return jsonify(symbol=s,price=price,change=change,rsi=rv,ema20=e20,ema50=e50,ema200=e200,signal=sig)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))

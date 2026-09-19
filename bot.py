import os,time,json,hmac,hashlib,urllib.parse,threading,math
from datetime import datetime
from decimal import Decimal,ROUND_DOWN
import requests
from flask import Flask,jsonify

API_KEY=os.getenv('BINANCE_API_KEY','').strip(); API_SECRET=os.getenv('BINANCE_API_SECRET','').strip(); API_BASE='https://api.binance.com'
STATE_FILE='state.json'; HISTORY_FILE='trade_history.json'; MIN_USDT=5.0; TRADE_USDT_PERCENT=.999; SCAN_INTERVAL=180; POSITION_CHECK_SECONDS=5
PUBLIC_REQUEST_DELAY=.12; PUBLIC_MAX_RETRIES=6; EXCHANGE_CACHE_SECONDS=1800
INITIAL_STOP=-.02; INITIAL_TARGET=.02; PROFIT_STEP=.01; TARGET_DISTANCE=.02; FEE_RATE=.001
app=Flask(__name__); exchange_cache=None; exchange_cache_time=0; public_lock=threading.Lock(); last_public_request=0.0
last_scan=''; last_signal=''; last_error=''; scan_count=0
balance_cache={'connected':False,'usdt':0.0}; balance_cache_time=0; BALANCE_CACHE_SECONDS=60; balance_lock=threading.Lock()

def log(x): print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {x}",flush=True)
def now_text(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def load_json(f,d):
 try:
  if not os.path.exists(f): return d
  with open(f,encoding='utf-8') as x:return json.load(x)
 except Exception as e: log(f'خطأ قراءة {f}: {e}'); return d
def save_json(f,d):
 t=f+'.tmp'
 with open(t,'w',encoding='utf-8') as x: json.dump(d,x,ensure_ascii=False,indent=2)
 os.replace(t,f)
def load_state(): return load_json(STATE_FILE,{})
def save_state(d): save_json(STATE_FILE,d)
def load_history(): return load_json(HISTORY_FILE,[])
def save_history(d): save_json(HISTORY_FILE,d)
def floor_step(v,s):
 try:
  v=Decimal(str(v));s=Decimal(str(s));return float((v/s).to_integral_value(rounding=ROUND_DOWN)*s)
 except:return float(v)

def signed_request(method,path,params=None):
 if not API_KEY or not API_SECRET: raise Exception('BINANCE_API_KEY أو BINANCE_API_SECRET غير موجود')
 p=dict(params or {});p['timestamp']=int(time.time()*1000);p['recvWindow']=10000
 q=urllib.parse.urlencode(p,doseq=True); sig=hmac.new(API_SECRET.encode(),q.encode(),hashlib.sha256).hexdigest()
 r=requests.request(method,f'{API_BASE}{path}?{q}&signature={sig}',headers={'X-MBX-APIKEY':API_KEY},timeout=20)
 if r.status_code>=400: raise Exception(f'Binance {r.status_code}: {r.text}')
 return r.json()

def public_get(path,params=None):
 global last_public_request
 for attempt in range(PUBLIC_MAX_RETRIES):
  try:
   with public_lock:
    elapsed=time.time()-last_public_request
    if elapsed<PUBLIC_REQUEST_DELAY: time.sleep(PUBLIC_REQUEST_DELAY-elapsed)
    r=requests.get(f'{API_BASE}{path}',params=params or {},timeout=20);last_public_request=time.time()
   if r.status_code<400:return r.json()
   if r.status_code==429:
    try:w=float(r.headers.get('Retry-After',10))
    except:w=min(60,5*(2**attempt))
    log(f'⚠️ Binance 429 → انتظار {w:.1f} ثانية');time.sleep(w);continue
   if r.status_code in (500,502,503,504):
    w=min(30,2*(2**attempt));time.sleep(w);continue
   raise Exception(f'Market {r.status_code}: {r.text}')
  except requests.exceptions.RequestException as e:
   w=min(30,2*(2**attempt));log(f'⚠️ اتصال Market → {e}');time.sleep(w)
 raise Exception(f'فشل Market API بعد {PUBLIC_MAX_RETRIES} محاولات')

def get_account(): return signed_request('GET','/api/v3/account')
def get_asset_free(asset):
 for b in get_account().get('balances',[]):
  if b['asset']==asset:return float(b['free'])
 return 0.0
def get_usdt_balance(): return get_asset_free('USDT')

def get_binance_status():
 global balance_cache,balance_cache_time
 with balance_lock:
  if time.time()-balance_cache_time<BALANCE_CACHE_SECONDS:return balance_cache
  try:
   a=get_account();u=0.0
   for b in a.get('balances',[]):
    if b.get('asset')=='USDT':u=float(b.get('free',0))+float(b.get('locked',0));break
   balance_cache={'connected':True,'usdt':u};balance_cache_time=time.time();return balance_cache
  except Exception as e:
   log(f'⚠️ فحص اتصال Binance: {e}');balance_cache={'connected':False,'usdt':0.0};balance_cache_time=time.time();return balance_cache

def get_exchange_info():
 global exchange_cache,exchange_cache_time
 if exchange_cache is not None and time.time()-exchange_cache_time<EXCHANGE_CACHE_SECONDS:return exchange_cache
 exchange_cache=public_get('/api/v3/exchangeInfo');exchange_cache_time=time.time();return exchange_cache
def get_symbol_info(symbol):
 for x in get_exchange_info().get('symbols',[]):
  if x['symbol']==symbol:return x
 raise Exception(f'لا توجد معلومات للعملة {symbol}')
def get_filters(symbol):
 t=s=.00000001;mq=mn=0.0
 for f in get_symbol_info(symbol).get('filters',[]):
  if f['filterType']=='PRICE_FILTER':t=float(f['tickSize'])
  elif f['filterType']=='LOT_SIZE':s=float(f['stepSize']);mq=float(f['minQty'])
  elif f['filterType'] in ('MIN_NOTIONAL','NOTIONAL'):mn=float(f.get('minNotional',f.get('notional',0)))
 return t,s,mq,mn
def get_price(symbol): return float(public_get('/api/v3/ticker/price',{'symbol':symbol})['price'])

def market_buy(symbol,amount):
 r=signed_request('POST','/api/v3/order',{'symbol':symbol,'side':'BUY','type':'MARKET','quoteOrderQty':f'{amount:.8f}','newOrderRespType':'FULL'})
 q=float(r.get('executedQty',0));quote=float(r.get('cummulativeQuoteQty',0))
 if q<=0:raise Exception('عملية الشراء لم تنفذ')
 return {'orderId':r['orderId'],'qty':q,'entry':quote/q,'raw':r}

def place_oco(symbol,qty,stop_price,target_price):
 tick,step,mq,mn=get_filters(symbol);qty=floor_step(qty,step);stop_price=floor_step(stop_price,tick);target_price=floor_step(target_price,tick);cur=get_price(symbol)
 if qty<mq:raise Exception(f'الكمية {qty} أقل من الحد الأدنى {mq}')
 if target_price<=cur:raise Exception(f'الهدف {target_price} أقل أو يساوي السعر الحالي {cur}')
 if stop_price>=cur:raise Exception(f'الوقف {stop_price} أعلى أو يساوي السعر الحالي {cur}')
 def fmt(x):return f'{x:.12f}'.rstrip('0').rstrip('.')
 r=signed_request('POST','/api/v3/orderList/oco',{'symbol':symbol,'side':'SELL','quantity':fmt(qty),'aboveType':'TAKE_PROFIT','aboveStopPrice':fmt(target_price),'belowType':'STOP_LOSS','belowStopPrice':fmt(stop_price),'newOrderRespType':'RESULT'})
 reports=r.get('orderReports') or r.get('orders') or [];above=below=None
 for o in reports:
  if o.get('type')=='TAKE_PROFIT':above=o.get('orderId')
  elif o.get('type')=='STOP_LOSS':below=o.get('orderId')
 return {'orderListId':r.get('orderListId'),'aboveOrderId':above,'belowOrderId':below,'stop_price':stop_price,'target_price':target_price,'qty':qty}
def cancel_oco(symbol,oid):
 if not oid:return True
 try:signed_request('DELETE','/api/v3/orderList',{'symbol':symbol,'orderListId':int(oid)});return True
 except Exception as e:log(f'⚠️ تعذر إلغاء OCO: {e}');return False
def get_order(symbol,oid):return signed_request('GET','/api/v3/order',{'symbol':symbol,'orderId':int(oid)})

def get_levels(entry,level):
 sp=INITIAL_STOP if level<=0 else level*PROFIT_STEP;tp=INITIAL_TARGET if level<=0 else sp+TARGET_DISTANCE
 return sp,tp,entry*(1+sp),entry*(1+tp)
def current_profit(entry,price):return (price-entry)/entry
def profit_level(p):return 0 if p<PROFIT_STEP else int(math.floor((p+1e-9)/PROFIT_STEP))

def create_oco_for_state(trade,level):
 symbol=trade['symbol'];entry=float(trade['entry']);sp,tp,stop,target=get_levels(entry,level);cur=get_price(symbol)
 if cur>=target:raise Exception(f'السعر الحالي {cur} تجاوز الهدف {target}')
 if cur<=stop:raise Exception(f'السعر الحالي {cur} تحت الوقف {stop}')
 base=symbol[:-4];free=get_asset_free(base);_,step,mq,mn=get_filters(symbol);qty=floor_step(min(free,float(trade['qty'])),step)
 if qty<=0:raise Exception('لا توجد كمية متاحة للبيع')
 if mn>0 and qty*cur<mn:raise Exception(f'قيمة الصفقة أقل من الحد الأدنى {mn}')
 o=place_oco(symbol,qty,stop,target);trade.update({'oco':o,'order_list_id':o['orderListId'],'above_order_id':o['aboveOrderId'],'below_order_id':o['belowOrderId'],'stop_price':o['stop_price'],'target_price':o['target_price'],'locked_profit':sp,'target_profit':tp,'level':level,'stop_status':'ACTIVE','oco_status':'EXECUTING'});save_state(trade)

def open_trade(signal):
 balance=get_usdt_balance();amount=balance*TRADE_USDT_PERCENT
 if amount<MIN_USDT:raise Exception(f'الرصيد {balance:.4f} USDT أقل من {MIN_USDT}')
 symbol=signal['symbol'];r=market_buy(symbol,amount);trade={'symbol':symbol,'entry':r['entry'],'current_price':r['entry'],'qty':r['qty'],'order_id':r['orderId'],'opened_at':now_text(),'profit_percent':0,'profit_usdt':0,'status':'متعادل','status_en':'EVEN','level':0,'locked_profit':INITIAL_STOP,'target_profit':INITIAL_TARGET,'stop_price':r['entry']*(1+INITIAL_STOP),'target_price':r['entry']*(1+INITIAL_TARGET),'order_list_id':None,'above_order_id':None,'below_order_id':None,'stop_status':'PENDING','oco_status':'PENDING'};save_state(trade)
 for attempt in range(5):
  try:create_oco_for_state(trade,0);return trade
  except Exception as e:global last_error;last_error=str(e);log(f'⚠️ OCO محاولة {attempt+1}/5: {e}');time.sleep(min(2*(attempt+1),10))
 raise Exception('فشل إنشاء OCO بعد 5 محاولات')

def record_closed_trade(trade,exit_price,reason):
 h=load_history();entry=float(trade['entry']);qty=float(trade['qty']);gross=(exit_price-entry)*qty;fees=abs(entry*qty)*FEE_RATE+abs(exit_price*qty)*FEE_RATE;net=gross-fees;inv=entry*qty;pp=net/inv*100 if inv>0 else 0
 h.append({'symbol':trade['symbol'],'entry':entry,'exit':exit_price,'qty':qty,'profit_usdt':net,'profit_percent':pp,'opened_at':trade.get('opened_at'),'closed_at':now_text(),'reason':reason});save_history(h)

def manage_position():
 global last_error
 trade=load_state()
 if not trade or not trade.get('symbol'):return
 try:
  symbol=trade['symbol'];price=get_price(symbol);entry=float(trade['entry']);qty=float(trade['qty']);p=current_profit(entry,price);trade.update({'current_price':price,'profit_percent':p*100,'profit_usdt':(price-entry)*qty,'status':'ربح' if p>0 else 'خسارة' if p<0 else 'متعادل','status_en':'PROFIT' if p>0 else 'LOSS' if p<0 else 'EVEN'})
  for key,reason in [('above_order_id','TAKE_PROFIT'),('below_order_id','STOP_LOSS')]:
   oid=trade.get(key)
   if oid:
    try:
     o=get_order(symbol,oid)
     if o.get('status')=='FILLED':
      ex=float(o.get('executedQty',0));quote=float(o.get('cummulativeQuoteQty',0));record_closed_trade(trade,quote/ex if ex>0 else price,reason);save_state({});return
    except Exception as e:last_error=str(e)
  level=profit_level(p);old=int(trade.get('level',0))
  if level>old:
   if cancel_oco(symbol,trade.get('order_list_id')):
    for attempt in range(5):
     try:create_oco_for_state(trade,level);break
     except Exception as e:last_error=str(e);time.sleep(min(2*(attempt+1),10))
  save_state(trade)
 except Exception as e:last_error=str(e);log(f'❌ خطأ إدارة الصفقة: {e}')

def restore_trade():
 trade=load_state()
 if not trade or not trade.get('symbol'):return
 try:
  base=trade['symbol'][:-4];free=get_asset_free(base)
  if free<=0:save_state({});return
  if not trade.get('order_list_id'):create_oco_for_state(trade,int(trade.get('level',0)))
 except Exception as e:log(f'⚠️ استعادة الصفقة: {e}')

def get_klines(symbol,interval,limit):return public_get('/api/v3/klines',{'symbol':symbol,'interval':interval,'limit':limit})
def ema(values,period):
 if len(values)<period:return None
 m=2/(period+1);r=sum(values[:period])/period
 for p in values[period:]:r=(p-r)*m+r
 return r

def scan_symbol(symbol):
 try:
  k=get_klines(symbol,'15m',210);c=[float(x[4]) for x in k];h=[float(x[2]) for x in k];v=[float(x[5]) for x in k];price=c[-1];e15=ema(c[-201:],200);res=max(h[-21:-1]);avg=sum(v[-21:-1])/20;vr=v[-1]/avg if avg>0 else 0;move=(price-c[-2])/c[-2]
  if price<=e15 or price<=res or vr<1.5 or move<.005 or move>.04:return None
  k=get_klines(symbol,'1h',210);c1=[float(x[4]) for x in k];e1=ema(c1[-201:],200)
  if price<=e1:return None
  return {'symbol':symbol,'price':price,'ema200_15':e15,'ema200_1h':e1,'resistance':res,'volume_ratio':vr,'breakout':(price-res)/res,'move':move}
 except Exception:return None

def get_usdt_symbols():
 out=[]
 for s in get_exchange_info().get('symbols',[]):
  if s.get('status')=='TRADING' and s.get('quoteAsset')=='USDT' and s.get('isSpotTradingAllowed') is not False and s['symbol'].endswith('USDT'):out.append(s['symbol'])
 return out

def bot_loop():
 global last_scan,last_signal,last_error,scan_count
 log('🚀 مضارب أبو سعود V2 بدأ');restore_trade()
 while True:
  try:
   trade=load_state()
   if trade and trade.get('symbol'):manage_position();time.sleep(POSITION_CHECK_SECONDS);continue
   last_scan=now_text();scan_count+=1;symbols=get_usdt_symbols();log(f'🔎 فحص {len(symbols)} عملة');found=None
   for symbol in symbols:
    s=scan_symbol(symbol)
    if s:found=s;last_signal=f"{symbol} | BUY | {s['price']}";log(f"🔥 إشارة شراء: {symbol} | {s['price']}");break
   if found:
    try:open_trade(found)
    except Exception as e:last_error=str(e);log(f'❌ فشل فتح الصفقة: {e}')
   time.sleep(SCAN_INTERVAL)
  except Exception as e:
   last_error=str(e);log(f'❌ خطأ رئيسي: {e}');time.sleep(60 if '429' in str(e) else 10)

def calculate_stats():
 h=load_history();now=datetime.now();daily=weekly=monthly=total=0;wins=losses=0
 for t in h:
  try:
   p=float(t.get('profit_usdt',0));total+=p;wins+=p>0;losses+=p<0;dt=datetime.strptime(t['closed_at'],'%Y-%m-%d %H:%M:%S');days=(now-dt).total_seconds()/86400
   if days<=1:daily+=p
   if days<=7:weekly+=p
   if dt.year==now.year and dt.month==now.month:monthly+=p
  except:continue
 n=wins+losses
 return {'daily':daily,'weekly':weekly,'monthly':monthly,'total':total,'trades':n,'wins':wins,'losses':losses,'win_rate':wins/n*100 if n else 0}

@app.route('/api/dashboard')
def dashboard_api():return jsonify({'bot':'مضارب أبو سعود V2 PRO','binance':get_binance_status(),'stats':calculate_stats(),'trade':load_state(),'scan_count':scan_count,'last_scan':last_scan,'last_signal':last_signal,'last_error':last_error,'server_time':now_text()})
@app.route('/health')
def health():return jsonify({'status':'ok','time':now_text()})

HTML='''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>مضارب أبو سعود V2 PRO</title><style>body{margin:0;font-family:Arial;background:#0b1020;color:white}.container{max-width:1100px;margin:auto;padding:20px}h1{text-align:center}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card{background:#151c31;border-radius:15px;padding:18px;margin-bottom:15px}.label{color:#9ca3af;font-size:13px}.value{font-size:22px;font-weight:bold;margin-top:8px}.green{color:#22c55e}.red{color:#ef4444}.row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #27304a}.error{background:#450a0a;color:#f87171;padding:10px;border-radius:10px;margin-top:10px}.status{text-align:center;padding:10px;border-radius:10px;background:#102a1b;color:#22c55e;margin-bottom:15px}.binance-box{text-align:center}</style></head><body><div class="container"><h1>🤖 مضارب أبو سعود V2 PRO</h1><div class="grid"><div class="card binance-box"><div class="label">حالة Binance</div><div id="binanceStatus" class="value">جاري التحقق...</div></div><div class="card binance-box"><div class="label">رصيد Binance</div><div id="binanceBalance" class="value">جاري التحقق...</div></div></div><div class="status">🟢 البوت يعمل</div><div class="grid"><div class="card"><div class="label">ربح اليوم</div><div id="daily" class="value">0</div></div><div class="card"><div class="label">ربح الأسبوع</div><div id="weekly" class="value">0</div></div><div class="card"><div class="label">ربح الشهر</div><div id="monthly" class="value">0</div></div><div class="card"><div class="label">إجمالي الربح</div><div id="total" class="value">0</div></div></div><div class="grid"><div class="card"><div class="label">عدد الصفقات</div><div id="trades" class="value">0</div></div><div class="card"><div class="label">الرابحة</div><div id="wins" class="value green">0</div></div><div class="card"><div class="label">الخاسرة</div><div id="losses" class="value red">0</div></div><div class="card"><div class="label">نسبة النجاح</div><div id="winrate" class="value">0%</div></div></div><div class="card"><h2>📊 الصفقة الحالية</h2><div id="noTrade">لا توجد صفقة مفتوحة</div><div id="trade" style="display:none"><div class="row"><span>العملة</span><b id="symbol"></b></div><div class="row"><span>الدخول</span><b id="entry"></b></div><div class="row"><span>السعر الحالي</span><b id="current"></b></div><div class="row"><span>الربح / الخسارة</span><b id="profit"></b></div><div class="row"><span>الوقف</span><b id="stop"></b></div><div class="row"><span>الهدف</span><b id="target"></b></div><div class="row"><span>الربح المؤمّن</span><b id="locked"></b></div><div class="row"><span>الهدف القادم</span><b id="targetProfit"></b></div><div class="row"><span>مستوى الحماية</span><b id="level"></b></div><div class="row"><span>حالة OCO</span><b id="oco"></b></div></div></div><div class="card"><h2>🤖 حالة البوت</h2><div class="row"><span>عدد الفحوصات</span><b id="scans"></b></div><div class="row"><span>آخر فحص</span><b id="lastScan"></b></div><div class="row"><span>آخر إشارة</span><b id="lastSignal"></b></div><div id="error"></div></div></div><script>function money(x){return Number(x||0).toFixed(4)}async function update(){try{const r=await fetch('/api/dashboard',{cache:'no-store'}),d=await r.json(),b=d.binance||{},s=d.stats;let bs=document.getElementById('binanceStatus'),bb=document.getElementById('binanceBalance');if(b.connected){bs.textContent='🟢 متصل بـ Binance';bs.className='value green';bb.textContent=Number(b.usdt||0).toFixed(4)+' USDT';bb.className='value green'}else{bs.textContent='🔴 غير متصل بـ Binance';bs.className='value red';bb.textContent='غير متاح';bb.className='value red'}daily.textContent=money(s.daily)+' USDT';weekly.textContent=money(s.weekly)+' USDT';monthly.textContent=money(s.monthly)+' USDT';total.textContent=money(s.total)+' USDT';trades.textContent=s.trades;wins.textContent=s.wins;losses.textContent=s.losses;winrate.textContent=Number(s.win_rate).toFixed(1)+'%';scans.textContent=d.scan_count;lastScan.textContent=d.last_scan||'-';lastSignal.textContent=d.last_signal||'-';let t=d.trade;if(t&&t.symbol){noTrade.style.display='none';trade.style.display='block';symbol.textContent=t.symbol;entry.textContent=Number(t.entry||0).toFixed(8);current.textContent=Number(t.current_price||0).toFixed(8);let p=Number(t.profit_percent||0);profit.textContent=p.toFixed(2)+'%';profit.className=p>=0?'green':'red';stop.textContent=Number(t.stop_price||0).toFixed(8);target.textContent=Number(t.target_price||0).toFixed(8);locked.textContent=Number((t.locked_profit||0)*100).toFixed(0)+'%';targetProfit.textContent=Number((t.target_profit||0)*100).toFixed(0)+'%';level.textContent='+'+(t.level||0)+'%';oco.textContent=t.oco_status||'-'}else{noTrade.style.display='block';trade.style.display='none'}error.innerHTML=d.last_error?'<div class="error">⚠️ '+d.last_error+'</div>':''}catch(e){binanceStatus.textContent='🔴 غير متصل بـ Binance';binanceStatus.className='value red';binanceBalance.textContent='غير متاح';binanceBalance.className='value red';error.innerHTML='<div class="error">تعذر الاتصال بالبوت</div>'}}update();setInterval(update,5000)</script></body></html>'''
@app.route('/')
def home():return HTML
def start_bot():threading.Thread(target=bot_loop,daemon=True).start()
if __name__=='__main__':
 start_bot();port=int(os.getenv('PORT','10000'));app.run(host='0.0.0.0',port=port,debug=False,use_reloader=False)

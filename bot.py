# مضارب أبو سعود V2 🤖
# Binance Spot + Public Dashboard + Login/Subscriptions/Admin
import os,time,json,hmac,hashlib,threading,urllib.parse,sqlite3
from decimal import Decimal,ROUND_DOWN
from functools import wraps
import requests
from flask import Flask,jsonify,request,session,redirect,url_for,render_template_string
from werkzeug.security import generate_password_hash,check_password_hash

API_KEY=os.getenv('BINANCE_API_KEY','').strip(); API_SECRET=os.getenv('BINANCE_API_SECRET','').strip()
API_BASE='https://api.binance.com'; MARKET_BASE='https://data-api.binance.vision'
STATE_FILE='state.json'; HISTORY_FILE='trade_history.json'; DB_FILE=os.getenv('DB_FILE','users.db')
INITIAL_STOP=-.02; PROFIT_STEP=.01; MIN_USDT=5.; TRADE_USDT_PERCENT=.999; SCAN_INTERVAL=180; POSITION_CHECK_SECONDS=5
BINANCE_PAY_UID=os.getenv('BINANCE_PAY_UID','28191866'); TRC20_ADDRESS=os.getenv('USDT_TRC20_ADDRESS','TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6')
ADMIN_USERNAME=os.getenv('ADMIN_USERNAME','admin'); ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','ChangeMe123!')
PLANS={'7':('7 أيام',10),'30':('30 يوم',20),'90':('90 يوم',30)}
app=Flask(__name__); app.secret_key=os.getenv('SECRET_KEY','change-this-secret-key')
session_req=requests.Session(); session_req.headers.update({'User-Agent':'Mudarib-Abo-Saud-V2/1.0'}); state_lock=threading.Lock(); _exchange_info=None; _exchange_lock=threading.Lock()

def log(x): print(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {x}',flush=True)
def load_json(f,d):
    try:
        if not os.path.exists(f): return d
        with open(f,encoding='utf-8') as h:return json.load(h)
    except Exception as e: log(f'⚠️ قراءة {f}: {e}'); return d
def save_json(f,d):
    t=f+'.tmp'
    with open(t,'w',encoding='utf-8') as h: json.dump(d,h,ensure_ascii=False,indent=2)
    os.replace(t,f)
def load_state(): return load_json(STATE_FILE,{})
def save_state(d):
    with state_lock: save_json(STATE_FILE,d)
def load_history(): return load_json(HISTORY_FILE,[])
def save_history(d): save_json(HISTORY_FILE,d)

# ---------------- AUTH / SUBSCRIPTIONS ----------------
def db():
    c=sqlite3.connect(DB_FILE,timeout=20); c.row_factory=sqlite3.Row; return c
def init_db():
    c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,is_admin INTEGER DEFAULT 0,active_until TEXT);CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,plan TEXT,method TEXT,reference TEXT,status TEXT DEFAULT 'pending',created_at TEXT,approved_at TEXT);''')
    row=c.execute('SELECT id FROM users WHERE is_admin=1 LIMIT 1').fetchone()
    if not row: c.execute('INSERT INTO users(username,password_hash,is_admin) VALUES(?,?,1)',(ADMIN_USERNAME,generate_password_hash(ADMIN_PASSWORD)))
    c.commit(); c.close()
def current_user():
    uid=session.get('uid')
    if not uid:return None
    c=db(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close(); return r
def login_required(f):
    @wraps(f)
    def w(*a,**k):
        if not current_user(): return redirect(url_for('login',next=request.path))
        return f(*a,**k)
    return w
def admin_required(f):
    @wraps(f)
    def w(*a,**k):
        u=current_user()
        if not u or not u['is_admin']: return redirect(url_for('login'))
        return f(*a,**k)
    return w
def active_subscription(u):
    if not u:return False
    if u['is_admin']:return True
    return bool(u['active_until'] and u['active_until']>=time.strftime('%Y-%m-%d %H:%M:%S'))
def change_admin_credentials(username,password):
    c=db(); u=c.execute('SELECT id FROM users WHERE is_admin=1 LIMIT 1').fetchone(); c.execute('UPDATE users SET username=?,password_hash=? WHERE id=?',(username,generate_password_hash(password),u['id'])); c.commit(); c.close()

def page(title,body):
    return f'''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>body{{background:#0b0f14;color:#fff;font-family:Arial;margin:0;padding:20px}}.card{{max-width:700px;margin:20px auto;background:#121923;border:1px solid #263241;border-radius:18px;padding:20px}}input,select,button{{width:100%;box-sizing:border-box;padding:12px;margin:7px 0;border-radius:10px;border:1px solid #39485a;background:#0d141d;color:#fff}}button{{cursor:pointer;background:#176b46;border:0}}a{{color:#61d89b}}.ok{{color:#35d07f}}.bad{{color:#ff6974}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #263241;text-align:right}}</style>{body}'''

@app.route('/register',methods=['GET','POST'])
def register():
    msg=''
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','')
        if len(u)<3 or len(p)<6: msg='اسم المستخدم 3 أحرف على الأقل وكلمة المرور 6 أحرف على الأقل.'
        else:
            try:
                c=db(); c.execute('INSERT INTO users(username,password_hash) VALUES(?,?)',(u,generate_password_hash(p))); c.commit(); c.close(); return redirect(url_for('login'))
            except sqlite3.IntegrityError: msg='اسم المستخدم مستخدم مسبقاً.'
    return page('تسجيل جديد',f'<div class="card"><h2>👤 إنشاء حساب</h2><div class="bad">{msg}</div><form method="post"><input name="username" placeholder="اسم المستخدم" required><input name="password" type="password" placeholder="كلمة المرور" required><button>إنشاء الحساب</button></form><a href="/login">تسجيل الدخول</a></div>')

@app.route('/login',methods=['GET','POST'])
def login():
    msg=''
    if request.method=='POST':
        u=request.form.get('username','').strip(); p=request.form.get('password','')
        c=db(); r=c.execute('SELECT * FROM users WHERE username=?',(u,)).fetchone(); c.close()
        if r and check_password_hash(r['password_hash'],p): session['uid']=r['id']; return redirect(request.args.get('next') or url_for('account'))
        msg='بيانات الدخول غير صحيحة.'
    return page('تسجيل الدخول',f'<div class="card"><h2>🔐 تسجيل الدخول</h2><div class="bad">{msg}</div><form method="post"><input name="username" placeholder="اسم المستخدم" required><input name="password" type="password" placeholder="كلمة المرور" required><button>دخول</button></form><a href="/register">إنشاء حساب</a></div>')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('home'))

@app.route('/account')
@login_required
def account():
    u=current_user(); status='فعّال' if active_subscription(u) else 'غير مشترك'; admin='<p><a href="/admin">👑 لوحة الأدمن</a></p>' if u['is_admin'] else ''
    return page('حسابي',f'<div class="card"><h2>👤 {u["username"]}</h2><p>الحالة: <b>{status}</b></p><p>ينتهي: {u["active_until"] or "-"}</p><p><a href="/subscribe">💳 الاشتراك</a></p>{admin}<p><a href="/logout">تسجيل خروج</a></p></div>')
@app.route('/subscribe',methods=['GET','POST'])
@login_required
def subscribe():
    u=current_user(); msg=''
    if request.method=='POST':
        plan=request.form.get('plan'); method=request.form.get('method'); ref=request.form.get('reference','').strip()
        if plan not in PLANS or method not in ('binance','trc20'): msg='اختيار غير صحيح.'
        else:
            c=db(); c.execute('INSERT INTO payments(user_id,plan,method,reference,created_at) VALUES(?,?,?,?,?)',(u['id'],plan,method,ref,time.strftime('%Y-%m-%d %H:%M:%S'))); c.commit(); c.close(); msg='تم إرسال طلبك. الأدمن يقدر يفعله بعد التأكد من الدفع.'
    opts=''.join(f'<option value="{k}">{v[0]} — {v[1]} USDT</option>' for k,v in PLANS.items())
    return page('الاشتراك',f'''<div class="card"><h2>💳 الاشتراك</h2><p>Binance Pay UID: <b>{BINANCE_PAY_UID}</b></p><p>USDT TRC20: <b>{TRC20_ADDRESS}</b></p><form method="post"><select name="plan">{opts}</select><select name="method"><option value="binance">Binance Pay</option><option value="trc20">USDT TRC20</option></select><input name="reference" placeholder="رقم العملية / TXID (اختياري)"><button>إرسال طلب الاشتراك</button></form><p class="ok">{msg}</p><a href="/account">رجوع</a></div>''')

@app.route('/admin',methods=['GET','POST'])
@admin_required
def admin():
    msg=''
    if request.method=='POST' and request.form.get('action')=='credentials':
        nu=request.form.get('new_username','').strip(); np=request.form.get('new_password','')
        if len(nu)>=3 and len(np)>=6: change_admin_credentials(nu,np); msg='تم تغيير اسم المستخدم وكلمة المرور.'
        else: msg='الاسم 3 أحرف على الأقل وكلمة المرور 6 أحرف على الأقل.'
    c=db(); users=c.execute('SELECT * FROM users ORDER BY id DESC').fetchall(); payments=c.execute('SELECT p.*,u.username FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC LIMIT 30').fetchall(); c.close()
    us=''.join(f'''<tr><td>{r['username']}</td><td>{'أدمن' if r['is_admin'] else 'مستخدم'}</td><td>{r['active_until'] or '-'}</td><td>{'' if r['is_admin'] else f'<form method="post" action="/admin/activate"><input type="hidden" name="user_id" value="{r["id"]}"><select name="plan"><option value="7">7 أيام</option><option value="30">30 يوم</option><option value="90">90 يوم</option></select><button>تفعيل</button></form>'}</td></tr>''' for r in users)
    ps=''.join(f'''<tr><td>{p['username']}</td><td>{p['plan']} يوم</td><td>{p['method']}</td><td>{p['reference'] or '-'}</td><td>{p['status']}</td><td>{'' if p['status']!='pending' else f'<form method="post" action="/admin/approve"><input type="hidden" name="payment_id" value="{p["id"]}"><button>تفعيل</button></form>'}</td></tr>''' for p in payments)
    return page('لوحة الأدمن',f'''<div class="card"><h2>👑 لوحة الأدمن</h2><p class="ok">{msg}</p><h3>تغيير بيانات الأدمن</h3><form method="post"><input type="hidden" name="action" value="credentials"><input name="new_username" placeholder="اسم المستخدم الجديد"><input name="new_password" type="password" placeholder="كلمة المرور الجديدة"><button>حفظ</button></form><h3>المستخدمون</h3><table><tr><th>المستخدم</th><th>النوع</th><th>ينتهي</th><th>إجراء</th></tr>{us}</table><h3>طلبات الدفع</h3><table><tr><th>المستخدم</th><th>الخطة</th><th>الدفع</th><th>المرجع</th><th>الحالة</th><th></th></tr>{ps}</table><p><a href="/logout">تسجيل خروج</a></p></div>''')

def activate(uid,days):
    c=db(); r=c.execute('SELECT active_until FROM users WHERE id=?',(uid,)).fetchone(); now=time.time(); base=now
    if r and r['active_until']:
        try:
            old=time.mktime(time.strptime(r['active_until'],'%Y-%m-%d %H:%M:%S')); base=max(now,old)
        except: pass
    until=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(base+days*86400)); c.execute('UPDATE users SET active_until=? WHERE id=?',(until,uid)); c.commit(); c.close(); return until
@app.route('/admin/activate',methods=['POST'])
@admin_required
def admin_activate(): activate(int(request.form['user_id']),int(request.form['plan'])); return redirect('/admin')
@app.route('/admin/approve',methods=['POST'])
@admin_required
def admin_approve():
    c=db(); p=c.execute('SELECT * FROM payments WHERE id=?',(int(request.form['payment_id']),)).fetchone();
    if p and p['status']=='pending': activate(p['user_id'],int(p['plan'])); c.execute("UPDATE payments SET status='approved',approved_at=? WHERE id=?",(time.strftime('%Y-%m-%d %H:%M:%S'),p['id'])); c.commit()
    c.close(); return redirect('/admin')

# ---------------- BINANCE ----------------
def signed_request(method,path,params=None):
    if not API_KEY or not API_SECRET: raise Exception('BINANCE_API_KEY / BINANCE_API_SECRET غير موجودة')
    p=dict(params or {}); p['timestamp']=int(time.time()*1000); p['recvWindow']=10000; q=urllib.parse.urlencode(p,doseq=True); sig=hmac.new(API_SECRET.encode(),q.encode(),hashlib.sha256).hexdigest(); r=session_req.request(method,API_BASE+path+'?'+q+'&signature='+sig,headers={'X-MBX-APIKEY':API_KEY},timeout=20)
    try:d=r.json()
    except:d=r.text
    if r.status_code>=400: raise Exception(f'HTTP {r.status_code} | {d}')
    return d
def public_get(path,params=None):
    for a in range(4):
        try:
            r=session_req.get(MARKET_BASE+path,params=params or {},timeout=15)
            if r.status_code in (418,429): time.sleep(min(30,2**a+1)); continue
            r.raise_for_status(); return r.json()
        except Exception:
            if a==3: raise
            time.sleep(2)
def get_account(): return signed_request('GET','/api/v3/account')
def get_usdt_balance(): return next((float(b['free']) for b in get_account().get('balances',[]) if b['asset']=='USDT'),0.)
def get_asset_balance(asset): return next((float(b['free'])+float(b['locked']) for b in get_account().get('balances',[]) if b['asset']==asset),0.)
def get_exchange_info():
    global _exchange_info
    if _exchange_info is not None:return _exchange_info
    with _exchange_lock:
        if _exchange_info is None:_exchange_info=public_get('/api/v3/exchangeInfo')
    return _exchange_info
def get_symbol_info(symbol): return next((s for s in get_exchange_info().get('symbols',[]) if s['symbol']==symbol),None)
def get_filters(symbol):
    s=get_symbol_info(symbol)
    if not s: raise Exception(f'العملة غير موجودة: {symbol}')
    x={'stepSize':0.,'minQty':0.,'minNotional':0.,'tickSize':0.}
    for f in s.get('filters',[]):
        if f['filterType']=='LOT_SIZE':x['stepSize']=float(f['stepSize']);x['minQty']=float(f['minQty'])
        elif f['filterType'] in ('MIN_NOTIONAL','NOTIONAL'):x['minNotional']=float(f.get('minNotional',0))
        elif f['filterType']=='PRICE_FILTER':x['tickSize']=float(f['tickSize'])
    return x
def floor_step(v,s):
    if s<=0:return v
    return float((Decimal(str(v))/Decimal(str(s))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(s)))
def get_price(symbol): return float(public_get('/api/v3/ticker/price',{'symbol':symbol})['price'])
def market_buy(symbol,amount):
    try:
        f=get_filters(symbol)
        if f['minNotional']>0 and amount<f['minNotional']:raise Exception(f'المبلغ أقل من MIN_NOTIONAL ({f["minNotional"]})')
        r=signed_request('POST','/api/v3/order',{'symbol':symbol,'side':'BUY','type':'MARKET','quoteOrderQty':f'{amount:.8f}','newOrderRespType':'FULL'}); q=float(r.get('executedQty',0)); cq=float(r.get('cummulativeQuoteQty',0))
        if q<=0 or cq<=0:raise Exception(f'Binance لم تنفذ الكمية | {r}')
        return {'symbol':symbol,'qty':q,'entry':cq/q,'orderId':r.get('orderId'),'quote':cq}
    except Exception as e:log(f'❌ فشل شراء Binance: {e}');return None
def place_stop(symbol,qty,price):
    try:
        f=get_filters(symbol); qty=floor_step(qty,f['stepSize']); price=floor_step(price,f['tickSize'])
        if qty<=0 or price<=0:raise Exception('الكمية/السعر غير صحيح')
        return signed_request('POST','/api/v3/order',{'symbol':symbol,'side':'SELL','type':'STOP_LOSS','quantity':f'{qty:.8f}','stopPrice':f'{price:.8f}','newOrderRespType':'RESULT'})
    except Exception as e:log(f'❌ فشل وضع وقف Binance: {e}');return None
def cancel_order(symbol,oid):
    try:return signed_request('DELETE','/api/v3/order',{'symbol':symbol,'orderId':oid})
    except Exception as e:log(f'⚠️ فشل إلغاء الوقف: {e}')
def get_order(symbol,oid):
    try:return signed_request('GET','/api/v3/order',{'symbol':symbol,'orderId':oid})
    except:return None
def position_exists(symbol):
    try:
        return get_asset_balance(symbol.replace('USDT',''))>=get_filters(symbol)['minQty']
    except:return False

def ensure_initial_stop(s):
    if s.get('stop_order_id'):return s
    p=float(s['entry'])*(1+INITIAL_STOP); r=place_stop(s['symbol'],s['qty'],p)
    if r:s['stop_order_id']=r.get('orderId');s['stop_price']=p;s['locked_profit']=INITIAL_STOP;save_state(s)
    return s
def raise_stop(s,profit):
    level=int(profit/PROFIT_STEP)
    if level<1:return s
    lock=level*PROFIT_STEP; old=float(s.get('locked_profit',INITIAL_STOP))
    if lock<=old:return s
    oid=s.get('stop_order_id')
    if oid:
        o=get_order(s['symbol'],oid)
        if o and o.get('status')=='NEW':cancel_order(s['symbol'],oid)
    p=float(s['entry'])*(1+lock); r=place_stop(s['symbol'],s['qty'],p)
    if r:s['stop_order_id']=r.get('orderId');s['stop_price']=p;s['locked_profit']=lock;save_state(s);log(f'🔒 تأمين ربح {lock*100:.0f}%')
    return s
def manage_position(s):
    s=ensure_initial_stop(s); save_state(s); symbol=s['symbol']
    while True:
        try:
            if not position_exists(symbol):
                cur=get_price(symbol); ent=float(s['entry']); qty=float(s['qty']); prof=(cur-ent)/ent; h=load_history();h.append({'symbol':symbol,'entry':ent,'exit':cur,'profit_percent':prof*100,'profit_usdt':(cur-ent)*qty,'time':time.strftime('%Y-%m-%d %H:%M:%S')});save_history(h[-500:]);save_state({});return
            cur=get_price(symbol);ent=float(s['entry']);qty=float(s['qty']);prof=(cur-ent)/ent;s.update(current_price=cur,profit_percent=prof*100,profit_usdt=(cur-ent)*qty);save_state(s)
            if prof>=PROFIT_STEP:s=raise_stop(s,prof)
            oid=s.get('stop_order_id')
            if oid:
                o=get_order(symbol,oid)
                if o and o.get('status')=='FILLED': time.sleep(2);save_state({});return
            time.sleep(POSITION_CHECK_SECONDS)
        except Exception as e:log(f'⚠️ خطأ متابعة الصفقة: {e}');time.sleep(5)
def restore_trade():
    s=load_state();
    if not s or not s.get('symbol'):return False
    if position_exists(s['symbol']):manage_position(s);return True
    save_state({});return False
def get_usdt_symbols(): return [s['symbol'] for s in get_exchange_info().get('symbols',[]) if s.get('status')=='TRADING' and s.get('quoteAsset')=='USDT' and s.get('isSpotTradingAllowed') is not False]
def get_klines(symbol,interval,limit=210):return public_get('/api/v3/klines',{'symbol':symbol,'interval':interval,'limit':limit})
def ema(v,p):
    if len(v)<p:return None
    m=2/(p+1);r=sum(v[:p])/p
    for x in v[p:]:r=(x-r)*m+r
    return r
def scan_symbol(symbol):
    try:
        k=get_klines(symbol,'15m',210)
        if len(k)<205:return False
        c=[float(x[4]) for x in k];h=[float(x[2]) for x in k];vol=[float(x[5]) for x in k];price=c[-1];e15=ema(c[-201:],200);res=max(h[-21:-1]);avg=sum(vol[-21:-1])/20;vr=vol[-1]/avg if avg else 0;move=(price-c[-2])/c[-2]
        if not e15 or price<=e15 or price<=res or vr<1.5 or move<.005 or move>.04:return False
        k1=get_klines(symbol,'1h',210);c1=[float(x[4]) for x in k1];e1=ema(c1[-201:],200)
        return bool(e1 and price>e1)
    except:return False
def open_trade(symbol):
    bal=get_usdt_balance();amount=bal*TRADE_USDT_PERCENT
    if amount<MIN_USDT:return False
    r=market_buy(symbol,amount)
    if not r:return False
    s={'symbol':symbol,'entry':r['entry'],'current_price':r['entry'],'qty':r['qty'],'order_id':r['orderId'],'opened_at':time.strftime('%Y-%m-%d %H:%M:%S'),'profit_percent':0,'profit_usdt':0,'locked_profit':INITIAL_STOP,'stop_price':r['entry']*(1+INITIAL_STOP),'stop_order_id':None};save_state(s);manage_position(s);return True
def bot_loop():
    time.sleep(3);log('🤖 مضارب أبو سعود V2 | Binance Spot | 15m + 1h')
    if not API_KEY or not API_SECRET:return
    while True:
        try:
            if restore_trade():continue
            if get_usdt_balance()<MIN_USDT:time.sleep(SCAN_INTERVAL);continue
            for symbol in get_usdt_symbols():
                if load_state().get('symbol'):break
                if scan_symbol(symbol) and open_trade(symbol):break
                time.sleep(.08)
            time.sleep(SCAN_INTERVAL)
        except Exception as e:log(f'❌ خطأ رئيسي: {e}');time.sleep(10)

# ---------------- PUBLIC DASHBOARD ----------------
DASH='''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>مضارب أبو سعود V2</title><style>body{margin:0;background:#0b0f14;color:#fff;font-family:Arial}.container{max-width:1100px;margin:auto;padding:20px}.card{background:#121923;border:1px solid #263241;border-radius:18px;padding:20px;margin-bottom:15px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.box{background:#0d141d;padding:15px;border-radius:14px}.value{font-size:22px;font-weight:bold;margin-top:8px}.green{color:#35d07f}.red{color:#ff5c67}.small{color:#98a5b5;font-size:13px}a{color:#61d89b}</style><script>async function update(){try{let r=await fetch('/api/dashboard'),d=await r.json();document.getElementById('status').innerText=d.online?'🟢 ONLINE':'🔴 OFFLINE';document.getElementById('balance').innerText=Number(d.balance).toFixed(4)+' USDT';let t=d.trade;if(t&&t.symbol){document.getElementById('trade').innerHTML=`<div class="grid"><div class="box">العملة<div class="value">${t.symbol}</div></div><div class="box">الدخول<div class="value">${t.entry}</div></div><div class="box">السعر الحالي<div class="value">${t.current_price}</div></div><div class="box">الربح<div class="value ${t.profit_percent>=0?'green':'red'}">${Number(t.profit_percent).toFixed(2)}%</div></div><div class="box">الربح USDT<div class="value">${Number(t.profit_usdt).toFixed(4)}</div></div><div class="box">وقف Binance<div class="value">${t.stop_price||'-'}</div></div><div class="box">تأمين الربح<div class="value">${(Number(t.locked_profit||-.02)*100).toFixed(0)}%</div></div></div>`}else document.getElementById('trade').innerHTML='<div class="small">لا توجد صفقة مفتوحة حالياً</div>'}catch(e){document.getElementById('status').innerText='🔴 خطأ اتصال'}}setInterval(update,5000);window.onload=update;</script></head><body><div class="container"><div class="card"><h1>🤖 مضارب أبو سعود V2</h1><div id="status">جاري الاتصال...</div><div style="margin-top:10px"><a href="/login">🔐 دخول</a>　<a href="/register">👤 إنشاء حساب</a></div></div><div class="card"><div class="grid"><div class="box">الرصيد<div id="balance" class="value">...</div></div><div class="box">الفريم<div class="value">15m + 1h</div></div><div class="box">وقف البداية<div class="value">-2%</div></div><div class="box">تأمين الربح<div class="value">كل +1%</div></div></div></div><div class="card"><h2>📊 الصفقة الحالية</h2><div id="trade">جاري التحميل...</div></div></div></body></html>'''
@app.route('/')
def home():return DASH
@app.route('/api/dashboard')
def dashboard():
    try:b=get_usdt_balance();connected=True
    except:b=0;connected=False
    return jsonify({'online':True,'binance_connected':connected,'balance':b,'trade':load_state() or None})
@app.route('/health')
def health():return jsonify(status='ok',bot='Mudarib Abo Saud V2')

init_db()
threading.Thread(target=bot_loop,daemon=True).start()
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')),threaded=True)

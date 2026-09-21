import os, time, random, sqlite3, secrets, smtplib
from email.message import EmailMessage
from functools import wraps
from flask import Flask, jsonify, request, render_template, session, redirect, url_for, flash
import requests

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
DB='site.db'
BINANCE='https://api.binance.com'
TRC20='TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6'
PAY_ID='28191866'

FREE_TOOLS=['السوق','الأسعار','البحث','الرسم البياني','المؤشرات الأساسية','المفضلة']
PREMIUM_TOOLS=['الماسح المتقدم','التحليل الكلاسيكي','الأنماط','الهارمونيك','السيولة والحجم','تحليل العقود الآجلة','التحليل متعدد الفريمات','الإشارات المتقدمة','التنبيهات','سجل الإشارات']

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,verified INTEGER DEFAULT 0,code TEXT,code_exp INTEGER,premium_until INTEGER DEFAULT 0,created_at INTEGER);
    CREATE TABLE IF NOT EXISTS sections(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,description TEXT DEFAULT '',premium INTEGER DEFAULT 1,enabled INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT,side TEXT,entry REAL,tp1 REAL,tp2 REAL,tp3 REAL,sl REAL,score INTEGER,reason TEXT,created_at INTEGER);
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT,method TEXT,reference TEXT,status TEXT DEFAULT 'pending',created_at INTEGER);
    ''')
    if c.execute('SELECT COUNT(*) FROM sections').fetchone()[0]==0:
        for i,n in enumerate(PREMIUM_TOOLS): c.execute('INSERT INTO sections(name,description,premium,sort_order) VALUES(?,?,1,?)',(n,'تحليل متقدم تلقائي للعملات الرقمية',i))
    c.commit(); c.close()
init_db()

def send_code(email,code):
    host=os.getenv('SMTP_HOST'); user=os.getenv('SMTP_USER'); password=os.getenv('SMTP_PASSWORD'); port=int(os.getenv('SMTP_PORT','587'))
    if not (host and user and password): return False
    msg=EmailMessage(); msg['Subject']='رمز دخول موقع تحليل العملات الرقمية'; msg['From']=user; msg['To']=email
    msg.set_content(f'رمز التحقق الخاص بك هو: {code}\n\nالرمز صالح لمدة 10 دقائق.')
    with smtplib.SMTP(host,port,timeout=15) as s:
        s.starttls(); s.login(user,password); s.send_message(msg)
    return True

def current_user():
    if 'uid' not in session: return None
    return db().execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()

def premium_required(f):
    @wraps(f)
    def w(*a,**kw):
        u=current_user()
        if not u or not u['verified'] or u['premium_until'] < int(time.time()): return jsonify({'error':'Premium مطلوب'}),403
        return f(*a,**kw)
    return w

@app.route('/')
def home(): return render_template('index.html',user=current_user(),sections=db().execute('SELECT * FROM sections WHERE enabled=1 ORDER BY sort_order,id').fetchall())

@app.post('/api/login')
def login():
    email=request.json.get('email','').strip().lower()
    if '@' not in email: return jsonify({'error':'اكتب إيميل صحيح'}),400
    code=f'{random.randint(0,999999):06d}'; now=int(time.time()); c=db();
    c.execute('INSERT INTO users(email,code,code_exp,created_at) VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET code=excluded.code,code_exp=excluded.code_exp',(email,code,now+600,now)); c.commit(); c.close()
    try: sent=send_code(email,code)
    except Exception: sent=False
    if not sent:
        # Dev fallback: never expose in production if SMTP is configured.
        return jsonify({'ok':True,'message':'SMTP غير مضبوط. أضف بيانات البريد في Render Environment Variables.','dev_code':code})
    return jsonify({'ok':True,'message':'تم إرسال رمز التحقق إلى الإيميل'})

@app.post('/api/verify')
def verify():
    data=request.json; email=data.get('email','').strip().lower(); code=data.get('code','').strip(); c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    if not u or u['code']!=code or u['code_exp']<int(time.time()): return jsonify({'error':'الرمز غير صحيح أو منتهي'}),400
    c.execute('UPDATE users SET verified=1,code=NULL WHERE id=?',(u['id'],)); c.commit(); session['uid']=u['id']; return jsonify({'ok':True})

@app.post('/api/logout')
def logout(): session.clear(); return jsonify({'ok':True})

@app.get('/api/binance/markets')
def markets():
    info=requests.get(BINANCE+'/api/v3/exchangeInfo',timeout=12).json(); tick=requests.get(BINANCE+'/api/v3/ticker/24hr',timeout=12).json(); allowed={x['symbol'] for x in info['symbols'] if x.get('status')=='TRADING' and x.get('quoteAsset')=='USDT' and x.get('isSpotTradingAllowed',True)}
    out=[]
    for x in tick:
        if x['symbol'] in allowed:
            out.append({'symbol':x['symbol'],'price':float(x['lastPrice']),'change':float(x['priceChangePercent']),'volume':float(x['quoteVolume'])})
    out.sort(key=lambda z:z['volume'],reverse=True); return jsonify(out[:600])

def ema(vals,p):
    if len(vals)<p:return vals[-1]
    k=2/(p+1); e=sum(vals[:p])/p
    for v in vals[p:]: e=v*k+e*(1-k)
    return e

def rsi(vals,p=14):
    if len(vals)<=p:return 50
    gains=[];loss=[]
    for a,b in zip(vals[-p-1:-1],vals[-p:]):
        d=b-a; gains.append(max(d,0)); loss.append(max(-d,0))
    ag=sum(gains)/p; al=sum(loss)/p
    return 100 if al==0 else 100-(100/(1+ag/al))

@app.get('/api/binance/analysis')
def analysis():
    sym=request.args.get('symbol','BTCUSDT').upper(); interval=request.args.get('interval','15m');
    rows=requests.get(BINANCE+'/api/v3/klines',params={'symbol':sym,'interval':interval,'limit':250},timeout=12).json()
    closes=[float(x[4]) for x in rows]; vols=[float(x[5]) for x in rows]; price=closes[-1]; e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200); rv=rsi(closes); avgvol=sum(vols[-21:-1])/20; vol=vols[-1]
    score=50; reasons=[]
    if price>e20: score+=8; reasons.append('السعر فوق متوسط 20')
    else: score-=8; reasons.append('السعر تحت متوسط 20')
    if e20>e50: score+=10; reasons.append('اتجاه متوسطات إيجابي')
    else: score-=10; reasons.append('اتجاه متوسطات سلبي')
    if price>e200: score+=10; reasons.append('السعر فوق متوسط 200')
    else: score-=10; reasons.append('السعر تحت متوسط 200')
    if 50<=rv<=70: score+=8; reasons.append('مؤشر القوة النسبية داعم')
    elif rv>70: score-=5; reasons.append('مؤشر القوة النسبية مرتفع')
    if vol>avgvol*1.5: score+=8; reasons.append('حجم تداول مرتفع')
    score=max(0,min(100,score)); side='شراء قوي' if score>=80 else 'شراء' if score>=65 else 'حيادي' if score>=45 else 'بيع' if score>=30 else 'بيع قوي'
    return jsonify({'symbol':sym,'interval':interval,'price':price,'score':score,'signal':side,'ema20':e20,'ema50':e50,'ema200':e200,'rsi':rv,'volume_ratio':vol/avgvol if avgvol else 0,'reasons':reasons,'candles':rows[-100:]})

@app.get('/api/sections')
def sections(): return jsonify([dict(x) for x in db().execute('SELECT * FROM sections WHERE enabled=1 ORDER BY sort_order,id').fetchall()])

@app.post('/api/payment')
def payment():
    u=current_user();
    if not u:return jsonify({'error':'سجل الدخول أولاً'}),401
    d=request.json; ref=d.get('reference','').strip(); method=d.get('method','USDT TRC20');
    c=db(); c.execute('INSERT INTO payments(email,method,reference,created_at) VALUES(?,?,?,?)',(u['email'],method,ref,int(time.time()))); c.commit(); return jsonify({'ok':True,'message':'تم إرسال طلب الدفع للمراجعة'})

@app.get('/admin')
def admin():
    if request.args.get('key') != os.getenv('ADMIN_KEY','change-me'): return 'غير مصرح',403
    return render_template('admin.html',sections=db().execute('SELECT * FROM sections ORDER BY sort_order,id').fetchall(),payments=db().execute('SELECT * FROM payments ORDER BY id DESC LIMIT 50').fetchall())

@app.post('/admin/section')
def admin_section():
    if request.args.get('key') != os.getenv('ADMIN_KEY','change-me'): return jsonify({'error':'غير مصرح'}),403
    d=request.json; c=db(); c.execute('INSERT INTO sections(name,description,premium,enabled,sort_order) VALUES(?,?,?,?,?)',(d['name'],d.get('description',''),int(d.get('premium',1)),1,int(d.get('sort_order',0)))); c.commit(); return jsonify({'ok':True})

@app.post('/admin/activate')
def admin_activate():
    if request.args.get('key') != os.getenv('ADMIN_KEY','change-me'): return jsonify({'error':'غير مصرح'}),403
    d=request.json; c=db(); c.execute("UPDATE users SET premium_until=? WHERE email=?",(int(time.time())+30*86400,d['email'].strip().lower())); c.commit(); return jsonify({'ok':True})

@app.get('/health')
def health(): return 'ok'

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')))

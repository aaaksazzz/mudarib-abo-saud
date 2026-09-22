import os,time,hashlib,hmac,secrets,threading,html
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed
from xml.etree import ElementTree as ET
import requests,psycopg
from flask import Flask,jsonify,render_template,request,session

app=Flask(__name__,template_folder='templates',static_folder='static')
app.secret_key=os.getenv('SECRET_KEY','change-this-secret-key')
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True,PERMANENT_SESSION_LIFETIME=timedelta(days=30))
DATABASE_URL=os.getenv('DATABASE_URL','')
ADMIN_USERNAME=os.getenv('ADMIN_USERNAME','aaaksazzz')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','')
PAYMENT_ADDRESS=os.getenv('TRC20_ADDRESS','TMWUt7upZhPDtaKDxVzCHh4uhL7ZVM2PN6')
PLANS={'7d':{'name':'7 أيام','days':7,'amount':10.0},'15d':{'name':'15 يوم','days':15,'amount':20.0},'30d':{'name':'30 يوم','days':30,'amount':30.0}}
BINANCE_BASES=['https://data-api.binance.vision','https://api.binance.com','https://api-gcp.binance.com']
BYBIT_BASE='https://api.bybit.com'
SAUDI_MARKET_SERVER=os.getenv('SAUDI_MARKET_SERVER','https://mwq-tdwl.onrender.com')
YAHOO_BASE='https://query1.finance.yahoo.com'
HTTP=requests.Session();HTTP.headers.update({'User-Agent':'Mudarib-Abo-Saud/2.0'})
CACHE={};LOCK=threading.Lock();MARKET_CACHE={'ts':0,'symbols':[]};BYBIT={'ts':0,'tickers':[],'instruments':{}};YAHOO={}
STABLE={'USDT','USDC','FDUSD','TUSD','USDE','DAI','USDP','USDD'}
INTERVALS={'5m','15m','1h','4h','1d'}
US_SYMBOLS=['AAPL','MSFT','NVDA','AMZN','META','GOOGL','GOOG','TSLA','AVGO','AMD','NFLX','JPM','WMT','ORCL','COST','LLY','XOM','V','MA','PLTR','MU','CRM','QCOM','INTC','BA','COIN','MSTR','CVX','JNJ','BAC']
US_NAMES={'AAPL':'Apple','MSFT':'Microsoft','NVDA':'NVIDIA','AMZN':'Amazon','META':'Meta','GOOGL':'Alphabet','GOOG':'Alphabet','TSLA':'Tesla','AVGO':'Broadcom','AMD':'AMD','NFLX':'Netflix','JPM':'JPMorgan','WMT':'Walmart','ORCL':'Oracle','COST':'Costco','LLY':'Eli Lilly','XOM':'Exxon Mobil','V':'Visa','MA':'Mastercard','PLTR':'Palantir','MU':'Micron','CRM':'Salesforce','QCOM':'Qualcomm','INTC':'Intel','BA':'Boeing','COIN':'Coinbase','MSTR':'Strategy','CVX':'Chevron','JNJ':'Johnson & Johnson','BAC':'Bank of America'}

def f(x,d=0.0):
    try:return float(x)
    except:return d
def now():return datetime.now(timezone.utc)
def err(msg,status=400):return jsonify({'ok':False,'error':msg}),status
def cget(k,age):
    with LOCK:
        x=CACHE.get(k)
        return x['data'] if x and time.time()-x['ts']<age else None
def cset(k,data):
    with LOCK:CACHE[k]={'ts':time.time(),'data':data}
    return data

# ---------------- DB ----------------
def db_conn():
    if not DATABASE_URL: raise RuntimeError('DATABASE_URL غير موجود في Render')
    return psycopg.connect(DATABASE_URL)
def init_db():
    if not DATABASE_URL:return
    with db_conn() as c:
        with c.cursor() as q:
            q.execute('''CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY,username TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,is_admin BOOLEAN NOT NULL DEFAULT FALSE,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),subscription_expires_at TIMESTAMPTZ)''')
            q.execute('''CREATE TABLE IF NOT EXISTS payments(id BIGSERIAL PRIMARY KEY,user_id BIGINT NOT NULL,plan TEXT NOT NULL,amount NUMERIC(12,2) NOT NULL,txid TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
        c.commit()
def hash_password(p):
    s=secrets.token_bytes(16);d=hashlib.pbkdf2_hmac('sha256',str(p).encode(),s,120000);return s.hex()+':'+d.hex()
def verify_password(p,v):
    try:
        s,d=str(v).split(':',1);x=hashlib.pbkdf2_hmac('sha256',str(p).encode(),bytes.fromhex(s),120000);return hmac.compare_digest(x.hex(),d)
    except:return False
def user_row(u):
    with db_conn() as c:
        with c.cursor() as q:q.execute('SELECT id,username,password_hash,is_admin,created_at,subscription_expires_at FROM users WHERE username=%s',(u,));return q.fetchone()
def user_json(r):
    if not r:return None
    return {'id':r[0],'username':r[1],'admin':bool(r[3]),'created_at':r[4].isoformat() if r[4] else None,'subscription_expires_at':r[5].isoformat() if r[5] else None}
def current_user():
    u=session.get('username')
    if not u:return None
    try:return user_row(u)
    except:return None
def admin():
    r=current_user();return bool(r and (r[3] or r[1]==ADMIN_USERNAME))

# ---------------- indicators ----------------
def ema(v,n):
    v=[f(x) for x in v]
    if not v:return 0
    if len(v)<n:return sum(v)/len(v)
    k=2/(n+1);r=sum(v[:n])/n
    for x in v[n:]:r=x*k+r*(1-k)
    return r
def rsi(v,n=14):
    v=[f(x) for x in v]
    if len(v)<=n:return 50
    g=[max(v[i]-v[i-1],0) for i in range(1,len(v))];l=[max(v[i-1]-v[i],0) for i in range(1,len(v))]
    ag=sum(g[:n])/n;al=sum(l[:n])/n
    for i in range(n,len(g)):ag=((ag*(n-1))+g[i])/n;al=((al*(n-1))+l[i])/n
    if al==0:return 100
    return 100-100/(1+ag/al)
def atr(k,n=14):
    if len(k)<2:return 0
    z=[]
    for i in range(1,len(k)):
        pc=f(k[i-1][4]);h=f(k[i][2]);l=f(k[i][3]);z.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(z[-n:])/min(n,len(z)) if z else 0
def analyze(k):
    if len(k)<30:return {'signal':'neutral','score':50,'score10':5,'price':0,'change':0,'entry':0,'tp1':0,'sl':0}
    cl=[f(x[4]) for x in k];vol=[f(x[5]) for x in k];p=cl[-1];e20=ema(cl,20);e50=ema(cl,50);e200=ema(cl,200);rv=rsi(cl);prev=cl[-2];chg=(p-prev)/prev*100 if prev else 0
    av=sum(vol[-21:-1])/max(1,len(vol[-21:-1]));vr=vol[-1]/av if av else 1;score=50
    score+=8 if p>e20 else -8;score+=10 if p>e50 else -10;score+=10 if p>e200 else -10
    score+=8 if rv>=55 else (-8 if rv<=45 else 0);score+=min(8,chg*2) if chg>0 else max(-8,chg*2);score+=5 if vr>=1.5 else 0
    score=max(0,min(100,score));sig='buy' if score>=62 else ('sell' if score<=38 else 'neutral');a=atr(k) or p*.01
    if sig=='buy':tp=p+max(a*1.5,p*.02);sl=p-max(a,p*.01)
    elif sig=='sell':tp=p-max(a*1.5,p*.02);sl=p+max(a,p*.01)
    else:tp=sl=p
    return {'signal':sig,'score':round(score,1),'score10':round(score/10,1),'price':p,'change':round(chg,4),'entry':p,'tp1':tp,'sl':sl,'ema20':e20,'ema50':e50,'ema200':e200,'rsi':round(rv,2),'volume_ratio':round(vr,2)}

# ---------------- Binance public ----------------
def binance_get(path,params=None,timeout=8):
    last=None
    for b in BINANCE_BASES:
        try:
            r=HTTP.get(b+path,params=params or {},timeout=timeout)
            if r.status_code==429:raise RuntimeError('Binance rate limit')
            r.raise_for_status();return r.json()
        except Exception as e:last=e
    raise RuntimeError(f'تعذر الاتصال بمصدر Binance: {last}')
def market_symbols():
    with LOCK:
        if MARKET_CACHE['symbols'] and time.time()-MARKET_CACHE['ts']<300:return MARKET_CACHE['symbols']
    d=binance_get('/api/v3/exchangeInfo');s=[x['symbol'] for x in d.get('symbols',[]) if x.get('status')=='TRADING' and x.get('quoteAsset')=='USDT' and x.get('isSpotTradingAllowed',True)]
    with LOCK:MARKET_CACHE.update(ts=time.time(),symbols=s)
    return s

@app.get('/api/binance/test')
def btest():
    try:return jsonify({'ok':True,'connected':True,'data':binance_get('/api/v3/ping')})
    except Exception as e:return jsonify({'ok':False,'connected':False,'error':str(e)})
@app.get('/api/binance/markets')
def bmarkets():
    try:return jsonify({'ok':True,'symbols':market_symbols()})
    except Exception as e:return err(str(e),502)
@app.get('/api/binance/prices')
def bprices():
    try:return jsonify({'ok':True,'prices':binance_get('/api/v3/ticker/24hr')})
    except Exception as e:return err(str(e),502)
@app.get('/api/binance/price')
def bprice():
    s=request.args.get('symbol','BTCUSDT').upper()
    try:d=binance_get('/api/v3/ticker/price',{'symbol':s});return jsonify({'ok':True,'symbol':s,'price':f(d.get('price'))})
    except Exception as e:return err(str(e),502)
@app.get('/api/binance/klines')
def bklines():
    s=request.args.get('symbol','BTCUSDT').upper();i=request.args.get('interval','15m')
    if i not in INTERVALS:return err('الفاصل غير مدعوم')
    try:return jsonify({'ok':True,'symbol':s,'interval':i,'klines':binance_get('/api/v3/klines',{'symbol':s,'interval':i,'limit':250})})
    except Exception as e:return err(str(e),502)
@app.get('/api/binance/analysis')
def banalysis():
    s=request.args.get('symbol','BTCUSDT').upper();i=request.args.get('interval','15m')
    if i not in INTERVALS:return err('الفاصل غير مدعوم')
    try:
        a=analyze(binance_get('/api/v3/klines',{'symbol':s,'interval':i,'limit':250}));a.update(symbol=s,interval=i,source='Binance');return jsonify({'ok':True,'analysis':a})
    except Exception as e:return err(str(e),502)
@app.get('/api/binance/scan')
def bscan():
    i=request.args.get('interval','15m');key='scan:'+i;old=cget(key,45)
    if old:return jsonify(old)
    try:
        sy=market_symbols();ticks={x.get('symbol'):x for x in binance_get('/api/v3/ticker/24hr')};cand=sorted([(s,f(ticks.get(s,{}).get('quoteVolume')) ) for s in sy if f(ticks.get(s,{}).get('quoteVolume'))>=1000000],key=lambda x:x[1],reverse=True)[:80];out=[]
        def w(s):
            try:
                a=analyze(binance_get('/api/v3/klines',{'symbol':s,'interval':i,'limit':120},7));a.update(symbol=s,interval=i,source='Binance');return a
            except:return None
        with ThreadPoolExecutor(max_workers=8) as ex:
            for x in as_completed([ex.submit(w,s) for s,_ in cand]):
                a=x.result()
                if a:out.append(a)
        out.sort(key=lambda x:(2 if x['signal']!='neutral' else 1,x['score']),reverse=True);p={'ok':True,'interval':i,'results':out,'signals':out};return jsonify(cset(key,p))
    except Exception as e:return err(str(e),502)

# ---------------- Auth/subscription/admin ----------------
@app.get('/api/auth/me')
def me():
    r=current_user();return jsonify({'ok':True,'user':user_json(r),'admin':bool(r and (r[3] or r[1]==ADMIN_USERNAME))})
@app.post('/api/auth/register')
def register():
    d=request.get_json(silent=True) or {};u=str(d.get('username','')).strip();p=str(d.get('password',''))
    if len(u)<3:return err('اسم المستخدم قصير')
    if len(p)<6:return err('كلمة المرور يجب أن تكون 6 أحرف على الأقل')
    try:
        with db_conn() as c:
            with c.cursor() as q:q.execute('INSERT INTO users(username,password_hash,is_admin) VALUES(%s,%s,%s)',(u,hash_password(p),u==ADMIN_USERNAME))
            c.commit()
    except psycopg.errors.UniqueViolation:return err('اسم المستخدم مستخدم مسبقاً',409)
    except Exception as e:return err(str(e),500)
    session.permanent=True;session['username']=u;return jsonify({'ok':True,'user':user_json(user_row(u))})
@app.post('/api/auth/login')
def login():
    d=request.get_json(silent=True) or {};u=str(d.get('username','')).strip();p=str(d.get('password',''))
    try:r=user_row(u)
    except Exception as e:return err(str(e),500)
    if not r or not verify_password(p,r[2]):return err('بيانات الدخول غير صحيحة',401)
    session.permanent=True;session['username']=u;return jsonify({'ok':True,'user':user_json(r),'admin':bool(r[3] or u==ADMIN_USERNAME)})
@app.post('/api/auth/logout')
def logout():session.clear();return jsonify({'ok':True})
@app.get('/api/subscription')
def subscription():
    r=current_user()
    if not r:return err('يجب تسجيل الدخول',401)
    return jsonify({'ok':True,'plans':PLANS,'payment_address':PAYMENT_ADDRESS,'user':user_json(r)})
@app.post('/api/subscription/request')
def subrequest():
    r=current_user()
    if not r:return err('يجب تسجيل الدخول',401)
    d=request.get_json(silent=True) or {};pid=str(d.get('plan',''));tx=str(d.get('txid','')).strip();pl=PLANS.get(pid)
    if not pl:return err('الخطة غير موجودة')
    with db_conn() as c:
        with c.cursor() as q:q.execute("INSERT INTO payments(user_id,plan,amount,txid,status) VALUES(%s,%s,%s,%s,'pending')",(r[0],pid,pl['amount'],tx))
        c.commit()
    return jsonify({'ok':True,'message':'تم إرسال الطلب للمراجعة'})
@app.get('/api/admin/users')
def users():
    if not admin():return err('غير مصرح',403)
    with db_conn() as c:
        with c.cursor() as q:q.execute('SELECT id,username,is_admin,created_at,subscription_expires_at FROM users ORDER BY id DESC');rows=q.fetchall()
    return jsonify({'ok':True,'users':[{'id':x[0],'username':x[1],'admin':bool(x[2]),'created_at':x[3].isoformat() if x[3] else None,'subscription_expires_at':x[4].isoformat() if x[4] else None} for x in rows]})
@app.get('/api/admin/payments')
def payments():
    if not admin():return err('غير مصرح',403)
    with db_conn() as c:
        with c.cursor() as q:q.execute('SELECT p.id,p.user_id,u.username,p.plan,p.amount,p.txid,p.status,p.created_at FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC');rows=q.fetchall()
    return jsonify({'ok':True,'payments':[{'id':x[0],'user_id':x[1],'username':x[2],'plan':x[3],'amount':float(x[4]),'txid':x[5],'status':x[6],'created_at':x[7].isoformat() if x[7] else None} for x in rows]})
@app.post('/api/admin/payments/<int:pid>/approve')
def approve(pid):
    if not admin():return err('غير مصرح',403)
    with db_conn() as c:
        with c.cursor() as q:
            q.execute('SELECT user_id,plan FROM payments WHERE id=%s',(pid,));x=q.fetchone()
            if not x:return err('الدفع غير موجود',404)
            pl=PLANS.get(x[1]);q.execute("UPDATE payments SET status='approved' WHERE id=%s",(pid,));q.execute('UPDATE users SET subscription_expires_at=%s WHERE id=%s',(now()+timedelta(days=pl['days']),x[0]))
        c.commit()
    return jsonify({'ok':True})

# ---------------- News ----------------
@app.get('/api/news')
def news():
    old=cget('news',600)
    if old:return jsonify(old)
    try:
        r=HTTP.get('https://www.coindesk.com/arc/outboundfeeds/rss/',timeout=10);r.raise_for_status();root=ET.fromstring(r.text);items=[]
        for x in root.findall('.//item')[:20]:items.append({'title':html.unescape(x.findtext('title') or ''),'url':x.findtext('link') or '','published':x.findtext('pubDate') or ''})
        return jsonify(cset('news',{'ok':True,'items':items}))
    except Exception as e:return err(str(e),502)

# =========================================================
# Alpha + Futures: Bybit public Linear USDT perpetuals only.
# Spot is deliberately NOT used for either section.
# =========================================================
def bybit_get(path,params=None,timeout=8):
    r=HTTP.get(BYBIT_BASE+path,params=params or {},timeout=timeout);r.raise_for_status();d=r.json()
    if d.get('retCode') not in (0,None):raise RuntimeError(d.get('retMsg','Bybit error'))
    return d
def bybit_tickers():
    with LOCK:
        if BYBIT['tickers'] and time.time()-BYBIT['ts']<30:return BYBIT['tickers']
    x=bybit_get('/v5/market/tickers',{'category':'linear'})['result']['list']
    with LOCK:BYBIT.update(ts=time.time(),tickers=x)
    return x
def bybit_instruments():
    with LOCK:
        if BYBIT['instruments'] and time.time()-BYBIT['ts']<300:return BYBIT['instruments']
    out={};cursor=''
    for _ in range(5):
        p={'category':'linear','limit':1000};
        if cursor:p['cursor']=cursor
        b=bybit_get('/v5/market/instruments-info',p)['result'];
        for x in b.get('list',[]):out[x.get('symbol')]=x
        cursor=b.get('nextPageCursor') or ''
        if not cursor:break
    with LOCK:BYBIT['instruments']=out
    return out
def bybit_klines(s):
    x=bybit_get('/v5/market/kline',{'category':'linear','symbol':s,'interval':'15','limit':180})['result']['list'];return list(reversed(x))
def bybit_universe():
    ins=bybit_instruments();out=[]
    for t in bybit_tickers():
        s=t.get('symbol','');i=ins.get(s,{})
        if s.endswith('USDT') and i.get('contractType')=='LinearPerpetual' and i.get('status')=='Trading' and f(t.get('turnover24h'))>=1000000:out.append((t,i))
    return sorted(out,key=lambda x:f(x[0].get('turnover24h')),reverse=True)[:35]
def lev(i):return f(i.get('leverageFilter',{}).get('maxLeverage'),1)
def build_derivative(kind):
    key=kind+'_signals';old=cget(key,60 if kind=='alpha' else 45)
    if old:return old
    out=[]
    def w(item):
        t,i=item;s=t.get('symbol')
        try:
            a=analyze(bybit_klines(s));
            if a['signal']=='neutral':return None
            ch=f(t.get('price24hPcnt'))*100;fund=f(t.get('fundingRate'))*100;score=a['score']
            if kind=='alpha':
                if a['signal']=='buy':score+=(7 if ch>1 else 0)+(7 if fund<=0 else -4 if fund>0.08 else 0)
                else:score+=(7 if ch<-1 else 0)+(7 if fund>=0 else -4 if fund<-0.08 else 0)
                if score<68 and score>32:return None
            return {**a,'score':round(max(0,min(100,score)),1),'score10':round(max(0,min(100,score))/10,1),'symbol':s,'side':'BUY' if a['signal']=='buy' else 'SELL','direction':'BUY' if a['signal']=='buy' else 'SELL','leverage':lev(i),'lev':lev(i),'funding':round(fund,5),'change24':round(ch,3),'turnover24h':f(t.get('turnover24h')),'marketType':kind,'type':kind,'source':'Bybit Linear','interval':'15m'}
        except:return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for z in as_completed([ex.submit(w,x) for x in bybit_universe()]):
            x=z.result()
            if x:out.append(x)
    out.sort(key=lambda x:x['score'],reverse=True);return cset(key,{'ok':True,'signals':out[:20]})
@app.get('/api/futures/signals')
def futures():
    try:return jsonify(build_derivative('futures'))
    except Exception as e:return err('تعذر تحميل صفقات الفيوتشر: '+str(e),502)
@app.get('/api/alpha/signals')
def alpha():
    try:return jsonify(build_derivative('alpha'))
    except Exception as e:return err('تعذر تحميل صفقات Alpha: '+str(e),502)

# ---------------- US market: public Yahoo chart data ----------------
def yahoo(s):
    with LOCK:
        x=YAHOO.get(s)
        if x and time.time()-x['ts']<300:return x['data']
    r=HTTP.get(f'{YAHOO_BASE}/v8/finance/chart/{s}',params={'range':'1y','interval':'1d','events':'div,splits'},timeout=10);r.raise_for_status();z=r.json()['chart']['result'][0];ts=z.get('timestamp',[]);q=z['indicators']['quote'][0];rows=[]
    for i,t in enumerate(ts):
        try:
            o,h,l,c,v=q['open'][i],q['high'][i],q['low'][i],q['close'][i],q.get('volume',[0]*len(ts))[i]
            if None in (o,h,l,c):continue
            rows.append([t*1000,float(o),float(h),float(l),float(c),float(v or 0)])
        except:pass
    data={'rows':rows,'meta':z.get('meta',{})}
    with LOCK:YAHOO[s]={'ts':time.time(),'data':data}
    return data
def build_us():
    old=cget('us_market_signals',300)
    if old:return old
    out=[]
    def w(s):
        try:
            d=yahoo(s);a=analyze(d['rows'])
            if a['signal']=='neutral':return None
            p=f(d['meta'].get('regularMarketPrice'),a['price']);pc=f(d['meta'].get('previousClose'));chg=(p-pc)/pc*100 if pc else a['change'];a.update(symbol=s,name=US_NAMES.get(s,s),price=p,change=round(chg,3),marketType='us',type='us',source='Yahoo Finance',interval='1d');return a
        except:return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for z in as_completed([ex.submit(w,s) for s in US_SYMBOLS]):
            x=z.result()
            if x:out.append(x)
    out.sort(key=lambda x:x['score'],reverse=True);return cset('us_market_signals',{'ok':True,'signals':out[:30]})
@app.get('/api/us-market/signals')
def usmarket():
    try:return jsonify(build_us())
    except Exception as e:return err('تعذر تحميل السوق الأمريكي: '+str(e),502)

# ---------------- Saudi market proxy ----------------
def saudi_data():
    old=cget('saudi_signals',180)
    if old:return old
    r=HTTP.get(SAUDI_MARKET_SERVER.rstrip('/')+'/api/signals',timeout=12);r.raise_for_status();d=r.json();s=d if isinstance(d,list) else (d.get('signals') or d.get('results') or d.get('data') or []);return cset('saudi_signals',{'ok':True,'signals':s,'source':'Saudi market server'})
@app.get('/api/saudi/signals')
def saudi():
    try:return jsonify(saudi_data())
    except Exception as e:return err('تعذر تحميل السوق السعودي: '+str(e),502)
@app.get('/api/signals')
def signals_alias():return saudi()

@app.get('/health')
def health():return jsonify({'ok':True,'service':'mudarib-abo-saud','time':now().isoformat()})
@app.get('/')
def home():return render_template('index.html')
try:init_db()
except Exception as e:print('DB INIT WARNING:',e)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')),debug=False)

const $=id=>document.getElementById(id);

const state={
  user:null,
  admin:false,
  interval:'15m',
  symbol:'BTCUSDT',
  results:[],
  signals:new Set(),
  sort:'change',
  dir:-1,
  busy:false,
  chart:null,
  recent:JSON.parse(localStorage.getItem('mudarib_recent')||'[]')
};

const signalRank={
  'شراء قوي':5,
  'شراء':4,
  'حيادي':3,
  'بيع':2,
  'بيع قوي':1
};

const api=async(url,opt={})=>{
  const r=await fetch(url,{
    ...opt,
    headers:{
      'Content-Type':'application/json',
      ...(opt.headers||{})
    }
  });

  let d={};
  try{
    d=await r.json();
  }catch{}

  if(!r.ok||d.ok===false){
    throw new Error(d.message||`HTTP ${r.status}`);
  }

  return d;
};

function fmt(v){
  if(v==null||Number.isNaN(Number(v)))return'—';

  v=Number(v);

  if(v===0)return'0';

  if(Math.abs(v)>=1000)
    return v.toLocaleString('en-US',{maximumFractionDigits:2});

  if(Math.abs(v)>=1)
    return v.toLocaleString('en-US',{maximumFractionDigits:4});

  return v.toLocaleString('en-US',{maximumFractionDigits:8});
}

function pct(v){
  v=Number(v||0);
  return`${v>=0?'+':''}${v.toFixed(2)}%`;
}

function money(v){
  v=Number(v||0);

  if(v>=1e9)return`${(v/1e9).toFixed(2)}B`;
  if(v>=1e6)return`${(v/1e6).toFixed(2)}M`;
  if(v>=1e3)return`${(v/1e3).toFixed(1)}K`;

  return fmt(v);
}

function sigClass(s){
  return s==='شراء قوي'||s==='شراء'
    ?'buy'
    :s==='بيع قوي'||s==='بيع'
      ?'sell'
      :'neutral';
}

function closeMenu(){
  document.body.classList.remove('menu-open');
}

function showSection(id){
  document.querySelectorAll('.section')
    .forEach(x=>x.classList.toggle('active',x.id===id));

  document.querySelectorAll('.nav-item')
    .forEach(x=>x.classList.toggle('active',x.dataset.section===id));

  const names={
    dashboard:'الرئيسية',
    scanner:'ماسح الفرص',
    recent:'الصفقات الحديثة',
    news:'الأخبار',
    subscription:'الاشتراك'
  };

  if($('pageTitle'))
    $('pageTitle').textContent=names[id]||'الرئيسية';

  closeMenu();

  window.scrollTo({
    top:0,
    behavior:'smooth'
  });
}

document.querySelectorAll('.nav-item').forEach(b=>{
  b.addEventListener('click',e=>{
    e.preventDefault();
    showSection(b.dataset.section);
  });
});

if($('menuBtn')){
  $('menuBtn').onclick=e=>{
    e.stopPropagation();
    document.body.classList.toggle('menu-open');
  };
}

document.addEventListener('click',e=>{
  if(!document.body.classList.contains('menu-open'))return;

  const sidebar=$('sidebar');
  const menu=$('menuBtn');

  if(
    sidebar &&
    !sidebar.contains(e.target) &&
    menu &&
    !menu.contains(e.target)
  ){
    closeMenu();
  }
});

window.addEventListener('resize',()=>{
  if(window.innerWidth>1000)
    closeMenu();
});

function openAuth(tab='login'){
  if(!$('authModal'))return;

  $('authModal').classList.add('show');

  if($('loginForm'))
    $('loginForm').hidden=tab!=='login';

  if($('registerForm'))
    $('registerForm').hidden=tab==='login';

  if($('loginTab'))
    $('loginTab').classList.toggle('active',tab==='login');

  if($('registerTab'))
    $('registerTab').classList.toggle('active',tab==='register');
}

document.querySelectorAll('[data-close]').forEach(b=>{
  b.onclick=()=>{
    const el=$(b.dataset.close);
    if(el)el.classList.remove('show');
  };
});

if($('loginBtn'))
  $('loginBtn').onclick=()=>openAuth('login');

if($('registerBtn'))
  $('registerBtn').onclick=()=>openAuth('register');

if($('loginTab'))
  $('loginTab').onclick=()=>openAuth('login');

if($('registerTab'))
  $('registerTab').onclick=()=>openAuth('register');

async function checkAuth(){
  try{
    const d=await api('/api/auth/me');
    state.user=d.user;
    updateAuth();
  }catch{
    state.user=null;
    updateAuth();
  }

  try{
    const a=await api('/api/admin/me');
    state.admin=!!a.admin;

    if($('adminLink'))
      $('adminLink').hidden=!state.admin;

  }catch{
    state.admin=false;

    if($('adminLink'))
      $('adminLink').hidden=true;
  }
}

function updateAuth(){
  const logged=!!state.user;

  if($('userBadge'))
    $('userBadge').textContent=logged?state.user.name:'زائر';

  if($('loginBtn'))
    $('loginBtn').hidden=logged;

  if($('registerBtn'))
    $('registerBtn').hidden=logged;

  if($('logoutBtn'))
    $('logoutBtn').hidden=!logged;

  if($('subscriptionNav'))
    $('subscriptionNav').hidden=!logged;

  if($('subscription'))
    $('subscription').hidden=!logged;

  if(logged)
    loadSubscription();
}

if($('logoutBtn')){
  $('logoutBtn').onclick=async()=>{
    try{
      await api('/api/auth/logout',{method:'POST'});
    }catch{}

    state.user=null;
    updateAuth();
    showSection('dashboard');
  };
}

if($('loginForm')){
  $('loginForm').onsubmit=async e=>{
    e.preventDefault();

    try{
      const d=await api('/api/auth/login',{
        method:'POST',
        body:JSON.stringify({
          email:$('loginEmail').value,
          password:$('loginPassword').value
        })
      });

      state.user=d.user;

      if($('authMsg'))
        $('authMsg').innerHTML='<span class="ok">تم تسجيل الدخول ✅</span>';

      if($('authModal'))
        $('authModal').classList.remove('show');

      updateAuth();

    }catch(err){

      if($('authMsg'))
        $('authMsg').innerHTML=`<span class="error">${err.message}</span>`;
    }
  };
}

if($('registerForm')){
  $('registerForm').onsubmit=async e=>{
    e.preventDefault();

    try{
      const d=await api('/api/auth/register',{
        method:'POST',
        body:JSON.stringify({
          name:$('regName').value,
          email:$('regEmail').value,
          password:$('regPassword').value
        })
      });

      state.user=d.user;

      if($('authModal'))
        $('authModal').classList.remove('show');

      updateAuth();

    }catch(err){

      if($('authMsg'))
        $('authMsg').innerHTML=`<span class="error">${err.message}</span>`;
    }
  };
}

document.querySelectorAll('#dashIntervals button').forEach(b=>{
  b.onclick=()=>{
    document
      .querySelectorAll('#dashIntervals button')
      .forEach(x=>x.classList.remove('active'));

    b.classList.add('active');

    state.interval=b.dataset.interval;

    loadAnalysis();
  };
});

document.querySelectorAll('#intervalChips button').forEach(b=>{
  b.onclick=()=>{
    document
      .querySelectorAll('#intervalChips button')
      .forEach(x=>x.classList.remove('active'));

    b.classList.add('active');

    state.interval=b.dataset.interval;

    runScanner();
  };
});

document.querySelectorAll('.signal-chips button').forEach(b=>{
  b.onclick=()=>{
    b.classList.toggle('active');

    const s=b.dataset.signal;

    if(state.signals.has(s))
      state.signals.delete(s);
    else
      state.signals.add(s);

    renderScanner();
  };
});

if($('sortField'))
  $('sortField').onchange=e=>{
    state.sort=e.target.value;
    renderScanner();
  };

if($('sortDir'))
  $('sortDir').onclick=()=>{
    state.dir*=-1;

    $('sortDir').textContent=
      state.dir===-1
        ?'↓ تنازلي'
        :'↑ تصاعدي';

    renderScanner();
  };

if($('scannerSearch'))
  $('scannerSearch').oninput=renderScanner;

if($('scanBtn'))
  $('scanBtn').onclick=runScanner;

function filtered(){
  let a=[...state.results];

  const q=$('scannerSearch')
    ?$('scannerSearch').value.trim().toUpperCase()
    :'';

  if(q)
    a=a.filter(x=>x.symbol.includes(q));

  if(state.signals.size)
    a=a.filter(x=>state.signals.has(x.signal));

  const f=state.sort;

  a.sort((x,y)=>{
    let av=
      f==='signal'
        ?signalRank[x.signal]
        :f==='symbol'
          ?x.symbol
          :x[f]??0;

    let bv=
      f==='signal'
        ?signalRank[y.signal]
        :f==='symbol'
          ?y.symbol
          :y[f]??0;

    if(typeof av==='string')
      return av.localeCompare(bv)*state.dir;

    return(Number(av)-Number(bv))*state.dir;
  });

  return a;
}

function renderScanner(){
  if(!$('scannerBody'))return;

  const rows=filtered();

  $('scannerBody').innerHTML=rows.length
    ?rows.map(x=>`
      <tr onclick="selectSymbol('${x.symbol}')">
        <td>
          <b>${x.symbol.replace('USDT','')}</b>
          <small>USDT</small>
        </td>

        <td>${fmt(x.price)}</td>

        <td class="${x.change>=0?'up':'down'}">
          ${pct(x.change)}
        </td>

        <td>
          <span class="signal ${sigClass(x.signal)}">
            ${x.signal}
          </span>
        </td>

        <td>${x.score10}/10</td>
        <td>${money(x.volume)}</td>
        <td>${x.interval}</td>
      </tr>
    `).join('')
    :'<tr><td colspan="7" class="empty">لا توجد نتائج مطابقة</td></tr>';
}

async function runScanner(){
  if(state.busy)return;

  state.busy=true;

  if($('scannerStatus'))
    $('scannerStatus').textContent='جاري فحص أعلى العملات سيولة...';

  try{

    const d=await api(
      `/api/binance/scan?interval=${encodeURIComponent(state.interval)}&limit=40`
    );

    state.results=d.results||[];

    if($('scannerStatus')){
      $('scannerStatus').textContent=
        `تم العثور على ${state.results.length} فرصة${d.cached?' — نتيجة محفوظة مؤقتًا':''}`;
    }

    renderScanner();
    captureRecent();

  }catch(e){

    if($('scannerStatus'))
      $('scannerStatus').textContent=`تعذر الفحص: ${e.message}`;

  }finally{
    state.busy=false;
  }
}

function captureRecent(){
  const now=Date.now();
  const bucket=Math.floor(now/300000);

  const old=new Set(
    state.recent.map(x=>x.key)
  );

  state.results
    .filter(x=>x.signal!=='حيادي')
    .slice(0,15)
    .forEach(x=>{
      const key=
        `${x.symbol}|${x.interval}|${x.signal}|${bucket}`;

      if(!old.has(key)){
        state.recent.unshift({
          ...x,
          key,
          time:now
        });
      }
    });

  state.recent=state.recent.slice(0,60);

  localStorage.setItem(
    'mudarib_recent',
    JSON.stringify(state.recent)
  );

  renderRecent();
}

function renderRecent(){
  if(!$('recentList'))return;

  const a=state.recent;

  if(!a.length){
    $('recentList').innerHTML=
      '<div class="empty-card">ما فيه فرص حديثة حتى الآن. شغّل الماسح.</div>';
    return;
  }

  $('recentList').innerHTML=
    a.slice(0,30).map(x=>`
      <div class="recent-card" onclick="selectSymbol('${x.symbol}')">

        <div>
          <b>${x.symbol}</b>
          <small>${new Date(x.time).toLocaleString('ar-SA')}</small>
        </div>

        <span class="signal ${sigClass(x.signal)}">
          ${x.signal}
        </span>

        <div>
          <small>السعر</small>
          <b>${fmt(x.price)}</b>
        </div>

        <div class="${x.change>=0?'up':'down'}">
          ${pct(x.change)}
        </div>

        <div>
          <small>TP1 / وقف</small>
          <b>${fmt(x.tp1)} / ${fmt(x.sl)}</b>
        </div>

      </div>
    `).join('');
}

if($('clearRecent')){
  $('clearRecent').onclick=()=>{
    state.recent=[];
    localStorage.removeItem('mudarib_recent');
    renderRecent();
  };
}

async function loadAnalysis(){
  const sym=state.symbol;

  try{

    const d=await api(
      `/api/binance/analysis?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(state.interval)}`
    );

    const a=d.analysis;

    if($('dashSymbol'))
      $('dashSymbol').textContent=sym;

    if($('dashPrice'))
      $('dashPrice').textContent=fmt(a.price);

    if($('dashChange'))
      $('dashChange').textContent='—';

    if($('dashSignal')){
      $('dashSignal').textContent=a.signal;
      $('dashSignal').className=`signal-text ${sigClass(a.signal)}`;
    }

    if($('bigSignal')){
      $('bigSignal').textContent=a.signal;
      $('bigSignal').className=`signal-big ${sigClass(a.signal)}`;
    }

    if($('scoreText'))
      $('scoreText').textContent=`${a.score}/100`;

    if($('scoreBar'))
      $('scoreBar').style.width=`${a.score}%`;

    if($('entry'))
      $('entry').textContent=fmt(a.entry);

    if($('tp1'))
      $('tp1').textContent=fmt(a.tp1);

    if($('tp2'))
      $('tp2').textContent=fmt(a.tp2);

    if($('tp3'))
      $('tp3').textContent=fmt(a.tp3);

    if($('sl'))
      $('sl').textContent=fmt(a.sl);

    if($('rsi'))
      $('rsi').textContent=Number(a.rsi).toFixed(1);

    if($('ema20'))
      $('ema20').textContent=fmt(a.ema20);

    if($('ema50'))
      $('ema50').textContent=fmt(a.ema50);

    if($('ema200'))
      $('ema200').textContent=fmt(a.ema200);

    if($('analysisMeta'))
      $('analysisMeta').textContent=`${sym} · ${state.interval}`;

    if($('reasons'))
      $('reasons').innerHTML=(a.reasons||[])
        .map(x=>`<li>${x}</li>`)
        .join('');

    drawChart(a.candles||[]);

  }catch(e){

    if($('bigSignal'))
      $('bigSignal').textContent=e.message;
  }
}

window.selectSymbol=(s)=>{
  state.symbol=s;
  showSection('dashboard');
  loadAnalysis();
};

function drawChart(c){
  const canvas=$('priceChart');

  if(!canvas || typeof Chart==='undefined')
    return;

  const ctx=canvas.getContext('2d');

  if(state.chart)
    state.chart.destroy();

  state.chart=new Chart(ctx,{
    type:'line',

    data:{
      labels:c.map(x=>
        new Date(x.t).toLocaleTimeString(
          'ar-SA',
          {
            hour:'2-digit',
            minute:'2-digit'
          }
        )
      ),

      datasets:[{
        label:state.symbol,
        data:c.map(x=>x.c),
        borderWidth:2,
        pointRadius:0,
        tension:.2
      }]
    },

    options:{
      responsive:true,
      maintainAspectRatio:false,

      plugins:{
        legend:{
          display:false
        }
      },

      scales:{
        x:{
          display:false
        },

        y:{
          grid:{
            color:'rgba(127,127,127,.15)'
          }
        }
      }
    }
  });
}

async function loadNews(){
  if(!$('newsList'))return;

  $('newsList').innerHTML=
    '<div class="empty-card">جاري تحميل الأخبار...</div>';

  try{

    const d=await api('/api/news');

    $('newsList').innerHTML=d.news?.length
      ?d.news.map(n=>`
        <a
          class="news-card"
          href="${n.link}"
          target="_blank"
          rel="noopener"
        >
          <small>${n.source} · ${n.published||''}</small>
          <h3>${n.title}</h3>
          <p>${n.description||''}</p>
        </a>
      `).join('')
      :'<div class="empty-card">لا توجد أخبار متاحة حاليًا.</div>';

  }catch(e){

    $('newsList').innerHTML=
      `<div class="empty-card">${e.message}</div>`;
  }
}

if($('newsBtn'))
  $('newsBtn').onclick=loadNews;

async function loadSubscription(){
  if(!$('subscriptionStatus'))return;

  try{

    const d=await api('/api/subscription/plans');
    renderPlans(d);

    const s=await api('/api/subscription/my');

    $('subscriptionStatus').innerHTML=
      s.active
        ?`<div class="active-plan">✅ اشتراكك فعال — ${s.plan} — ينتهي ${new Date(s.expires).toLocaleDateString('ar-SA')}</div>`
        :'<div class="inactive-plan">لا يوجد اشتراك فعال حاليًا.</div>';

    renderPaymentHistory(s.requests||[]);

  }catch(e){

    $('subscriptionStatus').innerHTML=
      `<div class="error">${e.message}</div>`;
  }
}

function renderPlans(d){
  if($('payAddress'))
    $('payAddress').value=d.address;

  if(!$('plans'))return;

  $('plans').innerHTML=
    Object.entries(d.plans).map(([k,p])=>`
      <button class="plan-card" data-plan="${k}">
        <b>${p.name}</b>
        <strong>${p.amount} USDT</strong>
        <small>دفع عبر TRC20</small>
      </button>
    `).join('');

  document.querySelectorAll('.plan-card').forEach(b=>{
    b.onclick=()=>{
      choosePlan(
        b.dataset.plan,
        d.plans[b.dataset.plan]
      );
    };
  });
}

function choosePlan(k,p){
  state.plan=k;

  if($('paymentBox'))
    $('paymentBox').hidden=false;

  if($('chosenPlan'))
    $('chosenPlan').innerHTML=
      `الباقة المختارة: <b>${p.name}</b> — <b>${p.amount} USDT</b>`;

  if($('qrBox'))
    $('qrBox').innerHTML='';

  if(
    window.QRCode &&
    $('qrBox') &&
    $('payAddress')
  ){
    QRCode.toCanvas(
      $('qrBox'),
      $('payAddress').value,
      {width:190},
      ()=>{}
    );
  }

  if($('paymentBox'))
    $('paymentBox').scrollIntoView({
      behavior:'smooth'
    });
}

if($('copyAddress')){
  $('copyAddress').onclick=async()=>{
    try{
      await navigator.clipboard.writeText(
        $('payAddress').value
      );

      $('copyAddress').textContent='تم النسخ ✓';

      setTimeout(()=>{
        $('copyAddress').textContent='نسخ';
      },1500);

    }catch{}
  };
}

if($('sendPayment')){
  $('sendPayment').onclick=async()=>{
    if(!state.plan)return;

    try{

      const d=await api(
        '/api/subscription/request',
        {
          method:'POST',
          body:JSON.stringify({
            plan:state.plan,
            txid:$('txid').value
          })
        }
      );

      if($('paymentMsg'))
        $('paymentMsg').innerHTML=
          `<span class="ok">${d.message} ✅</span>`;

      if($('txid'))
        $('txid').value='';

      loadSubscription();

    }catch(e){

      if($('paymentMsg'))
        $('paymentMsg').innerHTML=
          `<span class="error">${e.message}</span>`;
    }
  };
}

function renderPaymentHistory(rows){
  if(!$('paymentHistory'))return;

  $('paymentHistory').innerHTML=
    rows.length
      ?`
        <h3>طلبات الدفع</h3>

        <div class="payment-history">
          ${rows.map(x=>`
            <div>
              <b>${x.plan}</b>
              <span>${x.amount} USDT</span>
              <span class="status-${x.status}">
                ${
                  x.status==='pending'
                    ?'قيد المراجعة'
                    :x.status==='approved'
                      ?'مقبول'
                      :'مرفوض'
                }
              </span>
            </div>
          `).join('')}
        </div>
      `
      :'';
}

if($('themeBtn')){
  $('themeBtn').onclick=()=>{
    document.body.classList.toggle('light');

    localStorage.setItem(
      'theme',
      document.body.classList.contains('light')
        ?'light'
        :'dark'
    );
  };
}

if(localStorage.getItem('theme')==='light')
  document.body.classList.add('light');

(async function boot(){

  await checkAuth();

  if($('systemStatus'))
    $('systemStatus').textContent='متصل';

  await runScanner();
  await loadAnalysis();
  await loadNews();

  setInterval(()=>{
    runScanner();
  },60000);

  setInterval(()=>{
    loadNews();
  },600000);

})();

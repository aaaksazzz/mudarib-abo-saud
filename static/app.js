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
    recent:JSON.parse(localStorage.getItem('mudarib_recent')||'[]'),
    alpha:[],
    futures:[],
    usMarket:[],
    plan:null
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

    if(!r.ok||d.ok===false)
        throw new Error(d.message||`HTTP ${r.status}`);

    return d;
};

function fmt(v){
    if(v==null||Number.isNaN(Number(v)))return'—';

    v=Number(v);

    if(v===0)return'0';

    if(Math.abs(v)>=1000)
        return v.toLocaleString('en-US',{
            maximumFractionDigits:2
        });

    if(Math.abs(v)>=1)
        return v.toLocaleString('en-US',{
            maximumFractionDigits:4
        });

    return v.toLocaleString('en-US',{
        maximumFractionDigits:8
    });
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


/* ============================================================
   SECTION NAVIGATION
============================================================ */

const sectionNames={
    dashboard:'الرئيسية',
    scanner:'ماسح الفرص',
    recent:'🟢 صفقات السبوت',
    alpha:'⚡ صفقات Alpha',
    futures:'🚀 صفقات الفيوتشر',
    'us-market':'🇺🇸 صفقات السوق الأمريكي',
    news:'الأخبار',
    subscription:'الاشتراك'
};

function showSection(id){

    const target=document.getElementById(id);

    if(!target)return;

    document.querySelectorAll('.section').forEach(x=>{
        x.classList.toggle('active',x.id===id);
    });

    document.querySelectorAll('.nav-item').forEach(x=>{
        x.classList.toggle(
            'active',
            x.dataset.section===id
        );
    });

    $('pageTitle').textContent=
        sectionNames[id]||'الرئيسية';

    closeMenu();

    window.scrollTo({
        top:0,
        behavior:'smooth'
    });

    if(id==='recent')
        renderRecent();

    if(id==='alpha')
        loadAlpha();

    if(id==='futures')
        loadFutures();

    if(id==='us-market')
        loadUSMarket();

    if(id==='news')
        loadNews();

    if(id==='subscription' && state.user)
        loadSubscription();
}


/* ============================================================
   NAVIGATION
============================================================ */

document.querySelectorAll('.nav-item').forEach(b=>{
    b.addEventListener('click',e=>{
        e.preventDefault();

        const section=b.dataset.section;

        if(!section)return;

        showSection(section);
    });
});


/* ============================================================
   MOBILE MENU
============================================================ */

$('menuBtn').onclick=e=>{
    e.stopPropagation();
    document.body.classList.toggle('menu-open');
};

document.addEventListener('click',e=>{

    if(!document.body.classList.contains('menu-open'))
        return;

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


/* ============================================================
   AUTH
============================================================ */

function openAuth(tab='login'){

    $('authModal').classList.add('show');

    $('loginForm').hidden=tab!=='login';

    $('registerForm').hidden=tab==='login';

    $('loginTab').classList.toggle(
        'active',
        tab==='login'
    );

    $('registerTab').classList.toggle(
        'active',
        tab==='register'
    );
}

document.querySelectorAll('[data-close]').forEach(b=>{
    b.onclick=()=>
        $(b.dataset.close).classList.remove('show');
});

$('loginBtn').onclick=()=>{
    openAuth('login');
};

$('registerBtn').onclick=()=>{
    openAuth('register');
};

$('loginTab').onclick=()=>{
    openAuth('login');
};

$('registerTab').onclick=()=>{
    openAuth('register');
};


/* ============================================================
   AUTH CHECK
============================================================ */

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

        $('adminLink').hidden=!state.admin;

    }catch{

        state.admin=false;

        $('adminLink').hidden=true;
    }
}

function updateAuth(){

    const logged=!!state.user;

    $('userBadge').textContent=
        logged?state.user.name:'زائر';

    $('loginBtn').hidden=logged;

    $('registerBtn').hidden=logged;

    $('logoutBtn').hidden=!logged;

    $('subscriptionNav').hidden=!logged;

    $('subscription').hidden=!logged;

    if(logged)
        loadSubscription();
}

$('logoutBtn').onclick=async()=>{

    try{
        await api('/api/auth/logout',{
            method:'POST'
        });
    }catch{}

    state.user=null;

    updateAuth();

    showSection('dashboard');
};


/* ============================================================
   LOGIN
============================================================ */

$('loginForm').onsubmit=async e=>{

    e.preventDefault();

    try{

        const d=await api(
            '/api/auth/login',
            {
                method:'POST',
                body:JSON.stringify({
                    email:$('loginEmail').value,
                    password:$('loginPassword').value
                })
            }
        );

        state.user=d.user;

        $('authMsg').innerHTML=
            '<span class="ok">تم تسجيل الدخول ✅</span>';

        $('authModal').classList.remove('show');

        updateAuth();

    }catch(err){

        $('authMsg').innerHTML=
            `<span class="error">${err.message}</span>`;
    }
};


/* ============================================================
   REGISTER
============================================================ */

$('registerForm').onsubmit=async e=>{

    e.preventDefault();

    try{

        const d=await api(
            '/api/auth/register',
            {
                method:'POST',
                body:JSON.stringify({
                    name:$('regName').value,
                    email:$('regEmail').value,
                    password:$('regPassword').value
                })
            }
        );

        state.user=d.user;

        $('authModal').classList.remove('show');

        updateAuth();

    }catch(err){

        $('authMsg').innerHTML=
            `<span class="error">${err.message}</span>`;
    }
};


/* ============================================================
   DASHBOARD INTERVALS
============================================================ */

document.querySelectorAll(
    '#dashIntervals button'
).forEach(b=>{

    b.onclick=()=>{

        document.querySelectorAll(
            '#dashIntervals button'
        ).forEach(x=>
            x.classList.remove('active')
        );

        b.classList.add('active');

        state.interval=b.dataset.interval;

        loadAnalysis();
    };
});


/* ============================================================
   SCANNER INTERVALS
============================================================ */

document.querySelectorAll(
    '#intervalChips button'
).forEach(b=>{

    b.onclick=()=>{

        document.querySelectorAll(
            '#intervalChips button'
        ).forEach(x=>
            x.classList.remove('active')
        );

        b.classList.add('active');

        state.interval=b.dataset.interval;

        runScanner();
    };
});


/* ============================================================
   SIGNAL FILTERS
============================================================ */

document.querySelectorAll(
    '.signal-chips button'
).forEach(b=>{

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


/* ============================================================
   SCANNER SORT / SEARCH
============================================================ */

$('sortField').onchange=e=>{
    state.sort=e.target.value;
    renderScanner();
};

$('sortDir').onclick=()=>{

    state.dir*=-1;

    $('sortDir').textContent=
        state.dir===-1
        ?'↓ تنازلي'
        :'↑ تصاعدي';

    renderScanner();
};

$('scannerSearch').oninput=renderScanner;

$('scanBtn').onclick=runScanner;


function filtered(){

    let a=[...state.results];

    const q=$('scannerSearch')
        .value
        .trim()
        .toUpperCase();

    if(q)
        a=a.filter(x=>x.symbol.includes(q));

    if(state.signals.size)
        a=a.filter(x=>
            state.signals.has(x.signal)
        );

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

        return(
            Number(av)-Number(bv)
        )*state.dir;
    });

    return a;
}


function renderScanner(){

    const rows=filtered();

    $('scannerBody').innerHTML=
        rows.length
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
        :
        '<tr><td colspan="7" class="empty">لا توجد نتائج مطابقة</td></tr>';
}


/* ============================================================
   SCANNER
============================================================ */

async function runScanner(){

    if(state.busy)return;

    state.busy=true;

    $('scannerStatus').textContent=
        'جاري فحص أعلى العملات سيولة...';

    try{

        const d=await api(
            `/api/binance/scan?interval=${state.interval}&limit=40`
        );

        state.results=d.results||[];

        $('scannerStatus').textContent=
            `تم العثور على ${state.results.length} فرصة${
                d.cached
                ?' — نتيجة محفوظة مؤقتًا'
                :''
            }`;

        renderScanner();

        captureRecent();

    }catch(e){

        $('scannerStatus').textContent=
            `تعذر الفحص: ${e.message}`;

    }finally{

        state.busy=false;
    }
}


/* ============================================================
   SPOT
============================================================ */

function captureRecent(){

    const now=Date.now();

    const bucket=
        Math.floor(now/300000);

    const old=
        new Set(
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

    state.recent=
        state.recent.slice(0,60);

    localStorage.setItem(
        'mudarib_recent',
        JSON.stringify(state.recent)
    );

    renderRecent();
}


function renderRecent(){

    const a=state.recent;

    if(!a.length){

        $('recentList').innerHTML=
            '<div class="empty-card">ما فيه فرص حديثة حتى الآن. شغّل الماسح.</div>';

        return;
    }

    $('recentList').innerHTML=
        a.slice(0,30).map(x=>`

            <div
                class="recent-card"
                onclick="selectSymbol('${x.symbol}')"
            >

                <div>
                    <b>${x.symbol}</b>
                    <small>
                        ${new Date(x.time).toLocaleString('ar-SA')}
                    </small>
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
                    <b>
                        ${fmt(x.tp1)} / ${fmt(x.sl)}
                    </b>
                </div>

            </div>

        `).join('');
}


$('clearRecent').onclick=()=>{

    state.recent=[];

    localStorage.removeItem(
        'mudarib_recent'
    );

    renderRecent();
};


/* ============================================================
   ALPHA
============================================================ */

async function loadAlpha(){

    const box=$('alphaList');

    if(!box)return;

    box.innerHTML=
        '<div class="empty-card">جاري تحميل صفقات Alpha...</div>';

    try{

        const d=await api('/api/alpha/signals');

        state.alpha=d.signals||[];

        renderAlpha();

    }catch(e){

        box.innerHTML=
            `<div class="empty-card">تعذر تحميل صفقات Alpha: ${e.message}</div>`;
    }
}


function renderAlpha(){

    const box=$('alphaList');

    if(!box)return;

    const a=state.alpha||[];

    if(!a.length){

        box.innerHTML=
            '<div class="empty-card">لا توجد صفقات Alpha متاحة حاليًا.</div>';

        return;
    }

    box.innerHTML=a.map(x=>`

        <div class="recent-card"
             onclick="selectSymbol('${x.symbol}')">

            <div>
                <b>${x.symbol}</b>
                <small>⚡ Alpha</small>
            </div>

            <span class="signal ${sigClass(x.signal||'شراء')}">
                ${x.signal||'شراء'}
            </span>

            <div>
                <small>السعر</small>
                <b>${fmt(x.price||x.entry)}</b>
            </div>

            <div>
                <small>القوة</small>
                <b>${x.score10!=null?x.score10:(x.score!=null?Number(x.score).toFixed(1):'—')}/10</b>
            </div>

            <div>
                <small>TP1 / وقف</small>
                <b>${fmt(x.tp1)} / ${fmt(x.sl)}</b>
            </div>

        </div>

    `).join('');
}


$('alphaRefresh').onclick=loadAlpha;


/* ============================================================
   FUTURES
============================================================ */

async function loadFutures(){

    const box=$('futuresList');

    if(!box)return;

    box.innerHTML=
        '<div class="empty-card">جاري تحميل صفقات الفيوتشر...</div>';

    try{

        const d=await api('/api/futures/signals');

        state.futures=d.signals||[];

        renderFutures();

    }catch(e){

        box.innerHTML=
            `<div class="empty-card">تعذر تحميل صفقات الفيوتشر: ${e.message}</div>`;
    }
}


function renderFutures(){

    const box=$('futuresList');

    if(!box)return;

    const a=state.futures||[];

    if(!a.length){

        box.innerHTML=
            '<div class="empty-card">لا توجد صفقات فيوتشر متاحة حاليًا.</div>';

        return;
    }

    box.innerHTML=a.map(x=>{

        const side=
            x.side||
            x.direction||
            'LONG';

        const sideText=
            side==='SHORT'||side==='sell'
            ?'بيع'
            :'شراء';

        const sideClass=
            side==='SHORT'||side==='sell'
            ?'sell'
            :'buy';

        const leverage=
            x.leverage||
            x.lev||
            '—';

        return`

        <div class="recent-card"
             onclick="selectSymbol('${x.symbol}')">

            <div>
                <b>${x.symbol}</b>
                <small>🚀 Futures</small>
            </div>

            <span class="signal ${sideClass}">
                ${sideText}
            </span>

            <div>
                <small>الرافعة</small>
                <b>${leverage}x</b>
            </div>

            <div>
                <small>الدخول</small>
                <b>${fmt(x.entry||x.price)}</b>
            </div>

            <div>
                <small>TP1</small>
                <b>${fmt(x.tp1)}</b>
            </div>

            <div>
                <small>وقف</small>
                <b>${fmt(x.sl)}</b>
            </div>

        </div>

        `;

    }).join('');
}


$('futuresRefresh').onclick=loadFutures;


/* ============================================================
   US MARKET
============================================================ */

async function loadUSMarket(){

    const box=$('usMarketList');

    if(!box)return;

    /*
     * لا يوجد API للسوق الأمريكي في server.py الحالي.
     * لذلك القسم يظهر بشكل طبيعي بدون التأثير على بقية الموقع.
     */

    state.usMarket=[];

    renderUSMarket();
}


function renderUSMarket(){

    const box=$('usMarketList');

    if(!box)return;

    if(!state.usMarket.length){

        box.innerHTML=`
            <div class="empty-card">
                🇺🇸 لا توجد صفقات للسوق الأمريكي متاحة حاليًا.
            </div>
        `;

        return;
    }

    box.innerHTML=state.usMarket.map(x=>`

        <div class="recent-card">

            <div>
                <b>${x.symbol||'—'}</b>
                <small>🇺🇸 السوق الأمريكي</small>
            </div>

            <span class="signal ${sigClass(x.signal||'حيادي')}">
                ${x.signal||'حيادي'}
            </span>

            <div>
                <small>السعر</small>
                <b>${fmt(x.price)}</b>
            </div>

            <div>
                <small>القوة</small>
                <b>${x.score!=null?x.score:'—'}</b>
            </div>

            <div>
                <small>هدف</small>
                <b>${fmt(x.tp1)}</b>
            </div>

            <div>
                <small>وقف</small>
                <b>${fmt(x.sl)}</b>
            </div>

        </div>

    `).join('');
}


$('usMarketRefresh').onclick=loadUSMarket;


/* ============================================================
   ANALYSIS
============================================================ */

async function loadAnalysis(){

    const sym=state.symbol;

    try{

        const d=await api(
            `/api/binance/analysis?symbol=${sym}&interval=${state.interval}`
        );

        const a=d.analysis;

        $('dashSymbol').textContent=sym;

        $('dashPrice').textContent=
            fmt(a.price);

        $('dashChange').textContent='—';

        $('dashSignal').textContent=
            a.signal;

        $('dashSignal').className=
            `signal-text ${sigClass(a.signal)}`;

        $('bigSignal').textContent=
            a.signal;

        $('bigSignal').className=
            `signal-big ${sigClass(a.signal)}`;

        $('scoreText').textContent=
            `${a.score}/100`;

        $('scoreBar').style.width=
            `${a.score}%`;

        $('entry').textContent=
            fmt(a.entry);

        $('tp1').textContent=
            fmt(a.tp1);

        $('tp2').textContent=
            fmt(a.tp2);

        $('tp3').textContent=
            fmt(a.tp3);

        $('sl').textContent=
            fmt(a.sl);

        $('rsi').textContent=
            Number(a.rsi).toFixed(1);

        $('ema20').textContent=
            fmt(a.ema20);

        $('ema50').textContent=
            fmt(a.ema50);

        $('ema200').textContent=
            fmt(a.ema200);

        $('analysisMeta').textContent=
            `${sym} · ${state.interval}`;

        $('reasons').innerHTML=
            (a.reasons||[])
            .map(x=>`<li>${x}</li>`)
            .join('');

        drawChart(
            a.candles||[]
        );

    }catch(e){

        $('bigSignal').textContent=
            e.message;
    }
}


window.selectSymbol=(s)=>{

    state.symbol=s;

    showSection('dashboard');

    loadAnalysis();
};


/* ============================================================
   CHART
============================================================ */

function drawChart(c){

    const ctx=$('priceChart');

    if(!ctx)return;

    if(state.chart)
        state.chart.destroy();

    state.chart=new Chart(
        ctx,
        {
            type:'line',

            data:{
                labels:c.map(x=>
                    new Date(x.t)
                    .toLocaleTimeString(
                        'ar-SA',
                        {
                            hour:'2-digit',
                            minute:'2-digit'
                        }
                    )
                ),

                datasets:[
                    {
                        label:state.symbol,
                        data:c.map(x=>x.c),
                        borderWidth:2,
                        pointRadius:0,
                        tension:.2
                    }
                ]
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
                            color:
                                'rgba(127,127,127,.15)'
                        }
                    }
                }
            }
        }
    );
}


/* ============================================================
   NEWS
============================================================ */

async function loadNews(){

    const box=$('newsList');

    box.innerHTML=
        '<div class="empty-card">جاري تحميل الأخبار...</div>';

    try{

        const d=await api('/api/news');

        box.innerHTML=
            d.news?.length
            ?d.news.map(n=>`

                <a
                    class="news-card"
                    href="${n.link}"
                    target="_blank"
                    rel="noopener"
                >

                    <small>
                        ${n.source} · ${n.published||''}
                    </small>

                    <h3>
                        ${n.title}
                    </h3>

                    <p>
                        ${n.description||''}
                    </p>

                </a>

            `).join('')
            :
            '<div class="empty-card">لا توجد أخبار متاحة حاليًا.</div>';

    }catch(e){

        box.innerHTML=
            `<div class="empty-card">${e.message}</div>`;
    }
}

$('newsBtn').onclick=loadNews;


/* ============================================================
   SUBSCRIPTION
============================================================ */

async function loadSubscription(){

    try{

        const d=
            await api(
                '/api/subscription/plans'
            );

        renderPlans(d);

        const s=
            await api(
                '/api/subscription/my'
            );

        $('subscriptionStatus').innerHTML=
            s.active
            ?
            `<div class="active-plan">
                ✅ اشتراكك فعال — ${s.plan} —
                ينتهي ${new Date(s.expires).toLocaleDateString('ar-SA')}
            </div>`
            :
            `<div class="inactive-plan">
                لا يوجد اشتراك فعال حاليًا.
            </div>`;

        renderPaymentHistory(
            s.requests||[]
        );

    }catch(e){

        $('subscriptionStatus').innerHTML=
            `<div class="error">${e.message}</div>`;
    }
}


function renderPlans(d){

    $('payAddress').value=d.address;

    $('plans').innerHTML=
        Object.entries(d.plans)
        .map(([k,p])=>`

            <button
                class="plan-card"
                data-plan="${k}"
            >

                <b>${p.name}</b>

                <strong>
                    ${p.amount} USDT
                </strong>

                <small>
                    دفع عبر TRC20
                </small>

            </button>

        `)
        .join('');

    document.querySelectorAll(
        '.plan-card'
    ).forEach(b=>{

        b.onclick=()=>
            choosePlan(
                b.dataset.plan,
                d.plans[b.dataset.plan]
            );
    });
}


function choosePlan(k,p){

    state.plan=k;

    $('paymentBox').hidden=false;

    $('chosenPlan').innerHTML=
        `الباقة المختارة:
        <b>${p.name}</b> —
        <b>${p.amount} USDT</b>`;

    $('qrBox').innerHTML='';

    if(window.QRCode)
        QRCode.toCanvas(
            $('qrBox'),
            $('payAddress').value,
            {
                width:190
            },
            ()=>{}
        );

    $('paymentBox').scrollIntoView({
        behavior:'smooth'
    });
}


$('copyAddress').onclick=async()=>{

    try{

        await navigator.clipboard.writeText(
            $('payAddress').value
        );

        $('copyAddress').textContent=
            'تم النسخ ✓';

        setTimeout(
            ()=>
                $('copyAddress').textContent='نسخ',
            1500
        );

    }catch{}
};


$('sendPayment').onclick=async()=>{

    if(!state.plan)return;

    try{

        const d=
            await api(
                '/api/subscription/request',
                {
                    method:'POST',
                    body:JSON.stringify({
                        plan:state.plan,
                        txid:$('txid').value
                    })
                }
            );

        $('paymentMsg').innerHTML=
            `<span class="ok">
                ${d.message} ✅
            </span>`;

        $('txid').value='';

        loadSubscription();

    }catch(e){

        $('paymentMsg').innerHTML=
            `<span class="error">
                ${e.message}
            </span>`;
    }
};


function renderPaymentHistory(rows){

    $('paymentHistory').innerHTML=
        rows.length
        ?
        `<h3>طلبات الدفع</h3>
        <div class="payment-history">
            ${rows.map(x=>`

                <div>
                    <b>${x.plan}</b>

                    <span>
                        ${x.amount} USDT
                    </span>

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
        </div>`
        :'';
}


/* ============================================================
   THEME
============================================================ */

$('themeBtn').onclick=()=>{

    document.body.classList.toggle('light');

    localStorage.setItem(
        'theme',
        document.body.classList.contains('light')
        ?'light'
        :'dark'
    );
};

if(
    localStorage.getItem('theme')==='light'
)
    document.body.classList.add('light');


/* ============================================================
   BOOT
============================================================ */

(async function boot(){

    await checkAuth();

    $('systemStatus').textContent='متصل';

    await runScanner();

    await loadAnalysis();

    await loadNews();

    renderRecent();

    /*
     * لا نطلب Alpha/Futures عند تشغيل الموقع
     * حتى لا نضغط على Binance بدون حاجة.
     * يتم تحميلها عند فتح القسم.
     */

    setInterval(
        ()=>runScanner(),
        60000
    );

    setInterval(
        ()=>loadNews(),
        600000
    );

})();

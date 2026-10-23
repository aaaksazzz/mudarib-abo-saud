(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const view = $("pageView");
  const API_TIMEOUT = 45000;
  const markets = {
    spot:{slug:"spot",api:"spot",name:"سبوت Binance",sub:"العملات الفورية",icon:"◉",source:"Binance"},
    futures:{slug:"futures",api:"futures",name:"فيوتشر",sub:"عقود Binance الدائمة وفرص قصيرة الأجل",icon:"⇅",source:"Binance"},
    alpha:{slug:"alpha",api:"alpha",name:"Binance Alpha",sub:"أصول Binance Alpha",icon:"✦",source:"Binance Alpha"},
    contracts:{slug:"contracts",api:"contracts",name:"العقود الأمريكية",sub:"المؤشرات والسلع",icon:"◈",source:"Yahoo Finance"},
    us:{slug:"us-stocks",api:"us",name:"الأسهم الأمريكية",sub:"أسهم وصناديق أمريكية",icon:"▥",source:"Yahoo Finance"},
    saudi:{slug:"saudi",api:"saudi",name:"السوق السعودي",sub:"أسهم تداول",icon:"🇸🇦",source:"Yahoo Finance"},
    forex:{slug:"forex-gold",api:"forex",name:"الفوركس والذهب",sub:"أزواج العملات والمعادن",icon:"◆",source:"Yahoo Finance"}
  };
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const pathToMarket = {
    "/markets/spot":"spot","/markets/futures":"futures","/markets/alpha":"alpha",
    "/markets/contracts":"contracts","/markets/us-stocks":"us","/markets/saudi":"saudi",
    "/markets/forex-gold":"forex"
  };
  const marketKey = pathToMarket[path];
  const scanIntervalOrder = ["15m","1h","2h","4h","1d","1w"];
  let scanCycleIndex = 0;
  let selectedInterval = "15m";
  let marketSignalRefreshTimer = null;
  let marketLiveTrackTimer = null;
  let marketSignalRefreshBusy = false;
  let lastMarketItems = [];
  let currentChartSymbol = "";
  let adminAuth = "";
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const price = (v) => {
    const n=Number(v); if(!Number.isFinite(n)) return "—";
    return n.toLocaleString("en-US",{maximumFractionDigits:n<1?8:n<100?5:2});
  };
  const pct = (v) => {const n=Number(v);return Number.isFinite(n)?(n>0?"+":"")+n.toFixed(2)+"%":"—"};
  const timeText = (v) => {const n=Number(v);if(!n)return "—";try{return new Date(n<1e12?n*1000:n).toLocaleString("ar-SA",{dateStyle:"medium",timeStyle:"short"})}catch(_){return "—"}};
  async function getJSON(url, opts={}) {
    const controller = new AbortController();
    const timer = setTimeout(()=>controller.abort(), API_TIMEOUT);
    try {
      const response = await fetch(url,{cache:"no-store",...opts,signal:controller.signal});
      const raw = await response.text();
      let data; try {data=JSON.parse(raw)} catch(_){data={message:raw.slice(0,250)||"استجابة غير مفهومة من الخادم."}}
      if(!response.ok) throw new Error(data.detail || data.message || ("تعذر الطلب ("+response.status+")"));
      return data;
    } catch(err) {
      if(err.name==="AbortError") throw new Error("انتهت مهلة الاتصال. جرّب التحديث بعد قليل.");
      throw err;
    } finally {clearTimeout(timer)}
  }
  function setStatus(text, good=true) {
    const node=$("serviceStatus"); if(!node)return;
    node.innerHTML='<i style="background:'+(good?'var(--green)':'var(--gold)')+'"></i> '+esc(text);
  }
  function empty(message, detail="") {
    return '<div class="empty"><strong>'+esc(message)+'</strong>'+(detail?'<div>'+esc(detail)+'</div>':"")+'</div>';
  }
  function pageHeader(title, desc, crumb="الرئيسية") {
    return '<div class="section-heading"><div><span class="eyebrow">'+esc(crumb)+'</span><h1 class="page-title">'+esc(title)+'</h1><p class="page-intro">'+esc(desc)+'</p></div></div>';
  }
  function footerNotice(text) { return '<p class="news-summary">'+esc(text)+'</p>'; }
  function activateDrawer() {
    const drawer=$("drawer"), backdrop=$("backdrop"), toggle=$("menuToggle");
    const open=()=>{drawer.classList.add("open");backdrop.hidden=false;drawer.setAttribute("aria-hidden","false");toggle.setAttribute("aria-expanded","true");document.body.style.overflow="hidden"};
    const close=()=>{drawer.classList.remove("open");backdrop.hidden=true;drawer.setAttribute("aria-hidden","true");toggle.setAttribute("aria-expanded","false");document.body.style.overflow=""};
    toggle?.addEventListener("click",open);$("menuClose")?.addEventListener("click",close);backdrop?.addEventListener("click",close);
    document.addEventListener("keydown",e=>{if(e.key==="Escape")close()});
    drawer?.querySelectorAll("a").forEach(a=>a.addEventListener("click",close));
    document.querySelectorAll("[data-nav]").forEach(a=>{if(a.getAttribute("href")===path)a.classList.add("active")});
  }
  function renderHome() {
    getJSON("/api/status").then(data=>{
      const status=$("homeStatus");
      if(status)status.textContent=data.ok?"الخدمة تستجيب · بيانات الأسعار حسب المصدر":"الخدمة غير متاحة";
      setStatus(data.ok?"الخدمة جاهزة":"تحقق من الخدمة",!!data.ok);
    }).catch(()=>{
      const status=$("homeStatus");
      if(status)status.textContent="تعذر التحقق من الخدمة الآن";
      setStatus("تعذر التحقق",false);
    });
  }
  function quoteRows(items) {
    if(!items.length)return empty("لا توجد أصول متاحة","لم يرجع المصدر أصولًا قابلة للعرض.");
    return '<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>الشارت</th></tr></thead><tbody>'+
      items.map(x=>'<tr><td><b dir="ltr">'+esc(x.symbol||"—")+'</b></td><td><span class="pill">اضغط لعرض الشارت</span></td></tr>').join("")+
      '</tbody></table></div>';
  }
  function renderMarketPage(key) {
    const m=markets[key]; if(!m)return;
    view.innerHTML=
      '<style>'+
      '.surge-page{color:var(--text);background:radial-gradient(ellipse at 75% -10%,#12365b 0,transparent 42%),#06101d;border:1px solid #18334a;border-radius:20px;padding:clamp(12px,2vw,22px)}'+
      '.surge-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px}'+
      '.surge-hero{border:1px solid #20415d;background:linear-gradient(110deg,#0b2034,#0b1626);border-radius:18px;padding:20px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}'+
      '.surge-hero h1{font-size:clamp(22px,3vw,32px);margin:0 0 8px}.surge-hero p{color:#a9bfd5;margin:0;line-height:1.8;max-width:700px}'+
      '.surge-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}'+
      '.surge-stat{background:linear-gradient(145deg,#0c1d2e,#081522);border:1px solid #18334a;border-radius:14px;padding:13px;min-width:0}'+
      '.surge-stat small{color:#91a8c0;font-size:12px}.surge-stat strong{display:block;font-size:clamp(18px,2.2vw,25px);margin-top:8px;overflow-wrap:anywhere}'+
      '.surge-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(260px,.8fr);gap:14px}'+
      '.surge-panel{background:linear-gradient(145deg,#0c1d2e,#081522);border:1px solid #18334a;border-radius:15px;padding:14px;min-width:0}'+
      '.surge-head{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}.surge-head h2{font-size:16px;margin:0}'+
      '.surge-chip{border:1px solid #244661;border-radius:99px;padding:6px 10px;color:#91a8c0;font-size:11px}'+
      '.surge-table-wrap{overflow:auto} .surge-table{border-collapse:collapse;width:100%;min-width:560px}.surge-table th,.surge-table td{text-align:right;padding:11px 8px;border-bottom:1px solid #142b3e;font-size:12px;white-space:nowrap}.surge-table th{color:#91a8c0;font-size:11px}.surge-table tr:last-child td{border-bottom:0}'+
      '.surge-pos{color:#16d99a}.surge-neg{color:#ff647c}.surge-score{display:inline-flex;min-width:38px;justify-content:center;border-radius:7px;padding:5px 7px;background:#123e36;color:#6effcb;font-weight:800}.surge-score.mid{background:#40361b;color:#ffd976}.surge-score.low{background:#342537;color:#e0b2ff}'+
      '.surge-list{display:grid;gap:9px}.surge-item{border:1px solid #1a354a;border-radius:11px;padding:11px}.surge-item-head{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:12px;font-weight:700}.surge-item p{margin:7px 0 0;color:#91a8c0;font-size:11px;line-height:1.7}'+
      '.surge-heat{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.surge-heatbox{border-radius:9px;padding:10px 7px;background:#103b32;border:1px solid #1a5948;min-width:0}.surge-heatbox.down{background:#3a1d2b;border-color:#5e2c40}.surge-heatbox b{display:block;font-size:12px;overflow-wrap:anywhere}.surge-heatbox span{font-size:11px}.surge-muted{color:#91a8c0;font-size:11px;line-height:1.8}.surge-status{color:#91a8c0;font-size:12px;min-height:22px;margin-bottom:6px}.surge-empty{padding:22px;text-align:center;color:#91a8c0;font-size:12px}'+
      '@media(max-width:850px){.surge-layout{grid-template-columns:1fr}.surge-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:420px){.surge-page{padding:9px}.surge-hero{padding:14px}.surge-panel{padding:10px}.surge-stat{padding:10px}}'+
      '</style>'+
      '<div class="surge-page">'+
      '<div class="surge-top"><div><span class="eyebrow">SMART TRADING PRO · '+esc(m.source.toUpperCase())+'</span><h1 class="page-title" style="margin:5px 0">'+esc(m.name)+'</h1><p class="muted">'+esc(m.sub)+' · نموذج رصد حركة السوق، بدون صفقات أو توصيات شراء وبيع.</p></div><button class="button primary small" id="surgeRefresh">↻ تحديث البيانات</button></div>'+
      '<section class="surge-hero"><div><div style="color:#ffc85a;font-size:11px;margin-bottom:7px">MARKET MONITOR · '+esc(m.source.toUpperCase())+'</div><h1>'+esc(m.name)+' — رصد حركة السوق</h1><p>يعرض الأصول الفعلية المتاحة من مصدر هذا السوق، ويرتب تغيّر الأسعار وقيمة التداول. لا ينشئ صفقات أو أهدافًا أو وقف خسارة.</p></div><span class="surge-chip" id="surgeConnection">● جاري الاتصال بالمصدر</span></section>'+
      '<section class="surge-stats"><div class="surge-stat"><small>الأصول المفحوصة</small><strong id="surgeCount">—</strong><span class="surge-muted">من مصدر السوق المحدد</span></div><div class="surge-stat"><small>أصول صاعدة</small><strong id="surgeUp" class="surge-pos">—</strong><span class="surge-muted">حسب تغيّر السعر</span></div><div class="surge-stat"><small>أصول هابطة</small><strong id="surgeDown" class="surge-neg">—</strong><span class="surge-muted">حسب تغيّر السعر</span></div><div class="surge-stat"><small>أقوى تغيّر</small><strong id="surgeBest">—</strong><span class="surge-muted" id="surgeBestSymbol">بانتظار البيانات</span></div></section>'+
      '<div class="surge-layout"><section class="surge-panel"><div class="surge-head"><h2>◈ الأصول وترتيب الحركة</h2><span class="surge-chip" id="surgeUpdated">آخر تحديث —</span></div><div class="surge-status" id="surgeStatus">جاري تحميل بيانات السوق…</div><div class="surge-table-wrap"><table class="surge-table"><thead><tr><th>#</th><th>الأصل</th><th>السعر</th><th>التغيّر</th><th>قيمة التداول</th><th>درجة الرصد</th></tr></thead><tbody id="surgeRows"><tr><td colspan="6" class="surge-empty">جاري الاتصال بمصدر البيانات…</td></tr></tbody></table></div><p class="surge-muted">درجة الرصد لترتيب الأصول حسب حركة السعر والسيولة المتاحة، وليست احتمال ربح أو توصية تداول.</p></section>'+
      '<aside class="surge-panel"><div class="surge-head"><h2>🧭 ملخص الحركة</h2><span class="surge-chip">بيانات وصفية</span></div><div id="surgeHighlights" class="surge-list"><div class="surge-empty">بانتظار البيانات</div></div><div style="height:15px"></div><div class="surge-head"><h2>خريطة الحركة</h2></div><div id="surgeHeat" class="surge-heat"><div class="surge-empty">بانتظار البيانات</div></div><div style="height:15px"></div><div class="surge-head"><h2>اتجاه السوق</h2><button class="button small" id="surgeDirectionRefresh">تحديث</button></div><div id="surgeDirection" class="surge-list"><div class="surge-empty">جاري حساب الاتجاه…</div></div></aside></div>'+
      '<p class="surge-muted" style="margin-top:14px">الأسعار وتغطية الأصول تعتمد على المصدر المتاح لكل سوق وقد تتأخر. عند تعذّر المصدر لن تُعرض أرقام وهمية. لا توجد أوامر تداول آلية.</p></div>';
    let busy=false;
    const loadDirection=async()=>{const out=$("surgeDirection");if(!out)return;out.innerHTML='<div class="surge-empty">جاري حساب اتجاه السوق…</div>';try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(m.api));if(!d.ok)throw new Error(d.message||"الاتجاه غير متاح");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0);const color=d.direction==="BULLISH"?"#16d99a":d.direction==="BEARISH"?"#ff647c":"#ffc85a";out.innerHTML='<div class="surge-item"><div class="surge-item-head"><span>التوجّه العام</span><strong style="color:'+color+'">'+esc(d.direction_ar||"محايد")+'</strong></div><p>متوسط التغيّر: '+esc(pct(d.price_change_pct))+'<br>صاعد: '+up+' · هابط: '+down+' · مستقر: '+flat+'<br>العينة: '+esc(d.assets_sampled??up+down+flat)+' أصل</p></div>';}catch(e){out.innerHTML='<div class="surge-empty">'+esc(e.message||"الاتجاه غير متاح")+'</div>'}};
    async function refresh(){
      if(busy)return;busy=true;const btn=$("surgeRefresh");if(btn)btn.disabled=true;
      $("surgeStatus").textContent="جاري تحميل قائمة الأصول وترتيب الحركة…";$("surgeConnection").textContent="● جاري التحديث";
      try{
        const d=await getJSON("/api/market/"+encodeURIComponent(m.api)+"?limit=2000");
        if(!d||!Array.isArray(d.items))throw new Error(d.message||"المصدر لم يرجع قائمة أصول صالحة");
        if(d.live===false||d.stale===true)throw new Error(d.message||"البيانات قديمة؛ لم نعرض ترتيبًا جديدًا");
        const items=d.items.filter(x=>x&&String(x.symbol||"").trim()&&Number.isFinite(Number(x.price))&&Number(x.price)>0&&Number.isFinite(Number(x.change_pct)));
        if(!items.length)throw new Error("لم تتوفر أصول بأسعار وتغيّرات قابلة للفحص");
        const maxVol=Math.max(1,...items.map(x=>Number(x.quote_volume||x.dollar_volume||0)));
        const scored=items.map(x=>{const change=Number(x.change_pct)||0;const vol=Number(x.quote_volume||x.dollar_volume||0);const move=Math.min(65,Math.abs(change)*7);const liquidity=vol>0?Math.min(25,Math.log10(1+vol/100000)*6):0;const score=Math.round(Math.max(0,Math.min(100,15+move+liquidity)));return {...x,change,vol,score}}).sort((a,b)=>b.score-a.score);
        const up=scored.filter(x=>x.change>0).sort((a,b)=>b.score-a.score),down=scored.filter(x=>x.change<0).sort((a,b)=>b.score-a.score);
        $("surgeCount").textContent=items.length.toLocaleString("en-US");$("surgeUp").textContent=up.length.toLocaleString("en-US");$("surgeDown").textContent=down.length.toLocaleString("en-US");
        const best=[...scored].sort((a,b)=>Math.abs(b.change)-Math.abs(a.change))[0];$("surgeBest").textContent=(best.change>0?"+":"")+best.change.toFixed(2)+"%";$("surgeBest").className=best.change>=0?"surge-pos":"surge-neg";$("surgeBestSymbol").textContent=best.symbol;
        $("surgeUpdated").textContent="آخر تحديث "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
        $("surgeConnection").textContent="● بيانات متاحة · "+(d.provider||m.source);
        $("surgeStatus").textContent="تم تحميل "+items.length+" أصلًا · عرض أقوى الحركات حسب السعر والسيولة.";
        const fmtVol=n=>!Number.isFinite(n)||n<=0?"—":n>=1e9?(n/1e9).toFixed(2)+"B":n>=1e6?(n/1e6).toFixed(2)+"M":n.toLocaleString("en-US",{maximumFractionDigits:0});
        $("surgeRows").innerHTML=scored.slice(0,40).map((x,i)=>'<tr><td>'+(i+1)+'</td><td><strong dir="ltr">'+esc(x.symbol)+'</strong></td><td>'+esc(price(x.price))+' '+esc(x.currency||"")+'</td><td class="'+(x.change>=0?"surge-pos":"surge-neg")+'">'+esc(pct(x.change))+'</td><td>'+fmtVol(x.vol)+'</td><td><span class="surge-score '+(x.score<45?"low":x.score<70?"mid":"")+'">'+x.score+'</span></td></tr>').join("");
        const highlights=[...up.slice(0,3).map(x=>({...x,side:"صاعد"})),...down.slice(0,3).map(x=>({...x,side:"هابط"}))];
        $("surgeHighlights").innerHTML=highlights.length?highlights.map(x=>'<div class="surge-item"><div class="surge-item-head"><strong dir="ltr">'+esc(x.symbol)+'</strong><span class="'+(x.change>=0?"surge-pos":"surge-neg")+'">'+x.side+' · '+esc(pct(x.change))+'</span></div><p>السعر: '+esc(price(x.price))+' '+esc(x.currency||"")+'<br>قيمة التداول: '+fmtVol(x.vol)+' · درجة الرصد '+x.score+'/100</p></div>').join(""):'<div class="surge-empty">لا توجد حركة متاحة</div>';
        $("surgeHeat").innerHTML=scored.slice(0,6).map(x=>'<div class="surge-heatbox '+(x.change<0?"down":"")+'"><b dir="ltr">'+esc(x.symbol)+'</b><span class="'+(x.change>=0?"surge-pos":"surge-neg")+'">'+esc(pct(x.change))+'</span></div>').join("");
      }catch(e){$("surgeConnection").textContent="● تعذر الاتصال";$("surgeStatus").textContent="تعذر تحميل البيانات: "+(e.message||"خطأ غير معروف");$("surgeRows").innerHTML='<tr><td colspan="6" class="surge-empty">لم نعرض أرقامًا وهمية بدل البيانات الحقيقية.</td></tr>';$("surgeHighlights").innerHTML='<div class="surge-empty">بيانات الحركة غير متاحة.</div>';$("surgeHeat").innerHTML='<div class="surge-empty">لا توجد بيانات متاحة</div>';$("surgeCount").textContent="—";$("surgeUp").textContent="—";$("surgeDown").textContent="—";$("surgeBest").textContent="—";$("surgeBestSymbol").textContent="بانتظار البيانات";}
      finally{busy=false;if(btn)btn.disabled=false}
    }
    $("surgeRefresh").addEventListener("click",refresh);$("surgeDirectionRefresh").addEventListener("click",loadDirection);
    refresh();loadDirection();
    if(marketSignalRefreshTimer)clearInterval(marketSignalRefreshTimer);
    if(marketLiveTrackTimer)clearInterval(marketLiveTrackTimer);
    marketSignalRefreshTimer=setInterval(()=>{if(document.visibilityState==="visible"&&$("surgeRows"))refresh()},180000);
  }
  async function loadQuotes(m) {
    const out=$("quoteContent"), meta=$("quoteMeta"); if(!out)return;
    out.innerHTML='<div class="loading">جاري تحميل بيانات '+esc(m.name)+'…</div>';meta.textContent="تحميل قائمة الأصول";
    $("loadQuotes").disabled=true;$("refreshQuotes").disabled=true;
    try {
      const d=await getJSON("/api/market/"+encodeURIComponent(m.api)+"?limit=100");
      lastMarketItems=Array.isArray(d.items)?d.items:[];
      out.innerHTML=quoteRows(lastMarketItems);
      meta.textContent="تم تحميل "+lastMarketItems.length+" أصل · الأسعار مخفية";
      setStatus(d.live?"بيانات متاحة":"بيانات محدودة",!!d.live);
      if(!lastMarketItems.length)out.innerHTML=empty("المصدر لم يعرض أسعارًا",d.message||"لا توجد بيانات متاحة حاليًا.");
      else {out.querySelectorAll("tbody tr").forEach((row,i)=>{const symbol=lastMarketItems[i]?.symbol;if(symbol){row.tabIndex=0;row.setAttribute("role","button");row.setAttribute("aria-label","الأصل "+symbol);row.dataset.symbol=symbol}})}
    } catch(err) {out.innerHTML=empty("تعذر تحميل الأسعار",err.message);meta.textContent="تعذر تحميل الأصول";setStatus("مصدر غير متاح",false)}
    finally {$("loadQuotes").disabled=false;$("refreshQuotes").disabled=false}
  }
  function drawCandles(items, levels={}) {
    const rows=(items||[]).filter(c=>[c.open,c.high,c.low,c.close].every(v=>Number.isFinite(Number(v))&&Number(v)>0));
    if(rows.length<2)return empty("بيانات الشموع غير كافية","لم يرسم الموقع أي شموع تقديرية.");
    const W=1000,H=380,left=28,right=190,topPad=24,bottomPad=28;
    const priceLevels=[
      {label:"TP3",value:levels.tp3,color:"#38d996"},
      {label:"TP2",value:levels.tp2,color:"#38d996"},
      {label:"TP1",value:levels.tp1,color:"#38d996"},
      {label:"الدخول",value:levels.entry,color:"#f5c451"},
      {label:"وقف",value:levels.stop_loss??levels.stop,color:"#ff7184"}
    ].filter(v=>Number.isFinite(Number(v.value))&&Number(v.value)>0);
    const rawLow=Math.min(...rows.map(c=>Number(c.low)),...priceLevels.map(v=>Number(v.value)));
    const rawHigh=Math.max(...rows.map(c=>Number(c.high)),...priceLevels.map(v=>Number(v.value)));
    const padding=(rawHigh-rawLow)*.06||Math.max(rawHigh*.01,.00000001);
    const lo=Math.max(Number.MIN_VALUE,rawLow-padding),hi=rawHigh+padding,range=hi-lo||1;
    const plotRight=W-right,plotWidth=plotRight-left,plotHeight=H-topPad-bottomPad;
    const y=v=>topPad+(hi-Number(v))/range*plotHeight;
    const step=plotWidth/rows.length,bodyW=Math.max(2,Math.min(9,step*.58));
    const grid=[0,.25,.5,.75,1].map(t=>{const yy=topPad+plotHeight*t,priceValue=hi-range*t;return '<line x1="'+left+'" y1="'+yy+'" x2="'+plotRight+'" y2="'+yy+'" stroke="#26364d" stroke-width="1"/><text x="'+(plotRight-5)+'" y="'+(yy-4)+'" fill="#8fa2bd" font-size="11" text-anchor="end">'+esc(price(priceValue))+'</text>'}).join("");
    const candles=rows.map((c,i)=>{const x=left+step*i+step/2,up=Number(c.close)>=Number(c.open),color=up?"#43d6a1":"#ff7184",candleTop=y(Math.max(Number(c.open),Number(c.close))),bottom=y(Math.min(Number(c.open),Number(c.close))),height=Math.max(1,bottom-candleTop);return '<line x1="'+x+'" y1="'+y(c.high)+'" x2="'+x+'" y2="'+y(c.low)+'" stroke="'+color+'" stroke-width="1.3"/><rect x="'+(x-bodyW/2)+'" y="'+candleTop+'" width="'+bodyW+'" height="'+height+'" fill="'+color+'" rx=".5"/>'}).join("");
    // Keep right-side level labels separated so close targets/stop values remain readable.
    const labelRows=priceLevels.map((level,index)=>({level,index,actualY:y(level.value),labelY:y(level.value)})).sort((a,b)=>a.actualY-b.actualY);
    const minLabelY=topPad+10,maxLabelY=H-bottomPad-10,labelGap=24;
    labelRows.forEach((row,i)=>{row.labelY=Math.max(row.actualY,i?labelRows[i-1].labelY+labelGap:minLabelY)});
    if(labelRows.length&&labelRows[labelRows.length-1].labelY>maxLabelY){const shift=labelRows[labelRows.length-1].labelY-maxLabelY;labelRows.forEach(row=>row.labelY-=shift)}
    const labelByIndex=new Map(labelRows.map(row=>[row.index,row]));
    const levelLines=priceLevels.map((level,index)=>{const row=labelByIndex.get(index),yy=row.actualY,ly=row.labelY;return '<line x1="'+left+'" y1="'+yy+'" x2="'+(plotRight+8)+'" y2="'+yy+'" stroke="'+level.color+'" stroke-width="1.7" stroke-dasharray="7 4"/><line x1="'+(plotRight+8)+'" y1="'+yy+'" x2="'+(plotRight+8)+'" y2="'+ly+'" stroke="'+level.color+'" stroke-width="1.1"/><line x1="'+(plotRight+8)+'" y1="'+ly+'" x2="'+(W-8)+'" y2="'+ly+'" stroke="'+level.color+'" stroke-width="1.7" stroke-dasharray="7 4"/><rect x="'+(plotRight+8)+'" y="'+(ly-10)+'" width="'+(right-20)+'" height="20" rx="5" fill="'+level.color+'"/><text x="'+(plotRight+14)+'" y="'+(ly+4)+'" fill="#07111e" font-size="11" font-weight="700">'+esc(level.label)+' '+esc(price(level.value))+'</text>'}).join("");
    const last=Number(rows[rows.length-1].close);
    const currentLine='<line x1="'+left+'" y1="'+y(last)+'" x2="'+plotRight+'" y2="'+y(last)+'" stroke="#8da5ff" stroke-width="1.4" stroke-dasharray="3 4"/>';
    return '<div style="width:100%;overflow:hidden"><svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="شموع سعرية فعلية مع خط السعر الحالي والدخول ووقف الخسارة والأهداف" style="width:100%;height:auto;display:block;background:#0a1321;border-radius:12px">'+grid+currentLine+candles+levelLines+'</svg></div><div class="muted" style="margin-top:8px">آخر إغلاق: <b dir="ltr">'+esc(price(last))+'</b> · '+rows.length+' شمعة فعلية · خطوط الدخول والوقف والأهداف من بيانات الصفقة</div>';
  }
  async function loadChart(m,symbol) {
    currentChartSymbol=symbol;
    const out=$("chartContent"),meta=$("chartMeta"),badge=$("chartSymbol");if(!out)return;
    badge.textContent=symbol;out.innerHTML='<div class="loading">جاري تحميل الشموع الفعلية…</div>';meta.textContent=m.name+" · "+selectedInterval;
    try {const d=await getJSON("/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(symbol)+"&interval="+encodeURIComponent(selectedInterval));out.innerHTML=drawCandles(d.items||[]);meta.textContent=m.source+" · "+selectedInterval+" · "+(d.items||[]).length+" شمعة"}
    catch(err){out.innerHTML=empty("الشارت غير متاح",err.message);meta.textContent="لا توجد بيانات شموع مؤكدة"}
  }
  function signalCard(x, rank=0, marketKey="") {
    const l=x.levels||{};
    const side=x.direction||x.side||"غير محدد";
    const strength=x.signal_strength||side;
    const buy=["شراء","BUY","LONG"].includes(side);
    const entry=Number(l.entry??x.entry);
    const pctTo=(target, favorable)=> {
      const n=Number(target);
      if(!Number.isFinite(entry)||entry<=0||!Number.isFinite(n)||n<=0)return "—";
      const value=(buy?n-entry:entry-n)/entry*100;
      return (value>0?"+":"")+value.toFixed(2)+"%";
    };
    const medal=rank===0?"🥇 ذهبي":rank===1?"🥈 فضي":rank===2?"🥉 برونزي":"🏅 #"+(rank+1);
    const stop=l.stop_loss??x.stop_loss,tp1=l.tp1??x.tp1,tp2=l.tp2??x.tp2,tp3=l.tp3??x.tp3;
    return '<article class="signal-card"><div class="signal-top"><span class="tag" style="font-weight:800;border:1px solid #c79b35;background:linear-gradient(135deg,#35270a,#9b7622);color:#fff0b3">'+medal+'</span><b class="signal-symbol">'+esc(x.symbol||"—")+'</b><span class="tag '+(buy?"buy":"sell")+'">'+esc(strength)+'</span><span class="tag">تقييم الأدلة '+esc(x.combined_score??x.ai_score??x.confidence??"—")+'/100</span></div>'+
      '<div class="entry-line"><span>الدخول</span><strong>'+price(entry)+'</strong></div><div class="levels-grid">'+
      '<div class="level stop"><small>وقف الخسارة</small><strong>'+price(stop)+'</strong><small class="negative">خسارة محتملة '+pctTo(stop,false)+'</small></div>'+
      '<div class="level target"><small>الهدف الأول</small><strong>'+price(tp1)+'</strong><small class="positive">ربح محتمل '+pctTo(tp1,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثاني</small><strong>'+price(tp2)+'</strong><small class="positive">ربح محتمل '+pctTo(tp2,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثالث</small><strong>'+price(tp3)+'</strong><small class="positive">ربح محتمل '+pctTo(tp3,true)+'</small></div></div>'+
      '<div class="trade-live-tracker" data-live-symbol="'+esc(x.symbol||"")+'" data-live-market="'+esc(marketKey||x.market||"")+'" data-live-direction="'+esc(side)+'"><span>متابعة الصفقة الحية</span><strong data-live-status>جارٍ ربط سجل الصفقة…</strong><small data-live-price>آخر سعر: —</small></div>'+
      (x.url&&/^https?:\/\//i.test(x.url)?'<p class="muted" style="margin-top:10px"><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">فتح المنشور الأصلي للمصدر ↗</a> · الاتجاه الأصلي: '+esc(x.original_direction||"—")+'</p>':"")+
      '<div class="toolbar" style="margin-top:12px"><button type="button" class="button small" data-inline-chart="1" data-symbol="'+esc(x.symbol||"")+'" data-frame="'+esc(x.interval||selectedInterval)+'" data-entry="'+esc(entry)+'" data-stop="'+esc(stop)+'" data-tp1="'+esc(tp1)+'" data-tp2="'+esc(tp2)+'" data-tp3="'+esc(tp3)+'">عرض الشارت داخل الصفقة</button></div><div data-chart-box data-open="0" style="margin-top:10px"></div><div class="muted" style="margin-top:10px">'+esc(x.status||"النسب تقديرية من سعر الدخول إلى الهدف/الوقف، قبل الرسوم والانزلاق")+'</div></article>';
  }
  async function refreshLiveTradeTracking(m) {
    const cards=Array.from(document.querySelectorAll(".trade-live-tracker"));
    if(!cards.length)return;
    try {
      const data=await getJSON("/api/results?limit=200");
      const rows=Array.isArray(data.items)?data.items:[];
      cards.forEach(card=>{
        const symbol=card.dataset.liveSymbol;
        const direction=card.dataset.liveDirection;
        const row=rows.find(item=>String(item.market||"")===m.api && String(item.symbol||"").toUpperCase()===String(symbol||"").toUpperCase() && String(item.direction||"")===direction);
        const status=card.querySelector("[data-live-status]");
        const live=card.querySelector("[data-live-price]");
        if(!row){status.textContent="بانتظار تسجيل الصفقة في سجل المتابعة";live.textContent="آخر سعر: —";return;}
        const result=String(row.result||"OPEN").toUpperCase();
        status.textContent=row.status || (result==="TP3"?"اكتملت عند الهدف الثالث":result==="SL"?"انتهت عند وقف الخسارة":"صفقة مفتوحة — متابعة السعر");
        live.textContent="السعر الحالي: "+price(row.last_price)+" · الأداء غير المحقق: "+pct(row.pnl_pct);
        card.dataset.progress=String(row.progress||0);
      });
    } catch(_) {
      cards.forEach(card=>{const status=card.querySelector("[data-live-status]");if(status)status.textContent="تعذّر تحديث المتابعة مؤقتًا";});
    }
  }
  async function loadSignals(m) {
    if(marketSignalRefreshBusy)return;
    const out=$("signalContent"),meta=$("signalMeta"),status=$("signalAutoStatus");
    if(!out||!meta)return;
    marketSignalRefreshBusy=true;
    if(status)status.textContent="● جاري مسح الأصول";
    meta.textContent="ماسح الزخم: تغير السعر والسيولة وترتيب أقوى الحركة في هذا السوق فقط.";
    out.innerHTML='<div class="loading">جاري فحص الأصول المتاحة من مصدر السوق…</div>';
    try {
      const d=await getJSON("/api/market/"+encodeURIComponent(m.api)+"?limit=2000");
      if(!d||!Array.isArray(d.items))throw new Error(d.message||"المصدر لم يرجع قائمة أصول صالحة.");
      if(d.live===false||d.stale===true)throw new Error(d.message||"البيانات قديمة؛ أوقفنا ترتيب فرص جديدة حتى تتجدد.");
      const sourceItems=d.items.filter(x=>x&&String(x.symbol||"").trim()&&Number.isFinite(Number(x.price))&&Number(x.price)>0&&Number.isFinite(Number(x.change_pct)));
      const maxVol=Math.max(1,...sourceItems.map(x=>Number(x.quote_volume||x.dollar_volume||0)));
      const scored=sourceItems.map(x=>{
        const change=Number(x.change_pct)||0;
        const dollarVol=Number(x.quote_volume||x.dollar_volume||0);
        const avgVol=Number(x.avg_dollar_volume_5d||0);
        const relVol=avgVol>0?dollarVol/avgVol:null;
        const moveScore=Math.min(58,Math.abs(change)*7);
        const liquidityScore=Math.min(22,Math.log10(1+dollarVol/100000)*5);
        const volumeScore=relVol===null?0:Math.max(-10,Math.min(20,(relVol-1)*10));
        const score=Math.round(Math.max(0,Math.min(100,20+moveScore+liquidityScore+volumeScore)));
        const reasons=[];
        if(Math.abs(change)>=2)reasons.push("حركة يومية ملحوظة");
        if(relVol!==null)reasons.push("حجم مقابل متوسط 5 أيام: "+relVol.toFixed(1)+"×");
        if(dollarVol>0)reasons.push("قيمة تداول متاحة");
        if(Math.abs(change)>8)reasons.push("تنبيه: حركة حادة وقد تكون متأخرة");
        return {...x,change,dollarVol,relVol,score,reasons};
      });
      const rising=scored.filter(x=>x.change>0).sort((a,b)=>b.score-a.score||b.change-a.change).slice(0,10);
      const falling=scored.filter(x=>x.change<0).sort((a,b)=>b.score-a.score||a.change-b.change).slice(0,10);
      const top=[...rising.slice(0,5),...falling.slice(0,5)];
      const formatVol=n=>!Number.isFinite(n)||n<=0?"—":n>=1e9?(n/1e9).toFixed(2)+"B":n>=1e6?(n/1e6).toFixed(2)+"M":n.toLocaleString("en-US",{maximumFractionDigits:0});
      const card=(x,i,side)=>'<article class="signal-card"><div class="signal-card-head"><div><span class="signal-rank">#'+(i+1)+'</span> <strong dir="ltr">'+esc(x.symbol)+'</strong></div><span class="'+(side==="up"?"pos":"neg")+'">'+(side==="up"?"زخم صاعد":"زخم هابط")+'</span></div><div class="signal-metrics"><div><small>السعر</small><strong>'+esc(price(x.price))+' '+esc(x.currency||"")+'</strong></div><div><small>تغير السعر</small><strong class="'+(x.change>=0?"pos":"neg")+'">'+pct(x.change)+'</strong></div><div><small>درجة الرصد</small><strong>'+x.score+'/100</strong></div></div><div class="signal-progress"><span style="width:'+x.score+'%"></span></div><p class="signal-reasons">'+esc(x.reasons.join(" · ")||"الحركة والسعر حسب المصدر")+'</p><small class="muted">قيمة التداول التقريبية: '+formatVol(x.dollarVol)+(d.provider?" · "+esc(d.provider):"")+'</small></article>';
      if(!sourceItems.length)throw new Error("لم تتوفر أصول بأسعار وتغيرات قابلة للفحص.");
      const bestBox=$("marketBestSides");
      if(bestBox)bestBox.innerHTML='<div class="feature-card"><small>أقوى زخم صاعد</small><strong dir="ltr">'+esc(rising[0]?.symbol||"لا توجد حركة صاعدة")+'</strong><small>'+(rising[0]?pct(rising[0].change)+" · درجة "+rising[0].score+"/100":"لم تظهر بيانات صاعدة صالحة")+'</small></div><div class="feature-card"><small>أقوى زخم هابط</small><strong dir="ltr">'+esc(falling[0]?.symbol||"لا توجد حركة هابطة")+'</strong><small>'+(falling[0]?pct(falling[0].change)+" · درجة "+falling[0].score+"/100":"لم تظهر بيانات هابطة صالحة")+'</small></div>';
      meta.textContent="تم فحص "+sourceItems.length+" أصلًا · "+(d.provider||m.source)+(d.delayed?" · الأسعار قد تكون متأخرة":"")+" · الدرجة للترتيب وليست احتمال ربح";
      out.innerHTML=top.length?'<div class="surge-results-grid">'+rising.slice(0,5).map((x,i)=>card(x,i,"up")).join("")+falling.slice(0,5).map((x,i)=>card(x,i,"down")).join("")+'</div><p class="note">هذا ماسح زخم أولي يعتمد على تغير السعر والسيولة التي يوفرها المصدر، وليس توصية دخول. لا ينشئ دخولًا أو أهدافًا أو وقفًا غير محسوب. لا توجد بيانات شموع 15 دقيقة/ساعة لكل الأسواق في هذا الفحص.</p>':empty("لا توجد حركة واضحة","لم يعرض المصدر أصولًا تتحرك صعودًا أو هبوطًا.");
    } catch(err) {
      out.innerHTML=empty("تعذر فحص السوق",err.message||"تحقق من مصدر بيانات هذا السوق.");
      meta.textContent="لم نعرض نتائج تقديرية عند فشل المصدر.";
      const bestBox=$("marketBestSides");if(bestBox)bestBox.innerHTML="";
    } finally {
      marketSignalRefreshBusy=false;
      if(status)status.textContent="● الفحص التلقائي نشط";
    }
  }
  async function renderResults() {
    view.innerHTML=pageHeader("نتائج الصفقات","سجل حيّ للفرص التي رصدها الفحص، مع فصل المفتوح عن النتائج المحققة.","مركز الأداء")+
      '<section class="panel results-panel"><div class="panel-head"><div><span class="eyebrow">TRADE JOURNAL</span><h2>لوحة الأداء</h2><p class="muted">تُسجّل الفرصة عند رصدها؛ ولا تُحسب رابحة أو خاسرة إلا بعد تسجيل TP أو SL.</p></div><button class="button primary small" id="refreshResults">↻ تحديث السجل</button></div><div id="resultStats" class="feature-grid results-stats"><div class="loading">جاري تحميل الملخص…</div></div><div id="resultTable" style="margin-top:18px" class="loading">جاري تحميل سجل الصفقات…</div></section>'+
      '<div class="notice">السجل يتتبع الفرص الجديدة. قد تبقى الصفقة «مفتوحة» إلى أن تتم إضافة متابعة أسعار وتأكيد وصول الهدف أو وقف الخسارة؛ لا تعتبر الفرص المفتوحة نتائج ربح أو خسارة.</div>';
    const load=async()=>{
      const out=$("resultTable"),button=$("refreshResults");
      out.innerHTML='<div class="loading">تحديث بيانات السجل…</div>';
      if(button)button.disabled=true;
      try {
        const d=await getJSON("/api/results?limit=200");
        const items=Array.isArray(d.items)?d.items:[];
        const open=items.filter(x=>!["TP1","TP2","TP3","SL"].includes(String(x.result||"").toUpperCase())).length;
        const stats=[
          ["إجمالي الفرص",d.total??items.length,"◷"],
          ["مفتوحة",open,"↻"],
          ["مغلقة",d.closed??0,"✓"],
          ["أهداف محققة",d.wins??0,"↗"],
          ["وقف خسارة",d.losses??0,"↓"],
          ["نسبة النجاح",d.win_rate==null?"—":d.win_rate+"%","%"]
        ];
        $("resultStats").innerHTML=stats.map((s,i)=>'<div class="feature-card result-stat result-stat-'+i+'"><span class="result-stat-icon">'+esc(s[2])+'</span><small>'+esc(s[0])+'</small><strong>'+esc(s[1])+'</strong></div>').join("");
        out.innerHTML=items.length?'<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>السوق / الفريم</th><th>الاتجاه</th><th>الدخول</th><th>وقف الخسارة</th><th>النتيجة</th><th>الأداء</th></tr></thead><tbody>'+items.map(x=>{
          const status=String(x.result||"OPEN").toUpperCase();
          const statusLabel=({OPEN:"مفتوحة",TP1:"هدف 1",TP2:"هدف 2",TP3:"هدف 3",SL:"وقف خسارة"})[status]||status;
          const closed=["TP1","TP2","TP3","SL"].includes(status);
          const side=x.side==="BUY"||x.side==="شراء"?"شراء":x.side==="SELL"||x.side==="بيع"?"بيع":x.side||"—";
          const pnl=x.pnl_pct==null?"—":pct(x.pnl_pct);
          return '<tr><td dir="ltr"><strong>'+esc(x.symbol||"—")+'</strong></td><td>'+esc(x.market||"—")+' / '+esc(x.interval||"—")+'</td><td>'+esc(side)+'</td><td class="ltr">'+price(x.entry)+'</td><td class="ltr">'+price(x.stop_loss)+'</td><td><span class="result-status '+(closed?"is-closed":"is-open")+'">'+esc(statusLabel)+'</span></td><td class="'+(Number(x.pnl_pct)>0?"positive":Number(x.pnl_pct)<0?"negative":"muted")+'">'+esc(pnl)+'</td></tr>';
        }).join("")+'</tbody></table></div>':empty("السجل جاهز وينتظر أول فرصة","الفحص يعمل تلقائيًا في الخلفية لكل سوق وفريم. ستظهر الفرص هنا عند اكتشافها، ولن تُحتسب نتيجة مالية قبل تأكيدها.");
      } catch(err) {
        out.innerHTML=empty("تعذر تحميل سجل النتائج",err.message||"تحقق من اتصال الخادم ثم حاول مرة أخرى.")+'<div style="margin-top:12px"><button class="button secondary" id="retryResults">إعادة المحاولة</button></div>';
        $("retryResults")?.addEventListener("click",load);
      } finally {if(button)button.disabled=false}
    };
    $("refreshResults").addEventListener("click",load);
    await load();
  }
  async function renderNews() {
    view.innerHTML=pageHeader("أخبار الأسواق","كل خبر يوضح السوق المتأثر والأصل المذكور والأثر المحتمل، مع رابط للمصدر. تصنيف الأثر آلي وأولي وليس توصية شراء أو بيع.","المتابعة")+
      '<section class="panel"><div class="panel-head"><h2>اختر السوق</h2><select id="newsMarket" class="frame" aria-label="اختر السوق"><option value="all">كل الأسواق</option><option value="crypto">العملات الرقمية</option><option value="us">الأسهم الأمريكية</option><option value="saudi">السوق السعودي</option><option value="forex">الفوركس والذهب</option><option value="contracts">العقود الأمريكية</option><option value="spot">سبوت</option><option value="futures">فيوتشر</option></select><button id="newsRefresh" class="btn" type="button">↻ تحديث الأخبار</button></div><div class="notice" style="margin:12px 0">الإيجابي/السلبي يعني الأثر المحتمل من نص الخبر فقط؛ لا يعني أن الأصل سيرتفع أو ينخفض حتمًا. إذا لم يذكر الخبر أصلًا واضحًا سيظهر «الأصل غير محدد» بدل التخمين.</div><div id="newsSummary" class="stats-grid"></div><div id="newsContent" class="loading">جاري تجهيز الأخبار…</div></section>';
    const marketNames={all:"كل الأسواق",crypto:"العملات الرقمية",us:"الأسهم الأمريكية",saudi:"السوق السعودي",forex:"الفوركس والذهب",contracts:"العقود الأمريكية",spot:"سبوت",futures:"فيوتشر",alpha:"Binance Alpha"};
    const escAttr=s=>esc(String(s||"")).replace(/"/g,"&quot;");
    const load=async(refresh=false)=>{
      const out=$("newsContent"),summary=$("newsSummary"),market=$("newsMarket").value;
      out.innerHTML='<div class="loading">جاري تحميل الأخبار من المصادر العامة…</div>';
      summary.innerHTML="";
      try{
        const d=await getJSON("/api/news?market="+encodeURIComponent(market)+"&limit=40"+(refresh?"&refresh=1":""));
        const items=Array.isArray(d.items)?d.items:[];
        const positive=items.filter(x=>/إيجابي|positive/i.test(x.direction_ar||"")).length;
        const negative=items.filter(x=>/سلبي|negative/i.test(x.direction_ar||"")).length;
        const unclear=items.length-positive-negative;
        summary.innerHTML=[
          ["الأخبار المعروضة",items.length],
          ["أثر إيجابي محتمل",positive],
          ["أثر سلبي محتمل",negative],
          ["الأثر غير محسوم",unclear]
        ].map(x=>'<article class="stat-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></article>').join("");
        if(!items.length){out.innerHTML=empty("ما فيه أخبار مطابقة",d.message||"جرّب سوقًا آخر أو حدّث الأخبار.");return;}
        out.innerHTML='<div class="news-grid">'+items.slice(0,24).map(x=>{
          const labels=Array.isArray(x.asset_labels)?x.asset_labels.filter(Boolean):[];
          const direction=String(x.direction_ar||"غير واضح");
          const positiveLike=/إيجابي|positive/i.test(direction);
          const negativeLike=/سلبي|negative/i.test(direction);
          const impact=positiveLike?"أثر إيجابي محتمل":negativeLike?"أثر سلبي محتمل":"الأثر غير محسوم";
          const badgeColor=positiveLike?"#16a34a":negativeLike?"#dc2626":"#64748b";
          const assets=labels.length?labels.join("، "):"الأصل غير محدد في الخبر";
          const source=String(x.source||"مصدر الخبر");
          const published=x.published_at?timeText(x.published_at):"وقت النشر غير متوفر";
          return '<article class="news-card"><div class="news-card-top"><span class="badge">'+esc(marketNames[x.market]||marketNames[market]||"السوق")+'</span><span class="news-impact" style="color:'+badgeColor+'">'+esc(impact)+'</span></div><strong class="news-title">'+esc(x.title||x.headline||"خبر سوق")+'</strong><div class="news-asset">الأصل المذكور: <b>'+esc(assets)+'</b></div><p class="muted">'+esc(x.description||x.summary||"لا يتوفر ملخص إضافي من المصدر.")+'</p><small class="news-meta">'+esc(source)+' · '+esc(published)+'</small></article>';
        }).join("")+'</div>';
      }catch(err){summary.innerHTML="";out.innerHTML=empty("تعذر تحميل الأخبار",err.message||"تحقق من اتصال الخدمة ثم أعد المحاولة.");}
    };
    $("newsMarket").addEventListener("change",()=>load(false));
    $("newsRefresh").addEventListener("click",()=>load(true));
    await load(false);
  }
  function renderAnalysis() {
    const items=[["حركة السعر","قراءة القمم والقيعان، الاتجاه، ومناطق الدعم والمقاومة."],["الاتجاه متعدد الفريمات","مقارنة الإطار الأكبر بفريم الدخول لتجنب التعارض."],["السيولة وبنية السوق","شرح مفاهيم BOS وCHOCH ومناطق السيولة بصورة تعليمية."],["إدارة المخاطر","تحديد نقطة إبطال الفكرة وحساب المخاطرة قبل التفكير في الهدف."],["الحجم والزخم","استخدام الحجم والزخم كسياق مساعد، لا كضمان مستقل."],["النماذج السعرية","فهم النماذج مع انتظار تأكيد سعري بدل توقع النتيجة مسبقًا."]];
    view.innerHTML=pageHeader("مكتبة التحليل","محتوى تعليمي مختصر. مختبر الاستراتيجيات وإعداداتها ليسا متاحين للمستخدم العادي.","التعلّم")+
      '<div class="feature-grid">'+items.map(x=>'<article class="feature-card"><span>⌁</span><strong>'+esc(x[0])+'</strong><small>'+esc(x[1])+'</small></article>').join("")+'</div><div class="notice" style="margin-top:16px">المحتوى للتثقيف فقط. لا توجد استراتيجية مضمونة الربح، ويجب اختبار أي قواعد تاريخيًا بعد الرسوم والانزلاق.</div>';
  }
  function renderCandleChart(items,label) {
    return '<div id="tasiChart">'+drawCandles(items)+'</div><div class="muted" style="margin-top:8px">'+esc(label||"شموع المؤشر الفعلية")+'</div>';
  }
  async function renderTasi() {
    view.innerHTML=pageHeader("تحليل تاسي العام","تحليل المؤشر العام وليس توصية على سهم منفرد.","السوق السعودي")+
      '<section class="panel"><div class="panel-head"><h2>الفريم</h2><button class="button small" id="tasiRefresh">تحديث التحليل</button></div><div class="frame-list" id="tasiFrames">'+["15m","1h","4h","1d","1w","1M"].map(f=>'<button class="frame '+(f==="1d"?"active":"")+'" data-frame="'+f+'">'+f+'</button>').join("")+'</div><div id="tasiContent" class="loading">جاري طلب التحليل…</div></section>';
    let frame="1d";
    const load=async()=>{
      const out=$("tasiContent");out.innerHTML='<div class="loading">تحميل بيانات المؤشر…</div>';
      try {
        const d=await getJSON("/api/tasi/analysis?interval="+encodeURIComponent(frame));
        const stats=[["آخر سعر",price(d.price)],["التغير",pct(d.change_pct)],["الاتجاه",d.trend||"—"],["الدعم",price(d.support)],["المقاومة",price(d.resistance)],["السيناريو",d.scenario||"—"]];
        out.innerHTML='<div class="feature-grid">'+stats.map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div><div class="panel" style="margin:14px 0"><div class="panel-head"><h2>شموع تاسي</h2><span class="pill">'+esc(frame)+'</span></div>'+renderCandleChart(d.candles||[],(d.provider||"مصدر عام")+(d.delayed?" · قد تكون البيانات متأخرة":""))+'</div><div class="feature-grid">'+[["الدخول المشروط",price(d.entry)],["وقف الخسارة",price(d.stop_loss)],["الهدف الأول",price(d.tp1)],["الهدف الثاني",price(d.tp2)],["الهدف الثالث",price(d.tp3)]].map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div><p class="muted">'+esc(d.message||"")+'</p>';
      } catch(err){out.innerHTML=empty("تعذر جلب تحليل تاسي",err.message)}
    };
    $("tasiFrames").addEventListener("click",e=>{const b=e.target.closest("[data-frame]");if(!b)return;frame=b.dataset.frame;$("tasiFrames").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===b));load()});
    $("tasiRefresh").addEventListener("click",load);
    await load();
  }
  function renderAccount() {
    view.innerHTML=pageHeader("الحساب","حالة الحسابات والخدمات المتاحة حاليًا.","الحساب")+
      '<section class="panel"><h2>حالة العضوية</h2><div class="notice" style="margin-top:12px">تسجيل حسابات العملاء والاشتراكات غير مفعّل في هذه النسخة. لن نعرض نموذج تسجيل لا يعمل.</div><div class="feature-grid" style="margin-top:12px"><div class="feature-card"><small>أوامر تداول آلية</small><strong>متوقفة</strong></div><div class="feature-card"><small>الأسعار</small><strong>حسب المصدر</strong></div><div class="feature-card"><small>الإدارة</small><strong>محمية</strong></div></div></section>';
  }
  function renderAdmin() {
    view.innerHTML=pageHeader("إدارة المنصة","لوحة محمية للمشرف. صلاحيات الإدارة تتحقق من الخادم.","الإدارة")+
      '<section class="panel" id="adminLoginPanel"><h2>تسجيل دخول المشرف</h2><p class="muted">أدخل بيانات ADMIN_USERNAME وADMIN_PASSWORD المضبوطة في إعدادات الخدمة.</p><form id="adminLogin" class="form-grid"><label class="field">اسم المستخدم<input id="adminUser" autocomplete="username" required></label><label class="field">كلمة المرور<input id="adminPass" type="password" autocomplete="current-password" required></label><div><button class="button primary" type="submit">التحقق من الصلاحية</button></div></form><div id="adminMessage" class="muted" style="margin-top:10px"></div></section>'+
      '<section class="panel hidden" id="adminPanel"><div class="panel-head"><h2>حالة المنصة</h2><button class="button small" id="adminLogout">خروج</button></div><div id="adminStatus" class="loading"></div><h2 style="margin:20px 0 10px">نشر مقال</h2><form id="articleForm" class="form-grid"><label class="field">عنوان المقال<input id="articleTitle" required minlength="5"></label><label class="field">التصنيف<input id="articleCategory" value="تعليم التداول"></label><label class="field">ملخص المقال<input id="articleSummary"></label><label class="field">المحتوى<textarea id="articleBody" required minlength="30"></textarea></label><div><button class="button primary" type="submit">نشر المقال</button></div></form><div id="articleMessage" class="muted"></div><h2 style="margin:20px 0 10px">المقالات المنشورة</h2><div id="adminArticleList" class="list muted">تحميل المقالات بعد التحقق…</div></section>'+
      '<section class="panel hidden" id="adminSections"><div class="panel-head"><div><h2>صلاحيات الأقسام</h2><div class="muted">إعدادات الإتاحة محفوظة على الخادم. لا يظهر مختبر الاستراتيجيات للمستخدم العادي.</div></div><button class="button primary" id="saveSections">حفظ الصلاحيات</button></div><div id="sectionSettings" class="list"></div><div id="sectionMessage" class="muted" style="margin-top:10px"></div></section>';
    const msg=$("adminMessage");
    async function loadAdminSections() {
      const out=$("sectionSettings");out.innerHTML='<div class="loading">تحميل صلاحيات الأقسام…</div>';
      try {const d=await getJSON("/api/admin/sections",{headers:{Authorization:adminAuth}});out.innerHTML=(d.catalog||[]).map(item=>'<label class="field" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px;border:1px solid var(--line);border-radius:10px;background:#0d1726"><span>'+esc(item.label)+'</span><select data-section-id="'+esc(item.id)+'" class="frame"><option value="public" '+((d.sections||{})[item.id]==="public"?"selected":"")+'>عام</option><option value="subscription" '+((d.sections||{})[item.id]==="subscription"?"selected":"")+'>للمشتركين</option><option value="closed" '+((d.sections||{})[item.id]==="closed"?"selected":"")+'>مغلق</option></select></label>').join("")}catch(err){out.innerHTML=empty("تعذر تحميل صلاحيات الأقسام",err.message)}
    }
    async function loadAdminArticles() {
      const out=$("adminArticleList");try{const d=await getJSON("/api/admin/articles",{headers:{Authorization:adminAuth}});const items=d.items||[];out.innerHTML=items.length?items.slice(0,15).map(x=>'<div class="feature-card"><strong>'+esc(x.title||"مقال بدون عنوان")+'</strong><small>'+esc(x.category||"تعليم التداول")+' · '+timeText(x.published_at)+'</small></div>').join(""):empty("لا توجد مقالات منشورة")}catch(err){out.innerHTML=empty("تعذر تحميل المقالات",err.message)}
    }
    $("saveSections").addEventListener("click",async()=>{const out=$("sectionMessage");out.textContent="جاري حفظ الصلاحيات…";const sections={};$("sectionSettings").querySelectorAll("[data-section-id]").forEach(el=>sections[el.dataset.sectionId]=el.value);try{await getJSON("/api/admin/sections",{method:"POST",headers:{"Content-Type":"application/json",Authorization:adminAuth},body:JSON.stringify({sections})});out.textContent="تم حفظ صلاحيات الأقسام."}catch(err){out.textContent=err.message}});
    $("adminLogin").addEventListener("submit",async e=>{e.preventDefault();adminAuth="Basic "+btoa(unescape(encodeURIComponent($("adminUser").value+":"+$("adminPass").value)));msg.textContent="التحقق من الصلاحيات…";try{const d=await getJSON("/api/admin/status",{headers:{Authorization:adminAuth}});$("adminLoginPanel").classList.add("hidden");$("adminPanel").classList.remove("hidden");$("adminSections").classList.remove("hidden");$("adminStatus").innerHTML='<div class="feature-grid">'+[["مقالات",d.articles],["نتائج",d.results_count],["تخزين دائم",d.persistent_storage_configured?"مهيأ":"غير مؤكد"]].map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div>';await loadAdminSections();await loadAdminArticles();setStatus("تم التحقق",true)}catch(err){adminAuth="";msg.textContent=err.message;setStatus("الإدارة محمية",false)}});
    $("adminLogout").addEventListener("click",()=>{adminAuth="";$("adminPanel").classList.add("hidden");$("adminSections").classList.add("hidden");$("adminLoginPanel").classList.remove("hidden");$("adminUser").value="";$("adminPass").value=""});
    $("articleForm").addEventListener("submit",async e=>{e.preventDefault();const out=$("articleMessage");out.textContent="جاري النشر…";try{await getJSON("/api/admin/articles",{method:"POST",headers:{"Content-Type":"application/json",Authorization:adminAuth},body:JSON.stringify({title:$("articleTitle").value,category:$("articleCategory").value,summary:$("articleSummary").value,body:$("articleBody").value})});out.textContent="تم نشر المقال.";e.target.reset();await loadAdminArticles()}catch(err){out.textContent=err.message}});
  }
  function renderMarketDirection() {
    const options=Object.entries(markets).map(([key,m])=>'<option value="'+esc(key)+'">'+esc(m.name)+'</option>').join("");
    view.innerHTML=pageHeader("توجهات الأسواق","اعرف هل حركة الأصول تميل للصعود أو الهبوط أو الحياد، مع عدد الأصول الصاعدة والهابطة.","الأسواق")+
      '<section class="panel"><div class="toolbar"><label class="field" style="flex:1;min-width:180px">اختر السوق<select id="directionMarket" class="frame" style="width:100%;margin-top:6px">'+options+'</select></label><button class="button primary" id="refreshDirection">تحديث الاتجاه</button></div><div id="directionContent" style="margin-top:14px">'+empty("اختر السوق","اضغط تحديث الاتجاه لجلب قراءة السوق الحالية.")+'</div></section>'+
      '<div class="notice">الاتجاه قراءة عامة مبنية على تغيّر الأصول واتساع السوق، وليس توصية شراء أو بيع. قد تتأخر البيانات حسب المصدر.</div>';
    const load=async()=>{const out=$("directionContent"),btn=$("refreshDirection"),key=$("directionMarket").value;out.innerHTML='<div class="loading">جاري حساب اتجاه السوق…</div>';btn.disabled=true;try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(markets[key].api));if(!d.ok)throw new Error(d.message||"بيانات الاتجاه غير متاحة");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0),dir=d.direction_ar||"مختلط / محايد",color=d.direction==="BULLISH"?"var(--green)":d.direction==="BEARISH"?"var(--red)":"var(--gold)";out.innerHTML='<div class="feature-grid"><div class="feature-card"><small>اتجاه السوق</small><strong style="color:'+color+'">'+esc(dir)+'</strong></div><div class="feature-card"><small>متوسط التغير</small><strong>'+pct(d.price_change_pct)+'</strong></div><div class="feature-card"><small>أصول صاعدة</small><strong style="color:var(--green)">'+up+'</strong></div><div class="feature-card"><small>أصول هابطة</small><strong style="color:var(--red)">'+down+'</strong></div><div class="feature-card"><small>أصول شبه مستقرة</small><strong>'+flat+'</strong></div><div class="feature-card"><small>الأصول المفحوصة</small><strong>'+esc(d.assets_sampled??(up+down+flat))+'</strong></div></div><p class="muted" style="margin-top:12px">آخر تحديث: '+timeText(d.updated_at)+(d.stale?' · بيانات محفوظة مؤقتًا وليست مباشرة':'')+'</p>';}catch(err){out.innerHTML=empty("تعذر تحديد اتجاه السوق",err.message)}finally{btn.disabled=false}};
    $("refreshDirection").addEventListener("click",load);
    $("directionMarket").addEventListener("change",load);
    load();
  }
  function renderProtectedSection(title, renderer) {
    const unlockKey = "stpProtectedSectionsUnlockedAt";
    const sevenDaysMs = 7 * 24 * 60 * 60 * 1000;
    try {
      const unlockedAt = Number(localStorage.getItem(unlockKey) || 0);
      if (unlockedAt > 0 && Date.now() - unlockedAt < sevenDaysMs) {
        renderer();
        return;
      }
      if (unlockedAt > 0) localStorage.removeItem(unlockKey);
    } catch (_) {}
    view.innerHTML = pageHeader(title, "هذا القسم مقفل برقم سري.","قسم محمي") +
      '<section class="panel" style="max-width:460px;margin:24px auto"><div style="text-align:center;font-size:34px;margin-bottom:8px">🔒</div><h2 style="text-align:center">إدخال الرقم السري</h2><p class="muted" style="text-align:center;margin:8px 0 18px">بعد الفتح يبقى القسم مفتوحًا لمدة 7 أيام، ثم يُقفل تلقائيًا.</p><form id="protectedSectionForm" style="display:grid;gap:12px"><label class="field">الرقم السري<input id="protectedSectionPin" type="password" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" autocomplete="off" required placeholder="••••" style="text-align:center;letter-spacing:.35em;font-size:22px"></label><button class="button primary" type="submit">فتح القسم</button></form><div id="protectedSectionMessage" class="muted" role="alert" style="margin-top:10px;text-align:center"></div></section>';
    $("protectedSectionForm").addEventListener("submit", e => {
      e.preventDefault();
      const pin = $("protectedSectionPin").value;
      if (pin === "2341") {
        try { localStorage.setItem(unlockKey, String(Date.now())); } catch (_) {}
        renderer();
      } else {
        $("protectedSectionMessage").textContent = "الرقم السري غير صحيح.";
        $("protectedSectionPin").value = "";
        $("protectedSectionPin").focus();
      }
    });
  }
  async function render() {
    activateDrawer();
    if(path==="/"){renderHome();return}
    if(marketKey){if(marketKey==="futures"){renderProtectedSection("فيوتشر Binance",()=>renderMarketPage(marketKey));return}renderMarketPage(marketKey);return}
    if(path==="/market-direction"){renderMarketDirection();return}
    if(path==="/results"){await renderResults();return}
    if(path==="/news"){renderProtectedSection("أخبار الأسواق",()=>{renderNews().catch(err=>{view.innerHTML=pageHeader("أخبار الأسواق","تعذر تحميل الأخبار.","الأخبار")+empty("تعذر عرض الأخبار",err.message)})});return}
    if(path==="/analysis"){renderAnalysis();return}
    if(path==="/tasi-analysis"){renderProtectedSection("تحليل تاسي العام",()=>{renderTasi().catch(err=>{view.innerHTML=pageHeader("تحليل تاسي العام","تعذر تحميل التحليل.","السوق السعودي")+empty("تعذر عرض تحليل تاسي",err.message)})});return}
    if(path==="/account"){renderAccount();return}
    if(path==="/admin"){renderAdmin();return}
    // Blog pages are server-rendered and should never be replaced by this shell.
    view.innerHTML=pageHeader("الصفحة غير موجودة","الرابط المطلوب غير معروف. استخدم القائمة للعودة إلى قسم متاح.")+'<a class="button primary" href="/">العودة للرئيسية</a>';
  }
  document.addEventListener("DOMContentLoaded",()=>render().catch(err=>{if(view)view.innerHTML='<section class="panel">'+empty("تعذر عرض الصفحة",err.message)+'</section>';setStatus("خطأ في الواجهة",false)}));
})();
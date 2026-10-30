(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const view = $("pageView");
  // مهلة متوازنة للجوال والمتصفحات البطيئة، دون تعليق الواجهة لمدة طويلة.
  const API_TIMEOUT = 20000;
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
    // توافق مع WebViews والمتصفحات التي لا توفر AbortController.
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = controller ? setTimeout(()=>controller.abort(), API_TIMEOUT) : null;
    try {
      const requestOptions = {...opts, cache:"no-store"};
      if(controller) requestOptions.signal = controller.signal;
      const response = await fetch(url, requestOptions);
      const raw = await response.text();
      let data; try {data=JSON.parse(raw)} catch(_){data={message:raw.slice(0,250)||"استجابة غير مفهومة من الخادم."}}
      if(!response.ok) throw new Error(data.detail || data.message || ("تعذر الطلب ("+response.status+")"));
      return data;
    } catch(err) {
      if(err && err.name==="AbortError") throw new Error("انتهت مهلة الاتصال. جرّب التحديث بعد قليل.");
      throw err;
    } finally {if(timer) clearTimeout(timer)}
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
      '.surge-top{margin-bottom:16px}.surge-market-title{display:inline-block;font-size:clamp(30px,5vw,48px)!important;font-weight:900;padding:12px 22px;border-radius:14px;background:#0b2034;border:1px solid rgba(22,217,154,.22)}.surge-market-sub{color:#91a8c0;font-size:12px;margin-top:7px}'+
      '.surge-hero,.surge-panel{border:1px solid #20415d;background:linear-gradient(110deg,#0b2034,#0b1626);border-radius:16px;padding:16px;margin-bottom:14px}.surge-hero{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.surge-hero h2{margin:0 0 7px}.surge-hero p,.surge-muted{color:#a9bfd5;font-size:12px;line-height:1.8;margin:0}.surge-chip{border:1px solid #244661;border-radius:99px;padding:6px 10px;color:#91a8c0;font-size:11px}'+
      '.surge-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:14px}.surge-stat{background:#0c1d2e;border:1px solid #18334a;border-radius:14px;padding:13px}.surge-stat small{color:#91a8c0;font-size:12px}.surge-stat strong{display:block;font-size:clamp(18px,2.2vw,25px);margin-top:8px}.surge-pos{color:#16d99a}.surge-neg{color:#ff647c}.surge-list{display:grid;gap:9px}.surge-item{border:1px solid rgba(91,155,205,.28);border-radius:14px;padding:13px;background:#0a1726}.surge-item-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.surge-table-wrap{overflow:auto}.surge-table{border-collapse:collapse;width:100%;min-width:430px}.surge-table th,.surge-table td{text-align:right;padding:10px 8px;border-bottom:1px solid #142b3e;font-size:12px}.surge-table th{color:#91a8c0}.surge-empty{padding:20px;text-align:center;color:#91a8c0;font-size:12px}.surge-link{color:#6effcb;text-decoration:underline;font-weight:800}'+
      '@media(max-width:650px){.surge-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}'+
      '</style>'+
      '<div class="surge-page">'+
      '<div class="surge-top"><span class="eyebrow">SMART TRADING PRO</span><h1 class="page-title surge-market-title" style="margin:8px 0 0">'+esc(m.name)+'</h1><div class="surge-market-sub">'+(['spot','futures','alpha'].includes(m.api)?'فرص مختارة':'فرص مختارة')+'</div><p class="muted">'+esc(m.sub)+'</p></div>'+
      ''+
      ''+
      '<section class="surge-panel"><div class="surge-item-head"><h2 style="margin:0">📡 توصيات من فرص التداول</h2><span class="surge-chip" id="signalSourceLabel">محدثة</span></div><div id="surgeRecommendations" class="surge-empty">تظهر هنا الصفقات المكتملة بعد التحقق من الأسعار والمستويات وحالة الصفقة.</div><p class="surge-muted" style="margin-top:10px">الصفقات مرتبة حسب العائد المحتمل مقارنة بالمخاطرة، وعند التعادل تظهر الأحدث أولاً.</p></section>'+
      ''+
      '</div>';
    const loadDailyVip=async()=>{
      const out=$("surgeRecommendations"),label=$("signalSourceLabel");
      if(!out)return;
      if(!["spot","futures","alpha"].includes(m.api)){
        out.innerHTML='<div class="surge-empty">لا توجد صفقات موثقة متاحة لهذا السوق حاليًا.</div>';
        if(label)label.textContent="غير مدعوم";
        return;
      }
      out.innerHTML='<div class="surge-empty">جاري جلب التوصيات المنشورة…</div>';
      if(label)label.textContent="محدثة";
      try{
        const data=await getJSON("/api/trade-feed?market="+encodeURIComponent(m.api)+"&limit=20");
        const rows=(Array.isArray(data.items)?data.items:[]).slice().sort((a,b)=>{
          const score=(x)=>{const v=x.levels||{},entry=Number(v.entry),stop=Number(v.stop_loss),target=Number(v.tp3),long=x.original_direction==="LONG";const risk=Math.abs(entry-stop),reward=Math.abs(target-entry);return entry>0&&risk>0&&target>0?reward/risk:-1};
          const delta=score(b)-score(a);
          return Math.abs(delta)>1e-9?delta:Number(b.published_at||0)-Number(a.published_at||0);
        });
        if(!rows.length){out.innerHTML='<div class="surge-empty">'+esc(data.message||"لا توجد توصيات نشطة مكتملة الآن.")+'</div>';return}
        const targetKeys=["tp1","tp2","tp3","tp4","tp5"];
        out.innerHTML='<div class="surge-signal-grid">'+rows.map((x,i)=>{
          const lv=x.levels||{},buy=x.original_direction==="LONG";
          const entry=Number(lv.entry),stop=Number(lv.stop_loss);
          const move=(v)=>{const n=Number(v);return Number.isFinite(n)&&entry>0?((buy?n-entry:entry-n)/entry*100).toFixed(2)+"%":"—"};
          const entryText=price(lv.entry_min)+" – "+price(lv.entry_max);
          const targets=targetKeys.map((key,index)=>'<div class="surge-target"><small>TP'+(index+1)+'</small><b dir="ltr">'+price(lv[key])+'</b><small>'+move(lv[key])+'</small></div>').join("");
          const risk=Number.isFinite(stop)&&entry>0?((buy?entry-stop:stop-entry)/entry*100).toFixed(2)+"%":"—";
          return '<article class="surge-signal-card"><div class="surge-signal-head"><b dir="ltr">'+esc(x.symbol)+'</b><span class="surge-rank">#'+(i+1)+'</span><span class="surge-rec-side '+(buy?"buy":"sell")+'">'+(buy?"شراء LONG":"بيع SHORT")+'</span></div><div class="surge-entry"><small>منطقة الدخول</small><b dir="ltr">'+entryText+'</b></div><div class="surge-level-grid">'+targets+'<div class="surge-target stop"><small>وقف الخسارة</small><b dir="ltr">'+price(stop)+'</b><small>مخاطرة '+risk+'</small></div></div><div class="surge-signal-foot"><span>'+esc(x.status||"نشطة")+' · '+esc(x.age_hours)+" ساعة"+'</span></div></article>';
        }).join("")+'</div>';
      }catch(err){out.innerHTML='<div class="surge-empty">تعذر تحديث الصفقات حالياً. حاول لاحقاً.</div>'}
    };
    if(marketSignalRefreshTimer)clearInterval(marketSignalRefreshTimer);
    if(marketLiveTrackTimer)clearInterval(marketLiveTrackTimer);
    loadDailyVip();
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
    badge.textContent=symbol;out.innerHTML='<div class="loading">جاري تحميل الشموع الفعلية…</div>';meta.textContent=m.name;
    try {const d=await getJSON("/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(symbol)+"&interval=1d");out.innerHTML=drawCandles(d.items||[]);meta.textContent=m.source+" · "+(d.items||[]).length+" شمعة"}
    catch(err){out.innerHTML=empty("الشارت غير متاح",err.message);meta.textContent="لا توجد بيانات شموع مؤكدة"}
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
        out.innerHTML=items.length?'<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>السوق</th><th>الاتجاه</th><th>الدخول</th><th>وقف الخسارة</th><th>النتيجة</th><th>الأداء</th></tr></thead><tbody>'+items.map(x=>{
          const status=String(x.result||"OPEN").toUpperCase();
          const statusLabel=({OPEN:"مفتوحة",TP1:"هدف 1",TP2:"هدف 2",TP3:"هدف 3",SL:"وقف خسارة"})[status]||status;
          const closed=["TP1","TP2","TP3","SL"].includes(status);
          const side=x.side==="BUY"||x.side==="شراء"?"شراء":x.side==="SELL"||x.side==="بيع"?"بيع":x.side||"—";
          const pnl=x.pnl_pct==null?"—":pct(x.pnl_pct);
          return '<tr><td dir="ltr"><strong>'+esc(x.symbol||"—")+'</strong></td><td>'+esc(x.market||"—")+'</td><td>'+esc(side)+'</td><td class="ltr">'+price(x.entry)+'</td><td class="ltr">'+price(x.stop_loss)+'</td><td><span class="result-status '+(closed?"is-closed":"is-open")+'">'+esc(statusLabel)+'</span></td><td class="'+(Number(x.pnl_pct)>0?"positive":Number(x.pnl_pct)<0?"negative":"muted")+'">'+esc(pnl)+'</td></tr>';
        }).join("")+'</tbody></table></div>':empty("السجل جاهز وينتظر أول فرصة","ستظهر هنا التوصيات المرتبطة بمصدرها عند توفرها، ولن تُحتسب نتيجة مالية قبل تأكيدها.");
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
  function renderCandleChart(items,label) {
    return '<div id="tasiChart">'+drawCandles(items)+'</div><div class="muted" style="margin-top:8px">'+esc(label||"شموع المؤشر الفعلية")+'</div>';
  }
  async function renderTasi() {
    view.innerHTML=pageHeader("تحليل تاسي العام","قراءة يومية ثابتة للمؤشر العام.","السوق السعودي")+
      '<section class="panel"><div class="panel-head"><h2>قراءة المؤشر</h2><button class="button small" id="tasiRefresh">تحديث التحليل</button></div><div id="tasiContent" class="loading">جاري طلب التحليل…</div></section>';
    const load=async()=>{
      const out=$("tasiContent");out.innerHTML='<div class="loading">تحميل بيانات المؤشر…</div>';
      try {
        const d=await getJSON("/api/tasi/analysis?interval=1d");
        const stats=[["آخر سعر",price(d.price)],["التغير",pct(d.change_pct)],["الاتجاه",d.trend||"—"],["الدعم",price(d.support)],["المقاومة",price(d.resistance)],["السيناريو",d.scenario||"—"]];
        out.innerHTML='<div class="feature-grid">'+stats.map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div><div class="panel" style="margin:14px 0"><div class="panel-head"><h3>الرسم السعري</h3><span class="muted">قراءة يومية ثابتة</span></div>'+renderCandleChart(d.candles||[],"شموع يومية فعلية")+'</div><div class="feature-grid">'+[["الدخول المشروط",price(d.entry)],["وقف الخسارة",price(d.stop_loss)],["الهدف الأول",price(d.tp1)],["الهدف الثاني",price(d.tp2)],["الهدف الثالث",price(d.tp3)]].map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div><p class="muted">'+esc(d.message||"")+'</p>';
      } catch(err){out.innerHTML=empty("تعذر جلب تحليل تاسي",err.message)}
    };
    $("tasiRefresh").addEventListener("click",load);
    await load();
  }
  async function renderAccount() {
    view.innerHTML=pageHeader("الحساب والاشتراك","افتح جميع الأسواق عبر اشتراك أو تجربة مشاركة لمدة 24 ساعة.","الحساب")+
      '<section class="panel"><div class="toolbar"><button class="button primary" id="accountLoginTab">تسجيل الدخول</button><button class="button" id="accountRegisterTab">إنشاء حساب</button></div><div id="accountAuthArea" style="margin-top:16px"></div><div id="accountAuthMessage" class="muted" role="status" style="margin-top:12px"></div></section>';
    const area=$("accountAuthArea"), msg=$("accountAuthMessage");
    function showAuth(mode) {
      $("accountLoginTab").classList.toggle("primary",mode==="login");
      $("accountRegisterTab").classList.toggle("primary",mode==="register");
      area.innerHTML=mode==="register"
        ? '<form id="customerAuthForm" class="form-grid"><label class="field">الاسم<input name="name" autocomplete="name" minlength="2" maxlength="80" required></label><label class="field">البريد الإلكتروني<input name="email" type="email" autocomplete="email" required maxlength="254"></label><label class="field">كلمة المرور<input name="password" type="password" autocomplete="new-password" minlength="10" maxlength="128" required><small class="muted">10 أحرف على الأقل وتشمل حرفًا ورقمًا.</small></label><div><button class="button primary" type="submit">إنشاء الحساب</button></div></form>'
        : '<form id="customerAuthForm" class="form-grid"><label class="field">البريد الإلكتروني<input name="email" type="email" autocomplete="email" required></label><label class="field">كلمة المرور<input name="password" type="password" autocomplete="current-password" required></label><div><button class="button primary" type="submit">دخول</button></div></form>';
      const guestCard=document.createElement("div");
      guestCard.className="feature-card";
      guestCard.style.marginBottom="16px";
      guestCard.innerHTML='<strong>🎁 شارك موقع التداول الذكي PRO على مواقع التواصل الاجتماعي واحصل على يوم مجاني (24 ساعة) — بدون تسجيل حساب.</strong><p class="muted">اضغط مشاركة، واختر منصة التواصل الاجتماعي المناسبة. بعد إكمال المشاركة سنفعّل التجربة على هذا المتصفح.</p><button class="button primary" type="button" id="guestShareUnlock">📢 شارك الموقع واحصل على يوم مجاني</button>';
      area.prepend(guestCard);
      $("guestShareUnlock").addEventListener("click",async()=>{
        const btn=$("guestShareUnlock");btn.disabled=true;msg.textContent="افتح قائمة المشاركة واختر تطبيق تواصل اجتماعي.";
        try{
          if(navigator.share){
            await navigator.share({title:"التداول الذكي PRO",text:"أشارككم موقع التداول الذكي PRO لمتابعة الأسواق: ",url:location.origin});
          }else{
            try{await navigator.clipboard.writeText("التداول الذكي PRO — تابع الأسواق: "+location.origin);}
            catch(_){msg.textContent="انسخ الرابط وشاركه على مواقع التواصل: "+location.origin;return;}
            msg.textContent="نُسخ رابط الموقع. جاري تفعيل التجربة…";
          }
          msg.textContent="تمت المشاركة. انتظر 30 ثانية لتفعيل 24 ساعة مجانية إضافية…";
          await new Promise(resolve=>setTimeout(resolve,30000));
          const d=await getJSON("/api/billing/guest-share",{method:"POST"});
          msg.textContent="✅ تم تفعيل 24 ساعة مجانية حتى "+fmtDate(d.share_expires_at)+". تقدر تكرر المشاركة لتجديد المدة.";
        }catch(err){
          if(err.name==="AbortError"){msg.textContent="تم إلغاء المشاركة، ولم يُفعّل اليوم المجاني. اضغط الزر وأكمل المشاركة.";}
          else{msg.textContent=(err.message||"تعذر تفعيل التجربة.")+" إذا استمرت المشكلة، أرسل هذه الرسالة للدعم.";}
        }finally{btn.disabled=false;}
      });
      area.querySelector("form").addEventListener("submit",async e=>{
        e.preventDefault();const form=e.currentTarget,button=form.querySelector("button[type=submit]"),data=Object.fromEntries(new FormData(form).entries());button.disabled=true;msg.textContent="جاري التحقق…";
        try{const d=await getJSON(mode==="register"?"/api/auth/register":"/api/auth/login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});msg.textContent="تم "+(mode==="register"?"إنشاء الحساب":"تسجيل الدخول")+" بنجاح.";await showBilling(d.user);}
        catch(err){msg.textContent=err.message||"تعذر إكمال الطلب."}finally{if(button.isConnected)button.disabled=false;}
      });
    }
    function fmtDate(ts){return ts?new Date(ts*1000).toLocaleString("ar-SA",{dateStyle:"medium",timeStyle:"short"}):"غير مفعّل";}
    async function showBilling(user) {
      $("accountLoginTab").classList.remove("primary");$("accountRegisterTab").classList.remove("primary");
      area.innerHTML='<div id="billingProfile" class="feature-grid"></div><div id="billingState" class="notice" style="margin-top:12px">جاري فحص الاشتراك…</div><h2 style="margin:22px 0 10px">اختر الاشتراك</h2><div id="billingPlans" class="feature-grid"></div><div id="billingPayment" style="margin-top:14px"></div><h2 style="margin:22px 0 10px">تجربة المشاركة المجانية</h2><p class="muted">كل مرة تشارك فيها الرابط تمنحك 24 ساعة مجانية إضافية. بعد المشاركة انتظر 30 ثانية للتفعيل. لا يمكن للموقع التأكد من نشر منشور عام على كل منصة.</p><button class="button" id="shareUnlock">مشاركة الموقع وتجديد 24 ساعة مجانية</button><h2 style="margin:22px 0 10px">تحويل من Binance</h2><div class="feature-card"><strong>Binance Pay UID: 28191866</strong><p class="muted">التحقق الآلي من تحويل UID يحتاج ربط Binance Pay Merchant API ومفاتيح التاجر. حاليًا التفعيل الآلي متاح لتحويل USDT عبر شبكة TRC20 إلى عنوان المحفظة أدناه.</p></div><button class="button" id="customerLogout" style="margin-top:18px">تسجيل الخروج</button>';
      $("billingProfile").innerHTML='<div class="feature-card"><small>الاسم</small><strong>'+esc(user.name)+'</strong></div><div class="feature-card"><small>البريد الإلكتروني</small><strong>'+esc(user.email)+'</strong></div>';
      const plansOut=$("billingPlans"),payOut=$("billingPayment"),state=$("billingState");
      let plansData=null;
      async function refreshBilling(silent=false) {
        try{
          const d=await getJSON("/api/billing/status");
          state.textContent=d.subscription_expires_at>Math.floor(Date.now()/1000)?"اشتراكك فعّال حتى "+fmtDate(d.subscription_expires_at):(d.share_expires_at>Math.floor(Date.now()/1000)?"الأسواق مفتوحة مجانًا حتى "+fmtDate(d.share_expires_at):"لا يوجد اشتراك فعّال حاليًا.");
          if(d.pending){
            payOut.innerHTML='<div class="feature-card"><strong>بانتظار الدفع · '+esc(d.pending.amount_usd.toFixed(2))+' USDT</strong><p class="muted">حوّل المبلغ الظاهر بالضبط إلى عنوان TRC20 أدناه. يجري فحص التحويلات المؤكدة تلقائيًا.</p><p><strong>انتهاء الطلب:</strong> '+esc(fmtDate(d.pending.expires_at))+'</p><button class="button" id="copyWalletAgain">نسخ عنوان المحفظة</button></div>';
            $("copyWalletAgain").addEventListener("click",async()=>{try{await navigator.clipboard.writeText(plansData.wallet);msg.textContent="تم نسخ عنوان المحفظة."}catch(_){msg.textContent=plansData.wallet}});
          }
          if(d.has_access) document.querySelectorAll("[data-membership-lock]").forEach(x=>x.classList.remove("hidden"));
          if(!silent && d.paid_plan) msg.textContent="تم تأكيد الدفع وتفعيل "+d.paid_plan+" تلقائيًا.";
          if(d.pending && !silent) msg.textContent="نراقب التحويلات المؤكدة تلقائيًا. أبقِ الصفحة مفتوحة حتى يظهر التفعيل.";
        }catch(err){if(!silent)state.textContent="تعذر فحص حالة الدفع الآن: "+(err.message||"حاول لاحقًا");}
      }
      try {
        plansData=await getJSON("/api/billing/plans");
        plansOut.innerHTML=plansData.plans.map(p=>'<div class="feature-card"><small>'+esc(p.label)+'</small><strong>'+p.base_usd+' USDT</strong><p class="muted">'+p.days+' يومًا</p><button class="button primary" data-plan="'+esc(p.id)+'">اختيار الخطة</button></div>').join("");
        plansOut.querySelectorAll("[data-plan]").forEach(btn=>btn.addEventListener("click",async()=>{
          btn.disabled=true;msg.textContent="جاري تجهيز طلب الدفع…";
          try{
            const intent=await getJSON("/api/billing/create",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({plan_id:btn.dataset.plan})});
            payOut.innerHTML='<div class="feature-card"><small>المبلغ المطلوب بالضبط</small><strong>'+intent.amount_usd.toFixed(2)+' USDT</strong><p class="muted">شبكة TRON (TRC20) فقط. يجب أن يصل المبلغ الظاهر نفسه إلى المحفظة خلال ساعتين؛ لا تستخدم شبكة أخرى.</p><p style="overflow-wrap:anywhere"><strong>المحفظة:</strong><br>'+esc(intent.wallet)+'</p><button class="button primary" id="copyPayDetails">نسخ عنوان المحفظة</button><p class="muted">بعد وصول التحويل وتأكيده على الشبكة، يفعّل الموقع الاشتراك تلقائيًا. قد يستغرق ظهور التحويل بعض الوقت.</p></div>';
            $("copyPayDetails").addEventListener("click",async()=>{try{await navigator.clipboard.writeText(intent.wallet);msg.textContent="تم نسخ العنوان. حوّل المبلغ المحدد بالضبط."}catch(_){msg.textContent="انسخ العنوان يدويًا: "+intent.wallet}});
            msg.textContent="تم إنشاء طلب الدفع. المبلغ الدقيق "+intent.amount_usd.toFixed(2)+" USDT.";
            await refreshBilling(true);
          }catch(err){msg.textContent=err.message||"تعذر إنشاء طلب الدفع."}finally{btn.disabled=false;}
        }));
      }catch(err){plansOut.textContent="تعذر تحميل خطط الاشتراك: "+err.message}
      $("shareUnlock").addEventListener("click",async()=>{
        const shareData={title:"التداول الذكي PRO",text:"تابع الأسواق عبر التداول الذكي PRO",url:location.origin};
        try{
          if(navigator.share) await navigator.share(shareData);
          else {await navigator.clipboard.writeText(location.origin);msg.textContent="تم نسخ رابط الموقع. سيتم تفعيل العرض لهذا الحساب.";}
          msg.textContent="تمت المشاركة. انتظر 30 ثانية لتجديد 24 ساعة مجانية…";
          await new Promise(resolve=>setTimeout(resolve,30000));
          const d=await getJSON("/api/billing/share",{method:"POST"});
          msg.textContent="تم تجديد الوصول المجاني لمدة 24 ساعة حتى "+fmtDate(d.share_expires_at)+".";
          await refreshBilling(true);
        }catch(err){if(err.name!=="AbortError")msg.textContent=err.message||"لم يتم تفعيل العرض. جرّب مرة أخرى."}
      });
      $("customerLogout").addEventListener("click",async()=>{try{await getJSON("/api/auth/logout",{method:"POST"});msg.textContent="تم تسجيل الخروج.";showAuth("login");}catch(err){msg.textContent=err.message}});
      await refreshBilling();
      if(window.__billingPollTimer) clearInterval(window.__billingPollTimer);
      window.__billingPollTimer=setInterval(()=>refreshBilling(true),15000);
    }
    $("accountLoginTab").addEventListener("click",()=>{msg.textContent="";showAuth("login");});
    $("accountRegisterTab").addEventListener("click",()=>{msg.textContent="";showAuth("register");});
    try{const d=await getJSON("/api/auth/me");await showBilling(d.user);msg.textContent="أنت مسجّل الدخول.";}catch(_){showAuth("login");}
  }
  function renderAdmin() {
    view.innerHTML=pageHeader("إدارة المنصة","لوحة محمية للمشرف. صلاحيات الإدارة تتحقق من الخادم.","الإدارة")+
      '<section class="panel" id="adminLoginPanel"><h2>تسجيل دخول المشرف</h2><p class="muted">أدخل بيانات ADMIN_USERNAME وADMIN_PASSWORD المضبوطة في إعدادات الخدمة.</p><form id="adminLogin" class="form-grid"><label class="field">اسم المستخدم<input id="adminUser" autocomplete="username" required></label><label class="field">كلمة المرور<input id="adminPass" type="password" autocomplete="current-password" required></label><div><button class="button primary" type="submit">التحقق من الصلاحية</button></div></form><div id="adminMessage" class="muted" style="margin-top:10px"></div></section>'+
      '<section class="panel hidden" id="adminPanel"><div class="panel-head"><h2>حالة المنصة</h2><button class="button small" id="adminLogout">خروج</button></div><div id="adminStatus" class="loading"></div><section class="panel" style="margin-top:16px"><h2>🎟️ منح اشتراك يدوي</h2><p class="muted">اكتب بريد الحساب المسجل وحدد المدة بالأيام؛ مثل 30 يومًا لشهر أو 60 يومًا لشهرين.</p><form id="grantSubscriptionForm" class="form-grid"><label class="field">بريد حساب العميل<input id="grantSubscriptionEmail" type="email" required placeholder="name@example.com"></label><label class="field">مدة الاشتراك بالأيام<input id="grantSubscriptionDays" type="number" min="1" max="3650" value="30" required></label><div><button class="button primary" type="submit">تفعيل الاشتراك</button></div></form><div id="grantSubscriptionMessage" class="muted" style="margin-top:10px"></div></section><section class="panel" style="margin-top:16px"><div class="panel-head"><h2>💬 محادثات الدعم الفني</h2><button class="button small" id="supportInboxRefresh">تحديث</button></div><div id="supportInbox" class="list">تحميل المحادثات…</div><div id="supportChat" class="hidden"></div></section><h2 style="margin:20px 0 10px">نشر مقال</h2><form id="articleForm" class="form-grid"><label class="field">عنوان المقال<input id="articleTitle" required minlength="5"></label><label class="field">التصنيف<input id="articleCategory" value="تعليم التداول"></label><label class="field">ملخص المقال<input id="articleSummary"></label><label class="field">المحتوى<textarea id="articleBody" required minlength="30"></textarea></label><div><button class="button primary" type="submit">نشر المقال</button></div></form><div id="articleMessage" class="muted"></div><h2 style="margin:20px 0 10px">المقالات المنشورة</h2><div id="adminArticleList" class="list muted">تحميل المقالات بعد التحقق…</div></section>'+
      '<section class="panel hidden" id="adminSections"><div class="panel-head"><div><h2>صلاحيات الأقسام</h2><div class="muted">إعدادات الإتاحة محفوظة على الخادم. لا يظهر مختبر الاستراتيجيات للمستخدم العادي.</div></div><button class="button primary" id="saveSections">حفظ الصلاحيات</button></div><div id="sectionSettings" class="list"></div><div id="sectionMessage" class="muted" style="margin-top:10px"></div></section>';
    const msg=$("adminMessage");
    async function loadAdminSections() {
      const out=$("sectionSettings");out.innerHTML='<div class="loading">تحميل صلاحيات الأقسام…</div>';
      try {const d=await getJSON("/api/admin/sections",{headers:{Authorization:adminAuth}});out.innerHTML=(d.catalog||[]).map(item=>'<label class="field" style="display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px;border:1px solid var(--line);border-radius:10px;background:#0d1726"><span>'+esc(item.label)+'</span><select data-section-id="'+esc(item.id)+'" class="frame"><option value="public" '+((d.sections||{})[item.id]==="public"?"selected":"")+'>عام</option><option value="subscription" '+((d.sections||{})[item.id]==="subscription"?"selected":"")+'>للمشتركين</option><option value="closed" '+((d.sections||{})[item.id]==="closed"?"selected":"")+'>مغلق</option></select></label>').join("")}catch(err){out.innerHTML=empty("تعذر تحميل صلاحيات الأقسام",err.message)}
    }
    async function loadSupportInbox() {
      const out=$("supportInbox");if(!out||!adminAuth)return;
      try {
        const d=await getJSON("/api/admin/support/conversations",{headers:{Authorization:adminAuth}});
        const items=d.items||[];
        out.innerHTML=items.length?items.map(x=>'<button type="button" class="feature-card" data-support-conv="'+x.id+'" style="width:100%;text-align:right;cursor:pointer"><strong>'+esc(x.display_name||"عميل")+' · '+esc(x.email||"")+'</strong><small>'+esc(x.last_message||"لا توجد رسائل")+'</small><small>'+timeText(x.updated_at)+' · '+(x.last_sender==="customer"?"رسالة من العميل":"آخر رد من الدعم")+'</small></button>').join(""):'<p class="muted">لا توجد محادثات حتى الآن.</p>';
        out.querySelectorAll("[data-support-conv]").forEach(el=>el.addEventListener("click",()=>openSupportConversation(Number(el.dataset.supportConv))));
      } catch(err){out.innerHTML='<p class="muted">'+esc(err.message)+'</p>'}
    }
    async function openSupportConversation(id) {
      const out=$("supportChat");out.classList.remove("hidden");out.innerHTML='<div class="loading">تحميل المحادثة…</div>';
      async function refresh(){const d=await getJSON("/api/admin/support/conversations/"+id,{headers:{Authorization:adminAuth}});out.innerHTML='<h3>'+esc(d.conversation.display_name)+' · '+esc(d.conversation.email)+'</h3><div id="supportAdminMessages" style="max-height:300px;overflow:auto;display:grid;gap:8px;margin:12px 0">'+(d.items||[]).map(m=>'<div class="feature-card"><small>'+ (m.sender==="admin"?"الدعم الفني":"العميل") +' · '+timeText(m.created_at)+'</small><p style="white-space:pre-wrap">'+esc(m.body)+'</p></div>').join("")+'</div><form id="supportAdminReply" class="form-grid"><label class="field">ردّك للعميل<textarea id="supportAdminReplyBody" required maxlength="2000"></textarea></label><button class="button primary" type="submit">إرسال الرد</button><span id="supportAdminReplyMsg" class="muted"></span></form>';const form=$("supportAdminReply");form.addEventListener("submit",async e=>{e.preventDefault();const body=$("supportAdminReplyBody").value.trim();if(!body)return;const msg=$("supportAdminReplyMsg");msg.textContent="جارٍ الإرسال…";try{await getJSON("/api/admin/support/conversations/"+id,{method:"POST",headers:{"Content-Type":"application/json",Authorization:adminAuth},body:JSON.stringify({body})});await refresh();await loadSupportInbox()}catch(err){msg.textContent=err.message}})}
      try{await refresh()}catch(err){out.innerHTML='<p class="muted">'+esc(err.message)+'</p>'}
    }
    async function loadAdminArticles() {
      const out=$("adminArticleList");try{const d=await getJSON("/api/admin/articles",{headers:{Authorization:adminAuth}});const items=d.items||[];out.innerHTML=items.length?items.slice(0,15).map(x=>'<div class="feature-card"><strong>'+esc(x.title||"مقال بدون عنوان")+'</strong><small>'+esc(x.category||"تعليم التداول")+' · '+timeText(x.published_at)+'</small></div>').join(""):empty("لا توجد مقالات منشورة")}catch(err){out.innerHTML=empty("تعذر تحميل المقالات",err.message)}
    }
    $("saveSections").addEventListener("click",async()=>{const out=$("sectionMessage");out.textContent="جاري حفظ الصلاحيات…";const sections={};$("sectionSettings").querySelectorAll("[data-section-id]").forEach(el=>sections[el.dataset.sectionId]=el.value);try{await getJSON("/api/admin/sections",{method:"POST",headers:{"Content-Type":"application/json",Authorization:adminAuth},body:JSON.stringify({sections})});out.textContent="تم حفظ صلاحيات الأقسام."}catch(err){out.textContent=err.message}});
    $("adminLogin").addEventListener("submit",async e=>{e.preventDefault();adminAuth="Basic "+btoa(unescape(encodeURIComponent($("adminUser").value+":"+$("adminPass").value)));msg.textContent="التحقق من الصلاحيات…";try{const d=await getJSON("/api/admin/status",{headers:{Authorization:adminAuth}});await getJSON("/api/admin/site-access",{method:"POST",headers:{Authorization:adminAuth}});$("adminLoginPanel").classList.add("hidden");$("adminPanel").classList.remove("hidden");$("adminSections").classList.remove("hidden");$("adminStatus").innerHTML='<div class="feature-grid">'+[["مقالات",d.articles],["نتائج",d.results_count],["تخزين دائم",d.persistent_storage_configured?"مهيأ":"غير مؤكد"]].map(x=>'<div class="feature-card"><small>'+esc(x[0])+'</small><strong>'+esc(x[1])+'</strong></div>').join("")+'</div>';await loadAdminSections();await loadAdminArticles();await loadSupportInbox();if(window.__supportAdminTimer)clearInterval(window.__supportAdminTimer);window.__supportAdminTimer=setInterval(()=>{if(adminAuth)loadSupportInbox()},5000);setStatus("تم التحقق",true)}catch(err){adminAuth="";msg.textContent=err.message;setStatus("الإدارة محمية",false)}});
    $("adminLogout").addEventListener("click",()=>{adminAuth="";$("adminPanel").classList.add("hidden");$("adminSections").classList.add("hidden");$("adminLoginPanel").classList.remove("hidden");$("adminUser").value="";$("adminPass").value=""});
    $("grantSubscriptionForm").addEventListener("submit",async e=>{e.preventDefault();const out=$("grantSubscriptionMessage");out.textContent="جاري تفعيل الاشتراك…";try{const d=await getJSON("/api/admin/grant-subscription",{method:"POST",headers:{"Content-Type":"application/json",Authorization:adminAuth},body:JSON.stringify({email:$("grantSubscriptionEmail").value.trim(),days:Number($("grantSubscriptionDays").value)})});out.textContent="تم تفعيل "+d.days_added+" يومًا للحساب "+d.email+" بنجاح.";e.target.reset();$("grantSubscriptionDays").value="30";}catch(err){out.textContent=err.message||"تعذر تفعيل الاشتراك.";}});
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
  async function render() {
    activateDrawer();
    if(path==="/"){renderHome();return}
    if(marketKey){renderMarketPage(marketKey);return}
    if(path==="/market-direction"){renderMarketDirection();return}
    if(path==="/news"){renderNews().catch(err=>{view.innerHTML=pageHeader("أخبار الأسواق","تعذر تحميل الأخبار.","الأخبار")+empty("تعذر عرض الأخبار",err.message)});return}
    if(path==="/account"){renderAccount();return}
    if(path==="/admin"){renderAdmin();return}
    // Blog pages are server-rendered and should never be replaced by this shell.
    view.innerHTML=pageHeader("الصفحة غير موجودة","الرابط المطلوب غير معروف. استخدم القائمة للعودة إلى قسم متاح.")+'<a class="button primary" href="/">العودة للرئيسية</a>';
  }
  function setupSupportWidget() {
    if(document.getElementById("floatingSupport"))return;
    const style=document.createElement("style");
    style.textContent="#floatingSupport{position:fixed;bottom:18px;left:16px;z-index:9999;font-family:inherit}#floatingSupportBtn{border:0;border-radius:999px;padding:13px 17px;background:#16a085;color:#fff;font-weight:800;box-shadow:0 8px 28px #0006;cursor:pointer}#floatingSupportPanel{display:none;width:min(350px,calc(100vw - 28px));height:min(490px,70vh);margin-bottom:10px;background:#0d1726;color:#f5f7fb;border:1px solid #314158;border-radius:16px;box-shadow:0 12px 40px #0008;overflow:hidden}#floatingSupportPanel.open{display:flex;flex-direction:column}#floatingSupportHead{padding:13px;background:#142338;font-weight:800;display:flex;justify-content:space-between}#floatingSupportMessages{flex:1;overflow:auto;padding:10px;display:flex;flex-direction:column;gap:8px}#floatingSupportMessages .feature-card{padding:9px;border-radius:10px;background:#17263a;overflow-wrap:anywhere}#floatingSupportForm{display:flex;gap:6px;padding:10px;border-top:1px solid #314158}#floatingSupportInput{min-width:0;flex:1;background:#101d2e;color:#fff;border:1px solid #40516a;border-radius:9px;padding:9px}#floatingSupportForm button{border:0;border-radius:9px;padding:8px 12px;background:#16a085;color:white;font-weight:700}";
    document.head.appendChild(style);
    const root=document.createElement("div");root.id="floatingSupport";
    root.innerHTML='<section id="floatingSupportPanel"><header id="floatingSupportHead"><span>💬 الدعم الفني</span><button id="floatingSupportClose" type="button" style="background:none;border:0;color:white;font-size:20px">×</button></header><div id="floatingSupportMessages"><p class="muted">جاري تحميل المحادثة…</p></div><form id="floatingSupportForm"><input id="floatingSupportInput" maxlength="2000" placeholder="اكتب رسالتك…" required><button type="submit">إرسال</button></form></section><button id="floatingSupportBtn" type="button">💬 الدعم الفني</button>';
    document.body.appendChild(root);
    const panel=$("floatingSupportPanel"),msgs=$("floatingSupportMessages"),form=$("floatingSupportForm"),input=$("floatingSupportInput");
    $("floatingSupportBtn").addEventListener("click",()=>{panel.classList.toggle("open");if(panel.classList.contains("open"))refreshSupport()});
    $("floatingSupportClose").addEventListener("click",()=>panel.classList.remove("open"));
    let busy=false;
    async function refreshSupport(){if(busy)return;busy=true;try{const d=await getJSON("/api/support/messages");msgs.innerHTML=(d.items||[]).map(m=>'<div class="feature-card"><small>'+(m.sender==="admin"?"الدعم الفني":"أنت")+' · '+timeText(m.created_at)+'</small><p style="white-space:pre-wrap;margin:6px 0 0">'+esc(m.body)+'</p></div>').join("")||'<p class="muted">أهلًا بك! اكتب سؤالك وسيظهر هنا رد الدعم الفني.</p>';msgs.scrollTop=msgs.scrollHeight}catch(err){msgs.innerHTML='<p class="muted">'+esc(err.message||"سجّل الدخول أولًا لاستخدام الدعم الفني.")+'</p>'}finally{busy=false}}
    form.addEventListener("submit",async e=>{e.preventDefault();const body=input.value.trim();if(!body)return;const btn=form.querySelector("button");btn.disabled=true;try{await getJSON("/api/support/messages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({body})});input.value="";await refreshSupport()}catch(err){msgs.innerHTML='<p class="muted">'+esc(err.message)+'</p>'}finally{btn.disabled=false}});
    setInterval(()=>{if(panel.classList.contains("open"))refreshSupport()},4000);
    $("supportInboxRefresh")?.addEventListener("click",loadSupportInbox);
  }
  document.addEventListener("DOMContentLoaded",()=>{setupSupportWidget();render().catch(err=>{if(view)view.innerHTML='<section class="panel">'+empty("تعذر عرض الصفحة",err.message)+'</section>';setStatus("خطأ في الواجهة",false)});});
})();
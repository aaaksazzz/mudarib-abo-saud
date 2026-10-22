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
      '<div class="market-workspace">'+
        '<section class="market-hero"><div class="market-hero-copy"><span class="eyebrow">MARKET OVERVIEW · '+esc(m.source.toUpperCase())+'</span><h1>'+esc(m.name)+'</h1><p>'+esc(m.sub)+' — لوحة متابعة مستقلة لهذا السوق، مع فصل البيانات عن بقية الأسواق.</p><div class="market-hero-tags"><span class="market-live-dot">● متابعة السوق</span><span class="market-source-chip">المصدر: '+esc(m.source)+'</span></div></div><div class="market-hero-mark" aria-hidden="true">'+esc(m.icon)+'</div></section>'+
        '<section class="market-section market-overview-section"><div class="market-section-heading"><div><span class="section-kicker">01 / OVERVIEW</span><h2>اتجاه السوق والسيولة</h2><p>اتجاه عام، وعدد العملات الصاعدة والهابطة، ومؤشر ضغط الشراء والبيع من حركة الأسعار.</p></div><button class="button small market-refresh" id="refreshMarketDirection">↻ تحديث</button></div><div id="marketDirectionSummary" class="market-direction-host">'+empty("جاري قراءة السوق…","يتم تحميل ملخص مستقل لهذا السوق.")+'</div></section>'+
        '<section class="market-section market-opportunities-section"><div class="market-section-heading"><div><span class="section-kicker">02 / OPPORTUNITIES</span><h2>الفرص داخل السوق</h2><p>نتائج الفحص لهذا السوق فقط؛ لا يتم خلط الأصول مع أسواق أخرى.</p></div><span class="market-section-icon">⌁</span></div>'+
          '<div class="market-scan-controls"><div class="market-frame-picker"><span class="market-frame-label">اختر فريم التداول</span><div class="frame-list market-frame-list" id="marketSignalFrames">'+[["15m","15 دقيقة"],["1h","ساعة"],["2h","ساعتان"],["4h","4 ساعات"],["1d","يومي"],["1w","أسبوعي"]].map((f,i)=>'<button type="button" class="frame market-frame-button '+(i===0?"active":"")+'" data-market-frame="'+f[0]+'"><strong>'+f[1]+'</strong><small>'+f[0]+'</small></button>').join("")+'</div></div><span class="market-auto-badge" id="signalAutoStatus">● الفحص التلقائي نشط</span><span class="market-scan-meta" id="signalMeta">يتم فحص هذا الفريم تلقائيًا وترتيب الفرص حسب التقييم.</span></div>'+
          '<div class="market-best-grid" id="marketBestSides"></div><div class="signal-grid market-signals" id="signalContent"></div></section>'+
        '<div class="market-disclaimer"><span>ⓘ</span><p>اتجاه السوق قراءة وصفية وليست توصية دخول. الإشارات تجريبية ولا تضمن الربح؛ تأكد من الأسعار والمخاطر قبل أي قرار.</p></div>'+
      '</div>';
    const loadDirection=async()=>{const out=$("marketDirectionSummary"),btn=$("refreshMarketDirection");btn.disabled=true;out.innerHTML='<div class="loading">جاري حساب اتجاه '+esc(m.name)+'…</div>';try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(m.api));if(!d.ok)throw new Error(d.message||"بيانات الاتجاه غير متاحة");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0),total=Number(d.assets_sampled??(up+down+flat)),buyPct=total?Math.round(up/total*100):0,sellPct=total?Math.round(down/total*100):0,dir=d.direction_ar||"مختلط / محايد",color=d.direction==="BULLISH"?"var(--green)":d.direction==="BEARISH"?"var(--red)":"var(--gold)";out.innerHTML='<div class="market-direction-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px"><div class="feature-card direction-card direction-main" style="padding:10px;min-height:0;gap:4px"><small>التوجّه العام</small><strong style="color:'+color+'">'+esc(dir)+'</strong><span class="direction-caption">'+esc(m.name)+'</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small>متوسط التغيّر</small><strong>'+pct(d.price_change_pct)+'</strong><span class="direction-caption">حركة العينة</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small><i class="direction-dot up"></i> صاعد</small><strong style="color:var(--green)">'+up+'</strong><span class="direction-caption">أصل صاعد</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small><i class="direction-dot down"></i> هابط</small><strong style="color:var(--red)">'+down+'</strong><span class="direction-caption">أصل هابط</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small><i class="direction-dot flat"></i> مستقر</small><strong>'+flat+'</strong><span class="direction-caption">حركة محدودة</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small>الأصول المفحوصة</small><strong>'+esc(total)+'</strong><span class="direction-caption">ضمن العينة الحالية</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small>ميل الشراء</small><strong style="color:var(--green)">'+buyPct+'%</strong><span class="direction-caption">نسبة الأصول الصاعدة</span></div><div class="feature-card direction-card" style="padding:10px;min-height:0;gap:4px"><small>ميل البيع</small><strong style="color:var(--red)">'+sellPct+'%</strong><span class="direction-caption">نسبة الأصول الهابطة</span></div></div><p class="market-updated-at">آخر تحديث: '+timeText(d.updated_at)+(d.stale?' · بيانات محفوظة مؤقتًا وليست مباشرة':'')+'</p>';}catch(err){out.innerHTML=empty("تعذر تحديد توجّه السوق",err.message)}finally{btn.disabled=false}};
    $("refreshMarketDirection").addEventListener("click",loadDirection);
    $("marketSignalFrames").addEventListener("click",e=>{const b=e.target.closest("[data-market-frame]");if(!b)return;selectedInterval=b.dataset.marketFrame;scanCycleIndex=scanIntervalOrder.indexOf(selectedInterval);if(scanCycleIndex<0)scanCycleIndex=0;$("marketSignalFrames").querySelectorAll("[data-market-frame]").forEach(x=>{const active=x===b;x.classList.toggle("active",active);x.setAttribute("aria-pressed",active?"true":"false")});loadSignals(m)});
    if(marketSignalRefreshTimer)clearInterval(marketSignalRefreshTimer);
    marketSignalRefreshTimer=setInterval(()=>{if(document.visibilityState==="visible" && $("signalContent") && $("signalMeta") && $("pageView").innerHTML.includes(esc(m.name)) && !marketSignalRefreshBusy){scanCycleIndex=(scanCycleIndex+1)%scanIntervalOrder.length;selectedInterval=scanIntervalOrder[scanCycleIndex];$("marketSignalFrames").querySelectorAll("[data-market-frame]").forEach(x=>{const active=x.dataset.marketFrame===selectedInterval;x.classList.toggle("active",active);x.setAttribute("aria-pressed",active?"true":"false")});loadDirection();loadSignals(m)}},30*1000);
    $("signalContent").addEventListener("click",e=>{const b=e.target.closest("[data-inline-chart]");if(!b)return;const card=b.closest(".signal-card"),symbol=b.dataset.symbol,frame=b.dataset.frame||selectedInterval,box=card&&card.querySelector("[data-chart-box]");if(!box)return;if(box.dataset.open==="1"){box.dataset.open="0";box.innerHTML="";b.textContent="عرض الشارت داخل الصفقة";return;}box.dataset.open="1";b.textContent="إخفاء الشارت";box.innerHTML='<div class="loading">تحميل الشارت…</div>';getJSON("/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(symbol)+"&interval="+encodeURIComponent(frame)).then(d=>{if(box.dataset.open==="1")box.innerHTML=drawCandles(d.items||[],{entry:Number(b.dataset.entry),stop_loss:Number(b.dataset.stop),tp1:Number(b.dataset.tp1),tp2:Number(b.dataset.tp2),tp3:Number(b.dataset.tp3)})}).catch(err=>{if(box.dataset.open==="1")box.innerHTML=empty("الشارت غير متاح",err.message)});});
    loadDirection();
    // Load the latest opportunities automatically when a market page opens.
    // The server persists every completed scan, so users do not need to press Scan.
    loadSignals(m);
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
  function signalCard(x, rank=0) {
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
    return '<article class="signal-card"><div class="signal-top"><span class="tag" style="font-weight:800;border:1px solid #c79b35;background:linear-gradient(135deg,#35270a,#9b7622);color:#fff0b3">'+medal+'</span><b class="signal-symbol">'+esc(x.symbol||"—")+'</b><span class="tag '+(buy?"buy":"sell")+'">'+esc(strength)+'</span><span class="tag">'+esc(x.interval||selectedInterval)+'</span><span class="tag">تقييم آلي '+esc(x.ai_score??x.confidence??"—")+'/100</span></div>'+
      '<div class="entry-line"><span>الدخول</span><strong>'+price(entry)+'</strong></div><div class="levels-grid">'+
      '<div class="level stop"><small>وقف الخسارة</small><strong>'+price(stop)+'</strong><small class="negative">خسارة محتملة '+pctTo(stop,false)+'</small></div>'+
      '<div class="level target"><small>الهدف الأول</small><strong>'+price(tp1)+'</strong><small class="positive">ربح محتمل '+pctTo(tp1,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثاني</small><strong>'+price(tp2)+'</strong><small class="positive">ربح محتمل '+pctTo(tp2,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثالث</small><strong>'+price(tp3)+'</strong><small class="positive">ربح محتمل '+pctTo(tp3,true)+'</small></div></div>'+
      '<div class="toolbar" style="margin-top:12px"><button type="button" class="button small" data-inline-chart="1" data-symbol="'+esc(x.symbol||"")+'" data-frame="'+esc(x.interval||selectedInterval)+'" data-entry="'+esc(entry)+'" data-stop="'+esc(stop)+'" data-tp1="'+esc(tp1)+'" data-tp2="'+esc(tp2)+'" data-tp3="'+esc(tp3)+'">عرض الشارت داخل الصفقة</button></div><div data-chart-box data-open="0" style="margin-top:10px"></div><div class="muted" style="margin-top:10px">'+esc(x.status||"النسب تقديرية من سعر الدخول إلى الهدف/الوقف، قبل الرسوم والانزلاق")+'</div></article>';
  }
  function reversePublicIdea(item) {
    const original=String(item.direction||"");
    const buy=["شراء","BUY","LONG"].includes(original);
    const l=item.levels||{};
    const entry=Number(l.entry),oldStop=Number(l.stop_loss);
    const targets=["tp1","tp2","tp3"].map(k=>Number(l[k]));
    if(!Number.isFinite(entry)||entry<=0||!Number.isFinite(oldStop)||!targets.every(v=>Number.isFinite(v)&&v>0))return null;
    const side=buy?"بيع":"شراء";
    const stop=buy?entry+(entry-oldStop):entry-(oldStop-entry);
    const mirrored=targets.map(v=>buy?entry-(v-entry):entry+(entry-v)).sort((a,b)=>buy?b-a:a-b);
    const ordered=buy?(stop>entry&&mirrored.every(v=>v<entry)):(stop<entry&&mirrored.every(v=>v>entry));
    if(!ordered||mirrored.some(v=>!Number.isFinite(v)||v<=0))return null;
    return {...item,direction:side,side,original_direction:original,levels:{entry,stop_loss:stop,tp1:mirrored[0],tp2:mirrored[1],tp3:mirrored[2]},
      status:"صفقة معكوسة عن المصدر العام؛ المستويات انعكاس حسابي حول الدخول وليست توصية موثقة. المصدر: "+String(item.source||"مصدر عام")};
  }
  function analyzePublicCandles(rows) {
    if(!Array.isArray(rows)||rows.length<35)return {score:null,methods:[],note:"شموع غير كافية للتحليل الفني"};
    const close=rows.map(r=>Number(r.close??r.c)).filter(Number.isFinite);
    const high=rows.map(r=>Number(r.high??r.h)).filter(Number.isFinite);
    const low=rows.map(r=>Number(r.low??r.l)).filter(Number.isFinite);
    const volume=rows.map(r=>Number(r.volume??r.v??0));
    if(close.length<35||high.length!==close.length||low.length!==close.length)return {score:null,methods:[],note:"تعذر قراءة الشموع"};
    const ema=(period)=>{let a=close[0],k=2/(period+1);for(let i=1;i<close.length;i++)a=close[i]*k+a*(1-k);return a};
    const change=close.at(-1)-close.at(-2);
    let gains=0,losses=0;for(let i=Math.max(1,close.length-14);i<close.length;i++){const d=close[i]-close[i-1];if(d>0)gains+=d;else losses-=d;}
    const rsi=losses===0?100:100-100/(1+(gains/14)/(losses/14));
    const mean=close.slice(-20).reduce((a,b)=>a+b,0)/20;
    const sd=Math.sqrt(close.slice(-20).reduce((a,b)=>a+(b-mean)**2,0)/20);
    const avgVol=volume.slice(-21,-1).reduce((a,b)=>a+b,0)/20;
    const lastVol=volume.at(-1)||0;
    const methods=[];
    const add=(name,dir,why)=>methods.push({name,dir,why});
    add("اتجاه EMA 20/50",ema(20)>ema(50)?"شراء":"بيع",ema(20)>ema(50)?"EMA20 أعلى EMA50":"EMA20 أدنى EMA50");
    add("فلتر EMA200",ema(20)>ema(Math.min(200,close.length))?"شراء":"بيع",close.at(-1)>ema(Math.min(200,close.length))?"السعر فوق المتوسط الطويل":"السعر تحت المتوسط الطويل");
    add("RSI 14",rsi>=55?"شراء":rsi<=45?"بيع":"محايد","RSI "+rsi.toFixed(1));
    add("MACD مبسط",ema(12)>ema(26)?"شراء":"بيع","EMA12 مقابل EMA26");
    add("بولنجر 20",close.at(-1)>mean+sd?"شراء":close.at(-1)<mean-sd?"بيع":"محايد","موقع السعر من نطاق ±1 انحراف");
    add("زخم الشمعة",change>0?"شراء":"بيع",change>0?"الإغلاق أعلى من السابق":"الإغلاق أدنى من السابق");
    add("حجم التداول",lastVol>avgVol*1.2?(change>0?"شراء":"بيع"):"محايد","حجم آخر شمعة "+(avgVol>0?(lastVol/avgVol).toFixed(2)+"× المتوسط":"غير متاح"));
    const recentHigh=Math.max(...high.slice(-20)),recentLow=Math.min(...low.slice(-20));
    add("اختراق دعم/مقاومة",close.at(-1)>=recentHigh?"شراء":close.at(-1)<=recentLow?"بيع":"محايد","نطاق أعلى/أدنى 20 شمعة");
    const up=methods.filter(m=>m.dir==="شراء").length,down=methods.filter(m=>m.dir==="بيع").length;
    return {score:Math.round(Math.max(up,down)/methods.length*100),methods,note:""+up+" مناهج تميل للشراء · "+down+" تميل للبيع · البقية محايدة"};
  }
  async function loadSignals(m) {
    if(marketSignalRefreshBusy)return;
    const out=$("signalContent"),meta=$("signalMeta"),status=$("signalAutoStatus");
    if(!out||!meta)return;
    marketSignalRefreshBusy=true;
    if(status)status.textContent="● جاري الفحص التلقائي";
    meta.textContent="فحص متتابع يبدأ بالسريع: "+selectedInterval+" ثم الأبطأ…";
    if(!out.innerHTML.trim() || out.innerHTML.includes("جاري"))out.innerHTML='<div class="loading">جاري فحص الفرص تلقائيًا…</div>';
    try {
      const d=m.api==="futures"?await getJSON("/api/public-ideas?market=futures&interval=auto&limit=50&discover=true&refresh=true"):await getJSON("/api/signals/"+encodeURIComponent(m.api)+"?interval="+encodeURIComponent(selectedInterval)+"&limit=20&refresh=true");
      let rawItems=Array.isArray(d.items)?d.items:[];
      if(m.api==="futures") {
        const recent=rawItems.filter(x=>x&&x.has_complete_levels&&x.levels&&x.levels.tp1&&x.levels.tp2&&x.levels.tp3);
        const reversed=[];
        for(const x of recent.slice(0,20)){const y=reversePublicIdea(x);if(y)reversed.push(y);}
        const analyzed=await Promise.all(reversed.map(async x=>{try{const chart=await getJSON("/api/trade-chart-data?market=futures&symbol="+encodeURIComponent(x.symbol)+"&interval="+encodeURIComponent(selectedInterval));const a=analyzePublicCandles(chart.items||[]);return {...x,ai_score:a.score??"—",confidence:a.score??"—",technical_analysis:a,status:x.status+" · "+a.note+" · "+a.methods.map(m=>m.name+": "+m.dir).join("، ")};}catch(_){return {...x,ai_score:"—",confidence:"—",status:x.status+" · تعذر تحميل الشموع للتحليل المستقل"};}}));
        rawItems=analyzed;
      }
      // Reject malformed crypto symbols and incorrectly ordered price levels before rendering.
      const cryptoMarket=["spot","futures","alpha"].includes(m.api);
      const items=rawItems.filter(x=>{
        if(!x||typeof x!=="object")return false;
        const symbol=String(x.symbol||"").trim().toUpperCase();
        if(!symbol||(cryptoMarket&&!/^[A-Z0-9]+$/.test(symbol)))return false;
        const side=String(x.direction||x.side||"");
        const levels=x.levels&&typeof x.levels==="object"?x.levels:{};
        const nums=["entry","stop_loss","tp1","tp2","tp3"].map(k=>Number(levels[k]));
        if(!nums.every(v=>Number.isFinite(v)&&v>0))return false;
        const [entry,stop,tp1,tp2,tp3]=nums;
        if(side==="شراء"||side==="BUY"||side==="LONG")return stop<entry&&entry<tp1&&tp1<=tp2&&tp2<=tp3;
        if(side==="بيع"||side==="SELL"||side==="SHORT")return stop>entry&&entry>tp1&&tp1>=tp2&&tp2>=tp3;
        return false;
      });
      // Keep the server's quality/risk-reward order; sorting by score alone hid its ranking.
      meta.textContent="فُحص "+(d.scanned??"—")+" أصل على "+selectedInterval+" · "+items.length+" فرصة صالحة · ينتقل تلقائيًا من الأسرع للأبطأ";
      const bestBuy=items.find(x=>["شراء","BUY","LONG"].includes(x.direction||x.side)),bestSell=items.find(x=>["بيع","SELL","SHORT"].includes(x.direction||x.side)),bestBox=$("marketBestSides");if(bestBox)bestBox.innerHTML='<div class="feature-card"><small>أفضل شراء</small><strong>'+esc(bestBuy?.symbol||"لا توجد فرصة")+'</strong><small>'+esc(bestBuy?(bestBuy.interval||selectedInterval)+" · تقييم "+(bestBuy.ai_score??bestBuy.confidence??"—")+"/100":"لم تظهر صفقة شراء مؤهلة")+'</small></div><div class="feature-card"><small>أفضل بيع</small><strong>'+esc(bestSell?.symbol||"لا توجد فرصة")+'</strong><small>'+esc(bestSell?(bestSell.interval||selectedInterval)+" · تقييم "+(bestSell.ai_score??bestSell.confidence??"—")+"/100":"لم تظهر صفقة بيع مؤهلة")+'</small></div>';
      out.innerHTML=items.length?items.map((x,i)=>signalCard(x,i)).join(""):empty("لا توجد فرص مؤهلة الآن",d.message||"لن نعرض صفقة بمستويات ناقصة أو غير مرتبة.");
    } catch(err) {out.innerHTML=empty("تعذر فحص الفرص",err.message);meta.textContent="فشل الفحص"}
    finally {marketSignalRefreshBusy=false;if(status)status.textContent="● الفحص التلقائي نشط";}
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
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const view = $("pageView");
  const API_TIMEOUT = 12000;
  const markets = {
    spot:{slug:"spot",api:"spot",name:"سبوت Binance",sub:"العملات الفورية",icon:"◉",source:"Binance"},
    futures:{slug:"futures",api:"futures",name:"فيوتشر Binance",sub:"العقود الدائمة",icon:"⇅",source:"Binance"},
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
  let selectedInterval = "15m";
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
  function footerNotice(text) { return '<p class="muted">'+esc(text)+'</p>'; }
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
      const s=$("homeStatus"); if(s)s.textContent=data.ok?"الخدمة تستجيب · بيانات الأسعار حسب المصدر":"الخدمة غير متاحة";
      setStatus(data.ok?"الخدمة جاهزة":"تحقق من الخدمة",!!data.ok);
    }).catch(()=>{const s=$("homeStatus");if(s)s.textContent="تعذر التحقق من الخدمة الآن";setStatus("تعذر التحقق",false)});
    if($("homeMarketDashboard"))return;
    const hero=document.querySelector(".hero");
    if(!hero)return;
    const options=Object.entries(markets).map(([key,m])=>'<option value="'+esc(key)+'" '+(key==="futures"?"selected":"")+'>'+esc(m.name)+'</option>').join("");
    hero.insertAdjacentHTML("afterend",'<section class="panel" id="homeMarketDashboard" style="margin:16px 0"><div class="panel-head"><div><span class="eyebrow">LIVE MARKET</span><h2 style="margin:4px 0">توجّه السوق وأفضل صفقة</h2><p class="muted">قراءة السوق أولًا، ثم فحص صفقة مكتملة المستويات.</p></div><a class="button small" href="/market-direction">كل التوجهات</a></div><div class="toolbar"><label class="field" style="flex:1;min-width:170px">السوق<select id="homeTradeMarket" class="frame" style="width:100%;margin-top:6px">'+options+'</select></label><label class="field" style="min-width:110px">فريم الدخول<select id="homeTradeInterval" class="frame" style="width:100%;margin-top:6px"><option value="15m" selected>15 دقيقة</option><option value="1h">ساعة</option><option value="2h">ساعتان</option><option value="4h">4 ساعات</option><option value="1d">يومي</option><option value="1w">أسبوعي</option><option value="1M">شهري</option></select></label><button class="button primary" id="homeFindTrade">جلب أفضل صفقة</button></div><div id="homeDirectionResult" style="margin-top:14px">'+empty("جاري قراءة اتجاه السوق…")+'</div><div style="margin-top:14px"><h3>أفضل فرصة مؤهلة</h3><div id="homeTradeResult">'+empty("اضغط «جلب أفضل صفقة»","سنفحص فرص السوق المختار عند الطلب.")+'</div></div><p class="notice">الاتجاه العام ليس توصية دخول. لا تُعرض صفقة إذا كانت مستويات الدخول والوقف والأهداف غير مكتملة.</p></section>');
    const loadDirection=async()=>{const out=$("homeDirectionResult"),key=$("homeTradeMarket").value;out.innerHTML='<div class="loading">جاري قراءة توجه السوق…</div>';try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(markets[key].api));if(!d.ok)throw new Error(d.message||"بيانات الاتجاه غير متاحة");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0),dir=d.direction_ar||"مختلط / محايد",color=d.direction==="BULLISH"?"var(--green)":d.direction==="BEARISH"?"var(--red)":"var(--gold)";out.innerHTML='<div class="feature-grid"><div class="feature-card"><small>توجّه السوق</small><strong style="color:'+color+'">'+esc(dir)+'</strong></div><div class="feature-card"><small>متوسط التغير</small><strong>'+pct(d.price_change_pct)+'</strong></div><div class="feature-card"><small>صاعدة</small><strong style="color:var(--green)">'+up+'</strong></div><div class="feature-card"><small>هابطة</small><strong style="color:var(--red)">'+down+'</strong></div><div class="feature-card"><small>مستقرة</small><strong>'+flat+'</strong></div><div class="feature-card"><small>عينة الفحص</small><strong>'+esc(d.assets_sampled??(up+down+flat))+'</strong></div></div><p class="muted" style="margin-top:10px">آخر تحديث: '+timeText(d.updated_at)+'</p>';}catch(err){out.innerHTML=empty("تعذر تحديد التوجه",err.message)}};
    const findTrade=async()=>{const out=$("homeTradeResult"),btn=$("homeFindTrade"),key=$("homeTradeMarket").value,frame=$("homeTradeInterval").value;btn.disabled=true;out.innerHTML='<div class="loading">جاري فحص أفضل الفرص…</div>';try{const d=await getJSON("/api/signals/"+encodeURIComponent(markets[key].api)+"?interval="+encodeURIComponent(frame)+"&limit=20&refresh=true");const items=(Array.isArray(d.items)?d.items:[]).filter(x=>{const l=x.levels||{},entry=Number(l.entry??x.entry),sl=Number(l.stop_loss??x.stop_loss),t1=Number(l.tp1??x.tp1),t2=Number(l.tp2??x.tp2),t3=Number(l.tp3??x.tp3),side=x.direction||x.side,buy=["شراء","BUY","LONG"].includes(side);return [entry,sl,t1,t2,t3].every(n=>Number.isFinite(n)&&n>0)&&((buy&&sl<entry&&t1>entry&&t2>t1&&t3>t2)||(!buy&&sl>entry&&t1<entry&&t2<t1&&t3<t2))}).sort((a,b)=>Number(b.ai_score??b.confidence??0)-Number(a.ai_score??a.confidence??0));out.innerHTML=items.length?signalCard(items[0],0):empty("ما فيه صفقة مكتملة حاليًا","تم فحص "+(d.scanned??"العينة المتاحة")+" أصل. ما راح نركّب دخول أو أهداف من عندنا.");}catch(err){out.innerHTML=empty("تعذر جلب الصفقة",err.message)}finally{btn.disabled=false}};
    $("homeFindTrade").addEventListener("click",findTrade);
    $("homeTradeMarket").addEventListener("change",loadDirection);
    $("homeTradeResult").addEventListener("click",e=>{const b=e.target.closest("[data-inline-chart]");if(!b)return;const card=b.closest(".signal-card"),symbol=b.dataset.symbol,frame=b.dataset.frame||$("homeTradeInterval").value,box=card&&card.querySelector("[data-chart-box]");if(!box)return;if(box.dataset.open==="1"){box.dataset.open="0";box.innerHTML="";b.textContent="عرض الشارت داخل الصفقة";return;}box.dataset.open="1";b.textContent="إخفاء الشارت";box.innerHTML='<div class="loading">تحميل الشارت…</div>';getJSON("/api/trade-chart-data?market="+encodeURIComponent(markets[$("homeTradeMarket").value].api)+"&symbol="+encodeURIComponent(symbol)+"&interval="+encodeURIComponent(frame)).then(d=>{if(box.dataset.open==="1")box.innerHTML=drawCandles(d.items||[])}).catch(err=>{if(box.dataset.open==="1")box.innerHTML=empty("الشارت غير متاح",err.message)});});
    loadDirection();
  }
  function quoteRows(items) {
    if(!items.length)return empty("لا توجد أصول متاحة","لم يرجع المصدر أصولًا قابلة للعرض.");
    return '<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>الشارت</th></tr></thead><tbody>'+
      items.map(x=>'<tr><td><b dir="ltr">'+esc(x.symbol||"—")+'</b></td><td><span class="pill">اضغط لعرض الشارت</span></td></tr>').join("")+
      '</tbody></table></div>';
  }
  function renderMarketPage(key) {
    const m=markets[key]; if(!m)return;
    view.innerHTML=pageHeader(m.name,m.sub+" · المصدر: "+m.source,"الأسواق")+
      '<section class="panel"><div class="panel-head"><div><h2>توجّه السوق الآن</h2><div class="muted">ملخص هذا السوق فقط: الصاعد والهابط والمستقر ومتوسط الحركة.</div></div><button class="button small" id="refreshMarketDirection">تحديث الاتجاه</button></div><div id="marketDirectionSummary" style="margin-top:12px">'+empty("جاري قراءة السوق…")+'</div><div class="divider" style="margin:18px 0"></div><div class="panel-head"><div><h2>الصفقات داخل نفس السوق</h2><div class="muted">فحص حتى 20 أصلًا من السوق الحالي، على الفريم المحدد.</div></div></div><div class="toolbar"><label class="field" style="min-width:120px">فريم الدخول<select id="marketSignalInterval" class="frame" style="width:100%;margin-top:6px"><option value="15m" selected>15 دقيقة</option><option value="1h">ساعة</option><option value="2h">ساعتان</option><option value="4h">4 ساعات</option><option value="1d">يومي</option></select></label><button class="button primary" id="loadSignals">فحص أفضل الفرص</button><span class="muted" id="signalMeta">اضغط لفحص السوق الحالي.</span></div><div id="marketBestSides" class="feature-grid" style="margin-top:12px"></div><div class="signal-grid" id="signalContent" style="margin-top:12px"></div></section>'+
      '<div class="notice">الاتجاه قراءة وصفية للسوق وليست توصية دخول. الإشارات آلية تجريبية ولا تضمن الربح.</div>';
    const loadDirection=async()=>{const out=$("marketDirectionSummary"),btn=$("refreshMarketDirection");btn.disabled=true;out.innerHTML='<div class="loading">جاري حساب اتجاه '+esc(m.name)+'…</div>';try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(m.api));if(!d.ok)throw new Error(d.message||"بيانات الاتجاه غير متاحة");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0),dir=d.direction_ar||"مختلط / محايد",color=d.direction==="BULLISH"?"var(--green)":d.direction==="BEARISH"?"var(--red)":"var(--gold)";out.innerHTML='<div class="feature-grid"><div class="feature-card"><small>توجّه '+esc(m.name)+'</small><strong style="color:'+color+'">'+esc(dir)+'</strong></div><div class="feature-card"><small>متوسط التغيّر</small><strong>'+pct(d.price_change_pct)+'</strong></div><div class="feature-card"><small>🟢 صاعد</small><strong style="color:var(--green)">'+up+'</strong></div><div class="feature-card"><small>🔴 هابط</small><strong style="color:var(--red)">'+down+'</strong></div><div class="feature-card"><small>🟡 مستقر</small><strong>'+flat+'</strong></div><div class="feature-card"><small>الأصول المفحوصة</small><strong>'+esc(d.assets_sampled??up+down+flat)+'</strong></div></div><p class="muted" style="margin-top:10px">آخر تحديث: '+timeText(d.updated_at)+'</p>';}catch(err){out.innerHTML=empty("تعذر تحديد توجّه السوق",err.message)}finally{btn.disabled=false}};
    $("refreshMarketDirection").addEventListener("click",loadDirection);
    $("loadSignals").addEventListener("click",()=>{selectedInterval=$("marketSignalInterval").value;loadSignals(m)});
    $("marketSignalInterval").addEventListener("change",()=>{selectedInterval=$("marketSignalInterval").value;loadSignals(m)});
    // Refresh visible market opportunities periodically without background polling or parallel scans.
    setInterval(()=>{if(document.visibilityState==="visible" && $("signalContent") && !$("loadSignals").disabled){selectedInterval=$("marketSignalInterval").value;loadSignals(m)}},10*60*1000);
    $("signalContent").addEventListener("click",e=>{const b=e.target.closest("[data-inline-chart]");if(!b)return;const card=b.closest(".signal-card"),symbol=b.dataset.symbol,frame=b.dataset.frame||selectedInterval,box=card&&card.querySelector("[data-chart-box]");if(!box)return;if(box.dataset.open==="1"){box.dataset.open="0";box.innerHTML="";b.textContent="عرض الشارت داخل الصفقة";return;}box.dataset.open="1";b.textContent="إخفاء الشارت";box.innerHTML='<div class="loading">تحميل الشارت…</div>';getJSON("/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(symbol)+"&interval="+encodeURIComponent(frame)).then(d=>{if(box.dataset.open==="1")box.innerHTML=drawCandles(d.items||[])}).catch(err=>{if(box.dataset.open==="1")box.innerHTML=empty("الشارت غير متاح",err.message)});});
    loadDirection();
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
  function drawCandles(items) {
    const rows=(items||[]).filter(c=>[c.open,c.high,c.low,c.close].every(v=>Number.isFinite(Number(v))&&Number(v)>0));
    if(rows.length<2)return empty("بيانات الشموع غير كافية","لم يرسم الموقع أي شموع تقديرية.");
    const W=900,H=300,pad=28,lo=Math.min(...rows.map(c=>Number(c.low))),hi=Math.max(...rows.map(c=>Number(c.high))),range=hi-lo||1;
    const y=v=>pad+(hi-Number(v))/range*(H-pad*2),step=(W-pad*2)/rows.length,bodyW=Math.max(2,Math.min(9,step*.58));
    const grid=[0,.25,.5,.75,1].map(t=>{const yy=pad+(H-pad*2)*t;return '<line x1="'+pad+'" y1="'+yy+'" x2="'+(W-pad)+'" y2="'+yy+'" stroke="#26364d" stroke-width="1"/>'}).join("");
    const candles=rows.map((c,i)=>{const x=pad+step*i+step/2,up=Number(c.close)>=Number(c.open),color=up?"#43d6a1":"#ff7184",top=y(Math.max(Number(c.open),Number(c.close))),bottom=y(Math.min(Number(c.open),Number(c.close))),height=Math.max(1,bottom-top);return '<line x1="'+x+'" y1="'+y(c.high)+'" x2="'+x+'" y2="'+y(c.low)+'" stroke="'+color+'" stroke-width="1.3"/><rect x="'+(x-bodyW/2)+'" y="'+top+'" width="'+bodyW+'" height="'+height+'" fill="'+color+'" rx=".5"/>'}).join("");
    return '<div style="width:100%;overflow:hidden"><svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="مخطط شموع حقيقية دون إظهار تدريج الأسعار" style="width:100%;height:auto;display:block;background:#0a1321;border-radius:12px">'+grid+candles+'</svg></div><div class="muted" style="margin-top:8px">عدد الشموع: '+rows.length+' · المصدر الفعلي · تدريج الأسعار مخفي</div>';
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
    return '<article class="signal-card"><div class="signal-top"><span class="tag" style="font-weight:800;border:1px solid #c79b35;background:linear-gradient(135deg,#35270a,#9b7622);color:#fff0b3">'+medal+'</span><b class="signal-symbol">'+esc(x.symbol||"—")+'</b><span class="tag '+(buy?"buy":"sell")+'">'+esc(side)+'</span><span class="tag">'+esc(x.interval||selectedInterval)+'</span><span class="tag">AI '+esc(x.ai_score??x.confidence??"—")+'%</span></div>'+
      '<div class="entry-line"><span>الدخول</span><strong>'+price(entry)+'</strong></div><div class="levels-grid">'+
      '<div class="level stop"><small>وقف الخسارة</small><strong>'+price(stop)+'</strong><small class="negative">خسارة محتملة '+pctTo(stop,false)+'</small></div>'+
      '<div class="level target"><small>الهدف الأول</small><strong>'+price(tp1)+'</strong><small class="positive">ربح محتمل '+pctTo(tp1,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثاني</small><strong>'+price(tp2)+'</strong><small class="positive">ربح محتمل '+pctTo(tp2,true)+'</small></div>'+
      '<div class="level target"><small>الهدف الثالث</small><strong>'+price(tp3)+'</strong><small class="positive">ربح محتمل '+pctTo(tp3,true)+'</small></div></div>'+
      '<div class="toolbar" style="margin-top:12px"><button type="button" class="button small" data-inline-chart="1" data-symbol="'+esc(x.symbol||"")+'" data-frame="'+esc(x.interval||selectedInterval)+'">عرض الشارت داخل الصفقة</button></div><div data-chart-box data-open="0" style="margin-top:10px"></div><div class="muted" style="margin-top:10px">'+esc(x.status||"النسب تقديرية من سعر الدخول إلى الهدف/الوقف، قبل الرسوم والانزلاق")+'</div></article>';
  }
  async function loadSignals(m) {
    const out=$("signalContent"),meta=$("signalMeta"),button=$("loadSignals");button.disabled=true;
    out.innerHTML='<div class="loading">جاري فحص عينة محدودة من '+esc(m.name)+'…</div>';meta.textContent="فحص محدود · "+selectedInterval;
    try {
      const d=await getJSON("/api/signals/"+encodeURIComponent(m.api)+"?interval="+encodeURIComponent(selectedInterval)+"&limit=20&refresh=true");
      const items=Array.isArray(d.items)?d.items.slice():[];
      // Rank the medals by the source's own confidence score when available.
      items.sort((a,b)=>{
        const score=x=>{const n=Number(x.ai_score??x.confidence);return Number.isFinite(n)?n:null};
        const aa=score(a),bb=score(b);
        if(aa===null&&bb===null)return 0;
        if(aa===null)return 1;
        if(bb===null)return -1;
        return bb-aa;
      });
      meta.textContent="تم فحص "+(d.scanned??"—")+" أصل · "+items.length+" فرصة · الترتيب حسب الثقة المتاحة";
      const bestBuy=items.find(x=>["شراء","BUY","LONG"].includes(x.direction||x.side)),bestSell=items.find(x=>["بيع","SELL","SHORT"].includes(x.direction||x.side)),bestBox=$("marketBestSides");if(bestBox)bestBox.innerHTML='<div class="feature-card"><small>أفضل شراء</small><strong>'+esc(bestBuy?.symbol||"لا توجد فرصة")+'</strong><small>'+esc(bestBuy?(bestBuy.interval||selectedInterval)+" · ثقة "+(bestBuy.ai_score??bestBuy.confidence??"—")+"%":"لم تظهر صفقة شراء مؤهلة")+'</small></div><div class="feature-card"><small>أفضل بيع</small><strong>'+esc(bestSell?.symbol||"لا توجد فرصة")+'</strong><small>'+esc(bestSell?(bestSell.interval||selectedInterval)+" · ثقة "+(bestSell.ai_score??bestSell.confidence??"—")+"%":"لم تظهر صفقة بيع مؤهلة")+'</small></div>';
      out.innerHTML=items.length?items.map((x,i)=>signalCard(x,i)).join(""):empty("لا توجد فرص مؤهلة الآن",d.message||"لن نعرض صفقة بمستويات ناقصة أو غير مرتبة.");
    } catch(err) {out.innerHTML=empty("تعذر فحص الفرص",err.message);meta.textContent="فشل الفحص"}
    finally {button.disabled=false}
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
        }).join("")+'</tbody></table></div>':empty("السجل جاهز وينتظر أول فرصة","اذهب إلى صفحة أحد الأسواق وشغّل فحص الفرص. ستظهر الفرص المكتشفة هنا بعد الفحص، ولن تُحتسب نتيجة مالية قبل تأكيدها.");
      } catch(err) {
        out.innerHTML=empty("تعذر تحميل سجل النتائج",err.message||"تحقق من اتصال الخادم ثم حاول مرة أخرى.")+'<div style="margin-top:12px"><button class="button secondary" id="retryResults">إعادة المحاولة</button></div>';
        $("retryResults")?.addEventListener("click",load);
      } finally {if(button)button.disabled=false}
    };
    $("refreshResults").addEventListener("click",load);
    await load();
  }
  async function renderNews() {
    view.innerHTML=pageHeader("أخبار الأسواق","الأخبار العامة تساعد على فهم السياق ولا تعتبر توصية تداول.","المتابعة")+
      '<section class="panel"><div class="panel-head"><h2>تصفية الأخبار</h2><select id="newsMarket" class="frame" aria-label="اختر السوق"><option value="all">كل الأسواق</option><option value="crypto">العملات الرقمية</option><option value="us">الأسهم الأمريكية</option><option value="saudi">السوق السعودي</option><option value="forex">الفوركس والذهب</option><option value="contracts">العقود الأمريكية</option><option value="spot">سبوت</option><option value="futures">فيوتشر</option></select></div><div id="newsContent" class="loading">اختر السوق أو انتظر تحميل الأخبار…</div></section>';
    const load=async()=>{const out=$("newsContent");out.innerHTML='<div class="loading">جاري تحميل الأخبار…</div>';try{const d=await getJSON("/api/news?market="+encodeURIComponent($("newsMarket").value)+"&limit=30");const items=d.items||[];out.innerHTML=items.length?'<div class="feature-grid">'+items.map(x=>'<article class="feature-card"><span>◉</span><strong>'+esc(x.title||x.headline||"خبر سوق")+'</strong><small>'+esc(x.market||x.source||"مصدر عام")+' · '+timeText(x.published_at)+'</small><p class="muted">'+esc(x.description||x.summary||"")+'</p></article>').join("")+'</div>':empty("لا توجد أخبار مطابقة",d.message||"قد تكون المصادر غير متاحة مؤقتًا.")}catch(err){out.innerHTML=empty("تعذر تحميل الأخبار",err.message)}};
    $("newsMarket").addEventListener("change",load);await load();
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
    const load=async()=>{const out=$("directionContent"),btn=$("refreshDirection"),key=$("directionMarket").value;out.innerHTML='<div class="loading">جاري حساب اتجاه السوق…</div>';btn.disabled=true;try{const d=await getJSON("/api/market-direction?market="+encodeURIComponent(markets[key].api));if(!d.ok)throw new Error(d.message||"بيانات الاتجاه غير متاحة");const up=Number(d.assets_up||0),down=Number(d.assets_down||0),flat=Number(d.assets_flat||0),dir=d.direction_ar||"مختلط / محايد",color=d.direction==="BULLISH"?"var(--green)":d.direction==="BEARISH"?"var(--red)":"var(--gold)";out.innerHTML='<div class="feature-grid"><div class="feature-card"><small>اتجاه السوق</small><strong style="color:'+color+'">'+esc(dir)+'</strong></div><div class="feature-card"><small>متوسط التغير</small><strong>'+pct(d.price_change_pct)+'</strong></div><div class="feature-card"><small>أصول صاعدة</small><strong style="color:var(--green)">'+up+'</strong></div><div class="feature-card"><small>أصول هابطة</small><strong style="color:var(--red)">'+down+'</strong></div><div class="feature-card"><small>أصول شبه مستقرة</small><strong>'+flat+'</strong></div><div class="feature-card"><small>الأصول المفحوصة</small><strong>'+esc(d.assets_sampled??(up+down+flat))+'</strong></div></div><p class="muted" style="margin-top:12px">آخر تحديث: '+timeText(d.updated_at)+'</p>';}catch(err){out.innerHTML=empty("تعذر تحديد اتجاه السوق",err.message)}finally{btn.disabled=false}};
    $("refreshDirection").addEventListener("click",load);
    $("directionMarket").addEventListener("change",load);
    load();
  }
  async function render() {
    activateDrawer();
    if(path==="/"){renderHome();return}
    if(marketKey){renderMarketPage(marketKey);return}
    if(path==="/market-direction"){renderMarketDirection();return}
    if(path==="/results"){await renderResults();return}
    if(path==="/news"){await renderNews();return}
    if(path==="/analysis"){renderAnalysis();return}
    if(path==="/tasi-analysis"){await renderTasi();return}
    if(path==="/account"){renderAccount();return}
    if(path==="/admin"){renderAdmin();return}
    // Blog pages are server-rendered and should never be replaced by this shell.
    view.innerHTML=pageHeader("الصفحة غير موجودة","الرابط المطلوب غير معروف. استخدم القائمة للعودة إلى قسم متاح.")+'<a class="button primary" href="/">العودة للرئيسية</a>';
  }
  document.addEventListener("DOMContentLoaded",()=>render().catch(err=>{if(view)view.innerHTML='<section class="panel">'+empty("تعذر عرض الصفحة",err.message)+'</section>';setStatus("خطأ في الواجهة",false)}));
})();
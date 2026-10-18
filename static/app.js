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
  }
  function quoteRows(items) {
    if(!items.length)return empty("لا توجد أسعار متاحة","لم يرجع المصدر بيانات قابلة للعرض؛ لم نضع أسعارًا تقديرية.");
    return '<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>السعر</th><th>التغير 24س</th><th>حجم التداول</th></tr></thead><tbody>'+
      items.map(x=>'<tr><td><b dir="ltr">'+esc(x.symbol||"—")+'</b></td><td class="ltr">'+price(x.price)+'</td><td class="'+(Number(x.change_pct)>0?"positive":Number(x.change_pct)<0?"negative":"")+'">'+pct(x.change_pct)+'</td><td class="ltr">'+(x.quote_volume!=null?price(x.quote_volume):x.dollar_volume!=null?price(x.dollar_volume):"—")+'</td></tr>').join("")+
      '</tbody></table></div>';
  }
  function renderMarketPage(key) {
    const m=markets[key]; if(!m)return;
    view.innerHTML=pageHeader(m.name,m.sub+" · المصدر: "+m.source,"الأسواق")+
      '<section class="panel"><div class="panel-head"><div><h2>أسعار السوق</h2><div class="muted" id="quoteMeta">تحميل أسعار السوق عند الطلب…</div></div><div class="toolbar"><button class="button small primary" id="loadQuotes">تحميل الأسعار</button><button class="button small" id="refreshQuotes">تحديث</button></div></div><div id="quoteContent">'+empty("جاهز لتحميل السوق","اضغط تحميل الأسعار لبدء طلب واحد لهذا السوق فقط.")+'</div></section>'+
      '<section class="panel"><div class="panel-head"><div><h2>الشارت الفني</h2><div class="muted" id="chartMeta">اختر أصلًا من الجدول لعرض شموعه الفعلية.</div></div><span class="pill" id="chartSymbol">لم يُحدد أصل</span></div><div class="frame-list" id="frames">'+["15m","1h","4h","1d","1w","1M"].map((f,i)=>'<button class="frame '+(i===0?"active":"")+'" data-frame="'+f+'">'+({"15m":"15 دقيقة","1h":"ساعة","4h":"4 ساعات","1d":"يومي","1w":"أسبوعي","1M":"شهري"}[f])+'</button>').join("")+'</div><div id="chartContent">'+empty("بانتظار اختيار الأصل","سيتم رسم الشموع من بيانات المصدر الفعلية فقط.")+'</div></section>'+
      '<section class="panel"><div class="panel-head"><div><h2>فرص التحليل الفني</h2><div class="muted">فحص محدود عند الطلب حتى لا تتجمّد الصفحة.</div></div></div><div class="toolbar"><button class="button primary" id="loadSignals">فحص الفرص</button><span class="muted" id="signalMeta">لا يبدأ الفحص إلا عند الضغط.</span></div><div class="signal-grid" id="signalContent" style="margin-top:12px"></div></section>'+
      '<div class="notice">الأسعار العامة قد تكون متأخرة. الإشارات آلية تجريبية وليست ضمانًا للربح أو تنفيذًا لأوامر تداول.</div>';
    $("quoteContent").addEventListener("click",e=>{const row=e.target.closest("[data-symbol]");if(row)loadChart(m,row.dataset.symbol)});
    $("quoteContent").addEventListener("keydown",e=>{if((e.key==="Enter"||e.key===" ")&&e.target.matches("[data-symbol]")){e.preventDefault();loadChart(m,e.target.dataset.symbol)}});
    $("loadQuotes").addEventListener("click",()=>loadQuotes(m));
    $("refreshQuotes").addEventListener("click",()=>loadQuotes(m));
    $("loadSignals").addEventListener("click",()=>loadSignals(m));
    $("frames").addEventListener("click",e=>{const b=e.target.closest("[data-frame]");if(!b)return;selectedInterval=b.dataset.frame;$("frames").querySelectorAll("button").forEach(x=>x.classList.toggle("active",x===b));$("signalContent").innerHTML="";$("signalMeta").textContent="الفريم المختار: "+selectedInterval+" · اضغط فحص الفرص.";if(currentChartSymbol)loadChart(m,currentChartSymbol)});
    loadQuotes(m);
  }
  async function loadQuotes(m) {
    const out=$("quoteContent"), meta=$("quoteMeta"); if(!out)return;
    out.innerHTML='<div class="loading">جاري تحميل بيانات '+esc(m.name)+'…</div>';meta.textContent="اتصال بمصدر الأسعار";
    $("loadQuotes").disabled=true;$("refreshQuotes").disabled=true;
    try {
      const d=await getJSON("/api/market/"+encodeURIComponent(m.api)+"?limit=100");
      lastMarketItems=Array.isArray(d.items)?d.items:[];
      out.innerHTML=quoteRows(lastMarketItems);
      meta.textContent=(d.provider||m.source)+" · "+(d.delayed?"قد تكون متأخرة · ":"")+(d.updated_at?"آخر تحديث: "+timeText(d.updated_at):"البيانات حسب المصدر");
      setStatus(d.live?"بيانات متاحة":"بيانات محدودة",!!d.live);
      if(!lastMarketItems.length)out.innerHTML=empty("المصدر لم يعرض أسعارًا",d.message||"لا توجد بيانات متاحة حاليًا.");
      else {out.querySelectorAll("tbody tr").forEach((row,i)=>{const symbol=lastMarketItems[i]?.symbol;if(symbol){row.tabIndex=0;row.setAttribute("role","button");row.setAttribute("aria-label","عرض شارت "+symbol);row.dataset.symbol=symbol}});currentChartSymbol=lastMarketItems[0].symbol;loadChart(m,currentChartSymbol)}
    } catch(err) {out.innerHTML=empty("تعذر تحميل الأسعار",err.message);meta.textContent="فشل الطلب";setStatus("مصدر غير متاح",false)}
    finally {$("loadQuotes").disabled=false;$("refreshQuotes").disabled=false}
  }
  function drawCandles(items) {
    const rows=(items||[]).filter(c=>[c.open,c.high,c.low,c.close].every(v=>Number.isFinite(Number(v))&&Number(v)>0));
    if(rows.length<2)return empty("بيانات الشموع غير كافية","لم يرسم الموقع أي شموع تقديرية.");
    const W=900,H=300,pad=28,lo=Math.min(...rows.map(c=>Number(c.low))),hi=Math.max(...rows.map(c=>Number(c.high))),range=hi-lo||1;
    const y=v=>pad+(hi-Number(v))/range*(H-pad*2),step=(W-pad*2)/rows.length,bodyW=Math.max(2,Math.min(9,step*.58));
    const grid=[0,.25,.5,.75,1].map(t=>{const val=hi-range*t,yy=pad+(H-pad*2)*t;return '<line x1="'+pad+'" y1="'+yy+'" x2="'+(W-pad)+'" y2="'+yy+'" stroke="#26364d" stroke-width="1"/><text x="'+(W-pad)+'" y="'+(yy-4)+'" fill="#92a6c2" font-size="10" text-anchor="end">'+esc(price(val))+'</text>'}).join("");
    const candles=rows.map((c,i)=>{const x=pad+step*i+step/2,up=Number(c.close)>=Number(c.open),color=up?"#43d6a1":"#ff7184",top=y(Math.max(Number(c.open),Number(c.close))),bottom=y(Math.min(Number(c.open),Number(c.close))),height=Math.max(1,bottom-top);return '<line x1="'+x+'" y1="'+y(c.high)+'" x2="'+x+'" y2="'+y(c.low)+'" stroke="'+color+'" stroke-width="1.3"/><rect x="'+(x-bodyW/2)+'" y="'+top+'" width="'+bodyW+'" height="'+height+'" fill="'+color+'" rx=".5"/>'}).join("");
    return '<div style="width:100%;overflow:hidden"><svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="مخطط شموع حقيقية" style="width:100%;height:auto;display:block;background:#0a1321;border-radius:12px">'+grid+candles+'</svg></div><div class="muted" style="margin-top:8px">عدد الشموع: '+rows.length+' · المصدر الفعلي · آخر إغلاق: '+price(rows[rows.length-1].close)+'</div>';
  }
  async function loadChart(m,symbol) {
    currentChartSymbol=symbol;
    const out=$("chartContent"),meta=$("chartMeta"),badge=$("chartSymbol");if(!out)return;
    badge.textContent=symbol;out.innerHTML='<div class="loading">جاري تحميل الشموع الفعلية…</div>';meta.textContent=m.name+" · "+selectedInterval;
    try {const d=await getJSON("/api/trade-chart-data?market="+encodeURIComponent(m.api)+"&symbol="+encodeURIComponent(symbol)+"&interval="+encodeURIComponent(selectedInterval));out.innerHTML=drawCandles(d.items||[]);meta.textContent=m.source+" · "+selectedInterval+" · "+(d.items||[]).length+" شمعة"}
    catch(err){out.innerHTML=empty("الشارت غير متاح",err.message);meta.textContent="لا توجد بيانات شموع مؤكدة"}
  }
  function signalCard(x) {
    const l=x.levels||{};const side=x.direction||x.side||"غير محدد";const buy=["شراء","BUY","LONG"].includes(side);
    return '<article class="signal-card"><div class="signal-top"><b class="signal-symbol">'+esc(x.symbol||"—")+'</b><span class="tag '+(buy?"buy":"sell")+'">'+esc(side)+'</span><span class="tag">'+esc(x.interval||selectedInterval)+'</span><span class="tag">AI '+esc(x.ai_score??x.confidence??"—")+'%</span></div>'+
      '<div class="entry-line"><span>الدخول</span><strong>'+price(l.entry??x.entry)+'</strong></div><div class="levels-grid">'+
      '<div class="level stop"><small>وقف الخسارة</small><strong>'+price(l.stop_loss??x.stop_loss)+'</strong></div>'+
      '<div class="level target"><small>الهدف الأول</small><strong>'+price(l.tp1??x.tp1)+'</strong></div>'+
      '<div class="level target"><small>الهدف الثاني</small><strong>'+price(l.tp2??x.tp2)+'</strong></div>'+
      '<div class="level target"><small>الهدف الثالث</small><strong>'+price(l.tp3??x.tp3)+'</strong></div></div>'+
      '<div class="muted" style="margin-top:10px">'+esc(x.status||"إشارة فنية تجريبية · تحقق من البيانات قبل أي قرار")+'</div></article>';
  }
  async function loadSignals(m) {
    const out=$("signalContent"),meta=$("signalMeta"),button=$("loadSignals");button.disabled=true;
    out.innerHTML='<div class="loading">جاري فحص عينة محدودة من '+esc(m.name)+'…</div>';meta.textContent="فحص محدود · "+selectedInterval;
    try {
      const d=await getJSON("/api/signals/"+encodeURIComponent(m.api)+"?interval="+encodeURIComponent(selectedInterval)+"&limit=12");
      const items=Array.isArray(d.items)?d.items:[];
      meta.textContent="تم فحص "+(d.scanned??"—")+" أصل · "+items.length+" فرصة";
      out.innerHTML=items.length?items.map(signalCard).join(""):empty("لا توجد فرص مؤهلة الآن",d.message||"لن نعرض صفقة بمستويات ناقصة أو غير مرتبة.");
    } catch(err) {out.innerHTML=empty("تعذر فحص الفرص",err.message);meta.textContent="فشل الفحص"}
    finally {button.disabled=false}
  }
  async function renderResults() {
    view.innerHTML=pageHeader("نتائج الصفقات","سجل الإشارات التي رصدتها الخدمة، بدون احتساب نتائج غير مسجلة.","المتابعة")+
      '<section class="panel"><div class="panel-head"><h2>ملخص النتائج</h2><button class="button small" id="refreshResults">تحديث</button></div><div id="resultStats" class="feature-grid"></div><div id="resultTable" style="margin-top:14px" class="loading">جاري تحميل النتائج…</div></section>'+
      '<div class="notice">النتائج السابقة لا تضمن الأداء المستقبلي، وقد لا يكون السجل دائمًا إذا لم يُضبط التخزين الدائم في الخدمة.</div>';
    const load=async()=>{const out=$("resultTable");out.innerHTML='<div class="loading">تحميل السجل…</div>';try{const d=await getJSON("/api/results?limit=100");const stats=[["إجمالي السجل",d.total??0],["صفقات مغلقة",d.closed??0],["أهداف محققة",d.wins??0],["صفقات خاسرة",d.losses??0],["نسبة النجاح",d.win_rate==null?"—":d.win_rate+"%"]];$("resultStats").innerHTML=stats.map(s=>'<div class="feature-card"><small>'+esc(s[0])+'</small><strong style="font-size:22px">'+esc(s[1])+'</strong></div>').join("");const items=d.items||[];out.innerHTML=items.length?'<div class="table-wrap"><table><thead><tr><th>الأصل</th><th>السوق / الفريم</th><th>الاتجاه</th><th>الدخول</th><th>النتيجة</th><th>الأداء</th></tr></thead><tbody>'+items.map(x=>'<tr><td dir="ltr">'+esc(x.symbol||"—")+'</td><td>'+esc(x.market||"—")+' / '+esc(x.interval||"—")+'</td><td>'+esc(x.side==="BUY"?"شراء":x.side==="SELL"?"بيع":x.side||"—")+'</td><td class="ltr">'+price(x.entry)+'</td><td>'+esc(x.result||"—")+'</td><td class="'+(Number(x.pnl_pct)>=0?"positive":"negative")+'">'+(x.pnl_pct==null?"—":pct(x.pnl_pct))+'</td></tr>').join("")+'</tbody></table></div>':empty("لا توجد نتائج مسجلة",d.message||"لم يتم تسجيل نتائج بعد.")}catch(err){out.innerHTML=empty("تعذر تحميل النتائج",err.message)}};
    $("refreshResults").addEventListener("click",load);await load();
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
  async function render() {
    activateDrawer();
    if(path==="/"){renderHome();return}
    if(marketKey){renderMarketPage(marketKey);return}
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
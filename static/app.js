const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));async function get(u){const r=await fetch(u);if(!r.ok)throw Error("HTTP "+r.status);return r.json()}function fmt(n){return Number(n).toLocaleString("en-US",{maximumFractionDigits:6})}function card(x){const c=x.change>0?"up":x.change<0?"down":"neutral";return '<a class="market-box" href="/coin/'+encodeURIComponent(x.symbol)+'"><div class="market-symbol"><b>'+esc(x.symbol)+'</b><span class="'+c+'">'+(x.change>0?"+":"")+fmt(x.change)+"%</span></div><strong>"+fmt(x.price)+"</strong><small>🎯 عرض الأهداف · حجم 24س · "+fmt(x.volume/1e6)+"M</small></a>"}
async function loadHome(){try{const d=await get("/api/markets");const items=d.items||[];$("#marketCount").textContent=items.length+"+";$("#health").textContent="الاتصال يعمل";$("#markets").innerHTML=items.slice(0,6).map(card).join("")||'<div class="loading-card">لا توجد بيانات حالياً</div>';const pos=items.filter(x=>x.change>0).length,neg=items.filter(x=>x.change<0).length,vol=items.reduce((a,x)=>a+x.volume,0);$("#positiveCount").textContent=pos;$("#negativeCount").textContent=neg;$("#volumeCount").textContent=fmt(vol/1e9);loadOpportunities()}catch{$("#health").textContent="تعذر الاتصال";$("#markets").innerHTML='<div class="loading-card">تعذر تحميل بيانات السوق</div>'}}
async function loadOpportunities(){try{const d=await get("/api/opportunities");const items=(d.items||[]).slice(0,8);$("#opportunities").innerHTML=items.length?items.map(x=>'<a class="opportunity-card" href="/scanner"><div class="opp-head"><b>'+esc(x.symbol)+'</b><span class="'+(x.signal==="شراء"?"buy":x.signal.includes("ارتداد")?"watch":"neutral")+'">'+esc(x.signal)+'</span></div><strong>'+fmt(x.price)+'</strong><div class="opp-bottom"><span class="'+(x.change>=0?"up":"down")+'">'+(x.change>0?"+":"")+fmt(x.change)+'%</span><small>ثقة '+fmt(x.confidence)+'%</small></div></a>').join(""):'<div class="loading-card">لا توجد فرص مؤكدة حالياً</div>'}catch{$("#opportunities").innerHTML='<div class="loading-card">تعذر تحليل الفرص حالياً</div>'}}async function loadMarkets(){try{const d=await get("/api/markets");$("#marketTable").innerHTML=d.items.map(x=>'<a class="row" href="/coin/'+encodeURIComponent(x.symbol)+'"><b>'+esc(x.symbol)+'</b><span>'+fmt(x.price)+'</span><span class="'+(x.change>=0?"up":"down")+'">'+fmt(x.change)+"%</span><span>🎯 الأهداف</span></a>").join("")}catch{$("#marketTable").innerHTML='<div class="card">تعذر تحميل البيانات</div>'}}
async function loadMarketTrades(tf="15د"){
  const box=$("#marketTrades"), status=$("#marketTradeStatus"), tabs=$("#marketTimeframes");
  if(!box)return;
  const p=location.pathname;
  const market=p==="/spot"?"spot":p==="/futures"?"futures":p==="/contracts"?"contracts":p==="/us"?"us":p==="/saudi"?"saudi":p==="/forex"?"forex":"";
  const marketNames={spot:"سبوت",futures:"فيوتشر",contracts:"العقود",us:"السوق الأمريكي",saudi:"السوق السعودي",forex:"الفوركس والسلع"};
  if(!market)return;
  document.querySelectorAll(".market-name").forEach(x=>x.textContent=marketNames[market]||"");
  if(status)status.textContent="جاري تحليل "+tf+"...";
  box.innerHTML='<div class="loading-card">جاري استخراج صفقات '+tf+'...</div>';
  try{
    const d=await get("/api/market-trades/"+market+"?timeframe="+encodeURIComponent(tf));
    const items=d.items||[];
    box.innerHTML=items.length?items.map((x,i)=>'<article class="trade-card"><div class="trade-top"><b>'+(i<3?["👑","🥈","🥉"][i]+" ":"")+esc(x.symbol)+'</b><span>'+esc(x.timeframe)+'</span></div><div class="trade-meta-row"><span class="mini-badge ai-mini">🤖 AI '+fmt(x.confidence)+'%</span><span class="mini-badge">حركة '+fmt(x.movement)+'%</span><span class="mini-badge">RSI '+fmt(x.rsi)+'</span></div><div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div><div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div><div class="trade-line"><span>🎯 الهدف 1</span><b>'+fmt(x.tp1)+'</b></div><div class="trade-line"><span>🎯 الهدف 2</span><b>'+fmt(x.tp2)+'</b></div><div class="trade-line"><span>🎯 الهدف 3</span><b>'+fmt(x.tp3)+'</b></div><div class="trade-line stop-line"><span>🛑 وقف الخسارة</span><b>'+fmt(x.stop)+'</b></div></article>').join(""):'<div class="card empty">لا توجد صفقات مؤكدة لهذا الفريم حالياً.</div>';
    if(status)status.textContent="تم التحديث · "+items.length+" صفقة";
  }catch(e){
    if(status)status.textContent="تعذر التحليل";
    box.innerHTML='<div class="card empty">تعذر تحميل صفقات هذا الفريم حالياً.</div>';
  }
}
function setupMarketTimeframes(){
  const tabs=$("#marketTimeframes"); if(!tabs)return;
  const frames=["5د","15د","1س","4س","يومي","أسبوعي","شهري"];
  tabs.innerHTML=frames.map((x,i)=>'<button type="button" class="trade-tab '+(i===1?"active":"")+'" data-market-tf="'+x+'">'+x+'</button>').join("");
  tabs.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{
    tabs.querySelectorAll("button").forEach(x=>x.classList.remove("active"));
    b.classList.add("active"); loadMarketTrades(b.dataset.marketTf);
  }));
  loadMarketTrades("15د");
}

async function auth(form,url,msg){form?.addEventListener("submit",async e=>{e.preventDefault();const b=form.querySelector("button");b.disabled=true;$(msg).textContent="جارٍ التحقق...";try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded"},body:new URLSearchParams(new FormData(form))});const d=await r.json();if(!r.ok)throw Error(d.error||"تعذر التنفيذ");location.href="/"}catch(e){$(msg).textContent=e.message}finally{b.disabled=false}})}async function loadTrades(tf=""){const status=$("#tradeStatus"),grid=$("#tradesGrid");try{status.textContent="جاري تحليل السوق...";const d=await get("/api/trades"+(tf?"?timeframe="+encodeURIComponent(tf):""));grid.innerHTML=d.items.length?d.items.map(x=>'<article class="trade-card"><div class="trade-top"><b>'+esc(x.symbol)+'</b><span>'+esc(x.timeframe)+'</span></div><div class="trade-meta-row"><span class="mini-badge ai-mini">🤖 AI '+fmt(x.confidence??x.ai??0)+'%</span></div><div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+x.side+'</div><div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div><div class="trade-line"><span>الهدف</span><b>'+fmt(x.target)+'</b></div><div class="trade-line"><span>وقف الخسارة</span><b>'+fmt(x.stop)+'</b></div><div class="trade-meta">RSI '+x.rsi+' · '+new Date(x.time).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</div></article>').join(""):'<div class="card empty">لا توجد إشارة مؤكدة حالياً لهذا الفريم.</div>';status.textContent="تم التحديث الآن · "+d.items.length+" صفقة";}catch(e){status.textContent="تعذر تحليل الصفقات";grid.innerHTML='<div class="card empty">حاول مرة ثانية بعد قليل.</div>'}}
function setupTrades(){const tabs=$("#tradeTabs");if(!tabs)return;const frames=["الكل","5د","15د","1س","4س","يومي","أسبوعي","شهري"];tabs.innerHTML=frames.map((x,i)=>'<button type="button" class="trade-tab '+(i===0?"active":"")+'" data-tf="'+(x==="الكل"?"":x)+'">'+x+'</button>').join("");tabs.querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>{tabs.querySelectorAll("button").forEach(x=>x.classList.remove("active"));b.classList.add("active");loadTrades(b.dataset.tf)}));loadTrades()}
async function loadNews(){
  const box=$("#newsList"); if(!box)return;
  box.innerHTML='<div class="loading-card">جاري جلب الأخبار...</div>';
  try{
    const d=await get("/api/news"); const items=Array.isArray(d)?d:(d.items||[]);
    if(!items.length){box.innerHTML='<div class="loading-card">لا توجد أخبار حالياً</div>';return;}
    box.innerHTML=items.map(x=>'<article class="news-card"><small>'+esc(x.source||"موجز المضارب")+' · '+esc(x.time||"الآن")+'</small><h3>'+esc(x.title||"خبر جديد")+'</h3><p>'+esc(x.summary||"آخر مستجدات الأسواق والتحركات المالية.")+'</p></article>').join("");
  }catch(e){box.innerHTML='<div class="loading-card">تعذر جلب الأخبار حالياً — حاول التحديث مرة أخرى.</div>';}
}
async function loadScanner(){
  const grid=$("#scannerGrid"); if(!grid)return;
  const filter=$("#filter"); grid.innerHTML='<div class="loading-card">جاري فحص الأسواق...</div>';
  try{
    const d=await get("/api/opportunities"); let items=d.items||[];
    const q=(filter?.value||"").trim().toUpperCase();
    if(q) items=items.filter(x=>String(x.symbol).toUpperCase().includes(q));
    grid.innerHTML=items.length?items.map((x,i)=>'<article class="market-box"><div class="market-symbol"><b>'+(i<3?["👑","🥈","🥉"][i]:"")+' '+esc(x.symbol)+'</b><span class="'+(x.change>=0?"up":"down")+'">'+(x.change>0?"+":"")+fmt(x.change)+'%</span></div><strong>'+fmt(x.price)+'</strong><small>'+esc(x.signal)+' · 🤖 AI '+fmt(x.confidence)+'%</small><a class="btn primary" href="/trades">عرض الصفقات</a></article>').join(""):'<div class="loading-card">لا توجد فرص حالياً</div>';
  }catch(e){grid.innerHTML='<div class="loading-card">تعذر تشغيل الماسح حالياً</div>'}
}
function setupBreakingNews(){
  if(document.querySelector(".breaking-bar"))return;
  const header=document.querySelector("header"); if(!header || location.pathname!=="/")return;
  const bar=document.createElement("div"); bar.className="breaking-bar";
  bar.innerHTML='<div class="breaking-label">🔴 عاجل</div><div class="breaking-track"><div class="breaking-content">جاري جلب آخر أخبار الأسواق...</div></div>';
  header.insertAdjacentElement("afterend",bar);
  get("/api/news").then(d=>{
    const items=Array.isArray(d)?d:(d.items||[]);
    const titles=items.slice(0,12).map(x=>String(x.title||"خبر جديد").trim()).filter(Boolean);
    bar.querySelector(".breaking-content").textContent=titles.length?titles.join("   •   "):"آخر أخبار الأسواق والتحركات المالية أولاً بأول";
  }).catch(()=>{bar.querySelector(".breaking-content").textContent="آخر أخبار الأسواق والتحركات المالية أولاً بأول";});
}
function setup(){setupBreakingNews();const menu=$("#menu"),drawer=$("#drawer"),backdrop=$("#drawerBackdrop");
function closeDrawer(e){if(e)e.stopPropagation();drawer?.classList.remove("open");drawer?.setAttribute("aria-hidden","true");menu?.setAttribute("aria-expanded","false")}
function toggleDrawer(e){if(e){e.preventDefault();e.stopPropagation()}if(!drawer||!menu)return;const open=!drawer.classList.contains("open");drawer.classList.toggle("open",open);drawer.setAttribute("aria-hidden",String(!open));menu.setAttribute("aria-expanded",String(open))}
if(menu){let locked=false;const tap=e=>{if(locked)return;locked=true;toggleDrawer(e);setTimeout(()=>locked=false,350)};if(window.PointerEvent)menu.addEventListener("pointerup",tap,{passive:false});menu.addEventListener("click",tap)}
backdrop?.addEventListener("click",closeDrawer);
drawer?.querySelectorAll("a").forEach(a=>a.addEventListener("click",closeDrawer));
$("#theme")?.addEventListener("click",()=>{document.body.classList.toggle("light");localStorage.theme=document.body.classList.contains("light")?"light":"dark"});if(localStorage.theme==="light")document.body.classList.add("light");if($("#opportunities"))loadHome();setupTrades();if($("#marketTrades")){setupMarketTimeframes();loadMarketTrades("15د");}if($("#coinTargets"))loadCoin();if($("#newsList"))loadNews();if($("#scannerGrid")){loadScanner();$("#refresh")?.addEventListener("click",loadScanner);$("#filter")?.addEventListener("input",loadScanner);}auth($("#loginForm"),"/api/login","#loginMsg");auth($("#registerForm"),"/api/register","#registerMsg")}document.addEventListener("DOMContentLoaded",setup);
async function loadCoin(){
  const title=$("#coinTitle"), summary=$("#coinSummary"), grid=$("#coinTargets"), status=$("#coinStatus");
  if(!grid)return;
  const symbol=decodeURIComponent(location.pathname.split("/").pop()||"").toUpperCase();
  try{
    const d=await get("/api/coin/"+encodeURIComponent(symbol));
    title.textContent=d.asset.symbol;
    summary.innerHTML='<div class="market-symbol"><b>'+esc(d.asset.symbol)+'</b><span class="'+(d.asset.change>=0?"up":"down")+'">'+(d.asset.change>0?"+":"")+fmt(d.asset.change)+'%</span></div><strong class="coin-price">'+fmt(d.asset.price)+'</strong><small>حجم 24س · '+fmt(d.asset.volume/1e6)+'M</small>';
    grid.innerHTML=d.signals.length?d.signals.map(x=>'<article class="trade-card"><div class="trade-top"><b>'+esc(x.timeframe)+'</b><span>🤖 AI '+fmt(x.confidence)+'%</span></div><div class="trade-side '+(x.side==="شراء"?"buy":"sell")+'">'+esc(x.side)+'</div><div class="trade-line"><span>الدخول</span><b>'+fmt(x.entry)+'</b></div><div class="trade-line"><span>🎯 الهدف</span><b>'+fmt(x.target)+'</b></div><div class="trade-line"><span>🛑 وقف الخسارة</span><b>'+fmt(x.stop)+'</b></div><div class="trade-meta">RSI '+x.rsi+'</div></article>').join(""):'<div class="card empty">لا توجد إشارة مؤكدة حالياً، لكن بيانات العملة متاحة.</div>';
    status.textContent="تم التحليل على جميع الفريمات";
  }catch(e){title.textContent=symbol;summary.innerHTML='<div class="loading-card">تعذر تحميل العملة</div>';grid.innerHTML='<div class="card empty">تأكد من رمز العملة وحاول مرة ثانية.</div>'}
}

async function setupAssetSearch(){
  const input=$("#assetSearch"), btn=$("#assetSearchBtn"), clear=$("#assetSearchClear"), box=$("#assetSearchResults");
  if(!input||!box)return;
  let timer;
  function render(items,q){
    if(!q){box.innerHTML="";box.classList.remove("show");return}
    box.innerHTML=items.length?items.slice(0,12).map(x=>{
      const label=x.market==="spot"?"🟢 سبوت":x.market==="futures"?"🔴 فيوتشر":x.market==="us"?"🇺🇸 أمريكي":x.market==="saudi"?"🇸🇦 سعودي":"💱 فوركس و سلع";
      return '<a class="search-result-item" href="/asset/'+encodeURIComponent(x.market)+'/'+encodeURIComponent(x.symbol)+'"><span class="search-result-icon">'+label.split(" ")[0]+'</span><span class="search-result-main"><b>'+esc(x.symbol)+'</b><small>'+esc(x.name||"")+'</small></span><em>'+esc(label)+'</em></a>';
    }).join(""):'<div class="search-empty">ما لقيت أصل بهذا الاسم</div>';
    box.classList.add("show");
  }
  async function search(){
    const q=input.value.trim();
    if(!q){render([],q);return}
    box.innerHTML='<div class="search-empty">جاري البحث…</div>';box.classList.add("show");
    try{
      const d=await get("/api/asset-search?q="+encodeURIComponent(q));
      render(d.items||[],q);
    }catch{box.innerHTML='<div class="search-empty">تعذر البحث حالياً — جرّب مرة ثانية</div>';box.classList.add("show")}
  }
  input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(search,180)});
  btn?.addEventListener("click",search);
  clear?.addEventListener("click",()=>{input.value="";render([],"");input.focus()});
  input.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();search()}});
  document.addEventListener("click",e=>{if(!e.target.closest(".asset-search"))box.classList.remove("show")});
}

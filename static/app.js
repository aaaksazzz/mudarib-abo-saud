const TF=["ALL","15m","30m","1h","4h","1d","1w","1M"];
const UA=navigator.userAgent||"";
const IS_OPERA=/OPR\//i.test(UA)||/Opera/i.test(UA);
const IS_FIREFOX=/Firefox\//i.test(UA);
const IS_SAFARI=/Safari\//i.test(UA)&&!/Chrome\//i.test(UA)&&!/Chromium\//i.test(UA);
const IS_EDGE=/Edg\//i.test(UA);
if(IS_OPERA)document.documentElement.classList.add("operaBrowser");
if(IS_FIREFOX)document.documentElement.classList.add("firefoxBrowser");
if(IS_SAFARI)document.documentElement.classList.add("safariBrowser");
if(IS_EDGE)document.documentElement.classList.add("edgeBrowser");
document.documentElement.style.setProperty("--vh",window.innerHeight+"px");
let _vhTimer=0;
window.addEventListener("resize",()=>{clearTimeout(_vhTimer);_vhTimer=setTimeout(()=>document.documentElement.style.setProperty("--vh",window.innerHeight+"px"),120)},{passive:true});

const MK=[["ALL","الرئيسية"],["crypto_spot","₿ سبوت"],["crypto_futures","↕ فيوتشر"],["contracts","▣ العقود"],["us","🇺🇸 الأسهم الأمريكية"],["us_options","◈ الخيارات الأمريكية"],["saudi","🇸🇦 السوق السعودي"],["forex","◌ الفوركس والذهب"]];
let tf="15m",mk="ALL",data=[];
const marketTF={crypto_spot:"15m",crypto_futures:"15m",contracts:"15m",us:"15m",us_options:"15m",saudi:"15m",forex:"15m"};\nconst marketTF={crypto_spot:"15m",crypto_futures:"15m",contracts:"15m",us:"15m",us_options:"15m",saudi:"15m",forex:"15m"};
const $=s=>document.querySelector(s);
function go(id){
 const marketId=id&&id.startsWith("market_")?id.slice(7):null;
 document.querySelectorAll(".view").forEach(x=>x.classList.add("hidden"));
 const el=document.getElementById(marketId?"markets":id);
 if(el)el.classList.remove("hidden");
 const ticker=document.querySelector(".ticker");if(ticker)ticker.style.display=id==="markets"?"flex":"none";
 if(id==="signals")renderSignals();if(id==="trades")trades();if(id==="news")loadNews();if(id==="blog")loadBlog();if(id==="plans")loadPlans();if(id==="support")loadTickets();if(id==="legal")loadLegal();
 if(marketId){setTimeout(()=>document.getElementById("market_"+marketId)?.scrollIntoView({behavior:"smooth",block:"start"}),40);}
 else window.scrollTo(0,0);
}
function n(x){return x==null?"—":Number(x).toLocaleString("en-US",{maximumFractionDigits:8})}
function empty(t="لا توجد فرصة مطابقة الآن."){return '<div class="empty">'+t+"</div>"}
async function apiJSON(url,options={}){const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),15000);try{const r=await fetch(url,{...options,cache:"no-store",signal:ctl.signal});if(!r.ok)throw new Error("HTTP "+r.status);return await r.json()}finally{clearTimeout(timer)}}
async function scan(){
 try{
  const j=await apiJSON("/api/signals");
  data=Array.isArray(j.items)?j.items:[];
  render();
  renderSignals();
  const st=await apiJSON("/api/settings");
  if($("#mode"))$("#mode").textContent=(st.mode||"PAPER SAFE")+(st.execution_ready?" READY":"");
 }catch(e){
  console.error("scan",e);
  document.querySelectorAll(".marketPageTrades").forEach(box=>box.innerHTML=empty("تعذر جلب بيانات السوق حاليًا — أعد الفحص بعد لحظات."));
  if($("#signalList"))$("#signalList").innerHTML=empty("تعذر جلب الإشارات حاليًا.");
 }
}
function card(x){
 const buy=x.side==="BUY"||x.side==="LONG";
 const rate=x.success_rate??x.confidence??"—";
 const verified=x.success_rate_type==="verified_closed_trades" && Number(x.historical_trades||0)>=5;
 const win=verified?Number(x.historical_win_rate||0):null;
 const loss=verified?Number(x.historical_loss_rate||0):null;
 const market=(MK.find(m=>m[0]===x.market)||["",x.market_name||"السوق"])[1];
 const medal=x.medal||"•",rank=x.rank||"—",tag=x.quality_tag||"PRO";
 const ir=Array.isArray(x.institutional_reasons)?x.institutional_reasons.slice(0,5):[]; const iscore=x.institutional_score!=null?Number(x.institutional_score):null;
 return '<article class="card tradeCard proTradeCard"><div class="tradeRank"><b>'+medal+' #'+rank+'</b><span class="qualityTag">'+tag+'</span><span class="marketTag">'+market+'</span><span>'+x.tf+'</span><strong class="'+(buy?"sideBuy":"sideSell")+'">'+(buy?"شراء":"بيع")+'</strong></div><div class="tradeSymbol"><b>'+x.symbol+'</b><small>'+(x.strategy||"استراتيجية الفريم")+'</small></div><div class="qualityLine"><div><strong>'+rate+'%</strong><small>'+(verified?"نسبة نجاح موثقة":"تقدير النموذج")+'</small></div><div><strong>'+(verified?win+"%":"—")+'</strong><small>ربح</small></div><div><strong>'+(verified?loss+"%":"—")+'</strong><small>خسارة</small></div><div><strong>'+n(x.quality_score||rate)+'</strong><small>الجودة</small></div></div><div class="proConfluence"><b>GLOBAL PRO</b>'+(iscore!=null?'<span>تحليل مؤسسي '+n(iscore)+'/100</span>':'')+(ir.length?'<small>'+ir.join(' · ')+'</small>':'')+'</div><div class="prices"><div>الدخول<strong>'+n(x.entry)+'</strong></div><div>الهدف 1<strong>'+n(x.tp1)+'</strong></div><div>الهدف 2<strong>'+n(x.tp2)+'</strong></div><div>الهدف 3<strong>'+n(x.tp3)+'</strong></div><div class="sl">الوقف<strong>'+n(x.sl)+'</strong></div></div><div class="tradeFooter"><span>RR '+n(x.rr)+'</span><span>'+(x.reason||"إعداد فني مطابق للشروط")+'</span></div></article>';
}
function renderSignals(){if($("#signalList")){$("#signalList").innerHTML=data.slice(0,60).map(card).join("")||empty();}}
function render(){
 const ids=["crypto_spot","crypto_futures","contracts","us","us_options","saudi","forex"];
 ids.forEach(renderMarketPage);
}
function renderStats(a){const el=$("#stats");if(!el)return;const strong=a.filter(x=>Number(x.quality_score||0)>=85).length;const buys=a.filter(x=>x.side==="BUY"||x.side==="LONG").length;const sells=a.filter(x=>x.side==="SELL"||x.side==="SHORT").length;const avg=a.length?Math.round(a.reduce((q,x)=>q+Number(x.quality_score||x.success_rate||x.confidence||0),0)/a.length):0;el.innerHTML="<div><b>"+a.length+"</b><small>فرص مطابقة</small></div><div><b>"+strong+"</b><small>جودة 85%+</small></div><div><b>"+buys+" / "+sells+"</b><small>شراء / بيع</small></div><div><b>"+avg+"%</b><small>متوسط الجودة</small></div>"}
function renderMarketPage(id){
 const navEl=$("#tf_"+id),box=$("#marketTrades_"+id); if(!navEl||!box)return;
 const current=marketTF[id]||"15m";
 navEl.innerHTML=TF.filter(x=>x!=="ALL").map(x=>'<button class="'+(current===x?"on":"")+'" data-market-tf="'+id+'" data-tf="'+x+'">'+x+'</button>').join("");
 navEl.querySelectorAll("[data-market-tf]").forEach(btn=>btn.addEventListener("click",()=>setMarketTF(btn.dataset.marketTf,btn.dataset.tf)));
 let a=data.filter(x=>x.market===id&&(current==="ALL"||x.tf===current));
 a.sort((x,y)=>Number(y.quality_score??y.success_rate??y.confidence??0)-Number(x.quality_score??x.success_rate??x.confidence??0));
 box.innerHTML='<div class="marketPageHead"><div><b>'+((MK.find(x=>x[0]===id)||["","السوق"])[1])+'</b><small>'+a.length+' فرصة · فريم '+current+'</small></div><button onclick="scan()">↻ تحديث</button></div><div class="marketPageGrid">'+(a.slice(0,50).map(card).join("")||empty("لا توجد صفقة مطابقة لهذا الفريم حاليًا."))+'</div><div class="marketAutoTrades" id="marketAuto_'+id+'"><h3>الصفقات التلقائية المفتوحة</h3><div>جاري التحميل...</div></div>';
 loadMarketTradesPage(id);
}
async function loadMarketTradesPage(id){try{const a=await apiJSON("/api/trades?market="+encodeURIComponent(id));const box=$("#marketAuto_"+id);if(!box)return;const open=(a||[]).filter(x=>x.status==="OPEN");box.querySelector("div").innerHTML=open.length?open.map(x=>'<div class="autoTradeRow"><b>'+x.symbol+'</b><span>'+x.tf+'</span><span class="'+(x.side==="BUY"?"autoBuy":"autoSell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span><span>دخول '+n(x.entry)+'</span><span>هدف '+n(x.tp1)+'</span><span>وقف '+n(x.sl)+'</span><i>تلقائي</i></div>').join(""):'<div class="autoNone">ما فيه صفقة مفتوحة تلقائيًا حاليًا.</div>';}catch(e){}}
function setMarketTF(id,x){marketTF[id]=x;mk=id;tf=x;renderMarketPage(id);document.getElementById("marketSection_"+id)?.scrollIntoView({behavior:"smooth",block:"start"});}
async function trades(){
 try{
  const [a,s]=await Promise.all([fetch("/api/trades",{cache:"no-store"}).then(r=>r.json()),fetch("/api/stats",{cache:"no-store"}).then(r=>r.json())]);
  const target=$("#tradeStats");if(target)target.innerHTML="<div><b>"+s.total+"</b><small>إجمالي محفوظ</small></div><div><b>"+s.open+"</b><small>مفتوحة</small></div><div><b>"+s.closed+"</b><small>مغلقة</small></div><div><b>"+s.win_rate+"%</b><small>ربح فعلي</small></div><div><b>"+s.loss_rate+"%</b><small>خسارة فعلية</small></div>";
  if($("#tradesList"))$("#tradesList").innerHTML=(a||[]).map((x,i)=>'<article class="savedTradeCard"><div class="savedTop"><b>'+(x.medal||"•")+' #'+(x.display_rank||i+1)+' '+x.symbol+'</b><span class="qualityTag">'+(x.quality_tag||"PRO")+'</span><span>'+x.tf+'</span><strong class="'+(x.side==="BUY"?"autoBuy":"autoSell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</strong></div><div class="savedMeta"><span>الجودة <b>'+n(x.quality_score)+'</b>%</span><span>الدخول <b>'+n(x.entry)+'</b></span><span>الهدف <b>'+n(x.tp1)+'</b></span><span>الوقف <b>'+n(x.sl)+'</b></span><span>'+x.status+'</span></div></article>').join("")||empty("لا توجد صفقات محفوظة.");
 }catch(e){if($("#tradesList"))$("#tradesList").innerHTML=empty("تعذر تحميل الصفقات.");}
}
async function loadNews(){try{const a=await(await fetch("/api/news",{cache:"no-store"})).json();$("#newsList").innerHTML=(a||[]).map(x=>'<article class="card"><span class="eyebrow">'+(x.source||"NEWS")+'</span><h3>'+x.title+'</h3><p>'+(x.body||"")+"</p></article>").join("")||empty("لا توجد أخبار محفوظة.");}catch(e){$("#newsList").innerHTML=empty()}}
async function loadBlog(){try{const a=await(await fetch("/api/articles",{cache:"no-store"})).json();$("#blogList").innerHTML=(a||[]).map(x=>'<article class="card"><span class="eyebrow">RESEARCH</span><h3>'+x.title+'</h3><p>'+(x.body||"")+"</p></article>").join("")||empty("لا توجد مقالات منشورة.");}catch(e){$("#blogList").innerHTML=empty()}}
async function loadPlans(){try{const a=await(await fetch("/api/plans",{cache:"no-store"})).json();$("#plansList").innerHTML=(a||[]).map(x=>'<article class="card"><span class="eyebrow">PLAN</span><h3>'+x.name+'</h3><div class="conf">'+n(x.price)+' <small>ريال</small></div><p>'+x.duration_days+" يوم</p></article>").join("")||empty("لم تتم إضافة الباقات بعد.");}catch(e){$("#plansList").innerHTML=empty()}}
async function createTicket(){const token=localStorage.getItem("token");if(!token)return alert("سجل الدخول أولاً");const subject=$("#ticketSubject").value,body=$("#ticketBody").value;const r=await fetch("/api/support/tickets?token="+encodeURIComponent(token),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({subject,body})});const x=await r.json();alert(x.ok?"تم إرسال التذكرة":"تعذر إرسال التذكرة")}
async function loadTickets(){const token=localStorage.getItem("token");if(!token){if($("#tickets"))$("#tickets").innerHTML=empty("سجل الدخول لمتابعة تذاكر الدعم.");return}const a=await(await fetch("/api/support/tickets?token="+encodeURIComponent(token))).json();$("#tickets").innerHTML=(a||[]).map(x=>'<div class="card"><b>#'+x.id+" "+x.subject+'</b><p>'+x.body+'</p><small>'+x.status+"</small></div>").join("")||empty("لا توجد تذاكر.")}
async function loadLegal(){try{const x=await(await fetch("/api/legal")).json();$("#legalBox").innerHTML="<h3>إخلاء المسؤولية</h3><p>"+x.risk_disclaimer+"</p><h3>الاسترجاع</h3><p>"+x.refund_policy+"</p><h3>الشروط</h3><p>"+x.terms+"</p>"}catch(e){$("#legalBox").textContent="تعذر تحميل الشروط."}}
async function adminLoad(){const t=$("#adminToken").value;const [a,b]=await Promise.all([fetch("/api/admin/overview?token="+encodeURIComponent(t)),fetch("/api/admin/analytics?token="+encodeURIComponent(t))]);const x=await a.json(),y=await b.json();$("#adminBox").innerHTML='<div class="stats"><div><b>'+x.users+'</b><small>المستخدمون</small></div><div><b>'+y.active_subscriptions+'</b><small>اشتراكات نشطة</small></div><div><b>'+y.mrr+'</b><small>MRR</small></div><div><b>'+y.win_rate+'%</b><small>Win Rate</small></div></div>'}
function toggleMenu(){$("#sideMenu").classList.toggle("open");$("#menuOverlay").classList.toggle("open")}
function closeMenu(){$("#sideMenu").classList.remove("open");$("#menuOverlay").classList.remove("open")}
function menuGo(id){closeMenu();go(id)}
function menuMarket(id){mk=id;closeMenu();if(id==="ALL"){go("markets");scan();return}go("market_"+id);scan();}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu()});
document.addEventListener("click",e=>{const a=e.target.closest&&e.target.closest("a");if(a&&a.getAttribute("href")&&a.getAttribute("href").startsWith("#"))closeMenu()},{passive:true});
window.addEventListener("orientationchange",()=>setTimeout(()=>window.dispatchEvent(new Event("resize")),250),{passive:true});
go("markets");render();scan();setInterval(()=>{scan();if(!$("#trades").classList.contains("hidden"))trades();},180000);
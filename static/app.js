const TF=["ALL","15m","30m","1h","4h","1d","1w","1M"];
const MK=[["ALL","كل الأسواق"],["crypto_spot","سبوت"],["crypto_futures","فيوتشر"],["us","الأسهم الأمريكية"],["us_options","الخيارات الأمريكية"],["saudi","السعودي"],["forex","الفوركس + الذهب"]];
let tf="ALL",mk="ALL",data=[];
const $=s=>document.querySelector(s);
function go(id){document.querySelectorAll(".view").forEach(x=>x.classList.add("hidden"));const el=document.getElementById(id);if(el)el.classList.remove("hidden");const ticker=document.querySelector(".ticker");if(ticker)ticker.style.display=id==="markets"?"flex":"none";window.scrollTo(0,0);if(id==="signals")renderSignals();if(id==="trades")trades();if(id==="news")loadNews();if(id==="blog")loadBlog();if(id==="plans")loadPlans();if(id==="support")loadTickets();if(id==="legal")loadLegal();}
function nav(){if(!$("#marketNav"))return;$("#marketNav").innerHTML=MK.map(x=>'<button class="'+(mk===x[0]?"on":"")+'" onclick="setMK(\''+x[0]+'\')">'+x[1]+"</button>").join("");$("#filters").innerHTML=TF.map(x=>'<button class="'+(tf===x?"on":"")+'" onclick="setTF(\''+x+'\')">'+(x==="ALL"?"كل الفريمات":x)+"</button>").join("");renderMarketTradeAction();}
function setMK(x){mk=x;tf="ALL";nav();scan()}
function setTF(x){tf=x;nav();render()}
function n(x){return x==null?"—":Number(x).toLocaleString("en-US",{maximumFractionDigits:8})}
function empty(t="لا توجد فرصة مطابقة الآن."){return '<div class="empty">'+t+"</div>"}
async function apiJSON(url,options={}){const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),15000);try{const r=await fetch(url,{...options,cache:"no-store",signal:ctl.signal});if(!r.ok)throw new Error("HTTP "+r.status);return await r.json()}finally{clearTimeout(timer)}}
async function scan(){
 if($("#status"))$("#status").innerHTML='<i></i> SCANNING';
 try{
  const u=mk==="ALL"?"/api/signals":"/api/signals?market="+encodeURIComponent(mk);
  const j=await apiJSON(u);data=Array.isArray(j.items)?j.items:[];
  render();renderSignals();
  const s=await apiJSON("/api/settings");
  if($("#mode"))$("#mode").textContent=(s.mode||"PAPER SAFE")+(s.execution_ready?" READY":"");
 }catch(e){console.error("scan",e);if($("#cards"))$("#cards").innerHTML=empty("تعذر جلب بيانات السوق حاليًا — أعد الفحص بعد لحظات.");if($("#signalList"))$("#signalList").innerHTML=empty("تعذر جلب الإشارات حاليًا.");}
 if($("#status"))$("#status").innerHTML='<i></i> LIVE';
}
function card(x){
 const buy=x.side==="BUY"||x.side==="LONG";
 const rate=x.success_rate??x.confidence??"—";
 return '<article class="card tradeCard"><div class="top"><b>'+x.symbol+'</b><span>'+((x.market_name)||x.market||"السوق")+'</span><span>'+x.tf+'</span><strong class="'+(buy?"sideBuy":"sideSell")+'">'+(buy?"شراء":"بيع")+'</strong></div><div class="conf">'+rate+'% <small>نسبة نجاح تقديرية</small></div><div class="metrics"><span>'+(x.strategy||"استراتيجية مستقلة")+'</span><span>R:R '+(x.rr??"—")+'</span><span>ترتيب '+(x.success_rate_rank??"—")+'</span></div><div class="prices"><div>الدخول<strong>'+n(x.entry)+'</strong></div><div>الهدف 1<strong>'+n(x.tp1)+'</strong></div><div>الهدف 2<strong>'+n(x.tp2)+'</strong></div><div>الهدف 3<strong>'+n(x.tp3)+'</strong></div><div class="sl">الوقف<strong>'+n(x.sl)+'</strong></div></div><small class="reason">'+(x.reason||"إعداد فني مطابق للشروط")+'</small></article>';
}
function render(){if(!$("#cards"))return;const a=tf==="ALL"?data:data.filter(x=>x.tf===tf);a.sort((x,y)=>Number(y.success_rate??y.confidence??0)-Number(x.success_rate??x.confidence??0));a.forEach((x,i)=>x.success_rate_rank=i+1);$("#cards").innerHTML=a.slice(0,30).map(card).join("")||empty("لا توجد فرص مطابقة الآن.");renderStats(a);if($("#marketUpdated"))$("#marketUpdated").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})}
function renderStats(a){const el=$("#stats");if(!el)return;const strong=a.filter(x=>Number(x.success_rate??x.confidence??0)>=90).length;const buys=a.filter(x=>x.side==="BUY"||x.side==="LONG").length;const sells=a.filter(x=>x.side==="SELL"||x.side==="SHORT").length;const avg=a.length?Math.round(a.reduce((q,x)=>q+Number(x.success_rate??x.confidence??0),0)/a.length):0;el.innerHTML="<div><b>"+a.length+"</b><small>فرص مطابقة</small></div><div><b>"+strong+"</b><small>ثقة 90%+</small></div><div><b>"+buys+" / "+sells+"</b><small>شراء / بيع</small></div><div><b>"+avg+"%</b><small>متوسط التقدير</small></div>"}
function renderSignals(){if($("#signalList")){const a=data.slice().sort((x,y)=>Number(y.success_rate??y.confidence??0)-Number(x.success_rate??x.confidence??0));a.forEach((x,i)=>x.success_rate_rank=i+1);$("#signalList").innerHTML=a.slice(0,60).map(card).join("")||empty()}}
function renderMarketTradeAction(){const el=$("#marketTradeAction");if(!el)return;el.innerHTML=mk==="ALL"?'<div class="marketActionHint">اختر سوقًا لعرض خيار إطلاق الصفقة.</div>':'<button class="marketLaunch" onclick="launchTopMarketTrade()">▶ إطلاق أفضل فرصة في '+(MK.find(x=>x[0]===mk)?.[1]||"السوق")+"</button>"}
async function launchTopMarketTrade(){
 if(mk==="ALL")return alert("اختر سوق أولاً.");
 const candidates=data.filter(x=>x.market===mk&&x.state==="ENTERED"&&Number(x.confidence)>=90);
 if(!candidates.length)return alert("لا توجد إشارة مؤهلة الآن لهذا السوق.");
 const x=candidates.sort((a,b)=>Number(b.confidence)-Number(a.confidence))[0];
 const r=await fetch("/api/trades/launch",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({market:x.market,symbol:x.symbol,tf:x.tf})});
 const j=await r.json();alert(j.ok?"تم إطلاق الصفقة الورقية #"+j.trade_id:"تعذر إطلاق الصفقة: "+(j.error||"خطأ"));if(j.ok)trades();
}
async function trades(){
 try{
  const [a,s]=await Promise.all([fetch("/api/trades",{cache:"no-store"}).then(r=>r.json()),fetch("/api/stats",{cache:"no-store"}).then(r=>r.json())]);
  const target=$("#tradeStats");if(target)target.innerHTML='<div><b>'+s.total+'</b><small>إجمالي الصفقات</small></div><div><b>'+s.open+'</b><small>مفتوحة</small></div><div><b>'+s.closed+'</b><small>مغلقة</small></div><div><b>'+s.pnl+'</b><small>PnL</small></div>';
  if($("#tradesList"))$("#tradesList").innerHTML=(a||[]).map(x=>'<div class="row"><b>'+x.symbol+'</b><span>'+x.tf+'</span><span>'+x.side+'</span><span>'+x.status+'</span></div>').join("")||empty("لا توجد صفقات محفوظة.");
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
function menuMarket(id){mk=id;tf="ALL";closeMenu();go("markets");nav();scan()}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeMenu()});
nav();render();scan();setInterval(()=>{scan();if(!$("#trades").classList.contains("hidden"))trades()},180000);
"use strict";
const $=id=>document.getElementById(id),qsa=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const n=(v,d=6)=>{let x=Number(v);return Number.isFinite(x)?x.toLocaleString("en-US",{maximumFractionDigits:d}):"-"};
const pct=v=>{let x=Number(v);return Number.isFinite(x)?(x>=0?"+":"")+x.toFixed(2)+"%":"-"};
const cls=s=>{s=String(s||"").toLowerCase();return s.includes("شراء")||s.includes("buy")?"buy":s.includes("بيع")||s.includes("sell")?"sell":"neutral"};
async function api(u,o={}){let r=await fetch(u,{...o,credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json",...(o.headers||{})}}),d={};try{d=await r.json()}catch{}if(!r.ok||d.ok===false)throw Error(d.message||("HTTP "+r.status));return d}
function rows(d){return d?.results||d?.signals||d?.items||d?.data?.results||d?.data?.signals||[]}
function v(r,...keys){for(const k of keys)if(r[k]!==undefined&&r[k]!==null)return r[k];return null}
function card(r){
 let s=v(r,"signal","direction")||"حيادي",price=v(r,"price","close","last"),entry=v(r,"entry","entryPrice")||price,tp=v(r,"tp1","target","takeProfit","tp"),sl=v(r,"sl","stop","stopLoss"),conf=v(r,"confidence","score"),market=v(r,"market")||"";
 let icon=cls(s)==="buy"?"↗":cls(s)==="sell"?"↘":"•";
 return '<article class="trade-card premium-card"><div class="trade-head"><div><span class="trade-live">● AI LIVE</span><div class="symbol">'+esc(v(r,"symbol","name")||"-")+'</div><div class="market-tag">'+esc(market)+" · "+esc(v(r,"interval")||"")+'</div></div><div class="signal-box '+cls(s)+'"><span>'+icon+'</span><b>'+esc(s)+'</b></div></div><div class="trade-price"><span>السعر الحالي</span><strong>'+n(price)+'</strong></div><div class="trade-levels"><div class="trade-level entry"><span>الدخول</span><b>'+n(entry)+'</b></div><div class="trade-level tp"><span>الهدف</span><b>'+n(tp)+'</b></div><div class="trade-level sl"><span>الوقف</span><b>'+n(sl)+'</b></div></div><div class="trade-footer"><span>🤖 ثقة AI <b>'+n(conf,1)+'%</b></span><span>⚖️ R:R 1:2</span><span>⏱ '+esc(v(r,"interval")||"-")+'</span></div></article>'
}
function render(id,a){let e=$(id);if(!e)return;e.innerHTML=a.length?a.map(card).join(""):'<div class="empty">لا توجد صفقات حالياً.</div>'}
async function load(id,urls,status){let e=$(id),s=$(status);if(e)e.innerHTML='<div class="empty">⏳ جاري التحليل...</div>';for(const u of urls)try{let d=await api(u),a=rows(d);if(a.length||d.ok!==false){render(id,a.slice(0,60));if(s)s.textContent="تم التحديث";return}}catch{}if(e)e.innerHTML='<div class="empty">تعذر تحميل البيانات حالياً.</div>';if(s)s.textContent="تعذر الاتصال بالمصدر"}
function nav(){let p=document.body.dataset.page;qsa("[data-section]").forEach(a=>a.classList.toggle("active",a.dataset.section===p));$("menuBtn")?.addEventListener("click",()=>$("sidebar")?.classList.toggle("open"));$("themeBtn")?.addEventListener("click",()=>{document.body.classList.toggle("light");localStorage.setItem("theme",document.body.classList.contains("light")?"light":"dark")});if(localStorage.getItem("theme")==="light")document.body.classList.add("light")}
async function auth(){let b=$("userBadge");if(!b)return;try{let d=await api("/api/auth/me");b.innerHTML=d.user?'<span>'+esc(d.user)+'</span> <button id="logoutBtn" class="btn">خروج</button>':'<a class="btn" href="/login">دخول</a>';$("logoutBtn")?.addEventListener("click",async()=>{await api("/api/auth/logout",{method:"POST"});location.reload()})}catch{}}
async function marketEndpoint(m,i,l=60){return "/api/ai/signals?market="+encodeURIComponent(m)+"&interval="+encodeURIComponent(i)+"&limit="+l}
function renderFiltered(a){
 const dir=$("filterDirection")?.value||"all", min=Number($("filterConfidence")?.value||0), sort=$("filterSort")?.value||"confidence";
 a=a.filter(r=>Number(v(r,"confidence","score")||0)>=min);
 if(dir==="buy")a=a.filter(r=>cls(v(r,"signal","direction"))==="buy");
 if(dir==="sell")a=a.filter(r=>cls(v(r,"signal","direction"))==="sell");
 a.sort((x,y)=>Number(v(y,sort==="score"?"score":"confidence")||0)-Number(v(x,sort==="score"?"score":"confidence")||0));
 render("scannerBody",a.slice(0,80));
}
async function scannerPro(){
 if(!$("scannerBody"))return;
 const m=$("filterMarket")?.value||"crypto",i=$("filterInterval")?.value||"15m";
 $("scannerStatus").textContent="🤖 المحرك يحلل السوق...";
 try{
   let all=[];
   if(m==="all"){
     const jobs=[["crypto",i],["futures",i],["saudi",i],["usmarket",i],["forex",i]];
     const ds=await Promise.all(jobs.map(([x,y])=>api(marketEndpoint(x,y,20)).catch(()=>({results:[]}))));
     ds.forEach(d=>all.push(...rows(d)));
   }else all=rows(await api(marketEndpoint(m,i,80)));
   renderFiltered(all);
   $("scannerStatus").textContent="● تم التحديث · "+all.length+" فرصة تم فحصها";
 }catch(e){$("scannerStatus").textContent="تعذر تحديث البيانات";render("scannerBody",[])}
}
function setupScanner(){
 if(!$("scannerBody"))return;
 const params=new URLSearchParams(location.search),m=params.get("market");
 if(m&&$("filterMarket"))$("filterMarket").value=m;
 ["filterMarket","filterInterval","filterDirection","filterConfidence","filterSort"].forEach(id=>$(id)?.addEventListener("change",scannerPro));
 qsa(".filter-chip").forEach(b=>b.addEventListener("click",()=>{qsa(".filter-chip").forEach(x=>x.classList.remove("active"));b.classList.add("active");if(b.dataset.fast!=="all")$("filterDirection").value=b.dataset.fast;else $("filterDirection").value="all";scannerPro()}));
 $("scanBtn")?.addEventListener("click",scannerPro);
 scannerPro();
 setInterval(scannerPro,30000);
}
async function homePro(){
 if(!$("homeTrades"))return;
 try{
   const d=await api("/api/ai/feed"),a=rows(d);
   render("homeTrades",a.slice(0,12));
   const buys=a.filter(x=>cls(v(x,"signal","direction"))==="buy").length,sells=a.filter(x=>cls(v(x,"signal","direction"))==="sell").length,total=buys+sells||1;
   $("sentimentBars").innerHTML=[["العملات الرقمية",buys,sells],["الفيوتشر",a.filter(x=>x.market==="futures"&&cls(v(x,"signal","direction"))==="buy").length,a.filter(x=>x.market==="futures"&&cls(v(x,"signal","direction"))==="sell").length],["الأسواق الأخرى",a.filter(x=>x.market!=="crypto"&&x.market!=="futures"&&cls(v(x,"signal","direction"))==="buy").length,a.filter(x=>x.market!=="crypto"&&x.market!=="futures"&&cls(v(x,"signal","direction"))==="sell").length]].map(x=>{let p=Math.round(x[1]/Math.max(1,x[1]+x[2])*100);return '<div class="sentiment-row"><b>'+x[0]+'</b><div class="sentiment-track"><i style="width:'+p+'%"></i></div><span>'+p+'% شراء</span></div>'}).join("");
   $("tickerItems").innerHTML=a.slice(0,10).map(x=>'<span><b>'+esc(v(x,"symbol","name"))+'</b> <em class="'+cls(v(x,"signal","direction"))+'">'+esc(v(x,"signal","direction"))+'</em> '+n(v(x,"price"))+'</span>').join("");
 }catch(e){}
 $("dashAnalyze")?.addEventListener("click",quickAnalyze);
 $("homeNews")&&loadNewsMini();
}
async function quickAnalyze(){
 try{
  const sym=($("dashSymbol").value||"BTCUSDT").trim().toUpperCase(), i=$("dashInterval").value||"15m";
  let d=await api("/api/ai/signals?market=crypto&interval="+encodeURIComponent(i)+"&limit=50");
  let a=rows(d),r=a.find(x=>String(v(x,"symbol","name")).replace("-USDT-SWAP","").toUpperCase()===sym)||a[0];
  if(!r)throw Error("ما لقيت فرصة بهذا الرمز في الفحص الحالي");
  $("dashAnalysis").innerHTML=card(r);
 }catch(e){$("dashAnalysis").innerHTML='<div class="empty">'+esc(e.message)+'</div>'}
}
async function loadNewsMini(){try{let d=await api("/api/news").catch(()=>api("/api/news/latest")),a=rows(d).slice(0,4);$("homeNews").innerHTML=a.map(x=>'<div><span>●</span><b>'+esc(x.title||"خبر مالي")+'</b><small>'+esc(x.source||"")+'</small></div>').join("")||'<div class="empty">لا توجد أخبار حالياً</div>'}catch{}}

async function news(){if(!$("newsList"))return;try{let d=await api("/api/news").catch(()=>api("/api/news/latest")),a=rows(d);$("newsList").innerHTML=a.length?a.map(x=>'<article class="news-card"><span class="eyebrow">'+esc(x.source||"NEWS")+'</span><h3>'+esc(x.title||"خبر")+'</h3><p>'+esc(x.content||x.description||"")+'</p>'+(x.url?'<a class="btn" href="'+esc(x.url)+'" target="_blank">قراءة الخبر</a>':"")+'</article>').join(""):'<div class="empty">لا توجد أخبار.</div>'}catch{$("newsList").innerHTML='<div class="empty">تعذر تحميل الأخبار.</div>'}}
async function subscription(){if(!$("plans"))return;try{let d=await api("/api/subscription/plans").catch(()=>api("/api/plans")),a=Array.isArray(d.plans)?d.plans:Object.values(d.plans||{});$("plans").innerHTML=a.map(x=>'<article class="plan"><span class="eyebrow">'+esc(x.name||x.title||"باقة")+'</span><div class="price-big">'+n(x.amount??x.price,2)+' USDT</div><p>'+n(x.days,0)+' يوم</p><button class="btn primary planBtn" data-plan="'+esc(x.id||x.plan||"")+'">اختيار الباقة</button></article>').join("");$("payAddress").textContent=d.address||"-";$("binancePayId").textContent=d.binancePayId||d.binance_pay_id||"-";qsa(".planBtn").forEach(b=>b.onclick=()=>localStorage.setItem("plan",b.dataset.plan));$("copyAddress")?.addEventListener("click",()=>navigator.clipboard?.writeText($("payAddress").textContent));$("copyBinancePay")?.addEventListener("click",()=>navigator.clipboard?.writeText($("binancePayId").textContent));$("sendPayment")?.addEventListener("click",async()=>{try{await api("/api/payment",{method:"POST",body:JSON.stringify({plan:localStorage.getItem("plan")||"30d",txid:$("txid").value.trim()})});alert("تم إرسال طلب الدفع")}catch(e){alert(e.message)}})}catch(e){$("plans").innerHTML='<div class="empty">'+esc(e.message)+'</div>'}}
async function login(){if(!$("loginBtn"))return;$("loginBtn").onclick=async()=>{try{await api("/api/auth/login",{method:"POST",body:JSON.stringify({email:$("loginEmail").value,username:$("loginEmail").value,password:$("loginPassword").value})});location.href="/"}catch(e){$("authMsg").textContent=e.message}}}
async function register(){if(!$("registerBtn"))return;$("registerBtn").onclick=async()=>{try{await api("/api/auth/register",{method:"POST",body:JSON.stringify({name:$("regName").value,email:$("regEmail").value,password:$("regPassword").value})});$("authMsg").textContent="تم إنشاء الحساب";$("authMsg").className="flash ok";setTimeout(()=>location.href="/login",700)}catch(e){$("authMsg").textContent=e.message}}}
function boot(){nav();auth();homePro();setupScanner();markets();news();subscription();login();register()}
document.addEventListener("DOMContentLoaded",boot);
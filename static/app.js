let data=[],active="all";
const $=s=>document.querySelector(s);
const names={saudi:"السعودي",us:"الأمريكي",contracts:"العقود الأمريكية",forex:"الفوركس",futures:"الفيوتشر",crypto:"العملات"};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
function levels(x){const entry=Number(x.entry||x.price||0),sh=x.direction==="SHORT";const raw=Array.isArray(x.tps)?x.tps.filter(v=>Number(v)>0).map(Number):[];const tps=raw.length?raw:[entry*(sh?0.99:1.01),entry*(sh?0.98:1.02),entry*(sh?0.97:1.03)];const sl=Number(x.sl)>0?Number(x.sl):entry*(sh?1.02:0.98);return{entry,tps,sl}}
function fmt(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:8})}
function levelsHtml(x){const l=levels(x);return '<div class="levels"><span><b>دخول</b><em>'+fmt(l.entry)+'</em></span><span><b>TP1</b><em>'+fmt(l.tps[0])+'</em></span><span><b>TP2</b><em>'+fmt(l.tps[1])+'</em></span><span><b>TP3</b><em>'+fmt(l.tps[2])+'</em></span><span class="stop"><b>وقف</b><em>'+fmt(l.sl)+'</em></span></div>'}
function card(x){
 const sh=x.direction==="SHORT",src=x.sources_count||0,men=x.mentions||0;
 return '<article class="card"><div class="top"><small>'+esc(names[x.market||x.source_market]||"السوق")+'</small><span class="score">'+Math.round(x.score||0)+'%</span></div><div class="asset-line"><h3>'+esc(x.symbol)+'</h3><i class="badge '+(sh?"sell":"buy")+'">'+(sh?"بيع":"شراء")+'</i></div><div class="price">'+Number(x.price||x.entry||0).toLocaleString(undefined,{maximumFractionDigits:8})+'</div>'+levelsHtml(x)+'<div class="meta"><span>'+src+' مصادر</span><span>'+men+' توصيات</span><span>إجماع '+(x.consensus||0)+'%</span><span>RSI '+(x.technical?.rsi??"—")+'</span></div><div class="meter"><i style="width:'+Math.min(100,x.score||0)+'%"></i></div></article>'
}
function bestHtml(b){
 return b?'<div class="best"><div><label>أعلى فرصة مؤهلة</label><h3>'+esc(b.symbol)+' <i class="'+(b.direction==="SHORT"?"short":"long")+'">'+(b.direction==="SHORT"?"بيع":"شراء")+'</i></h3><p>'+esc(b.technical?.trend||"تحقق فني")+' · '+(b.sources_count||1)+' مصادر · '+(b.mentions||0)+' توصيات · إجماع '+(b.consensus||0)+'%</p></div><div class="best-score"><b>'+Math.round(b.score||0)+'%</b><small>قوة الفرصة</small></div></div>':'<div class="empty">ما فيه فرصة مؤهلة حاليًا.</div>'
}
function render(){
 const a=active==="all"?data:data.filter(x=>(x.market||x.source_market)===active);
 $("#filterState").textContent=active==="all"?"كل الأسواق":(names[active]||active);
 $("#best").innerHTML=bestHtml(a[0]);
 $("#cards").innerHTML=a.slice(0,15).map(card).join("")||'<div class="empty">ما فيه فرصة مؤهلة حاليًا.</div>';
}
function renderMarket(m){
 const root=document.querySelector('.market-content[data-market="'+m+'"]');
 if(!root)return;
 const a=data.filter(x=>(x.market||x.source_market)===m);
 root.querySelector(".best").innerHTML=bestHtml(a[0]);
 root.querySelector(".grid").innerHTML=a.slice(0,20).map(card).join("")||'<div class="empty">ما فيه فرصة مؤهلة حاليًا في هذا القسم.</div>';
}
function renderAllMarkets(){["saudi","us","contracts","crypto","futures","forex"].forEach(renderMarket)}
async function load(){
 try{
  const r=await fetch("/api/opportunities",{cache:"no-store"}),d=await r.json();
  data=d.opportunities||[];
  const live=d.radar?.sources_live??d.radar?.sources_total??0,total=d.radar?.sources_total??0;
  $("#statOpp").textContent=data.length;$("#statSrc").textContent=live+"/"+total;$("#statCons").textContent=(data[0]?.consensus||0)+"%";$("#statAge").textContent=new Date().toLocaleTimeString("ar-SA");
  render();renderAllMarkets();
  $("#trades").innerHTML=(d.live_trades||[]).filter(t=>t.status==="OPEN"||String(t.status).startsWith("TP")).slice(-8).reverse().map(trade).join("")||'<div class="empty">ما فيه فرص قيد المتابعة.</div>';
  $("#update").textContent="آخر تحديث "+new Date().toLocaleTimeString("ar-SA");
 }catch(e){console.error(e)}
}
function trade(t){return '<article class="trade"><div><b>'+esc(t.symbol)+'</b> <i class="'+(t.direction==="SHORT"?"short":"long")+'">'+(t.direction==="SHORT"?"بيع":"شراء")+'</i></div><b>'+esc(t.status||"OPEN")+'</b><small>الدخول '+Number(t.entry||0).toLocaleString(undefined,{maximumFractionDigits:8})+' · الحالي '+(t.current?Number(t.current).toLocaleString(undefined,{maximumFractionDigits:8}):"—")+' · P/L '+(t.pnl_pct??0)+'%</small></article>'}
let authMode="login";
const modal=$("#authModal"), authTitle=$("#authTitle"), authName=$("#authName"), authEmail=$("#authEmail"), authPassword=$("#authPassword"), authSubmit=$("#authSubmit"), authError=$("#authError");
function openAuth(mode){authMode=mode;modal.classList.remove("hidden");authTitle.textContent=mode==="login"?"تسجيل الدخول":"إنشاء حساب";authName.classList.toggle("hidden",mode==="login");authSubmit.textContent=mode==="login"?"دخول":"إنشاء الحساب";authError.textContent="";}
function closeAuth(){modal.classList.add("hidden")}
async function authSubmitNow(){
 try{const r=await fetch("/api/auth/"+(authMode==="login"?"login":"register"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:authName.value,email:authEmail.value,password:authPassword.value})});const d=await r.json();if(!r.ok)throw Error(d.error||"تعذر إتمام العملية");closeAuth();syncAuth();}catch(e){authError.textContent=e.message}
}
async function syncAuth(){
 try{const r=await fetch("/api/auth/me",{cache:"no-store"}),d=await r.json(),u=d.user;
 $("#loginBtn").classList.toggle("hidden",!!u);$("#registerBtn").classList.toggle("hidden",!!u);$("#dashboardBtn").classList.toggle("hidden",!u);$("#logoutBtn").classList.toggle("hidden",!u);syncDrawerAuth(u);
 if(u){$("#dashboardBtn").textContent=u.name||"حسابي";$("#accountName").textContent=u.email;loadDashboard()}
 }catch(e){}
}
async function loadDashboard(){try{const r=await fetch("/api/dashboard"),d=await r.json();if(!r.ok)return;$("#accountStats").innerHTML='<div><small>الفرص المتابعة</small><b>'+d.stats.tracked+'</b></div><div><small>مفتوحة</small><b>'+d.stats.open+'</b></div><div><small>أهداف محققة</small><b>'+d.stats.tp+'</b></div><div><small>وقف</small><b>'+d.stats.sl+'</b></div>'}catch(e){}}
$("#loginBtn").onclick=()=>openAuth("login");$("#registerBtn").onclick=()=>openAuth("register");$("#dashboardBtn").onclick=()=>showSection("account");$("#logoutBtn").onclick=async()=>{await fetch("/api/auth/logout",{method:"POST"});$("#accountPanel").classList.add("hidden");syncAuth()};$("#authClose").onclick=closeAuth;$("#authSubmit").onclick=authSubmitNow;$("#authSwitch").onclick=()=>openAuth(authMode==="login"?"register":"login");syncAuth();

const drawer=$("#drawer"),menuBtn=$("#menuBtn"),drawerClose=$("#drawerClose");
const drawerLogin=$("#drawerLoginBtn"),drawerRegister=$("#drawerRegisterBtn"),drawerLogout=$("#drawerLogoutBtn");
function syncDrawerAuth(u){if(!drawerLogin)return;drawerLogin.classList.toggle("hidden",!!u);drawerRegister.classList.toggle("hidden",!!u);if(drawerLogout)drawerLogout.classList.toggle("hidden",!u)}
function showSection(s){
 document.querySelectorAll(".page-section").forEach(x=>x.style.display="none");
 $("#accountPanel").classList.add("hidden");
 let target=s;
 if(["saudi","us","contracts","crypto","futures","forex"].includes(s))target="market-"+s;
 if(s==="account")target="accountPanel";
 const el=$("#"+target);
 if(el)el.style.display="";
 if(target==="accountPanel")$("#accountPanel").classList.remove("hidden");
 if(target==="radar"){active="all";document.querySelectorAll("#nav button").forEach(b=>b.classList.toggle("active",b.dataset.m==="all"));render()}
 if(target.startsWith("market-")){active=s;document.querySelectorAll("#nav button").forEach(b=>b.classList.toggle("active",b.dataset.m===s));renderMarket(s)}
 drawer.classList.remove("open");
}
menuBtn.onclick=()=>drawer.classList.add("open");
drawerClose.onclick=()=>drawer.classList.remove("open");
if(drawerLogin)drawerLogin.onclick=()=>{drawer.classList.remove("open");openAuth("login")};
if(drawerRegister)drawerRegister.onclick=()=>{drawer.classList.remove("open");openAuth("register")};
if(drawerLogout)drawerLogout.onclick=async()=>{await fetch("/api/auth/logout",{method:"POST"});syncAuth()};
window.addEventListener("keydown",e=>{if(e.key==="Escape"){drawer.classList.remove("open");closeAuth()}});
document.querySelectorAll(".drawer-nav button[data-section], [data-section]").forEach(b=>b.onclick=()=>showSection(b.dataset.section));
document.querySelectorAll("#nav button[data-m]").forEach(b=>b.onclick=()=>showSection(b.dataset.m));
showSection("home");
const $=s=>document.querySelector(s);
const MARKET_NAMES={spot:"Binance Spot",futures:"Binance Futures",alpha:"Binance Alpha",saudi:"السوق السعودي",us:"الأسهم الأمريكية",contracts:"العقود الأمريكية",forex:"الفوركس والذهب"};
const PATH=location.pathname.replace(/\/+$/,"")||"/";
const marketMatch=PATH.match(/^\/markets\/([a-z]+)$/);
let market=marketMatch?marketMatch[1]:"spot",busy=false,pending=false,timer=null;
const fmt=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const compact=n=>{n=Number(n)||0;if(n>=1e9)return (n/1e9).toFixed(2)+"B";if(n>=1e6)return (n/1e6).toFixed(2)+"M";if(n>=1e3)return (n/1e3).toFixed(1)+"K";return fmt(n)};
const pct=n=>(Number(n)>=0?"+":"")+Number(n).toFixed(2)+"%";
const safe=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function get(url,timeout=18000){
 const controller=new AbortController(),id=setTimeout(()=>controller.abort(),timeout);
 try{
  const r=await fetch(url,{cache:"no-store",signal:controller.signal,headers:{"Accept":"application/json"}});
  let j={};try{j=await r.json()}catch{}
  if(!r.ok)throw Error(j.error||j.message||("تعذر جلب البيانات ("+r.status+")"));
  return j;
 }catch(e){if(e.name==="AbortError")throw Error("تأخر مصدر البيانات؛ حاول التحديث بعد قليل.");throw e}
 finally{clearTimeout(id)}
}
function renderMovers(rows){
 const root=$("#movers");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا تتوفر حركة أصول كافية للعرض.</div>';return}
 root.innerHTML=rows.map(x=>'<article class="mover"><div class="mover-head"><b class="mover-symbol">'+safe(x.symbol)+'</b><span class="mover-side">'+(x.change24h>=0?"الأعلى صعودًا":"الأعلى هبوطًا")+'</span></div><b class="mover-price">'+fmt(x.price)+'</b><div class="mover-change '+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</div><small class="mover-volume">حجم 24س '+compact(x.volume)+' USDT</small></article>').join("");
}
function renderSignals(rows){
 const root=$("#cards");
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد فرصة اجتازت شروط الاتجاه وتوافق 4 ساعات واليومي حاليًا. سيستمر الفحص مع التحديث القادم.</div>';return}
 root.innerHTML=rows.map((x,i)=>{
  const side=x.side==="BUY"?1:-1;
  const tp1=pct(side*(x.tp1/x.entry-1)*100),tp2=pct(side*(x.tp2/x.entry-1)*100),tp3=pct(side*(x.tp3/x.entry-1)*100);
  const rank=i===0?"gold":i===1?"silver":"bronze";
  return '<article class="trade"><div class="trade-head"><div class="trade-title"><span class="rank '+rank+'">'+(i+1)+'</span><b>'+safe(x.symbol)+'</b></div><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?"شراء":"بيع")+'</span></div><div class="trade-meta-top"><span>تغير 24س <b class="'+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</b></span></div><div class="entry"><small>سعر الدخول</small><strong>'+fmt(x.entry)+'</strong></div><div class="levels"><div><small>TP1 · '+tp1+'</small><b>'+fmt(x.tp1)+'</b></div><div><small>TP2 · '+tp2+'</small><b>'+fmt(x.tp2)+'</b></div><div><small>TP3 · '+tp3+'</small><b>'+fmt(x.tp3)+'</b></div><div class="stop"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b></div></div><div class="trade-stats"><div class="trade-stat"><small>المخاطرة</small><b>'+x.risk_percent+'%</b></div><div class="trade-stat"><small>جودة الشروط</small><b>'+x.quality_score+'/100</b></div><div class="trade-stat"><small>RSI · حجم</small><b>'+x.rsi+' · '+compact(x.volume)+'</b></div></div></article>';
 }).join("");
}
function renderOpen(rows){
 const root=$("#openTrades");$("#openCount").textContent=(rows?.length||0)+" مفتوحة";
 if(!rows||!rows.length){root.innerHTML='<div class="empty">لا توجد صفقات مفتوحة محفوظة لهذا السوق.</div>';return}
 const target=(name,value,hit)=>'<div class="'+(hit?"hit":"")+'"><small>'+name+(hit?" ✓":"")+'</small><b>'+fmt(value)+'</b></div>';
 root.innerHTML=rows.map(x=>'<article class="open-row"><div><b>'+safe(x.symbol)+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div>'+target("TP1",x.tp1,x.tp1_hit)+target("TP2",x.tp2,x.tp2_hit)+target("TP3",x.tp3,x.tp3_hit)+'<div class="stop"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b></div><span class="tag">مفتوحة</span></article>').join("");
}
function renderClosed(rows){
 const closed=(rows||[]).filter(x=>x.status!=="OPEN").slice(0,12);
 $("#historyCount").textContent=closed.length+" مغلقة";
 const root=$("#closedTrades");
 if(!closed.length){root.innerHTML='<div class="empty">لا توجد نتائج مغلقة مسجلة بعد.</div>';return}
 root.innerHTML=closed.map(x=>'<article class="history-row"><div><b>'+safe(x.symbol)+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>النتيجة</small><b class="history-status '+(x.status==="TP3"?"tp":"sl")+'">'+(x.status==="TP3"?"وصل TP3":"وقف الخسارة")+'</b></div><div><small>تاريخ الإغلاق</small><b>'+new Date((x.closed_at||x.updated_at)*1000).toLocaleDateString("ar-SA")+'</b></div></article>').join("");
}
async function loadMarketStatuses(){
 try{
  const d=await get("/api/markets",8000);
  const states=new Map((d.markets||[]).map(x=>[x.id,x]));
  document.querySelectorAll("[data-market]").forEach(b=>{
   const item=states.get(b.dataset.market);if(!item)return;
   const live=item.status==="live"||item.status==="configured_watchlist";
   const small=b.querySelector("small");if(small)small.textContent=live?"مصدر متاح":item.status==="provider_required"?"مزود البيانات غير مربوط":"يتطلب إعداد المصدر";
   b.title=live?"مصدر البيانات متاح":"صفحة السوق مستقلة، لكن مصدر البيانات يحتاج إعدادًا";
   b.classList.toggle("active",b.dataset.market===market);
   const dot=b.querySelector(".tab-state");if(dot)dot.style.display=live?"block":"none";
  });
 }catch(e){$("#health").textContent="تعذر فحص الأسواق";$("#health").className="bad"}
}
async function load(){
 if(busy){pending=true;return}
 busy=true;pending=false;
 const refresh=$("#refresh");refresh.disabled=true;refresh.innerHTML="<span>↻</span> جارٍ التحديث";
 $("#health").textContent="جارٍ التحديث";$("#scanState").textContent="يفحص السوق";$("#scanState").className="";
 try{
  const requestedMarket=market;
  const [d,t]=await Promise.all([
   get("/api/market/"+requestedMarket),
   get("/api/trades?market="+encodeURIComponent(requestedMarket),10000).catch(()=>({items:[]})) 
  ]);
  if(requestedMarket!==market){pending=true;return}
  $("#direction").textContent=d.direction_ar;$("#direction").className="direction-value "+(d.direction==="BUY"?"up":d.direction==="SELL"?"down":"neutral");
  $("#up").textContent=d.up;$("#down").textContent=d.down;$("#flat").textContent=d.flat??0;$("#total").textContent=d.total;
  const total=Math.max(1,Number(d.total)||0);
  $("#upBar").style.width=(d.up/total*100)+"%";$("#downBar").style.width=(d.down/total*100)+"%";$("#flatBar").style.width=((d.flat||0)/total*100)+"%";
  $("#updated").textContent=new Date(d.updated*1000).toLocaleTimeString("ar-SA");
  $("#source").textContent="مصدر البيانات: "+d.source+" · "+d.strategy;
  $("#sourceShort").textContent=d.source||"بيانات عامة";
  $("#scanState").textContent="اكتمل";$("#scanState").className="state-good";
  renderMovers(d.movers);renderSignals(d.signals);renderOpen(d.open_trades);renderClosed(t.items);
  $("#health").textContent="متصل";$("#health").className="ok";
 }catch(e){
  $("#cards").innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  $("#scanState").textContent="تعذر الفحص";$("#scanState").className="down";
  $("#health").textContent="غير متصل";$("#health").className="bad";
 }finally{
  busy=false;refresh.disabled=false;refresh.innerHTML="<span>↻</span> تحديث البيانات";
  if(pending){pending=false;load()}
 }
}


$("#refresh").addEventListener("click",load);
async function loadNews(){
 const root=$("#newsFeed");if(!root)return;
 root.innerHTML='<div class="empty">جارٍ جلب آخر العناوين...</div>';
 try{
  const d=await get("/api/news",10000);
  if(!d.items?.length){root.innerHTML='<div class="empty">'+safe(d.error||"لا توجد عناوين متاحة الآن.")+'</div>';return}
  root.innerHTML=d.items.map(x=>'<article class="news-item"><div><small>'+safe(x.source||"مصدر خارجي")+' · '+safe(x.published||"")+'</small><h3><a href="'+safe(x.url)+'" target="_blank" rel="noopener noreferrer">'+safe(x.title)+'</a></h3></div><span class="news-arrow">↗</span></article>').join("");
 }catch(e){root.innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
}
$("#newsRefresh")?.addEventListener("click",loadNews);
function configurePage(){
 const ids=["homeSection","marketSection","directionSection","moversSection","movers","opportunitiesSection","cards","openSection","historySection","blogSection","newsSection"];
 const hideAll=()=>ids.forEach(id=>{const el=$("#"+id);if(el)el.hidden=true});
 const show=(...names)=>names.forEach(id=>{const el=$("#"+id);if(el)el.hidden=false});
 if(PATH==="/"){
  hideAll();show("homeSection","marketSection");
  $("#homeSection h1").innerHTML='مركز <span>الأسواق</span>';
  $("#homeSection p").textContent="اختر سوقًا مستقلًا أو قسمًا لعرضه في صفحة منفصلة.";
 }else if(marketMatch){
  if(!MARKET_NAMES[market]){location.replace("/");return}
  hideAll();show("homeSection","directionSection","moversSection","movers","opportunitiesSection","cards","openSection","historySection");
  $("#homeSection h1").innerHTML='<span>'+MARKET_NAMES[market]+'</span>';
  $("#homeSection p").textContent="صفحة مستقلة؛ بيانات واتجاهات وفرص وسجل هذا السوق فقط.";
 }else if(PATH.startsWith("/sections/")){
  const section=PATH.split("/").pop();
  const map={direction:["directionSection"],movers:["moversSection","movers"],opportunities:["opportunitiesSection","cards"],"open-trades":["openSection"],history:["historySection"]};
  hideAll();show("homeSection",...(map[section]||[]));
  const titles={direction:"توجه السوق",movers:"الأصول الأكثر حركة",opportunities:"أفضل الفرص الفنية","open-trades":"متابعة الصفقات",history:"سجل النتائج"};
  $("#homeSection h1").innerHTML='<span>'+safe(titles[section]||"القسم")+'</span>';
  $("#homeSection p").textContent="قسم مستقل عن الصفحة الرئيسية.";
 }else if(PATH==="/blog"){
  hideAll();show("homeSection","blogSection");
  $("#homeSection h1").innerHTML='المدونة <span>التعليمية</span>';
  $("#homeSection p").textContent="محتوى تعليمي مستقل عن صفحات الأسواق.";
 }else if(PATH==="/news"){
  hideAll();show("homeSection","newsSection");
  $("#homeSection h1").innerHTML='أخبار <span>الأسواق</span>';
  $("#homeSection p").textContent="آخر العناوين من موجز أخبار خارجي.";
  loadNews();
 }else{hideAll();show("homeSection","marketSection")}
 $("#marketSection").hidden=PATH!=="/";
 $("#refresh").hidden=PATH==="/"||PATH==="/blog"||PATH==="/news";
 if(PATH==="/admin"){
  if($("#adminPanel").hidden){location.replace("/");return}
  hideAll();show("homeSection","adminPanel");
  $("#homeSection h1").innerHTML="إدارة <span>المشتركين</span>";
  $("#homeSection p").textContent="إدارة الحسابات والصلاحيات بشكل مستقل.";
 }
 const drawer=$("#siteDrawer");
 if(drawer)drawer.querySelectorAll("a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")===PATH));
}

document.addEventListener("visibilitychange",()=>{if(!document.hidden && !$("#mainContent").hidden && (marketMatch||PATH.startsWith("/sections/")))load()});
function tick(){ $("#clock").textContent=new Date().toLocaleTimeString("en-GB",{hour12:false}); }
async function showAccess(message, user=null){
 $("#mainContent").hidden=true;
 $("#accessGate").hidden=false;
 $("#topLogout").hidden=true;
 $("#authNotice").textContent=message||"";
 $("#authLogout").hidden=!user;
 $("#authToggle").hidden=!!user;
 $("#authForm").hidden=!!user;
 $("#accessTitle").textContent=user?"الاشتراك غير مفعل":"تسجيل الدخول";
 $("#accessMessage").textContent=user?"حسابك مسجل، لكن لا يوجد اشتراك نشط. تواصل مع الإدارة لتفعيل الوصول إلى الأسواق.":"أنشئ حسابًا أو سجل دخولك. الوصول إلى الأسواق للمشتركين فقط.";
}
async function startAuthorized(user=null){
 $("#accessGate").hidden=true;
 $("#mainContent").hidden=false;
 $("#topLogout").hidden=true;
 $("#adminPanel").hidden=!(user&&user.is_admin);
 $("#drawerAdmin").hidden=!(user&&user.is_admin);
 if(user&&user.is_admin) await loadAdminUsers();
 configurePage();
 if(marketMatch){await loadMarketStatuses();await load();}
 else if(PATH==="/"){await loadMarketStatuses();}
 else if(PATH.startsWith("/sections/") && ["direction","movers","opportunities","open-trades","history"].includes(PATH.split("/").pop())){await loadMarketStatuses();await load();}
}
async function initializeAccess(){
 // Public browsing is enabled. Login is optional and only used for admin tools.
 let user=null;
 try{
  const d=await get("/api/auth/me",5000);
  if(d&&d.configured&&d.user) user=d.user;
 }catch(e){
  console.warn("Optional account status unavailable; continuing in public mode.",e);
 }
 await startAuthorized(user);
}
let creatingAccount=false;
$("#authToggle").addEventListener("click",()=>{
 creatingAccount=!creatingAccount;
 $("#accessTitle").textContent=creatingAccount?"إنشاء حساب جديد":"تسجيل الدخول";
 $("#authSubmit").textContent=creatingAccount?"إنشاء الحساب":"دخول";
 $("#authPassword").autocomplete=creatingAccount?"new-password":"current-password";
 $("#authToggle").textContent=creatingAccount?"لديك حساب؟ تسجيل الدخول":"ليس لديك حساب؟ إنشاء حساب";
 $("#authNotice").textContent="";
});
$("#authForm").addEventListener("submit",async e=>{
 e.preventDefault();
 const button=$("#authSubmit");button.disabled=true;
 $("#authNotice").textContent="جارٍ التحقق...";
 try{
  const response=await fetch(creatingAccount?"/api/auth/register":"/api/auth/login",{
   method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({email:$("#authEmail").value,password:$("#authPassword").value})
  });
  const d=await response.json();
  if(!response.ok)throw Error(d.message||"تعذر إكمال الطلب.");
  if(d.user?.is_admin || d.user?.subscribed) await startAuthorized(d.user);
  else await showAccess("تم إنشاء الحساب بنجاح. الاشتراك يحتاج موافقة الأدمن.",d.user);
 }catch(err){$("#authNotice").textContent=err.message}
 finally{button.disabled=false}
});
async function logout(){
 await fetch("/api/auth/logout",{method:"POST"});
 location.reload();
}
$("#authLogout").addEventListener("click",logout);
$("#topLogout").addEventListener("click",logout);
async function loadAdminUsers(){
 try{
  const d=await get("/api/admin/users",10000);
  const root=$("#adminUsers");
  if(!d.users.length){root.innerHTML='<div class="empty">لا توجد حسابات بعد.</div>';return}
  root.innerHTML=d.users.map(u=>{
   const expiry=u.subscription_expires_at?new Date(u.subscription_expires_at*1000).toLocaleDateString("ar-SA"):"—";
   const status=u.role==="admin"?"أدمن":u.subscribed?"مشترك حتى "+expiry:"غير مشترك";
   const actions=u.role==="admin"?"":'<div class="admin-actions"><button data-admin-action="grant" data-days="30" data-user="'+u.id+'">شهر</button><button data-admin-action="grant" data-days="60" data-user="'+u.id+'">شهرين</button><button data-admin-action="grant" data-days="90" data-user="'+u.id+'">3 أشهر</button><button data-admin-action="grant" data-days="180" data-user="'+u.id+'">6 أشهر</button><button data-admin-action="grant" data-days="365" data-user="'+u.id+'">سنة</button><button class="revoke" data-admin-action="revoke" data-user="'+u.id+'">إلغاء</button></div>';
   return '<article class="admin-user"><div><b>'+safe(u.email)+'</b><small>رقم الحساب: '+u.id+' · '+status+'</small></div>'+actions+'</article>';
  }).join("");
 }catch(e){$("#adminUsers").innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
}
$("#adminRefresh").addEventListener("click",loadAdminUsers);
$("#adminUsers").addEventListener("click",async e=>{
 const b=e.target.closest("[data-admin-action]");if(!b)return;
 b.disabled=true;
 try{
  const response=await fetch("/api/admin/subscription",{
   method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user_id:Number(b.dataset.user),action:b.dataset.adminAction,days:Number(b.dataset.days||0)})
  });
  const d=await response.json();if(!response.ok)throw Error(d.message||"تعذر تعديل الاشتراك.");
  await loadAdminUsers();
 }catch(err){alert(err.message);b.disabled=false}
});

function closeDrawer(){
 const drawer=$("#siteDrawer"),backdrop=$("#drawerBackdrop"),open=$("#menuOpen");
 drawer.classList.remove("open");drawer.setAttribute("aria-hidden","true");
 backdrop.hidden=true;open.setAttribute("aria-expanded","false");
}
$("#menuOpen").addEventListener("click",()=>{
 const drawer=$("#siteDrawer"),backdrop=$("#drawerBackdrop"),open=$("#menuOpen");
 drawer.classList.add("open");drawer.setAttribute("aria-hidden","false");
 backdrop.hidden=false;open.setAttribute("aria-expanded","true");
});
$("#menuClose").addEventListener("click",closeDrawer);
$("#drawerBackdrop").addEventListener("click",closeDrawer);
$("#siteDrawer").addEventListener("click",e=>{
 const link=e.target.closest("a");if(!link)return;
 closeDrawer();
});

tick();setInterval(tick,1000);
initializeAccess();
timer=setInterval(()=>{if(!document.hidden && !$("#mainContent").hidden && (marketMatch||PATH.startsWith("/sections/")))load() },30000);

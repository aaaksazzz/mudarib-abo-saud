(function(){
"use strict";
function $(id){return document.getElementById(id);}
function esc(x){return String(x==null?"":x).replace(/[&<>"']/g,function(m){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m];});}
function num(x){return Number(x||0).toLocaleString("en-US",{maximumFractionDigits:8});}
async function api(url,opts){
 opts=opts||{};
 var headers={"Content-Type":"application/json"};
 if(opts.headers){Object.assign(headers,opts.headers);}
 var res=await fetch(url,{cache:"no-store",credentials:"same-origin",method:opts.method||"GET",body:opts.body||undefined,headers:headers});
 var data=await res.json().catch(function(){return {};});
 if(!res.ok||data.ok===false){throw new Error(data.message||"حدث خطأ في الخادم");}
 return data;
}
function card(x){
 var cls=x.direction==="شراء"?"buy":x.direction==="بيع"?"sell":"neutral";
 return '<article class="trade"><div class="trade-top"><div><div class="symbol">'+esc(x.displayName||x.symbol)+'</div><small>'+esc(x.symbol)+' · '+esc(x.interval)+'</small></div><b class="signal '+cls+'">'+esc(x.signal)+'</b></div><h3>دخول: '+num(x.entry)+'</h3><div class="levels"><div class="level"><small>TP1</small>'+num(x.tp1)+'</div><div class="level"><small>TP2</small>'+num(x.tp2)+'</div><div class="level"><small>TP3</small>'+num(x.tp3)+'</div><div class="level"><small>SL</small>'+num(x.sl)+'</div></div><div class="meta">ثقة التحليل: '+num(x.confidence)+'% · R:R '+num(x.rr)+'</div></article>';
}
async function loadMarket(market,interval,box){
 if(!box)return;
 box.innerHTML='<div class="empty">🤖 جاري التحليل...</div>';
 try{
  var d=await api("/api/ai/signals?market="+encodeURIComponent(market)+"&interval="+encodeURIComponent(interval)+"&limit=20");
  var results=(d.results||[]).filter(function(x){return x.tradeReady;});
  box.innerHTML=results.length?results.map(card).join(""):'<div class="empty">لا توجد صفقة مستوفية حالياً. جرّب تحديث أو فاصل زمني آخر.</div>';
 }catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
}
function section(){
 var box=$("market"),page=document.body.getAttribute("data-page");
 var map={spot:["crypto","15m"],futures:["futures","15m"],contracts:["futures","15m"],saudi:["saudi","1D"],usmarket:["usmarket","1D"],forex:["forex","1H"]};
 var cfg=map[page];
 if(!box||!cfg)return;
 var market=cfg[0],def=cfg[1],buttons=document.querySelectorAll("[data-i]");
 buttons.forEach(function(btn){btn.addEventListener("click",function(){buttons.forEach(function(x){x.classList.remove("active");});btn.classList.add("active");loadMarket(market,btn.getAttribute("data-i"),box);});});
 var first=document.querySelector('[data-i="'+def+'"]');
 if(first)first.classList.add("active");
 var refresh=$("refresh");
 if(refresh)refresh.addEventListener("click",function(){var a=document.querySelector("[data-i].active");loadMarket(market,a?a.getAttribute("data-i"):def,box);});
 loadMarket(market,def,box);
}
function marketName(m){return {crypto:"🟢 العملات الرقمية",futures:"🔵 الفيوتشر",saudi:"🇸🇦 السوق السعودي",usmarket:"🇺🇸 السوق الأمريكي",forex:"💱 الفوركس والسلع"}[m]||m;}
function overviewCard(x){
 var total=x.total||0;
 return '<article class="market-card"><div class="market-head"><h3>'+marketName(x.market)+'</h3><span>'+esc(x.interval)+'</span></div><div class="market-counts"><div><b class="up">'+x.up+'</b><small>صاعد</small></div><div><b class="down">'+x.down+'</b><small>هابط</small></div><div><b class="flat">'+x.neutral+'</b><small>محايد</small></div><div><b>'+total+'</b><small>الإجمالي</small></div></div><div class="market-bar"><i style="width:'+((x.up/Math.max(total,1))*100)+'%"></i></div><p class="muted">أقوى إشارة: '+esc(x.top||"لا توجد")+' · ثقة '+num(x.confidence||0)+'%</p><a class="btn" href="'+(x.market==="crypto"?"/spot":x.market==="futures"?"/futures":x.market==="saudi"?"/saudi":x.market==="usmarket"?"/usmarket":"/forex")+'">عرض السوق بالكامل</a></article>';
}
async function homeOverview(){
 var box=$("marketOverview"); if(!box)return;
 try{
  var d=await api("/api/home/overview");
  box.innerHTML=(d.markets||[]).map(overviewCard).join("")||'<div class="empty">لا توجد بيانات حالياً.</div>';
 }catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
}
function newsTime(x){try{return new Date(x).toLocaleString("ar-SA",{hour:"2-digit",minute:"2-digit",day:"numeric",month:"short"});}catch(e){return x||"";}}
function newsCard(x){return '<article class="news-card"><div class="news-source">📰 '+esc(x.source||"أخبار الأسواق")+' <span>'+esc(newsTime(x.published))+'</span></div><h3>'+esc(x.title)+'</h3><p>'+esc(x.description||"")+'</p><a href="'+esc(x.link||"#")+'" target="_blank" rel="noopener">قراءة الخبر ↗</a></article>';}
async function homeNews(){
 var box=$("homeNews");if(!box)return;
 try{
  var d=await api("/api/live-news");
  box.innerHTML=(d.news||[]).map(newsCard).join("")||'<div class="empty">لا توجد أخبار متاحة حالياً.</div>';
  var ticker=$("newsTicker");
  if(ticker){var items=(d.news||[]).slice(0,15);ticker.innerHTML=items.map(function(x){return '<a href="'+esc(x.link||"#")+'" target="_blank" rel="noopener">🔴 '+esc(x.title)+'</a>';}).join("　 •　 ")||'<span>لا توجد أخبار حالياً</span>';}
  var u=$("newsUpdated");if(u)u.textContent="● آخر تحديث "+newsTime(d.updatedAt);
 }catch(e){box.innerHTML='<div class="empty">⚠️ تعذر تحديث الأخبار حالياً</div>';}
}
function home(){var box=$("home");if(box)loadMarket("crypto","15m",box);homeOverview();homeNews();setInterval(homeNews,60000);}
function scanner(){
 var box=$("scanResults"),market=$("scanMarket"),interval=$("interval"),btn=$("scan");
 if(!box||!market||!interval||!btn)return;
 btn.addEventListener("click",function(){loadMarket(market.value,interval.value,box);});
 loadMarket(market.value,interval.value,box);
}
function auth(){
 var login=$("login");
 if(login)login.addEventListener("click",async function(){
  try{await api("/api/auth/login",{method:"POST",body:JSON.stringify({email:$("email").value,password:$("password").value})});location.href="/";}
  catch(e){$("msg").textContent=e.message;}
 });
 var register=$("register");
 if(register)register.addEventListener("click",async function(){
  try{await api("/api/auth/register",{method:"POST",body:JSON.stringify({name:$("name").value,email:$("email").value,password:$("password").value})});location.href="/";}
  catch(e){$("msg").textContent=e.message;}
 });
}
async function subscription(){
 if(!$("plans"))return;
 try{
  var d=await api("/api/subscription");
  $("plans").innerHTML=Object.keys(d.plans||{}).map(function(k){var v=d.plans[k];return '<button type="button" data-plan="'+esc(k)+'">'+esc(v.name)+" — "+num(v.amount)+" USDT</button>";}).join("");
  $("trc").textContent=(d.payment&&d.payment.trc20)||"غير مضبوط";
  $("bin").textContent=(d.payment&&d.payment.binancePay)||"غير مضبوط";
  var selected=null;
  document.querySelectorAll("[data-plan]").forEach(function(b){b.addEventListener("click",function(){selected=b.getAttribute("data-plan");document.querySelectorAll("[data-plan]").forEach(function(x){x.classList.remove("active");});b.classList.add("active");});});
  var send=$("send");
  if(send)send.addEventListener("click",async function(){
   try{if(!selected)throw new Error("اختر الباقة أولاً");await api("/api/subscription/request",{method:"POST",body:JSON.stringify({plan:selected,txid:$("txid").value.trim()})});$("msg").textContent="تم إرسال طلب الدفع";}
   catch(e){$("msg").textContent=e.message;}
  });
 }catch(e){$("msg").textContent=e.message;}
}
async function news(){
 var box=$("news");if(!box)return;
 try{var d=await api("/api/news");box.innerHTML=(d.news||[]).map(function(x){return '<article class="trade"><h3>'+esc(x.title)+'</h3><p>'+esc(x.content)+'</p><small>'+esc(x.created_at)+'</small></article>';}).join("")||'<div class="empty">لا توجد أخبار.</div>';}
 catch(e){box.innerHTML='<div class="empty">⚠️ '+esc(e.message)+'</div>';}
}
async function loadAdmin(){
 try{
  var s=await api("/api/admin/stats"),p=await api("/api/admin/payments"),u=await api("/api/admin/users");
  $("stats").innerHTML='<div>👥 المستخدمون: <b>'+s.users+'</b></div><div>💳 اشتراكات فعالة: <b>'+s.active_subscriptions+'</b></div><div>⏳ طلبات معلقة: <b>'+s.pending_payments+'</b></div>';
  $("payments").innerHTML=(p.payments||[]).map(function(x){var a=x.status==="pending"?' <button type="button" data-approve="'+x.id+'">اعتماد</button> <button type="button" data-reject="'+x.id+'">رفض</button>':"";return '<article class="trade">#'+x.id+" · "+esc(x.username)+" · "+esc(x.plan)+" · "+esc(x.txid)+" · "+esc(x.status)+a+"</article>";}).join("")||'<div class="empty">لا توجد طلبات</div>';
  $("users").innerHTML=(u.users||[]).map(function(x){return '<article class="trade"><b>'+esc(x.name)+'</b><br>'+esc(x.email)+'<br><small>الاشتراك: '+esc(x.subscription_until||"بدون اشتراك")+'</small><br><button type="button" data-extend="'+x.id+'">+30 يوم</button> <button type="button" data-delete="'+x.id+'">حذف</button></article>';}).join("")||'<div class="empty">لا يوجد مستخدمون</div>';
  document.querySelectorAll("[data-approve]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/payments/approve",{id:Number(b.getAttribute("data-approve"))});};});
  document.querySelectorAll("[data-reject]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/payments/reject",{id:Number(b.getAttribute("data-reject"))});};});
  document.querySelectorAll("[data-extend]").forEach(function(b){b.onclick=function(){adminAction("/api/admin/users/extend",{id:Number(b.getAttribute("data-extend")),days:30});};});
  document.querySelectorAll("[data-delete]").forEach(function(b){b.onclick=function(){if(confirm("حذف المستخدم؟"))adminAction("/api/admin/users/delete",{id:Number(b.getAttribute("data-delete"))});};});
 }catch(e){$("msg").textContent=e.message;}
}
async function adminAction(url,body){try{await api(url,{method:"POST",body:JSON.stringify(body)});loadAdmin();}catch(e){alert(e.message);}}
function admin(){
 var login=$("alogin");if(!login)return;
 login.addEventListener("click",async function(){
  try{await api("/api/admin/login",{method:"POST",body:JSON.stringify({username:$("au").value,password:$("ap").value})});$("adminLogin").hidden=true;$("adminPanel").hidden=false;loadAdmin();}
  catch(e){$("msg").textContent=e.message;}
 });
 var logout=$("alogout");
 if(logout)logout.addEventListener("click",async function(){await api("/api/admin/logout",{method:"POST"});location.reload();});
 var add=$("addNews");
 if(add)add.addEventListener("click",async function(){
  try{await api("/api/admin/news",{method:"POST",body:JSON.stringify({title:$("nt").value.trim(),content:$("nc").value.trim(),source:"مضارب أبو سعود"})});$("nt").value="";$("nc").value="";$("msg").textContent="تم نشر الخبر";}
  catch(e){$("msg").textContent=e.message;}
 });
}
document.addEventListener("DOMContentLoaded",function(){
 if(localStorage.getItem("theme")==="light")document.body.classList.add("light");section();home();scanner();auth();subscription();news();admin();
 var menu=$("menu");if(menu)menu.addEventListener("click",function(e){e.preventDefault();var side=$("side");if(side)side.classList.toggle("open");});
 var theme=$("theme");if(theme)theme.addEventListener("click",function(e){e.preventDefault();document.body.classList.toggle("light");localStorage.setItem("theme",document.body.classList.contains("light")?"light":"dark");});
});
})();
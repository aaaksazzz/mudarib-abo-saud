const frames=[["5m","5د"],["15m","15د"],["1h","1س"],["4h","4س"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]],markets={spot:"السبوت",futures:"الفيوتشر",contracts:"العقود",saudi:"السعودي",us:"الأمريكي",forex:"فوركس وذهب"};let frame="5m";const $=s=>document.querySelector(s);
document.getElementById("menu").onclick=()=>document.getElementById("side").classList.toggle("open");document.getElementById("theme").onclick=()=>document.body.classList.toggle("light");document.querySelectorAll("aside a").forEach(a=>a.onclick=()=>{document.getElementById("side").classList.remove("open");page(a.dataset.p)});
function buttons(){return '<div class="frames">'+frames.map(x=>'<button class="frame '+(x[0]===frame?"active":"")+'" onclick="setFrame(\''+x[0]+'\')">'+x[1]+"</button>").join("")+"</div>"}window.setFrame=f=>{frame=f;page(location.hash.slice(1)||"home")};
async function get(u){try{let r=await fetch(u);let d=await r.json();return r.ok?d:{error:d.detail||"حدث خطأ"}}catch(e){return {error:"تعذر الاتصال"}}}
async function send(u,method,body){try{let r=await fetch(u,{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});let d=await r.json();return r.ok?d:{error:d.detail||"حدث خطأ"}}catch(e){return {error:"تعذر الاتصال"}}}
function fmt(v){return Number(v).toPrecision(7)}
function pct(entry,target){entry=Number(entry);target=Number(target);if(!entry)return "0.00";return Math.abs((target-entry)/entry*100).toFixed(2)}
function card(x,i){
 const side=x.side, a=(x.analysts||[]).map(v=>'<span class="muted">'+v.name+' '+v.score+'%</span>').join(' · ');
 return '<div class="card"><div class="rank">'+(i<3?["👑","🥈","🥉"][i]:"#"+(i+1))+" "+x.symbol+'</div>'+
 '<div class="muted">'+markets[x.market]+' · '+x.timeframe+(x.change!=null?' · '+x.change+'%':'')+'</div>'+
 '<p class="signal '+(side==="BUY"?"buy":"sell")+'">'+(side==="BUY"?"شراء":"بيع")+' <span class="muted">AI '+x.ai+'% · توافق '+(x.agreement||0)+'/7</span></p>'+
 '<div class="bar"><i style="width:'+x.ai+'%"></i></div>'+
 '<div class="levels"><div class="level"><span>الدخول</span>'+fmt(x.entry)+'</div>'+
 '<div class="level"><span>TP1</span>'+fmt(x.tp1)+'</div><div class="level"><span>TP2</span>'+fmt(x.tp2)+'</div>'+
 '<div class="level"><span>TP3</span>'+fmt(x.tp3)+'</div><div class="level"><span>وقف</span>'+fmt(x.sl)+'</div></div>'+
 '<div class="levels"><div class="level"><span>ربح TP1</span>+'+pct(x.entry,x.tp1)+'%</div><div class="level"><span>خسارة الوقف</span>-'+pct(x.entry,x.sl)+'%</div></div>'+
 '<details><summary>🧠 كل التحليلات</summary><div class="muted analyst-list">'+a+'</div></details></div>';
}

async function market(p){$("#app").innerHTML='<div class="hero"><h1>'+markets[p]+'</h1><p class="muted">الإطار الافتراضي 5 دقائق</p>'+buttons()+'</div><div id="list" class="grid"><div class="loading">جاري التحليل...</div></div>';let d=await get("/api/trades?market="+p+"&timeframe="+frame);$("#list").innerHTML=d?.items?.length?d.items.map(card).join(""):'<div class="loading">لا توجد بيانات</div>'}
async function scanner(){
 $("#app").innerHTML='<div class="hero"><h1>⌕ الماسح الذكي</h1><p class="muted">فحص واسع للفرص ثم ترتيبها حسب توافق 7 محللين</p>'+buttons()+'</div><div id="list" class="grid"><div class="loading">جاري الفحص العميق...</div></div>';
 let d=await get("/api/scanner?timeframe="+frame);
 $("#list").innerHTML=d?.items?.map(card).join("")||'<div class="loading">تعذر جلب الفرص</div>';
}
async function analysts7(){
 $("#app").innerHTML='<div class="hero"><h1>◈ المحللين السبعة</h1><p class="muted">دمج كل الإشارات في تحليل واحد — الفرص الأقوى أولاً</p>'+buttons()+'</div><div id="list" class="grid"><div class="loading">جاري التحليل...</div></div>';
 let d=await get("/api/scanner?timeframe="+frame);
 $("#list").innerHTML=d?.items?.map(card).join("")||'<div class="loading">لا توجد فرص كافية</div>';
}
async function tracker(){
  let d=await get("/api/tracker");
  if(d?.error){simple("◷ متابع الصفقات",d.error);return}
  const s=d.stats||{}, all=d.items||[];
  const open=all.filter(x=>x.status==="open"), closed=all.filter(x=>x.status==="closed");
  const wins=Number(s.wins||0), losses=Number(s.losses||0), closedCount=Number(s.closed||0);
  const winRate=(wins+losses)>0?((wins/(wins+losses))*100).toFixed(1):"0.0";
  const money=Number(s.pnl||0);
  const stat=(icon,title,val,cls="")=>'<div class="tracker-stat '+cls+'"><span class="stat-icon">'+icon+'</span><div><small>'+title+'</small><strong>'+val+'</strong></div></div>';
  const num=v=>Number(v||0).toPrecision(8);
  const row=x=>{
    const live=x.status==="open", pnl=Number(x.pnl||0), buy=x.side==="BUY", market=markets[x.market]||x.market;
    const result=x.result==="win"?"🎯 رابحة":x.result==="loss"?"🛑 خاسرة":"—";
    return '<article class="trade-row '+(live?"is-open":"is-closed")+'">'+
      '<div class="trade-main"><div class="trade-title"><b>'+x.symbol+'</b><span class="market-pill">'+market+'</span><span class="tf-pill">'+x.timeframe+'</span></div>'+
      '<div class="trade-meta"><span class="trade-side '+(buy?"buy":"sell")+'">'+(buy?"شراء":"بيع")+'</span><span class="ai-pill">AI '+Number(x.ai||0).toFixed(0)+'%</span><span class="status-pill '+(live?"live":"closed")+'">'+(live?"● مفتوحة":"● مغلقة")+'</span></div></div>'+
      '<div class="trade-levels"><div><small>دخول</small><b>'+num(x.entry)+'</b></div><div><small>السعر الحالي</small><b>'+num(x.current_price||x.entry)+'</b></div><div><small>TP1</small><b class="tp"> '+num(x.tp1)+'</b></div><div><small>TP2</small><b class="tp"> '+num(x.tp2)+'</b></div><div><small>TP3</small><b class="tp"> '+num(x.tp3)+'</b></div><div><small>وقف</small><b class="sl"> '+num(x.sl)+'</b></div></div>'+
      '<div class="trade-result '+(pnl>=0?"positive":"negative")+'"><strong>'+(pnl>=0?"+":"")+pnl.toFixed(2)+'%</strong><small>'+result+'</small></div>'+
    '</article>';
  };
  const section=(title,items,empty,cls)=>'<section class="tracker-panel '+cls+'"><div class="tracker-panel-head"><div><h2>'+title+'</h2><span>'+items.length+' صفقة</span></div></div><div class="trade-list">'+(items.length?items.map(row).join(""):'<div class="tracker-empty">'+empty+'</div>')+'</div></section>';
  const total=Number(s.total||0);
  const summary=' <div class="tracker-summary"><b>النتيجة الفعلية</b><span>رابحة <strong>'+wins+'</strong></span><i>•</i><span>خاسرة <strong>'+losses+'</strong></span><i>•</i><span>مغلقة <strong>'+closedCount+'</strong></span></div>';
  $( "#app" ).innerHTML=
    '<section class="tracker-head"><div><h1>◷ متابع الصفقات</h1><p>متابعة الصفقات الحيّة المحفوظة على الخادم — بدون صفقات تجريبية</p>'+summary+'</div><div class="tracker-actions"><span class="tracker-live">● LIVE</span><button class="frame" onclick="tracker()">↻ تحديث</button><button class="frame" onclick="startBacktest()">🧪 اختبار الجهتين</button></div></section>'+
    '<section id="backtestBox" class="tracker-backtest-box"><div class="tracker-note">🧪 اختبار الجهتين: إشارة شراء 15M تُنفذ بيعاً، وقف 2% وهدف 4%.</div></section><section class="tracker-stats">'+
      stat("📊","إجمالي",total,"total")+stat("🟢","مفتوحة",s.open||0,"open")+stat("🏆","رابحة",wins,"win")+stat("🔴","خاسرة",losses,"loss")+stat("📈","نسبة النجاح",winRate+"%","rate")+stat("💰","صافي PnL",(money>=0?"+":"")+money.toFixed(2)+"%","pnl")+
    '</section>'+
    '<div class="tracker-note">🟢 المفتوحة الآن · 🏆 رابحة · 🔴 خاسرة · النتائج محسوبة من الصفقات الحيّة فقط</div>'+
    section("🟢 الصفقات المفتوحة",open,"لا توجد صفقات مفتوحة حالياً","open-panel")+
    section("📋 سجل الصفقات المغلقة",closed,"لا توجد صفقات مغلقة حتى الآن","closed-panel");
  if(window.__trackerTimer) clearTimeout(window.__trackerTimer);
  window.__trackerTimer=setTimeout(tracker,60000);
}

async function startBacktest(){
  const box=document.getElementById("backtestBox");
  if(box) box.innerHTML='<div class="tracker-note">⏳ بدأ اختبار 30 يوم... جاري فحص العملات.</div>';
  let d=await send("/api/backtest/both?limit=0","POST",{});
  if(d.error){if(box)box.innerHTML='<div class="tracker-note">❌ '+d.error+'</div>';return}
  pollBacktest();
}
async function pollBacktest(){
  let d=await get("/api/backtest/both/status");
  const box=document.getElementById("backtestBox");
  if(!box)return;
  if(d.running){
    const p=d.total?Math.round((d.progress/d.total)*100):0;
    box.innerHTML='<div class="tracker-note">⏳ اختبار الاستراتيجية المعكوسة: '+d.progress+'/'+d.total+' عملة ('+p+'%)</div>';
    setTimeout(pollBacktest,3000); return;
  }
  if(d.error){box.innerHTML='<div class="tracker-note">❌ '+d.error+'</div>';return}
  if(!d.done){box.innerHTML='<div class="tracker-note">🧪 اضغط «اختبار المعكوس» لبدء الاختبار.</div>';return}
  const r=d.result||{}, buy=r.original_buy||{}, sell=r.reversed_sell||{};
  const summary=(title,x,cls)=>'<div class="tracker-panel '+cls+'"><div class="tracker-panel-head"><div><h2>'+title+'</h2><span>'+x.trades+' صفقة</span></div></div><div class="tracker-stats">'+
  '<div class="tracker-stat total"><span class="stat-icon">📊</span><div><small>الصفقات</small><strong>'+x.trades+'</strong></div></div>'+
  '<div class="tracker-stat win"><span class="stat-icon">🏆</span><div><small>رابحة</small><strong>'+x.wins+'</strong></div></div>'+
  '<div class="tracker-stat loss"><span class="stat-icon">🔴</span><div><small>خاسرة</small><strong>'+x.losses+'</strong></div></div>'+
  '<div class="tracker-stat rate"><span class="stat-icon">📈</span><div><small>نسبة النجاح</small><strong>'+x.win_rate+'%</strong></div></div>'+
  '<div class="tracker-stat pnl"><span class="stat-icon">💰</span><div><small>الصافي</small><strong>'+x.net_pct+'%</strong></div></div>'+
  '<div class="tracker-stat"><span class="stat-icon">📉</span><div><small>أكبر سحب</small><strong>'+x.max_drawdown_pct+'%</strong></div></div>'+
  '</div><div class="tracker-note">Profit Factor: '+(x.profit_factor==null?"—":x.profit_factor)+'</div></div>';
  box.innerHTML=summary("🟢 BUY الأصلية",buy,"open-panel")+summary("🔴 SELL المعكوسة",sell,"closed-panel")+
  '<div class="tracker-note">آخر 30 يوم · '+r.symbols+' عملة · فريم 15د · سيولة يومية فوق 1,000,000 USDT · العملات المستقرة مستبعدة · وقف 2% · هدف 4%</div>';
}
async function news(){let d=await get("/api/news");$("#app").innerHTML='<div class="hero"><h1>📰 الأخبار</h1></div><div class="grid">'+d.items.map(x=>'<div class="card"><b>'+x.title+'</b><p class="muted">'+x.time+"</p></div>").join("")+"</div>"}
async function blog(){let d=await get("/api/blog");$("#app").innerHTML='<div class="hero"><h1>✎ المدونة</h1><p class="muted">مقالات التداول والتحليل</p></div><div class="grid">'+((d.items||[]).map(x=>'<article class="card"><h3>'+x.title+'</h3><p class="muted">'+x.excerpt+'</p><button class="frame" onclick="readBlog(\''+encodeURIComponent(x.slug)+'\')">قراءة المقال</button></article>').join("")||'<div class="loading">لا توجد مقالات منشورة</div>')+"</div>"}
async function readBlog(slug){let d=await get("/api/blog/"+decodeURIComponent(slug));if(d.error){simple("المدونة",d.error);return}$("#app").innerHTML='<div class="hero"><h1>'+d.title+'</h1><p class="muted">'+d.excerpt+'</p></div><article class="card article">'+d.body.replace(/\n/g,"<br>")+'</article><button class="frame" onclick="blog()">← المدونة</button>'}
function simple(t,x){$("#app").innerHTML='<div class="hero"><h1>'+t+'</h1><p class="muted">'+x+'</p></div>'}
async function account(){let m=await get("/api/auth/me");if(m.authenticated){$("#app").innerHTML='<div class="hero"><h1>👤 الحساب</h1><p>'+m.user.email+'</p><p class="muted">الصلاحية: '+m.user.role+'</p><button class="frame" onclick="logout()">تسجيل خروج</button></div>';return}$("#app").innerHTML='<div class="hero"><h1>👤 الحساب</h1><div class="auth"><input id="email" type="email" placeholder="البريد الإلكتروني"><input id="password" type="password" placeholder="كلمة المرور — 8 أحرف على الأقل"><button class="frame" onclick="authLogin()">دخول</button><button class="frame" onclick="authRegister()">تسجيل حساب</button><p id="authmsg" class="muted"></p></div></div>'}
async function authLogin(){let d=await send("/api/auth/login","POST",{email:$("#email").value,password:$("#password").value});$("#authmsg").textContent=d.error||"تم الدخول";if(d.ok)account()}
async function authRegister(){let d=await send("/api/auth/register","POST",{email:$("#email").value,password:$("#password").value});$("#authmsg").textContent=d.error||"تم إنشاء الحساب، سجل الدخول";if(d.ok)$("#password").value=""}
async function logout(){await send("/api/auth/logout","POST",{});account()}
async function admin(){let m=await get("/api/auth/me");if(!m.authenticated){simple("⚙ الإدارة","سجل الدخول بحساب المدير أولاً");return}if(m.user.role!=="admin"){simple("⚙ الإدارة","ليس لديك صلاحية الإدارة");return}let s=await get("/api/admin/stats"),u=await get("/api/admin/users"),a=await get("/api/admin/blog/all"),sub=await get("/api/admin/subscriptions");$("#app").innerHTML='<div class="hero"><h1>⚙ الإدارة</h1><p>المستخدمون '+s.users+" · المقالات "+s.articles+" · الصفقات "+s.trades+" · طلبات معلقة "+s.pending_subscriptions+'</p><button class="frame" onclick="telegramTest()">اختبار Telegram</button></div><h3>الحسابات</h3><div class="grid">'+(u.items||[]).map(x=>'<div class="card"><b>'+x.email+'</b><p class="muted">'+x.role+" · "+(x.active?"نشط":"موقوف")+'</p><button class="frame" onclick="role('+x.id+',\''+x.role+'\')">'+(x.role==="admin"?"مستخدم":"مدير")+'</button> <button class="frame" onclick="activeUser('+x.id+','+x.active+')">'+(x.active?"إيقاف":"تفعيل")+"</button></div>").join("")+'</div><h3>إضافة مقال</h3><div class="card auth"><input id="bt" placeholder="عنوان المقال"><input id="bs" placeholder="الرابط slug"><input id="be" placeholder="وصف مختصر"><textarea id="bb" placeholder="محتوى المقال"></textarea><button class="frame" onclick="addBlog()">نشر المقال</button></div><h3>المقالات</h3><div class="grid">'+(a.items||[]).map(x=>'<div class="card"><b>'+x.title+'</b><p class="muted">'+(x.published?"منشور":"مخفي")+'</p><button class="frame" onclick="delBlog('+x.id+')">حذف</button></div>').join("")+'</div><h3>الاشتراكات</h3><div class="grid">'+(sub.items||[]).map(x=>'<div class="card"><b>'+x.email+'</b><p>'+x.plan+" · "+x.amount+" USDT · "+x.status+'</p><button class="frame" onclick="subStatus('+x.id+',\'approved\')">قبول</button> <button class="frame" onclick="subStatus('+x.id+',\'rejected\')">رفض</button></div>').join("")+"</div>"}
async function role(id,r){await send("/api/admin/users/"+id,"PATCH",{role:r==="admin"?"user":"admin"});admin()}async function activeUser(id,a){await send("/api/admin/users/"+id,"PATCH",{active:!a});admin()}
async function addBlog(){let d=await send("/api/admin/blog","POST",{title:$("#bt").value,slug:$("#bs").value,excerpt:$("#be").value,body:$("#bb").value,published:true});alert(d.error||"تم نشر المقال");admin()}
async function delBlog(id){if(confirm("حذف المقال؟")){await send("/api/admin/blog/"+id,"DELETE",{});admin()}}
async function subStatus(id,status){await send("/api/admin/subscriptions/"+id,"PATCH",{status});admin()}
async function telegramTest(){let d=await send("/api/admin/telegram/test","POST",{});alert(d.error||"تم إرسال اختبار Telegram")}
function home(){let h='<div class="hero"><h1>التداول الذكي PRO</h1><p class="muted">منصة تحليل أسواق — الافتراضي 5 دقائق</p>'+buttons()+'</div><div class="grid">';for(const[k,v]of Object.entries(markets))h+='<div class="card" onclick="page(\''+k+'\')"><h3>'+v+'</h3><p class="muted">عرض الفرص والتحليل</p></div>';h+="</div>";$("#app").innerHTML=h}
function page(p){location.hash=p;if(p==="home")home();else if(p==="scanner")scanner();else if(p==="analysts7")analysts7();else if(p==="tracker")tracker();else if(p==="news")news();else if(p==="blog")blog();else if(p==="account")account();else if(p==="admin")admin();else if(markets[p])market(p);else home()}
page(location.hash.slice(1)||"home");
const app=document.getElementById("app");
const drawer=document.getElementById("drawer"),backdrop=document.getElementById("backdrop"),modal=document.getElementById("modal"),modalContent=document.getElementById("modalContent"),toastEl=document.getElementById("toast");
const markets={spot:"السبوت",futures:"الفيوتشر",contracts:"العقود",us:"السوق الأمريكي",saudi:"السوق السعودي",forex:"الفوركس"};
const tfs=["15m","30m","1h","4h","1d","1w","1M"];
function toast(x){toastEl.textContent=x;toastEl.classList.add("show");setTimeout(function(){toastEl.classList.remove("show")},2600)}
function openModal(x){modalContent.innerHTML=x;modal.classList.add("show")}
function closeModal(){modal.classList.remove("show")}
document.getElementById("menuBtn").onclick=function(){drawer.classList.add("open");backdrop.classList.add("open")};
document.getElementById("closeMenu").onclick=function(){drawer.classList.remove("open");backdrop.classList.remove("open")};
backdrop.onclick=function(){drawer.classList.remove("open");backdrop.classList.remove("open")};
modal.onclick=function(e){if(e.target===modal||e.target.hasAttribute("data-close"))closeModal()};
document.querySelectorAll(".drawer a").forEach(function(a){a.onclick=function(){drawer.classList.remove("open");backdrop.classList.remove("open")}});
document.getElementById("supportOpen").onclick=function(){drawer.classList.remove("open");backdrop.classList.remove("open");supportModal()};

function home(){
app.innerHTML='<section class="hero"><div class="hero-card"><div class="eyebrow">منصة تداول منظمة وواضحة</div><h1>التداول الذكي <span style="color:var(--accent)">PRO</span></h1><p>منصة تجمع أقسام الأسواق في مكان واحد، مع حسابات ومتابعة وإدارة ودعم. <b>الصفحة الرئيسية بدون أي صفقات.</b></p><div class="actions"><a class="btn primary" href="/account">إنشاء حساب</a><a class="btn" href="/account">تسجيل الدخول</a><button class="btn" onclick="supportModal()">تواصل مع الدعم</button></div><div class="grid" style="margin-top:28px;text-align:right"><div class="feature"><b>📊 أسواق مستقلة</b><span class="muted">كل سوق له قسمه الخاص بدون خلط.</span></div><div class="feature"><b>🏅 ترتيب الصفقات</b><span class="muted">ترقيم وميداليات وترتيب حسب التغير.</span></div><div class="feature"><b>🔐 حساب وإدارة</b><span class="muted">تسجيل دخول وإدارة ومحتوى منظم.</span></div></div></div></section>';
}
async function marketPage(key){
let tf=new URLSearchParams(location.search).get("tf")||"15m";if(!tfs.includes(tf))tf="15m";
let buttons=tfs.map(function(x){return '<button class="tf '+(x===tf?"active":"")+'" data-tf="'+x+'">'+x+'</button>'}).join("");
app.innerHTML='<section><div class="market-head"><div><h1>'+markets[key]+'</h1><p>الصفقات فقط — مرتبة حسب نسبة التغير</p></div></div><div class="timeframes">'+buttons+'</div><div id="trades" class="trade-list"><div class="empty">جاري الفحص...</div></div></section>';
document.querySelectorAll(".tf").forEach(function(b){b.onclick=function(){marketPageWithTf(key,b.dataset.tf)}});
await loadTrades(key,tf);
}
async function marketPageWithTf(key,tf){history.replaceState({},"","/market/"+key+"?tf="+tf);await marketPage(key)}
function money(v){return v==null?"—":Number(v).toLocaleString("en-US",{maximumFractionDigits:8})}
function pct(v){return v==null?"—":(Number(v)>0?"+":"")+Number(v).toFixed(2)+"%"}
function tradeCard(t){
let side=t.side==="SELL"?"بيع":"شراء";
return '<article class="trade"><div class="trade-top"><div class="rank">'+(t.medal||("#"+t.rank))+'</div><div class="symbol">'+t.symbol+'</div><span class="side '+(t.side==="SELL"?"sell":"buy")+'">'+side+'</span><span class="tag">'+(t.tag||"—")+'</span></div><div class="trade-meta"><div class="metric"><small>التغير</small><b>'+pct(t.change_pct)+'</b></div><div class="metric"><small>نسبة الربح</small><b>'+pct(t.profit_pct)+'</b></div><div class="metric"><small>نسبة الخسارة</small><b>'+pct(t.loss_pct)+'</b></div><div class="metric"><small>AI</small><b>'+(t.ai_pct==null?"—":Number(t.ai_pct).toFixed(0)+"%")+'</b></div></div><div class="targets"><div class="level"><small>الدخول</small>'+money(t.entry)+'</div><div class="level"><small>TP1</small>'+money(t.tp1)+'</div><div class="level"><small>TP2</small>'+money(t.tp2)+'</div><div class="level"><small>TP3</small>'+money(t.tp3)+'</div><div class="level"><small>SL</small>'+money(t.sl)+'</div></div></article>';
}
async function loadTrades(key,tf){
let box=document.getElementById("trades");
try{
 let url=key==="spot"?"/api/strategy/scan?market=spot&timeframe="+encodeURIComponent(tf):"/api/trades/"+key+"?timeframe="+encodeURIComponent(tf);
 let r=await fetch(url);let d=await r.json();
 box.innerHTML=d.trades&&d.trades.length?d.trades.map(tradeCard).join(""):'<div class="empty">لا توجد صفقات مطابقة للاستراتيجية حالياً.</div>';
}catch(e){box.innerHTML='<div class="empty">تعذر تحميل الصفقات حالياً.</div>'}
}
function account(){
app.innerHTML='<section class="form-card" id="accountBox"><h1>الحساب</h1><div id="accountContent"><div class="muted">جاري التحميل...</div></div></section>';
fetch("/api/me").then(function(r){return r.json()}).then(function(d){
if(d.user){document.getElementById("accountContent").innerHTML='<p>مرحباً <b>'+d.user.name+'</b></p><p class="muted">'+d.user.email+'</p><div class="actions" style="justify-content:flex-start"><button class="btn primary" onclick="logout()">تسجيل الخروج</button>'+(d.user.is_admin?'<a class="btn" href="/admin">الإدارة</a>':"")+'</div>'}
else{document.getElementById("accountContent").innerHTML='<div class="actions" style="margin-bottom:15px"><button class="btn primary" onclick="showLogin()">تسجيل الدخول</button><button class="btn" onclick="showRegister()">إنشاء حساب</button></div><div id="accountForm"></div>';showLogin()}
})
}
function showLogin(){document.getElementById("accountForm").innerHTML='<form onsubmit="login(event)"><div class="field"><label>البريد</label><input name="email" type="email" required></div><div class="field"><label>كلمة المرور</label><input name="password" type="password" required></div><button class="btn primary">دخول</button></form>'}
function showRegister(){document.getElementById("accountForm").innerHTML='<form onsubmit="register(event)"><div class="field"><label>الاسم</label><input name="name" required></div><div class="field"><label>البريد</label><input name="email" type="email" required></div><div class="field"><label>كلمة المرور</label><input name="password" type="password" minlength="6" required></div><button class="btn primary">إنشاء الحساب</button></form>'}
async function login(e){e.preventDefault();let r=await fetch("/api/login",{method:"POST",body:new FormData(e.target)}),d=await r.json();toast(d.message);if(r.ok)location.reload()}
async function register(e){e.preventDefault();let r=await fetch("/api/register",{method:"POST",body:new FormData(e.target)}),d=await r.json();toast(d.message);if(r.ok)location.reload()}
async function logout(){await fetch("/api/logout",{method:"POST"});location.reload()}
function supportModal(){openModal('<h2>تواصل مع الدعم</h2><p class="muted">أرسل رسالتك وسيتم حفظها للإدارة.</p><form onsubmit="sendSupport(event)"><div class="field"><label>الاسم</label><input name="name" required></div><div class="field"><label>البريد</label><input name="email" type="email" required></div><div class="field"><label>الرسالة</label><textarea name="body" required></textarea></div><button class="btn primary">إرسال</button></form>')}
async function sendSupport(e){e.preventDefault();let r=await fetch("/api/support",{method:"POST",body:new FormData(e.target)}),d=await r.json();toast(d.message);if(r.ok)closeModal()}
function forum(){app.innerHTML='<section class="form-card"><h1>المنتدى</h1><p class="muted">مساحة مستقلة للنقاشات والمحتوى المجتمعي.</p><button class="btn primary" onclick="supportModal()">تواصل مع الدعم</button></section>'}
async function admin(){
let marketsOptions=Object.keys(markets).map(function(k){return '<option value="'+k+'">'+markets[k]+'</option>'}).join("");
let tfOptions=tfs.map(function(x){return '<option>'+x+'</option>'}).join("");
app.innerHTML='<section><h1>الإدارة</h1><div id="stats" class="admin-grid"><div class="empty">جاري التحميل...</div></div><div class="grid" style="margin-top:14px"><div class="form-card" style="margin:0;max-width:none"><h2>إضافة صفقة</h2><form onsubmit="addTrade(event)"><div class="field"><label>السوق</label><select name="market">'+marketsOptions+'</select></div><div class="field"><label>الرمز</label><input name="symbol" required></div><div class="field"><label>الاتجاه</label><select name="side"><option>BUY</option><option>SELL</option></select></div><div class="field"><label>الفريم</label><select name="timeframe">'+tfOptions+'</select></div><div class="field"><label>التغير %</label><input name="change_pct" type="number" step="any" required></div><div class="field"><label>الربح %</label><input name="profit_pct" type="number" step="any" required></div><div class="field"><label>الخسارة %</label><input name="loss_pct" type="number" step="any" required></div><div class="field"><label>AI %</label><input name="ai_pct" type="number" step="any" required></div><div class="field"><label>التاج</label><input name="tag" placeholder="قوي"></div><div class="field"><label>Entry</label><input name="entry" type="number" step="any" required></div><div class="field"><label>TP1</label><input name="tp1" type="number" step="any" required></div><div class="field"><label>TP2</label><input name="tp2" type="number" step="any" required></div><div class="field"><label>TP3</label><input name="tp3" type="number" step="any" required></div><div class="field"><label>SL</label><input name="sl" type="number" step="any" required></div><button class="btn primary">حفظ الصفقة</button></form></div><div class="form-card" style="margin:0;max-width:none"><h2>رسالة منبثقة</h2><form onsubmit="addMessage(event)"><div class="field"><label>العنوان</label><input name="title" required></div><div class="field"><label>النص</label><textarea name="body" required></textarea></div><button class="btn primary">نشر الرسالة</button></form></div></div></section>';
let r=await fetch("/api/admin/summary");if(r.ok){let d=await r.json();document.getElementById("stats").innerHTML='<div class="stat">المستخدمون<b>'+d.users+'</b></div><div class="stat">الصفقات<b>'+d.trades+'</b></div><div class="stat">دعم جديد<b>'+d.new_support+'</b></div>'}else location.href="/account"
}
async function addTrade(e){e.preventDefault();let r=await fetch("/api/admin/trades",{method:"POST",body:new FormData(e.target)}),d=await r.json();toast(d.message||"تم الحفظ");if(r.ok)e.target.reset()}
async function addMessage(e){e.preventDefault();let r=await fetch("/api/admin/message",{method:"POST",body:new FormData(e.target)}),d=await r.json();toast(d.message||"تم النشر");if(r.ok)e.target.reset()}
function route(){let p=location.pathname.split("/").filter(Boolean);if(p[0]==="market"&&markets[p[1]])return marketPage(p[1]);if(p[0]==="account")return account();if(p[0]==="forum")return forum();if(p[0]==="admin")return admin();return home()}
route();
fetch("/api/message").then(function(r){return r.json()}).then(function(d){if(d.message&&!sessionStorage.getItem("popup_seen")){sessionStorage.setItem("popup_seen","1");openModal('<h2>'+d.message.title+'</h2><p class="muted" style="line-height:1.9">'+d.message.body+'</p><button class="btn primary" data-close>حسناً</button>')}}).catch(function(){});

(function(){
"use strict";
var $=function(s){return document.querySelector(s);};
function msg(t){var e=$("#authMsg");if(e)e.textContent=t;}
function post(url,data){return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify(data)}).then(async function(r){var j=await r.json().catch(function(){return {}});if(!r.ok)throw new Error(j.error||"تعذر تنفيذ الطلب");return j;});}
function bindAuth(){
 var sf=$("#signupForm"),lf=$("#loginForm");
 if(sf)sf.addEventListener("submit",function(e){e.preventDefault();var f=new FormData(sf);msg("جاري إنشاء الحساب…");post("/api/auth/signup",{username:f.get("username"),password:f.get("password")}).then(function(){msg("تم إنشاء الحساب وتسجيل الدخول بنجاح.");setTimeout(function(){location.href="/"},500);}).catch(function(e){msg(e.message);});});
 if(lf)lf.addEventListener("submit",function(e){e.preventDefault();var f=new FormData(lf);msg("جاري تسجيل الدخول…");post("/api/auth/login",{username:f.get("username"),password:f.get("password")}).then(function(j){msg("تم الدخول بنجاح.");setTimeout(function(){location.href=j.role==="admin"?"/admin":"/"},500);}).catch(function(e){msg(e.message);});});
 var ab=$("#adminPanel"),am=$("#adminMsg");
 if(ab||am)fetch("/api/admin/status",{cache:"no-store",credentials:"same-origin"}).then(function(r){if(!r.ok)throw new Error();return r.json();}).then(function(){if(am)am.textContent="تم التحقق: أنت مدير النظام.";if(ab)ab.style.display="block";}).catch(function(){if(am)am.textContent="غير مصرح. سجّل دخولك بحساب المدير أولاً.";});
 var lo=$("#logoutBtn");if(lo)lo.addEventListener("click",function(){fetch("/api/auth/logout",{method:"POST",credentials:"same-origin"}).then(function(){location.href="/login";});});
 var n=$("#newsCards");if(n)fetch("/api/news?x="+Date.now(),{cache:"no-store"}).then(r=>r.json()).then(function(j){n.innerHTML=(j.items||[]).map(function(x){return '<article class="card"><span class="rank">'+String(x.source||"مصدر")+'</span><h3>'+esc(x.title)+'</h3><p class="card-foot">'+esc(x.published||"")+'</p>'+(x.url?'<a class="primary" target="_blank" rel="noopener" href="'+esc(x.url)+'">المصدر ↗</a>':"")+'</article>';}).join("")||'<div class="empty">لا توجد أخبار متاحة حالياً.</div>';}).catch(function(){n.innerHTML='<div class="empty">تعذر جلب الأخبار حالياً.</div>';});
 var b=$("#blogCards");if(b)fetch("/api/blog?x="+Date.now(),{cache:"no-store"}).then(r=>r.json()).then(function(j){b.innerHTML=(j.items||[]).map(function(x){return '<article class="card"><span class="eyebrow">SMART TRADING</span><h3>'+esc(x.title)+'</h3><p class="card-foot">'+esc(x.text)+'</p></article>';}).join("")||'<div class="empty">لا توجد مقالات.</div>';}).catch(function(){b.innerHTML='<div class="empty">تعذر جلب المدونة.</div>';});
}
function esc(v){return String(v==null?"":v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bindAuth);else bindAuth();
})();
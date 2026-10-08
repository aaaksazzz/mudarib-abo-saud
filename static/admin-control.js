(function(){
"use strict";
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url,opt){const r=await fetch(url,{cache:"no-store",credentials:"same-origin",...(opt||{})});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.message||"غير مصرح");return j}
async function load(){
 try{
  const s=await api("/api/admin/summary"); $("#summary").innerHTML=[
   ["المستخدمون",s.users],["الصفقات",s.trades],["رسائل الدعم",s.new_support]
  ].map(x=>'<div class="metric"><span>'+x[0]+'</span><b>'+x[1]+'</b></div>').join("");
  const sec=await api("/api/admin/access");
  $("#sections").innerHTML=sec.sections.map(x=>'<article class="card" style="padding:16px"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center"><div><b>'+esc(x.name)+'</b><p>'+esc(x.key)+'</p></div><button class="primary" data-lock="'+esc(x.key)+'">'+(x.enabled?"إغلاق القسم":"فتح القسم")+'</button></div></article>').join("");
  document.querySelectorAll("[data-lock]").forEach(b=>b.onclick=async()=>{b.disabled=true;await api("/api/admin/access",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:b.dataset.lock,enabled:b.textContent.includes("إغلاق")?false:true})});load()});
  const u=await api("/api/admin/users");
  $("#users").innerHTML=u.users.map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.email)+'</td><td>'+esc(x.plan||"بدون")+'</td><td>'+esc(x.expires_at||"—")+'</td><td><button class="primary" data-sub="'+x.id+'">اشتراك</button></td></tr>').join("");
  document.querySelectorAll("[data-sub]").forEach(b=>b.onclick=async()=>{const days=prompt("مدة الاشتراك بالأيام: 7 أو 15 أو 30","30");if(!days)return;b.disabled=true;const fd=new FormData();fd.append("user_id",b.dataset.sub);fd.append("days",days);await api("/api/admin/subscription",{method:"POST",body:fd});load()});
  $("#adminState").textContent="مدير مصادق عليه";
 }catch(e){$("#adminState").textContent=e.message;setTimeout(()=>location.href="/login",900)}
}
$("#logout").onclick=async()=>{await api("/api/logout",{method:"POST"});location.href="/login"};load();
})();
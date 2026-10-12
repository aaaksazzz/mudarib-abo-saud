(function(){
"use strict";
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url,opt){const r=await fetch(url,{cache:"no-store",credentials:"same-origin",...(opt||{})});const j=await r.json().catch(()=>({}));if(!r.ok)throw Error(j.message||"تعذر تنفيذ الطلب");return j}
function renderSections(items){$("#sections").innerHTML=items.map(x=>'<article class="card market-access-card" style="padding:16px"><div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap"><div><b>'+esc(x.name)+'</b><p style="margin:6px 0 0;color:#8fa8c2;font-size:12px">'+esc(x.key)+'</p><span style="display:inline-block;margin-top:9px;padding:5px 9px;border-radius:99px;border:1px solid '+(x.enabled?'#287e65':'#7e4050')+';background:'+(x.enabled?'#12382f':'#351d29')+';color:'+(x.enabled?'#7cf0c5':'#ffb8c3')+';font-size:11px">'+(x.enabled?'السوق مفتوح':'السوق مغلق')+'</span></div><button class="'+(x.enabled?'ghost-btn':'primary')+'" data-lock="'+esc(x.key)+'" data-enabled="'+(x.enabled?'1':'0')+'">'+(x.enabled?'إغلاق السوق':'فتح السوق')+'</button></div></article>').join("");}
async function load(){
 try{
  const s=await api("/api/admin/summary");
  $("#summary").innerHTML=[["المستخدمون",s.users],["الصفقات",s.trades],["رسائل الدعم",s.new_support]].map(x=>'<div class="metric"><span>'+x[0]+'</span><b>'+esc(x[1])+'</b></div>').join("");
  const sec=await api("/api/admin/access");renderSections(sec.sections||[]);
  const u=await api("/api/admin/users");
  $("#users").innerHTML=(u.users||[]).map(x=>'<tr><td>'+esc(x.name)+'</td><td>'+esc(x.email)+'</td><td>'+esc(x.plan||"بدون")+'</td><td>'+esc(x.expires_at||"—")+'</td><td><button class="primary" data-sub="'+esc(x.id)+'">إدارة الاشتراك</button></td></tr>').join("");
  $("#adminState").textContent="مدير مصادق عليه";
 }catch(e){$("#adminState").textContent=e.message;if(/مصرح|صلاحية|403/i.test(e.message))setTimeout(()=>location.href="/login?next=/admin",900);}
}
document.addEventListener("click",async e=>{
 const b=e.target.closest("[data-lock]");if(b){
  const key=b.dataset.lock,enabled=b.dataset.enabled!=="1";
  b.disabled=true;b.textContent="جارٍ الحفظ…";
  try{await api("/api/admin/access",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key,enabled})});await load();}
  catch(err){b.disabled=false;b.textContent=enabled?"فتح السوق":"إغلاق السوق";alert("ما قدرنا نحفظ التغيير: "+err.message);}
  return;
 }
 const sub=e.target.closest("[data-sub]");if(sub){
  const days=prompt("مدة الاشتراك بالأيام: 7 أو 15 أو 30","30");if(!days)return;
  sub.disabled=true;
  try{const fd=new FormData();fd.append("user_id",sub.dataset.sub);fd.append("days",days);await api("/api/admin/subscription",{method:"POST",body:fd});await load();}
  catch(err){sub.disabled=false;alert("تعذر تحديث الاشتراك: "+err.message);}
 }
});
$("#logout").addEventListener("click",async()=>{try{await api("/api/logout",{method:"POST"});}finally{location.href="/login";}});
load();
})();
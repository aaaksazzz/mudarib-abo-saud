(()=>{
"use strict";
const KEY="stp-signal-lab-v1",INTERVAL=15*60*1000,MAX_AGE=10*24*60*60*1000;
const $=id=>document.getElementById(id);
let signals=load(),busy=false;
function load(){try{const x=JSON.parse(localStorage.getItem(KEY)||"[]");return Array.isArray(x)?x:[]}catch{return []}}
function save(){localStorage.setItem(KEY,JSON.stringify(signals))}
function toast(s){$("toast").textContent=s;$("toast").classList.add("show");setTimeout(()=>$("toast").classList.remove("show"),2600)}
function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function num(v){return Number(v)}
function valid(s){const long=s.side==="BUY";return s.entry>0&&s.stop>0&&s.tp1>0&&s.tp2>0&&s.tp3>0&&(long?s.stop<s.entry&&s.entry<s.tp1&&s.tp1<s.tp2&&s.tp2<s.tp3:s.stop>s.entry&&s.entry>s.tp1&&s.tp1>s.tp2&&s.tp2>s.tp3)}
function localInputNow(){const d=new Date(Date.now()-new Date().getTimezoneOffset()*60000);return d.toISOString().slice(0,16)}
function signedMove(entry,exit,side){return (exit/entry-1)*(side==="BUY"?1:-1)*100}
function netFor(s,kind){const r=signedMove(s.entry,s[kind],s.side);return r-s.fee}
function resultFor(s){const st=s.status,risk=Math.abs(signedMove(s.entry,s.stop,s.side));if(st==="tp3_hit")return (signedMove(s.entry,s.tp1,s.side)+signedMove(s.entry,s.tp2,s.side)+signedMove(s.entry,s.tp3,s.side))/3-s.fee;if(st==="stopped_after_tp2")return (signedMove(s.entry,s.tp1,s.side)+signedMove(s.entry,s.tp2,s.side)-risk)/3-s.fee;if(st==="stopped_after_tp1")return (signedMove(s.entry,s.tp1,s.side)-2*risk)/3-s.fee;if(st==="stopped")return -risk-s.fee;return null}
function label(s){return ({active:"قيد المتابعة",unfilled:"الدخول لم يتفعل",tp1_hit:"وصل TP1",tp2_hit:"وصل TP2",tp3_hit:"وصل TP3",stopped:"وقف قبل TP1",stopped_after_tp1:"وقف بعد TP1",stopped_after_tp2:"وقف بعد TP2",expired:"انتهت مدة المتابعة"})[s.status]||"قيد المتابعة"}
function statusClass(s){return ["tp1_hit","tp2_hit","tp3_hit","stopped_after_tp1","stopped_after_tp2"].includes(s.status)?"good":s.status==="stopped"?"bad":""}
function summarize(items){const done=items.filter(s=>resultFor(s)!==null),filled=items.filter(s=>!!s.filledAt).length,tp1=items.filter(s=>Number(s.maxTarget||0)>=1).length,stops=items.filter(s=>s.status==="stopped").length;const net=done.reduce((a,s)=>a+resultFor(s),0);return {total:items.length,filled:filled.length,tp1,stops,net,closed:done.length}}
function render(){
 const all=summarize(signals);$("s-total").textContent=all.total;$("s-filled").textContent=all.filled;$("s-tp1").textContent=all.tp1;$("s-stop").textContent=all.stops;$("s-net").textContent=all.net.toFixed(2)+"%";
 $("s-net").style.color=all.net>=0?"#56d6ad":"#ff747d";
 const groups=["Darwin Lab","HafizeBot","مصدر آخر"];
 $("provider-stats").innerHTML=groups.map(p=>{const x=summarize(signals.filter(s=>s.provider===p));const winRate=x.closed?((signals.filter(s=>s.provider===p&&resultFor(s)>0).length/x.closed)*100).toFixed(1)+"%":"—";return '<div class="provider"><b>'+esc(p)+'</b><span>التوصيات: '+x.total+' · TP1: '+x.tp1+' · وقف قبل TP1: '+x.stops+'</span><span>مغلقة: '+x.closed+' · نسبة صافي الربح: '+winRate+' · صافي افتراضي: '+x.net.toFixed(2)+'%</span></div>'}).join("");
 const rows=$("rows");if(!signals.length){rows.innerHTML='<tr><td colspan="9" class="empty">لا توجد توصيات مسجلة بعد.</td></tr>';return}
 rows.innerHTML=[...signals].sort((a,b)=>b.sentAt-a.sentAt).map(s=>{const r=resultFor(s);return '<tr><td>'+esc(s.provider)+'</td><td><b>'+esc(s.symbol)+'</b></td><td>'+ (s.side==="BUY"?"شراء":"بيع")+'</td><td>'+esc(s.entry)+'</td><td>'+esc(s.stop)+'</td><td><span class="pill '+statusClass(s)+'">'+label(s)+'</span></td><td style="color:'+(r===null?"#8b9bb0":r>=0?"#56d6ad":"#ff747d")+'">'+(r===null?"—":(r>0?"+":"")+r.toFixed(2)+"%")+'</td><td>'+new Date(s.sentAt).toLocaleString("ar-SA")+'</td><td><button class="btn danger" data-delete="'+esc(s.id)+'">حذف</button></td></tr>'}).join("");
 rows.querySelectorAll("[data-delete]").forEach(b=>b.addEventListener("click",()=>{if(confirm("حذف هذه التوصية من سجل هذا الجهاز؟")){signals=signals.filter(s=>s.id!==b.dataset.delete);save();render()}}));
}
async function fetchCandles(symbol,start){const u="/api/signal-lab/klines?symbol="+encodeURIComponent(symbol)+"&startTime="+encodeURIComponent(start);const r=await fetch(u,{cache:"no-store"});const d=await r.json();if(!r.ok)throw Error(d.error||"تعذر جلب الشموع");return d.candles||[]}
function trackOne(s,candles,now){
 if(!["active","tp1_hit","tp2_hit"].includes(s.status))return false;
 let changed=false,filled=!!s.filledAt,lastClose=0;
 const start=Math.ceil(s.sentAt/INTERVAL)*INTERVAL;
 for(const c of candles){const t=Number(c[0]),high=Number(c[1]),low=Number(c[2]),close=Number(c[3]);if(t<start||close>now)continue;lastClose=close;
  if(!filled){const entryTouched=s.side==="BUY"?low<=s.entry:high>=s.entry;if(!entryTouched)continue;filled=true;s.filledAt=t;changed=true}
  const stopHit=s.side==="BUY"?low<=s.stop:high>=s.stop;
  const targets=[s.tp1,s.tp2,s.tp3].map(v=>s.side==="BUY"?high>=v:low<=v);
  if(stopHit){s.status=s.maxTarget>=2?"stopped_after_tp2":s.maxTarget>=1?"stopped_after_tp1":"stopped";s.closedAt=close;changed=true;break}
  const hit=targets[2]?3:targets[1]?2:targets[0]?1:0;
  if(hit>s.maxTarget){s.maxTarget=hit;s.status=hit===3?"tp3_hit":hit===2?"tp2_hit":"tp1_hit";changed=true}
  if(hit===3){s.closedAt=close;break}
 }
 if(!filled&&now-s.sentAt>48*60*60*1000){s.status="unfilled";s.closedAt=now;changed=true}
 else if(filled&&now-s.sentAt>MAX_AGE&&s.status!=="tp3_hit"){s.status="expired";s.closedAt=now;changed=true}
 return changed;
}
async function refresh(){
 if(busy||!signals.some(s=>s.status==="active"))return;
 busy=true;$("last-check").textContent="جارٍ تحديث الشموع…";
 try{
  const now=Date.now(),active=signals.filter(s=>["active","tp1_hit","tp2_hit"].includes(s.status)),symbols=[...new Set(active.map(s=>s.symbol))];let changed=0;
  for(const symbol of symbols){const batch=active.filter(s=>s.symbol===symbol);const oldest=Math.min(...batch.map(s=>s.sentAt));if(now-oldest>MAX_AGE){batch.forEach(s=>{if(s.status==="active"){s.status=s.filledAt?"expired":"unfilled";s.closedAt=now;changed++}});continue}
   const candles=await fetchCandles(symbol,Math.max(oldest,now-MAX_AGE));for(const s of batch)if(trackOne(s,candles,now))changed++;
  }
  if(changed)save();$("last-check").textContent="آخر تحديث: "+new Date().toLocaleTimeString("ar-SA");render();
 }catch(e){$("last-check").textContent="تعذر التحديث: "+e.message}
 finally{busy=false}
}
$("signal-form").addEventListener("submit",e=>{
 e.preventDefault();const s={id:crypto.randomUUID?crypto.randomUUID():String(Date.now())+Math.random(),provider:$("provider").value,symbol:$("symbol").value.trim().toUpperCase(),side:$("side").value,sentAt:new Date($("sentAt").value).getTime(),entry:num($("entry").value),stop:num($("stop").value),tp1:num($("tp1").value),tp2:num($("tp2").value),tp3:num($("tp3").value),fee:num($("fee").value),status:"active",maxTarget:0,filledAt:null,closedAt:null};
 if(!Number.isFinite(s.sentAt)||s.sentAt>Date.now()+60000||!valid(s)){toast("راجع الأسعار: الشراء يجب أن يكون الوقف أقل من الدخول والأهداف تصاعدية، والعكس للبيع.");return}
 if(!/^[A-Z0-9]{2,26}USDT$/.test(s.symbol)){toast("اكتب رمز عقد USDT مثل BTCUSDT");return}
 if(signals.some(x=>x.provider===s.provider&&x.symbol===s.symbol&&x.sentAt===s.sentAt)){toast("هذه التوصية مسجلة مسبقاً");return}
 signals.push(s);save();render();e.target.reset();$("sentAt").value=localInputNow();$("symbol").value="BTCUSDT";$("fee").value="0.10";toast("تم حفظ التوصية وبدء المتابعة");refresh();
});
$("refresh").addEventListener("click",refresh);
$("export").addEventListener("click",()=>{const header=["provider","symbol","side","sent_at","entry","stop","tp1","tp2","tp3","status","net_pct"];const lines=[header.join(","),...signals.map(s=>[s.provider,s.symbol,s.side,new Date(s.sentAt).toISOString(),s.entry,s.stop,s.tp1,s.tp2,s.tp3,s.status,resultFor(s)??""].map(v=>'"'+String(v).replace(/"/g,'""')+'"').join(","))];const blob=new Blob(["\ufeff"+lines.join("\r\n")],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="signal-lab-results.csv";a.click();URL.revokeObjectURL(a.href)});
$("sentAt").value=localInputNow();render();refresh();setInterval(refresh,120000);
})();
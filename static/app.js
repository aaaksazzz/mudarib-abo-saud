(function(){
"use strict";
var $=function(s){return document.querySelector(s);};
var routes={home:"/",technical:"/static/technical.html?v=20261010-clickfix",radar:"/static/radar.html?v=20261008-core",gold:"/static/gold.html?v=20261008-core",results:"/static/results.html?v=20261008-core",news:"/static/news.html?v=20261008-core",blog:"/static/blog.html?v=20261010-seo",spot:"/static/spot.html?v=20261008-core",futures:"/static/futures.html?v=20261008-core",alpha:"/static/alpha.html?v=20261010-alpha",whales:"/static/whales.html?v=20261010-whales",contracts:"/static/contracts.html?v=20261008-core",us:"/static/us.html?v=20261008-core",saudi:"/static/saudi.html?v=20261008-core",forex:"/static/forex.html?v=20261008-core",signup:"/static/signup.html?v=20261008-core",login:"/static/login.html?v=20261008-core",admin:"/static/admin.html?v=20261008-core"};
var page=document.body.getAttribute("data-page")||"home",market=document.body.getAttribute("data-market")||"",loading=false,trackingTimer=null;
var selectedTimeframe="15m";
var timeframes=[["15m","15 دقيقة"],["30m","30 دقيقة"],["1h","ساعة"],["4h","4 ساعات"],["1d","يومي"],["1w","أسبوعي"],["1M","شهري"]];
var selectedTechnicalMarket="spot";
var selectedTechnicalMethod="all";
var technicalMethods=[["all","✦","التوافق العام","عرض فرص السوق العامة دون نسبتها إلى منهج واحد."],["price-action","📈","برايس أكشن","قراءة حركة السعر والقمم والقيعان والاختراقات بدون الاعتماد الأساسي على المؤشرات."],["smc","🏦","SMC — مفاهيم السيولة","هيكل السوق، BOS وCHOCH، مناطق الطلب المؤسسي، واصطياد السيولة."],["ict","🎯","ICT","توقيت الجلسات، السيولة، FVG، مناطق الخصم والعلاوة، ومناطق الدخول المحتملة."],["classical","📐","التحليل الكلاسيكي","الدعم والمقاومة، الترند لاين، القنوات، والاختراق وإعادة الاختبار."],["candles","🕯️","الشموع اليابانية","ابتلاع شرائي/بيعي، دوجي، مطرقة، نجمة الصباح والمساء."],["patterns","🔺","النماذج السعرية","رأس وكتفين، قمم وقيعان مزدوجة، مثلثات، أعلام وأوتاد."],["indicators","📊","المؤشرات الفنية","المتوسطات EMA/SMA، RSI، MACD، Stochastic، ADX وBollinger Bands."],["fibonacci","🌀","فيبوناتشي","التصحيحات والامتدادات ومناطق التقاء النسب مع الدعم والمقاومة."],["harmonic","🦋","الهارمونيك","نماذج Gartley وBat وButterfly وCrab باستخدام نسب فيبوناتشي."],["elliott","🌊","موجات إليوت","تحليل الموجات الدافعة والتصحيحية والسيناريوهات المحتملة للاتجاه."],["wyckoff","🐋","وايكوف","التجميع والتصريف، الاختبار، Spring وUpthrust وسلوك العرض والطلب."],["volume","📦","الحجم وVSA","مقارنة الحجم بحركة السعر والمدى لاكتشاف قوة الدفع أو ضعف الحركة."],["order-flow","🧾","تدفق الأوامر والسيولة","قراءة دفتر الأوامر والاختلالات والضغط الشرائي/البيعي عند توفر بياناتها."],["ichimoku","☁️","إيشيموكو","السحابة والاتجاه والدعم والمقاومة وخطوط التحول والأساس."],["dow-mtf","🧭","داو وتعدد الفريمات","تأكيد الاتجاه عبر القمم والقيعان وربط الفريم الصغير بالفريم الأكبر."],["quant","🧮","التحليل الكمي والإحصائي","اختبار القواعد تاريخيًا وقياس العائد والمخاطر ونسبة النجاح خارج العينة."],["gann","⏱️","غان ودورات الزمن","دراسة دورات الزمن والزوايا السعرية كإطار تحليلي تجريبي."]];
var pageTechnicalMethod="";
try{var initialMethod=document.body.getAttribute("data-tech-method")||new URLSearchParams(window.location.search).get("method");if(technicalMethods.some(function(x){return x[0]===initialMethod;})){pageTechnicalMethod=initialMethod;selectedTechnicalMethod=initialMethod;}}catch(e){}
var technicalMarkets=[["spot","₿","سبوت"],["futures","⚡","فيوتشر"],["alpha","α","تحليل Alpha"],["contracts","◉","العقود الأمريكية"],["us","🇺🇸","الأسهم الأمريكية"],["saudi","🇸🇦","السعودي / تاسي"],["forex","🥇","فوركس وذهب"]];
try{var initialTechnicalMarket=new URLSearchParams(window.location.search).get("market");if(technicalMarkets.some(function(x){return x[0]===initialTechnicalMarket;}))selectedTechnicalMarket=initialTechnicalMarket;}catch(e){}
function esc(v){return String(v==null?"":v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}

function displaySymbol(x){var s=String((x&&x.symbol)||"").trim().toUpperCase();var m=String((x&&x.market)||market||"").toLowerCase();if((m==="spot"||m==="futures")&&s&&!/USDT$/.test(s)&&/^[A-Z0-9]+$/.test(s)){s=s+"USDT";}return s;}function go(s){var marketKeys=["spot","futures","alpha","contracts","us","saudi","forex"];if(page==="technical"&&marketKeys.indexOf(s)>=0){window.location.href="/static/technical-"+encodeURIComponent(pageTechnicalMethod||"price-action")+".html?market="+encodeURIComponent(s);return;}if(routes[s]){window.location.href=routes[s];}}
function closeMenu(){var s=$("#sidebar"),o=$("#overlay");if(s)s.classList.remove("open");if(o)o.classList.remove("show");}
function getJSON(url){return fetch(url,{cache:"no-store"}).then(function(r){if(!r.ok)throw new Error("HTTP "+r.status);return r.json();});}
function signalScore(x){return Number(x.recommendation_score||x.ai_pct||x.ai||x.analysis_score||0);}
function rankMark(i){return i===0?"👑":i===1?"🥈":i===2?"🥉":"#"+(i+1);}
function card(x,i){
 var sell=String(x.direction||x.side||"").toUpperCase()==="SELL";
 var score=signalScore(x),w=Math.max(0,Math.min(100,score)),mark=rankMark(i),tier=i===0?"rank-crown":i===1?"rank-silver":i===2?"rank-bronze":"rank-normal";
 var stamp=Number(x.detected_at||x.updated_at||0),age=stamp?Math.max(0,Math.floor((Date.now()/1000-stamp)/60)):null;
 var current=Number(x.current_price||x.live_price||x.price||x.entry||0);
 var targets=Array.isArray(x.targets)?x.targets.filter(function(v){return v!==null&&v!==undefined&&v!=="";}):[];
 if(!targets.length){[x.tp1,x.tp2,x.tp3].forEach(function(v){if(v!==null&&v!==undefined&&v!=="")targets.push(v);});}
 var lv='<div class="level"><small>السعر الحالي</small><b>'+esc(current||"—")+'</b></div>';
 lv+='<div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div>';
 targets.forEach(function(v,n){lv+='<div class="level trade-target"><small>TP'+(n+1)+'</small><b>'+esc(v)+'</b></div>';});
 lv+='<div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div>';
 var entry=Number(x.entry||0),sl=Number(x.sl||0),tps=targets.map(Number).filter(function(v){return Number.isFinite(v)&&v>0;}),pnl=(current>0&&entry>0)?((current-entry)/entry*100*(sell?-1:1)):null;
 var hit="OPEN",hitText="🟡 متابعة الصفقة",hitClass="track-open";
 if(current>0&&sl>0&&((sell&&current>=sl)||(!sell&&current<=sl))){hit="SL";hitText="🔴 وصل وقف الخسارة";hitClass="track-loss";}
 else if(current>0&&tps.length){for(var ti=tps.length-1;ti>=0;ti--){if((sell&&current<=tps[ti])||(!sell&&current>=tps[ti])){hit="TP"+(ti+1);hitText="🟢 وصل الهدف "+(ti+1);hitClass="track-win";break;}}}
 var pnlText=pnl===null?"الربح/الخسارة بانتظار السعر":((pnl>=0?"+":"")+pnl.toFixed(2)+"% "+(pnl>=0?"ربح":"خسارة"));
 var ageText=age===null?"التحديث غير متاح":age<1?"محدث الآن":"محدث قبل "+age+" د";
 return '<article class="card trade-tracking-card '+tier+'"><div class="card-top"><div><span class="rank trade-rank">'+mark+' '+(i+1)+' · '+esc(x.signal_label||(sell?"بيع":"شراء"))+'</span><div class="symbol">'+esc(displaySymbol(x)||"")+'</div></div><span class="direction '+(sell?"sell":"buy")+'">'+(sell?"بيع":"شراء")+'</span></div><div class="trade-track '+hitClass+'" aria-live="polite"><span class="track-dot"></span><b>'+hitText+'</b><strong>'+pnlText+'</strong></div><div class="score"><b>الثقة '+Math.round(score)+'%</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">'+(hit==="OPEN"?"الصفقة قيد المتابعة":hitText)+'</span></div><div class="levels">'+lv+'</div><div class="card-foot">📡 متابعة السعر · 🎯 تنبيه عند الهدف أو الوقف · '+ageText+'</div></article>';
}
function render(el,rows){if(!el)return;var a=(rows||[]).slice().sort(function(x,y){var d=signalScore(y)-signalScore(x);if(d)return d;var sc=Number(y.source_count||y.alignment||0)-Number(x.source_count||x.alignment||0);if(sc)return sc;return Number(y.detected_at||y.updated_at||0)-Number(x.detected_at||x.updated_at||0);});el.innerHTML=a.length?a.map(card).join(""):'<div class="empty">لا توجد توصيات منشورة خلال آخر 24 ساعة حالياً — جاري إعادة الفحص.</div>';}
function loadMarket(m,tf){
 var el=$("#marketCards"),st=$("#marketStatus");if(!el)return;
 if(m==="alpha"){el.innerHTML='<div class="empty">قسم Binance Alpha مستقل، لكن مصدر إشارات Alpha غير مربوط حاليًا. ما راح نعرض إشارات الفيوتشر على أنها Alpha.</div>';if(st)st.textContent="Binance Alpha · بانتظار ربط مصدر البيانات المستقل";return;}
 selectedTimeframe=tf||selectedTimeframe||"15m";
 var head=$(".page-head"),sw=$("#timeframeSwitch");
 if(head&&!sw){sw=document.createElement("div");sw.id="timeframeSwitch";sw.className="timeframe-switch";head.insertAdjacentElement("afterend",sw);}
 if(sw){sw.innerHTML=timeframes.map(function(t){return '<button type="button" class="timeframe-btn '+(t[0]===selectedTimeframe?'active':'')+'" data-timeframe="'+t[0]+'">'+t[1]+'</button>';}).join("");Array.prototype.forEach.call(sw.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadMarket(m,b.getAttribute("data-timeframe"));});});}
 if(st)st.textContent="جاري تحليل "+(timeframes.find(function(t){return t[0]===selectedTimeframe;})||timeframes[0])[1]+"…";
 function fetchMarketOnce(url,done){getJSON(url).then(function(j){j=j||{};done(j);if(j.scan_stats&&j.scan_stats.scanning){setTimeout(function(){fetchMarketOnce(url+"&retry="+Date.now(),done);},8000);}}).catch(function(){if(st)st.textContent="تعذر جلب بيانات هذا السوق حالياً — اضغط تحديث للمحاولة مرة ثانية.";});}
 fetchMarketOnce("/api/opportunities?market="+encodeURIComponent(m)+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now(),function(j){var rows=j.opportunities||[],s=j.scan_stats||{};render(el,rows);var t=s.updated_at?new Date(s.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):"جاري التحديث";if(st)st.textContent=s.scanning?"جاري فحص "+m+" بالخلفية · سيتم تحديث النتائج تلقائياً…":"تحليل "+selectedTimeframe+" · آخر تحديث: "+t;});
}

function renderTechnicalMethods(){
 var grid=$("#technicalMethodGrid"),detail=$("#technicalMethodDetail");
 var active=technicalMethods.find(function(x){return x[0]===selectedTechnicalMethod;})||technicalMethods[0];
 if(pageTechnicalMethod){
  if(grid)grid.style.display="none";
  if(detail)detail.innerHTML='<div class="method-detail-head"><b>'+active[1]+' '+active[2]+'</b><p>'+active[3]+'</p><a class="method-back-link" href="/static/technical.html?v=20261010-method-index">← كل مناهج التحليل الفني</a></div>';
  return;
 }
 if(!grid)return;
 grid.innerHTML=technicalMethods.filter(function(x){return x[0]!=="all";}).map(function(x){return '<a class="method-card method-link" href="/static/technical-'+encodeURIComponent(x[0])+ '.html?v=20261010-methodfix"><span class="method-icon">'+x[1]+'</span><b>'+x[2]+'</b><small>'+x[3]+'</small><span class="method-open">فتح صفحة المنهج ←</span></a>';}).join("");
 if(detail)detail.innerHTML='<b>كل منهج في صفحة مستقلة</b><p>اضغط على المنهج لفتح صفحته الخاصة؛ داخل كل صفحة تختار السوق والفريم وتظهر الفرص المطابقة لهذا المنهج فقط.</p>';
}

function filterTechnicalMethods(rows){
 if(selectedTechnicalMethod==="all")return rows;
 var map={"price-action":["price_action"],smc:["smc"],ict:["ict_liquidity"],classical:["dow","support_resistance","breakout","retest","chart_pattern"],candles:["candlestick"],patterns:["chart_pattern"],indicators:[],fibonacci:["fibonacci"],harmonic:[],elliott:["elliott"],wyckoff:["wyckoff"],volume:["raw_volume"],"order-flow":[],ichimoku:[],"dow-mtf":["dow"],quant:[],gann:[]};
 var keys=map[selectedTechnicalMethod]||[];
 if(!keys.length)return [];
 return rows.map(function(r){
  var votes=r.methods||r.analysis_methods||r.method_votes||{};
  var vals=keys.map(function(k){return Number(votes[k]||0);}).filter(function(n){return n!==0;});
  if(!vals.length)return null;
  var vote=vals.reduce(function(a,b){return a+b;},0);
  if(vote===0)return null;
  var side=vote>0?"BUY":"SELL";
  var x=Object.assign({},r,{side:side,direction:side,technical_method:selectedTechnicalMethod});
  var entry=Number(x.entry||x.current_price||x.live_price||x.price||0);
  if(!(entry>0))return null;
  var support=Number(x.support||0),resistance=Number(x.resistance||0);
  var risk=Math.max(entry*0.008,Math.abs(entry-(side==="BUY"?(support||entry):(resistance||entry)))*0.45);
  x.entry=entry;
  x.sl=side==="BUY"?entry-risk:entry+risk;
  x.tp1=side==="BUY"?entry+risk:entry-risk;
  x.tp2=side==="BUY"?entry+risk*2:entry-risk*2;
  x.tp3=side==="BUY"?entry+risk*3:entry-risk*3;
  x.targets=[x.tp1,x.tp2,x.tp3];
  x.reason="إشارة مستقلة حسب تصويت منهج "+selectedTechnicalMethod+" من بيانات الشموع؛ الأهداف والوقف محسوبة باتجاه الإشارة";
  return x;
 }).filter(Boolean);
}
function loadTechnical(m,tf){
 var box=$("#marketCards"),status=$("#marketStatus"),marketSwitch=$("#technicalMarketSwitch"),tfSwitch=$("#timeframeSwitch");
 renderTechnicalMethods();
 var tradingPanel=$("#technicalTradingPanel");
 if(!pageTechnicalMethod){if(tradingPanel)tradingPanel.style.display="none";return;}
 if(tradingPanel)tradingPanel.style.display="";
 if(!box)return;
 if(m)selectedTechnicalMarket=m;
 if(tf)selectedTimeframe=tf;
 if(!technicalMarkets.some(function(x){return x[0]===selectedTechnicalMarket;}))selectedTechnicalMarket="spot";
 if(marketSwitch){
  marketSwitch.innerHTML=technicalMarkets.map(function(x){return '<button type="button" class="timeframe-btn '+(x[0]===selectedTechnicalMarket?'active':'')+'" data-technical-market="'+x[0]+'">'+x[1]+' '+x[2]+'</button>';}).join("");
  Array.prototype.forEach.call(marketSwitch.querySelectorAll("[data-technical-market]"),function(b){b.addEventListener("click",function(){loadTechnical(b.getAttribute("data-technical-market"),selectedTimeframe);});});
 }
 if(tfSwitch){
  tfSwitch.innerHTML=timeframes.map(function(x){return '<button type="button" class="timeframe-btn '+(x[0]===selectedTimeframe?'active':'')+'" data-timeframe="'+x[0]+'">'+x[1]+'</button>';}).join("");
  Array.prototype.forEach.call(tfSwitch.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadTechnical(selectedTechnicalMarket,b.getAttribute("data-timeframe"));});});
 }
 var marketName=(technicalMarkets.find(function(x){return x[0]===selectedTechnicalMarket;})||technicalMarkets[0])[2];
 var tfName=(timeframes.find(function(x){return x[0]===selectedTimeframe;})||timeframes[2])[1];
 if(status)status.textContent="جاري تحليل "+marketName+" · "+tfName+"…";
 if(selectedTechnicalMarket==="alpha"){box.innerHTML='<div class="empty">مصدر Binance Alpha المستقل غير مربوط حاليًا. لن نستبدل بياناته بإشارات الفيوتشر.</div>';if(status)status.textContent=marketName+" · لا توجد بيانات مستقلة متاحة";return;}
 var apiMarket=selectedTechnicalMarket;
 var methodName=(technicalMethods.find(function(x){return x[0]===selectedTechnicalMethod;})||technicalMethods[0])[2];
 // Use dedicated, real scanners only where the backend exposes them. Never relabel
 // generic research recommendations as signals from a specific technical method.
 var dedicatedEngines={"price-action":"price-action","patterns":"patterns","order-flow":"order-flow"};
 var engine=selectedTechnicalMarket==="spot"?dedicatedEngines[selectedTechnicalMethod]:"";
 var endpoint=engine
  ?"/api/strategy/engine?engine="+encodeURIComponent(engine)+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now()
  :"/api/opportunities?market="+encodeURIComponent(apiMarket)+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now();
 getJSON(endpoint).then(function(j){
  var s=j.scan_stats||{},rows=j.opportunities||[];
  var methodRows=engine?rows:filterTechnicalMethods(rows);
  if(engine)methodRows=methodRows.map(function(r){return Object.assign({},r,{market:"spot",technical_method:selectedTechnicalMethod});});
  render(box,methodRows);
  if(!methodRows.length&&selectedTechnicalMethod!=="all"){
   var hasDedicated=!!engine;
   box.innerHTML='<div class="empty">'+(hasDedicated
    ?'اكتمل فحص '+esc(methodName)+' على سبوت وفريم '+esc(tfName)+'، لكن ما ظهرت فرصة تستوفي شروط المنهج الآن.'
    :'المنهج هذا ما عنده ماسح مستقل مربوط بالسوق المختار حاليًا. ما راح ننسب له إشارات عامة أو إشارات من منهج ثاني.')+'</div>';
  }
  var rawStamp=s.updated_at?new Date(s.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):(j.updated_at?new Date(j.updated_at).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"}):"جاري التحديث");
  if(status)status.textContent=(s.scanning?"الفحص مستمر بالخلفية · ":"")+marketName+" · "+methodName+" · فريم "+tfName+" · "+methodRows.length+" فرصة · آخر تحديث: "+rawStamp;
 }).catch(function(){if(status)status.textContent="تعذر جلب بيانات هذا السوق الآن — جرّب تحديث الصفحة أو غيّر الفريم.";});
}
function loadCoreMarkets(){
 var box=$("#coreMarkets");if(!box)return;
 var items=[["₿","سبوت","spot","Binance Spot"],["⚡","فيوتشر","futures","Binance Futures"],["α","Binance Alpha","alpha","قسم مستقل"],["◉","العقود الأمريكية","contracts","عقود ومؤشرات"],["🇺🇸","الأسهم الأمريكية","us","سوق الأسهم الأمريكي"],["🇸🇦","السعودي / تاسي","saudi","السوق السعودي"],["💱","الفوركس","forex","أزواج العملات"],["🥇","الذهب","forex","تحليل الذهب"]];
 box.innerHTML=items.map(function(x){return '<article class="core-card market-link" role="link" tabindex="0" data-core-market="'+x[2]+'"><div class="core-title"><span>'+x[0]+'</span><b>'+x[1]+'</b></div><div class="core-analysis">'+x[3]+'</div><div class="card-foot">فتح القسم ←</div></article>';}).join("")+'<article class="core-card market-link" role="link" tabindex="0" data-core-market="technical"><div class="core-title"><span>📐</span><b>مناهج التحليل الفني</b></div><div class="core-analysis">اختر المنهج ثم السوق والفريم</div><div class="card-foot">عرض المناهج ←</div></article>';
}
function loadMarketSectors(){
 var box=$("#marketSectors");if(!box)return;
 var items=[
  ["🇸🇦","السعودي / تاسي","saudi"],["🇺🇸","الأسهم الأمريكية","us"],["💻","التقنية","us"],["🏦","البنوك والمالي","saudi"],["🏭","الصناعة","saudi"],["🏥","الصحة","us"],["🛒","الاستهلاك والتجزئة","us"],["⚡","الطاقة والمرافق","contracts"],["🏗️","العقار والإنشاءات","saudi"],["₿","الكريبتو","spot"],["🥇","الذهب والمعادن","forex"],["🛢️","النفط والطاقة","contracts"],["💵","الفوركس","forex"],["📈","المؤشرات","contracts"],["🌍","الاقتصاد العالمي","news"]
 ];
 box.innerHTML=items.map(function(x){return '<article class="core-card sector-link" role="link" tabindex="0" data-s="'+x[2]+'"><div class="core-title"><span>'+x[0]+'</span><b>'+x[1]+'</b></div><div class="core-analysis">اضغط لفتح القسم ←</div></article>';}).join("");
}
function loadHome(){loadCoreMarkets();loadMarketSectors();var el=$("#homeCards"),rb=$("#homeResults");if(loading)return;loading=true;Promise.all([getJSON("/api/radar?x="+Date.now()),getJSON("/api/results?x="+Date.now())]).then(function(v){var j=v[0]||{},r=v[1]||{},rows=j.opportunities||[];render(el,rows.slice().sort(function(a,b){return signalScore(b)-signalScore(a);}).slice(0,8));if($("#count"))$("#count").textContent=rows.length;if($("#sources"))$("#sources").textContent=(j.opportunities||[]).reduce(function(n,x){return n+Number(x.source_count||0);},0);if($("#updated"))$("#updated").textContent=new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});var rs=r.results||[];if(rb)rb.innerHTML=rs.length?rs.slice(0,6).map(function(x){var st=x.status==="WIN"?"✅ رابحة":x.status==="LOSS"?"❌ خاسرة":x.status==="EXPIRED"?"⚪ منتهية":"⏳ مفتوحة";return '<article class="card"><div class="card-top"><div><span class="rank">'+st+'</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(x.direction==="SELL"?"sell":"buy")+'">'+(x.direction==="SELL"?"بيع":"شراء")+'</span></div><div class="levels"><div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div><div class="level"><small>TP1</small><b>'+esc(x.tp1||"—")+'</b></div><div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div></div><div class="card-foot">نتيجة التوصية · '+esc(x.updated||x.created||"—")+'</div></article>';}).join(""):'<div class="empty">لا توجد نتائج حديثة حالياً.</div>';}).catch(function(){render(el,[]);if(rb)rb.innerHTML='<div class="empty">لا توجد نتائج حديثة حالياً.</div>';}).finally(function(){loading=false;});}
function fortuneCard(x,i){var d=x.direction==="SELL",score=Number(x.recommendation_score||x.ai_pct||x.ai||x.analysis_score||0),w=Math.max(0,Math.min(100,score)),ts=[x.tp1,x.tp2,x.tp3,x.tp4,x.tp5,x.tp6].filter(function(v){return v!==null&&v!==undefined&&v!=="";});var lv='<div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div>';ts.forEach(function(v,n){lv+='<div class="level"><small>TP'+(n+1)+'</small><b>'+esc(v)+'</b></div>';});lv+='<div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div>';return '<article class="card fortune-card"><div class="card-top"><div><span class="rank">#'+(i+1)+' · صفقة</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(d?"sell":"buy")+'">'+(d?"بيع":"شراء")+'</span></div><div class="score"><b>توافق '+Math.round(score)+'%</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">'+esc(x.verdict||"صفقة خارجية")+'</span></div><div class="levels">'+lv+'</div><div class="card-foot">🧠 تحليل مباشر للصفقة · '+esc(x.alignment||0)+'% مصادر مستقلة · 🕒 '+esc(x.published||"—")+'</div></article>';}
function loadGold(tf){
 var edge=$("#smartEdgeCards"),summary=$("#smartEdgeSummary"),updated=$("#smartEdgeUpdated");
 if(!edge)return;
 selectedTimeframe=tf||selectedTimeframe||"15m";
 var head=$(".page-head"),sw=$("#timeframeSwitch");
 if(head&&!sw){sw=document.createElement("div");sw.id="timeframeSwitch";sw.className="timeframe-switch";head.insertAdjacentElement("afterend",sw);}
 if(sw){sw.innerHTML=timeframes.map(function(t){return '<button type="button" class="timeframe-btn '+(t[0]===selectedTimeframe?"active":"")+'" data-timeframe="'+t[0]+'">'+t[1]+'</button>';}).join("");Array.prototype.forEach.call(sw.querySelectorAll("[data-timeframe]"),function(b){b.addEventListener("click",function(){loadGold(b.getAttribute("data-timeframe"));});});}
 var markets=[["spot","₿","سبوت"],["futures","⚡","فيوتشر"],["contracts","◉","العقود الأمريكية"],["us","🇺🇸","الأسهم الأمريكية"],["saudi","🇸🇦","السوق السعودي"],["forex","💱","فوركس وذهب"]];
 edge.innerHTML='<div class="empty">جاري فحص الأسواق الستة على فريم '+esc(selectedTimeframe)+'…</div>';
 if(summary)summary.innerHTML='';
 if(updated)updated.textContent="جاري فحص 6 أسواق…";
 function num(v){var n=Number(v);return v!==null&&v!==undefined&&v!==""&&Number.isFinite(n)?n:null;}
 function stamp(x){var v=num(x.detected_at||x.updated_at||x.timestamp);if(v===null)return null;if(v>1e12)v=v/1000;return v>0?v:null;}
 function movement(x){var keys=["timeframe_change_pct","change_pct","price_change_pct","pct_change","change_percent"];for(var k=0;k<keys.length;k++){var v=num(x[keys[k]]);if(v!==null)return v;}return null;}
 function grade(x,mv){
  var conf=num(x.recommendation_score);if(conf===null)conf=num(x.ai_pct);if(conf===null)conf=num(x.analysis_score);conf=conf===null?0:Math.max(0,Math.min(100,conf));
  var sources=Math.max(0,Math.min(10,num(x.source_count)||0));
  var agree=num(x.external_agreement);if(agree===null)agree=num(x.research_agreement);agree=agree===null?0:Math.max(0,Math.min(100,agree));
  var age=stamp(x),ageH=age===null?null:Math.max(0,(Date.now()/1000-age)/3600);
  var side=String(x.direction||x.side||"").toUpperCase(),match=mv===null?0:((mv>0&&side==="BUY")||(mv<0&&side==="SELL")?10:((mv<0&&side==="BUY")||(mv>0&&side==="SELL")?-18:0));
  var movePts=mv===null?0:Math.min(35,Math.abs(mv)*7);
  var freshness=ageH===null?0:(ageH<=1?10:ageH<=6?7:ageH<=24?3:-15);
  var total=Math.round(Math.max(0,Math.min(100,movePts+conf*.25+sources*1.5+agree*.15+freshness+match)));
  return {total:total,conf:conf,sources:sources,agree:agree,ageH:ageH,match:match};
 }
 Promise.all(markets.map(function(m){return getJSON("/api/opportunities?market="+encodeURIComponent(m[0])+"&timeframe="+encodeURIComponent(selectedTimeframe)+"&x="+Date.now()).then(function(j){return {market:m,rows:(j.opportunities||[]).filter(function(x){return !x.timeframe||String(x.timeframe)===selectedTimeframe;}),scan:j.scan_stats||{}};}).catch(function(){return {market:m,rows:[],error:true};});})).then(function(groups){
  var all=[],total=0,withMove=0,failed=0;
  groups.forEach(function(g){if(g.error)failed++;g.rows.forEach(function(x){var mv=movement(x),q=grade(x,mv);all.push({x:x,move:mv,quality:q,market:g.market});if(mv!==null)withMove++;});total+=g.rows.length;});
  all.sort(function(a,b){return b.quality.total-a.quality.total;});
  function card(z,i){
   var x=z.x,mv=z.move,q=z.quality,down=String(x.direction||x.side||"").toUpperCase()==="SELL",score=q.total,w=score;
   var change=mv===null?'<span class="edge-no-change">بيانات تغيّر الفريم غير متاحة</span>':'<b class="edge-pct '+(mv>=0?"edge-up":"edge-down")+'" dir="ltr">'+(mv>0?"+":"")+mv.toFixed(3)+'%</b>';
   function val(v){return v===null||v===undefined||v===""?"غير محسوب":esc(v);}
   var price=x.current_price||x.live_price||x.price||"—",entry=x.entry||"—";
   var levels='<div class="level"><small>السعر الحالي</small><b>'+val(price)+'</b></div><div class="level"><small>الدخول</small><b>'+val(entry)+'</b></div><div class="level"><small>TP1</small><b>'+val(x.tp1)+'</b></div><div class="level"><small>وقف الخسارة</small><b>'+val(x.sl)+'</b></div>';
   var freshness=q.ageH===null?"حداثة البيانات غير مؤكدة":q.ageH<1?"البيانات خلال آخر ساعة":q.ageH<=24?"عمر البيانات "+Math.round(q.ageH)+" ساعة":"⚠️ البيانات أقدم من 24 ساعة";
   return '<article class="card smart-edge-card"><div class="card-top"><div><span class="rank">'+(i===0?"👑 الأقوى عبر الأسواق":"#"+(i+1))+' · '+esc(z.market[2])+' · '+esc(selectedTimeframe)+'</span><div class="symbol">'+esc(displaySymbol(x)||"—")+'</div></div><span class="direction '+(down?"sell":"buy")+'">'+(down?"بيع":"شراء")+'</span></div><div class="edge-change"><small>تغيّر الفريم</small>'+change+'</div><div class="score"><b>قوة الفرصة '+score+'/100</b><div class="score-bar"><i style="width:'+w+'%"></i></div><span class="rank">تقييم فرز وليس احتمال ربح</span></div><div class="levels">'+levels+'</div><div class="card-foot">المصادر: '+q.sources+' · توافق خارجي: '+q.agree+'% · '+freshness+(q.match<0?' · ⚠️ اتجاه الإشارة يعاكس الحركة':'')+'</div></article>';
  }
  var top=all.slice(0,5);
  var topHtml=top.length?'<section class="edge-market-group"><div class="edge-market-title"><h3>🏆 أقوى الفرص بين جميع الأسواق</h3><span>مرتبة حسب قوة الفرصة</span></div><div class="cards">'+top.map(card).join("")+'</div></section>':'<div class="empty">ما وصلت إشارات قابلة للتقييم من المصادر الحالية.</div>';
  var groupsHtml=groups.map(function(g){
   var rows=all.filter(function(z){return z.market[0]===g.market[0];});
   var body=rows.length?rows.map(function(z,i){return card(z,i+5);}).join(""):'<div class="empty">'+(g.error?"تعذر جلب هذا السوق؛ ما نحسبه كسوق سليم.":"ما فيه إشارات متاحة على الفريم المختار.")+'</div>';
   var st=g.scan||{},scanned=num(st.scanned||st.total_scanned||st.assets_scanned);
   return '<section class="edge-market-group"><div class="edge-market-title"><h3>'+g.market[1]+' '+g.market[2]+'</h3><span>'+rows.length+' إشارة'+(scanned===null?"":" · فُحص "+scanned+" أصل")+'</span></div><div class="cards">'+body+'</div></section>';
  }).join("");
  edge.innerHTML=topHtml+groupsHtml;
  if(summary)summary.innerHTML='<div class="edge-stat"><span>الفريم</span><b>'+esc(selectedTimeframe)+'</b></div><div class="edge-stat"><span>الأسواق المستجيبة</span><b>'+(markets.length-failed)+'/6</b></div><div class="edge-stat"><span>الإشارات المستلمة</span><b>'+total+'</b></div><div class="edge-stat"><span>تغيّر فريم متوفر</span><b>'+withMove+'/'+total+'</b></div>';
  if(updated)updated.textContent="آخر فحص: "+new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+(failed?" · تعذر سوق/أسواق":"");
 }).catch(function(){edge.innerHTML='<div class="empty">تعذر تحديث رادار الأسواق حالياً.</div>';if(updated)updated.textContent="تعذر التحديث";});
}
function loadBlog(){var el=$("#blogCards");if(!el)return;getJSON("/api/blog?x="+Date.now()).then(function(j){var rows=j.items||[];el.innerHTML=rows.length?rows.map(function(x){return '<article class="card"><span class="eyebrow">SMART TRADING / BLOG</span><h3><a href="/blog/'+encodeURIComponent(x.slug||"")+'">'+esc(x.title||"مقال")+'</a></h3><p class="card-foot">'+esc(x.text||"")+'</p><a href="/blog/'+encodeURIComponent(x.slug||"")+'" aria-label="اقرأ المقال">اقرأ المقال ←</a></article>';}).join(""):'<div class="empty">لا توجد مقالات حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">جاري تحديث المدونة…</div>';});}
function loadNews(){var el=$("#newsCards");if(!el)return;getJSON("/api/news?x="+Date.now()).then(function(j){var rows=j.items||[];el.innerHTML=rows.length?rows.map(function(x){var impacts=x.impacts||[];var marketCards=impacts.map(function(i){var d=i.direction==="بيع",neutral=i.direction==="محايد",cls=neutral?"":(d?"sell":"buy"),icon=neutral?"⚪":(d?"🔴":"🟢");return '<div class="news-market-impact"><div class="card-top"><div><span class="rank">'+icon+' '+esc(i.market_name||"السوق")+' · '+esc(i.impact||"")+'</span><div class="symbol">'+esc(i.symbol||"السوق")+'</div></div><span class="direction '+cls+'">'+esc(i.action||i.direction||"مراقبة")+'</span></div><div class="levels"><div class="level"><small>الاتجاه</small><b>'+esc(i.direction||"محايد")+'</b></div><div class="level"><small>قوة التأثير</small><b>'+esc(i.impact||"—")+'</b></div></div><p class="news-why">💡 '+esc(i.why||"متابعة حركة السعر")+'</p></div>';}).join("");return '<article class="card news-intel"><div class="card-top"><div><span class="rank">📰 خبر يؤثر على '+esc(x.markets_count||impacts.length)+' أسواق</span></div><span class="rank">حديث</span></div><h3>'+esc(x.title||"خبر السوق")+'</h3><p class="news-summary">'+esc(x.summary||"تحليل الخبر حسب كل سوق")+'</p><div class="news-market-list">'+marketCards+'</div><div class="card-foot">تحليل مستقل لكل سوق داخل نفس الخبر · بدون عرض مصادر</div></article>';}).join(""):'<div class="empty">لا توجد أخبار جديدة مؤثرة حالياً.</div>';}).catch(function(){el.innerHTML='<div class="empty">تعذر تحديث تحليل الأخبار حالياً.</div>';});}
function loadResults(){
 var box=$("#resultsCards"),summary=$("#resultsSummary"),markets=$("#resultsMarkets");if(!box)return;
 getJSON("/api/results?x="+Date.now()).then(function(j){
  var s=j.stats||{};
  if(summary)summary.innerHTML='<div class="metric"><span>إجمالي التوصيات</span><b>'+s.total+'</b><small>آخر 24 ساعة</small></div><div class="metric"><span>رابحة</span><b>'+s.wins+'</b><small>وصلت للهدف</small></div><div class="metric"><span>خاسرة</span><b>'+s.losses+'</b><small>وصلت للوقف</small></div><div class="metric"><span>نسبة النجاح</span><b>'+s.win_rate+'%</b><small>من الصفقات المغلقة</small></div>';
  if(markets)markets.innerHTML=Object.keys(j.by_market||{}).map(function(k){var m=j.by_market[k]||{},n={spot:"سبوت",futures:"فيوتشر",contracts:"العقود الأمريكية",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب"}[k]||k;return '<div class="metric"><span>'+n+'</span><b>'+m.win_rate+'%</b><small>'+m.wins+' رابحة · '+m.losses+' خاسرة · '+m.open+' مفتوحة</small></div>';}).join("");
  var rows=j.results||[];
  box.innerHTML=rows.length?rows.map(function(x){var st=x.status==="WIN"?"✅ رابحة":x.status==="LOSS"?"❌ خاسرة":x.status==="EXPIRED"?"⚪ منتهية":"⏳ مفتوحة",cls=x.status==="WIN"?"buy":x.status==="LOSS"?"sell":"";return '<article class="card"><div class="card-top"><div><span class="rank">'+st+'</span><div class="symbol">'+esc(displaySymbol(x))+'</div></div><span class="direction '+cls+'">'+(x.direction==="SELL"?"بيع":"شراء")+'</span></div><div class="levels"><div class="level"><small>الدخول</small><b>'+esc(x.entry||"—")+'</b></div><div class="level"><small>TP1</small><b>'+esc(x.tp1||"—")+'</b></div><div class="level"><small>TP2</small><b>'+esc(x.tp2||"—")+'</b></div><div class="level"><small>TP3</small><b>'+esc(x.tp3||"—")+'</b></div><div class="level"><small>SL</small><b>'+esc(x.sl||"—")+'</b></div><div class="level"><small>النتيجة</small><b>'+st+'</b></div></div><div class="card-foot">'+esc({spot:"سبوت",futures:"فيوتشر",contracts:"العقود",us:"الأمريكي",saudi:"السعودي",forex:"فوركس وذهب"}[x.market]||x.market)+' · '+new Date(x.created*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"})+'</div></article>';}).join(""):'<div class="empty">لا توجد نتائج مسجلة حتى الآن.</div>';
 }).catch(function(){box.innerHTML='<div class="empty">تعذر جلب النتائج حالياً.</div>';});
}
var selectedWhaleMarket="spot";
var selectedWhaleThreshold=10000;
function loadWhales(tf,marketChoice,thresholdChoice){
 var summary=$("#whaleSummary"),markets=$("#whaleMarkets"),box=$("#whaleCards");if(!box)return;
 if(marketChoice)selectedWhaleMarket=marketChoice;
 if(thresholdChoice)selectedWhaleThreshold=Number(thresholdChoice)||10000;
 var names={spot:"سبوت بايننس",futures:"فيوتشر بايننس",contracts:"العقود الأمريكية",us:"الأسهم الأمريكية",saudi:"السوق السعودي / تاسي",forex:"فوركس وذهب"};
 var thresholds=[10000,50000,100000,500000];
 var head=$(".page-head"),mw=$("#whaleMarketSwitch"),tw=$("#whaleThresholdSwitch");
 if(head&&!mw){mw=document.createElement("div");mw.id="whaleMarketSwitch";mw.className="timeframe-switch whale-market-switch";head.insertAdjacentElement("afterend",mw);}
 if(mw){mw.innerHTML=Object.keys(names).map(function(m){return '<button type="button" class="timeframe-btn '+(m===selectedWhaleMarket?'active':'')+'" data-whale-market="'+m+'">'+names[m]+'</button>';}).join("");Array.prototype.forEach.call(mw.querySelectorAll("[data-whale-market]"),function(b){b.addEventListener("click",function(){loadWhales(selectedTimeframe,b.getAttribute("data-whale-market"));});});}
 if(head&&!tw){tw=document.createElement("div");tw.id="whaleThresholdSwitch";tw.className="timeframe-switch whale-threshold-switch";tw.setAttribute("aria-label","فلتر حجم الصفقة");(mw||head).insertAdjacentElement("afterend",tw);}
 if(tw){tw.innerHTML='<span class="whale-filter-label">أقل قيمة للصفقة:</span>'+thresholds.map(function(v){return '<button type="button" class="timeframe-btn '+(v===selectedWhaleThreshold?'active':'')+'" data-whale-threshold="'+v+'">$'+(v/1000)+' ألف</button>';}).join("");Array.prototype.forEach.call(tw.querySelectorAll("[data-whale-threshold]"),function(b){b.addEventListener("click",function(){loadWhales(selectedTimeframe,null,b.getAttribute("data-whale-threshold"));});});}
 var marketName=names[selectedWhaleMarket]||names.spot;
 var thresholdLabel="$"+selectedWhaleThreshold.toLocaleString("en-US");
 if(!["spot","futures"].includes(selectedWhaleMarket)){
  if(summary)summary.innerHTML='<div class="metric"><span>السوق</span><b>'+marketName+'</b><small>المصدر المباشر غير موصول لهذا السوق</small></div>';
  if(markets)markets.innerHTML='<div class="metric"><span>حالة المصدر</span><b>غير موصول</b><small>لن نعرض حركة سعر على أنها صفقات حيتان</small></div>';
  box.innerHTML='<div class="empty">رصد الصفقات الكبيرة المنفذة متاح حاليًا من Binance Spot وFutures فقط. هذا السوق يحتاج مصدر صفقات مستقل.</div>';return;
 }
 if(summary)summary.innerHTML='<div class="metric"><span>المصدر</span><b>Binance مباشر</b><small>صفقات منفذة فعلية</small></div><div class="metric"><span>السوق</span><b>'+marketName+'</b><small>هذا السوق فقط</small></div><div class="metric"><span>حد الصفقة</span><b>'+thresholdLabel+'</b><small>قيمة اسمية للصفقة</small></div>';
 if(markets)markets.innerHTML='<div class="metric"><span>حالة الرصد</span><b>جاري الاتصال</b><small>فحص أعلى 30 زوج USDT بعد استبعاد العملات المستقرة</small></div>';
 box.innerHTML='<div class="empty">جاري جلب الصفقات الكبيرة المنفذة من Binance…</div>';
 getJSON('/api/whale-trades?market='+encodeURIComponent(selectedWhaleMarket)+'&min_notional_usdt='+selectedWhaleThreshold+'&x='+Date.now()).then(function(j){
  var trades=Array.isArray(j.trades)?j.trades:[];
  trades.sort(function(a,b){return Number(b.notional_usdt||0)-Number(a.notional_usdt||0);});
  if(summary)summary.innerHTML='<div class="metric"><span>المصدر</span><b>Binance مباشر</b><small>بيانات صفقات منفذة</small></div><div class="metric"><span>الرموز المفحوصة</span><b>'+Number(j.symbols_scanned||0)+'</b><small>أعلى أزواج USDT تداولًا بعد استبعاد المستقرة</small></div><div class="metric"><span>الصفقات الكبيرة</span><b>'+trades.length+'</b><small>حد أدنى '+thresholdLabel+'</small></div><div class="metric"><span>آخر تحديث</span><b>'+(j.updated_at?new Date(j.updated_at*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—")+'</b><small>'+(j.cached?'من ذاكرة مؤقتة قصيرة':'بيانات جديدة')+'</small></div>';
  if(markets)markets.innerHTML='<div class="metric"><span>'+marketName+'</span><b>'+(j.ok?'متصل':'تعذر الاتصال')+'</b><small>'+esc(j.message||'بيانات صفقات عامة')+'</small></div><div class="metric"><span>الترتيب</span><b>الأكبر أولًا</b><small>حسب القيمة الاسمية للصفقة</small></div><div class="metric"><span>تنبيه</span><b>لا تكشف الهوية</b><small>اتجاه taker لا يحدد نية المحفظة</small></div>';
  box.innerHTML=trades.length?trades.map(function(t,i){var buy=t.side==='BUY',time=t.trade_time?new Date(t.trade_time).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—";return '<article class="card whale-real-card"><div class="card-top"><div><span class="rank">#'+(i+1)+' · صفقة منفذة</span><div class="symbol">'+esc(t.symbol)+'</div></div><span class="direction '+(buy?'buy':'sell')+'">'+(buy?'شراء من السوق':'بيع للسوق')+'</span></div><div class="levels"><div class="level"><small>القيمة الاسمية</small><b>$'+Number(t.notional_usdt||0).toLocaleString("en-US",{maximumFractionDigits:0})+'</b></div><div class="level"><small>سعر التنفيذ</small><b>'+Number(t.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="level"><small>الكمية</small><b>'+Number(t.quantity||0).toLocaleString("en-US",{maximumFractionDigits:6})+'</b></div><div class="level"><small>وقت التنفيذ</small><b>'+time+'</b></div></div><div class="whale-liquidity" data-liquidity-symbol="'+esc(t.symbol)+'" data-liquidity-side="'+(buy?'BUY':'SELL')+'" data-liquidity-entry="'+Number(t.price||0)+'"><div class="whale-liquidity-head">🎯 أهداف السيولة ووقف الخسارة</div><div class="whale-liquidity-content"><span class="liquidity-loading">جاري حساب مستويات السيولة…</span></div></div><div class="card-foot">صفقة منفذة من Binance · مستويات السيولة تقديرية وليست ضمانًا</div></article>';}).join(''): '<div class="empty">'+esc(j.message||'ما فيه صفقات تجاوزت '+thresholdLabel+' في العينة الحالية.')+'</div>';
  var liquidityCards=Array.prototype.slice.call(box.querySelectorAll("[data-liquidity-symbol]")), liquidityCursor=0;
  function loadNextLiquidity(){
   if(liquidityCursor>=liquidityCards.length)return;
   var el=liquidityCards[liquidityCursor++],content=el.querySelector(".whale-liquidity-content");
   var symbol=el.getAttribute("data-liquidity-symbol"),side=el.getAttribute("data-liquidity-side"),entry=el.getAttribute("data-liquidity-entry");
   getJSON('/api/whale-liquidity?market='+encodeURIComponent(selectedWhaleMarket)+'&symbol='+encodeURIComponent(symbol)+'&side='+side+'&entry='+encodeURIComponent(entry)+'&x='+Date.now()).then(function(l){
    if(!content)return;
    if(!l.available){content.innerHTML='<span class="liquidity-unavailable">'+esc(l.message||'مستويات السيولة غير متاحة الآن')+'</span>';return;}
    var targets=Array.isArray(l.targets)?l.targets:[];
    var targetHtml=targets.map(function(t){return '<div class="liquidity-level"><small>'+esc(t.name)+'</small><b>'+Number(t.price||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b><em>R/R '+Number(t.risk_reward||0).toFixed(2)+'x</em></div>';}).join('');
    content.innerHTML='<div class="liquidity-entry"><small>الدخول المرجعي</small><b>'+Number(l.entry||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="liquidity-targets">'+targetHtml+'</div><div class="liquidity-stop"><small>🛑 وقف الخسارة</small><b>'+Number(l.stop_loss||0).toLocaleString("en-US",{maximumFractionDigits:8})+'</b></div><div class="liquidity-note">'+esc(l.note||'مستويات تقديرية')+'</div>';
   }).catch(function(){if(content)content.innerHTML='<span class="liquidity-unavailable">تعذر حساب السيولة لهذه الصفقة.</span>';}).finally(function(){loadNextLiquidity();});
  }
  for(var liquidityWorker=0;liquidityWorker<Math.min(4,liquidityCards.length);liquidityWorker++)loadNextLiquidity();
 }).catch(function(){if(box)box.innerHTML='<div class="empty">تعذر الاتصال ببيانات الصفقات الكبيرة؛ أعد المحاولة بعد قليل.</div>';});
}
function bind(){
 var side=$("#sidebar");
 if(side){
  if(!side.querySelector('[data-s="technical"]')){
   var tb=document.createElement("button");tb.className="nav-item";tb.type="button";tb.setAttribute("data-s","technical");tb.innerHTML="<span>📈</span> تحليل فني";side.insertBefore(tb,side.querySelector('[data-s="signup"]')||null);
  }
  side.querySelectorAll('[data-s="technical"]').forEach(function(b){b.classList.toggle("active",page==="technical");});

  var labels={whales:"متابعة الحيتان",results:"النتائج",news:"الأخبار",blog:"المدونة"};
  var icons={whales:"🐋",results:"📊",news:"📰",blog:"✍️"};
  Object.keys(labels).forEach(function(k){
   if(!side.querySelector('[data-s="'+k+'"]')){
    var b=document.createElement("button");
    b.className="nav-item";b.type="button";b.setAttribute("data-s",k);
    b.innerHTML="<span>"+icons[k]+"</span> "+labels[k];
    side.appendChild(b);
   }
  });
 }
 document.addEventListener("click",function(e){
  var target=e.target;
  if(target&&target.nodeType!==1)target=target.parentElement;
  if(!target)return;
  var nav=target.closest("[data-s]");
  if(nav){var destination=nav.getAttribute("data-s");if(destination){e.preventDefault();closeMenu();go(destination);}return;}
  var marketCard=target.closest("[data-core-market]");
  if(marketCard){var marketDestination=marketCard.getAttribute("data-core-market");if(marketDestination){e.preventDefault();go(marketDestination);}}
 },true);
 document.addEventListener("keydown",function(e){
  if(e.key!=="Enter"&&e.key!==" ")return;
  var el=e.target.closest('[role="link"][data-s], [role="link"][data-core-market]');
  if(!el)return;
  e.preventDefault();
  go(el.getAttribute("data-s")||el.getAttribute("data-core-market"));
 });
 var menu=$("#menu"),overlay=$("#overlay");
 if(menu)menu.addEventListener("click",function(){
  var s=$("#sidebar");if(s)s.classList.add("open");
  if(overlay)overlay.classList.add("show");
 });
 if(overlay)overlay.addEventListener("click",closeMenu);
}
function start(){bind();if(page==="technical"){loadTechnical();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(function(){loadTechnical(selectedTechnicalMarket,selectedTimeframe);},20000);}else if(page==="home")loadHome();else if(page==="radar"){var lr=function(){var box=$("#radarCards");if(!box)return;getJSON("/api/radar?x="+Date.now()).then(function(j){var rows=j.opportunities||[];render(box,rows);}).catch(function(){box.innerHTML='<div class="empty">تعذر تحديث الرادار حالياً — جاري إعادة المحاولة تلقائياً.</div>';});};lr();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(lr,20000);}else if(page==="gold"){loadGold();}else if(page==="results"){loadResults();}else if(page==="whales"){loadWhales();if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(loadWhales,60000);}else if(page==="news"){loadNews();}else if(page==="blog"){loadBlog();}else if(market){loadMarket(market);if(trackingTimer)clearInterval(trackingTimer);trackingTimer=setInterval(function(){loadMarket(market,selectedTimeframe);},20000);}}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();
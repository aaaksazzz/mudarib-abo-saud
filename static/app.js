const $=s=>document.querySelector(s);
const MARKET_IDS=["spot","futures","coinm","alpha","saudi","us","contracts","forex"];
const MARKET_NAMES={spot:"Binance Spot",futures:"Binance USD-M Futures",coinm:"Binance COIN-M Futures",alpha:"Binance Alpha",saudi:"السوق السعودي",us:"الأسهم الأمريكية",contracts:"العقود الأمريكية",forex:"الفوركس والذهب"};
function marketName(id){const i=MARKET_IDS.indexOf(id);return i<0?(MARKET_NAMES[id]||id):(MARKET_TRANSLATIONS[currentLanguage]||MARKET_TRANSLATIONS.ar)[i]}
const PATH=location.pathname.replace(/\/+$/,"")||"/";
const marketMatch=PATH.match(/^\/markets\/([a-z]+)$/);
let market=marketMatch?marketMatch[1]:"spot",busy=false,pending=false,timer=null;
let marketStatuses=new Map();
let analysisTimeframe=new URLSearchParams(location.search).get("timeframe")||"15m";
const VALID_TFS=["15m"];
if(!VALID_TFS.includes(analysisTimeframe))analysisTimeframe="15m";
function syncTimeframeButtons(){document.querySelectorAll("[data-timeframe]").forEach(button=>{const visible=button.dataset.timeframe==="15m";button.hidden=!visible;const active=visible&&button.dataset.timeframe===analysisTimeframe;button.classList.toggle("active",active);button.setAttribute("aria-pressed",active?"true":"false")})}
syncTimeframeButtons();
const fmt=n=>Number(n).toLocaleString("en-US",{maximumFractionDigits:8});
const compact=n=>{n=Number(n)||0;if(n>=1e9)return (n/1e9).toFixed(2)+"B";if(n>=1e6)return (n/1e6).toFixed(2)+"M";if(n>=1e3)return (n/1e3).toFixed(1)+"K";return fmt(n)};
const pct=n=>(Number(n)>=0?"+":"")+Number(n).toFixed(2)+"%";
const safe=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const LANG_KEYS=["menu","close","home","markets","sections","content","marketIndependent","direction","marketTrend","scanned","up","down","neutral","opportunities","strategyConfirm","timeframe","min15","hour","hour4","daily","weekly","monthly","openTrades","tracking","noOpenTrades","language","auto","night","day","manualExecution","marketHomeTitle","marketPageDescription","selectMarket","independentSources","rankingTop3","dataSource","buy","sell","entry","stopLoss","target1","target2","target3","noTrade","live"];
const LANG_TEXT={
ar:["القائمة","إغلاق","الرئيسية","الأسواق المستقلة","أقسام المنصة","المحتوى","صفحة مستقلة","توجه السوق","الاتجاه العام","أصل مفحوص","صاعد","هابط","محايد","فرص التداول","اتجاه وسيولة وزخم · كل التحليل على 15 دقيقة","فريم التحليل","15 دقيقة","ساعة","4 ساعات","يومي","أسبوعي","شهري","متابعة الصفقات","متابعة تلقائية للصفقات","لا توجد صفقات مفتوحة محفوظة لهذا السوق.","اللغة","تلقائي","وضع ليلي","وضع نهاري","تحليل آلي · تنفيذ يدوي فقط","الأسواق الذكية","بيانات واتجاهات وفرص هذا السوق فقط.","اختر السوق","مصادر مستقلة لكل سوق","أفضل 3 فرص","مصدر البيانات","شراء","بيع","الدخول","وقف الخسارة","الهدف الأول","الهدف الثاني","الهدف الثالث","لا توجد صفقة مؤكدة الآن. ننتظر اكتمال شروط الدخول والوقف والأهداف.","مباشر"],
en:["Menu","Close","Home","Markets","Sections","Content","Independent page","Market direction","Overall trend","Assets scanned","Bullish","Bearish","Neutral","Trading opportunities","15m direction, liquidity and momentum analysis","Timeframe","15 minutes","1 hour","4 hours","Daily","Weekly","Monthly","Trade tracker","Automatic trade tracking","No open trades saved for this market.","Language","Auto","Dark mode","Light mode","Automated analysis · Manual execution only","Smart Markets","Market data, direction and opportunities only.","Select market","Independent data sources","Top 3 opportunities","Data source","Buy","Sell","Entry","Stop loss","Target 1","Target 2","Target 3","No confirmed trade now. Waiting for valid entry, stop and targets.","Live"],
es:["Menú","Cerrar","Inicio","Mercados","Secciones","Contenido","Página independiente","Dirección del mercado","Tendencia general","Activos analizados","Alcista","Bajista","Neutral","Oportunidades","Dirección, liquidez y momentum en 15 minutos","Marco temporal","15 minutos","1 hora","4 horas","Diario","Semanal","Mensual","Seguimiento de operaciones","Seguimiento automático","No hay operaciones abiertas guardadas para este mercado.","Idioma","Automático","Modo oscuro","Modo claro","Análisis automático · Ejecución manual","Mercados inteligentes","Solo datos, dirección y oportunidades de este mercado.","Elegir mercado","Fuentes independientes","Mejores 3 oportunidades","Fuente de datos","Comprar","Vender","Entrada","Stop loss","Objetivo 1","Objetivo 2","Objetivo 3","No hay operaciones confirmadas. Esperando condiciones válidas.","En vivo"],
de:["Menü","Schließen","Startseite","Märkte","Bereiche","Inhalte","Eigene Marktseite","Marktrichtung","Gesamttrend","Geprüfte Assets","Aufwärts","Abwärts","Neutral","Handelschancen","Richtung, Liquidität und Momentum auf 15 Minuten","Zeitrahmen","15 Minuten","1 Stunde","4 Stunden","Täglich","Wöchentlich","Monatlich","Trade-Überwachung","Automatische Trade-Überwachung","Keine offenen Trades für diesen Markt gespeichert.","Sprache","Automatisch","Dunkelmodus","Hellmodus","Automatische Analyse · Manuelle Ausführung","Intelligente Märkte","Nur Daten, Richtung und Chancen dieses Marktes.","Markt wählen","Unabhängige Datenquellen","Top 3 Chancen","Datenquelle","Kaufen","Verkaufen","Einstieg","Stop-Loss","Ziel 1","Ziel 2","Ziel 3","Kein bestätigter Trade. Warte auf gültige Bedingungen.","Live"],
id:["Menu","Tutup","Beranda","Pasar","Bagian","Konten","Halaman terpisah","Arah pasar","Tren keseluruhan","Aset dipindai","Naik","Turun","Netral","Peluang trading","Arah, likuiditas, dan momentum pada 15 menit","Kerangka waktu","15 menit","1 jam","4 jam","Harian","Mingguan","Bulanan","Pemantauan posisi","Pemantauan otomatis","Tidak ada posisi terbuka tersimpan untuk pasar ini.","Bahasa","Otomatis","Mode gelap","Mode terang","Analisis otomatis · Eksekusi manual","Pasar Cerdas","Hanya data, arah, dan peluang pasar ini.","Pilih pasar","Sumber data independen","3 peluang teratas","Sumber data","Beli","Jual","Entry","Stop loss","Target 1","Target 2","Target 3","Belum ada transaksi terkonfirmasi. Menunggu kondisi valid.","Live"],
"pt-BR":["Menu","Fechar","Início","Mercados","Seções","Conteúdo","Página independente","Direção do mercado","Tendência geral","Ativos analisados","Alta","Baixa","Neutro","Oportunidades","Direção, liquidez e momentum em 15 minutos","Período","15 minutos","1 hora","4 horas","Diário","Semanal","Mensal","Acompanhamento de operações","Acompanhamento automático","Não há operações abertas salvas para este mercado.","Idioma","Automático","Modo escuro","Modo claro","Análise automática · Execução manual","Mercados inteligentes","Somente dados, direção e oportunidades deste mercado.","Selecionar mercado","Fontes de dados independentes","3 melhores oportunidades","Fonte de dados","Comprar","Vender","Entrada","Stop loss","Alvo 1","Alvo 2","Alvo 3","Nenhuma operação confirmada. Aguardando condições válidas.","Ao vivo"],
tr:["Menü","Kapat","Ana sayfa","Piyasalar","Bölümler","İçerik","Bağımsız sayfa","Piyasa yönü","Genel eğilim","Taranan varlıklar","Yükseliş","Düşüş","Nötr","İşlem fırsatları","15 dakikada yön, likidite ve momentum","Zaman dilimi","15 dakika","1 saat","4 saat","Günlük","Haftalık","Aylık","İşlem takibi","Otomatik işlem takibi","Bu piyasa için kayıtlı açık işlem yok.","Dil","Otomatik","Koyu mod","Açık mod","Otomatik analiz · Manuel işlem","Akıllı Piyasalar","Yalnızca bu piyasanın verileri, yönü ve fırsatları.","Piyasa seç","Bağımsız veri kaynakları","En iyi 3 fırsat","Veri kaynağı","Al","Sat","Giriş","Zarar durdur","Hedef 1","Hedef 2","Hedef 3","Onaylanmış işlem yok. Geçerli koşullar bekleniyor.","Canlı"],
fr:["Menu","Fermer","Accueil","Marchés","Sections","Contenu","Page indépendante","Direction du marché","Tendance générale","Actifs analysés","Hausse","Baisse","Neutre","Opportunités","Direction, liquidité et momentum sur 15 minutes","Unité de temps","15 minutes","1 heure","4 heures","Quotidien","Hebdomadaire","Mensuel","Suivi des trades","Suivi automatique","Aucun trade ouvert enregistré pour ce marché.","Langue","Automatique","Mode sombre","Mode clair","Analyse automatique · Exécution manuelle","Marchés intelligents","Données, direction et opportunités de ce marché uniquement.","Choisir un marché","Sources de données indépendantes","Top 3 opportunités","Source des données","Acheter","Vendre","Entrée","Stop loss","Objectif 1","Objectif 2","Objectif 3","Aucun trade confirmé. En attente de conditions valides.","En direct"],
hi:["मेनू","बंद करें","होम","बाज़ार","अनुभाग","सामग्री","अलग पृष्ठ","बाज़ार की दिशा","समग्र रुझान","स्कैन की गई संपत्तियाँ","तेज़ी","मंदी","तटस्थ","ट्रेडिंग अवसर","15 मिनट पर दिशा, लिक्विडिटी और मोमेंटम","समय-सीमा","15 मिनट","1 घंटा","4 घंटे","दैनिक","साप्ताहिक","मासिक","ट्रेड निगरानी","स्वचालित निगरानी","इस बाज़ार के लिए कोई खुला ट्रेड सहेजा नहीं गया है।","भाषा","स्वचालित","डार्क मोड","लाइट मोड","स्वचालित विश्लेषण · मैन्युअल निष्पादन","स्मार्ट मार्केट","केवल इस बाज़ार का डेटा, दिशा और अवसर।","बाज़ार चुनें","स्वतंत्र डेटा स्रोत","शीर्ष 3 अवसर","डेटा स्रोत","खरीदें","बेचें","प्रवेश","स्टॉप लॉस","लक्ष्य 1","लक्ष्य 2","लक्ष्य 3","अभी कोई पुष्ट ट्रेड नहीं। वैध शर्तों की प्रतीक्षा है।","लाइव"]
};
const MARKET_TRANSLATIONS={
ar:["Binance Spot","Binance USD-M Futures","Binance COIN-M Futures","Binance Alpha","السوق السعودي","الأسهم الأمريكية","العقود الأمريكية","الفوركس والذهب"],
en:["Binance Spot","Binance USD-M Futures","Binance COIN-M Futures","Binance Alpha","Saudi Market","U.S. Stocks","U.S. Contracts","Forex & Gold"],
es:["Binance Spot","Futuros Binance USD-M","Futuros Binance COIN-M","Binance Alpha","Mercado saudí","Acciones de EE. UU.","Contratos de EE. UU.","Forex y oro"],
de:["Binance Spot","Binance USD-M Futures","Binance COIN-M Futures","Binance Alpha","Saudi-Arabischer Markt","US-Aktien","US-Kontrakte","Forex & Gold"],
id:["Binance Spot","Binance USD-M Futures","Binance COIN-M Futures","Binance Alpha","Pasar Saudi","Saham AS","Kontrak AS","Forex & Emas"],
"pt-BR":["Binance Spot","Futuros Binance USD-M","Futuros Binance COIN-M","Binance Alpha","Mercado saudita","Ações dos EUA","Contratos dos EUA","Forex e ouro"],
tr:["Binance Spot","Binance USD-M Vadeli","Binance COIN-M Vadeli","Binance Alpha","Suudi Piyasası","ABD Hisseleri","ABD Kontratları","Forex ve Altın"],
fr:["Binance Spot","Futures Binance USD-M","Futures Binance COIN-M","Binance Alpha","Marché saoudien","Actions américaines","Contrats américains","Forex et or"],
hi:["Binance Spot","Binance USD-M Futures","Binance COIN-M Futures","Binance Alpha","सऊदी बाज़ार","अमेरिकी शेयर","अमेरिकी कॉन्ट्रैक्ट","फॉरेक्स और सोना"]
};

const TRADE_KEYS=["currentPrice","returnFromEntry","proposedEntry","riskToStop","potentialProfit","movementSpeed","orderFlow","supportive","opposing","balanced","unavailable","quality","reversal","entryPrice","liveReturn","openCount"];
const TRADE_TEXT={
ar:["السعر الحالي · آخر تحديث","العائد من الدخول","الدخول المقترح","المخاطرة حتى الوقف","ربح محتمل","سرعة الحركة","تدفق الأوامر","مؤيد","معاكس","متوازن","غير متاح","جودة الشروط","الإشارة الفنية","سعر الدخول","العائد الحي من الدخول","مفتوحة"],
en:["Current price · latest update","Return from entry","Proposed entry","Risk to stop","Potential profit","Momentum speed","Order flow","Supportive","Opposing","Balanced","Unavailable","Setup quality","Technical signal","Entry price","Live return from entry","Open"],
es:["Precio actual · última actualización","Rendimiento desde la entrada","Entrada propuesta","Riesgo hasta el stop","Beneficio potencial","Velocidad del movimiento","Flujo de órdenes","A favor","En contra","Equilibrado","No disponible","Calidad de la configuración","Señal técnica","Precio de entrada","Rendimiento actual desde la entrada","Abiertas"],
de:["Aktueller Preis · letzte Aktualisierung","Rendite ab Einstieg","Vorgeschlagener Einstieg","Risiko bis Stop","Mögliches Gewinnziel","Bewegungsdynamik","Orderfluss","Unterstützend","Gegenläufig","Ausgeglichen","Nicht verfügbar","Setup-Qualität","Technisches Signal","Einstiegspreis","Live-Rendite ab Einstieg","Offen"],
id:["Harga saat ini · pembaruan terakhir","Imbal hasil dari entry","Entry yang disarankan","Risiko ke stop","Potensi keuntungan","Kecepatan momentum","Arus order","Mendukung","Berlawanan","Seimbang","Tidak tersedia","Kualitas setup","Sinyal teknikal","Harga entry","Imbal hasil langsung dari entry","Terbuka"],
"pt-BR":["Preço atual · última atualização","Retorno desde a entrada","Entrada sugerida","Risco até o stop","Lucro potencial","Velocidade do movimento","Fluxo de ordens","Favorável","Contrário","Equilibrado","Indisponível","Qualidade da configuração","Sinal técnico","Preço de entrada","Retorno ao vivo desde a entrada","Abertas"],
tr:["Güncel fiyat · son güncelleme","Girişten getiri","Önerilen giriş","Stop seviyesine risk","Potansiyel kâr","Hareket hızı","Emir akışı","Destekleyici","Karşıt","Dengeli","Kullanılamıyor","Kurulum kalitesi","Teknik sinyal","Giriş fiyatı","Girişten anlık getiri","Açık"],
fr:["Prix actuel · dernière mise à jour","Rendement depuis l’entrée","Entrée proposée","Risque jusqu’au stop","Profit potentiel","Vitesse du mouvement","Flux des ordres","Favorable","Opposé","Équilibré","Indisponible","Qualité du signal","Signal technique","Prix d’entrée","Rendement en direct depuis l’entrée","Ouverts"],
hi:["वर्तमान मूल्य · नवीनतम अपडेट","एंट्री से रिटर्न","सुझाई गई एंट्री","स्टॉप तक जोखिम","संभावित लाभ","मूवमेंट की गति","ऑर्डर फ्लो","समर्थक","विरोधी","संतुलित","उपलब्ध नहीं","सेटअप गुणवत्ता","तकनीकी संकेत","एंट्री मूल्य","एंट्री से लाइव रिटर्न","खुले"]
};

const LANG_INDEX=Object.fromEntries(LANG_KEYS.map((key,i)=>[key,i]));
let currentLanguage="ar";
function tr(key){const i=LANG_INDEX[key];if(i!==undefined)return (LANG_TEXT[currentLanguage]||LANG_TEXT.ar)[i];const j=TRADE_KEYS.indexOf(key);return j<0?key:(TRADE_TEXT[currentLanguage]||TRADE_TEXT.ar)[j]}
function effectiveLanguage(choice){
 if(choice!=="auto")return LANG_TEXT[choice]?choice:"ar";
 const browser=(navigator.language||"ar").toLowerCase();
 if(browser.startsWith("pt"))return "pt-BR";
 const match=["ar","en","es","de","id","tr","fr","hi"].find(code=>browser.startsWith(code));
 return match||"ar";
}
function applyLanguage(choice){
 const lang=effectiveLanguage(choice);currentLanguage=lang;
 document.documentElement.lang=lang;document.documentElement.dir=lang==="ar"?"rtl":"ltr";
 const set=(selector,key)=>{const el=$(selector);if(el)el.textContent=tr(key)};
 set("#menuOpen span","menu");set(".drawer-head b","sections");$("#menuOpen")?.setAttribute("aria-label",tr("menu"));set('#siteDrawer a[href="/"]',"home");
 const groups=document.querySelectorAll("#siteDrawer .drawer-group");if(groups[0])groups[0].textContent=tr("markets");if(groups[1])groups[1].textContent=tr("sections");if(groups[2])groups[2].textContent=tr("content");
 const navKeys=["direction","opportunities","openTrades"];const navLinks=[...document.querySelectorAll("#siteDrawer a")];
 const navMap={"/sections/direction":"direction","/sections/opportunities":"opportunities","/sections/open-trades":"openTrades"};
 navLinks.forEach(a=>{const key=navMap[a.getAttribute("href")];if(key)a.textContent=tr(key)});
 const markets=Object.keys(MARKET_NAMES);document.querySelectorAll("[data-market] b").forEach(el=>{const index=markets.indexOf(el.closest("[data-market]")?.dataset.market);if(index>=0)el.textContent=(MARKET_TRANSLATIONS[lang]||MARKET_TRANSLATIONS.ar)[index]});document.querySelectorAll("[data-market] small").forEach(el=>el.textContent=tr("marketIndependent"));
 set(".switcher-heading > span","selectMarket");set(".switcher-heading small","independentSources");
 set("#directionSection .panel-top h2","direction");set("#directionSection .direction-main small","marketTrend");set("#directionSection .breadth-total small","scanned");
 const breadthLabels=["up","down","neutral"];document.querySelectorAll("#directionSection .breadth-legend span").forEach((el,i)=>{el.childNodes.forEach(node=>{if(node.nodeType===3)node.textContent=" "+tr(breadthLabels[i]||"neutral")+" "})});
 set("#opportunitiesSection h2","opportunities");set("#opportunitiesSection p","strategyConfirm");set(".timeframe-label","timeframe");
 const tfKeys=["min15","hour","hour4","daily","weekly","monthly"];document.querySelectorAll("[data-timeframe]").forEach((el,i)=>{if(tfKeys[i])el.textContent=tr(tfKeys[i])});
 set("#openSection h2","openTrades");set("#openSection p","tracking");set("#footerLanguageLabel","language");
 const select=$("#languageSelect");if(select&&select.value!==choice)select.value=choice;if(select?.options[0])select.options[0].textContent=tr("auto");
 const heading=$("#homeSection h1"),description=$("#homeSection p");
 if(heading){if(marketMatch)heading.innerHTML="<span>"+safe(marketName(market))+"</span>";else if(PATH==="/")heading.innerHTML="<span>"+tr("marketHomeTitle")+"</span>"}
 if(description){if(marketMatch||PATH==="/")description.textContent=tr("marketPageDescription")}

 const theme=$("#themeToggle");if(theme)theme.textContent=(document.documentElement.dataset.theme==="light"?"🌙 "+tr("night"):"☀️ "+tr("day"));
}
function applyTheme(theme){
 const value=theme==="light"?"light":"dark";document.documentElement.dataset.theme=value;
 const button=$("#themeToggle");if(button)button.textContent=(value==="light"?"🌙 "+tr("night"):"☀️ "+tr("day"));
 try{localStorage.setItem("stp-theme",value)}catch{}
}
function initPreferences(){
 let language="auto",theme="dark";
 try{language=localStorage.getItem("stp-language")||"auto";theme=localStorage.getItem("stp-theme")||"dark"}catch{}
 const select=$("#languageSelect");if(select){select.value=language;select.addEventListener("change",()=>{try{localStorage.setItem("stp-language",select.value)}catch{}applyLanguage(select.value)})}
 $("#themeToggle")?.addEventListener("click",()=>applyTheme(document.documentElement.dataset.theme==="light"?"dark":"light"));
 applyTheme(theme);applyLanguage(language);
}

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
function livePnl(side,entry,current){
 if(!Number.isFinite(Number(entry))||!Number.isFinite(Number(current))||Number(entry)<=0)return null;
 return (Number(current)/Number(entry)-1)*(side==="BUY"?1:-1)*100;
}
function renderSignals(rows,diagnostics={}){
 const root=$("#cards");
 if(!rows||!rows.length){
  const reasons=diagnostics.rejected_by_reason||{};
  const names={insufficient_candles:"شموع فريم الدخول غير كافية",strategy_15m_only:"تم توحيد الفريم تلقائياً إلى 15 دقيقة",provider_error:"تعذر جلب بيانات المصدر",analysis_error:"خطأ في التحليل",no_confirmed_liquidity_or_momentum_setup:"لم يكتمل تأكيد سحب السيولة أو الاختراق أو الزخم",no_sweep_or_absorption:"لم يظهر سحب سيولة أو امتصاص ضمن نطاق الحركة القريب",volume_below_threshold:"حجم التداول دون الشرط",candle_not_confirmed:"شمعة الدخول غير مؤكدة",risk_above_4_5pct:"مخاطرة أعلى من الحد",invalid_risk_levels:"وقف الخسارة أو مستويات المخاطرة غير صالحة",entry_beyond_stop:"السعر تجاوز الوقف",missing_volume:"بيانات الحجم ناقصة",no_signal:"إشارة الفريم غير واضحة أو لا تحقق شروط الدخول",no_clear_15m_direction:"اتجاه 15 دقيقة غير واضح",invalid_atr:"مدى الحركة غير صالح",malformed_candles:"بيانات شموع غير سليمة",invalid_ohlc:"بيانات سعر غير سليمة",timeframe_conflict:"تعارض شروط التحليل على 15 دقيقة"};
  const top=Object.entries(reasons).sort((a,b)=>b[1]-a[1]).slice(0,3);
  const detail=top.map(([key,count])=>safe(names[key]||key)+' ('+count+')').join(' · ');
  const scanned=Number(diagnostics.candidates_scanned||0);
  root.innerHTML='<div class="empty">'+tr("noTrade")+
   (detail?'<small>أكثر أسباب الاستبعاد: '+detail+'</small>':'')+
   (scanned?'<small>الأصول التي فُحصت في هذه الدورة: '+scanned+'</small>':'')+'</div>';
   return;
 }
 root.innerHTML=rows.map((x,i)=>{
  const side=x.side==="BUY"?1:-1;
  const targetPct=v=>pct(side*(Number(v)/Number(x.entry)-1)*100);
  const stopPct=pct(-Math.abs(Number(x.risk_percent)||Math.abs((x.stop_loss/x.entry-1)*100)));
  const live=x.price==null?null:Number(x.price),pnl=live===null?null:livePnl(x.side,x.entry,live);
  const liveText=live===null?"—":fmt(live);
  const rank=i===0?"gold":i===1?"silver":i===2?"bronze":"standard";const medal=i===0?"👑":i===1?"🥈":i===2?"🥉":"";const rankLabel=i===0?"المركز الأول · ذهبي":i===1?"المركز الثاني · فضي":i===2?"المركز الثالث · برونزي":"ترتيب "+(i+1);
  const flow=x.institutional_flow||{};
  return '<article class="trade pro-trade-card"><div class="pro-card-top '+(i<3?"podium-"+rank:"")+'"><div class="trade-title"><span class="rank '+rank+'"><span class="rank-medal">'+medal+'</span><b>'+(i+1)+'</b></span><div><b>'+safe(x.symbol)+'</b><small class="card-market-label">'+safe(marketName(market))+' · '+safe(x.timeframe||"15m")+'</small></div></div><div class="card-live-state"><i></i> '+rankLabel+'</div></div><div class="pro-signal-strip"><span class="market-direction '+(x.side==="BUY"?"up":"down")+'">'+(x.side==="BUY"?"▲ "+tr("up"):"▼ "+tr("down"))+'</span><span class="tag '+(x.side==="BUY"?"buy":"sell")+'">'+(x.side==="BUY"?tr("buy"):tr("sell"))+'</span><span class="quality-chip">جودة الشروط '+Number(x.quality_score||0)+'/100</span><span class="quality-chip">الإشارة الفنية: '+safe(x.signal_state_ar||"—")+'</span></div><div class="pro-live-price"><div><small>السعر الحالي · آخر تحديث</small><b>'+liveText+'</b></div><div class="live-pnl '+(pnl>=0?"up":"down")+'"><small>العائد من الدخول</small><b>'+(pnl===null?"—":(pnl>0?"+":"")+pnl.toFixed(2)+"%")+'</b></div></div><div class="pro-entry-line"><span>الدخول المقترح</span><b>'+fmt(x.entry)+'</b><span>المخاطرة حتى الوقف</span><b class="down">'+stopPct+'</b></div><div class="pro-target-grid"><div class="target-box"><small>TP1 · '+(x.tp1_r_multiple?Number(x.tp1_r_multiple).toFixed(1)+'R':'هدف متغير')+'</small><b>'+fmt(x.tp1)+'</b><em>'+targetPct(x.tp1)+'</em></div><div class="target-box"><small>TP2 · '+(x.tp2_r_multiple?Number(x.tp2_r_multiple).toFixed(1)+'R':'هدف متغير')+'</small><b>'+fmt(x.tp2)+'</b><em>'+targetPct(x.tp2)+'</em></div><div class="target-box"><small>TP3 · '+(x.tp3_r_multiple?Number(x.tp3_r_multiple).toFixed(1)+'R':'هدف متغير')+'</small><b>'+fmt(x.tp3)+'</b><em>'+targetPct(x.tp3)+'</em></div><div class="target-box stop-box"><small>وقف الخسارة</small><b>'+fmt(x.stop_loss)+'</b><em>'+stopPct+'</em></div></div><div class="pro-card-footer"><span>سرعة الحركة <b>'+Number(x.fast_mover_score||0)+'/100</b></span><span>تدفق الأوامر <b>'+safe(flow.status==="supportive"?tr("supportive"):flow.status==="opposing"?tr("opposing"):flow.status==="balanced"?tr("balanced"):tr("unavailable"))+'</b></span><span>تغير 24س <b class="'+(x.change24h>=0?"up":"down")+'">'+pct(x.change24h)+'</b></span></div><div class="pro-card-note">العائد المحتمل محسوب من الدخول إلى الهدف، وليس ضمانًا للربح.</div></article>';
 }).join("");
}
function renderOpen(rows){
 const root=$("#openTrades");$("#openCount").textContent=(rows?.length||0)+" مفتوحة";
 if(!rows||!rows.length){root.innerHTML='<div class="empty">'+tr("noOpenTrades")+'</div>';return}
 root.innerHTML=rows.map(x=>{
  const pnl=x.current_price==null?null:(x.live_pnl_percent==null?livePnl(x.side,x.entry,x.current_price):Number(x.live_pnl_percent));
  const current=x.current_price==null?"—":fmt(x.current_price);
  const target=(name,value,lit,kind)=>'<div class="tracked-level '+(lit?'level-lit '+kind:'')+'"><small>'+name+'</small><b>'+fmt(value)+'</b></div>';
  return '<article class="tracked-trade-card"><div class="tracked-head"><div><b>'+safe(x.symbol)+'</b><small>'+safe(marketName(x.market))+' · '+(x.side==="BUY"?tr("buy"):tr("sell"))+' · '+safe(x.timeframe)+'</small></div></div><div class="tracked-live-grid"><div><small>السعر الحالي</small><b>'+current+'</b></div><div><small>العائد الحي من الدخول</small><b class="'+(pnl>=0?"up":"down")+'">'+(pnl==null?"—":(pnl>0?"+":"")+pnl.toFixed(2)+"%")+'</b></div><div><small>سعر الدخول</small><b>'+fmt(x.entry)+'</b></div></div><div class="tracked-levels">'+target("TP1",x.tp1,x.tp1_hit,"target-lit")+target("TP2",x.tp2,x.tp2_hit,"target-lit")+target("TP3",x.tp3,x.tp3_hit||x.status==="TP3","target-lit")+target(tr("stopLoss"),x.stop_loss,x.status==="SL","stop-lit")+'</div></article>';
 }).join("");
}
function renderClosed(rows){
 const closed=(rows||[]).filter(x=>x.status!=="OPEN").slice(0,100);
 $("#historyCount").textContent=closed.length+" مغلقة";
 const root=$("#closedTrades");
 if(!closed.length){root.innerHTML='<div class="empty">لا توجد نتائج مغلقة مسجلة بعد.</div>';return}
 root.innerHTML=closed.map(x=>'<article class="history-row"><div><b>'+safe(x.symbol)+'</b><small>'+(x.side==="BUY"?"شراء":"بيع")+' · '+safe(marketName(x.market))+'</small></div><div><small>الدخول</small><b>'+fmt(x.entry)+'</b></div><div><small>النتيجة</small><b class="history-status '+(x.status==="TP3"?"tp history-lit-target":x.status==="EXPIRED"?"expired":"sl history-lit-stop")+'">'+(x.status==="TP3"?"وصل TP3":x.status==="EXPIRED"?"انتهت صلاحية 24س":"وقف الخسارة")+'</b></div><div><small>تاريخ الإغلاق</small><b>'+new Date((x.closed_at||x.updated_at)*1000).toLocaleDateString("ar-SA")+'</b></div></article>').join("");
}
async function loadHistoryPage(){
 const root=$("#closedTrades");
 if(root)root.innerHTML='<div class="empty">جارٍ تحميل نتائج جميع الأسواق...</div>';
 try{
  const d=await get("/api/trades",12000);
  const rows=d.items||[];
  const closed=rows.filter(x=>x.status!=="OPEN");
  const wins=closed.filter(x=>x.status==="TP3").length;
  const losses=closed.filter(x=>x.status==="SL").length;
  const expired=closed.filter(x=>x.status==="EXPIRED").length;
  $("#historySummary").innerHTML='<article class="result-metric"><small>إجمالي الصفقات المغلقة</small><b>'+closed.length+'</b></article><article class="result-metric"><small>وصلت للهدف الثالث</small><b class="up">'+wins+'</b></article><article class="result-metric"><small>وصلت لوقف الخسارة</small><b class="down">'+losses+'</b></article><article class="result-metric"><small>انتهت صلاحيتها</small><b>'+expired+'</b></article><article class="result-metric"><small>نسبة TP3 من TP3 وSL</small><b>'+((wins+losses)?(wins/(wins+losses)*100).toFixed(1)+'%':'—')+'</b></article>';
  renderClosed(rows);
  $("#health").textContent="تم تحديث النتائج";$("#health").className="ok";
 }catch(e){
  if(root)root.innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  $("#health").textContent="تعذر تحميل النتائج";$("#health").className="bad";
 }
}
async function loadMarketStatuses(){
 try{
  const d=await get("/api/markets",8000);
  const states=new Map((d.markets||[]).map(x=>[x.id,x]));
  marketStatuses=states;
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
function renderGamma(payload){
 const root=$("#gammaCards"),note=$("#gammaNote");
 if(!payload){root.innerHTML='<div class="empty">تحليل السيولة المحلي غير متاح الآن.</div>';return}
 root.innerHTML='<article class="gamma-card"><div class="gamma-card-head"><b>محرك السيولة المحلي</b><span class="gamma-status up">يعمل دون مفاتيح</span></div><div class="gamma-levels"><div><small>نوع التحليل</small><b>OHLCV</b></div><div><small>نسبة الحجم</small><b>Volume Ratio</b></div><div><small>ضغط السعر</small><b>Price Pressure</b></div><div><small>سحب السيولة</small><b>Liquidity Sweep</b></div><div><small>الامتصاص</small><b>Absorption</b></div></div><small class="gamma-time">'+safe(payload.message||"تحليل محلي من بيانات الشموع والحجم العامة؛ ليس Options GEX.")+'</small></article>';
 if(note)note.textContent="محرك التحليل لا يحتاج مفاتيح API. لا يتم احتساب Gamma Exposure أو بيانات الخيارات دون مصدر خيارات موثوق.";
}
async function loadGamma(){
 const button=$("#gammaRefresh"),root=$("#gammaCards");
 if(!button||button.disabled)return;
 button.disabled=true;button.textContent="جارٍ تحديث التحليل...";
 root.innerHTML='<div class="empty">جارٍ تحميل بيانات الشموع العامة وتحليل السيولة...</div>';
 try{const d=await get("/api/analysis/method",12000);renderGamma(d)}
 catch(e){root.innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
 finally{button.disabled=false;button.textContent="تحديث تحليل السيولة"}
}
$("#gammaRefresh")?.addEventListener("click",loadGamma);


async function load(){
 if(busy){pending=true;return}
 busy=true;pending=false;
 const refresh=$("#refresh");if(refresh){refresh.disabled=true;refresh.innerHTML="<span>↻</span> جارٍ التحديث";}
 $("#health").textContent="جارٍ التحديث";
 try{
  const requestedMarket=market;
   const requestedTimeframe=analysisTimeframe;
  const providerState=marketStatuses.get(requestedMarket);
  if(providerState && !["live","configured_watchlist"].includes(providerState.status)){
   $("#direction").textContent="غير متاح";
   $("#direction").className="direction-value neutral";
   ["#up","#down","#flat","#total"].forEach(id=>$(id).textContent="—");
      $("#source").textContent="مصدر البيانات غير مربوط";
   $("#upBar").style.width="0%";$("#downBar").style.width="0%";$("#flatBar").style.width="0%";
      $("#cards").innerHTML='<article class="scan-diagnostic"><h3>مصدر البيانات غير مربوط</h3><p>هذا السوق لا يملك حالياً مزود بيانات مفعّلاً. لن نعرض أسعاراً أو توصيات غير موثوقة.</p></article>';
   $("#openTrades").innerHTML='<div class="empty">'+tr("noOpenTrades")+'</div>';
   $("#openCount").textContent="—";
   $("#health").textContent="المصدر غير مربوط";
   $("#health").className="bad";
   return;
  }
  const section=PATH.startsWith("/sections/")?PATH.split("/").pop():requestedMarket;
  const d=await get("/api/market/"+requestedMarket+"?timeframe="+encodeURIComponent(requestedTimeframe)+"&section="+encodeURIComponent(section),60000);
  if(requestedMarket!==market||requestedTimeframe!==analysisTimeframe){pending=true;return}
  $("#direction").textContent=d.direction==="BUY"?tr("up"):d.direction==="SELL"?tr("down"):tr("neutral");$("#direction").className="direction-value "+(d.direction==="BUY"?"up":d.direction==="SELL"?"down":"neutral");
  $("#up").textContent=d.up;$("#down").textContent=d.down;$("#flat").textContent=d.flat??0;$("#total").textContent=d.total;
  const total=Math.max(1,Number(d.total)||0);
  $("#upBar").style.width=(d.up/total*100)+"%";$("#downBar").style.width=(d.down/total*100)+"%";$("#flatBar").style.width=((d.flat||0)/total*100)+"%";
    $("#source").textContent="مصدر البيانات: "+d.source+" · "+d.strategy;
    
  renderSignals(d.signals,d.scan_diagnostics||{});renderOpen(d.open_trades);
  const strategyLabel={"15m":"الاتجاه والسيولة والزخم والدخول · 15 دقيقة"};
  const label=$("#activeStrategy");if(label)label.textContent=strategyLabel[analysisTimeframe]||analysisTimeframe;
  const minutes=Math.max(0,Math.ceil(Number(d.seconds_until_next_scan||0)/60));
  $("#health").textContent=d.snapshot_stale?"آخر نتائج محفوظة · المصدر متوقف مؤقتاً":d.scan_cached?"نتائج محفوظة · الفحص القادم بعد "+minutes+" د":"اكتمل الفحص وحُفظت النتائج";
  $("#health").className=d.snapshot_stale?"bad":"ok";
  if(d.snapshot_stale&&d.message)$("#source").textContent+=" · "+d.message;
 }catch(e){
  $("#direction").textContent="غير متاح";$("#direction").className="direction-value neutral";
  ["#up","#down","#flat","#total"].forEach(id=>$(id).textContent="—");
    $("#upBar").style.width="0%";$("#downBar").style.width="0%";$("#flatBar").style.width="0%";
  $("#openCount").textContent="—";
  $("#openTrades").innerHTML='<div class="empty">تعذر تحديث متابعة الصفقات؛ أعد المحاولة عند عودة المصدر.</div>';
  $("#cards").innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  
  $("#health").textContent="غير متصل";$("#health").className="bad";
 }finally{
  busy=false;if(refresh){refresh.disabled=false;refresh.innerHTML="<span>↻</span> تحديث البيانات";}
  if(pending){pending=false;load()}
 }
}


$("#refresh")?.addEventListener("click",()=>{if(PATH==="/sections/history")loadHistoryPage();else load()});
document.querySelectorAll("[data-timeframe]").forEach(button=>button.addEventListener("click",()=>{
 const next=button.dataset.timeframe;if(!VALID_TFS.includes(next)||next===analysisTimeframe)return;
 analysisTimeframe=next;syncTimeframeButtons();
 const url=new URL(location.href);url.searchParams.set("timeframe",next);history.replaceState({}, "", url);
 load();
}));
async function loadNews(){
 const root=$("#newsFeed");if(!root)return;
 root.innerHTML='<div class="empty">جارٍ جلب آخر العناوين...</div>';
 try{
  const d=await get("/api/news",10000);
  if(!d.items?.length){root.innerHTML='<div class="empty">'+safe(d.error||"لا توجد عناوين متاحة الآن.")+'</div>';return}
  root.innerHTML=d.items.map(x=>'<article class="news-item"><div><small>'+safe(x.source||"مصدر خارجي")+' · '+safe(x.published||"")+'</small><h3>'+safe(x.title)+'</h3></div><span class="news-arrow" aria-label="خبر داخل المنصة">•</span></article>').join("");
 }catch(e){root.innerHTML='<div class="empty">'+safe(e.message)+'</div>'}
}
$("#newsRefresh")?.addEventListener("click",loadNews);

async function loadHomeOverview(){
 const moversRoot=$("#homeMovers"),coverageRoot=$("#homeCoverage");
 if(!moversRoot||!coverageRoot)return;
 try{
  const data=await get("/api/overview",25000);
  $("#homeAssetCount").textContent=compact(data.eligible_assets||0);
  $("#homeMarketCount").textContent=(data.available_markets||0)+" / "+(data.markets||[]).length;
  $("#homeMoverCount").textContent=(data.fast_movers||[]).length;
  $("#homeUpdated").textContent="آخر فحص · "+new Date((data.updated||Date.now()/1000)*1000).toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});
  const movers=data.fast_movers||[];
  moversRoot.innerHTML=movers.length?movers.map((x,i)=>'<div class="home-mover-row"><span class="home-mover-rank">'+(i+1)+'</span><div class="home-mover-name"><b>'+safe(x.symbol)+'</b><small>'+safe(x.market_name)+'</small></div><b class="home-mover-change '+(Number(x.change24h)>=0?"up":"down")+'">'+pct(x.change24h)+'</b></div>').join(""):'<div class="empty">لا توجد بيانات حركة مؤكدة من المصادر المتاحة حاليًا.</div>';
  coverageRoot.innerHTML=(data.markets||[]).map(x=>{
   const ready=x.status==="live"||x.status==="watchlist";
   const state=x.status==="watchlist"?"قائمة محددة":ready?"متاح":x.status==="provider_required"?"المصدر غير مربوط":"تعذر التحديث";
   const direction=x.direction==="BUY"?"صاعد":x.direction==="SELL"?"هابط":x.direction==="NEUTRAL"?"محايد":"—";
   const breadth=ready&&x.up!=null?" · "+direction+" ("+x.up+"/"+x.down+")":"";
   return '<a class="home-coverage-row" href="/markets/'+encodeURIComponent(x.id)+'"><span class="home-coverage-dot '+(ready?"ready":"")+'"></span><span class="home-coverage-name">'+safe(x.name)+'</span><b>'+ (ready?compact(x.eligible_assets)+" أصل · "+state+breadth:state)+'</b><span class="home-coverage-arrow">←</span></a>';
  }).join("");
 }catch(e){
  moversRoot.innerHTML='<div class="empty">'+safe(e.message)+'</div>';
  coverageRoot.innerHTML='<div class="empty">تعذر قراءة تغطية الأسواق الآن.</div>';
 }
}

function configurePage(){
 document.body.classList.toggle("home-page",PATH==="/");
 document.body.classList.toggle("market-page",!!marketMatch);
 const timeframeSwitcher=$("#marketTimeframeSwitcher");if(timeframeSwitcher)timeframeSwitcher.hidden=!marketMatch;
 const adminAllowed=!$("#adminPanel").hidden;$("#adminPanel").hidden=true;
 const ids=["homeSection","homeOverview","marketSection","directionSection","opportunitiesSection","cards","openSection","blogSection","newsSection"];
 const hideAll=()=>ids.forEach(id=>{const el=$("#"+id);if(el)el.hidden=true});
 const show=(...names)=>names.forEach(id=>{const el=$("#"+id);if(el)el.hidden=false});
 if(PATH==="/"){
  hideAll();show("homeSection","homeOverview","marketSection");
  $("#homeSection h1").innerHTML='<span>'+tr("marketHomeTitle")+'</span>';
  $("#homeSection p").textContent=tr("marketPageDescription");
 }else if(marketMatch){
  if(!MARKET_NAMES[market]){location.replace("/");return}
  hideAll();show("homeSection","directionSection","opportunitiesSection","cards","openSection");
  $("#homeSection h1").innerHTML='<span>'+safe(marketName(market))+'</span>';
  $("#homeSection p").textContent="اتجاه السوق والفرص والصفقات الخاصة بهذا السوق فقط.";
 }else if(PATH.startsWith("/sections/")){
  const section=PATH.split("/").pop();
  const map={direction:["directionSection"],opportunities:["opportunitiesSection","cards"],"open-trades":["opportunitiesSection","cards","openSection"]};
  hideAll();show("homeSection",...(map[section]||[]));
  const titles={direction:"توجه السوق",opportunities:"فرص التداول","open-trades":"متابعة الصفقات"};
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
 const refreshButton=$("#refresh");if(refreshButton)refreshButton.hidden=true;
 if(PATH==="/admin"){
  if(!adminAllowed){location.replace("/");return}
  hideAll();show("homeSection","adminPanel");$("#adminPanel").hidden=false;
  $("#homeSection h1").innerHTML="إدارة <span>المشتركين</span>";
  $("#homeSection p").textContent="إدارة الحسابات والصلاحيات بشكل مستقل.";
 }
 const drawer=$("#siteDrawer");
 if(drawer)drawer.querySelectorAll("a").forEach(a=>a.classList.toggle("active",a.getAttribute("href")===PATH));
}

document.addEventListener("visibilitychange",()=>{
 if(document.hidden||$("#mainContent").hidden||busy)return;
 if(marketMatch||(["direction","opportunities","open-trades"].includes(PATH.split("/").pop())&&PATH.startsWith("/sections/"))){load();}
 
});
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
 $("#accessMessage").textContent=user?"حسابك مسجل. اختر مدة الاشتراك وطريقة الدفع لتفعيل الوصول.":"أنشئ حساباً أو سجل دخولك للوصول إلى المنصة.";
 $("#subscriptionPanel").hidden=!user;
}
async function startAuthorized(user=null){
 $("#accessGate").hidden=true;
 $("#mainContent").hidden=false;
 $("#topLogout").hidden=!user;
 $("#adminPanel").hidden=!(user&&user.is_admin);
 $("#drawerAdmin").hidden=!(user&&user.is_admin);
 if(user&&user.is_admin){await loadAdminUsers();await loadAdminPayments();await loadAdminSections();}
 configurePage();
 if(user&&!user.is_admin)await loadUserSectionAccess();
 if(marketMatch){await loadMarketStatuses();await load();}
 else if(PATH==="/"){await loadMarketStatuses();await loadHomeOverview();}
 else if(PATH.startsWith("/sections/") && ["direction","opportunities","open-trades"].includes(PATH.split("/").pop())){await loadMarketStatuses();await load();}
 else if(PATH==="/sections/history"){await loadHistoryPage();}
}
async function initializeAccess(){
 let user=null;
 try{
  const d=await get("/api/auth/me",7000);
  user=d?.user||null;
 }catch(e){console.warn("Optional account lookup failed; continuing with public market access.",e)}
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
  else {await showAccess("تم إنشاء الحساب. اختر مدة الاشتراك وأكمل الدفع.",d.user);await loadPaymentOptions();}
 }catch(err){$("#authNotice").textContent=err.message}
 finally{button.disabled=false}
});
async function logout(){
 await fetch("/api/auth/logout",{method:"POST"});
 location.reload();
}
$("#authLogout").addEventListener("click",logout);
$("#topLogout").addEventListener("click",logout);
async function loadUserSectionAccess(){
 try{
  const d=await get("/api/access/sections",7000),sections=d.sections||{};
  // Market pages remain public; section switches cannot hide market access.
  const links={"/sections/direction":"direction","/sections/opportunities":"opportunities","/sections/open-trades":"open-trades","/sections/history":"history","/news":"news","/blog":"blog"};
  Object.entries(links).forEach(([href,key])=>{const el=document.querySelector('#siteDrawer a[href="'+href+'"]');if(el)el.hidden=sections[key]===false});
  const page=PATH.startsWith("/sections/")?PATH.split("/").pop():(PATH==="/blog"?"blog":PATH==="/news"?"news":"");
  if(page&&sections[page]===false){$("#health").textContent="هذا القسم مغلق من الإدارة";$("#health").className="bad";}
 }catch(e){console.warn("Section permissions unavailable",e)}
}

async function loadPaymentOptions(){try{let d=await get("/api/payments/options");$("#planMonths").innerHTML=Object.entries(d.prices).map(([m,p])=>'<option value="'+m+'">'+m+' شهر · '+p+' USDT</option>').join("");$("#paymentNetwork").innerHTML=Object.entries(d.networks).map(([k,n])=>'<option value="'+k+'">'+safe(n.label)+'</option>').join("");updatePlanAmount()}catch(e){$("#paymentNotice").textContent=e.message}}
function updatePlanAmount(){let p={1:30,2:60,3:90,6:180,12:360};$("#planAmount").textContent=(p[$("#planMonths").value]||30)+" USDT"}
$("#planMonths").addEventListener("change",updatePlanAmount);
$("#createPaymentOrder").addEventListener("click",async()=>{try{let r=await fetch("/api/payments/orders",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({months:+$("#planMonths").value,network:$("#paymentNetwork").value})}),d=await r.json();if(!r.ok)throw Error(d.message);$("#activeOrderId").value=d.order.id;$("#paymentAddress").textContent=d.payment.address;$("#paymentAddressWrap").hidden=false;$("#txHashWrap").hidden=!d.payment.automatic_verification;$("#binancePayNote").hidden=d.payment.automatic_verification;$("#paymentNotice").textContent="طلب #"+d.order.id+" · "+d.order.amount_usdt+" USDT"}catch(e){$("#paymentNotice").textContent=e.message}});
$("#copyPaymentAddress").addEventListener("click",()=>navigator.clipboard.writeText($("#paymentAddress").textContent).then(()=>$("#paymentNotice").textContent="تم النسخ").catch(()=>$("#paymentNotice").textContent="انسخ العنوان يدوياً"));
$("#submitBinanceReference").addEventListener("click",async()=>{try{let r=await fetch("/api/payments/reference",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({order_id:+$("#activeOrderId").value,reference:$("#binancePayReference").value.trim()})}),d=await r.json();if(!r.ok)throw Error(d.message);$("#paymentNotice").textContent=d.message}catch(e){$("#paymentNotice").textContent=e.message}});
$("#verifyPayment").addEventListener("click",async()=>{try{let r=await fetch("/api/payments/verify",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({order_id:+$("#activeOrderId").value,tx_hash:$("#txHash").value.trim()})}),d=await r.json();if(!r.ok)throw Error(d.message);$("#paymentNotice").textContent=d.message;setTimeout(()=>location.reload(),700)}catch(e){$("#paymentNotice").textContent=e.message}});


async function loadAdminPayments(){try{let d=await get("/api/admin/payments");$("#adminPayments").innerHTML=d.payments.map(p=>'<p>'+safe(p.email)+' · #'+p.id+' · '+p.months+' شهر · '+p.amount_usdt+' USDT · '+safe(p.network)+' · '+safe(p.status)+(p.note?' · '+safe(p.note):'')+(p.network==="binance_pay"&&p.status==="pending"?' <button data-pay="'+p.id+'" data-action="approve">قبول</button><button data-pay="'+p.id+'" data-action="reject">رفض</button>':'')+'</p>').join("")||"لا توجد طلبات"}catch(e){$("#adminPayments").textContent=e.message}}
async function loadAdminSections(){try{let d=await get("/api/admin/sections");$("#adminSections").innerHTML=d.sections.map(x=>'<label>'+safe(x.name)+' <input type="checkbox" data-section="'+x.id+'" '+(x.enabled?"checked":"")+'> '+(x.enabled?"مفتوح":"مغلق")+'</label>').join("")}catch(e){$("#adminSections").textContent=e.message}}
$("#adminPaymentsRefresh").addEventListener("click",loadAdminPayments);
$("#adminSections").addEventListener("change",async e=>{let x=e.target.closest("[data-section]");if(!x)return;try{let r=await fetch("/api/admin/sections",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({section:x.dataset.section,enabled:x.checked})});if(!r.ok)throw Error("تعذر تحديث القسم")}catch(err){x.checked=!x.checked;alert(err.message)}});
$("#adminPayments").addEventListener("click",async e=>{let b=e.target.closest("[data-pay]");if(!b)return;try{let r=await fetch("/api/admin/payments/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({order_id:+b.dataset.pay,action:b.dataset.action})});if(!r.ok)throw Error("تعذر تحديث الدفع");await loadAdminPayments()}catch(err){alert(err.message)}});

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
initPreferences();
initializeAccess();
timer=setInterval(()=>{if(document.hidden||$("#mainContent").hidden||busy)return;if(marketMatch||(["direction","opportunities","open-trades"].includes(PATH.split("/").pop())&&PATH.startsWith("/sections/"))){load()}else if(PATH==="/")loadHomeOverview()},60000);

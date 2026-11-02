# التداول الذكي PRO

منصة عربية RTL لمراقبة الأسواق وتحليل الفرص الفنية، بواجهة داكنة متجاوبة ومصادر بيانات عامة.

## التشغيل
`pip install -r requirements.txt`
`python app.py`

## الأسواق ومصادر البيانات
- Binance Spot: واجهات Binance العامة الرسمية مع تدوير تلقائي بين api.binance.com وapi-gcp وapi1 إلى api4 وdata-api.binance.vision؛ لا تحتاج مفاتيح API.
- Binance USD-M Futures: واجهة Binance العامة؛ يكتشف العقود الدائمة النشطة فقط ويشترط قيمة تداول 24 ساعة لا تقل عن مليون دولار.
- Binance COIN-M Futures: واجهة Binance DAPI العامة؛ سوق مستقل لعقود COIN-M الدائمة النشطة، مع شرط قيمة تداول 24 ساعة لا تقل عن مليون دولار.
- Binance Alpha: واجهات Binance العامة لقائمة الرموز ومعلومات أزواج USDT والشموع؛ لا تحتاج مفاتيح API، ولا يوجد بديل مطابق موثوق.
- الفوركس والذهب: رُبط BiQuote العام دون مفتاح API لاكتشاف رموز Forex/Commodity وجلب الأسعار والشموع المغلقة 15m؛ تُرفض الأسعار المغلقة أو الأقدم من 5 دقائق.
- الأسهم السعودية والأسهم الأمريكية: أُضيف موصل Yahoo Finance اختياري عبر yfinance للاختبار الداخلي فقط. لا يعمل افتراضياً؛ يتطلب YAHOO_FINANCE_ENABLED=1 وقوائم YAHOO_SAUDI_SYMBOLS وYAHOO_US_SYMBOLS (رموز مفصولة بفواصل). يفحص فقط الرموز المضبوطة، ويرفض الأسعار الأقدم من 45 دقيقة والشموع غير المكتملة. لا يعتبر هذا تغطية كاملة للسوق ولا يجوز إعادة توزيع بيانات Yahoo على موقع عام دون ترخيص. لا تفعّل هذا المصدر على موقع عام قبل التأكد من شروط الاستخدام وتأمين الموقع الخاص.
- العقود الأمريكية: ما زالت غير مفعّلة؛ موصل Yahoo هذا لا يوفر فحصاً موثوقاً لكل عقود الخيارات.
- `/api/providers` يعرض حالة كل مزود ومسارات الاحتياط المفعّلة فعلياً، ويميزها عن المصادر التي لم تُدمج أو لم تُتحقق.
- Yahoo اختياري ويتطلب إعداد متغيرات البيئة في الاستضافة؛ لا يتم تفعيله تلقائياً.

## لوحة المنصة
- اتجاه السوق محسوب من عدد الأصول الصاعدة والهابطة والمحايدة خلال 24 ساعة.
- ترتيب الأصول الأسرع حركة أولاً بدرجة نسبية تعتمد على زخم 24 ساعة ونطاق الحركة والسيولة، ثم فحص أول 40 أصلاً في الترتيب. الدرجة ترتيب فحص وليست احتمال ربح.
- التحقق من أن رموز Binance Spot وUSD-M وCOIN-M نشطة وقابلة للتداول عبر exchangeInfo قبل إدراجها.
- فريمات التحليل القابلة للاختيار: 15m و1h و4h و1d و1w و1M؛ تأكيد اتجاه الأصل من 4 ساعات واليومي معاً؛ لا تُقبل إلا جهة متوافقة في الفريمين. الدخول يُحلل على الفريم المختار (15m افتراضياً)، وترتيب الفرص يعتمد على تغير شمعة 15m المكتملة. حد أقصى لأربع عمليات تحليل متوازية.
- عرض الدخول والأهداف الثلاثة والوقف ومؤشرات المخاطرة وجودة الشروط.
- سجل الصفقات المفتوحة والصفقات المغلقة.
- تحديث تلقائي كل 60 ثانية عند بقاء الصفحة ظاهرة، مع منع تداخل الطلبات ومهلة اتصال.
- تصميم RTL داكن متجاوب للجوال وسطح المكتب.

## API
- `/health` و`/api/health`
- `/api/markets`
- `/api/market/spot`
- `/api/market/futures`
- `/api/market/coinm`
- `/api/market/alpha`
- `/api/trades?market=spot`

## HAWK QUANT PRO v2 — محرك الاستراتيجية الموحد
- **اتجاه الأصل:** شموع 4 ساعات واليومي المكتملة؛ لا تُقبل الصفقة إلا إذا اتفق الفريمان على BUY أو SELL.
- **بوابة اتجاه السوق:** اتجاه اتساع السوق خلال 24 ساعة يجب أن يوافق جهة الصفقة؛ الاتجاه المحايد أو المعاكس يمنع فتح صفقات جديدة.
- **الدخول:** تحليل شموع 15 دقيقة المكتملة فقط عبر سحب السيولة والاسترداد، أو الامتصاص، أو الاختراق/الاستمرار المؤكد بالحجم والضغط السعري.
- **الترتيب:** يفحص النظام دفعات صغيرة من الأصول ذات الحركة والسيولة، ثم يرتب الفرص المقبولة حسب تغير 15 دقيقة الموافق لاتجاه الصفقة، ثم جودة الشروط. يعرض أفضل 3 فقط.
- **تأكيد دفتر الأوامر:** متاح كعامل مساعد للأسواق المدعومة من Binance فقط؛ لا يمنع التحليل في الأسواق الأخرى ولا يُقدّم على أنه تدفق مؤسسي خفي.
- **المخاطر:** وقف خلف منطقة الحدث مع هامش تقلب، و3 أهداف متكيفة مع ATR ومضاعفات المخاطرة. تُرفض المخاطرة التي تتجاوز 4.5% من سعر الدخول.
- **الدرجة:** مقياس توافق شروط من 100، وليست نسبة نجاح أو احتمال ربح. لا توجد مفاتيح API خاصة أو ربط بحساب تداول، ولا تنفيذ آلي.
- المحرك النشط موحد في strategy_engine.py؛ وحدات التحليل القديمة المساعدة ليست مسارات استراتيجية مستقلة في الفحص المباشر.

**حدود بيانات Gamma:** لا يوجد حالياً مزود موثوق موحد لبيانات خيارات/GEX يغطي كل الأسواق والأصول. لذلك لا يعرض النظام قيمة Gamma ولا ينسب مراكز لصانع السوق عند غياب بيانات الخيارات. ضغط الشمعة والحجم النسبي إشارات مشتقة من OHLCV وليست Delta فعلية أو دفتر أوامر أو مراكز صانع السوق. يتطلب GEX الحقيقي تكامل بيانات خيارات مرخصة لكل سوق يدعمها.

## تتبع الصفقات
تُحفظ الصفقات في SQLite وتُحدّث حالة TP1 وTP2 وTP3 وSL عند تحديث بيانات السوق. ثبّت وحدة تخزين دائمة في Northflank على `/data` حتى تبقى السجلات بعد إعادة النشر. لا يتم تنفيذ أوامر تداول آلية.

## النشر والاختبارات
المنفذ 8080. على موارد Northflank الصغيرة (0.2 vCPU / 512 MB) يعمل Gunicorn بعامل واحد وأربع خيوط، مع مهلة 60 ثانية، لتقليل استهلاك الذاكرة وتجنب إنهاء طلبات الفحص الطويلة مبكرًا. فحوص CI تشمل compileall وNode syntax check وpytest.


## Accounts and subscriptions

Market data, analysis, and trade tracking are available in read-only mode without a paid subscription. Account sign-in is optional. Administrative user and subscription management endpoints remain restricted to the administrator.

Configure these secrets in the hosting service before enabling access:

- `SECRET_KEY`: a long random secret (at least 32 random bytes).
- `ADMIN_EMAIL`: the administrator login email.
- `ADMIN_PASSWORD`: the initial administrator password (at least 12 characters).

The first administrator account is created automatically in the persistent SQLite database on first request. Keep `/data` on persistent storage so accounts survive restarts. Do not commit secret values to GitHub. Optional registration uses email/password; no payment processing is integrated.


## GammaFlip crypto GEX
- تكامل اختياري للقراءة فقط عبر GammaFlip REST API: `GAMMAFLIP_API_KEY` يحفظ في Northflank Secrets فقط، ولا يوضع في GitHub أو JavaScript.
- يغطي GEX الحقيقي العملات التي لديها خيارات مدعومة: BTC وETH وSOL وXRP وHYPE، مع تجميع venues المتاحة عبر `/levels/all/{coin}`.
- يعرض Gamma Flip وNet GEX وCall/Put walls ووقت لقطة البيانات. تُرفض اللقطات الأقدم من 30 دقيقة أو غير الموسومة كسوق Crypto.
- زر تحديث يدوي فقط؛ النتيجة تخزن 15 دقيقة. كل دفعة تكلف حتى 5 طلبات، والحد المحلي الافتراضي 40 طلبًا يوميًا لترك هامش من حصة التجربة. يمكن ضبط `GAMMAFLIP_DAILY_BUDGET` حسب خطة المزود.
- العملات غير المدعومة تواصل استخدام محرك السيولة السابق دون اختلاق GEX. التكامل لا ينفذ تداولًا ولا يدّعي معرفة مراكز كل صانع سوق على حدة.


## مركز مراقبة المنصة
- صفحة `/sections/system` تعرض حالة قاعدة البيانات، وعدد الصفقات المفتوحة والمغلقة، وحجم الذاكرة المؤقتة، وتكوين مزودي الأسواق.
- لا تنفذ الصفحة اختبارات ضغط ولا تضيف اتصالات بمصادر السوق؛ تقرأ الحالة المحلية وتكوين المزود فقط.
- حالة "مهيأ" لا تعني أن المزود الخارجي متاح لحظيًا. التحقق الفعلي يتم عند طلب بيانات السوق.
- endpoint `/api/system/status` لا يعرض مفاتيح API أو بيانات حسابات المستخدمين.


## Fast-mover ranking
- ترتيب نسبي داخل كل سوق: 50% absolute 24h change, 30% 24h high-low range, 20% quote turnover/liquidity. A feature with no variation is omitted and remaining weights are normalized.
- The scanner rotates through small batches (8 assets, including up to 4 priority movers) per market and scan cycle. A candidate must pass 4h + daily agreement, the 24h market-breadth gate, and a completed 15m liquidity trigger. Final opportunities rank by direction-aligned 15m change and then setup quality; up to three are displayed.
- No ranking score is a win probability. Markets without valid price/candle providers remain unavailable rather than being populated with guessed tickers.

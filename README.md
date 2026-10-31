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
- أفضل ثلاث فرص فنية من فحص ثابت على 15 دقيقة، دون أزرار لتغيير الأطر، مع حد أقصى لأربع عمليات تحليل متوازية لتخفيف الضغط على الخادم.
- عرض الدخول والأهداف الثلاثة والوقف ومؤشرات المخاطرة وجودة الشروط.
- سجل الصفقات المفتوحة والصفقات المغلقة.
- تحديث تلقائي كل 30 ثانية، مع منع تداخل الطلبات ومهلة اتصال.
- تصميم RTL داكن متجاوب للجوال وسطح المكتب.

## API
- `/health` و`/api/health`
- `/api/markets`
- `/api/market/spot`
- `/api/market/futures`
- `/api/market/coinm`
- `/api/market/alpha`
- `/api/trades?market=spot`

## GAMMA PRO
محرك التوصيات الأساسي يحلل شموع 15 دقيقة المكتملة لاكتشاف سحب السيولة واسترداد المستوى، أو الامتصاص قرب مناطق الدعم والمقاومة، مع تأكيد حركة الشمعة والحجم النسبي. لا يستخدم EMA أو RSI أو MACD أو مؤشرات الاتجاه التقليدية. يحدد الدخول من آخر سعر متاح، والوقف خلف ذيل حدث السيولة بهامش مبني على المدى الحقيقي، والأهداف عند 1R و2R و3R. لا يصدر توصية ما لم تكتمل شروط الحدث والتأكيد وحد المخاطرة. درجة الجودة تقييم لقوة الشروط وليست احتمال ربح أو نسبة نجاح.

**حدود بيانات Gamma:** لا يوجد حالياً مزود موثوق موحد لبيانات خيارات/GEX يغطي كل الأسواق والأصول. لذلك لا يعرض النظام قيمة Gamma ولا ينسب مراكز لصانع السوق عند غياب بيانات الخيارات. ضغط الشمعة والحجم النسبي إشارات مشتقة من OHLCV وليست Delta فعلية أو دفتر أوامر أو مراكز صانع السوق. يتطلب GEX الحقيقي تكامل بيانات خيارات مرخصة لكل سوق يدعمها.

## تتبع الصفقات
تُحفظ الصفقات في SQLite وتُحدّث حالة TP1 وTP2 وTP3 وSL عند تحديث بيانات السوق. ثبّت وحدة تخزين دائمة في Northflank على `/data` حتى تبقى السجلات بعد إعادة النشر. لا يتم تنفيذ أوامر تداول آلية.

## النشر والاختبارات
المنفذ 8080. على موارد Northflank الصغيرة (0.2 vCPU / 512 MB) يعمل Gunicorn بعامل واحد وأربع خيوط، مع مهلة 60 ثانية، لتقليل استهلاك الذاكرة وتجنب إنهاء طلبات الفحص الطويلة مبكرًا. فحوص CI تشمل compileall وNode syntax check وpytest.


## Accounts and subscriptions

The app now requires an account with an active subscription to access market analysis and trade history. New registrations are pending until an administrator grants access. Administrators can grant 30, 90, or 365 days from the in-app subscriber panel, or revoke access; expiry is enforced by the server.

Configure these secrets in the hosting service before enabling access:

- `SECRET_KEY`: a long random secret (at least 32 random bytes).
- `ADMIN_EMAIL`: the administrator login email.
- `ADMIN_PASSWORD`: the initial administrator password (at least 12 characters).

The first administrator account is created automatically in the persistent SQLite database on first request. Keep `/data` on persistent storage so accounts and subscriptions survive restarts. Do not commit secret values to GitHub. Registration currently uses email/password without email verification or payment processing; subscriptions are granted manually by the administrator.


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
- The scanner analyses up to the first 40 ranked assets, keeps the existing 15m liquidity event and 1h/4h/1d HAWK confirmations, and displays up to three qualifying trades.
- No ranking score is a win probability. Markets without valid price/candle providers remain unavailable rather than being populated with guessed tickers.

# التداول الذكي PRO

منصة عربية RTL لمراقبة الأسواق وتحليل الفرص الفنية، بواجهة داكنة متجاوبة ومصادر بيانات عامة.

## التشغيل
`pip install -r requirements.txt`
`python app.py`

## الأسواق ومصادر البيانات
- Binance Spot: واجهات Binance العامة الرسمية مع تدوير تلقائي بين api.binance.com وapi-gcp وapi1 إلى api4 وdata-api.binance.vision؛ لا تحتاج مفاتيح API.
- Binance Futures: واجهة Binance USD-M العامة؛ لا يوجد نطاق احتياطي رسمي موثق حالياً.
- Binance Alpha: واجهات Binance العامة لقائمة الرموز ومعلومات أزواج USDT والشموع؛ لا تحتاج مفاتيح API، ولا يوجد بديل مطابق موثوق.
- الفوركس والذهب: رُبط BiQuote العام دون مفتاح API لاكتشاف رموز Forex/Commodity وجلب الأسعار والشموع المغلقة 15m؛ تُرفض الأسعار المغلقة أو الأقدم من 5 دقائق.
- الأسهم السعودية والأسهم الأمريكية: أُضيف موصل Yahoo Finance اختياري عبر yfinance للاختبار الداخلي فقط. لا يعمل افتراضياً؛ يتطلب YAHOO_FINANCE_ENABLED=1 وقوائم YAHOO_SAUDI_SYMBOLS وYAHOO_US_SYMBOLS (رموز مفصولة بفواصل). يفحص فقط الرموز المضبوطة، ويرفض الأسعار الأقدم من 45 دقيقة والشموع غير المكتملة. لا يعتبر هذا تغطية كاملة للسوق ولا يجوز إعادة توزيع بيانات Yahoo على موقع عام دون ترخيص. لا تفعّل هذا المصدر على موقع عام قبل التأكد من شروط الاستخدام وتأمين الموقع الخاص.
- العقود الأمريكية: ما زالت غير مفعّلة؛ موصل Yahoo هذا لا يوفر فحصاً موثوقاً لكل عقود الخيارات.
- `/api/providers` يعرض حالة كل مزود ومسارات الاحتياط المفعّلة فعلياً، ويميزها عن المصادر التي لم تُدمج أو لم تُتحقق.
- Yahoo اختياري ويتطلب إعداد متغيرات البيئة في الاستضافة؛ لا يتم تفعيله تلقائياً.

## لوحة المنصة
- اتجاه السوق محسوب من عدد الأصول الصاعدة والهابطة والمحايدة خلال 24 ساعة.
- عرض أكثر ثلاثة أصول صعودًا وثلاثة هبوطًا من قائمة الأصول المؤهلة للسيولة.
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

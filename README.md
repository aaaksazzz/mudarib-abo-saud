# تحليل العملات الرقمية

موقع Flask جاهز لـ Render: Binance Spot public market data، تسجيل دخول بالإيميل ورمز تحقق، Premium، دفع USDT TRC20/Binance Pay كطلب مراجعة، ولوحة أدمن لإضافة أقسام وتفعيل الاشتراك.

## Render
Build: `pip install -r requirements.txt`
Start: `gunicorn server:app`

Environment Variables:
- SECRET_KEY
- ADMIN_KEY
- SMTP_HOST
- SMTP_PORT=587
- SMTP_USER
- SMTP_PASSWORD

لو ما ضبطت SMTP سيظهر رمز اختبار في الاستجابة؛ لا تستخدم هذا الوضع للإنتاج.

## Admin
`/admin?key=ADMIN_KEY`

## ملاحظات
بيانات Binance العامة لا تحتاج ربط حساب العميل. الموقع لا ينفذ صفقات.

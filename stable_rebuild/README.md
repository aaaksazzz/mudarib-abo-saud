# المضارب ذكي — Stable Rebuild

هذه النسخة هي البديل الجديد للتطبيق القديم.

## البنية
- FastAPI + Gunicorn/Uvicorn للويب.
- PostgreSQL للبيانات الدائمة.
- Redis للكاش والـheartbeat.
- Worker مستقل للماسح ومتابعة الصفقات.
- HTML/CSS/JS الحالية محفوظة وتعمل فوق API الجديد.
- لا يوجد Flask أو SQLite أو server.py في النسخة الجديدة.

## ما تم نقله
- المصادقة والتسجيل والجلسات.
- الاشتراكات وطلبات الدفع.
- لوحة الإدارة والمستخدمون والمدفوعات.
- الأخبار والمدونة.
- إشارات Spot وFutures والعقود والسوق السعودي والأمريكي والفوركس.
- استراتيجية التحليل القديمة مع عكس اتجاه الإشارة كما كانت.
- الذاكرة التاريخية وتحليل الأنماط والمؤشرات.
- سجل الصفقات وTP/SL ومتابعة الصفقات بدون الاعتماد على فتح صفحة الصفقات.
- تقويم العقود.
- Telegram hooks.
- robots/sitemap.
- حماية الكاش ومنع تشغيل الماسح من طلبات الويب.

## التشغيل
Web:
gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --timeout 120 stable_rebuild.app.main:app

Worker:
python -m stable_rebuild.worker

المتغيرات الأساسية:
DATABASE_URL
REDIS_URL
SECRET_KEY
ADMIN_USERNAME
ADMIN_PASSWORD

لا تضع الأسرار داخل GitHub.

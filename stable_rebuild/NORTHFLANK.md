# تشغيل النسخة المستقرة على Northflank

## Web
gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --workers 1 --timeout 120 stable_rebuild.app.main:app

## Worker مستقل
python -m stable_rebuild.worker

## متغيرات البيئة المطلوبة
DATABASE_URL
REDIS_URL
SECRET_KEY
ADMIN_USERNAME
ADMIN_PASSWORD

## اختيارية
PUBLIC_BASE_URL
TRC20_ADDRESS
BINANCE_PAY_ID
BINANCE_BASE_URL
SCAN_INTERVAL_SECONDS=180
TRADE_REVIEW_SECONDS=15
MAX_SIGNALS=70

Web وWorker يستخدمان نفس PostgreSQL وRedis، ولا يتم تشغيل Worker داخل Web.

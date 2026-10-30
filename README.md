# التداول الذكي PRO

نسخة جديدة خفيفة من المنصة، مبنية بواجهة عربية RTL وخادم Flask.

## التشغيل
`pip install -r requirements.txt`
`python app.py`

## نقاط API
- `/health` فحص صحة الخدمة
- `/api/markets` حالة مصادر الأسواق
- `/api/market/spot?timeframe=15m`
- `/api/market/futures?timeframe=1h`

بيانات Spot وFutures من واجهات Binance العامة دون مفاتيح API. بقية الأسواق تظهر بوضوح أنها تحتاج مزود بيانات قبل تفعيلها؛ لا يتم عرض أسعار أو إشارات وهمية.

## الاختبار
`pytest -q`

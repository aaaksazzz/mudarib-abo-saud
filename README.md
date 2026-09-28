# التداول الذكي PRO

منصة تحليل أسواق متعددة مبنية من الصفر على فكرة الموقع الأصلية.


## Northflank multi-service scanning

The scanner can be split across independent services using environment variables. Use the same repository/image for each service and assign a non-overlapping `WORKER_MARKETS` value:

- Binance Spot: `WORKER_MARKETS=spot`
- Binance Futures USDT-M: `WORKER_MARKETS=futures`
- US stocks + Saudi: `WORKER_MARKETS=us,saudi`
- Forex + US contracts: `WORKER_MARKETS=forex,contracts`

Set a unique `WORKER_NAME` on each service. The scanner keeps the full market universe; the split only changes which worker performs the scan. Keep the main web service on `WORKER_MARKETS=spot` until the dedicated workers are running, then move it to a dedicated web-only configuration. Do not run duplicate market assignments because that doubles provider/API load.

## توزيع الفحص على خدمات Northflank
نفس صورة التطبيق يمكن تشغيلها كخدمات فحص صغيرة. كل خدمة تأخذ جزءاً مختلفاً من رموز السوق عبر `WORKER_PARTITION_INDEX` و`WORKER_PARTITION_COUNT`، ويجب أن تستخدم نفس قاعدة البيانات المشتركة.

إعداد مقترح:
- Spot: 8 خدمات — `WORKER_MARKETS=spot`, `WORKER_PARTITION_COUNT=8`, والفهرس من 0 إلى 7.
- Futures: 6 خدمات — `WORKER_MARKETS=futures`, `WORKER_PARTITION_COUNT=6`, والفهرس من 0 إلى 5.
- US: 3 خدمات — `WORKER_MARKETS=us`, `WORKER_PARTITION_COUNT=3`, والفهرس من 0 إلى 2.
- Saudi: 2 خدمات — `WORKER_MARKETS=saudi`, `WORKER_PARTITION_COUNT=2`, والفهرس من 0 إلى 1.
- Forex: 2 خدمات — `WORKER_MARKETS=forex`, `WORKER_PARTITION_COUNT=2`, والفهرس من 0 إلى 1.
- Contracts: 2 خدمات — `WORKER_MARKETS=contracts`, `WORKER_PARTITION_COUNT=2`, والفهرس من 0 إلى 1.

لكل خدمة اجعل `RUN_SCANNER_WORKER=1` واسم `WORKER_NAME` مختلفاً. خدمة الموقع الرئيسية تجعل `RUN_SCANNER_WORKER=0` حتى لا تشغل الفحص بالخلفية، وخدمة الأخبار الوحيدة تجعل `RUN_NEWS_WORKER=1`.

# التداول الذكي PRO

منصة تحليل أسواق متعددة مبنية من الصفر على فكرة الموقع الأصلية.


## Northflank multi-service scanning

The scanner can be split across independent services using environment variables. Use the same repository/image for each service and assign a non-overlapping `WORKER_MARKETS` value:

- Binance Spot: `WORKER_MARKETS=spot`
- Binance Futures USDT-M: `WORKER_MARKETS=futures`
- US stocks + Saudi: `WORKER_MARKETS=us,saudi`
- Forex + US contracts: `WORKER_MARKETS=forex,contracts`

Set a unique `WORKER_NAME` on each service. The scanner keeps the full market universe; the split only changes which worker performs the scan. Keep the main web service on `WORKER_MARKETS=spot` until the dedicated workers are running, then move it to a dedicated web-only configuration. Do not run duplicate market assignments because that doubles provider/API load.

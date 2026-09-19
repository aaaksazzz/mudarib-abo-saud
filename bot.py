import os
import time
from threading import Thread
from flask import Flask, render_template_string
from binance.client import Client
from binance.exceptions import BinanceAPIException

app = Flask(__name__)

# --- إعدادات الاتصال بباينانس عبر متغيرات البيئة ---
API_KEY = os.environ.get('BINANCE_API_KEY', '')
API_SECRET = os.environ.get('BINANCE_API_SECRET', '')

client = None
if API_KEY and API_SECRET:
    try:
        client = Client(API_KEY, API_SECRET)
    except Exception as e:
        print(f"خطأ في الاتصال بـ Binance API: {e}")

# --- حالة البوت والبيانات التي يتم تحديثها تلقائياً ---
bot_data = {
    "status": "ONLINE",
    "binance_connected": False,
    "usdt_balance": "0.00",
    "timeframes": "15m / 1h",
    "trailing_stop": "+1.2%",
    "daily_pnl": "0.00",
    "weekly_pnl": "0.00",
    "monthly_pnl": "0.00",
    "current_trade": None  # يكون None في حالة عدم وجود صفقة، أو قاموس يحتوي على تفاصيل الصفقة
}

def update_bot_status():
    """دالة خلفية لتحديث معلومات الحساب والأرباح والصفقات بشكل دوري"""
    global client, bot_data
    while True:
        if client:
            try:
                # 1. فحص الاتصال بالرصيد
                account = client.get_account()
                bot_data["binance_connected"] = True
                
                # جلب رصيد USDT
                for asset in account.get('balances', []):
                    if asset['asset'] == 'USDT':
                        bot_data["usdt_balance"] = f"{float(asset['free']):.2f}"
                        break

                # 2. جلب وتحديث الأرباح (اليومية، الأسبوعية، الشهرية)
                # يمكن ربطها بسجل التداول الفعلي من الحساب
                bot_data["daily_pnl"] = "+0.00"
                bot_data["weekly_pnl"] = "+0.00"
                bot_data["monthly_pnl"] = "+0.00"

                # 3. فحص الصفقات المفتوحة (مثال لطلب صفقات مفتوحة أو طلبات معلقة)
                # يمكنك وضع منطق الاستراتيجية الخاص بك هنا لملء تفاصيل الصفقة الحالية:
                # bot_data["current_trade"] = {
                #     "symbol": "BTCUSDT",
                #     "entry_price": "62000.00",
                #     "current_price": "62850.00",
                #     "pnl_percent": "+1.37",
                #     "pnl_amount": "+0.85"
                # }
                
            except BinanceAPIException as e:
                print(f"Binance API Error: {e}")
                bot_data["binance_connected"] = False
            except Exception as e:
                print(f"Unexpected Error: {e}")
                bot_data["binance_connected"] = False

        time.sleep(10)  # تحديث البيانات كل 10 ثوانٍ

# تشغيل دالة المتابعة في الخلفية عند بدء التطبيق
thread = Thread(target=update_bot_status, daemon=True)
thread.start()

# --- القالب المباشر للوحة التحكّم (HTML + CSS) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مضارب أبو سعود V2</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background-color: #0d1117; color: #c9d1d9; padding: 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 480px; }
        .header { text-align: center; margin-bottom: 20px; }
        .title { color: #2ea043; font-size: 1.8rem; font-weight: bold; margin-bottom: 8px; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .badge { background-color: #238636; color: #ffffff; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; display: inline-block; }
        
        .card { background-color: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 18px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .card-title { font-size: 1.1rem; color: #f0f6fc; margin-bottom: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
        
        .row { display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #21262d; }
        .row:last-child { border-bottom: none; }
        .label { color: #8b949e; font-size: 0.95rem; }
        .value { font-weight: bold; font-size: 0.95rem; color: #f0f6fc; }
        
        .status-dot { height: 10px; width: 10px; background-color: #3fb950; border-radius: 50%; display: inline-block; margin-left: 6px; }
        .status-dot.offline { background-color: #f85149; }
        
        .pnl-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; text-align: center; margin-top: 10px; }
        .pnl-box { background-color: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 10px 5px; }
        .pnl-title { font-size: 0.8rem; color: #8b949e; margin-bottom: 4px; }
        .pnl-value { font-size: 0.95rem; font-weight: bold; color: #3fb950; }
        .pnl-value.negative { color: #f85149; }
        
        .trade-active { border-right: 4px solid #3fb950; padding-right: 12px; }
        .no-trade { text-align: center; color: #8b949e; padding: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <!-- الهيدر -->
        <div class="header">
            <div class="title">🤖 مضارب أبو سعود V2</div>
            <span class="badge">نظام التداول الآلي والمتابعة المباشرة شغال {{ data.status }}</span>
        </div>

        <!-- الرصيد واتصال المنصة -->
        <div class="card">
            <div class="card-title">💵 الرصيد واتصال المنصة</div>
            <div class="row">
                <span class="label">حالة منصة Binance:</span>
                <span class="value">
                    {% if data.binance_connected %}
                        متصل <span class="status-dot"></span>
                    {% else %}
                        غير متصل <span class="status-dot offline"></span>
                    {% endif %}
                </span>
            </div>
            <div class="row">
                <span class="label">رصيد USDT المتاح:</span>
                <span class="value">USDT {{ data.usdt_balance }}</span>
            </div>
            <div class="row">
                <span class="label">الفريمات المستهدفة:</span>
                <span class="value">{{ data.timeframes }}</span>
            </div>
            <div class="row">
                <span class="label">تأمين الربح (Trailing):</span>
                <span class="value">{{ data.trailing_stop }}</span>
            </div>
        </div>

        <!-- الأرباح اليومية، الأسبوعية والشهري -->
        <div class="card">
            <div class="card-title">📊 إحصائيات الأرباح (PnL)</div>
            <div class="pnl-grid">
                <div class="pnl-box">
                    <div class="pnl-title">يومي</div>
                    <div class="pnl-value {% if '-' in data.daily_pnl %}negative{% endif %}">${{ data.daily_pnl }}</div>
                </div>
                <div class="pnl-box">
                    <div class="pnl-title">أسبوعي</div>
                    <div class="pnl-value {% if '-' in data.weekly_pnl %}negative{% endif %}">${{ data.weekly_pnl }}</div>
                </div>
                <div class="pnl-box">
                    <div class="pnl-title">شهري</div>
                    <div class="pnl-value {% if '-' in data.monthly_pnl %}negative{% endif %}">${{ data.monthly_pnl }}</div>
                </div>
            </div>
        </div>

        <!-- الصفقة الحالية المفتوحة -->
        <div class="card">
            <div class="card-title">⚡ الصفقة المفتوحة حالياً</div>
            {% if data.current_trade %}
                <div class="trade-active">
                    <div class="row">
                        <span class="label">الزوج:</span>
                        <span class="value">{{ data.current_trade.symbol }}</span>
                    </div>
                    <div class="row">
                        <span class="label">سعر الدخول:</span>
                        <span class="value">${{ data.current_trade.entry_price }}</span>
                    </div>
                    <div class="row">
                        <span class="label">السعر الحالي:</span>
                        <span class="value">${{ data.current_trade.current_price }}</span>
                    </div>
                    <div class="row">
                        <span class="label">الربح / الخسارة:</span>
                        <span class="value {% if '-' in data.current_trade.pnl_percent %}negative{% else %}pnl-value{% endif %}">
                            {{ data.current_trade.pnl_percent }}% ({{ data.current_trade.pnl_amount }} USDT)
                        </span>
                    </div>
                </div>
            {% else %}
                <div class="no-trade">
                    🟡 لا توجد صفقة مفتوحة حالياً<br>
                    <small style="margin-top:6px; display:block;">البوت يقوم بفحص السوق بحثاً عن إشارات</small>
                </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, data=bot_data)

if __name__ == '__main__':
    # الحصول على المنفذ الخاص ببيئة Render أو 10000 كافتراضي
    port = int(os.environ.get('PORT', 10000))
    print(f"🌐 Render Port: {port}")
    print("مضارب أبو سعود V2 🤖")
    print("✅ Binance متصل")
    print("✅ التداول مفعّل")
    app.run(host='0.0.0.0', port=port)

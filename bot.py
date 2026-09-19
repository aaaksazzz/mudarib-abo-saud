from flask import Flask, jsonify, render_template_string
import os
import json
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# =========================
# الملفات
# =========================

BASE_DIR = os.path.expanduser("~/mybot")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
HISTORY_FILE = os.path.join(BASE_DIR, "trade_history.json")

# =========================
# الصفحة
# =========================

HTML = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<meta name="theme-color" content="#07111f">

<title>مضارب أبو سعود V2</title>

<style>

*{
    box-sizing:border-box;
}

body{
    margin:0;
    background:
    radial-gradient(circle at top,#13243a 0,#07101d 45%,#050912 100%);
    color:#fff;
    font-family:
    Arial,
    Tahoma,
    sans-serif;
}

.container{
    width:100%;
    max-width:1000px;
    margin:auto;
    padding:16px;
}

/* HEADER */

.header{
    background:rgba(13,24,40,.92);
    border:1px solid #243750;
    border-radius:24px;
    padding:22px;
    margin-bottom:14px;
    box-shadow:0 15px 45px rgba(0,0,0,.25);
}

.header-top{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:10px;
}

.logo{
    font-size:25px;
    font-weight:800;
}

.online{
    background:#0c2d23;
    color:#35e58c;
    border:1px solid #1b664b;
    padding:8px 13px;
    border-radius:30px;
    font-size:13px;
    font-weight:bold;
}

.offline{
    background:#32171b;
    color:#ff6875;
    border-color:#703039;
}

.subtitle{
    margin-top:10px;
    color:#8292a8;
    font-size:13px;
}

/* GRID */

.grid{
    display:grid;
    grid-template-columns:
    repeat(4,1fr);
    gap:12px;
    margin-bottom:14px;
}

.card{
    background:rgba(13,23,38,.92);
    border:1px solid #243750;
    border-radius:20px;
    padding:17px;
    box-shadow:0 10px 35px rgba(0,0,0,.18);
}

.label{
    color:#7f90a8;
    font-size:13px;
    margin-bottom:9px;
}

.big{
    font-size:23px;
    font-weight:800;
}

.green{
    color:#35e58c;
}

.red{
    color:#ff6875;
}

.gray{
    color:#9ba8b8;
}

/* TRADE */

.trade-card{
    margin-bottom:14px;
}

.trade-header{
    display:flex;
    justify-content:space-between;
    align-items:center;
    margin-bottom:18px;
}

.trade-title{
    font-size:19px;
    font-weight:bold;
}

.trade-status{
    color:#35e58c;
    font-size:13px;
}

.symbol{
    font-size:30px;
    font-weight:900;
    margin-bottom:17px;
}

.trade-grid{
    display:grid;
    grid-template-columns:
    repeat(3,1fr);
    gap:10px;
}

.trade-item{
    background:#0a1422;
    border:1px solid #1d3048;
    border-radius:15px;
    padding:14px;
}

.trade-value{
    font-size:17px;
    font-weight:bold;
}

/* PROTECTION */

.protection{
    display:grid;
    grid-template-columns:
    repeat(3,1fr);
    gap:10px;
    margin-top:12px;
}

.protection-item{
    padding:15px;
    border-radius:15px;
    background:#0a1422;
    border:1px solid #1d3048;
}

.stop{
    color:#ff6875;
}

.lock{
    color:#35e58c;
}

/* NO TRADE */

.no-trade{
    text-align:center;
    padding:35px 10px;
    color:#8190a5;
}

.no-trade-icon{
    font-size:40px;
    margin-bottom:10px;
}

/* PROFIT */

.profit-card{
    margin-bottom:14px;
}

.profit-grid{
    display:grid;
    grid-template-columns:
    repeat(3,1fr);
    gap:10px;
}

.profit-box{
    text-align:center;
    background:#0a1422;
    border:1px solid #1d3048;
    border-radius:16px;
    padding:20px 10px;
}

.profit-period{
    color:#8292a8;
    font-size:13px;
    margin-bottom:8px;
}

.profit-number{
    font-size:22px;
    font-weight:900;
}

/* HISTORY */

.history-card{
    margin-bottom:14px;
}

.table-wrap{
    overflow-x:auto;
}

table{
    width:100%;
    min-width:650px;
    border-collapse:collapse;
}

th{
    color:#7f90a8;
    font-size:13px;
    font-weight:normal;
    padding:13px 8px;
    border-bottom:1px solid #263850;
}

td{
    padding:14px 8px;
    border-bottom:1px solid #18283c;
    text-align:center;
    font-size:13px;
}

.empty{
    text-align:center;
    color:#7f90a8;
    padding:30px;
}

/* FOOTER */

.footer{
    text-align:center;
    color:#63748a;
    font-size:12px;
    padding:10px;
}

/* MOBILE */

@media(max-width:800px){

    .grid{
        grid-template-columns:
        repeat(2,1fr);
    }

    .trade-grid{
        grid-template-columns:
        repeat(2,1fr);
    }

}

@media(max-width:500px){

    .container{
        padding:10px;
    }

    .header{
        padding:18px;
    }

    .logo{
        font-size:21px;
    }

    .grid{
        grid-template-columns:
        repeat(2,1fr);
        gap:8px;
    }

    .card{
        padding:14px;
    }

    .big{
        font-size:18px;
    }

    .trade-grid{
        grid-template-columns:
        repeat(2,1fr);
    }

    .protection{
        grid-template-columns:1fr;
    }

    .profit-grid{
        grid-template-columns:
        repeat(3,1fr);
    }

    .profit-number{
        font-size:17px;
    }

}

</style>

</head>

<body>

<div class="container">

<!-- HEADER -->

<div class="header">

    <div class="header-top">

        <div class="logo">
            🤖 مضارب أبو سعود V2
        </div>

        <div id="online"
             class="online">
            🟢 ONLINE
        </div>

    </div>

    <div class="subtitle">
        نظام المتابعة المباشرة للصفقات
    </div>

</div>


<!-- BASIC INFO -->

<div class="grid">

    <div class="card">

        <div class="label">
            💰 رصيد USDT
        </div>

        <div id="balance"
             class="big">
            --
        </div>

    </div>


    <div class="card">

        <div class="label">
            🔗 Binance
        </div>

        <div id="binance"
             class="big green">
            متصل
        </div>

    </div>


    <div class="card">

        <div class="label">
            ⏱️ البيانات
        </div>

        <div class="big">
            15د / 1س
        </div>

    </div>


    <div class="card">

        <div class="label">
            🔄 آخر تحديث
        </div>

        <div id="updateTime"
             class="big">
            --
        </div>

    </div>

</div>


<!-- CURRENT TRADE -->

<div class="card trade-card">

    <div class="trade-header">

        <div class="trade-title">
            📈 الصفقة الحالية
        </div>

        <div id="tradeStatus"
             class="trade-status">
            --
        </div>

    </div>


    <div id="noTrade"
         class="no-trade">

        <div class="no-trade-icon">
            📭
        </div>

        لا توجد صفقة مفتوحة حالياً

    </div>


    <div id="trade"
         style="display:none;">

        <div id="symbol"
             class="symbol">
            --
        </div>


        <div class="trade-grid">

            <div class="trade-item">

                <div class="label">
                    سعر الدخول
                </div>

                <div id="entry"
                     class="trade-value">
                    --
                </div>

            </div>


            <div class="trade-item">

                <div class="label">
                    السعر الحالي
                </div>

                <div id="current"
                     class="trade-value">
                    --
                </div>

            </div>


            <div class="trade-item">

                <div class="label">
                    الكمية
                </div>

                <div id="quantity"
                     class="trade-value">
                    --
                </div>

            </div>


            <div class="trade-item">

                <div class="label">
                    الربح %
                </div>

                <div id="pnl"
                     class="trade-value">
                    --
                </div>

            </div>


            <div class="trade-item">

                <div class="label">
                    الربح USDT
                </div>

                <div id="pnlUsd"
                     class="trade-value">
                    --
                </div>

            </div>


            <div class="trade-item">

                <div class="label">
                    قيمة الصفقة
                </div>

                <div id="value"
                     class="trade-value">
                    --
                </div>

            </div>

        </div>


        <!-- PROTECTION -->

        <div class="protection">

            <div class="protection-item">

                <div class="label">
                    🛑 وقف الخسارة
                </div>

                <div id="stop"
                     class="trade-value stop">
                    -2.00%
                </div>

            </div>


            <div class="protection-item">

                <div class="label">
                    🔒 تأمين الربح
                </div>

                <div id="locked"
                     class="trade-value lock">
                    0.00%
                </div>

            </div>


            <div class="protection-item">

                <div class="label">
                    🛡️ حالة الحماية
                </div>

                <div id="stopStatus"
                     class="trade-value">
                    --
                </div>

            </div>

        </div>

    </div>

</div>


<!-- PROFITS -->

<div class="card profit-card">

    <div class="trade-title"
         style="margin-bottom:15px;">
        💵 الأرباح
    </div>


    <div class="profit-grid">

        <div class="profit-box">

            <div class="profit-period">
                اليوم
            </div>

            <div id="daily"
                 class="profit-number green">
                +0.00
            </div>

            <div class="label">
                USDT
            </div>

        </div>


        <div class="profit-box">

            <div class="profit-period">
                هذا الأسبوع
            </div>

            <div id="weekly"
                 class="profit-number green">
                +0.00
            </div>

            <div class="label">
                USDT
            </div>

        </div>


        <div class="profit-box">

            <div class="profit-period">
                هذا الشهر
            </div>

            <div id="monthly"
                 class="profit-number green">
                +0.00
            </div>

            <div class="label">
                USDT
            </div>

        </div>

    </div>

</div>


<!-- HISTORY -->

<div class="card history-card">

    <div class="trade-title"
         style="margin-bottom:15px;">
        📜 سجل الصفقات
    </div>


    <div class="table-wrap">

        <table>

            <thead>

                <tr>

                    <th>العملة</th>
                    <th>الدخول</th>
                    <th>الخروج</th>
                    <th>الربح %</th>
                    <th>الربح USDT</th>
                    <th>الوقت</th>

                </tr>

            </thead>

            <tbody id="history">

                <tr>
                    <td colspan="6"
                        class="empty">
                        لا توجد صفقات مغلقة
                    </td>
                </tr>

            </tbody>

        </table>

    </div>

</div>


<div class="footer">

    مضارب أبو سعود V2 🤖
    <br>
    تحديث تلقائي كل 5 ثواني

</div>


</div>


<script>

function num(value, digits=4){

    const n = Number(value);

    if(!Number.isFinite(n))
        return "0.00";

    return n.toFixed(digits);

}


function percent(value){

    const n = Number(value);

    if(!Number.isFinite(n))
        return "0.00%";

    return (n >= 0 ? "+" : "") +
           n.toFixed(2) +
           "%";

}


function money(value){

    const n = Number(value);

    if(!Number.isFinite(n))
        return "0.00";

    return (n >= 0 ? "+" : "") +
           n.toFixed(4) +
           " USDT";

}


function colorize(element,value){

    element.classList.remove(
        "green",
        "red",
        "gray"
    );

    const n = Number(value);

    if(n > 0)
        element.classList.add("green");

    else if(n < 0)
        element.classList.add("red");

    else
        element.classList.add("gray");
}


function escapeHtml(value){

    return String(value ?? "")
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll('"',"&quot;")
        .replaceAll("'","&#039;");

}


function formatTime(value){

    if(!value)
        return "--";

    try{

        const d = new Date(value);

        if(Number.isNaN(d.getTime()))
            return String(value);

        return d.toLocaleString(
            "ar-SA",
            {
                hour:"2-digit",
                minute:"2-digit",
                day:"2-digit",
                month:"2-digit"
            }
        );

    }catch{

        return String(value);

    }

}


async function loadDashboard(){

    try{

        const response =
            await fetch(
                "/api/dashboard?t=" +
                Date.now(),
                {
                    cache:"no-store"
                }
            );

        if(!response.ok)
            throw new Error("HTTP " + response.status);

        const data =
            await response.json();


        /* ONLINE */

        const online =
            document.getElementById("online");

        online.textContent =
            "🟢 ONLINE";

        online.classList.remove(
            "offline"
        );


        /* BALANCE */

        document.getElementById(
            "balance"
        ).textContent =
            num(data.balance,4) +
            " USDT";


        /* BINANCE */

        document.getElementById(
            "binance"
        ).textContent =
            data.binance_connected
            ? "متصل"
            : "غير متصل";


        if(!data.binance_connected){

            document.getElementById(
                "binance"
            ).classList.remove("green");

            document.getElementById(
                "binance"
            ).classList.add("red");

        }


        /* TIME */

        document.getElementById(
            "updateTime"
        ).textContent =
            new Date().toLocaleTimeString(
                "ar-SA"
            );


        /* TRADE */

        const trade =
            data.trade;


        if(trade){

            document.getElementById(
                "noTrade"
            ).style.display =
                "none";

            document.getElementById(
                "trade"
            ).style.display =
                "block";

            document.getElementById(
                "tradeStatus"
            ).textContent =
                "🟢 مفتوحة";


            document.getElementById(
                "symbol"
            ).textContent =
                "🟢 " +
                trade.symbol;


            document.getElementById(
                "entry"
            ).textContent =
                num(trade.entry,8);


            document.getElementById(
                "current"
            ).textContent =
                num(trade.current,8);


            document.getElementById(
                "quantity"
            ).textContent =
                num(trade.quantity,8);


            const pnl =
                document.getElementById(
                    "pnl"
                );

            pnl.textContent =
                percent(trade.pnl_pct);

            colorize(
                pnl,
                trade.pnl_pct
            );


            const pnlUsd =
                document.getElementById(
                    "pnlUsd"
                );

            pnlUsd.textContent =
                money(trade.pnl_usdt);

            colorize(
                pnlUsd,
                trade.pnl_usdt
            );


            document.getElementById(
                "value"
            ).textContent =
                num(
                    trade.current *
                    trade.quantity,
                    4
                ) +
                " USDT";


            document.getElementById(
                "stop"
            ).textContent =
                percent(
                    trade.stop_pct
                );


            document.getElementById(
                "locked"
            ).textContent =
                percent(
                    trade.locked_pct
                );


            document.getElementById(
                "stopStatus"
            ).textContent =
                trade.stop_order_id
                ? "🟢 مفعل"
                : "🟠 غير مفعل";

        }

        else{

            document.getElementById(
                "trade"
            ).style.display =
                "none";

            document.getElementById(
                "noTrade"
            ).style.display =
                "block";

            document.getElementById(
                "tradeStatus"
            ).textContent =
                "لا توجد صفقة";

        }


        /* PROFITS */

        document.getElementById(
            "daily"
        ).textContent =
            money(data.daily);


        document.getElementById(
            "weekly"
        ).textContent =
            money(data.weekly);


        document.getElementById(
            "monthly"
        ).textContent =
            money(data.monthly);


        /* HISTORY */

        const history =
            document.getElementById(
                "history"
            );


        if(
            Array.isArray(data.history) &&
            data.history.length
        ){

            history.innerHTML =
                data.history
                .slice()
                .reverse()
                .map(function(t){

                    const profit =
                        Number(
                            t.pnl_usdt ??
                            t.profit_usdt ??
                            t.profit ??
                            0
                        );

                    const profitPct =
                        Number(
                            t.pnl_pct ??
                            t.profit_pct ??
                            0
                        );

                    const cls =
                        profit >= 0
                        ? "green"
                        : "red";


                    return `
                    <tr>

                        <td>
                            ${escapeHtml(
                                t.symbol || "--"
                            )}
                        </td>

                        <td>
                            ${num(
                                t.entry ??
                                t.entry_price,
                                8
                            )}
                        </td>

                        <td>
                            ${num(
                                t.exit ??
                                t.exit_price ??
                                t.close_price,
                                8
                            )}
                        </td>

                        <td class="${cls}">
                            ${percent(
                                profitPct
                            )}
                        </td>

                        <td class="${cls}">
                            ${money(
                                profit
                            )}
                        </td>

                        <td>
                            ${formatTime(
                                t.closed_at ??
                                t.close_time ??
                                t.time
                            )}
                        </td>

                    </tr>
                    `;

                })
                .join("");

        }

        else{

            history.innerHTML =
                `
                <tr>
                    <td
                        colspan="6"
                        class="empty">
                        لا توجد صفقات مغلقة
                    </td>
                </tr>
                `;

        }

    }

    catch(error){

        console.error(error);

        const online =
            document.getElementById(
                "online"
            );

        online.textContent =
            "🟠 جاري الاتصال...";

        online.classList.add(
            "offline"
        );

    }

}


/* أول تحميل */

loadDashboard();


/* تحديث كل 5 ثواني */

setInterval(
    loadDashboard,
    5000
);

</script>

</body>
</html>
"""


# =========================
# قراءة JSON
# =========================

def read_json(path, default):

    try:

        if not os.path.exists(path):
            return default

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return default


# =========================
# رقم
# =========================

def get_number(data, keys, default=0):

    if not isinstance(data, dict):
        return default

    for key in keys:

        value = data.get(key)

        if value is None:
            continue

        try:
            return float(value)
        except:
            continue

    return default


# =========================
# التاريخ
# =========================

def parse_date(value):

    if value is None:
        return None

    try:

        if isinstance(value, (int,float)):

            return datetime.fromtimestamp(
                float(value),
                timezone.utc
            )

        text = str(value)

        text = text.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(text)

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except:

        return None


# =========================
# أرباح
# =========================

def calculate_profit(history):

    now = datetime.now(
        timezone.utc
    )

    day_start = now - timedelta(
        days=1
    )

    week_start = now - timedelta(
        days=7
    )

    month_start = datetime(
        now.year,
        now.month,
        1,
        tzinfo=timezone.utc
    )

    daily = 0.0
    weekly = 0.0
    monthly = 0.0

    for trade in history:

        if not isinstance(
            trade,
            dict
        ):
            continue

        profit = get_number(
            trade,
            [
                "pnl_usdt",
                "profit_usdt",
                "profit",
                "pnl"
            ],
            0
        )

        date_value = (
            trade.get("closed_at")
            or
            trade.get("close_time")
            or
            trade.get("time")
            or
            trade.get("timestamp")
        )

        dt = parse_date(
            date_value
        )

        if not dt:
            continue

        if dt >= day_start:
            daily += profit

        if dt >= week_start:
            weekly += profit

        if dt >= month_start:
            monthly += profit

    return (
        daily,
        weekly,
        monthly
    )


# =========================
# الصفحة الرئيسية
# =========================

@app.route("/")
def index():

    return render_template_string(
        HTML
    )


# =========================
# API المتابعة
# =========================

@app.route(
    "/api/dashboard"
)
def dashboard():

    state = read_json(
        STATE_FILE,
        {}
    )

    history = read_json(
        HISTORY_FILE,
        []
    )


    # لو ملف التاريخ عبارة عن dict

    if isinstance(
        history,
        dict
    ):

        history = (
            history.get("trades")
            or
            history.get("history")
            or
            []
        )


    if not isinstance(
        history,
        list
    ):

        history = []


    # الرصيد

    balance = get_number(
        state,
        [
            "balance",
            "usdt_balance",
            "available_usdt"
        ],
        0
    )


    # الصفقة

    trade = None


    symbol = (
        state.get("symbol")
        if isinstance(
            state,
            dict
        )
        else None
    )


    if symbol:

        entry = get_number(
            state,
            [
                "entry",
                "entry_price",
                "buy_price"
            ],
            0
        )


        quantity = get_number(
            state,
            [
                "qty",
                "quantity"
            ],
            0
        )


        current = get_number(
            state,
            [
                "current",
                "current_price",
                "last_price"
            ],
            entry
        )


        # حساب الربح

        if entry > 0:

            pnl_pct = (
                (
                    current -
                    entry
                )
                /
                entry
            ) * 100

        else:

            pnl_pct = 0


        pnl_usdt = (
            current -
            entry
        ) * quantity


        # مستوى التأمين

        locked = get_number(
            state,
            [
                "locked_level",
                "locked_pct",
                "lock_level"
            ],
            0
        )


        # رقم أمر الوقف

        stop_order_id = (
            state.get(
                "stop_order_id"
            )
            or
            state.get(
                "stopOrderId"
            )
        )


        trade = {

            "symbol":
                symbol,

            "entry":
                entry,

            "current":
                current,

            "quantity":
                quantity,

            "pnl_pct":
                pnl_pct,

            "pnl_usdt":
                pnl_usdt,

            "stop_pct":
                -2.0,

            "locked_pct":
                locked,

            "stop_order_id":
                stop_order_id

        }


    # الأرباح

    daily, weekly, monthly = (
        calculate_profit(
            history
        )
    )


    return jsonify({

        "online":
            True,

        "binance_connected":
            True,

        "balance":
            balance,

        "trade":
            trade,

        "daily":
            daily,

        "weekly":
            weekly,

        "monthly":
            monthly,

        "trade_count":
            len(history),

        "history":
            history[-50:]

    })


# =========================
# Health Check
# =========================

@app.route(
    "/health"
)
def health():

    return jsonify({
        "status":
            "ok",
        "service":
            "mudarib-abo-saud-v2"
    })


# =========================
# التشغيل
# =========================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )

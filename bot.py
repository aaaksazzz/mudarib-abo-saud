import os
import time
import hmac
import hashlib
import urllib.parse
import json
import threading
import requests

from decimal import Decimal, ROUND_DOWN
from flask import Flask, jsonify, render_template_string


# =========================================================
# CONFIG
# =========================================================

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

BASE_URL = "https://api.binance.com"
PORT = int(os.getenv("PORT", "10000"))

EMA_PERIOD = 200

MIN_CHANGE_15M = Decimal("1.0")

# يبدأ تأمين الربح عند +1%
TRAIL_START_PROFIT = Decimal("1.0")

# الهدف الأساسي للـTrailing = 0.50%
DESIRED_TRAILING_PERCENT = Decimal("0.50")

# استخدام الرصيد
BALANCE_USAGE = Decimal("0.999")

# كل دورة بحث
SCAN_INTERVAL = 20

# تقليل ضغط Binance
REQUEST_DELAY = 0.06

STATE_FILE = "bot_data.json"


# =========================================================
# APP
# =========================================================

app = Flask(__name__)
session = requests.Session()

session.headers.update({
    "X-MBX-APIKEY": API_KEY
})

state_lock = threading.Lock()

state = {
    "status": "starting",
    "active_trade": None,
    "symbols_count": 0,
    "candidates_count": 0,
    "best_candidate": None,
    "last_scan": None,
    "last_action": "بدء التشغيل",
    "last_error": None,
    "scan_number": 0
}


# =========================================================
# DASHBOARD
# =========================================================

HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>مضارب أبو سعود V5</title>

<style>

*{
    box-sizing:border-box;
}

body{
    margin:0;
    background:#0b0f14;
    color:#fff;
    font-family:Arial,sans-serif;
}

.container{
    width:100%;
    max-width:1100px;
    margin:auto;
    padding:18px;
}

.header{
    background:linear-gradient(135deg,#151c25,#10151c);
    border:1px solid #27313d;
    border-radius:20px;
    padding:22px;
    margin-bottom:16px;
}

.title{
    font-size:27px;
    font-weight:bold;
}

.sub{
    color:#8d99a8;
    margin-top:7px;
}

.grid{
    display:grid;
    grid-template-columns:repeat(2,1fr);
    gap:14px;
}

.card{
    background:#121820;
    border:1px solid #26313c;
    border-radius:18px;
    padding:18px;
}

.full{
    grid-column:1/-1;
}

.label{
    color:#8d99a8;
    font-size:13px;
}

.value{
    font-size:22px;
    font-weight:bold;
    margin-top:6px;
}

.row{
    display:flex;
    justify-content:space-between;
    gap:15px;
    padding:12px 0;
    border-bottom:1px solid #222b35;
}

.row:last-child{
    border-bottom:0;
}

.green{
    color:#27e58b;
}

.red{
    color:#ff5c6c;
}

.yellow{
    color:#ffd166;
}

.blue{
    color:#55b7ff;
}

.badge{
    display:inline-block;
    padding:7px 12px;
    border-radius:20px;
    background:#1c2833;
    font-size:13px;
}

@media(max-width:650px){

    .grid{
        grid-template-columns:1fr;
    }

    .full{
        grid-column:auto;
    }

}

</style>
</head>

<body>

<div class="container">

<div class="header">

<div class="title">
🤖 مضارب أبو سعود V5
</div>

<div class="sub">
Binance Spot • All USDT • EMA200 • Trailing Profit
</div>

<br>

<div id="status" class="badge">
جاري التشغيل...
</div>

</div>


<div class="grid">


<div class="card">

<div class="label">
العملات المفحوصة
</div>

<div id="symbols" class="value">
-
</div>

</div>


<div class="card">

<div class="label">
المرشحين فوق +1%
</div>

<div id="candidates" class="value">
-
</div>

</div>


<div class="card full">

<div class="label">
أفضل فرصة
</div>

<div id="best" class="value blue">
-
</div>

</div>


<div class="card full">

<h3>
📈 الصفقة الحالية
</h3>

<div class="row">
<span>العملة</span>
<b id="tradeSymbol">-</b>
</div>

<div class="row">
<span>الدخول</span>
<b id="entry">-</b>
</div>

<div class="row">
<span>السعر الحالي</span>
<b id="price">-</b>
</div>

<div class="row">
<span>الربح</span>
<b id="profit">-</b>
</div>

<div class="row">
<span>أعلى سعر</span>
<b id="high">-</b>
</div>

<div class="row">
<span>الحماية</span>
<b id="protection">-</b>
</div>

<div class="row">
<span>Trailing Delta</span>
<b id="delta">-</b>
</div>

<div class="row">
<span>الكمية</span>
<b id="qty">-</b>
</div>

</div>


<div class="card">

<div class="label">
آخر إجراء
</div>

<div id="action" class="value">
-
</div>

</div>


<div class="card">

<div class="label">
رقم الفحص
</div>

<div id="scan" class="value">
-
</div>

</div>


<div class="card full">

<div class="label">
آخر خطأ
</div>

<div id="error" class="value red">
لا يوجد
</div>

</div>

</div>

</div>


<script>

async function update(){

    try{

        const response =
            await fetch("/api/status");

        const d =
            await response.json();

        document.getElementById("status").innerText =
            d.status || "-";

        document.getElementById("symbols").innerText =
            d.symbols_count || 0;

        document.getElementById("candidates").innerText =
            d.candidates_count || 0;

        document.getElementById("action").innerText =
            d.last_action || "-";

        document.getElementById("scan").innerText =
            d.scan_number || 0;

        document.getElementById("error").innerText =
            d.last_error || "لا يوجد";


        if(d.best_candidate){

            document.getElementById("best").innerText =
                d.best_candidate.symbol +
                "  +" +
                Number(
                    d.best_candidate.change
                ).toFixed(2) +
                "%";

        }else{

            document.getElementById("best").innerText =
                "لا توجد فرصة";

        }


        const t = d.active_trade;

        if(t){

            document.getElementById("tradeSymbol").innerText =
                t.symbol || "-";

            document.getElementById("entry").innerText =
                t.entry_price || "-";

            document.getElementById("price").innerText =
                t.current_price || "-";

            const p =
                Number(t.profit_percent || 0);

            const pe =
                document.getElementById("profit");

            pe.innerText =
                (p >= 0 ? "+" : "") +
                p.toFixed(2) +
                "%";

            pe.className =
                p >= 0
                ? "value green"
                : "

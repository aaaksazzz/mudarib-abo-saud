// ============================================================
// تحليل العملات الرقمية - Frontend
// ============================================================

const state = {
    symbol: "BTCUSDT",
    interval: "15m",
    markets: [],
    prices: {},
    analysis: null,
    candles: [],
    loading: false
};

const $ = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", () => {
    init();
});

async function init() {
    bindEvents();
    await loadMarkets();
    await loadData();
    setInterval(loadData, 30000);
}

function bindEvents() {

    const search = $("coinSearch");

    if (search) {
        search.addEventListener("input", () => {
            renderCoins(search.value);
        });
    }

    document.querySelectorAll("[data-interval]").forEach(btn => {
        btn.addEventListener("click", () => {

            state.interval = btn.dataset.interval;

            document.querySelectorAll("[data-interval]")
                .forEach(x => x.classList.remove("active"));

            btn.classList.add("active");

            loadData();
        });
    });

    const refresh = $("refreshBtn");

    if (refresh) {
        refresh.addEventListener("click", loadData);
    }

    const menuBtn = $("menuBtn");
    const sidebar = $("sidebar");

    if (menuBtn && sidebar) {
        menuBtn.addEventListener("click", () => {
            sidebar.classList.toggle("open");
        });
    }
}


// ============================================================
// API
// ============================================================

async function api(url) {

    const response = await fetch(url, {
        cache: "no-store"
    });

    const data = await response.json();

    if (!response.ok || data.ok === false) {
        throw new Error(
            data.message || "حدث خطأ في الاتصال"
        );
    }

    return data;
}


// ============================================================
// تحميل العملات
// ============================================================

async function loadMarkets() {

    try {

        const data = await api(
            "/api/binance/markets"
        );

        state.markets = data.symbols || [];

        renderCoins("");

        const count = $("coinCount");

        if (count) {
            count.textContent =
                `${state.markets.length} عملة`;
        }

    } catch (error) {

        showError(
            "تعذر تحميل قائمة العملات: " +
            error.message
        );
    }
}


// ============================================================
// عرض العملات
// ============================================================

function renderCoins(search = "") {

    const container = $("coinList");

    if (!container) return;

    const query = search.trim().toUpperCase();

    let coins = state.markets;

    if (query) {

        coins = coins.filter(coin =>
            coin.symbol.includes(query)
        );
    }

    coins = coins.slice(0, 100);

    container.innerHTML = "";

    coins.forEach(coin => {

        const button = document.createElement("button");

        button.className =
            "coin-item " +
            (
                coin.symbol === state.symbol
                    ? "selected"
                    : ""
            );

        const symbol = coin.symbol
            .replace("USDT", "");

        const price =
            state.prices[coin.symbol];

        const priceText =
            price
                ? formatPrice(price.price)
                : "--";

        const change =
            price
                ? price.change24h
                : 0;

        button.innerHTML = `
            <div class="coin-name">
                <strong>${symbol}</strong>
                <span>${coin.symbol}</span>
            </div>

            <div class="coin-price">
                <strong>${priceText}</strong>
                <span class="${change >= 0 ? "positive" : "negative"}">
                    ${formatPercent(change)}
                </span>
            </div>
        `;

        button.addEventListener("click", () => {

            state.symbol = coin.symbol;

            document.querySelectorAll(".coin-item")
                .forEach(x => x.classList.remove("selected"));

            button.classList.add("selected");

            loadData();
        });

        container.appendChild(button);
    });
}


// ============================================================
// تحميل الأسعار + التحليل
// ============================================================

async function loadData() {

    if (state.loading) return;

    state.loading = true;

    setStatus("جاري تحديث البيانات...");

    try {

        const [prices, analysis] =
            await Promise.all([
                api("/api/binance/prices"),
                api(
                    `/api/binance/analysis?symbol=${encodeURIComponent(state.symbol)}&interval=${state.interval}`
                )
            ]);

        state.prices = {};

        (prices.prices || []).forEach(item => {
            state.prices[item.symbol] = item;
        });

        state.analysis = analysis.analysis;
        state.candles = analysis.candles || [];

        renderCoins(
            $("coinSearch")
                ? $("coinSearch").value
                : ""
        );

        renderMarketHeader();
        renderAnalysis();
        renderChart();

        setStatus(
            "آخر تحديث: " +
            new Date().toLocaleTimeString("ar-SA")
        );

    } catch (error) {

        console.error(error);

        showError(
            "تعذر تحديث البيانات: " +
            error.message
        );

        setStatus("تعذر التحديث");

    } finally {

        state.loading = false;
    }
}


// ============================================================
// رأس العملة
// ============================================================

function renderMarketHeader() {

    const item =
        state.prices[state.symbol];

    const analysis =
        state.analysis;

    const symbolName =
        state.symbol.replace("USDT", "");

    setText(
        "symbolName",
        symbolName + " / USDT"
    );

    setText(
        "currentPrice",
        analysis
            ? formatPrice(analysis.price)
            : "--"
    );

    if (item) {

        const change =
            item.change24h;

        const changeEl =
            $("priceChange");

        if (changeEl) {

            changeEl.textContent =
                formatPercent(change);

            changeEl.className =
                change >= 0
                    ? "positive"
                    : "negative";
        }

        setText(
            "high24h",
            formatPrice(item.high24h)
        );

        setText(
            "low24h",
            formatPrice(item.low24h)
        );

        setText(
            "volume24h",
            formatVolume(item.volume)
        );
    }
}


// ============================================================
// التحليل
// ============================================================

function renderAnalysis() {

    const a = state.analysis;

    if (!a) return;

    const signal =
        $("signal");

    if (signal) {

        signal.textContent =
            a.signal;

        signal.className =
            "signal " +
            signalClass(a.signal);
    }

    setText(
        "score",
        `${a.score ?? 0}/10`
    );

    setText(
        "entry",
        formatPrice(a.entry)
    );

    setText(
        "tp1",
        formatPrice(a.tp1)
    );

    setText(
        "tp2",
        formatPrice(a.tp2)
    );

    setText(
        "tp3",
        formatPrice(a.tp3)
    );

    setText(
        "sl",
        formatPrice(a.sl)
    );

    setText(
        "rr",
        a.rr
            ? "1 : " + Number(a.rr).toFixed(2)
            : "--"
    );

    setText(
        "rsi",
        a.rsi !== null
            ? Number(a.rsi).toFixed(2)
            : "--"
    );

    setText(
        "ema20",
        formatPrice(a.ema20)
    );

    setText(
        "ema50",
        formatPrice(a.ema50)
    );

    setText(
        "ema200",
        formatPrice(a.ema200)
    );

    setText(
        "macd",
        a.macd !== null
            ? Number(a.macd).toFixed(6)
            : "--"
    );

    setText(
        "atr",
        formatPrice(a.atr)
    );

    setText(
        "support",
        formatPrice(a.support)
    );

    setText(
        "resistance",
        formatPrice(a.resistance)
    );

    setText(
        "volumeRatio",
        a.volumeRatio
            ? Number(a.volumeRatio).toFixed(2) + "x"
            : "--"
    );

    renderReasons(
        a.reasons || []
    );
}


// ============================================================
// أسباب التحليل
// ============================================================

function renderReasons(reasons) {

    const container =
        $("reasons");

    if (!container) return;

    container.innerHTML = "";

    if (!reasons.length) {

        container.innerHTML =
            "<div class='empty'>لا توجد أسباب كافية</div>";

        return;
    }

    reasons.forEach(reason => {

        const item =
            document.createElement("div");

        item.className =
            "reason";

        item.innerHTML = `
            <span class="reason-check">✓</span>
            <span>${reason}</span>
        `;

        container.appendChild(item);
    });
}


// ============================================================
// الشارت
// ============================================================

function renderChart() {

    const canvas =
        $("priceChart");

    if (!canvas || !state.candles.length) {
        return;
    }

    const ctx =
        canvas.getContext("2d");

    const rect =
        canvas.getBoundingClientRect();

    const dpr =
        window.devicePixelRatio || 1;

    canvas.width =
        rect.width * dpr;

    canvas.height =
        rect.height * dpr;

    ctx.scale(dpr, dpr);

    const width =
        rect.width;

    const height =
        rect.height;

    ctx.clearRect(
        0,
        0,
        width,
        height
    );

    const candles =
        state.candles.slice(-80);

    const highs =
        candles.map(x => x.high);

    const lows =
        candles.map(x => x.low);

    const max =
        Math.max(...highs);

    const min =
        Math.min(...lows);

    const range =
        max - min || 1;

    const padding =
        20;

    const chartWidth =
        width - padding * 2;

    const chartHeight =
        height - padding * 2;

    // خطوط الشبكة

    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i++) {

        const y =
            padding +
            chartHeight *
            (i / 4);

        ctx.beginPath();

        ctx.moveTo(
            padding,
            y
        );

        ctx.lineTo(
            width - padding,
            y
        );

        ctx.strokeStyle =
            "rgba(148,163,184,.15)";

        ctx.stroke();
    }

    // الشموع

    const candleWidth =
        Math.max(
            3,
            chartWidth / candles.length * 0.65
        );

    candles.forEach((candle, index) => {

        const x =
            padding +
            index *
            (chartWidth / candles.length) +
            (chartWidth / candles.length) / 2;

        const yHigh =
            padding +
            (max - candle.high) /
            range *
            chartHeight;

        const yLow =
            padding +
            (max - candle.low) /
            range *
            chartHeight;

        const yOpen =
            padding +
            (max - candle.open) /
            range *
            chartHeight;

        const yClose =
            padding +
            (max - candle.close) /
            range *
            chartHeight;

        const bullish =
            candle.close >= candle.open;

        ctx.strokeStyle =
            bullish
                ? "#22c55e"
                : "#ef4444";

        ctx.fillStyle =
            bullish
                ? "#22c55e"
                : "#ef4444";

        // الذيل

        ctx.beginPath();

        ctx.moveTo(
            x,
            yHigh
        );

        ctx.lineTo(
            x,
            yLow
        );

        ctx.stroke();

        // الجسم

        const bodyTop =
            Math.min(
                yOpen,
                yClose
            );

        const bodyHeight =
            Math.max(
                1,
                Math.abs(
                    yClose - yOpen
                )
            );

        ctx.fillRect(
            x - candleWidth / 2,
            bodyTop,
            candleWidth,
            bodyHeight
        );
    });

    // السعر الحالي

    const price =
        candles[candles.length - 1].close;

    const currentY =
        padding +
        (max - price) /
        range *
        chartHeight;

    ctx.strokeStyle =
        "#f59e0b";

    ctx.setLineDash([
        6,
        5
    ]);

    ctx.beginPath();

    ctx.moveTo(
        padding,
        currentY
    );

    ctx.lineTo(
        width - padding,
        currentY
    );

    ctx.stroke();

    ctx.setLineDash([]);

    ctx.fillStyle =
        "#f59e0b";

    ctx.font =
        "12px Arial";

    ctx.fillText(
        formatPrice(price),
        width - 90,
        currentY - 6
    );
}


// ============================================================
// Resize
// ============================================================

window.addEventListener(
    "resize",
    () => renderChart()
);


// ============================================================
// Helpers
// ============================================================

function setText(id, value) {

    const element =
        $(id);

    if (element) {
        element.textContent =
            value ?? "--";
    }
}


function formatPrice(value) {

    if (
        value === null ||
        value === undefined ||
        isNaN(value)
    ) {
        return "--";
    }

    const number =
        Number(value);

    if (number >= 1000) {
        return number.toLocaleString(
            "en-US",
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }
        );
    }

    if (number >= 1) {
        return number.toLocaleString(
            "en-US",
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 4
            }
        );
    }

    if (number >= 0.01) {
        return number.toLocaleString(
            "en-US",
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 6
            }
        );
    }

    return number.toLocaleString(
        "en-US",
        {
            minimumFractionDigits: 4,
            maximumFractionDigits: 10
        }
    );
}


function formatPercent(value) {

    if (
        value === null ||
        value === undefined ||
        isNaN(value)
    ) {
        return "--";
    }

    const number =
        Number(value);

    return (
        number >= 0 ? "+" : ""
    ) +
    number.toFixed(2) +
    "%";
}


function formatVolume(value) {

    if (
        value === null ||
        value === undefined ||
        isNaN(value)
    ) {
        return "--";
    }

    const n =
        Number(value);

    if (n >= 1000000000) {
        return (
            n / 1000000000
        ).toFixed(2) + "B";
    }

    if (n >= 1000000) {
        return (
            n / 1000000
        ).toFixed(2) + "M";
    }

    if (n >= 1000) {
        return (
            n / 1000
        ).toFixed(2) + "K";
    }

    return n.toFixed(2);
}


function signalClass(signal) {

    if (signal === "شراء قوي") {
        return "strong-buy";
    }

    if (signal === "شراء") {
        return "buy";
    }

    if (signal === "بيع قوي") {
        return "strong-sell";
    }

    if (signal === "بيع") {
        return "sell";
    }

    return "neutral";
}


function setStatus(text) {

    const element =
        $("status");

    if (element) {
        element.textContent = text;
    }
}


function showError(message) {

    const element =
        $("errorBox");

    if (element) {

        element.textContent =
            message;

        element.classList.add(
            "show"
        );

        setTimeout(() => {
            element.classList.remove(
                "show"
            );
        }, 6000);
    }
}

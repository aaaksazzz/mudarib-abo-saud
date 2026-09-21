/* ============================================================
   موقع تحليل تداول العملات الرقمية
   app.js - النسخة المعدلة
   ============================================================ */

"use strict";

const state = {
    symbol: "BTCUSDT",
    interval: "15m",

    markets: [],
    prices: {},
    analysis: null,
    candles: [],

    loading: false,
    user: null,

    settings: {
        theme: "dark",
        interval: "15m",
        refresh_seconds: 30,
        notifications: false
    },

    favorites: JSON.parse(localStorage.getItem("favorites") || "[]"),
    refreshTimer: null
};


/* ============================================================
   تشغيل الموقع
   ============================================================ */

document.addEventListener("DOMContentLoaded", init);

async function init() {
    bindEvents();
    loadLocalTheme();

    await loadUser();
    await loadSettings();
    await loadMarkets();
    await loadPrices();

    await loadData();

    startAutoRefresh();
}


/* ============================================================
   الأحداث
   ============================================================ */

function bindEvents() {

    // البحث عن العملات
    const search = document.getElementById("coinSearch");

    if (search) {
        search.addEventListener("input", () => {
            renderCoins(search.value);
        });
    }


    // الفواصل الزمنية
    document.querySelectorAll("[data-interval]").forEach(button => {

        button.addEventListener("click", async () => {

            const interval = button.dataset.interval;

            if (!interval) return;

            state.interval = interval;
            state.settings.interval = interval;

            document.querySelectorAll("[data-interval]")
                .forEach(btn => btn.classList.remove("active"));

            button.classList.add("active");

            updateElement("chartTimeframe", interval);

            await loadData();
        });

    });


    // تحديث يدوي
    const refreshBtn = document.getElementById("refreshBtn");

    if (refreshBtn) {
        refreshBtn.addEventListener("click", async () => {

            if (state.loading) return;

            await loadPrices();
            await loadData();
        });
    }


    // تسجيل الدخول
    const loginBtn = document.getElementById("loginBtn");

    if (loginBtn) {
        loginBtn.addEventListener("click", () => {
            showLogin();
        });
    }


    // تسجيل الخروج
    const logoutBtn = document.getElementById("logoutBtn");

    if (logoutBtn) {
        logoutBtn.addEventListener("click", logout);
    }


    // نموذج تسجيل الدخول
    const loginForm = document.getElementById("loginForm");

    if (loginForm) {
        loginForm.addEventListener("submit", async event => {

            event.preventDefault();

            const username =
                document.getElementById("loginUsername")?.value.trim();

            const password =
                document.getElementById("loginPassword")?.value;

            if (!username || !password) {
                showLoginError("اكتب اسم المستخدم وكلمة المرور");
                return;
            }

            try {

                const data = await api("/api/auth/login", {
                    method: "POST",
                    body: JSON.stringify({
                        username,
                        password
                    })
                });

                if (data.user) {
                    state.user = data.user;
                } else {
                    state.user = {
                        username: data.username || username
                    };
                }

                updateUserUI();
                closeModal("authModal");

                showToast("تم تسجيل الدخول بنجاح ✅");

            } catch (error) {
                showLoginError(error.message);
            }
        });
    }


    // نموذج التسجيل
    const registerForm = document.getElementById("registerForm");

    if (registerForm) {
        registerForm.addEventListener("submit", async event => {

            event.preventDefault();

            const username =
                document.getElementById("registerUsername")?.value.trim();

            const email =
                document.getElementById("registerEmail")?.value.trim();

            const password =
                document.getElementById("registerPassword")?.value;

            if (!username || !email || !password) {
                showRegisterError("كمل جميع البيانات");
                return;
            }

            try {

                const data = await api("/api/auth/register", {
                    method: "POST",
                    body: JSON.stringify({
                        username,
                        email,
                        password
                    })
                });

                state.user = data.user || {
                    username
                };

                updateUserUI();

                closeModal("authModal");

                showToast("تم إنشاء الحساب بنجاح 🎉");

            } catch (error) {
                showRegisterError(error.message);
            }
        });
    }


    // الانتقال من الدخول إلى التسجيل
    const createAccountBtn =
        document.getElementById("createAccountBtn");

    if (createAccountBtn) {
        createAccountBtn.addEventListener("click", showRegister);
    }


    const switchToRegister =
        document.getElementById("switchToRegister");

    if (switchToRegister) {
        switchToRegister.addEventListener("click", showRegister);
    }


    // الرجوع للدخول
    const switchToLogin =
        document.getElementById("switchToLogin");

    if (switchToLogin) {
        switchToLogin.addEventListener("click", showLogin);
    }


    // الوضع الليلي / النهاري
    const themeToggle =
        document.getElementById("themeToggle");

    if (themeToggle) {
        themeToggle.addEventListener("click", toggleTheme);
    }


    // حفظ الإعدادات
    const saveSettingsBtn =
        document.getElementById("saveSettingsBtn");

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener("click", saveSettings);
    }


    // زر المميز
    const premiumOpenBtn =
        document.getElementById("premiumOpenBtn");

    if (premiumOpenBtn) {
        premiumOpenBtn.addEventListener("click", () => {
            openModal("premiumModal");
        });
    }


    // أزرار المميز
    document.querySelectorAll("[data-premium]").forEach(button => {

        button.addEventListener("click", () => {
            openModal("premiumModal");
        });

    });


    // المفضلة
    const favoriteBtn =
        document.getElementById("favoriteBtn");

    if (favoriteBtn) {
        favoriteBtn.addEventListener("click", toggleFavorite);
    }


    // الماسح
    const scannerBtn =
        document.getElementById("runScannerBtn");

    if (scannerBtn) {
        scannerBtn.addEventListener("click", runScanner);
    }


    // إغلاق المودالات
    document.querySelectorAll("[data-close-modal]").forEach(button => {

        button.addEventListener("click", () => {

            const modalId = button.dataset.closeModal;

            if (modalId) {
                closeModal(modalId);
            } else {
                const modal = button.closest(".modal");

                if (modal) {
                    closeModal(modal.id);
                }
            }

        });

    });


    // الضغط خارج المودال
    document.querySelectorAll(".modal").forEach(modal => {

        modal.addEventListener("click", event => {

            if (event.target === modal) {
                closeModal(modal.id);
            }

        });

    });


    // ESC
    document.addEventListener("keydown", event => {

        if (event.key === "Escape") {

            document
                .querySelectorAll(".modal.open")
                .forEach(modal => {
                    closeModal(modal.id);
                });

        }

    });


    // إعادة رسم الشارت
    window.addEventListener("resize", () => {
        drawChart();
    });
}


/* ============================================================
   API
   ============================================================ */

async function api(url, options = {}) {

    const config = {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        },
        cache: "no-store"
    };

    const response = await fetch(url, config);

    let data = {};

    try {
        data = await response.json();
    } catch (_) {
        data = {};
    }

    if (!response.ok) {

        throw new Error(
            data.error ||
            data.message ||
            `خطأ HTTP ${response.status}`
        );
    }

    return data;
}


/* ============================================================
   المستخدم
   ============================================================ */

async function loadUser() {

    try {

        const data = await api("/api/auth/me");

        state.user = data.user || null;

    } catch (_) {

        state.user = null;
    }

    updateUserUI();
}


function updateUserUI() {

    const userArea =
        document.getElementById("userArea");

    const usernameDisplay =
        document.getElementById("usernameDisplay");

    const planDisplay =
        document.getElementById("planDisplay");

    const loginBtn =
        document.getElementById("loginBtn");

    const logoutBtn =
        document.getElementById("logoutBtn");


    if (state.user) {

        if (userArea) {
            userArea.classList.add("logged-in");
        }

        if (usernameDisplay) {
            usernameDisplay.textContent =
                state.user.username ||
                state.user.name ||
                "المستخدم";
        }

        if (planDisplay) {

            const plan =
                state.user.plan ||
                state.user.subscription ||
                "مجاني";

            planDisplay.textContent = plan;
        }

        if (loginBtn) {
            loginBtn.style.display = "none";
        }

        if (logoutBtn) {
            logoutBtn.style.display = "";
        }

    } else {

        if (userArea) {
            userArea.classList.remove("logged-in");
        }

        if (usernameDisplay) {
            usernameDisplay.textContent = "زائر";
        }

        if (planDisplay) {
            planDisplay.textContent = "مجاني";
        }

        if (loginBtn) {
            loginBtn.style.display = "";
        }

        if (logoutBtn) {
            logoutBtn.style.display = "none";
        }
    }
}


async function logout() {

    try {
        await api("/api/auth/logout", {
            method: "POST"
        });
    } catch (_) {
        // حتى لو فشل الطلب نرجع الواجهة لوضع الزائر
    }

    state.user = null;

    updateUserUI();

    showToast("تم تسجيل الخروج");

    closeModal("authModal");
}


/* ============================================================
   الإعدادات
   ============================================================ */

async function loadSettings() {

    try {

        const data = await api("/api/settings");

        if (data.settings) {

            state.settings = {
                ...state.settings,
                ...data.settings
            };

            if (state.settings.interval) {
                state.interval =
                    state.settings.interval;
            }
        }

    } catch (_) {
        // الإعدادات الافتراضية
    }

    applySettingsToUI();
}


function applySettingsToUI() {

    const interval =
        state.settings.interval ||
        state.interval ||
        "15m";

    state.interval = interval;

    document
        .querySelectorAll("[data-interval]")
        .forEach(button => {

            button.classList.toggle(
                "active",
                button.dataset.interval === interval
            );

        });


    const theme =
        state.settings.theme || "dark";

    if (theme === "light") {

        document.body.classList.add("light-theme");

    } else {

        document.body.classList.remove("light-theme");
    }


    updateElement(
        "refreshSeconds",
        state.settings.refresh_seconds
    );
}


async function saveSettings() {

    const refreshInput =
        document.getElementById("refreshSeconds");

    const notifications =
        document.getElementById("notificationsToggle");


    let refreshSeconds =
        Number(
            refreshInput?.value ||
            state.settings.refresh_seconds ||
            30
        );

    if (!Number.isFinite(refreshSeconds)) {
        refreshSeconds = 30;
    }

    refreshSeconds =
        Math.max(10, Math.min(3600, refreshSeconds));


    state.settings.refresh_seconds =
        refreshSeconds;

    state.settings.notifications =
        notifications ?
            notifications.checked :
            state.settings.notifications;


    try {

        await api("/api/settings", {
            method: "POST",
            body: JSON.stringify(state.settings)
        });

        showToast("تم حفظ الإعدادات ✅");

    } catch (error) {

        showToast(
            "تم الحفظ محلياً: " + error.message
        );
    }


    // مهم جداً: إعادة تشغيل المؤقت بعد تغيير المدة
    startAutoRefresh();
}


/* ============================================================
   الثيم
   ============================================================ */

function loadLocalTheme() {

    const saved =
        localStorage.getItem("theme");

    if (saved === "light") {

        document.body.classList.add("light-theme");

    } else {

        document.body.classList.remove("light-theme");
    }
}


function toggleTheme() {

    const light =
        document.body.classList.toggle("light-theme");

    const theme =
        light ? "light" : "dark";

    state.settings.theme = theme;

    localStorage.setItem("theme", theme);

    showToast(
        light ?
            "تم تفعيل الوضع النهاري ☀️" :
            "تم تفعيل الوضع الليلي 🌙"
    );
}


/* ============================================================
   العملات
   ============================================================ */

async function loadMarkets() {

    try {

        const data =
            await api("/api/binance/markets");

        let markets =
            data.symbols ||
            data.markets ||
            [];


        if (!Array.isArray(markets)) {
            markets = [];
        }


        // نحتفظ بكل العملات التي يرجعها السيرفر
        state.markets = markets;


        // تحديث العدد الحقيقي
        updateElement(
            "coinCount",
            state.markets.length.toLocaleString("en-US")
        );


        renderCoins();

    } catch (error) {

        showError(
            "تعذر تحميل العملات: " +
            error.message
        );
    }
}


/* ============================================================
   عرض كل العملات
   ============================================================ */

function renderCoins(searchText = "") {

    const container =
        document.getElementById("coinList");

    if (!container) return;


    const query =
        String(searchText || "")
            .trim()
            .toUpperCase();


    let filtered =
        state.markets.filter(item => {

            const symbol =
                getMarketSymbol(item);

            if (!symbol) return false;

            if (!query) return true;

            return symbol.includes(query);
        });


    /*
       مهم:
       لا يوجد هنا slice(0, 100)
       لذلك يتم عرض كل العملات الموجودة.
    */


    container.innerHTML = "";


    if (!filtered.length) {

        container.innerHTML = `
            <div class="empty-state">
                لا توجد عملات مطابقة 🔎
            </div>
        `;

        return;
    }


    const fragment =
        document.createDocumentFragment();


    filtered.forEach(item => {

        const symbol =
            getMarketSymbol(item);

        if (!symbol) return;


        const price =
            getPrice(symbol);


        const change =
            getChange(symbol, item);


        const div =
            document.createElement("div");


        div.className =
            "coin-item" +
            (
                symbol === state.symbol ?
                    " selected active" :
                    ""
            );


        div.dataset.symbol =
            symbol;


        div.innerHTML = `
            <div class="coin-name">
                ${escapeHtml(formatSymbol(symbol))}
            </div>

            <div class="coin-price">
                ${formatPrice(price)}
            </div>

            <div class="coin-change ${
                change >= 0 ?
                    "positive" :
                    "negative"
            }">
                ${formatPercent(change)}
            </div>
        `;


        div.addEventListener("click", async () => {

            state.symbol = symbol;

            document
                .querySelectorAll(".coin-item")
                .forEach(item => {
                    item.classList.remove(
                        "selected",
                        "active"
                    );
                });


            div.classList.add(
                "selected",
                "active"
            );


            await loadData();

        });


        fragment.appendChild(div);
    });


    container.appendChild(fragment);


    updateElement(
        "coinCount",
        state.markets.length.toLocaleString("en-US")
    );
}


function getMarketSymbol(item) {

    if (typeof item === "string") {
        return item.toUpperCase();
    }

    if (!item) return "";

    return String(
        item.symbol ||
        item.name ||
        item.ticker ||
        ""
    ).toUpperCase();
}


function formatSymbol(symbol) {

    if (symbol.endsWith("USDT")) {
        return symbol.replace("USDT", " / USDT");
    }

    return symbol;
}


/* ============================================================
   الأسعار
   ============================================================ */

async function loadPrices() {

    try {

        const data =
            await api("/api/binance/prices");

        const prices =
            data.prices ||
            data.data ||
            data ||
            [];


        if (Array.isArray(prices)) {

            state.prices = {};

            prices.forEach(item => {

                if (!item) return;

                const symbol =
                    String(
                        item.symbol ||
                        ""
                    ).toUpperCase();

                if (!symbol) return;

                state.prices[symbol] = item;
            });

        } else if (
            prices &&
            typeof prices === "object"
        ) {

            state.prices = prices;
        }


        renderCoins(
            document.getElementById(
                "coinSearch"
            )?.value || ""
        );

    } catch (error) {

        console.warn(
            "تعذر تحميل الأسعار:",
            error
        );
    }
}


function getPrice(symbol) {

    const item =
        state.prices?.[symbol];


    if (typeof item === "number") {
        return item;
    }


    if (typeof item === "string") {
        return Number(item);
    }


    if (item && typeof item === "object") {

        return Number(
            item.price ??
            item.lastPrice ??
            item.last ??
            0
        );
    }


    return 0;
}


function getChange(symbol, market = {}) {

    const item =
        state.prices?.[symbol];


    const candidates = [

        item?.priceChangePercent,

        item?.changePercent,

        item?.change,

        market?.priceChangePercent,

        market?.changePercent,

        market?.change
    ];


    for (const value of candidates) {

        const number =
            Number(value);

        if (Number.isFinite(number)) {
            return number;
        }
    }


    return 0;
}


/* ============================================================
   التحليل
   ============================================================ */

async function loadData() {

    if (state.loading) return;

    state.loading = true;

    try {

        showLoading(true);


        const url =
            `/api/binance/analysis` +
            `?symbol=${encodeURIComponent(state.symbol)}` +
            `&interval=${encodeURIComponent(state.interval)}`;


        const data =
            await api(url);


        state.analysis =
            data.analysis ||
            data.data ||
            data;


        state.candles =
            data.candles ||
            data.klines ||
            state.analysis?.candles ||
            [];


        renderAnalysis();

        drawChart();


        updateElement(
            "chartTimeframe",
            state.interval
        );


    } catch (error) {

        console.error(
            "Analysis error:",
            error
        );

        showError(
            "تعذر تحميل تحليل " +
            state.symbol +
            ": " +
            error.message
        );

    } finally {

        state.loading = false;

        showLoading(false);
    }
}


/* ============================================================
   عرض التحليل
   ============================================================ */

function renderAnalysis() {

    const a =
        state.analysis || {};


    const signal =
        normalizeSignal(
            a.signal ||
            a.recommendation ||
            a.action ||
            "حيادي"
        );


    const score =
        Number(
            a.score ??
            a.confidence ??
            a.signal_score ??
            0
        );


    // الإشارة
    updateElement(
        "signal",
        signal
    );


    const signalElement =
        document.getElementById("signal");


    if (signalElement) {

        signalElement.classList.remove(
            "buy",
            "sell",
            "strong-buy",
            "strong-sell",
            "neutral",
            "positive",
            "negative"
        );


        const cls =
            signalClass(signal);

        signalElement.classList.add(cls);
    }


    // الدرجة
    updateElement(
        "score",
        formatNumber(score, 0)
    );


    // شريط قوة الإشارة
    const safeScore =
        Math.max(
            0,
            Math.min(
                100,
                Number(score) || 0
            )
        );


    const progress =
        document.getElementById(
            "signalProgress"
        );


    const bar =
        document.getElementById(
            "signalBar"
        );


    if (progress) {
        progress.style.width =
            `${safeScore}%`;
    }


    if (bar) {
        bar.style.width =
            `${safeScore}%`;
    }


    // مستويات الصفقة
    updateElement(
        "entry",
        formatPriceValue(
            a.entry ??
            a.entry_price ??
            a.entryPrice
        )
    );


    updateElement(
        "tp1",
        formatPriceValue(
            a.tp1 ??
            a.take_profit_1 ??
            a.target1
        )
    );


    updateElement(
        "tp2",
        formatPriceValue(
            a.tp2 ??
            a.take_profit_2 ??
            a.target2
        )
    );


    updateElement(
        "tp3",
        formatPriceValue(
            a.tp3 ??
            a.take_profit_3 ??
            a.target3
        )
    );


    updateElement(
        "sl",
        formatPriceValue(
            a.sl ??
            a.stop_loss ??
            a.stopLoss
        )
    );


    updateElement(
        "rr",
        formatRR(
            a.rr ??
            a.risk_reward ??
            a.riskReward
        )
    );


    // السعر
    const currentPrice =
        a.current_price ??
        a.currentPrice ??
        a.price ??
        getPrice(state.symbol);


    updateElement(
        "currentPrice",
        formatPrice(currentPrice)
    );


    const priceChange =
        a.price_change_percent ??
        a.priceChangePercent ??
        a.change_percent ??
        a.changePercent;


    updateElement(
        "priceChange",
        formatPercent(priceChange)
    );


    // 24 ساعة
    updateElement(
        "high24h",
        formatPriceValue(
            a.high24h ??
            a.high_24h ??
            a.high
        )
    );


    updateElement(
        "low24h",
        formatPriceValue(
            a.low24h ??
            a.low_24h ??
            a.low
        )
    );


    updateElement(
        "volume24h",
        formatVolume(
            a.volume24h ??
            a.volume_24h ??
            a.volume
        )
    );


    // حالة السوق
    const marketRegime =
        a.market_regime ??
        a.marketRegime ??
        a.regime ??
        a.trend ??
        "حيادي";


    updateElement(
        "marketRegime",
        marketRegime
    );


    // RSI
    const rsi =
        Number(
            a.rsi ??
            a.RSI ??
            a.indicators?.rsi
        );


    updateElement(
        "rsi",
        Number.isFinite(rsi) ?
            rsi.toFixed(2) :
            "--"
    );


    updateElement(
        "rsiStatus",
        getRSIStatus(rsi)
    );


    // EMA
    updateElement(
        "ema20",
        formatPriceValue(
            a.ema20 ??
            a.EMA20 ??
            a.indicators?.ema20
        )
    );


    updateElement(
        "ema50",
        formatPriceValue(
            a.ema50 ??
            a.EMA50 ??
            a.indicators?.ema50
        )
    );


    updateElement(
        "ema200",
        formatPriceValue(
            a.ema200 ??
            a.EMA200 ??
            a.indicators?.ema200
        )
    );


    // MACD
    const macd =
        a.macd ??
        a.MACD ??
        a.indicators?.macd;


    updateElement(
        "macd",
        formatNumber(macd, 4)
    );


    updateElement(
        "macdStatus",
        getMACDStatus(macd)
    );


    // ATR
    updateElement(
        "atr",
        formatPriceValue(
            a.atr ??
            a.ATR ??
            a.indicators?.atr
        )
    );


    // نسبة الحجم
    updateElement(
        "volumeRatio",
        formatRatio(
            a.volume_ratio ??
            a.volumeRatio ??
            a.indicators?.volumeRatio
        )
    );


    // الاتجاه
    updateElement(
        "trend",
        a.trend ??
        a.direction ??
        a.market_trend ??
        "حيادي"
    );


    // الدعم والمقاومة
    updateElement(
        "support",
        formatPriceValue(
            a.support ??
            a.support_level ??
            a.supportLevel
        )
    );


    updateElement(
        "resistance",
        formatPriceValue(
            a.resistance ??
            a.resistance_level ??
            a.resistanceLevel
        )
    );


    // الأسباب
    renderReasons(
        a.reasons ||
        a.reason ||
        a.analysis_reasons ||
        []
    );


    // تحديث المفضلة
    updateFavoriteButton();
}


/* ============================================================
   الإشارة
   ============================================================ */

function normalizeSignal(value) {

    if (value === null || value === undefined) {
        return "حيادي";
    }


    const s =
        String(value)
            .trim()
            .toLowerCase();


    if (
        s.includes("شراء قوي") ||
        s.includes("strong buy") ||
        s.includes("strong-buy") ||
        s === "strong_buy"
    ) {
        return "شراء قوي";
    }


    if (
        s === "شراء" ||
        s === "buy" ||
        s.includes("buy")
    ) {
        return "شراء";
    }


    if (
        s.includes("بيع قوي") ||
        s.includes("strong sell") ||
        s.includes("strong-sell") ||
        s === "strong_sell"
    ) {
        return "بيع قوي";
    }


    if (
        s === "بيع" ||
        s === "sell" ||
        s.includes("sell")
    ) {
        return "بيع";
    }


    return "حيادي";
}


function signalClass(signal) {

    switch (normalizeSignal(signal)) {

        case "شراء قوي":
            return "strong-buy";

        case "شراء":
            return "buy";

        case "بيع قوي":
            return "strong-sell";

        case "بيع":
            return "sell";

        default:
            return "neutral";
    }
}


/* ============================================================
   RSI
   ============================================================ */

function getRSIStatus(rsi) {

    if (!Number.isFinite(rsi)) {
        return "--";
    }


    if (rsi >= 70) {
        return "تشبع شراء";
    }


    if (rsi <= 30) {
        return "تشبع بيع";
    }


    if (rsi >= 50) {
        return "إيجابي";
    }


    return "سلبي";
}


/* ============================================================
   MACD
   ============================================================ */

function getMACDStatus(macd) {

    if (
        macd === null ||
        macd === undefined ||
        macd === ""
    ) {
        return "--";
    }


    const value =
        Number(
            typeof macd === "object" ?
                (
                    macd.histogram ??
                    macd.value ??
                    macd.macd ??
                    0
                ) :
                macd
        );


    if (!Number.isFinite(value)) {
        return "--";
    }


    if (value > 0) {
        return "إيجابي";
    }


    if (value < 0) {
        return "سلبي";
    }


    return "محايد";
}


/* ============================================================
   الأسباب
   ============================================================ */

function renderReasons(reasons) {

    const container =
        document.getElementById("reasons");

    if (!container) return;


    let list = reasons;


    if (typeof list === "string") {

        list =
            list
                .split(/\n|،|,/)
                .map(x => x.trim())
                .filter(Boolean);
    }


    if (!Array.isArray(list)) {
        list = [];
    }


    container.innerHTML = "";


    if (!list.length) {

        container.innerHTML = `
            <div class="reason">
                لا توجد أسباب إضافية حالياً
            </div>
        `;

        return;
    }


    list.forEach(reason => {

        const text =
            typeof reason === "object" ?
                (
                    reason.text ||
                    reason.reason ||
                    reason.title ||
                    JSON.stringify(reason)
                ) :
                String(reason);


        const div =
            document.createElement("div");


        div.className =
            "reason reason-item";


        div.innerHTML =
            `✓ ${escapeHtml(text)}`;


        container.appendChild(div);
    });
}


/* ============================================================
   الشارت
   ============================================================ */

function drawChart() {

    const canvas =
        document.getElementById("priceChart");

    if (!canvas) return;


    const wrapper =
        canvas.parentElement;


    const width =
        Math.max(
            300,
            wrapper?.clientWidth ||
            canvas.clientWidth ||
            800
        );


    const height =
        Math.max(
            250,
            wrapper?.clientHeight ||
            380
        );


    const ratio =
        window.devicePixelRatio || 1;


    canvas.width =
        width * ratio;

    canvas.height =
        height * ratio;


    canvas.style.width =
        `${width}px`;

    canvas.style.height =
        `${height}px`;


    const ctx =
        canvas.getContext("2d");


    ctx.setTransform(
        ratio,
        0,
        0,
        ratio,
        0,
        0
    );


    ctx.clearRect(
        0,
        0,
        width,
        height
    );


    let candles =
        Array.isArray(state.candles) ?
            state.candles :
            [];


    if (!candles.length) {

        drawChartMessage(
            ctx,
            width,
            height,
            "لا توجد بيانات الشارت"
        );

        return;
    }


    candles =
        candles.slice(-80);


    const parsed =
        candles
            .map(parseCandle)
            .filter(Boolean);


    if (!parsed.length) {

        drawChartMessage(
            ctx,
            width,
            height,
            "بيانات الشارت غير متاحة"
        );

        return;
    }


    const highs =
        parsed.map(c => c.high);

    const lows =
        parsed.map(c => c.low);


    let max =
        Math.max(...highs);

    let min =
        Math.min(...lows);


    if (
        !Number.isFinite(max) ||
        !Number.isFinite(min) ||
        max === min
    ) {

        drawChartMessage(
            ctx,
            width,
            height,
            "لا توجد حركة سعرية كافية"
        );

        return;
    }


    const padding =
        Math.max(
            20,
            (max - min) * 0.05
        );


    max += padding;
    min -= padding;


    const left = 45;
    const right = 15;
    const top = 20;
    const bottom = 25;


    const chartWidth =
        width - left - right;

    const chartHeight =
        height - top - bottom;


    function y(value) {

        return top +
            (
                (max - value) /
                (max - min)
            ) *
            chartHeight;
    }


    // الشبكة
    ctx.lineWidth = 1;

    ctx.strokeStyle =
        getCSSColor(
            "--chart-grid",
            "rgba(255,255,255,.08)"
        );


    for (let i = 0; i <= 5; i++) {

        const yy =
            top +
            (chartHeight / 5) * i;


        ctx.beginPath();

        ctx.moveTo(
            left,
            yy
        );

        ctx.lineTo(
            width - right,
            yy
        );

        ctx.stroke();


        const value =
            max -
            ((max - min) / 5) * i;


        ctx.fillStyle =
            getCSSColor(
                "--muted",
                "#888"
            );


        ctx.font =
            "10px Arial";


        ctx.fillText(
            formatPrice(value),
            4,
            yy + 3
        );
    }


    const candleWidth =
        Math.max(
            2,
            chartWidth / parsed.length * 0.65
        );


    parsed.forEach((candle, index) => {

        const x =
            left +
            (
                index /
                Math.max(1, parsed.length - 1)
            ) *
            chartWidth;


        const openY =
            y(candle.open);

        const closeY =
            y(candle.close);

        const highY =
            y(candle.high);

        const lowY =
            y(candle.low);


        const bullish =
            candle.close >= candle.open;


        ctx.strokeStyle =
            bullish ?
                "#16c784" :
                "#ea3943";


        ctx.fillStyle =
            bullish ?
                "#16c784" :
                "#ea3943";


        // الذيل
        ctx.beginPath();

        ctx.moveTo(
            x,
            highY
        );

        ctx.lineTo(
            x,
            lowY
        );

        ctx.stroke();


        // الجسم
        const bodyTop =
            Math.min(
                openY,
                closeY
            );


        const bodyHeight =
            Math.max(
                1,
                Math.abs(
                    closeY -
                    openY
                )
            );


        ctx.fillRect(
            x - candleWidth / 2,
            bodyTop,
            candleWidth,
            bodyHeight
        );
    });


    // خط السعر الحالي
    const current =
        getPrice(state.symbol) ||
        parsed[parsed.length - 1].close;


    if (Number.isFinite(current)) {

        const currentY =
            y(current);


        ctx.strokeStyle =
            "#f0a500";


        ctx.setLineDash([
            5,
            5
        ]);


        ctx.beginPath();

        ctx.moveTo(
            left,
            currentY
        );

        ctx.lineTo(
            width - right,
            currentY
        );

        ctx.stroke();

        ctx.setLineDash([]);


        ctx.fillStyle =
            "#f0a500";


        ctx.font =
            "bold 11px Arial";


        ctx.fillText(
            formatPrice(current),
            width - 70,
            currentY - 5
        );
    }
}


function parseCandle(candle) {

    if (Array.isArray(candle)) {

        return {
            open: Number(candle[1]),
            high: Number(candle[2]),
            low: Number(candle[3]),
            close: Number(candle[4])
        };
    }


    if (!candle || typeof candle !== "object") {
        return null;
    }


    const result = {

        open: Number(
            candle.open ??
            candle.o
        ),

        high: Number(
            candle.high ??
            candle.h
        ),

        low: Number(
            candle.low ??
            candle.l
        ),

        close: Number(
            candle.close ??
            candle.c
        )
    };


    if (
        !Number.isFinite(result.open) ||
        !Number.isFinite(result.high) ||
        !Number.isFinite(result.low) ||
        !Number.isFinite(result.close)
    ) {
        return null;
    }


    return result;
}


function drawChartMessage(
    ctx,
    width,
    height,
    message
) {

    ctx.fillStyle =
        getCSSColor(
            "--muted",
            "#888"
        );

    ctx.font =
        "14px Arial";

    ctx.textAlign =
        "center";

    ctx.fillText(
        message,
        width / 2,
        height / 2
    );

    ctx.textAlign =
        "start";
}


/* ============================================================
   المفضلة
   ============================================================ */

function toggleFavorite() {

    const index =
        state.favorites.indexOf(
            state.symbol
        );


    if (index >= 0) {

        state.favorites.splice(
            index,
            1
        );

        showToast("تم حذف العملة من المفضلة");

    } else {

        state.favorites.push(
            state.symbol
        );

        showToast("تمت إضافة العملة للمفضلة ⭐");
    }


    localStorage.setItem(
        "favorites",
        JSON.stringify(state.favorites)
    );


    updateFavoriteButton();
}


function updateFavoriteButton() {

    const button =
        document.getElementById(
            "favoriteBtn"
        );

    if (!button) return;


    const favorite =
        state.favorites.includes(
            state.symbol
        );


    button.classList.toggle(
        "active",
        favorite
    );


    button.setAttribute(
        "aria-pressed",
        favorite ? "true" : "false"
    );


    if (
        button.querySelector(".favorite-text")
    ) {

        button.querySelector(
            ".favorite-text"
        ).textContent =
            favorite ?
                "من المفضلة" :
                "إضافة للمفضلة";
    }
}


/* ============================================================
   Scanner
   ============================================================ */

async function runScanner() {

    const container =
        document.getElementById(
            "scannerResults"
        );


    if (!container) return;


    container.innerHTML = `
        <div class="loading">
            جاري فحص العملات... 🔎
        </div>
    `;


    try {

        const data =
            await api(
                "/api/binance/scan"
            );


        const results =
            data.results ||
            data.scan ||
            data.symbols ||
            [];


        if (!Array.isArray(results) || !results.length) {

            container.innerHTML = `
                <div class="empty-state">
                    ما لقيت إشارات حالياً
                </div>
            `;

            return;
        }


        container.innerHTML = "";


        results.forEach(item => {

            const symbol =
                getMarketSymbol(item) ||
                item.symbol ||
                "";


            const signal =
                normalizeSignal(
                    item.signal ||
                    item.recommendation ||
                    "حيادي"
                );


            const div =
                document.createElement("div");


            div.className =
                "scan-item";


            div.innerHTML = `
                <div>
                    <strong>
                        ${escapeHtml(symbol)}
                    </strong>

                    <small>
                        ${escapeHtml(signal)}
                    </small>
                </div>

                <div>
                    ${
                        item.score !== undefined ?
                        formatNumber(item.score, 0) :
                        "--"
                    }
                </div>
            `;


            div.addEventListener(
                "click",
                async () => {

                    state.symbol =
                        symbol;

                    await loadData();

                }
            );


            container.appendChild(div);
        });


    } catch (error) {

        container.innerHTML = `
            <div class="error-state">
                ${escapeHtml(error.message)}
            </div>
        `;
    }
}


/* ============================================================
   المودالات
   ============================================================ */

function openModal(id) {

    const modal =
        document.getElementById(id);

    if (!modal) return;


    modal.classList.add("open");

    modal.style.display =
        "flex";
}


function closeModal(id) {

    const modal =
        document.getElementById(id);

    if (!modal) return;


    modal.classList.remove("open");


    setTimeout(() => {

        if (
            !modal.classList.contains("open")
        ) {

            modal.style.display =
                "none";
        }

    }, 200);
}


function showLogin() {

    openModal("authModal");


    const loginForm =
        document.getElementById(
            "loginForm"
        );


    const registerForm =
        document.getElementById(
            "registerForm"
        );


    if (loginForm) {
        loginForm.style.display = "";
    }


    if (registerForm) {
        registerForm.style.display = "none";
    }


    clearAuthErrors();
}


function showRegister() {

    openModal("authModal");


    const loginForm =
        document.getElementById(
            "loginForm"
        );


    const registerForm =
        document.getElementById(
            "registerForm"
        );


    if (loginForm) {
        loginForm.style.display = "none";
    }


    if (registerForm) {
        registerForm.style.display = "";
    }


    clearAuthErrors();
}


function clearAuthErrors() {

    updateElement(
        "loginError",
        ""
    );


    updateElement(
        "registerError",
        ""
    );
}


function showLoginError(message) {

    updateElement(
        "loginError",
        message
    );
}


function showRegisterError(message) {

    updateElement(
        "registerError",
        message
    );
}


/* ============================================================
   التحديث التلقائي
   ============================================================ */

function startAutoRefresh() {

    if (state.refreshTimer) {

        clearInterval(
            state.refreshTimer
        );

        state.refreshTimer = null;
    }


    let seconds =
        Number(
            state.settings.refresh_seconds
        );


    if (
        !Number.isFinite(seconds) ||
        seconds < 10
    ) {
        seconds = 30;
    }


    state.refreshTimer =
        setInterval(
            async () => {

                if (state.loading) {
                    return;
                }


                try {

                    await loadPrices();

                    await loadData();

                } catch (error) {

                    console.warn(
                        "Auto refresh:",
                        error
                    );
                }

            },
            seconds * 1000
        );
}


/* ============================================================
   واجهة التحميل والخطأ
   ============================================================ */

function showLoading(show) {

    const refreshBtn =
        document.getElementById(
            "refreshBtn"
        );


    if (!refreshBtn) return;


    refreshBtn.classList.toggle(
        "loading",
        show
    );


    refreshBtn.disabled =
        show;
}


function showError(message) {

    const errorBox =
        document.getElementById(
            "errorBox"
        );


    if (!errorBox) {

        console.error(message);

        return;
    }


    errorBox.textContent =
        message;


    errorBox.classList.add(
        "show"
    );


    setTimeout(() => {

        errorBox.classList.remove(
            "show"
        );

    }, 6000);
}


function showToast(message) {

    let toast =
        document.getElementById(
            "appToast"
        );


    if (!toast) {

        toast =
            document.createElement(
                "div"
            );


        toast.id =
            "appToast";


        toast.style.position =
            "fixed";


        toast.style.bottom =
            "25px";


        toast.style.left =
            "50%";


        toast.style.transform =
            "translateX(-50%)";


        toast.style.zIndex =
            "99999";


        toast.style.padding =
            "12px 20px";


        toast.style.borderRadius =
            "12px";


        toast.style.background =
            "#111827";


        toast.style.color =
            "#fff";


        toast.style.boxShadow =
            "0 10px 30px rgba(0,0,0,.25)";


        toast.style.fontSize =
            "14px";


        document.body.appendChild(
            toast
        );
    }


    toast.textContent =
        message;


    toast.style.display =
        "block";


    clearTimeout(
        toast._timer
    );


    toast._timer =
        setTimeout(() => {

            toast.style.display =
                "none";

        }, 3000);
}


/* ============================================================
   أدوات مساعدة
   ============================================================ */

function updateElement(id, value) {

    const element =
        document.getElementById(id);

    if (!element) return;

    element.textContent =
        value === null ||
        value === undefined ||
        value === "" ?
            "--" :
            value;
}


function formatPrice(value) {

    const number =
        Number(value);


    if (
        !Number.isFinite(number) ||
        number === 0
    ) {
        return "--";
    }


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
                maximumFractionDigits: 6
            }
        );
    }


    return number.toLocaleString(
        "en-US",
        {
            minimumFractionDigits: 0,
            maximumFractionDigits: 10
        }
    );
}


function formatPriceValue(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return String(value);
    }


    return formatPrice(number);
}


function formatPercent(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return (
        number >= 0 ? "+" : ""
    ) +
    number.toFixed(2) +
    "%";
}


function formatNumber(value, decimals = 2) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return number.toFixed(
        decimals
    );
}


function formatRR(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return String(value);
    }


    return "1:" +
        number.toFixed(2);
}


function formatRatio(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return number.toFixed(2) + "x";
}


function formatVolume(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "--";
    }


    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    if (number >= 1e9) {
        return (
            number / 1e9
        ).toFixed(2) + "B";
    }


    if (number >= 1e6) {
        return (
            number / 1e6
        ).toFixed(2) + "M";
    }


    if (number >= 1e3) {
        return (
            number / 1e3
        ).toFixed(2) + "K";
    }


    return number.toFixed(2);
}


function getCSSColor(
    variable,
    fallback
) {

    try {

        const value =
            getComputedStyle(
                document.documentElement
            )
                .getPropertyValue(variable)
                .trim();


        return value || fallback;

    } catch (_) {

        return fallback;
    }
}


function escapeHtml(value) {

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* ============================================================
   تنظيف المؤقت عند إغلاق الصفحة
   ============================================================ */

window.addEventListener(
    "beforeunload",
    () => {

        if (state.refreshTimer) {

            clearInterval(
                state.refreshTimer
            );
        }
    }
);

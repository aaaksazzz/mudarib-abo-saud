// ============================================================
// تحليل العملات الرقمية - APP.JS
// Frontend + Auth + Settings + Binance Analysis
// ============================================================

"use strict";

const state = {
    symbol: "BTCUSDT",
    interval: "15m",
    markets: [],
    prices: {},
    analysis: null,
    candles: [],
    loading: false,
    loggedIn: false,
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

const $ = (id) => document.getElementById(id);


// ============================================================
// START
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {

    bindEvents();

    loadLocalTheme();

    await checkSession();

    await loadSettings();

    await loadMarkets();

    await loadData();

    startAutoRefresh();

});


// ============================================================
// EVENTS
// ============================================================

function bindEvents() {

    // البحث
    const search = $("coinSearch");

    if (search) {
        search.addEventListener("input", () => {
            renderCoins(search.value);
        });
    }


    // الفريمات
    document.querySelectorAll("[data-interval]").forEach(btn => {

        btn.addEventListener("click", async () => {

            state.interval = btn.dataset.interval;

            document.querySelectorAll("[data-interval]")
                .forEach(x => x.classList.remove("active"));

            btn.classList.add("active");

            if ($("intervalSetting")) {
                $("intervalSetting").value = state.interval;
            }

            await loadData();

        });

    });


    // تحديث
    const refresh = $("refreshBtn");

    if (refresh) {
        refresh.addEventListener("click", loadData);
    }


    // تسجيل الدخول
    const loginForm = $("loginForm");

    if (loginForm) {

        loginForm.addEventListener("submit", async (event) => {

            event.preventDefault();

            await login();

        });

    }


    // إنشاء الحساب
    const registerForm = $("registerForm");

    if (registerForm) {

        registerForm.addEventListener("submit", async (event) => {

            event.preventDefault();

            await register();

        });

    }


    // تسجيل الخروج
    const logoutBtn = $("logoutBtn");

    if (logoutBtn) {

        logoutBtn.addEventListener("click", logout);

    }


    // حفظ الإعدادات
    const saveSettingsBtn = $("saveSettingsBtn");

    if (saveSettingsBtn) {

        saveSettingsBtn.addEventListener(
            "click",
            saveSettings
        );

    }


    // المفضلة
    const favoriteBtn = $("favoriteBtn");

    if (favoriteBtn) {

        favoriteBtn.addEventListener(
            "click",
            toggleFavorite
        );

    }


    // ماسح الفرص
    const scannerBtn = $("runScannerBtn");

    if (scannerBtn) {

        scannerBtn.addEventListener(
            "click",
            runScanner
        );

    }


    // Premium
    const subscribeBtn = $("subscribeBtn");

    if (subscribeBtn) {

        subscribeBtn.addEventListener(
            "click",
            openPremiumPayment
        );

    }


    // زر الأدمن
    const adminLink = $("adminLink");

    if (adminLink) {

        adminLink.addEventListener("click", () => {

            window.location.href = "/admin";

        });

    }


    // الوضع
    const themeDark = $("themeDark");

    if (themeDark) {

        themeDark.addEventListener("click", () => {

            applyTheme("dark");

        });

    }


    const themeLight = $("themeLight");

    if (themeLight) {

        themeLight.addEventListener("click", () => {

            applyTheme("light");

        });

    }

}


// ============================================================
// API
// ============================================================

async function api(url, options = {}) {

    const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    let data = {};

    try {

        data = await response.json();

    } catch (error) {

        data = {};

    }


    if (!response.ok || data.ok === false) {

        throw new Error(
            data.message ||
            data.error ||
            `HTTP ${response.status}`
        );

    }

    return data;

}


// ============================================================
// SESSION
// ============================================================

async function checkSession() {

    try {

        const data = await api(
            "/api/auth/me"
        );

        state.loggedIn = true;

        state.user =
            data.user ||
            data.account ||
            data;

        updateUserUI();

    } catch (error) {

        state.loggedIn = false;

        state.user = null;

        updateUserUI();

    }

}


// ============================================================
// USER UI
// ============================================================

function updateUserUI() {

    const loginBtn = $("loginBtn");
    const logoutBtn = $("logoutBtn");
    const username = $("usernameDisplay");
    const plan = $("planDisplay");
    const adminLink = $("adminLink");

    if (!state.loggedIn || !state.user) {

        if (loginBtn) {
            loginBtn.style.display = "";
        }

        if (logoutBtn) {
            logoutBtn.style.display = "none";
        }

        if (username) {
            username.textContent = "";
        }

        if (plan) {
            plan.textContent = "مجاني";
        }

        if (adminLink) {
            adminLink.style.display = "none";
        }

        return;
    }


    if (loginBtn) {
        loginBtn.style.display = "none";
    }

    if (logoutBtn) {
        logoutBtn.style.display = "";
    }


    const usernameValue =
        state.user.username ||
        state.user.name ||
        "";

    if (username) {
        username.textContent =
            usernameValue;
    }


    const userPlan =
        state.user.plan ||
        state.user.subscription ||
        "free";

    if (plan) {

        plan.textContent =
            isPremiumPlan(userPlan)
                ? "Premium 👑"
                : "مجاني";

        plan.className =
            isPremiumPlan(userPlan)
                ? "plan-display premium"
                : "plan-display";

    }


    // إظهار لوحة الإدارة إذا كانت البيانات تشير إلى Admin
    const isAdmin =
        state.user.is_admin === true ||
        state.user.role === "admin";

    if (adminLink) {

        adminLink.style.display =
            isAdmin
                ? ""
                : "none";

    }

}


// ============================================================
// LOGIN
// ============================================================

async function login() {

    const username =
        $("loginUsername")?.value.trim();

    const password =
        $("loginPassword")?.value || "";

    const error =
        $("loginError");


    if (!username || !password) {

        showFormError(
            error,
            "اكتب اسم المستخدم وكلمة المرور."
        );

        return;

    }


    setButtonLoading(
        $("loginForm")?.querySelector(
            'button[type="submit"]'
        ),
        true,
        "جاري الدخول..."
    );


    try {

        const data = await api(
            "/api/auth/login",
            {
                method: "POST",
                body: JSON.stringify({
                    username,
                    password
                })
            }
        );


        state.loggedIn = true;

        state.user =
            data.user ||
            data.account ||
            data;


        updateUserUI();

        closeModal("authModal");

        showToast(
            "تم تسجيل الدخول بنجاح ✅"
        );


        await loadSettings();


    } catch (err) {

        showFormError(
            error,
            err.message
        );

    } finally {

        setButtonLoading(
            $("loginForm")?.querySelector(
                'button[type="submit"]'
            ),
            false,
            "دخول"
        );

    }

}


// ============================================================
// REGISTER
// ============================================================

async function register() {

    const username =
        $("registerUsername")?.value.trim();

    const email =
        $("registerEmail")?.value.trim();

    const password =
        $("registerPassword")?.value || "";

    const password2 =
        $("registerPassword2")?.value || "";

    const error =
        $("registerError");


    if (!username || !email || !password) {

        showFormError(
            error,
            "عبّ جميع البيانات المطلوبة."
        );

        return;

    }


    if (password !== password2) {

        showFormError(
            error,
            "كلمتا المرور غير متطابقتين."
        );

        return;

    }


    if (password.length < 6) {

        showFormError(
            error,
            "كلمة المرور لازم تكون 6 أحرف أو أكثر."
        );

        return;

    }


    setButtonLoading(
        $("registerForm")?.querySelector(
            'button[type="submit"]'
        ),
        true,
        "جاري إنشاء الحساب..."
    );


    try {

        const data = await api(
            "/api/auth/register",
            {
                method: "POST",
                body: JSON.stringify({
                    username,
                    email,
                    password
                })
            }
        );


        // إذا السيرفر يدخل المستخدم مباشرة
        if (
            data.user ||
            data.account ||
            data.logged_in ||
            data.login
        ) {

            state.loggedIn = true;

            state.user =
                data.user ||
                data.account ||
                data;

            updateUserUI();

            closeModal("authModal");

            showToast(
                "تم إنشاء حسابك بنجاح 🎉"
            );

        } else {

            showLoginForm();

            showToast(
                "تم إنشاء الحساب، سجّل دخولك الآن ✅"
            );

        }


    } catch (err) {

        showFormError(
            error,
            err.message
        );

    } finally {

        setButtonLoading(
            $("registerForm")?.querySelector(
                'button[type="submit"]'
            ),
            false,
            "إنشاء الحساب"
        );

    }

}


// ============================================================
// LOGOUT
// ============================================================

async function logout() {

    try {

        await api(
            "/api/auth/logout",
            {
                method: "POST"
            }
        );

    } catch (error) {

        console.warn(error);

    }


    state.loggedIn = false;

    state.user = null;

    updateUserUI();

    showToast(
        "تم تسجيل الخروج 👋"
    );

}


// ============================================================
// SETTINGS
// ============================================================

async function loadSettings() {

    if (!state.loggedIn) {
        return;
    }


    try {

        const data =
            await api("/api/settings");


        const settings =
            data.settings ||
            data;


        state.settings = {
            ...state.settings,
            ...settings
        };


        if (settings.interval) {

            state.interval =
                settings.interval;

        }


        if (settings.refresh_seconds) {

            state.settings.refresh_seconds =
                Number(settings.refresh_seconds);

        }


        if (
            settings.theme === "light" ||
            settings.theme === "dark"
        ) {

            applyTheme(
                settings.theme,
                false
            );

        }


        updateSettingsUI();

        startAutoRefresh();

    } catch (error) {

        console.warn(
            "Settings:",
            error.message
        );

    }

}


// ============================================================
// SAVE SETTINGS
// ============================================================

async function saveSettings() {

    if (!state.loggedIn) {

        openAuth();

        return;

    }


    const interval =
        $("intervalSetting")?.value ||
        state.interval;


    const refreshSeconds =
        Number(
            $("refreshSetting")?.value ||
            30
        );


    const notifications =
        Boolean(
            $("notificationsSetting")?.checked
        );


    const theme =
        document.body.classList.contains(
            "light-theme"
        )
            ? "light"
            : "dark";


    const payload = {

        theme,

        interval,

        refresh_seconds:
            refreshSeconds,

        notifications

    };


    try {

        await api(
            "/api/settings",
            {
                method: "POST",
                body: JSON.stringify(payload)
            }
        );


        state.settings =
            {
                ...state.settings,
                ...payload
            };


        state.interval =
            interval;


        applyIntervalButton(
            state.interval
        );


        startAutoRefresh();


        const message =
            $("settingsMessage");

        if (message) {

            message.textContent =
                "تم حفظ الإعدادات ✅";

            setTimeout(() => {

                message.textContent = "";

            }, 3000);

        }


        showToast(
            "تم حفظ الإعدادات ✅"
        );


    } catch (error) {

        showToast(
            "تعذر حفظ الإعدادات: " +
            error.message,
            true
        );

    }

}


// ============================================================
// SETTINGS UI
// ============================================================

function updateSettingsUI() {

    if ($("intervalSetting")) {

        $("intervalSetting").value =
            state.interval ||
            "15m";

    }


    if ($("refreshSetting")) {

        $("refreshSetting").value =
            String(
                state.settings.refresh_seconds ||
                30
            );

    }


    if ($("notificationsSetting")) {

        $("notificationsSetting").checked =
            Boolean(
                state.settings.notifications
            );

    }


    applyIntervalButton(
        state.interval
    );

}


// ============================================================
// AUTO REFRESH
// ============================================================

function startAutoRefresh() {

    if (state.refreshTimer) {

        clearInterval(
            state.refreshTimer
        );

    }


    const seconds =
        Number(
            state.settings.refresh_seconds ||
            30
        );


    state.refreshTimer =
        setInterval(
            () => loadData(),
            Math.max(10, seconds) * 1000
        );

}


// ============================================================
// MARKETS
// ============================================================

async function loadMarkets() {

    try {

        const data =
            await api(
                "/api/binance/markets"
            );


        state.markets =
            data.symbols ||
            data.markets ||
            [];


        renderCoins("");


        setText(
            "coinCount",
            `${state.markets.length} عملة`
        );


    } catch (error) {

        showError(
            "تعذر تحميل قائمة العملات: " +
            error.message
        );

    }

}


// ============================================================
// RENDER COINS
// ============================================================

function renderCoins(search = "") {

    const container =
        $("coinList");

    if (!container) {
        return;
    }


    const query =
        String(search)
            .trim()
            .toUpperCase();


    let coins =
        Array.isArray(state.markets)
            ? state.markets
            : [];


    if (query) {

        coins =
            coins.filter(coin => {

                const symbol =
                    typeof coin === "string"
                        ? coin
                        : coin.symbol;

                return String(symbol)
                    .toUpperCase()
                    .includes(query);

            });

    }


    coins =
        coins.slice(0, 150);


    container.innerHTML = "";


    if (!coins.length) {

        container.innerHTML = `
            <div class="empty-state">
                لا توجد عملات مطابقة للبحث.
            </div>
        `;

        return;

    }


    coins.forEach(coin => {

        const symbol =
            typeof coin === "string"
                ? coin
                : coin.symbol;


        if (!symbol) {
            return;
        }


        const button =
            document.createElement("button");


        button.type =
            "button";


        button.className =
            "coin-item " +
            (
                symbol === state.symbol
                    ? "selected"
                    : ""
            );


        const base =
            symbol.replace(
                /USDT$/i,
                ""
            );


        const price =
            state.prices[symbol];


        const priceValue =
            price?.price ??
            price?.lastPrice ??
            price?.last ??
            null;


        const change =
            Number(
                price?.change24h ??
                price?.priceChangePercent ??
                0
            );


        button.innerHTML = `

            <div class="coin-name">

                <strong>
                    ${escapeHtml(base)}
                </strong>

                <span>
                    ${escapeHtml(symbol)}
                </span>

            </div>


            <div class="coin-price">

                <strong>
                    ${formatPrice(priceValue)}
                </strong>

                <span class="${change >= 0 ? "positive" : "negative"}">
                    ${formatPercent(change)}
                </span>

            </div>

        `;


        button.addEventListener(
            "click",
            async () => {

                state.symbol =
                    symbol;


                document
                    .querySelectorAll(
                        ".coin-item"
                    )
                    .forEach(
                        x =>
                            x.classList.remove(
                                "selected"
                            )
                    );


                button.classList.add(
                    "selected"
                );


                await loadData();

            }
        );


        container.appendChild(
            button
        );

    });

}


// ============================================================
// LOAD DATA
// ============================================================

async function loadData() {

    if (state.loading) {
        return;
    }


    state.loading = true;


    setStatus(
        "جاري تحديث بيانات السوق..."
    );


    try {

        const [
            prices,
            analysis
        ] = await Promise.all([

            api(
                "/api/binance/prices"
            ),

            api(
                `/api/binance/analysis?symbol=${encodeURIComponent(
                    state.symbol
                )}&interval=${encodeURIComponent(
                    state.interval
                )}`
            )

        ]);


        state.prices = {};


        const priceList =
            prices.prices ||
            prices.data ||
            [];


        if (Array.isArray(priceList)) {

            priceList.forEach(item => {

                if (item.symbol) {

                    state.prices[
                        item.symbol
                    ] = item;

                }

            });

        }


        state.analysis =
            analysis.analysis ||
            analysis.data ||
            analysis;


        state.candles =
            analysis.candles ||
            analysis.data?.candles ||
            [];


        renderCoins(
            $("coinSearch")
                ? $("coinSearch").value
                : ""
        );


        renderMarketHeader();

        renderAnalysis();

        renderChart();

        renderFavoriteButton();


        setStatus(
            "آخر تحديث: " +
            new Date().toLocaleTimeString(
                "ar-SA"
            )
        );


    } catch (error) {

        console.error(
            "loadData:",
            error
        );


        showError(
            "تعذر تحديث البيانات: " +
            error.message
        );


        setStatus(
            "تعذر تحديث البيانات"
        );

    } finally {

        state.loading =
            false;

    }

}


// ============================================================
// MARKET HEADER
// ============================================================

function renderMarketHeader() {

    const item =
        state.prices[
            state.symbol
        ];


    const a =
        state.analysis;


    const symbolName =
        state.symbol.replace(
            /USDT$/i,
            ""
        );


    setText(
        "symbolName",
        symbolName + " / USDT"
    );


    setText(
        "currentPrice",
        a
            ? formatPrice(
                a.price ??
                a.current_price
            )
            : formatPrice(
                item?.price
            )
    );


    if (item) {

        const change =
            Number(
                item.change24h ??
                item.priceChangePercent ??
                0
            );


        const changeEl =
            $("priceChange");


        if (changeEl) {

            changeEl.textContent =
                formatPercent(
                    change
                );


            changeEl.className =
                change >= 0
                    ? "positive"
                    : "negative";

        }


        setText(
            "high24h",
            formatPrice(
                item.high24h ??
                item.highPrice
            )
        );


        setText(
            "low24h",
            formatPrice(
                item.low24h ??
                item.lowPrice
            )
        );


        setText(
            "volume24h",
            formatVolume(
                item.volume ??
                item.quoteVolume
            )
        );

    }


    if (a) {

        const regime =
            a.market_regime ||
            a.regime ||
            a.marketRegime ||
            null;


        if (regime) {

            setText(
                "marketRegime",
                regime
            );

            setText(
                "marketRegimeOverview",
                regime
            );

        }

    }

}


// ============================================================
// ANALYSIS
// ============================================================

function renderAnalysis() {

    const a =
        state.analysis;


    if (!a) {
        return;
    }


    const signal =
        a.signal ||
        a.status ||
        "حيادي";


    const signalEl =
        $("signal");


    if (signalEl) {

        signalEl.textContent =
            signal;


        signalEl.className =
            "signal " +
            signalClass(
                signal
            );

    }


    // النقاط: نحولها للعرض حسب المتاح
    const score =
        Number(
            a.score ??
            a.strength ??
            0
        );


    setText(
        "score",
        `${score}/10`
    );


    setText(
        "entry",
        formatPrice(
            a.entry
        )
    );


    setText(
        "tp1",
        formatPrice(
            a.tp1
        )
    );


    setText(
        "tp2",
        formatPrice(
            a.tp2
        )
    );


    setText(
        "tp3",
        formatPrice(
            a.tp3
        )
    );


    setText(
        "sl",
        formatPrice(
            a.sl
        )
    );


    const rr =
        Number(
            a.rr ??
            a.risk_reward ??
            0
        );


    setText(
        "rr",
        rr
            ? `1 : ${rr.toFixed(2)}`
            : "--"
    );


    // RSI
    const rsi =
        numberOrNull(
            a.rsi
        );


    setText(
        "rsi",
        rsi !== null
            ? rsi.toFixed(2)
            : "--"
    );


    setText(
        "rsiStatus",
        rsiStatus(rsi)
    );


    // EMA
    setText(
        "ema20",
        formatPrice(
            a.ema20
        )
    );


    setText(
        "ema50",
        formatPrice(
            a.ema50
        )
    );


    setText(
        "ema200",
        formatPrice(
            a.ema200
        )
    );


    // MACD
    const macd =
        numberOrNull(
            a.macd
        );


    setText(
        "macd",
        macd !== null
            ? macd.toFixed(6)
            : "--"
    );


    setText(
        "macdStatus",
        macdStatus(macd)
    );


    // ATR
    setText(
        "atr",
        formatPrice(
            a.atr
        )
    );


    // Volume
    const volumeRatio =
        numberOrNull(
            a.volumeRatio
        );


    setText(
        "volumeRatio",
        volumeRatio !== null
            ? volumeRatio.toFixed(2) + "x"
            : "--"
    );


    // Support
    setText(
        "support",
        formatPrice(
            a.support
        )
    );


    // Resistance
    setText(
        "resistance",
        formatPrice(
            a.resistance
        )
    );


    // Trend
    const trend =
        a.trend ||
        a.direction ||
        "--";


    setText(
        "trend",
        trend
    );


    setText(
        "marketTrend",
        trend
    );


    setText(
        "marketStrength",
        `${score}/10`
    );


    renderReasons(
        a.reasons ||
        a.reason ||
        []
    );


    updateSignalProgress(
        score
    );

}


// ============================================================
// SIGNAL PROGRESS
// ============================================================

function updateSignalProgress(score) {

    const progress =
        $("signalProgress");


    if (!progress) {
        return;
    }


    const value =
        Math.max(
            0,
            Math.min(
                100,
                Number(score) * 10
            )
        );


    progress.style.width =
        value + "%";

}


// ============================================================
// REASONS
// ============================================================

function renderReasons(reasons) {

    const container =
        $("reasons");


    if (!container) {
        return;
    }


    if (!Array.isArray(reasons)) {

        reasons =
            reasons
                ? [String(reasons)]
                : [];

    }


    container.innerHTML =
        "";


    if (!reasons.length) {

        container.innerHTML = `
            <div class="empty">
                لا توجد أسباب إضافية متاحة حالياً.
            </div>
        `;

        return;

    }


    reasons.forEach(reason => {

        const item =
            document.createElement(
                "div"
            );


        item.className =
            "reason";


        item.innerHTML = `

            <span class="reason-check">
                ✓
            </span>

            <span>
                ${escapeHtml(
                    String(reason)
                )}
            </span>

        `;


        container.appendChild(
            item
        );

    });

}


// ============================================================
// CHART
// ============================================================

function renderChart() {

    const canvas =
        $("priceChart");


    if (
        !canvas ||
        !Array.isArray(
            state.candles
        ) ||
        !state.candles.length
    ) {
        return;
    }


    const ctx =
        canvas.getContext(
            "2d"
        );


    const rect =
        canvas.getBoundingClientRect();


    const width =
        Math.max(
            rect.width,
            300
        );


    const height =
        Math.max(
            rect.height,
            300
        );


    const dpr =
        window.devicePixelRatio ||
        1;


    canvas.width =
        width * dpr;


    canvas.height =
        height * dpr;


    ctx.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );


    ctx.clearRect(
        0,
        0,
        width,
        height
    );


    const candles =
        state.candles
            .slice(-80)
            .map(normalizeCandle)
            .filter(Boolean);


    if (!candles.length) {
        return;
    }


    const highs =
        candles.map(
            x => x.high
        );


    const lows =
        candles.map(
            x => x.low
        );


    const max =
        Math.max(
            ...highs
        );


    const min =
        Math.min(
            ...lows
        );


    const range =
        max - min || 1;


    const padding =
        25;


    const chartWidth =
        width -
        padding * 2;


    const chartHeight =
        height -
        padding * 2;


    // الشبكة
    ctx.lineWidth =
        1;


    for (
        let i = 0;
        i <= 4;
        i++
    ) {

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


    const step =
        chartWidth /
        candles.length;


    const candleWidth =
        Math.max(
            2,
            step * 0.62
        );


    candles.forEach(
        (candle, index) => {

            const x =
                padding +
                index * step +
                step / 2;


            const yHigh =
                priceToY(
                    candle.high,
                    max,
                    range,
                    padding,
                    chartHeight
                );


            const yLow =
                priceToY(
                    candle.low,
                    max,
                    range,
                    padding,
                    chartHeight
                );


            const yOpen =
                priceToY(
                    candle.open,
                    max,
                    range,
                    padding,
                    chartHeight
                );


            const yClose =
                priceToY(
                    candle.close,
                    max,
                    range,
                    padding,
                    chartHeight
                );


            const bullish =
                candle.close >=
                candle.open;


            const color =
                bullish
                    ? "#22c55e"
                    : "#ef4444";


            ctx.strokeStyle =
                color;


            ctx.fillStyle =
                color;


            // wick
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


            // body
            const top =
                Math.min(
                    yOpen,
                    yClose
                );


            const bodyHeight =
                Math.max(
                    1,
                    Math.abs(
                        yClose -
                        yOpen
                    )
                );


            ctx.fillRect(
                x -
                candleWidth / 2,
                top,
                candleWidth,
                bodyHeight
            );

        }
    );


    // السعر الحالي
    const last =
        candles[
            candles.length - 1
        ];


    const currentY =
        priceToY(
            last.close,
            max,
            range,
            padding,
            chartHeight
        );


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
        formatPrice(
            last.close
        ),
        Math.max(
            5,
            width - 95
        ),
        Math.max(
            15,
            currentY - 7
        )
    );

}


// ============================================================
// CHART HELPERS
// ============================================================

function normalizeCandle(candle) {

    if (!candle) {
        return null;
    }


    // Object
    if (
        typeof candle === "object" &&
        !Array.isArray(candle)
    ) {

        const open =
            Number(
                candle.open
            );


        const high =
            Number(
                candle.high
            );


        const low =
            Number(
                candle.low
            );


        const close =
            Number(
                candle.close
            );


        if (
            Number.isFinite(open) &&
            Number.isFinite(high) &&
            Number.isFinite(low) &&
            Number.isFinite(close)
        ) {

            return {
                open,
                high,
                low,
                close
            };

        }

    }


    // Binance raw kline
    if (
        Array.isArray(candle) &&
        candle.length >= 5
    ) {

        const open =
            Number(
                candle[1]
            );


        const high =
            Number(
                candle[2]
            );


        const low =
            Number(
                candle[3]
            );


        const close =
            Number(
                candle[4]
            );


        if (
            Number.isFinite(open) &&
            Number.isFinite(high) &&
            Number.isFinite(low) &&
            Number.isFinite(close)
        ) {

            return {
                open,
                high,
                low,
                close
            };

        }

    }


    return null;

}


function priceToY(
    price,
    max,
    range,
    padding,
    chartHeight
) {

    return (
        padding +
        (
            (max - price) /
            range
        ) *
        chartHeight
    );

}


// ============================================================
// RESIZE
// ============================================================

window.addEventListener(
    "resize",
    () => {

        renderChart();

    }
);


// ============================================================
// FAVORITES
// ============================================================

function toggleFavorite() {

    if (!state.loggedIn) {

        openAuth();

        return;

    }


    const index =
        state.favorites.indexOf(
            state.symbol
        );


    if (index >= 0) {

        state.favorites.splice(
            index,
            1
        );

        showToast(
            "تم حذف العملة من المفضلة"
        );

    } else {

        state.favorites.push(
            state.symbol
        );

        showToast(
            "تمت إضافة العملة للمفضلة ⭐"
        );

    }


    localStorage.setItem(
        "favorites",
        JSON.stringify(
            state.favorites
        )
    );


    renderFavoriteButton();

    renderFavorites();

}


function renderFavoriteButton() {

    const btn =
        $("favoriteBtn");


    if (!btn) {
        return;
    }


    const favorite =
        state.favorites.includes(
            state.symbol
        );


    btn.textContent =
        favorite
            ? "★"
            : "☆";


    btn.classList.toggle(
        "active",
        favorite
    );

}


function renderFavorites() {

    const container =
        $("favoritesList");


    if (!container) {
        return;
    }


    const favorites =
        state.favorites;


    if (!favorites.length) {

        container.innerHTML = `
            <div>
                ⭐
            </div>

            <h3>
                لا توجد عملات مفضلة
            </h3>

            <p>
                أضف العملات للمفضلة من صفحة التحليل.
            </p>
        `;

        return;

    }


    container.className =
        "coin-list";


    container.innerHTML =
        "";


    favorites.forEach(
        symbol => {

            const button =
                document.createElement(
                    "button"
                );


            button.className =
                "coin-item";


            button.type =
                "button";


            button.innerHTML = `

                <div class="coin-name">

                    <strong>
                        ${escapeHtml(
                            symbol.replace(
                                /USDT$/i,
                                ""
                            )
                        )}
                    </strong>

                    <span>
                        ${escapeHtml(
                            symbol
                        )}
                    </span>

                </div>

            `;


            button.addEventListener(
                "click",
                () => {

                    state.symbol =
                        symbol;

                    loadData();

                    showDashboard();

                }
            );


            container.appendChild(
                button
            );

        }
    );

}


// ============================================================
// SCANNER
// ============================================================

async function runScanner() {

    const container =
        $("scannerResults");


    if (!container) {
        return;
    }


    if (!state.loggedIn) {

        openAuth();

        return;

    }


    if (
        !isPremiumPlan(
            state.user?.plan
        )
    ) {

        openPremium();

        return;

    }


    container.innerHTML = `
        <div class="loading">
            🔎 جاري فحص السوق...
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
            data.signals ||
            data.data ||
            [];


        renderScannerResults(
            Array.isArray(results)
                ? results
                : []
        );


    } catch (error) {

        container.innerHTML = `
            <div class="empty-state">
                <div>⚠️</div>
                <h3>تعذر تشغيل الماسح</h3>
                <p>
                    ${escapeHtml(
                        error.message
                    )}
                </p>
            </div>
        `;

    }

}


function renderScannerResults(results) {

    const container =
        $("scannerResults");


    if (!results.length) {

        container.innerHTML = `
            <div class="empty-state">
                <div>🔎</div>
                <h3>لا توجد فرص حالياً</h3>
                <p>
                    لم يجد الماسح عملات تستوفي الشروط الحالية.
                </p>
            </div>
        `;

        return;

    }


    container.innerHTML =
        "";


    results.forEach(item => {

        const symbol =
            item.symbol ||
            item.ticker ||
            "--";


        const signal =
            item.signal ||
            "حيادي";


        const score =
            item.score ??
            "--";


        const card =
            document.createElement(
                "button"
            );


        card.type =
            "button";


        card.className =
            "scanner-card";


        card.innerHTML = `

            <div>

                <strong>
                    ${escapeHtml(
                        symbol
                    )}
                </strong>

                <span class="${signalClass(
                    signal
                )}">
                    ${escapeHtml(
                        signal
                    )}
                </span>

            </div>

            <div>

                <span>
                    القوة
                </span>

                <strong>
                    ${escapeHtml(
                        String(score)
                    )}
                </strong>

            </div>

        `;


        card.addEventListener(
            "click",
            () => {

                state.symbol =
                    symbol;

                loadData();

                showDashboard();

            }
        );


        container.appendChild(
            card
        );

    });

}


// ============================================================
// PREMIUM
// ============================================================

function openPremiumPayment() {

    if (!state.loggedIn) {

        openAuth();

        return;

    }


    showToast(
        "اختر طريقة الدفع لإكمال الاشتراك 👑"
    );

    // واجهة الدفع فقط حالياً.
    // التحقق الآلي من Binance Pay/USDT
    // يحتاج ربط نظام الدفع في السيرفر.

}


function openPremium() {

    const modal =
        $("premiumModal");


    if (modal) {

        modal.classList.add(
            "show"
        );

    }

}


// ============================================================
// NAVIGATION
// ============================================================

function showDashboard() {

    document
        .querySelectorAll(
            ".page-section"
        )
        .forEach(
            section =>
                section.classList.remove(
                    "active"
                )
        );


    const dashboard =
        $("dashboardSection");


    if (dashboard) {

        dashboard.classList.add(
            "active"
        );

    }


    document
        .querySelectorAll(
            ".nav-item"
        )
        .forEach(
            item =>
                item.classList.remove(
                    "active"
                )
        );


    const dashboardBtn =
        document.querySelector(
            '[data-section="dashboard"]'
        );


    if (dashboardBtn) {

        dashboardBtn.classList.add(
            "active"
        );

    }

}


function showSection(name) {

    document
        .querySelectorAll(
            ".page-section"
        )
        .forEach(
            section =>
                section.classList.remove(
                    "active"
                )
        );


    const section =
        $(
            name +
            "Section"
        );


    if (section) {

        section.classList.add(
            "active"
        );

    }


    document
        .querySelectorAll(
            ".nav-item[data-section]"
        )
        .forEach(
            item => {

                item.classList.toggle(
                    "active",
                    item.dataset.section ===
                    name
                );

            }
        );


    if (name === "favorites") {

        renderFavorites();

    }


    if (name === "settings") {

        updateSettingsUI();

    }

}


// ============================================================
// APPLY INTERVAL BUTTON
// ============================================================

function applyIntervalButton(interval) {

    document
        .querySelectorAll(
            "[data-interval]"
        )
        .forEach(btn => {

            btn.classList.toggle(
                "active",
                btn.dataset.interval ===
                interval
            );

        });

}


// ============================================================
// THEME
// ============================================================

function loadLocalTheme() {

    const theme =
        localStorage.getItem(
            "theme"
        ) ||
        "dark";


    applyTheme(
        theme,
        false
    );

}


function applyTheme(
    theme,
    save = true
) {

    if (theme === "light") {

        document.body.classList.add(
            "light-theme"
        );

    } else {

        document.body.classList.remove(
            "light-theme"
        );

        theme =
            "dark";

    }


    const toggle =
        $("themeToggle");


    if (toggle) {

        toggle.textContent =
            theme === "light"
                ? "☀️"
                : "🌙";

    }


    const dark =
        $("themeDark");


    const light =
        $("themeLight");


    if (dark) {

        dark.classList.toggle(
            "active",
            theme === "dark"
        );

    }


    if (light) {

        light.classList.toggle(
            "active",
            theme === "light"
        );

    }


    if (save) {

        localStorage.setItem(
            "theme",
            theme
        );

    }

}


// ============================================================
// AUTH MODAL
// ============================================================

function openAuth() {

    const modal =
        $("authModal");


    if (!modal) {
        return;
    }


    modal.classList.add(
        "show"
    );


    showLoginForm();

}


function closeModal(id) {

    const modal =
        $(id);


    if (modal) {

        modal.classList.remove(
            "show"
        );

    }

}


function showLoginForm() {

    const login =
        $("loginForm");


    const register =
        $("registerForm");


    const title =
        $("authTitle");


    const subtitle =
        $("authSubtitle");


    if (login) {
        login.style.display =
            "flex";
    }


    if (register) {
        register.style.display =
            "none";
    }


    if (title) {
        title.textContent =
            "تسجيل الدخول";
    }


    if (subtitle) {
        subtitle.textContent =
            "ادخل لحسابك لمتابعة التحليلات.";
    }

}


// ============================================================
// TOAST
// ============================================================

function showToast(
    message,
    error = false
) {

    let toast =
        $("appToast");


    if (!toast) {

        toast =
            document.createElement(
                "div"
            );


        toast.id =
            "appToast";


        document.body.appendChild(
            toast
        );

    }


    toast.textContent =
        message;


    toast.className =
        error
            ? "app-toast error"
            : "app-toast";


    requestAnimationFrame(
        () => {

            toast.classList.add(
                "show"
            );

        }
    );


    setTimeout(
        () => {

            toast.classList.remove(
                "show"
            );

        },
        3500
    );

}


// ============================================================
// ERROR
// ============================================================

function showError(message) {

    const element =
        $("errorBox");


    if (!element) {
        return;
    }


    element.textContent =
        message;


    element.style.display =
        "block";


    element.classList.add(
        "show"
    );


    setTimeout(
        () => {

            element.classList.remove(
                "show"
            );

            element.style.display =
                "none";

        },
        7000
    );

}


// ============================================================
// STATUS
// ============================================================

function setStatus(text) {

    const element =
        $("status");


    if (element) {

        element.textContent =
            text;

    }

}


// ============================================================
// FORM ERROR
// ============================================================

function showFormError(
    element,
    message
) {

    if (!element) {
        return;
    }


    element.textContent =
        message;


    element.style.display =
        "block";

}


// ============================================================
// BUTTON LOADING
// ============================================================

function setButtonLoading(
    button,
    loading,
    text
) {

    if (!button) {
        return;
    }


    if (loading) {

        button.dataset.oldText =
            button.textContent;


        button.disabled =
            true;


        button.textContent =
            text;

    } else {

        button.disabled =
            false;


        button.textContent =
            text ||
            button.dataset.oldText ||
            "إرسال";

    }

}


// ============================================================
// SIGNAL
// ============================================================

function signalClass(signal) {

    const value =
        String(
            signal ||
            ""
        ).toLowerCase();


    if (
        value.includes(
            "شراء قوي"
        ) ||
        value.includes(
            "strong buy"
        )
    ) {

        return "strong-buy";

    }


    if (
        value === "شراء" ||
        value.includes(
            "buy"
        )
    ) {

        return "buy";

    }


    if (
        value.includes(
            "بيع قوي"
        ) ||
        value.includes(
            "strong sell"
        )
    ) {

        return "strong-sell";

    }


    if (
        value === "بيع" ||
        value.includes(
            "sell"
        )
    ) {

        return "sell";

    }


    return "neutral";

}


// ============================================================
// PLAN
// ============================================================

function isPremiumPlan(plan) {

    const value =
        String(
            plan ||
            ""
        ).toLowerCase();


    return (
        value === "premium" ||
        value === "paid" ||
        value === "pro"
    );

}


// ============================================================
// RSI
// ============================================================

function rsiStatus(rsi) {

    if (rsi === null) {
        return "--";
    }


    if (rsi >= 70) {
        return "تشبع شرائي";
    }


    if (rsi <= 30) {
        return "تشبع بيعي";
    }


    if (rsi >= 50) {
        return "إيجابي";
    }


    return "ضعيف";

}


// ============================================================
// MACD
// ============================================================

function macdStatus(macd) {

    if (macd === null) {
        return "--";
    }


    if (macd > 0) {
        return "إيجابي";
    }


    if (macd < 0) {
        return "سلبي";
    }


    return "محايد";

}


// ============================================================
// NUMBER
// ============================================================

function numberOrNull(value) {

    if (
        value === null ||
        value === undefined ||
        value === "" ||
        !Number.isFinite(
            Number(value)
        )
    ) {

        return null;

    }


    return Number(value);

}


// ============================================================
// TEXT
// ============================================================

function setText(
    id,
    value
) {

    const element =
        $(id);


    if (element) {

        element.textContent =
            value ??
            "--";

    }

}


// ============================================================
// FORMAT PRICE
// ============================================================

function formatPrice(value) {

    if (
        value === null ||
        value === undefined ||
        value === "" ||
        !Number.isFinite(
            Number(value)
        )
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


// ============================================================
// FORMAT PERCENT
// ============================================================

function formatPercent(value) {

    if (
        value === null ||
        value === undefined ||
        !Number.isFinite(
            Number(value)
        )
    ) {

        return "--";

    }


    const number =
        Number(value);


    return (
        number >= 0
            ? "+"
            : ""
    ) +
    number.toFixed(2) +
    "%";

}


// ============================================================
// FORMAT VOLUME
// ============================================================

function formatVolume(value) {

    if (
        value === null ||
        value === undefined ||
        !Number.isFinite(
            Number(value)
        )
    ) {

        return "--";

    }


    const n =
        Number(value);


    if (n >= 1000000000) {

        return (
            n / 1000000000
        ).toFixed(2) +
        "B";

    }


    if (n >= 1000000) {

        return (
            n / 1000000
        ).toFixed(2) +
        "M";

    }


    if (n >= 1000) {

        return (
            n / 1000
        ).toFixed(2) +
        "K";

    }


    return n.toFixed(2);

}


// ============================================================
// ESCAPE HTML
// ============================================================

function escapeHtml(value) {

    return String(value)
        .replace(
            /&/g,
            "&amp;"
        )
        .replace(
            /</g,
            "&lt;"
        )
        .replace(
            />/g,
            "&gt;"
        )
        .replace(
            /"/g,
            "&quot;"
        )
        .replace(
            /'/g,
            "&#039;"
        );

}


// ============================================================
// INITIAL UI
// ============================================================

renderFavoriteButton();

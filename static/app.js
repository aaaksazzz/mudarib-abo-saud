// ============================================================
// تحليل العملات الرقمية - Frontend PRO
// ============================================================

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
    favorites: JSON.parse(localStorage.getItem("favorites") || "[]")
};

const $ = (id) => document.getElementById(id);


// ============================================================
// تشغيل الموقع
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    init();
});


async function init() {

    bindEvents();

    loadLocalTheme();

    await loadUser();

    await loadSettings();

    await loadMarkets();

    await loadData();

    startAutoRefresh();
}


// ============================================================
// الأحداث
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

        btn.addEventListener("click", () => {

            state.interval = btn.dataset.interval;

            state.settings.interval = state.interval;

            document
                .querySelectorAll("[data-interval]")
                .forEach(x => x.classList.remove("active"));

            btn.classList.add("active");

            loadData();
        });

    });


    // تحديث
    const refresh = $("refreshBtn");

    if (refresh) {
        refresh.addEventListener("click", async () => {

            refresh.classList.add("loading");

            await loadData();

            refresh.classList.remove("loading");
        });
    }


    // القائمة الجانبية
    const menuBtn = $("menuBtn");
    const sidebar = $("sidebar");

    if (menuBtn && sidebar) {

        menuBtn.addEventListener("click", () => {
            sidebar.classList.toggle("open");
        });
    }


    // إغلاق القائمة عند الضغط على المحتوى
    document.addEventListener("click", (event) => {

        const sidebar = $("sidebar");
        const menuBtn = $("menuBtn");

        if (!sidebar || !menuBtn) return;

        if (
            sidebar.classList.contains("open") &&
            !sidebar.contains(event.target) &&
            !menuBtn.contains(event.target)
        ) {
            sidebar.classList.remove("open");
        }

    });


    // تسجيل الدخول
    const loginForm = $("loginForm");

    if (loginForm) {
        loginForm.addEventListener("submit", handleLogin);
    }


    // إنشاء الحساب
    const registerForm = $("registerForm");

    if (registerForm) {
        registerForm.addEventListener(
            "submit",
            handleRegister
        );
    }


    // تسجيل الخروج
    const logoutBtn = $("logoutBtn");

    if (logoutBtn) {
        logoutBtn.addEventListener(
            "click",
            handleLogout
        );
    }


    // دخول
    const loginBtn = $("loginBtn");

    if (loginBtn) {
        loginBtn.addEventListener(
            "click",
            () => openModal("authModal")
        );
    }


    // إنشاء حساب
    const createAccountBtn = $("createAccountBtn");

    if (createAccountBtn) {
        createAccountBtn.addEventListener(
            "click",
            () => {
                openModal("authModal");
                showRegister();
            }
        );
    }


    // زر التحويل لإنشاء حساب
    const showRegisterBtn = $("showRegisterBtn");

    if (showRegisterBtn) {
        showRegisterBtn.addEventListener(
            "click",
            showRegister
        );
    }


    // زر العودة لتسجيل الدخول
    const showLoginBtn = $("showLoginBtn");

    if (showLoginBtn) {
        showLoginBtn.addEventListener(
            "click",
            showLogin
        );
    }


    // الوضع الداكن
    const themeDark = $("themeDark");

    if (themeDark) {
        themeDark.addEventListener(
            "click",
            () => setTheme("dark")
        );
    }


    // الوضع الفاتح
    const themeLight = $("themeLight");

    if (themeLight) {
        themeLight.addEventListener(
            "click",
            () => setTheme("light")
        );
    }


    // حفظ الإعدادات
    const saveSettingsBtn =
        $("saveSettingsBtn");

    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener(
            "click",
            saveSettings
        );
    }


    // زر Premium
    document
        .querySelectorAll(
            "[data-premium], .premium-btn, #premiumBtn"
        )
        .forEach(btn => {

            btn.addEventListener(
                "click",
                openPremium
            );

        });


    // إغلاق النوافذ
    document
        .querySelectorAll(
            "[data-close-modal]"
        )
        .forEach(btn => {

            btn.addEventListener(
                "click",
                () => {
                    closeModal(
                        btn.dataset.closeModal
                    );
                }
            );

        });


    // زر الماسح
    const scanBtn = $("scanBtn");

    if (scanBtn) {
        scanBtn.addEventListener(
            "click",
            runScanner
        );
    }


    // المفضلة
    const favoriteBtn =
        $("favoriteBtn");

    if (favoriteBtn) {
        favoriteBtn.addEventListener(
            "click",
            toggleFavorite
        );
    }
}


// ============================================================
// API
// ============================================================

async function api(url, options = {}) {

    const response =
        await fetch(url, {
            cache: "no-store",
            credentials: "same-origin",
            ...options
        });

    let data = {};

    try {
        data = await response.json();
    } catch {
        throw new Error(
            "استجابة غير صالحة من السيرفر"
        );
    }

    if (
        !response.ok ||
        data.ok === false
    ) {

        throw new Error(
            data.message ||
            "حدث خطأ في الاتصال"
        );
    }

    return data;
}


// ============================================================
// المستخدم
// ============================================================

async function loadUser() {

    try {

        const data =
            await api("/api/auth/me");

        state.user =
            data.user || null;

        updateUserUI();

    } catch {

        state.user = null;

        updateUserUI();
    }
}


function updateUserUI() {

    const userArea =
        $("userArea");

    const usernameDisplay =
        $("usernameDisplay");

    const planDisplay =
        $("planDisplay");

    const loginBtn =
        $("loginBtn");

    const logoutBtn =
        $("logoutBtn");

    if (state.user) {

        if (userArea) {
            userArea.classList.add("logged-in");
        }

        if (usernameDisplay) {
            usernameDisplay.textContent =
                state.user.username || "";
        }

        if (planDisplay) {

            planDisplay.textContent =
                state.user.plan === "premium"
                    ? "Premium 👑"
                    : "مجاني";
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
            usernameDisplay.textContent = "";
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


// ============================================================
// تسجيل الدخول
// ============================================================

async function handleLogin(event) {

    event.preventDefault();

    const username =
        $("loginUsername")?.value.trim();

    const password =
        $("loginPassword")?.value;

    const error =
        $("loginError");

    if (!username || !password) {

        showFormError(
            error,
            "اكتب اسم المستخدم وكلمة المرور"
        );

        return;
    }

    try {

        setFormLoading(
            event.target,
            true
        );

        const data =
            await api(
                "/api/auth/login",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        username,
                        password
                    })
                }
            );

        state.user =
            data.user || null;

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

        setFormLoading(
            event.target,
            false
        );
    }
}


// ============================================================
// إنشاء حساب
// ============================================================

async function handleRegister(event) {

    event.preventDefault();

    const username =
        $("registerUsername")?.value.trim();

    const email =
        $("registerEmail")?.value.trim();

    const password =
        $("registerPassword")?.value;

    const password2 =
        $("registerPassword2")?.value;

    const error =
        $("registerError");


    if (
        !username ||
        !email ||
        !password ||
        !password2
    ) {

        showFormError(
            error,
            "عبّ جميع البيانات"
        );

        return;
    }


    if (password !== password2) {

        showFormError(
            error,
            "كلمتا المرور غير متطابقتين"
        );

        return;
    }


    if (password.length < 6) {

        showFormError(
            error,
            "كلمة المرور لازم تكون 6 أحرف أو أكثر"
        );

        return;
    }


    try {

        setFormLoading(
            event.target,
            true
        );

        const data =
            await api(
                "/api/auth/register",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        username,
                        email,
                        password
                    })
                }
            );


        state.user =
            data.user || null;

        updateUserUI();

        closeModal("authModal");

        showToast(
            "تم إنشاء الحساب بنجاح 🎉"
        );

        await loadSettings();

    } catch (err) {

        showFormError(
            error,
            err.message
        );

    } finally {

        setFormLoading(
            event.target,
            false
        );
    }
}


// ============================================================
// تسجيل الخروج
// ============================================================

async function handleLogout() {

    try {

        await api(
            "/api/auth/logout",
            {
                method: "POST"
            }
        );

    } catch {}

    state.user = null;

    updateUserUI();

    showToast(
        "تم تسجيل الخروج"
    );
}


// ============================================================
// الإعدادات
// ============================================================

async function loadSettings() {

    try {

        const data =
            await api("/api/settings");

        if (data.settings) {

            state.settings = {
                ...state.settings,
                ...data.settings
            };
        }

    } catch {}

    state.interval =
        state.settings.interval ||
        "15m";

    updateSettingsUI();
}


function updateSettingsUI() {

    const interval =
        $("intervalSetting");

    const refresh =
        $("refreshSetting");

    const notifications =
        $("notificationsSetting");


    if (interval) {

        interval.value =
            state.settings.interval ||
            "15m";
    }


    if (refresh) {

        refresh.value =
            String(
                state.settings.refresh_seconds ||
                30
            );
    }


    if (notifications) {

        notifications.checked =
            Boolean(
                state.settings.notifications
            );
    }


    document
        .querySelectorAll(
            "[data-interval]"
        )
        .forEach(btn => {

            btn.classList.toggle(
                "active",
                btn.dataset.interval ===
                state.interval
            );

        });
}


async function saveSettings() {

    if (!state.user) {

        openModal("authModal");

        showLogin();

        return;
    }


    const interval =
        $("intervalSetting")?.value ||
        "15m";

    const refreshSeconds =
        Number(
            $("refreshSetting")?.value ||
            30
        );

    const notifications =
        Boolean(
            $("notificationsSetting")?.checked
        );


    try {

        await api(
            "/api/settings",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json"
                },
                body: JSON.stringify({
                    theme:
                        state.settings.theme,
                    interval,
                    refresh_seconds:
                        refreshSeconds,
                    notifications
                })
            }
        );


        state.settings.interval =
            interval;

        state.settings.refresh_seconds =
            refreshSeconds;

        state.settings.notifications =
            notifications;

        state.interval =
            interval;


        showToast(
            "تم حفظ الإعدادات ✅"
        );

        await loadData();

    } catch (err) {

        showToast(
            err.message
        );
    }
}


// ============================================================
// الثيم
// ============================================================

function loadLocalTheme() {

    const saved =
        localStorage.getItem(
            "theme"
        ) || "dark";

    setTheme(
        saved,
        false
    );
}


async function setTheme(
    theme,
    save = true
) {

    state.settings.theme =
        theme;


    document.documentElement
        .setAttribute(
            "data-theme",
            theme
        );


    document.body.classList.toggle(
        "light-theme",
        theme === "light"
    );


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


    localStorage.setItem(
        "theme",
        theme
    );


    if (
        save &&
        state.user
    ) {

        try {

            await api(
                "/api/settings",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json"
                    },
                    body: JSON.stringify({
                        theme,
                        interval:
                            state.settings.interval,
                        refresh_seconds:
                            state.settings.refresh_seconds,
                        notifications:
                            state.settings.notifications
                    })
                }
            );

        } catch {}
    }
}


// ============================================================
// العملات
// ============================================================

async function loadMarkets() {

    try {

        const data =
            await api(
                "/api/binance/markets"
            );

        state.markets =
            data.symbols || [];


        renderCoins("");


        const count =
            $("coinCount");


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

    const container =
        $("coinList");

    if (!container) return;


    const query =
        search.trim().toUpperCase();


    let coins =
        state.markets;


    if (query) {

        coins =
            coins.filter(
                coin =>
                    coin.symbol
                        .includes(query)
            );
    }


    coins =
        coins.slice(0, 100);


    container.innerHTML = "";


    coins.forEach(coin => {

        const button =
            document.createElement(
                "button"
            );


        button.className =
            "coin-item " +
            (
                coin.symbol ===
                state.symbol
                    ? "selected"
                    : ""
            );


        const symbol =
            coin.symbol.replace(
                "USDT",
                ""
            );


        const price =
            state.prices[
                coin.symbol
            ];


        const priceText =
            price
                ? formatPrice(
                    price.price
                )
                : "--";


        const change =
            price
                ? price.change24h
                : 0;


        const favorite =
            state.favorites.includes(
                coin.symbol
            );


        button.innerHTML = `

            <div class="coin-name">

                <strong>
                    ${favorite ? "⭐ " : ""}
                    ${symbol}
                </strong>

                <span>
                    ${coin.symbol}
                </span>

            </div>


            <div class="coin-price">

                <strong>
                    ${priceText}
                </strong>

                <span class="${
                    change >= 0
                        ? "positive"
                        : "negative"
                }">

                    ${formatPercent(change)}

                </span>

            </div>

        `;


        button.addEventListener(
            "click",
            () => {

                state.symbol =
                    coin.symbol;

                document
                    .querySelectorAll(
                        ".coin-item"
                    )
                    .forEach(
                        x =>
                            x.classList
                                .remove(
                                    "selected"
                                )
                    );


                button.classList.add(
                    "selected"
                );


                loadData();
            }
        );


        container.appendChild(
            button
        );
    });
}


// ============================================================
// البيانات
// ============================================================

async function loadData() {

    if (state.loading) return;


    state.loading = true;


    setStatus(
        "جاري تحديث البيانات..."
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


        (
            prices.prices || []
        ).forEach(item => {

            state.prices[
                item.symbol
            ] = item;

        });


        state.analysis =
            analysis.analysis;


        state.candles =
            analysis.candles || [];


        renderCoins(
            $("coinSearch")
                ? $("coinSearch").value
                : ""
        );


        renderMarketHeader();

        renderAnalysis();

        renderChart();

        updateFavoriteButton();


        setStatus(
            "آخر تحديث: " +
            new Date()
                .toLocaleTimeString(
                    "ar-SA"
                )
        );


    } catch (error) {

        console.error(error);


        showError(
            "تعذر تحديث البيانات: " +
            error.message
        );


        setStatus(
            "تعذر التحديث"
        );


    } finally {

        state.loading =
            false;
    }
}


// ============================================================
// رأس العملة
// ============================================================

function renderMarketHeader() {

    const item =
        state.prices[
            state.symbol
        ];


    const analysis =
        state.analysis;


    const symbolName =
        state.symbol.replace(
            "USDT",
            ""
        );


    setText(
        "symbolName",
        symbolName +
        " / USDT"
    );


    setText(
        "currentPrice",
        analysis
            ? formatPrice(
                analysis.price
            )
            : "--"
    );


    if (!item) return;


    const change =
        item.change24h;


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
            item.high24h
        )
    );


    setText(
        "low24h",
        formatPrice(
            item.low24h
        )
    );


    setText(
        "volume24h",
        formatVolume(
            item.volume
        )
    );
}


// ============================================================
// التحليل
// ============================================================

function renderAnalysis() {

    const a =
        state.analysis;


    if (!a) return;


    const signal =
        $("signal");


    if (signal) {

        signal.textContent =
            a.signal || "حيادي";


        signal.className =
            "signal " +
            signalClass(
                a.signal
            );
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
            ? "1 : " +
              Number(
                  a.rr
              ).toFixed(2)
            : "--"
    );


    setText(
        "rsi",
        a.rsi !== null &&
        a.rsi !== undefined
            ? Number(
                a.rsi
              ).toFixed(2)
            : "--"
    );


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


    setText(
        "macd",
        a.macd !== null &&
        a.macd !== undefined
            ? Number(
                a.macd
              ).toFixed(6)
            : "--"
    );


    setText(
        "atr",
        formatPrice(
            a.atr
        )
    );


    setText(
        "support",
        formatPrice(
            a.support
        )
    );


    setText(
        "resistance",
        formatPrice(
            a.resistance
        )
    );


    setText(
        "volumeRatio",
        a.volumeRatio
            ? Number(
                a.volumeRatio
              ).toFixed(2) + "x"
            : "--"
    );


    setText(
        "trend",
        a.trend ||
        a.direction ||
        "--"
    );


    renderReasons(
        a.reasons || []
    );
}


// ============================================================
// أسباب التحليل
// ============================================================

function renderReasons(
    reasons
) {

    const container =
        $("reasons");


    if (!container) return;


    container.innerHTML = "";


    if (!reasons.length) {

        container.innerHTML =
            "<div class='empty'>لا توجد أسباب كافية</div>";

        return;
    }


    reasons.forEach(
        reason => {

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
        }
    );
}


// ============================================================
// الشارت
// ============================================================

function renderChart() {

    const canvas =
        $("priceChart");


    if (
        !canvas ||
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


    if (
        !rect.width ||
        !rect.height
    ) {
        return;
    }


    const dpr =
        window.devicePixelRatio ||
        1;


    canvas.width =
        rect.width * dpr;


    canvas.height =
        rect.height * dpr;


    ctx.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );


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
        state.candles.slice(
            -80
        );


    const highs =
        candles.map(
            x => Number(x.high)
        );


    const lows =
        candles.map(
            x => Number(x.low)
        );


    const max =
        Math.max(...highs);


    const min =
        Math.min(...lows);


    const range =
        max - min || 1;


    const padding =
        20;


    const chartWidth =
        width -
        padding * 2;


    const chartHeight =
        height -
        padding * 2;


    // الشبكة
    ctx.lineWidth = 1;


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


    // الشموع
    const candleSlot =
        chartWidth /
        candles.length;


    const candleWidth =
        Math.max(
            3,
            candleSlot * 0.65
        );


    candles.forEach(
        (candle, index) => {

            const open =
                Number(
                    candle.open
                );


            const close =
                Number(
                    candle.close
                );


            const high =
                Number(
                    candle.high
                );


            const low =
                Number(
                    candle.low
                );


            const x =
                padding +
                index *
                candleSlot +
                candleSlot / 2;


            const yHigh =
                padding +
                (
                    max - high
                ) /
                range *
                chartHeight;


            const yLow =
                padding +
                (
                    max - low
                ) /
                range *
                chartHeight;


            const yOpen =
                padding +
                (
                    max - open
                ) /
                range *
                chartHeight;


            const yClose =
                padding +
                (
                    max - close
                ) /
                range *
                chartHeight;


            const bullish =
                close >= open;


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
                        yClose -
                        yOpen
                    )
                );


            ctx.fillRect(
                x -
                    candleWidth / 2,
                bodyTop,
                candleWidth,
                bodyHeight
            );
        }
    );


    // السعر الحالي
    const price =
        Number(
            candles[
                candles.length - 1
            ].close
        );


    const currentY =
        padding +
        (
            max - price
        ) /
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
        Math.max(
            padding,
            width - 90
        ),
        currentY - 6
    );
}


// ============================================================
// المفضلة
// ============================================================

function toggleFavorite() {

    const index =
        state.favorites.indexOf(
            state.symbol
        );


    if (index === -1) {

        state.favorites.push(
            state.symbol
        );

        showToast(
            "تمت الإضافة للمفضلة ⭐"
        );

    } else {

        state.favorites.splice(
            index,
            1
        );

        showToast(
            "تمت إزالة العملة من المفضلة"
        );
    }


    localStorage.setItem(
        "favorites",
        JSON.stringify(
            state.favorites
        )
    );


    updateFavoriteButton();

    renderCoins(
        $("coinSearch")
            ? $("coinSearch").value
            : ""
    );
}


function updateFavoriteButton() {

    const btn =
        $("favoriteBtn");


    if (!btn) return;


    const active =
        state.favorites.includes(
            state.symbol
        );


    btn.textContent =
        active
            ? "★"
            : "☆";


    btn.classList.toggle(
        "active",
        active
    );
}


// ============================================================
// ماسح الفرص
// ============================================================

async function runScanner() {

    const container =
        $("scannerResults");


    const scanBtn =
        $("scanBtn");


    if (scanBtn) {

        scanBtn.disabled =
            true;

        scanBtn.textContent =
            "⏳ جاري الفحص...";
    }


    if (container) {

        container.innerHTML =
            "<div class='empty'>جاري فحص السوق...</div>";
    }


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


        if (!results.length) {

            if (container) {

                container.innerHTML =
                    "<div class='empty'>ما لقى فرص حسب شروط التحليل الحالية.</div>";
            }

            return;
        }


        if (container) {

            container.innerHTML = "";


            results
                .slice(0, 50)
                .forEach(
                    item => {

                        const row =
                            document.createElement(
                                "button"
                            );


                        row.className =
                            "scan-item";


                        const symbol =
                            item.symbol ||
                            "--";


                        const signal =
                            item.signal ||
                            "حيادي";


                        const score =
                            item.score ??
                            "--";


                        row.innerHTML = `

                            <strong>
                                ${escapeHtml(symbol)}
                            </strong>

                            <span class="${signalClass(signal)}">
                                ${escapeHtml(signal)}
                            </span>

                            <small>
                                ${score}/10
                            </small>

                        `;


                        row.addEventListener(
                            "click",
                            () => {

                                state.symbol =
                                    symbol;

                                loadData();

                                window.scrollTo({
                                    top: 0,
                                    behavior: "smooth"
                                });
                            }
                        );


                        container.appendChild(
                            row
                        );
                    }
                );
        }


        showToast(
            `تم فحص السوق وظهرت ${results.length} فرصة`
        );


    } catch (err) {

        if (container) {

            container.innerHTML =
                `
                <div class="empty">
                    تعذر تشغيل الماسح:
                    ${escapeHtml(
                        err.message
                    )}
                </div>
                `;
        }


        showToast(
            err.message
        );


    } finally {

        if (scanBtn) {

            scanBtn.disabled =
                false;

            scanBtn.textContent =
                "🔎 بدء الفحص";
        }
    }
}


// ============================================================
// النوافذ
// ============================================================

function openModal(id) {

    const modal =
        $(id);


    if (!modal) return;


    modal.classList.add(
        "open"
    );


    modal.style.display =
        "flex";
}


function closeModal(id) {

    const modal =
        $(id);


    if (!modal) return;


    modal.classList.remove(
        "open"
    );


    setTimeout(
        () => {
            if (
                !modal.classList.contains(
                    "open"
                )
            ) {
                modal.style.display =
                    "";
            }
        },
        200
    );
}


function showLogin() {

    const login =
        $("loginForm");


    const register =
        $("registerForm");


    if (login) {
        login.style.display =
            "";
    }


    if (register) {
        register.style.display =
            "none";
    }
}


function showRegister() {

    const login =
        $("loginForm");


    const register =
        $("registerForm");


    if (login) {
        login.style.display =
            "none";
    }


    if (register) {
        register.style.display =
            "";
    }
}


// ============================================================
// Premium
// ============================================================

function openPremium() {

    if (
        state.user &&
        state.user.plan === "premium"
    ) {

        showToast(
            "حسابك Premium بالفعل 👑"
        );

        return;
    }


    openModal(
        "premiumModal"
    );
}


// ============================================================
// التحديث التلقائي
// ============================================================

let refreshTimer = null;


function startAutoRefresh() {

    if (refreshTimer) {
        clearInterval(
            refreshTimer
        );
    }


    const seconds =
        Number(
            state.settings.refresh_seconds
        ) || 30;


    refreshTimer =
        setInterval(
            () => {

                if (
                    document.visibilityState ===
                    "visible"
                ) {
                    loadData();
                }

            },
            seconds * 1000
        );
}


// ============================================================
// Resize
// ============================================================

window.addEventListener(
    "resize",
    () => {
        renderChart();
    }
);


// ============================================================
// Helpers
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
        number >= 0
            ? "+"
            : ""
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


function signalClass(
    signal
) {

    if (
        signal ===
        "شراء قوي"
    ) {
        return "strong-buy";
    }


    if (
        signal ===
        "شراء"
    ) {
        return "buy";
    }


    if (
        signal ===
        "بيع قوي"
    ) {
        return "strong-sell";
    }


    if (
        signal ===
        "بيع"
    ) {
        return "sell";
    }


    return "neutral";
}


function setStatus(
    text
) {

    const element =
        $("status");


    if (element) {
        element.textContent =
            text;
    }
}


function showError(
    message
) {

    const element =
        $("errorBox");


    if (!element) return;


    element.textContent =
        message;


    element.classList.add(
        "show"
    );


    setTimeout(
        () => {

            element.classList.remove(
                "show"
            );

        },
        6000
    );
}


function showToast(
    message
) {

    let toast =
        $("siteToast");


    if (!toast) {

        toast =
            document.createElement(
                "div"
            );


        toast.id =
            "siteToast";


        toast.style.cssText = `
            position:fixed;
            bottom:25px;
            right:25px;
            z-index:99999;
            background:#111827;
            color:#fff;
            padding:13px 18px;
            border-radius:12px;
            box-shadow:0 10px 30px rgba(0,0,0,.25);
            font-size:14px;
            max-width:90%;
            transition:.25s;
        `;


        document.body.appendChild(
            toast
        );
    }


    toast.textContent =
        message;


    toast.style.opacity =
        "1";


    clearTimeout(
        toast._timer
    );


    toast._timer =
        setTimeout(
            () => {

                toast.style.opacity =
                    "0";

            },
            3000
        );
}


function showFormError(
    element,
    message
) {

    if (!element) return;


    element.textContent =
        message;


    element.classList.add(
        "show"
    );
}


function setFormLoading(
    form,
    loading
) {

    if (!form) return;


    const buttons =
        form.querySelectorAll(
            "button[type='submit']"
        );


    buttons.forEach(
        btn => {

            btn.disabled =
                loading;

            if (loading) {

                btn.dataset.oldText =
                    btn.textContent;

                btn.textContent =
                    "⏳ جاري التنفيذ...";
            } else {

                btn.textContent =
                    btn.dataset.oldText ||
                    btn.textContent;
            }
        }
    );
}


function escapeHtml(
    text
) {

    return String(text)
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
// إغلاق النوافذ بالضغط خارجها
// ============================================================

document.addEventListener(
    "click",
    event => {

        if (
            event.target.classList &&
            event.target.classList.contains(
                "modal"
            )
        ) {

            event.target.classList.remove(
                "open"
            );

            event.target.style.display =
                "";
        }
    }
);


// ============================================================
// ESC
// ============================================================

document.addEventListener(
    "keydown",
    event => {

        if (
            event.key !==
            "Escape"
        ) {
            return;
        }


        document
            .querySelectorAll(
                ".modal.open"
            )
            .forEach(
                modal => {

                    modal.classList.remove(
                        "open"
                    );

                    modal.style.display =
                        "";
                }
            );
    }
);

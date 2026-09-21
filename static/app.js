"use strict";

/* =========================================================
   STATE
========================================================= */

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

    favorites: JSON.parse(
        localStorage.getItem("favorites") || "[]"
    ),

    refreshTimer: null
};


/* =========================================================
   INIT
========================================================= */

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


/* =========================================================
   EVENTS
========================================================= */

function bindEvents() {

    /* SEARCH */

    const search = document.getElementById("coinSearch");

    if (search) {
        search.addEventListener("input", function () {
            renderCoins(search.value);
        });
    }


    /* REFRESH */

    const refreshBtn =
        document.getElementById("refreshBtn");

    if (refreshBtn) {

        refreshBtn.addEventListener(
            "click",
            async function () {

                if (state.loading) return;

                await loadPrices();
                await loadData();
            }
        );
    }


    /* TIMEFRAMES */

    document
        .querySelectorAll("[data-interval]")
        .forEach(function (button) {

            button.addEventListener(
                "click",
                async function () {

                    const interval =
                        button.dataset.interval;

                    if (!interval) return;

                    state.interval = interval;

                    state.settings.interval =
                        interval;

                    document
                        .querySelectorAll("[data-interval]")
                        .forEach(function (btn) {
                            btn.classList.remove("active");
                        });

                    button.classList.add("active");

                    updateElement(
                        "chartTimeframe",
                        getIntervalName(interval)
                    );

                    await loadData();
                }
            );
        });


    /* LOGIN */

    const loginBtn =
        document.getElementById("loginBtn");

    if (loginBtn) {

        loginBtn.addEventListener(
            "click",
            function () {

                showLogin();
            }
        );
    }


    /* CLOSE LOGIN */

    const closeAuth =
        document.getElementById("closeAuth");

    if (closeAuth) {

        closeAuth.addEventListener(
            "click",
            function () {

                closeModal("authModal");
            }
        );
    }


    /* REGISTER */

    const showRegisterBtn =
        document.getElementById(
            "showRegisterBtn"
        );

    if (showRegisterBtn) {

        showRegisterBtn.addEventListener(
            "click",
            function () {

                showRegister();
            }
        );
    }


    /* BACK LOGIN */

    const showLoginBtn =
        document.getElementById(
            "showLoginBtn"
        );

    if (showLoginBtn) {

        showLoginBtn.addEventListener(
            "click",
            function () {

                showLogin();
            }
        );
    }


    /* LOGIN FORM */

    const loginForm =
        document.getElementById("loginForm");

    if (loginForm) {

        loginForm.addEventListener(
            "submit",
            loginUser
        );
    }


    /* REGISTER FORM */

    const registerForm =
        document.getElementById(
            "registerForm"
        );

    if (registerForm) {

        registerForm.addEventListener(
            "submit",
            registerUser
        );
    }


    /* LOGOUT */

    const logoutBtn =
        document.getElementById("logoutBtn");

    if (logoutBtn) {

        logoutBtn.addEventListener(
            "click",
            logout
        );
    }


    /* THEME TOP BUTTON */

    const themeToggle =
        document.getElementById(
            "themeToggle"
        );

    if (themeToggle) {

        themeToggle.addEventListener(
            "click",
            function () {

                const light =
                    document.body.classList.contains(
                        "light-theme"
                    );

                applyTheme(
                    light ? "dark" : "light"
                );
            }
        );
    }


    /* THEME SETTINGS */

    const themeDark =
        document.getElementById("themeDark");

    const themeLight =
        document.getElementById("themeLight");


    if (themeDark) {

        themeDark.addEventListener(
            "click",
            function () {

                applyTheme("dark");
            }
        );
    }


    if (themeLight) {

        themeLight.addEventListener(
            "click",
            function () {

                applyTheme("light");
            }
        );
    }


    /* SETTINGS */

    const saveSettingsBtn =
        document.getElementById(
            "saveSettingsBtn"
        );

    if (saveSettingsBtn) {

        saveSettingsBtn.addEventListener(
            "click",
            saveSettings
        );
    }


    /* PREMIUM BUTTONS */

    const premiumBtn =
        document.getElementById(
            "premiumBtn"
        );

    const premiumOpenBtn =
        document.getElementById(
            "premiumOpenBtn"
        );


    if (premiumBtn) {

        premiumBtn.addEventListener(
            "click",
            function () {

                openPremium();
            }
        );
    }


    if (premiumOpenBtn) {

        premiumOpenBtn.addEventListener(
            "click",
            function () {

                openPremium();
            }
        );
    }


    /* CLOSE PREMIUM */

    const closePremium =
        document.getElementById(
            "closePremium"
        );

    if (closePremium) {

        closePremium.addEventListener(
            "click",
            function () {

                closeModal("premiumModal");
            }
        );
    }


    /* SUBSCRIBE */

    const subscribeBtn =
        document.getElementById(
            "subscribeBtn"
        );

    if (subscribeBtn) {

        subscribeBtn.addEventListener(
            "click",
            function () {

                startSubscription();
            }
        );
    }


    /* FAVORITE */

    const favoriteBtn =
        document.getElementById(
            "favoriteBtn"
        );

    if (favoriteBtn) {

        favoriteBtn.addEventListener(
            "click",
            toggleFavorite
        );
    }


    /* SCANNER */

    const runScannerBtn =
        document.getElementById(
            "runScannerBtn"
        );

    if (runScannerBtn) {

        runScannerBtn.addEventListener(
            "click",
            runScanner
        );
    }


    /* SIDEBAR */

    setupSidebar();

    /* NAVIGATION */

    setupNavigation();

    /* MODALS */

    setupModalOutsideClick();

    /* ESC */

    document.addEventListener(
        "keydown",
        function (event) {

            if (event.key === "Escape") {

                document
                    .querySelectorAll(".modal.open")
                    .forEach(function (modal) {

                        closeModal(modal.id);
                    });
            }
        }
    );


    /* RESIZE */

    window.addEventListener(
        "resize",
        drawChart
    );
}


/* =========================================================
   SIDEBAR
========================================================= */

function setupSidebar() {

    const menuBtn =
        document.getElementById("menuBtn");

    const closeSidebar =
        document.getElementById(
            "closeSidebar"
        );

    const overlay =
        document.getElementById(
            "sidebarOverlay"
        );


    if (menuBtn) {

        menuBtn.addEventListener(
            "click",
            openSidebar
        );
    }


    if (closeSidebar) {

        closeSidebar.addEventListener(
            "click",
            closeSide
        );
    }


    if (overlay) {

        overlay.addEventListener(
            "click",
            closeSide
        );
    }
}


function openSidebar() {

    const sidebar =
        document.getElementById("sidebar");

    const overlay =
        document.getElementById(
            "sidebarOverlay"
        );


    if (sidebar) {
        sidebar.classList.add("open");
    }

    if (overlay) {
        overlay.classList.add("open");
    }
}


function closeSide() {

    const sidebar =
        document.getElementById("sidebar");

    const overlay =
        document.getElementById(
            "sidebarOverlay"
        );


    if (sidebar) {
        sidebar.classList.remove("open");
    }

    if (overlay) {
        overlay.classList.remove("open");
    }
}


/* =========================================================
   NAVIGATION
========================================================= */

function setupNavigation() {

    document
        .querySelectorAll(
            ".nav-item[data-section]"
        )
        .forEach(function (button) {

            button.addEventListener(
                "click",
                function () {

                    const name =
                        button.dataset.section;

                    document
                        .querySelectorAll(
                            ".nav-item"
                        )
                        .forEach(function (item) {

                            item.classList.remove(
                                "active"
                            );
                        });


                    button.classList.add(
                        "active"
                    );


                    document
                        .querySelectorAll(
                            ".page-section"
                        )
                        .forEach(function (section) {

                            section.classList.remove(
                                "active"
                            );
                        });


                    const section =
                        document.getElementById(
                            name + "Section"
                        );


                    if (section) {

                        section.classList.add(
                            "active"
                        );
                    }


                    closeSide();
                }
            );
        });
}


/* =========================================================
   MODALS
========================================================= */

function openModal(id) {

    const modal =
        document.getElementById(id);

    if (!modal) return;

    modal.classList.add("open");
    modal.classList.add("show");

    modal.style.display = "flex";
}


function closeModal(id) {

    const modal =
        document.getElementById(id);

    if (!modal) return;

    modal.classList.remove("open");
    modal.classList.remove("show");

    modal.style.display = "none";
}


function setupModalOutsideClick() {

    document
        .querySelectorAll(".modal")
        .forEach(function (modal) {

            modal.addEventListener(
                "click",
                function (event) {

                    if (
                        event.target === modal
                    ) {

                        closeModal(modal.id);
                    }
                }
            );
        });
}


/* =========================================================
   LOGIN / REGISTER
========================================================= */

function showLogin() {

    const loginForm =
        document.getElementById(
            "loginForm"
        );

    const registerForm =
        document.getElementById(
            "registerForm"
        );


    if (loginForm) {
        loginForm.style.display = "flex";
    }

    if (registerForm) {
        registerForm.style.display = "none";
    }


    updateElement(
        "authTitle",
        "تسجيل الدخول"
    );


    updateElement(
        "authSubtitle",
        "ادخل لحسابك لمتابعة التحليلات."
    );


    clearAuthErrors();

    openModal("authModal");
}


function showRegister() {

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
        registerForm.style.display = "flex";
    }


    updateElement(
        "authTitle",
        "إنشاء حساب"
    );


    updateElement(
        "authSubtitle",
        "أنشئ حسابك وابدأ استخدام المنصة."
    );


    clearAuthErrors();

    openModal("authModal");
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


async function loginUser(event) {

    event.preventDefault();


    const username =
        document.getElementById(
            "loginUsername"
        )?.value.trim();


    const password =
        document.getElementById(
            "loginPassword"
        )?.value;


    if (!username || !password) {

        showLoginError(
            "اكتب اسم المستخدم وكلمة المرور"
        );

        return;
    }


    try {

        const data =
            await api(
                "/api/auth/login",
                {
                    method: "POST",
                    body: JSON.stringify({
                        username,
                        password
                    })
                }
            );


        state.user =
            data.user || {
                username:
                    data.username ||
                    username,

                plan:
                    data.plan ||
                    "مجاني"
            };


        updateUserUI();

        closeModal("authModal");


        showToast(
            "تم تسجيل الدخول بنجاح ✅"
        );


        /*
           بعد تسجيل الدخول:
           يظهر زر الاشتراك
        */
        showSubscriptionUI();

    } catch (error) {

        showLoginError(
            error.message
        );
    }
}


async function registerUser(event) {

    event.preventDefault();


    const username =
        document.getElementById(
            "registerUsername"
        )?.value.trim();


    const email =
        document.getElementById(
            "registerEmail"
        )?.value.trim();


    const password =
        document.getElementById(
            "registerPassword"
        )?.value;


    const password2 =
        document.getElementById(
            "registerPassword2"
        )?.value;


    if (
        !username ||
        !email ||
        !password ||
        !password2
    ) {

        showRegisterError(
            "كمل جميع البيانات"
        );

        return;
    }


    if (password !== password2) {

        showRegisterError(
            "كلمتا المرور غير متطابقتين"
        );

        return;
    }


    if (password.length < 6) {

        showRegisterError(
            "كلمة المرور لازم تكون 6 أحرف على الأقل"
        );

        return;
    }


    try {

        const data =
            await api(
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


        state.user =
            data.user || {
                username,
                email,
                plan: "مجاني"
            };


        updateUserUI();

        closeModal("authModal");


        showToast(
            "تم إنشاء الحساب بنجاح 🎉"
        );


        showSubscriptionUI();

    } catch (error) {

        showRegisterError(
            error.message
        );
    }
}


/* =========================================================
   USER UI
========================================================= */

function updateUserUI() {

    const usernameDisplay =
        document.getElementById(
            "usernameDisplay"
        );

    const planDisplay =
        document.getElementById(
            "planDisplay"
        );

    const loginBtn =
        document.getElementById(
            "loginBtn"
        );

    const logoutBtn =
        document.getElementById(
            "logoutBtn"
        );


    if (state.user) {

        updateElement(
            "usernameDisplay",
            state.user.username ||
            state.user.name ||
            "المستخدم"
        );


        updateElement(
            "planDisplay",
            state.user.plan ||
            state.user.subscription ||
            "مجاني"
        );


        if (loginBtn) {
            loginBtn.style.display = "none";
        }


        if (logoutBtn) {
            logoutBtn.style.display = "";
        }


        showSubscriptionUI();

    } else {

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


function showSubscriptionUI() {

    const premiumBtn =
        document.getElementById(
            "premiumBtn"
        );

    const premiumOpenBtn =
        document.getElementById(
            "premiumOpenBtn"
        );


    /*
       نخلي الاشتراك يظهر للمستخدم
       بعد تسجيل الدخول فقط
    */

    if (premiumBtn) {

        premiumBtn.style.display =
            "flex";
    }


    if (premiumOpenBtn) {

        premiumOpenBtn.style.display =
            "inline-flex";
    }
}


/* =========================================================
   PREMIUM / PAYMENT
========================================================= */

function openPremium() {

    /*
       لا نفتح الاشتراك للزائر
    */

    if (!state.user) {

        showToast(
            "سجل دخولك أولاً ثم تقدر تشترك 🔐"
        );

        showLogin();

        return;
    }


    openModal("premiumModal");
}


function startSubscription() {

    /*
       لازم يكون المستخدم مسجل
    */

    if (!state.user) {

        closeModal("premiumModal");

        showToast(
            "سجل دخولك أولاً للاشتراك 🔐"
        );

        showLogin();

        return;
    }


    /*
       هنا يتم تحويل المستخدم إلى صفحة الدفع
       إذا كان السيرفر يوفر endpoint للدفع.
    */

    window.location.href =
        "/api/payment/subscribe";
}


/* =========================================================
   THEME
========================================================= */

function loadLocalTheme() {

    const theme =
        localStorage.getItem(
            "theme"
        ) || "dark";


    applyTheme(theme);
}


function applyTheme(theme) {

    const light =
        theme === "light";


    if (light) {

        document.body.classList.add(
            "light-theme"
        );

    } else {

        document.body.classList.remove(
            "light-theme"
        );
    }


    const darkBtn =
        document.getElementById(
            "themeDark"
        );

    const lightBtn =
        document.getElementById(
            "themeLight"
        );


    if (darkBtn) {

        darkBtn.classList.toggle(
            "active",
            !light
        );
    }


    if (lightBtn) {

        lightBtn.classList.toggle(
            "active",
            light
        );
    }


    const toggle =
        document.getElementById(
            "themeToggle"
        );


    if (toggle) {

        toggle.textContent =
            light ? "☀️" : "🌙";
    }


    localStorage.setItem(
        "theme",
        theme
    );


    state.settings.theme =
        theme;
}


function toggleTheme() {

    const light =
        document.body.classList.contains(
            "light-theme"
        );


    applyTheme(
        light ? "dark" : "light"
    );
}


/* =========================================================
   SETTINGS
========================================================= */

async function loadSettings() {

    try {

        const data =
            await api(
                "/api/settings"
            );


        if (data.settings) {

            state.settings = {
                ...state.settings,
                ...data.settings
            };
        }


        if (state.settings.interval) {

            state.interval =
                state.settings.interval;
        }

    } catch (_) {}

    applySettingsToUI();
}


function applySettingsToUI() {

    const interval =
        state.interval || "15m";


    document
        .querySelectorAll(
            "[data-interval]"
        )
        .forEach(function (button) {

            button.classList.toggle(
                "active",
                button.dataset.interval === interval
            );
        });


    const intervalSetting =
        document.getElementById(
            "intervalSetting"
        );


    if (intervalSetting) {

        intervalSetting.value =
            interval;
    }


    const refreshSetting =
        document.getElementById(
            "refreshSetting"
        );


    if (refreshSetting) {

        refreshSetting.value =
            String(
                state.settings.refresh_seconds ||
                30
            );
    }


    const notifications =
        document.getElementById(
            "notificationsSetting"
        );


    if (notifications) {

        notifications.checked =
            !!state.settings.notifications;
    }


    applyTheme(
        state.settings.theme || "dark"
    );
}


async function saveSettings() {

    const intervalSetting =
        document.getElementById(
            "intervalSetting"
        );


    const refreshSetting =
        document.getElementById(
            "refreshSetting"
        );


    const notifications =
        document.getElementById(
            "notificationsSetting"
        );


    if (intervalSetting) {

        state.interval =
            intervalSetting.value;

        state.settings.interval =
            intervalSetting.value;
    }


    if (refreshSetting) {

        state.settings.refresh_seconds =
            Number(
                refreshSetting.value
            ) || 30;
    }


    if (notifications) {

        state.settings.notifications =
            notifications.checked;
    }


    try {

        await api(
            "/api/settings",
            {
                method: "POST",
                body: JSON.stringify(
                    state.settings
                )
            }
        );


        updateElement(
            "settingsMessage",
            "تم حفظ الإعدادات ✅"
        );


        showToast(
            "تم حفظ الإعدادات ✅"
        );


    } catch (error) {

        showToast(
            "تعذر حفظ الإعدادات: " +
            error.message
        );
    }


    startAutoRefresh();
}


/* =========================================================
   MARKETS
========================================================= */

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


        if (!Array.isArray(
            state.markets
        )) {

            state.markets = [];
        }


        /*
           مهم:
           لا يوجد slice(0,100)
           جميع العملات تظهر
        */

        updateElement(
            "coinCount",
            state.markets.length.toLocaleString(
                "en-US"
            )
        );


        renderCoins();

    } catch (error) {

        showError(
            "تعذر تحميل العملات: " +
            error.message
        );
    }
}


function renderCoins(searchText = "") {

    const container =
        document.getElementById(
            "coinList"
        );


    if (!container) return;


    const query =
        String(searchText)
            .trim()
            .toUpperCase();


    const filtered =
        state.markets.filter(
            function (item) {

                const symbol =
                    getMarketSymbol(item);


                if (!symbol) {
                    return false;
                }


                if (!query) {
                    return true;
                }


                return symbol.includes(
                    query
                );
            }
        );


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


    filtered.forEach(function (item) {

        const symbol =
            getMarketSymbol(item);


        const price =
            getPrice(symbol);


        const change =
            getChange(
                symbol,
                item
            );


        const div =
            document.createElement(
                "div"
            );


        div.className =
            "coin-item";


        if (
            symbol ===
            state.symbol
        ) {

            div.classList.add(
                "selected"
            );

            div.classList.add(
                "active"
            );
        }


        div.innerHTML = `
            <div class="coin-name">
                ${escapeHtml(
                    formatSymbol(symbol)
                )}
            </div>

            <div class="coin-price">
                ${formatPrice(price)}
            </div>

            <div class="coin-change ${
                change >= 0
                    ? "positive"
                    : "negative"
            }">
                ${formatPercent(change)}
            </div>
        `;


        div.addEventListener(
            "click",
            async function () {

                state.symbol =
                    symbol;

                renderCoins(
                    document.getElementById(
                        "coinSearch"
                    )?.value || ""
                );


                await loadData();
            }
        );


        fragment.appendChild(
            div
        );
    });


    container.appendChild(
        fragment
    );
}


/* =========================================================
   PRICES
========================================================= */

async function loadPrices() {

    try {

        const data =
            await api(
                "/api/binance/prices"
            );


        const prices =
            data.prices ||
            data.data ||
            data;


        state.prices = {};


        if (Array.isArray(prices)) {

            prices.forEach(
                function (item) {

                    const symbol =
                        String(
                            item.symbol ||
                            ""
                        ).toUpperCase();


                    if (symbol) {

                        state.prices[
                            symbol
                        ] = item;
                    }
                }
            );

        } else if (
            prices &&
            typeof prices ===
            "object"
        ) {

            state.prices =
                prices;
        }


        renderCoins(
            document.getElementById(
                "coinSearch"
            )?.value || ""
        );

    } catch (error) {

        console.warn(
            "Prices:",
            error
        );
    }
}


function getPrice(symbol) {

    const item =
        state.prices[
            symbol
        ];


    if (
        typeof item ===
        "number"
    ) {
        return item;
    }


    if (
        typeof item ===
        "string"
    ) {
        return Number(item);
    }


    if (
        item &&
        typeof item ===
        "object"
    ) {

        return Number(
            item.price ??
            item.lastPrice ??
            item.last ??
            0
        );
    }


    return 0;
}


function getChange(
    symbol,
    market
) {

    const item =
        state.prices[
            symbol
        ];


    const values = [

        item?.priceChangePercent,

        item?.changePercent,

        item?.change,

        market?.priceChangePercent,

        market?.changePercent,

        market?.change
    ];


    for (
        const value
        of values
    ) {

        const number =
            Number(value);


        if (
            Number.isFinite(number)
        ) {

            return number;
        }
    }


    return 0;
}


/* =========================================================
   ANALYSIS
========================================================= */

async function loadData() {

    if (state.loading) return;


    state.loading = true;

    showLoading(true);


    try {

        const url =
            "/api/binance/analysis" +
            "?symbol=" +
            encodeURIComponent(
                state.symbol
            ) +
            "&interval=" +
            encodeURIComponent(
                state.interval
            );


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


        updateElement(
            "symbolName",
            state.symbol
        );


        updateElement(
            "chartTimeframe",
            getIntervalName(
                state.interval
            )
        );


        renderAnalysis();

        drawChart();

    } catch (error) {

        showError(
            "تعذر تحميل التحليل: " +
            error.message
        );

    } finally {

        state.loading = false;

        showLoading(false);
    }
}


/* =========================================================
   RENDER ANALYSIS
========================================================= */

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


    updateElement(
        "signal",
        signal
    );


    const signalElement =
        document.getElementById(
            "signal"
        );


    if (signalElement) {

        signalElement.className =
            "signal-value " +
            signalClass(signal);
    }


    updateElement(
        "score",
        Number.isFinite(score)
            ? score.toFixed(0)
            : "--"
    );


    const percentage =
        Math.max(
            0,
            Math.min(
                100,
                score || 0
            )
        );


    const progress =
        document.getElementById(
            "signalProgress"
        );


    if (progress) {

        progress.style.width =
            percentage + "%";
    }


    const bar =
        document.getElementById(
            "signalBar"
        );


    if (bar) {

        bar.style.setProperty(
            "--progress",
            percentage + "%"
        );
    }


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


    updateElement(
        "currentPrice",
        formatPrice(
            a.current_price ??
            a.currentPrice ??
            a.price ??
            getPrice(state.symbol)
        )
    );


    updateElement(
        "priceChange",
        formatPercent(
            a.price_change_percent ??
            a.priceChangePercent ??
            a.change_percent ??
            a.changePercent
        )
    );


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


    updateElement(
        "marketRegime",
        a.market_regime ??
        a.marketRegime ??
        a.regime ??
        a.trend ??
        "حيادي"
    );


    const rsi =
        Number(
            a.rsi ??
            a.RSI ??
            a.indicators?.rsi
        );


    updateElement(
        "rsi",
        Number.isFinite(rsi)
            ? rsi.toFixed(2)
            : "--"
    );


    updateElement(
        "rsiStatus",
        getRSIStatus(rsi)
    );


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


    const macd =
        a.macd ??
        a.MACD ??
        a.indicators?.macd;


    updateElement(
        "macd",
        formatNumber(
            typeof macd === "object"
                ? macd?.value ??
                  macd?.macd
                : macd,
            4
        )
    );


    updateElement(
        "macdStatus",
        getMACDStatus(macd)
    );


    updateElement(
        "atr",
        formatPriceValue(
            a.atr ??
            a.ATR ??
            a.indicators?.atr
        )
    );


    updateElement(
        "volumeRatio",
        formatRatio(
            a.volume_ratio ??
            a.volumeRatio ??
            a.indicators?.volumeRatio
        )
    );


    updateElement(
        "trend",
        a.trend ??
        a.direction ??
        a.market_trend ??
        "حيادي"
    );


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


    renderReasons(
        a.reasons ||
        a.reason ||
        a.analysis_reasons ||
        []
    );


    updateFavoriteButton();
}


/* =========================================================
   SIGNAL
========================================================= */

function normalizeSignal(value) {

    const text =
        String(
            value || ""
        )
        .trim()
        .toLowerCase();


    if (
        text.includes("شراء قوي") ||
        text.includes("strong buy") ||
        text.includes("strong_buy")
    ) {
        return "شراء قوي";
    }


    if (
        text === "شراء" ||
        text === "buy" ||
        text.includes("buy")
    ) {
        return "شراء";
    }


    if (
        text.includes("بيع قوي") ||
        text.includes("strong sell") ||
        text.includes("strong_sell")
    ) {
        return "بيع قوي";
    }


    if (
        text === "بيع" ||
        text === "sell" ||
        text.includes("sell")
    ) {
        return "بيع";
    }


    return "حيادي";
}


function signalClass(signal) {

    switch (
        normalizeSignal(signal)
    ) {

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


/* =========================================================
   REASONS
========================================================= */

function renderReasons(reasons) {

    const container =
        document.getElementById(
            "reasons"
        );


    if (!container) return;


    let list = reasons;


    if (
        typeof list ===
        "string"
    ) {

        list =
            list
                .split(/\n|،|,/)
                .map(
                    x => x.trim()
                )
                .filter(Boolean);
    }


    if (!Array.isArray(list)) {
        list = [];
    }


    container.innerHTML = "";


    if (!list.length) {

        container.innerHTML = `
            <div class="reason-item">
                لا توجد أسباب إضافية حالياً
            </div>
        `;

        return;
    }


    list.forEach(
        function (reason) {

            const text =
                typeof reason ===
                "object"
                    ? (
                        reason.text ||
                        reason.reason ||
                        reason.title ||
                        ""
                    )
                    : String(reason);


            const div =
                document.createElement(
                    "div"
                );


            div.className =
                "reason-item";


            div.textContent =
                "✓ " + text;


            container.appendChild(
                div
            );
        }
    );
}


/* =========================================================
   FAVORITES
========================================================= */

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


    updateFavoriteButton();
}


function updateFavoriteButton() {

    const button =
        document.getElementById(
            "favoriteBtn"
        );


    if (!button) return;


    const active =
        state.favorites.includes(
            state.symbol
        );


    button.classList.toggle(
        "active",
        active
    );


    button.textContent =
        active ? "★" : "☆";
}


/* =========================================================
   SCANNER
========================================================= */

async function runScanner() {

    if (!state.user) {

        showToast(
            "سجل دخولك أولاً لاستخدام الماسح 🔐"
        );

        showLogin();

        return;
    }


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


        if (
            !Array.isArray(results) ||
            !results.length
        ) {

            container.innerHTML = `
                <div class="empty-state">
                    لا توجد إشارات حالياً
                </div>
            `;

            return;
        }


        container.innerHTML = "";


        results.forEach(
            function (item) {

                const symbol =
                    getMarketSymbol(
                        item
                    );


                const signal =
                    normalizeSignal(
                        item.signal ||
                        item.recommendation
                    );


                const div =
                    document.createElement(
                        "div"
                    );


                div.className =
                    "scan-item";


                div.innerHTML = `
                    <strong>
                        ${escapeHtml(symbol)}
                    </strong>

                    <span>
                        ${escapeHtml(signal)}
                    </span>

                    <b>
                        ${
                            item.score ??
                            "--"
                        }
                    </b>
                `;


                div.addEventListener(
                    "click",
                    async function () {

                        state.symbol =
                            symbol;

                        await loadData();
                    }
                );


                container.appendChild(
                    div
                );
            }
        );

    } catch (error) {

        container.innerHTML = `
            <div class="error-state">
                ${escapeHtml(
                    error.message
                )}
            </div>
        `;
    }
}


/* =========================================================
   AUTO REFRESH
========================================================= */

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
            async function () {

                if (state.loading) {
                    return;
                }


                await loadPrices();

                await loadData();

            },
            seconds * 1000
        );
}


/* =========================================================
   API
========================================================= */

async function api(
    url,
    options = {}
) {

    const response =
        await fetch(
            url,
            {
                ...options,

                headers: {
                    "Content-Type":
                        "application/json",

                    ...(options.headers || {})
                },

                cache: "no-store"
            }
        );


    let data = {};

    try {

        data =
            await response.json();

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


/* =========================================================
   LOGOUT
========================================================= */

async function logout() {

    try {

        await api(
            "/api/auth/logout",
            {
                method: "POST"
            }
        );

    } catch (_) {}


    state.user = null;

    updateUserUI();

    showToast(
        "تم تسجيل الخروج"
    );
}


/* =========================================================
   CHART
========================================================= */

function drawChart() {

    const canvas =
        document.getElementById(
            "priceChart"
        );


    if (!canvas) return;


    const wrapper =
        canvas.parentElement;


    const width =
        Math.max(
            300,
            wrapper?.clientWidth ||
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
        width + "px";

    canvas.style.height =
        height + "px";


    const ctx =
        canvas.getContext(
            "2d"
        );


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


    const candles =
        Array.isArray(
            state.candles
        )
            ? state.candles.slice(-80)
            : [];


    if (!candles.length) {

        drawChartMessage(
            ctx,
            width,
            height,
            "لا توجد بيانات الشارت"
        );

        return;
    }


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


    let max =
        Math.max(
            ...parsed.map(
                c => c.high
            )
        );


    let min =
        Math.min(
            ...parsed.map(
                c => c.low
            )
        );


    const extra =
        (max - min) * 0.05;


    max += extra;
    min -= extra;


    const left = 45;
    const right = 15;
    const top = 20;
    const bottom = 25;


    const chartWidth =
        width -
        left -
        right;


    const chartHeight =
        height -
        top -
        bottom;


    function y(value) {

        return top +
            (
                (max - value) /
                (max - min)
            ) *
            chartHeight;
    }


    ctx.strokeStyle =
        "rgba(255,255,255,.08)";


    ctx.lineWidth = 1;


    for (
        let i = 0;
        i <= 5;
        i++
    ) {

        const yy =
            top +
            (
                chartHeight /
                5
            ) *
            i;


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
    }


    const candleWidth =
        Math.max(
            2,
            chartWidth /
            parsed.length *
            0.65
        );


    parsed.forEach(
        function (candle, index) {

            const x =
                left +
                (
                    index /
                    Math.max(
                        1,
                        parsed.length - 1
                    )
                ) *
                chartWidth;


            const bullish =
                candle.close >=
                candle.open;


            ctx.strokeStyle =
                bullish
                    ? "#16c784"
                    : "#ea3943";


            ctx.fillStyle =
                bullish
                    ? "#16c784"
                    : "#ea3943";


            ctx.beginPath();

            ctx.moveTo(
                x,
                y(candle.high)
            );

            ctx.lineTo(
                x,
                y(candle.low)
            );

            ctx.stroke();


            const topBody =
                Math.min(
                    y(candle.open),
                    y(candle.close)
                );


            const bodyHeight =
                Math.max(
                    1,
                    Math.abs(
                        y(candle.close) -
                        y(candle.open)
                    )
                );


            ctx.fillRect(
                x -
                candleWidth / 2,

                topBody,

                candleWidth,

                bodyHeight
            );
        }
    );
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


    if (!candle) return null;


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
        !Number.isFinite(
            result.open
        ) ||
        !Number.isFinite(
            result.high
        ) ||
        !Number.isFinite(
            result.low
        ) ||
        !Number.isFinite(
            result.close
        )
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
        "#888";

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


/* =========================================================
   HELPERS
========================================================= */

function getMarketSymbol(item) {

    if (
        typeof item ===
        "string"
    ) {

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

    if (
        symbol.endsWith("USDT")
    ) {

        return symbol.replace(
            "USDT",
            " / USDT"
        );
    }


    return symbol;
}


function getIntervalName(interval) {

    const names = {

        "5m": "5 دقائق",
        "15m": "15 دقيقة",
        "1h": "ساعة",
        "4h": "4 ساعات",
        "1d": "يومي",
        "1w": "أسبوعي"
    };


    return (
        names[interval] ||
        interval
    );
}


function updateElement(
    id,
    value
) {

    const element =
        document.getElementById(id);


    if (!element) return;


    element.textContent =
        value === null ||
        value === undefined ||
        value === ""
            ? "--"
            : value;
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


    return formatPrice(value);
}


function formatPercent(value) {

    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return (
        number >= 0
            ? "+"
            : ""
    ) +
    number.toFixed(2) +
    "%";
}


function formatNumber(
    value,
    decimals = 2
) {

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

    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return "1:" +
        number.toFixed(2);
}


function formatRatio(value) {

    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    return number.toFixed(2) +
        "x";
}


function formatVolume(value) {

    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return "--";
    }


    if (number >= 1e9) {

        return (
            number / 1e9
        ).toFixed(2) +
        "B";
    }


    if (number >= 1e6) {

        return (
            number / 1e6
        ).toFixed(2) +
        "M";
    }


    if (number >= 1e3) {

        return (
            number / 1e3
        ).toFixed(2) +
        "K";
    }


    return number.toFixed(2);
}


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


function getMACDStatus(macd) {

    let value;


    if (
        typeof macd ===
        "object"
    ) {

        value =
            Number(
                macd?.histogram ??
                macd?.value ??
                macd?.macd
            );

    } else {

        value =
            Number(macd);
    }


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


function escapeHtml(value) {

    return String(value)
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );
}


function showLoading(show) {

    const button =
        document.getElementById(
            "refreshBtn"
        );


    if (!button) return;


    button.disabled =
        show;


    button.classList.toggle(
        "loading",
        show
    );
}


function showError(message) {

    const box =
        document.getElementById(
            "errorBox"
        );


    if (!box) {

        console.error(message);

        return;
    }


    box.textContent =
        message;


    box.style.display =
        "block";


    box.classList.add(
        "show"
    );


    setTimeout(
        function () {

            box.style.display =
                "none";

            box.classList.remove(
                "show"
            );

        },
        6000
    );
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


        toast.style.cssText = `
            position:fixed;
            bottom:25px;
            left:50%;
            transform:translateX(-50%);
            z-index:999999;
            background:#111827;
            color:#fff;
            padding:12px 20px;
            border-radius:12px;
            box-shadow:0 10px 30px rgba(0,0,0,.3);
            font-size:14px;
        `;


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
        setTimeout(
            function () {

                toast.style.display =
                    "none";

            },
            3000
        );
}


/* =========================================================
   CLEANUP
========================================================= */

window.addEventListener(
    "beforeunload",
    function () {

        if (state.refreshTimer) {

            clearInterval(
                state.refreshTimer
            );
        }
    }
);

(() => {
    "use strict";

    // =========================================================
    // HELPERS
    // =========================================================

    const $ = (id) => document.getElementById(id);

    const qs = (selector, root = document) =>
        root.querySelector(selector);

    const qsa = (selector, root = document) =>
        [...root.querySelectorAll(selector)];

    const state = {
        user: null,
        admin: false,

        symbol: "BTCUSDT",
        interval: "15m",

        results: [],
        signals: [],

        spotResults: [],
        alphaResults: [],
        futuresResults: [],
        usResults: [],
        saudiResults: [],

        sortField: "change",
        sortDesc: true,

        chart: null,

        loadingAnalysis: false,
        loadingScan: false,

        currentSection: "dashboard",

        selectedPlan: null,

        authMode: "login"
    };


    // =========================================================
    // API
    // =========================================================

    async function api(url, options = {}) {

        const response = await fetch(
            url,
            {
                credentials: "same-origin",
                ...options,
                headers: {
                    "Content-Type": "application/json",
                    ...(options.headers || {})
                }
            }
        );

        let data = null;

        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (!response.ok) {

            throw new Error(
                data.message ||
                data.error ||
                `HTTP ${response.status}`
            );
        }

        return data;
    }


    // =========================================================
    // FORMAT
    // =========================================================

    function number(value, digits = 4) {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        if (Math.abs(n) >= 1000) {
            return n.toLocaleString(
                "en-US",
                {
                    maximumFractionDigits: 2
                }
            );
        }

        return n.toLocaleString(
            "en-US",
            {
                maximumFractionDigits: digits
            }
        );
    }


    function price(value) {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        if (n >= 1000) {
            return n.toLocaleString(
                "en-US",
                {
                    maximumFractionDigits: 2
                }
            );
        }

        if (n >= 1) {
            return n.toLocaleString(
                "en-US",
                {
                    maximumFractionDigits: 4
                }
            );
        }

        return n.toLocaleString(
            "en-US",
            {
                maximumFractionDigits: 8
            }
        );
    }


    function percent(value) {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
    }


    function escapeHTML(value) {

        return String(
            value ?? ""
        )
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    function signalClass(signal) {

        if (signal === "شراء قوي") {
            return "signal-buy-strong";
        }

        if (signal === "شراء") {
            return "signal-buy";
        }

        if (signal === "بيع قوي") {
            return "signal-sell-strong";
        }

        if (signal === "بيع") {
            return "signal-sell";
        }

        return "signal-neutral";
    }


    function signalIcon(signal) {

        if (signal === "شراء قوي") {
            return "🟢";
        }

        if (signal === "شراء") {
            return "🟩";
        }

        if (signal === "بيع قوي") {
            return "🔴";
        }

        if (signal === "بيع") {
            return "🟥";
        }

        return "⚪";
    }


    function directionText(item) {

        if (item.direction === "buy") {
            return "شراء";
        }

        if (item.direction === "sell") {
            return "بيع";
        }

        return "حيادي";
    }


    // =========================================================
    // LOCAL STORAGE
    // =========================================================

    function saveLocalResults() {

        try {

            localStorage.setItem(
                "mudarib_spot_results",
                JSON.stringify(
                    state.spotResults.slice(0, 100)
                )
            );

            localStorage.setItem(
                "mudarib_alpha_results",
                JSON.stringify(
                    state.alphaResults.slice(0, 100)
                )
            );

            localStorage.setItem(
                "mudarib_futures_results",
                JSON.stringify(
                    state.futuresResults.slice(0, 100)
                )
            );

        } catch (_) {}
    }


    function loadLocalResults() {

        try {

            const spot =
                JSON.parse(
                    localStorage.getItem(
                        "mudarib_spot_results"
                    ) || "[]"
                );

            const alpha =
                JSON.parse(
                    localStorage.getItem(
                        "mudarib_alpha_results"
                    ) || "[]"
                );

            const futures =
                JSON.parse(
                    localStorage.getItem(
                        "mudarib_futures_results"
                    ) || "[]"
                );

            if (Array.isArray(spot)) {
                state.spotResults = spot;
            }

            if (Array.isArray(alpha)) {
                state.alphaResults = alpha;
            }

            if (Array.isArray(futures)) {
                state.futuresResults = futures;
            }

        } catch (_) {}
    }


    // =========================================================
    // NAVIGATION
    // =========================================================

    const sectionTitles = {
        dashboard: "الرئيسية",
        scanner: "ماسح الفرص",
        recent: "🟢 صفقات السبوت",
        alpha: "⚡ صفقات Alpha",
        futures: "🚀 صفقات الفيوتشر",
        "us-market": "🇺🇸 صفقات السوق الأمريكي",
        news: "الأخبار",
        subscription: "الاشتراك"
    };


    function showSection(section) {

        const target = $(section);

        if (!target) {
            return;
        }

        qsa(".section").forEach(
            (el) => {
                el.classList.remove(
                    "active"
                );
            }
        );

        target.classList.add(
            "active"
        );

        qsa(".nav-item").forEach(
            (btn) => {

                btn.classList.toggle(
                    "active",
                    btn.dataset.section === section
                );
            }
        );

        state.currentSection = section;

        if ($("pageTitle")) {

            $("pageTitle").textContent =
                sectionTitles[section] ||
                "تحليل العملات الرقمية";
        }

        const sidebar = $("sidebar");

        if (sidebar) {
            sidebar.classList.remove(
                "open"
            );
        }

        if (section === "dashboard") {
            loadDashboardAnalysis();
        }

        if (section === "scanner") {
            if (!state.results.length) {
                runScanner();
            }
        }

        if (section === "recent") {
            renderSpot();
        }

        if (section === "alpha") {
            loadAlpha();
        }

        if (section === "futures") {
            loadFutures();
        }

        if (section === "us-market") {
            loadUSMarket();
        }

        if (section === "news") {
            loadNews();
        }

        if (section === "subscription") {
            loadSubscription();
        }
    }


    function initNavigation() {

        qsa(".nav-item").forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {

                        showSection(
                            button.dataset.section
                        );
                    }
                );
            }
        );


        if ($("menuBtn")) {

            $("menuBtn").addEventListener(
                "click",
                () => {

                    $("sidebar")?.classList.toggle(
                        "open"
                    );
                }
            );
        }
    }


    // =========================================================
    // AUTH MODAL
    // =========================================================

    function openAuth(mode = "login") {

        const modal = $("authModal");

        if (!modal) {
            return;
        }

        state.authMode = mode;

        modal.hidden = false;

        showAuthMode(mode);

        setTimeout(
            () => {

                const input =
                    mode === "login"
                        ? $("modalLoginEmail")
                        : $("modalRegisterName");

                input?.focus();

            },
            50
        );
    }


    function closeAuth() {

        const modal = $("authModal");

        if (modal) {
            modal.hidden = true;
        }

        clearAuthMessages();
    }


    function showAuthMode(mode) {

        state.authMode = mode;

        const loginBox =
            $("loginBox");

        const registerBox =
            $("registerBox");

        const title =
            $("authModalTitle");

        if (loginBox) {
            loginBox.hidden =
                mode !== "login";
        }

        if (registerBox) {
            registerBox.hidden =
                mode !== "register";
        }

        if (title) {

            title.textContent =
                mode === "login"
                    ? "تسجيل الدخول"
                    : "إنشاء حساب";
        }

        clearAuthMessages();
    }


    function clearAuthMessages() {

        [
            "modalLoginMessage",
            "modalRegisterMessage"
        ].forEach(
            (id) => {

                const el = $(id);

                if (!el) {
                    return;
                }

                el.style.display =
                    "none";

                el.textContent =
                    "";
            }
        );
    }


    function authMessage(
        id,
        message,
        error = false
    ) {

        const el = $(id);

        if (!el) {
            return;
        }

        el.textContent =
            message || "";

        el.style.display =
            message ? "block" : "none";

        el.classList.toggle(
            "error",
            error
        );
    }


    function initAuth() {

        $("loginBtn")?.addEventListener(
            "click",
            () => openAuth("login")
        );

        $("registerBtn")?.addEventListener(
            "click",
            () => openAuth("register")
        );

        $("authModalClose")?.addEventListener(
            "click",
            closeAuth
        );

        $("authModalOverlay")?.addEventListener(
            "click",
            closeAuth
        );

        $("showRegister")?.addEventListener(
            "click",
            () => showAuthMode("register")
        );

        $("showLogin")?.addEventListener(
            "click",
            () => showAuthMode("login")
        );


        $("modalLoginForm")?.addEventListener(
            "submit",
            login
        );

        $("modalRegisterForm")?.addEventListener(
            "submit",
            register
        );


        document.addEventListener(
            "keydown",
            (event) => {

                if (
                    event.key === "Escape"
                    &&
                    $("authModal")
                    &&
                    !$("authModal").hidden
                ) {

                    closeAuth();
                }
            }
        );


        $("logoutBtn")?.addEventListener(
            "click",
            logout
        );
    }


    async function login(event) {

        event.preventDefault();

        const email =
            $("modalLoginEmail")?.value.trim();

        const password =
            $("modalLoginPassword")?.value || "";

        if (!email || !password) {

            authMessage(
                "modalLoginMessage",
                "اكتب البريد وكلمة المرور",
                true
            );

            return;
        }

        const button =
            $("modalLoginSubmit");

        if (button) {
            button.disabled = true;
            button.textContent =
                "⏳ جاري الدخول...";
        }

        try {

            const data = await api(
                "/api/auth/login",
                {
                    method: "POST",
                    body: JSON.stringify({
                        email,
                        password
                    })
                }
            );

            if (
                data.ok === false
                &&
                !data.user
            ) {

                throw new Error(
                    data.message ||
                    "تعذر تسجيل الدخول"
                );
            }

            closeAuth();

            await loadAuth();

            setStatus(
                "تم تسجيل الدخول"
            );

        } catch (error) {

            authMessage(
                "modalLoginMessage",
                error.message,
                true
            );

        } finally {

            if (button) {

                button.disabled = false;

                button.textContent =
                    "🔐 تسجيل الدخول";
            }
        }
    }


    async function register(event) {

        event.preventDefault();

        const name =
            $("modalRegisterName")?.value.trim();

        const email =
            $("modalRegisterEmail")?.value.trim();

        const password =
            $("modalRegisterPassword")?.value || "";

        if (!name || !email || !password) {

            authMessage(
                "modalRegisterMessage",
                "عبّ البيانات المطلوبة",
                true
            );

            return;
        }

        if (password.length < 6) {

            authMessage(
                "modalRegisterMessage",
                "كلمة المرور لازم تكون 6 أحرف على الأقل",
                true
            );

            return;
        }

        const button =
            $("modalRegisterSubmit");

        if (button) {

            button.disabled = true;

            button.textContent =
                "⏳ جاري إنشاء الحساب...";
        }

        try {

            const data = await api(
                "/api/auth/register",
                {
                    method: "POST",
                    body: JSON.stringify({
                        name,
                        email,
                        password
                    })
                }
            );

            if (
                data.ok === false
                &&
                !data.user
            ) {

                throw new Error(
                    data.message ||
                    "تعذر إنشاء الحساب"
                );
            }

            closeAuth();

            await loadAuth();

            setStatus(
                "تم إنشاء الحساب"
            );

        } catch (error) {

            authMessage(
                "modalRegisterMessage",
                error.message,
                true
            );

        } finally {

            if (button) {

                button.disabled = false;

                button.textContent =
                    "📝 إنشاء الحساب";
            }
        }
    }


    async function logout() {

        try {

            await api(
                "/api/auth/logout",
                {
                    method: "POST",
                    body: JSON.stringify({})
                }
            );

        } catch (_) {}

        state.user = null;
        state.admin = false;

        updateAuthUI();

        showSection(
            state.currentSection === "subscription"
                ? "dashboard"
                : state.currentSection
        );
    }


    // =========================================================
    // AUTH STATE
    // =========================================================

    async function loadAuth() {

        try {

            const data = await api(
                "/api/auth/me"
            );

            state.user =
                data.user ||
                data.current_user ||
                (
                    data.authenticated
                        ? data
                        : null
                );

        } catch (_) {

            state.user = null;
        }


        try {

            const data = await api(
                "/api/admin/me"
            );

            state.admin =
                !!(
                    data.admin
                    ||
                    data.is_admin
                    ||
                    data.authenticated
                );

        } catch (_) {

            state.admin = false;
        }

        updateAuthUI();
    }


    function updateAuthUI() {

        const logged =
            !!state.user;

        const name =
            state.user?.name ||
            state.user?.email ||
            "زائر";


        if ($("userBadge")) {

            $("userBadge").textContent =
                logged
                    ? name
                    : "زائر";
        }


        if ($("loginBtn")) {
            $("loginBtn").hidden =
                logged;
        }

        if ($("registerBtn")) {
            $("registerBtn").hidden =
                logged;
        }

        if ($("logoutBtn")) {
            $("logoutBtn").hidden =
                !logged;
        }


        if ($("subscriptionNav")) {

            $("subscriptionNav").hidden =
                !logged;
        }


        if ($("adminLink")) {

            $("adminLink").hidden =
                !state.admin;
        }


        if ($("subscription")) {

            $("subscription").hidden =
                !logged;
        }
    }


    // =========================================================
    // STATUS
    // =========================================================

    function setStatus(text) {

        if ($("systemStatus")) {

            $("systemStatus").textContent =
                text;
        }
    }


    function scannerStatus(text) {

        if ($("scannerStatus")) {

            $("scannerStatus").textContent =
                text;
        }
    }


    // =========================================================
    // DASHBOARD ANALYSIS
    // =========================================================

    async function loadDashboardAnalysis() {

        if (state.loadingAnalysis) {
            return;
        }

        state.loadingAnalysis = true;

        try {

            setStatus(
                "جاري تحديث التحليل..."
            );

            const data = await api(
                `/api/binance/analysis?symbol=${encodeURIComponent(
                    state.symbol
                )}&interval=${encodeURIComponent(
                    state.interval
                )}`
            );

            const result =
                data.result ||
                data.analysis ||
                data;

            renderDashboard(
                result
            );

            setStatus(
                "متصل"
            );

        } catch (error) {

            setStatus(
                "تعذر تحديث التحليل"
            );

            console.error(
                error
            );

        } finally {

            state.loadingAnalysis = false;
        }
    }


    function renderDashboard(data) {

        if (!data) {
            return;
        }


        if ($("dashSymbol")) {

            $("dashSymbol").textContent =
                data.symbol ||
                state.symbol;
        }


        if ($("dashPrice")) {

            $("dashPrice").textContent =
                price(
                    data.price
                );
        }


        if ($("dashChange")) {

            $("dashChange").textContent =
                percent(
                    data.change
                );
        }


        if ($("dashSignal")) {

            $("dashSignal").textContent =
                data.signal ||
                "—";

            $("dashSignal").className =
                signalClass(
                    data.signal
                );
        }


        if ($("bigSignal")) {

            $("bigSignal").textContent =
                `${signalIcon(
                    data.signal
                )} ${data.signal || "—"}`;

            $("bigSignal").className =
                `signal-big ${signalClass(
                    data.signal
                )}`;
        }


        if ($("scoreText")) {

            $("scoreText").textContent =
                data.score != null
                    ? `${number(data.score, 1)}/100`
                    : "—";
        }


        if ($("scoreBar")) {

            const score =
                Math.max(
                    0,
                    Math.min(
                        100,
                        Number(data.score) || 0
                    )
                );

            $("scoreBar").style.width =
                `${score}%`;
        }


        setText(
            "entry",
            price(data.entry)
        );

        setText(
            "tp1",
            price(data.tp1)
        );

        setText(
            "tp2",
            price(data.tp2)
        );

        setText(
            "tp3",
            price(data.tp3)
        );

        setText(
            "sl",
            price(data.sl)
        );

        setText(
            "rsi",
            number(data.rsi, 2)
        );

        setText(
            "ema20",
            price(data.ema20)
        );

        setText(
            "ema50",
            price(data.ema50)
        );

        setText(
            "ema200",
            price(data.ema200)
        );


        if ($("analysisMeta")) {

            $("analysisMeta").textContent =
                `${data.symbol || state.symbol} — ${state.interval}`;
        }


        renderReasons(
            data.reasons
        );

        renderChart(
            data.candles || []
        );
    }


    function setText(
        id,
        value
    ) {

        const el = $(id);

        if (el) {
            el.textContent =
                value;
        }
    }


    function renderReasons(reasons) {

        const list =
            $("reasons");

        if (!list) {
            return;
        }

        if (!Array.isArray(reasons)) {

            list.innerHTML =
                "";

            return;
        }

        list.innerHTML =
            reasons
                .map(
                    reason =>
                        `<li>${escapeHTML(
                            reason
                        )}</li>`
                )
                .join("");
    }


    // =========================================================
    // CHART
    // =========================================================

    function renderChart(candles) {

        const canvas =
            $("priceChart");

        if (!canvas || !window.Chart) {
            return;
        }

        if (
            !Array.isArray(candles)
            ||
            !candles.length
        ) {
            return;
        }

        const labels =
            candles.map(
                candle =>
                    new Date(
                        Number(
                            candle.t
                        )
                    ).toLocaleTimeString(
                        "ar-SA",
                        {
                            hour: "2-digit",
                            minute: "2-digit"
                        }
                    )
            );

        const values =
            candles.map(
                candle =>
                    Number(
                        candle.c
                    )
            );


        if (state.chart) {

            state.chart.destroy();

            state.chart = null;
        }


        state.chart =
            new Chart(
                canvas.getContext("2d"),
                {
                    type: "line",

                    data: {

                        labels,

                        datasets: [
                            {
                                label:
                                    "السعر",

                                data:
                                    values,

                                tension:
                                    0.25,

                                pointRadius:
                                    0,

                                borderWidth:
                                    2,

                                fill:
                                    false
                            }
                        ]
                    },

                    options: {

                        responsive:
                            true,

                        maintainAspectRatio:
                            false,

                        interaction: {
                            mode:
                                "index",

                            intersect:
                                false
                        },

                        plugins: {

                            legend: {
                                display:
                                    false
                            }
                        },

                        scales: {

                            x: {
                                ticks: {
                                    maxTicksLimit:
                                        8
                                }
                            },

                            y: {
                                ticks: {
                                    callback:
                                        value =>
                                            price(value)
                                }
                            }
                        }
                    }
                }
            );
    }


    // =========================================================
    // DASHBOARD INTERVAL
    // =========================================================

    function initDashboardIntervals() {

        qsa(
            "#dashIntervals button"
        ).forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {

                        qsa(
                            "#dashIntervals button"
                        ).forEach(
                            btn =>
                                btn.classList.remove(
                                    "active"
                                )
                        );

                        button.classList.add(
                            "active"
                        );

                        state.interval =
                            button.dataset.interval ||
                            "15m";

                        loadDashboardAnalysis();
                    }
                );
            }
        );
    }


    // =========================================================
    // SCANNER
    // =========================================================

    function initScanner() {

        qsa(
            "#intervalChips button"
        ).forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {

                        qsa(
                            "#intervalChips button"
                        ).forEach(
                            btn =>
                                btn.classList.remove(
                                    "active"
                                )
                        );

                        button.classList.add(
                            "active"
                        );

                        state.interval =
                            button.dataset.interval ||
                            "15m";

                        runScanner();
                    }
                );
            }
        );


        qsa(
            ".signal-chips button"
        ).forEach(
            (button) => {

                button.addEventListener(
                    "click",
                    () => {

                        button.classList.toggle(
                            "active"
                        );

                        applyScannerFilters();
                    }
                );
            }
        );


        $("scannerSearch")?.addEventListener(
            "input",
            applyScannerFilters
        );


        $("sortField")?.addEventListener(
            "change",
            () => {

                state.sortField =
                    $("sortField").value;

                applyScannerFilters();
            }
        );


        $("sortDir")?.addEventListener(
            "click",
            () => {

                state.sortDesc =
                    !state.sortDesc;

                $("sortDir").textContent =
                    state.sortDesc
                        ? "↓ تنازلي"
                        : "↑ تصاعدي";

                applyScannerFilters();
            }
        );


        $("scanBtn")?.addEventListener(
            "click",
            runScanner
        );
    }


    async function runScanner() {

        if (state.loadingScan) {
            return;
        }

        state.loadingScan = true;

        scannerStatus(
            "⏳ جاري فحص العملات حبة حبة..."
        );

        if ($("scanBtn")) {
            $("scanBtn").disabled = true;
        }

        try {

            const data = await api(
                `/api/binance/scan?interval=${encodeURIComponent(
                    state.interval
                )}&limit=40`
            );

            state.results =
                data.results ||
                data.data ||
                [];

            state.spotResults =
                state.results.slice();

            saveLocalResults();

            applyScannerFilters();

            renderSpot();

            scannerStatus(
                `تم الفحص — ${state.results.length} نتيجة`
            );

            setStatus(
                "متصل"
            );

        } catch (error) {

            scannerStatus(
                `تعذر الفحص: ${error.message}`
            );

        } finally {

            state.loadingScan = false;

            if ($("scanBtn")) {
                $("scanBtn").disabled = false;
            }
        }
    }


    function applyScannerFilters() {

        let results =
            state.results.slice();


        const search =
            (
                $("scannerSearch")?.value ||
                ""
            )
                .trim()
                .toUpperCase();


        if (search) {

            results =
                results.filter(
                    item =>
                        String(
                            item.symbol ||
                            ""
                        )
                            .toUpperCase()
                            .includes(search)
                );
        }


        const selectedSignals =
            qsa(
                ".signal-chips button.active"
            )
                .map(
                    btn =>
                        btn.dataset.signal
                );


        if (selectedSignals.length) {

            results =
                results.filter(
                    item =>
                        selectedSignals.includes(
                            item.signal
                        )
                );
        }


        const field =
            state.sortField;


        results.sort(
            (a, b) => {

                let av;
                let bv;


                if (field === "symbol") {

                    av =
                        String(
                            a.symbol ||
                            ""
                        ).toUpperCase();

                    bv =
                        String(
                            b.symbol ||
                            ""
                        ).toUpperCase();

                    return state.sortDesc
                        ? bv.localeCompare(av)
                        : av.localeCompare(bv);
                }


                if (field === "signal") {

                    av =
                        signalRank(
                            a.signal
                        );

                    bv =
                        signalRank(
                            b.signal
                        );

                } else if (field === "score") {

                    av =
                        Number(
                            a.score
                        ) || 0;

                    bv =
                        Number(
                            b.score
                        ) || 0;

                } else if (field === "price") {

                    av =
                        Number(
                            a.price
                        ) || 0;

                    bv =
                        Number(
                            b.price
                        ) || 0;

                } else if (field === "volume") {

                    av =
                        Number(
                            a.volume
                        ) || 0;

                    bv =
                        Number(
                            b.volume
                        ) || 0;

                } else {

                    av =
                        Number(
                            a.change
                        ) || 0;

                    bv =
                        Number(
                            b.change
                        ) || 0;
                }


                return state.sortDesc
                    ? bv - av
                    : av - bv;
            }
        );


        renderScanner(
            results
        );
    }


    function signalRank(signal) {

        return {
            "شراء قوي": 5,
            "شراء": 4,
            "حيادي": 3,
            "بيع": 2,
            "بيع قوي": 1
        }[signal] || 0;
    }


    function renderScanner(results) {

        const body =
            $("scannerBody");

        if (!body) {
            return;
        }


        if (!results.length) {

            body.innerHTML =
                `
                <tr>
                    <td colspan="7">
                        لا توجد نتائج
                    </td>
                </tr>
                `;

            return;
        }


        body.innerHTML =
            results.map(
                item => {

                    const change =
                        Number(
                            item.change
                        ) || 0;

                    return `
                    <tr
                        data-symbol="${escapeHTML(
                            item.symbol
                        )}"
                    >

                        <td>
                            <button
                                class="coin-link"
                                data-symbol="${escapeHTML(
                                    item.symbol
                                )}"
                            >
                                ${escapeHTML(
                                    item.symbol
                                )}
                            </button>
                        </td>

                        <td>
                            ${price(item.price)}
                        </td>

                        <td class="${
                            change >= 0
                                ? "positive"
                                : "negative"
                        }">
                            ${percent(change)}
                        </td>

                        <td>
                            <span class="${signalClass(
                                item.signal
                            )}">
                                ${signalIcon(
                                    item.signal
                                )}
                                ${escapeHTML(
                                    item.signal || "—"
                                )}
                            </span>
                        </td>

                        <td>
                            ${number(
                                item.score,
                                1
                            )}
                        </td>

                        <td>
                            ${number(
                                item.volume,
                                0
                            )}
                        </td>

                        <td>
                            ${escapeHTML(
                                item.interval ||
                                state.interval
                            )}
                        </td>

                    </tr>
                    `;
                }
            ).join("");


        qsa(
            ".coin-link",
            body
        ).forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        state.symbol =
                            button.dataset.symbol;

                        showSection(
                            "dashboard"
                        );
                    }
                );
            }
        );
    }


    // =========================================================
    // SPOT
    // =========================================================

    function renderSpot() {

        const box =
            $("recentList");

        if (!box) {
            return;
        }

        renderTradeCards(
            box,
            state.spotResults,
            "spot"
        );
    }


    // =========================================================
    // ALPHA
    // =========================================================

    async function loadAlpha() {

        const box =
            $("alphaList");

        if (!box) {
            return;
        }


        if (
            state.alphaResults.length
        ) {

            renderTradeCards(
                box,
                state.alphaResults,
                "alpha"
            );

            return;
        }


        box.innerHTML =
            `
            <div class="panel">
                ⏳ جاري تحميل صفقات Alpha...
            </div>
            `;


        try {

            const data = await api(
                `/api/alpha/scan?interval=${encodeURIComponent(
                    state.interval
                )}&limit=40`
            );

            state.alphaResults =
                data.results ||
                data.data ||
                [];

            saveLocalResults();

            renderTradeCards(
                box,
                state.alphaResults,
                "alpha"
            );

        } catch (error) {

            box.innerHTML =
                `
                <div class="panel">
                    تعذر تحميل Alpha:
                    ${escapeHTML(
                        error.message
                    )}
                </div>
                `;
        }
    }


    // =========================================================
    // FUTURES
    // =========================================================

    async function loadFutures() {

        const box =
            $("futuresList");

        if (!box) {
            return;
        }


        if (
            state.futuresResults.length
        ) {

            renderTradeCards(
                box,
                state.futuresResults,
                "futures"
            );

            return;
        }


        box.innerHTML =
            `
            <div class="panel">
                ⏳ جاري تحميل صفقات الفيوتشر...
            </div>
            `;


        try {

            const data = await api(
                `/api/futures/scan?interval=${encodeURIComponent(
                    state.interval
                )}&limit=40`
            );

            state.futuresResults =
                data.results ||
                data.data ||
                [];

            saveLocalResults();

            renderTradeCards(
                box,
                state.futuresResults,
                "futures"
            );

        } catch (error) {

            box.innerHTML =
                `
                <div class="panel">
                    تعذر تحميل الفيوتشر:
                    ${escapeHTML(
                        error.message
                    )}
                </div>
                `;
        }
    }


    // =========================================================
    // TRADE CARDS
    // =========================================================

    function renderTradeCards(
        container,
        results,
        type
    ) {

        if (!results.length) {

            container.innerHTML =
                `
                <div class="panel">
                    لا توجد صفقات حالياً.
                </div>
                `;

            return;
        }


        container.innerHTML =
            results
                .map(
                    item =>
                        tradeCard(
                            item,
                            type
                        )
                )
                .join("");


        qsa(
            "[data-open-symbol]",
            container
        ).forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        state.symbol =
                            button.dataset.openSymbol;

                        showSection(
                            "dashboard"
                        );
                    }
                );
            }
        );
    }


    function tradeCard(
        item,
        type
    ) {

        const futures =
            type === "futures";

        const alpha =
            type === "alpha";


        const leverage =
            item.leverageText ||
            (
                item.leverage
                    ? `${item.leverage}x`
                    : "5x"
            );


        const market =
            futures
                ? "Futures"
                : alpha
                    ? "Alpha"
                    : "Spot";


        return `
        <article class="trade-card">

            <div class="trade-card-head">

                <div>

                    <button
                        class="coin-link"
                        data-open-symbol="${escapeHTML(
                            item.symbol || ""
                        )}"
                    >
                        ${escapeHTML(
                            item.symbol || "—"
                        )}
                    </button>

                    <small>
                        ${market}
                        ${
                            futures
                                ? ` • ${escapeHTML(
                                    leverage
                                )}`
                                : ""
                        }
                    </small>

                </div>


                <span class="${signalClass(
                    item.signal
                )}">
                    ${signalIcon(
                        item.signal
                    )}
                    ${escapeHTML(
                        item.signal || "—"
                    )}
                </span>

            </div>


            <div class="trade-levels">

                <div>
                    <span>الدخول</span>
                    <b>
                        ${price(
                            item.entry ??
                            item.price
                        )}
                    </b>
                </div>


                <div>
                    <span>TP1</span>
                    <b>
                        ${price(
                            item.tp1
                        )}
                    </b>
                </div>


                <div>
                    <span>TP2</span>
                    <b>
                        ${price(
                            item.tp2
                        )}
                    </b>
                </div>


                <div>
                    <span>TP3</span>
                    <b>
                        ${price(
                            item.tp3
                        )}
                    </b>
                </div>


                <div>
                    <span>وقف</span>
                    <b>
                        ${price(
                            item.sl
                        )}
                    </b>
                </div>

            </div>


            <div class="trade-meta">

                <span>
                    القوة:
                    <b>
                        ${number(
                            item.score,
                            1
                        )}
                    </b>
                </span>


                <span>
                    RSI:
                    <b>
                        ${number(
                            item.rsi,
                            2
                        )}
                    </b>
                </span>


                <span>
                    24س:
                    <b>
                        ${percent(
                            item.change
                        )}
                    </b>
                </span>


                ${
                    futures
                        ? `
                        <span>
                            الرافعة:
                            <b>
                                ${escapeHTML(
                                    leverage
                                )}
                            </b>
                        </span>
                        `
                        : ""
                }

            </div>

        </article>
        `;
    }


    // =========================================================
    // CLEAR SPOT
    // =========================================================

    function initClearRecent() {

        $("clearRecent")?.addEventListener(
            "click",
            () => {

                state.spotResults = [];

                try {

                    localStorage.removeItem(
                        "mudarib_spot_results"
                    );

                } catch (_) {}

                renderSpot();
            }
        );
    }


    // =========================================================
    // US MARKET
    // =========================================================

    async function loadUSMarket() {

        const box =
            $("usMarketList");

        if (!box) {
            return;
        }


        box.innerHTML =
            `
            <div class="panel">
                ⏳ جاري تحميل صفقات السوق الأمريكي...
            </div>
            `;


        try {

            const data =
                await fetchBybitService(
                    "/us/scan?interval=15m&limit=40"
                );


            // عرض الصفقات الفعلية فقط:
            // شراء أو بيع — وإخفاء الحيادي
            state.usResults =
                (
                    data.results ||
                    data.data ||
                    []
                ).filter(
                    item =>
                        item.direction === "buy" ||
                        item.direction === "sell"
                );


            if (
                !state.usResults.length
            ) {

                box.innerHTML =
                    `
                    <div class="panel">
                        لا توجد صفقات أمريكية حالياً.
                    </div>
                    `;

                return;
            }


            renderUSCards(
                box,
                state.usResults
            );

        } catch (error) {

            box.innerHTML =
                `
                <div class="panel">
                    تعذر تحميل صفقات السوق الأمريكي:
                    ${escapeHTML(
                        error.message
                    )}
                </div>
                `;
        }
    }


    function renderUSCards(
        container,
        results
    ) {

        container.innerHTML =
            results.map(
                item => `

                <article class="trade-card">

                    <div class="trade-card-head">

                        <div>

                            <b>
                                ${escapeHTML(
                                    item.underlyingTicker ||
                                    item.symbol ||
                                    "—"
                                )}
                            </b>

                            <small>
                                🇺🇸
                                ${escapeHTML(
                                    item.name ||
                                    item.fullName ||
                                    ""
                                )}
                            </small>

                        </div>


                        <span class="${signalClass(
                            item.signal
                        )}">
                            ${signalIcon(
                                item.signal
                            )}
                            ${escapeHTML(
                                item.signal ||
                                "—"
                            )}
                        </span>

                    </div>


                    <div class="trade-levels">

                        <div>
                            <span>السعر</span>
                            <b>
                                ${price(
                                    item.price
                                )}
                            </b>
                        </div>

                        <div>
                            <span>الدخول</span>
                            <b>
                                ${price(
                                    item.entry
                                )}
                            </b>
                        </div>

                        <div>
                            <span>TP1</span>
                            <b>
                                ${price(
                                    item.tp1
                                )}
                            </b>
                        </div>

                        <div>
                            <span>TP2</span>
                            <b>
                                ${price(
                                    item.tp2
                                )}
                            </b>
                        </div>

                        <div>
                            <span>وقف</span>
                            <b>
                                ${price(
                                    item.sl
                                )}
                            </b>
                        </div>

                    </div>


                    <div class="trade-meta">

                        <span>
                            التغير:
                            <b>
                                ${percent(
                                    item.change
                                )}
                            </b>
                        </span>

                        <span>
                            القوة:
                            <b>
                                ${number(
                                    item.score,
                                    1
                                )}
                            </b>
                        </span>

                    </div>

                </article>
                `
            ).join("");
    }


    // =========================================================
    // BYBIT SERVICE
    // =========================================================

    async function fetchBybitService(
        path
    ) {

        /*
         * إذا ربطت bybit_service داخل server.py
         * اجعل هذا المسار:
         *
         * /api/bybit/...
         *
         * أو:
         *
         * /bybit/...
         *
         * هنا نجرّب المسار المباشر أولاً،
         * ثم مسار /api/bybit.
         */

        const paths = [

            `/api/bybit${path}`,

            `/bybit${path}`,

            path
        ];


        let lastError =
            "تعذر الاتصال بخدمة Bybit";


        for (
            const url of paths
        ) {

            try {

                const response =
                    await fetch(
                        url,
                        {
                            credentials:
                                "same-origin"
                        }
                    );


                if (
                    response.status === 404
                ) {

                    continue;
                }


                const data =
                    await response.json();


                if (!response.ok) {

                    throw new Error(
                        data.message ||
                        `HTTP ${response.status}`
                    );
                }


                if (
                    data.ok === false
                    &&
                    !data.results
                ) {

                    throw new Error(
                        data.message ||
                        "خدمة Bybit غير متاحة"
                    );
                }


                return data;

            } catch (error) {

                lastError =
                    error.message;
            }
        }


        throw new Error(
            lastError
        );
    }


    // =========================================================
    // SAUDI MARKET
    // =========================================================

    async function loadSaudiMarket() {

        try {

            const data =
                await fetchBybitService(
                    "/saudi/market"
                );

            state.saudiResults =
                data.results ||
                data.data ||
                [];

            return state.saudiResults;

        } catch (error) {

            console.error(
                "Saudi market:",
                error
            );

            return [];
        }
    }


    // =========================================================
    // NEWS
    // =========================================================

    async function loadNews() {

        const box =
            $("newsList");

        if (!box) {
            return;
        }


        box.innerHTML =
            `
            <div class="panel">
                ⏳ جاري تحميل الأخبار...
            </div>
            `;


        try {

            const data =
                await api(
                    "/api/news"
                );

            const items =
                data.items ||
                data.results ||
                data.news ||
                [];


            if (!items.length) {

                box.innerHTML =
                    `
                    <div class="panel">
                        لا توجد أخبار حالياً.
                    </div>
                    `;

                return;
            }


            box.innerHTML =
                items
                    .map(
                        item => `

                        <article class="news-card">

                            <h3>
                                ${escapeHTML(
                                    item.title ||
                                    item.name ||
                                    "خبر"
                                )}
                            </h3>

                            <p>
                                ${escapeHTML(
                                    item.description ||
                                    item.summary ||
                                    ""
                                )}
                            </p>

                            ${
                                item.url
                                    ? `
                                    <a
                                        href="${escapeHTML(
                                            item.url
                                        )}"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        قراءة الخبر
                                    </a>
                                    `
                                    : ""
                            }

                        </article>
                        `
                    )
                    .join("");

        } catch (error) {

            box.innerHTML =
                `
                <div class="panel">
                    تعذر تحميل الأخبار:
                    ${escapeHTML(
                        error.message
                    )}
                </div>
                `;
        }
    }


    // =========================================================
    // SUBSCRIPTION
    // =========================================================

    async function loadSubscription() {

        if (!state.user) {

            showSection(
                "dashboard"
            );

            return;
        }


        try {

            const data =
                await api(
                    "/api/subscription"
                );

            renderSubscription(
                data
            );

        } catch (error) {

            console.error(
                error
            );

            loadPlans();
        }
    }


    async function loadPlans() {

        try {

            const data =
                await api(
                    "/api/plans"
                );

            renderPlans(
                data
            );

        } catch (_) {

            renderPlans({
                plans: [
                    {
                        id: "7d",
                        name: "7 أيام",
                        days: 7,
                        amount: 10
                    },
                    {
                        id: "15d",
                        name: "15 يوم",
                        days: 15,
                        amount: 20
                    },
                    {
                        id: "30d",
                        name: "30 يوم",
                        days: 30,
                        amount: 30
                    }
                ]
            });
        }
    }


    function renderSubscription(
        data
    ) {

        if ($("subscriptionStatus")) {

            const plan =
                data.plan ||
                state.user?.plan ||
                "free";

            const expires =
                data.plan_expires ||
                state.user?.plan_expires;

            $("subscriptionStatus").innerHTML =
                `
                <div class="panel">
                    الباقة الحالية:
                    <b>${escapeHTML(
                        plan
                    )}</b>
                    ${
                        expires
                            ? `
                            <br>
                            تنتهي:
                            ${escapeHTML(
                                formatDate(
                                    expires
                                )
                            )}
                            `
                            : ""
                    }
                </div>
                `;
        }


        renderPlans(
            data
        );
    }


    function renderPlans(
        data
    ) {

        const box =
            $("plans");

        if (!box) {
            return;
        }


        const plans =
            data.plans ||
            data.results ||
            [
                {
                    id: "7d",
                    name: "7 أيام",
                    days: 7,
                    amount: 10
                },
                {
                    id: "15d",
                    name: "15 يوم",
                    days: 15,
                    amount: 20
                },
                {
                    id: "30d",
                    name: "30 يوم",
                    days: 30,
                    amount: 30
                }
            ];


        box.innerHTML =
            plans
                .map(
                    plan => `

                    <div class="plan-card">

                        <h3>
                            ${escapeHTML(
                                plan.name ||
                                `${plan.days} يوم`
                            )}
                        </h3>

                        <strong>
                            ${number(
                                plan.amount,
                                2
                            )}
                            USDT
                        </strong>

                        <button
                            class="btn primary"
                            data-plan-id="${escapeHTML(
                                plan.id ||
                                plan.code ||
                                ""
                            )}"
                        >
                            اختيار الباقة
                        </button>

                    </div>
                    `
                )
                .join("");


        qsa(
            "[data-plan-id]",
            box
        ).forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        selectPlan(
                            button.dataset.planId,
                            plans
                        );
                    }
                );
            }
        );
    }


    function selectPlan(
        planId,
        plans
    ) {

        state.selectedPlan =
            plans.find(
                plan =>
                    String(
                        plan.id ||
                        plan.code
                    )
                    ===
                    String(planId)
            );


        if (!state.selectedPlan) {
            return;
        }


        const paymentBox =
            $("paymentBox");

        if (paymentBox) {
            paymentBox.hidden =
                false;
        }


        if ($("chosenPlan")) {

            $("chosenPlan").textContent =
                `${
                    state.selectedPlan.name ||
                    `${state.selectedPlan.days} يوم`
                } — ${
                    state.selectedPlan.amount
                } USDT`;
        }


        loadPaymentInfo();

        paymentBox?.scrollIntoView({
            behavior: "smooth",
            block: "center"
        });
    }


    async function loadPaymentInfo() {

        try {

            const data =
                await api(
                    "/api/payment/info"
                );

            const address =
                data.address ||
                data.payment_address ||
                data.trc20_address ||
                "";

            if ($("payAddress")) {

                $("payAddress").value =
                    address;
            }


            if (
                address
                &&
                window.QRCode
                &&
                $("qrBox")
            ) {

                $("qrBox").innerHTML =
                    "";

                QRCode.toCanvas(
                    address,
                    {
                        width: 180
                    },
                    (
                        error,
                        canvas
                    ) => {

                        if (
                            !error
                            &&
                            canvas
                        ) {

                            $("qrBox")
                                .appendChild(
                                    canvas
                                );
                        }
                    }
                );
            }

        } catch (_) {}
    }


    // =========================================================
    // PAYMENT
    // =========================================================

    function initPayment() {

        $("copyAddress")?.addEventListener(
            "click",
            async () => {

                const address =
                    $("payAddress")?.value ||
                    "";

                if (!address) {
                    return;
                }

                try {

                    await navigator.clipboard.writeText(
                        address
                    );

                    setPaymentMessage(
                        "تم نسخ العنوان ✅"
                    );

                } catch (_) {

                    $("payAddress")?.select();

                    document.execCommand(
                        "copy"
                    );

                    setPaymentMessage(
                        "تم النسخ ✅"
                    );
                }
            }
        );


        $("sendPayment")?.addEventListener(
            "click",
            sendPayment
        );
    }


    async function sendPayment() {

        if (!state.selectedPlan) {

            setPaymentMessage(
                "اختر الباقة أولاً",
                true
            );

            return;
        }


        const txid =
            $("txid")?.value.trim();


        if (!txid) {

            setPaymentMessage(
                "أدخل TXID بعد التحويل",
                true
            );

            return;
        }


        const button =
            $("sendPayment");

        if (button) {

            button.disabled = true;

            button.textContent =
                "⏳ جاري الإرسال...";
        }


        try {

            await api(
                "/api/payment/request",
                {
                    method: "POST",
                    body: JSON.stringify({

                        plan:
                            state.selectedPlan.id ||
                            state.selectedPlan.code,

                        txid
                    })
                }
            );


            setPaymentMessage(
                "تم إرسال طلب الاشتراك للإدارة ✅"
            );


            if ($("txid")) {
                $("txid").value = "";
            }


            loadPaymentHistory();

        } catch (error) {

            setPaymentMessage(
                error.message,
                true
            );

        } finally {

            if (button) {

                button.disabled = false;

                button.textContent =
                    "إرسال طلب الاشتراك";
            }
        }
    }


    function setPaymentMessage(
        message,
        error = false
    ) {

        const el =
            $("paymentMsg");

        if (!el) {
            return;
        }

        el.textContent =
            message;

        el.classList.toggle(
            "error",
            error
        );
    }


    async function loadPaymentHistory() {

        try {

            const data =
                await api(
                    "/api/payment/history"
                );

            const box =
                $("paymentHistory");

            if (!box) {
                return;
            }


            const items =
                data.items ||
                data.results ||
                [];


            if (!items.length) {

                box.innerHTML =
                    "";

                return;
            }


            box.innerHTML =
                `
                <div class="panel">

                    <h3>
                        طلبات الاشتراك
                    </h3>

                    ${items.map(
                        item => `
                        <div class="payment-history-item">

                            <b>
                                ${escapeHTML(
                                    item.plan ||
                                    ""
                                )}
                            </b>

                            <span>
                                ${escapeHTML(
                                    item.status ||
                                    ""
                                )}
                            </span>

                            <small>
                                ${formatDate(
                                    item.created_at
                                )}
                            </small>

                        </div>
                        `
                    ).join("")}

                </div>
                `;

        } catch (_) {}
    }


    // =========================================================
    // THEME
    // =========================================================

    function initTheme() {

        const saved =
            localStorage.getItem(
                "mudarib_theme"
            );


        if (saved === "dark") {

            document.body.classList.add(
                "dark"
            );
        }


        updateThemeButton();


        $("themeBtn")?.addEventListener(
            "click",
            () => {

                document.body.classList.toggle(
                    "dark"
                );

                localStorage.setItem(
                    "mudarib_theme",
                    document.body.classList.contains(
                        "dark"
                    )
                        ? "dark"
                        : "light"
                );

                updateThemeButton();
            }
        );
    }


    function updateThemeButton() {

        const button =
            $("themeBtn");

        if (!button) {
            return;
        }

        button.textContent =
            document.body.classList.contains(
                "dark"
            )
                ? "☀️ الوضع النهاري"
                : "🌙 الوضع الليلي";
    }


    // =========================================================
    // NEWS BUTTON
    // =========================================================

    function initNews() {

        $("newsBtn")?.addEventListener(
            "click",
            loadNews
        );
    }


    // =========================================================
    // DATE
    // =========================================================

    function formatDate(
        value
    ) {

        if (!value) {
            return "—";
        }

        const date =
            new Date(value);

        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return String(
                value
            );
        }

        return date.toLocaleString(
            "ar-SA",
            {
                dateStyle: "medium",
                timeStyle: "short"
            }
        );
    }


    // =========================================================
    // STARTUP
    // =========================================================

    async function init() {

        loadLocalResults();

        initNavigation();

        initAuth();

        initDashboardIntervals();

        initScanner();

        initClearRecent();

        initPayment();

        initTheme();

        initNews();

        renderSpot();

        updateAuthUI();

        setStatus(
            "جاري الاتصال..."
        );


        await loadAuth();

        await loadDashboardAnalysis();

        if (
            state.currentSection ===
            "dashboard"
        ) {

            loadDashboardAnalysis();
        }
    }


    // =========================================================
    // START
    // =========================================================

    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            init
        );

    } else {

        init();
    }

})();

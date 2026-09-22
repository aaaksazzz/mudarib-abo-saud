(() => {
    "use strict";

    const $ = id => document.getElementById(id);

    const state = {
        user: null,
        admin: false,
        interval: "15m",
        symbol: "BTCUSDT",
        results: [],
        signals: new Set(),
        sort: "change",
        dir: -1,
        busy: false,
        chart: null,
        plan: null,
        usResults: [],
        recent: JSON.parse(
            localStorage.getItem("mudarib_recent") || "[]"
        )
    };

    const signalRank = {
        "شراء قوي": 5,
        "شراء": 4,
        "حيادي": 3,
        "بيع": 2,
        "بيع قوي": 1
    };

    const api = async (url, opt = {}) => {
        const options = {
            ...opt,
            headers: {
                "Content-Type": "application/json",
                ...(opt.headers || {})
            }
        };

        const r = await fetch(url, options);

        let d = {};

        try {
            d = await r.json();
        } catch {}

        if (!r.ok || d.ok === false) {
            throw new Error(
                d.message ||
                d.error ||
                `HTTP ${r.status}`
            );
        }

        return d;
    };

    function fmt(v) {
        if (
            v == null ||
            Number.isNaN(Number(v))
        ) {
            return "—";
        }

        v = Number(v);

        if (v === 0) return "0";

        if (Math.abs(v) >= 1000) {
            return v.toLocaleString("en-US", {
                maximumFractionDigits: 2
            });
        }

        if (Math.abs(v) >= 1) {
            return v.toLocaleString("en-US", {
                maximumFractionDigits: 4
            });
        }

        return v.toLocaleString("en-US", {
            maximumFractionDigits: 8
        });
    }

    function pct(v) {
        v = Number(v || 0);

        return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
    }

    function money(v) {
        v = Number(v || 0);

        if (v >= 1e9) {
            return `${(v / 1e9).toFixed(2)}B`;
        }

        if (v >= 1e6) {
            return `${(v / 1e6).toFixed(2)}M`;
        }

        if (v >= 1e3) {
            return `${(v / 1e3).toFixed(1)}K`;
        }

        return fmt(v);
    }

    function sigClass(s) {
        if (
            s === "شراء قوي" ||
            s === "شراء"
        ) {
            return "buy";
        }

        if (
            s === "بيع قوي" ||
            s === "بيع"
        ) {
            return "sell";
        }

        return "neutral";
    }

    function escapeHTML(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    /* ========================= MENU ========================= */

    function closeMenu() {
        document.body.classList.remove("menu-open");
    }

    function showSection(id) {
        document.querySelectorAll(".section").forEach(x => {
            x.classList.toggle(
                "active",
                x.id === id
            );
        });

        document.querySelectorAll(".nav-item").forEach(x => {
            x.classList.toggle(
                "active",
                x.dataset.section === id
            );
        });

        const names = {
            dashboard: "الرئيسية",
            scanner: "ماسح الفرص",
            recent: "الصفقات الحديثة",
            alpha: "صفقات Alpha",
            futures: "صفقات الفيوتشر",
            "us-market": "صفقات السوق الأمريكي",
            news: "الأخبار",
            subscription: "الاشتراك"
        };

        if ($("pageTitle")) {
            $("pageTitle").textContent =
                names[id] || "الرئيسية";
        }

        closeMenu();

        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });

        if (id === "us-market") {
            loadUSMarket();
        }

        if (id === "news") {
            loadNews();
        }

        if (id === "subscription" && state.user) {
            loadSubscription();
        }
    }

    document.querySelectorAll(".nav-item").forEach(b => {
        b.addEventListener("click", e => {
            e.preventDefault();

            showSection(
                b.dataset.section
            );
        });
    });

    if ($("menuBtn")) {
        $("menuBtn").onclick = e => {
            e.stopPropagation();

            document.body.classList.toggle(
                "menu-open"
            );
        };
    }

    document.addEventListener("click", e => {
        if (
            !document.body.classList.contains(
                "menu-open"
            )
        ) {
            return;
        }

        const sidebar = $("sidebar");
        const menu = $("menuBtn");

        if (
            sidebar &&
            !sidebar.contains(e.target) &&
            menu &&
            !menu.contains(e.target)
        ) {
            closeMenu();
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 1000) {
            closeMenu();
        }
    });

    /* ========================= AUTH MODAL ========================= */

    function openAuth(tab = "login") {
        const modal = $("authModal");

        if (!modal) return;

        modal.hidden = false;
        modal.classList.add("show");

        const loginBox = $("loginBox");
        const registerBox = $("registerBox");

        if (loginBox) {
            loginBox.hidden =
                tab !== "login";
        }

        if (registerBox) {
            registerBox.hidden =
                tab !== "register";
        }

        if ($("loginTab")) {
            $("loginTab").classList.toggle(
                "active",
                tab === "login"
            );
        }

        if ($("registerTab")) {
            $("registerTab").classList.toggle(
                "active",
                tab === "register"
            );
        }

        if (tab === "login") {
            setTimeout(() => {
                $("modalLoginEmail")?.focus();
            }, 50);
        } else {
            setTimeout(() => {
                $("modalRegisterName")?.focus();
            }, 50);
        }
    }

    function closeAuth() {
        const modal = $("authModal");

        if (!modal) return;

        modal.classList.remove("show");
        modal.hidden = true;

        clearAuthMessages();
    }

    function clearAuthMessages() {
        const loginMessage =
            $("modalLoginMessage");

        const registerMessage =
            $("modalRegisterMessage");

        if (loginMessage) {
            loginMessage.textContent = "";
            loginMessage.innerHTML = "";
            loginMessage.style.display = "none";
        }

        if (registerMessage) {
            registerMessage.textContent = "";
            registerMessage.innerHTML = "";
            registerMessage.style.display = "none";
        }
    }

    function showAuthMessage(
        id,
        message,
        error = false
    ) {
        const el = $(id);

        if (!el) return;

        el.innerHTML = "";

        const span =
            document.createElement("span");

        span.className =
            error ? "error" : "ok";

        span.textContent = message;

        el.appendChild(span);

        el.style.display = "block";
    }

    if ($("authModalClose")) {
        $("authModalClose").onclick = () => {
            closeAuth();
        };
    }

    if ($("authModalOverlay")) {
        $("authModalOverlay").onclick = () => {
            closeAuth();
        };
    }

    if ($("loginBtn")) {
        $("loginBtn").onclick = () => {
            openAuth("login");
        };
    }

    if ($("registerBtn")) {
        $("registerBtn").onclick = () => {
            openAuth("register");
        };
    }

    if ($("showRegister")) {
        $("showRegister").onclick = () => {
            openAuth("register");
        };
    }

    if ($("showLogin")) {
        $("showLogin").onclick = () => {
            openAuth("login");
        };
    }

    document.addEventListener("keydown", e => {
        if (e.key !== "Escape") return;

        const modal = $("authModal");

        if (
            modal &&
            !modal.hidden
        ) {
            closeAuth();
        }
    });

    /* ========================= AUTH CHECK ========================= */

    async function checkAuth() {
        try {
            const d =
                await api("/api/auth/me");

            state.user =
                d.user || null;

            updateAuth();
        } catch {
            state.user = null;
            updateAuth();
        }

        try {
            const a =
                await api("/api/admin/me");

            state.admin =
                !!a.admin;

            if ($("adminLink")) {
                $("adminLink").hidden =
                    !state.admin;
            }
        } catch {
            state.admin = false;

            if ($("adminLink")) {
                $("adminLink").hidden = true;
            }
        }
    }

    function updateAuth() {
        const logged =
            !!state.user;

        if ($("userBadge")) {
            $("userBadge").textContent =
                logged
                    ? (
                        state.user.name ||
                        state.user.email ||
                        "مستخدم"
                    )
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

        if ($("subscription")) {
            $("subscription").hidden =
                !logged;
        }

        if (logged) {
            loadSubscription();
        }
    }

    /* ========================= LOGIN ========================= */

    if ($("modalLoginForm")) {
        $("modalLoginForm").onsubmit =
            async e => {
                e.preventDefault();

                const email =
                    $("modalLoginEmail")
                        ?.value
                        .trim()
                        .toLowerCase();

                const password =
                    $("modalLoginPassword")
                        ?.value || "";

                if (!email) {
                    showAuthMessage(
                        "modalLoginMessage",
                        "فضلاً اكتب البريد الإلكتروني.",
                        true
                    );
                    return;
                }

                if (!password) {
                    showAuthMessage(
                        "modalLoginMessage",
                        "فضلاً اكتب كلمة المرور.",
                        true
                    );
                    return;
                }

                const btn =
                    $("modalLoginSubmit");

                if (btn) {
                    btn.disabled = true;
                    btn.textContent =
                        "⏳ جاري الدخول...";
                }

                try {
                    const d =
                        await api(
                            "/api/auth/login",
                            {
                                method: "POST",
                                body: JSON.stringify({
                                    email,
                                    password
                                })
                            }
                        );

                    state.user =
                        d.user || null;

                    showAuthMessage(
                        "modalLoginMessage",
                        "تم تسجيل الدخول بنجاح ✅",
                        false
                    );

                    updateAuth();

                    setTimeout(() => {
                        closeAuth();
                    }, 500);
                } catch (err) {
                    showAuthMessage(
                        "modalLoginMessage",
                        err.message ||
                            "بيانات الدخول غير صحيحة.",
                        true
                    );
                } finally {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent =
                            "🔐 تسجيل الدخول";
                    }
                }
            };
    }

    /* ========================= REGISTER ========================= */

    if ($("modalRegisterForm")) {
        $("modalRegisterForm").onsubmit =
            async e => {
                e.preventDefault();

                const name =
                    $("modalRegisterName")
                        ?.value
                        .trim() || "";

                const email =
                    $("modalRegisterEmail")
                        ?.value
                        .trim()
                        .toLowerCase() || "";

                const password =
                    $("modalRegisterPassword")
                        ?.value || "";

                if (name.length < 2) {
                    showAuthMessage(
                        "modalRegisterMessage",
                        "فضلاً اكتب الاسم بشكل صحيح.",
                        true
                    );
                    return;
                }

                if (
                    !email ||
                    !email.includes("@")
                ) {
                    showAuthMessage(
                        "modalRegisterMessage",
                        "فضلاً اكتب بريد إلكتروني صحيح.",
                        true
                    );
                    return;
                }

                if (password.length < 6) {
                    showAuthMessage(
                        "modalRegisterMessage",
                        "كلمة المرور يجب أن تكون 6 أحرف على الأقل.",
                        true
                    );
                    return;
                }

                const btn =
                    $("modalRegisterSubmit");

                if (btn) {
                    btn.disabled = true;
                    btn.textContent =
                        "⏳ جاري إنشاء الحساب...";
                }

                try {
                    const d =
                        await api(
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

                    state.user =
                        d.user || null;

                    showAuthMessage(
                        "modalRegisterMessage",
                        "تم إنشاء الحساب بنجاح ✅",
                        false
                    );

                    updateAuth();

                    setTimeout(() => {
                        closeAuth();
                    }, 700);
                } catch (err) {
                    showAuthMessage(
                        "modalRegisterMessage",
                        err.message ||
                            "تعذر إنشاء الحساب.",
                        true
                    );
                } finally {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent =
                            "📝 إنشاء الحساب";
                    }
                }
            };
    }

    /* ========================= LOGOUT ========================= */

    if ($("logoutBtn")) {
        $("logoutBtn").onclick =
            async () => {
                try {
                    await api(
                        "/api/auth/logout",
                        {
                            method: "POST"
                        }
                    );
                } catch {}

                state.user = null;
                state.admin = false;

                updateAuth();

                if ($("adminLink")) {
                    $("adminLink").hidden =
                        true;
                }

                showSection("dashboard");
            };
    }

    /* ========================= DASHBOARD INTERVAL ========================= */

    document
        .querySelectorAll(
            "#dashIntervals button"
        )
        .forEach(b => {
            b.onclick = () => {
                document
                    .querySelectorAll(
                        "#dashIntervals button"
                    )
                    .forEach(x => {
                        x.classList.remove(
                            "active"
                        );
                    });

                b.classList.add("active");

                state.interval =
                    b.dataset.interval;

                loadAnalysis();
            };
        });

    /* ========================= SCANNER INTERVAL ========================= */

    document
        .querySelectorAll(
            "#intervalChips button"
        )
        .forEach(b => {
            b.onclick = () => {
                document
                    .querySelectorAll(
                        "#intervalChips button"
                    )
                    .forEach(x => {
                        x.classList.remove(
                            "active"
                        );
                    });

                b.classList.add("active");

                state.interval =
                    b.dataset.interval;

                runScanner();
            };
        });

    /* ========================= SIGNAL FILTERS ========================= */

    document
        .querySelectorAll(
            ".signal-chips button"
        )
        .forEach(b => {
            b.onclick = () => {
                b.classList.toggle("active");

                const s =
                    b.dataset.signal;

                if (state.signals.has(s)) {
                    state.signals.delete(s);
                } else {
                    state.signals.add(s);
                }

                renderScanner();
            };
        });

    if ($("sortField")) {
        $("sortField").onchange =
            e => {
                state.sort =
                    e.target.value;

                renderScanner();
            };
    }

    if ($("sortDir")) {
        $("sortDir").onclick = () => {
            state.dir *= -1;

            $("sortDir").textContent =
                state.dir === -1
                    ? "↓ تنازلي"
                    : "↑ تصاعدي";

            renderScanner();
        };
    }

    if ($("scannerSearch")) {
        $("scannerSearch").oninput =
            renderScanner;
    }

    if ($("scanBtn")) {
        $("scanBtn").onclick =
            runScanner;
    }

    /* ========================= FILTER ========================= */

    function filtered() {
        let a = [...state.results];

        const q =
            $("scannerSearch")
                ? $("scannerSearch")
                    .value
                    .trim()
                    .toUpperCase()
                : "";

        if (q) {
            a = a.filter(x =>
                String(
                    x.symbol || ""
                ).includes(q)
            );
        }

        if (state.signals.size) {
            a = a.filter(x =>
                state.signals.has(
                    x.signal
                )
            );
        }

        const f = state.sort;

        a.sort((x, y) => {
            let av =
                f === "signal"
                    ? signalRank[
                        x.signal
                    ] || 0
                    : f === "symbol"
                    ? x.symbol
                    : x[f] ?? 0;

            let bv =
                f === "signal"
                    ? signalRank[
                        y.signal
                    ] || 0
                    : f === "symbol"
                    ? y.symbol
                    : y[f] ?? 0;

            if (
                typeof av === "string"
            ) {
                return (
                    av.localeCompare(bv) *
                    state.dir
                );
            }

            return (
                Number(av) -
                Number(bv)
            ) * state.dir;
        });

        return a;
    }

    /* ========================= SCANNER RENDER ========================= */

    function renderScanner() {
        if (!$("scannerBody")) return;

        const rows =
            filtered();

        $("scannerBody").innerHTML =
            rows.length
                ? rows.map(x => `
                    <div class="scanner-row">
                        <strong>
                            ${escapeHTML(
                                String(
                                    x.symbol || ""
                                ).replace(
                                    "USDT",
                                    ""
                                )
                            )}
                        </strong>

                        <span>
                            USDT
                        </span>

                        <span>
                            ${fmt(x.price)}
                        </span>

                        <span>
                            ${pct(x.change)}
                        </span>

                        <span class="${sigClass(
                            x.signal
                        )}">
                            ${escapeHTML(
                                x.signal
                            )}
                        </span>

                        <span>
                            ${x.score10 ?? "—"}/10
                        </span>

                        <span>
                            ${money(x.volume)}
                        </span>

                        <span>
                            ${x.interval ||
                                state.interval}
                        </span>
                    </div>
                `).join("")
                : `
                    <div class="empty-state">
                        لا توجد نتائج مطابقة
                    </div>
                `;
    }

    /* ========================= RUN SCANNER ========================= */

    async function runScanner() {
        if (state.busy) return;

        state.busy = true;

        if ($("scannerStatus")) {
            $("scannerStatus").textContent =
                "جاري فحص أعلى العملات سيولة...";
        }

        try {
            const d =
                await api(
                    `/api/binance/scan?interval=${encodeURIComponent(
                        state.interval
                    )}&limit=40`
                );

            state.results =
                d.results || [];

            if ($("scannerStatus")) {
                $("scannerStatus").textContent =
                    `تم العثور على ${state.results.length} فرصة` +
                    (
                        d.cached
                            ? " — نتيجة محفوظة مؤقتًا"
                            : ""
                    );
            }

            renderScanner();
            captureRecent();
        } catch (e) {
            if ($("scannerStatus")) {
                $("scannerStatus").textContent =
                    `تعذر الفحص: ${e.message}`;
            }
        } finally {
            state.busy = false;
        }
    }

    /* ========================= RECENT ========================= */

    function captureRecent() {
        const now = Date.now();

        const bucket =
            Math.floor(
                now / 300000
            );

        const old =
            new Set(
                state.recent.map(
                    x => x.key
                )
            );

        state.results
            .filter(
                x =>
                    x.signal !==
                    "حيادي"
            )
            .slice(0, 15)
            .forEach(x => {
                const key =
                    `${x.symbol}|${x.interval}|${x.signal}|${bucket}`;

                if (!old.has(key)) {
                    state.recent.unshift({
                        ...x,
                        key,
                        time: now
                    });
                }
            });

        state.recent =
            state.recent.slice(
                0,
                60
            );

        localStorage.setItem(
            "mudarib_recent",
            JSON.stringify(
                state.recent
            )
        );

        renderRecent();
    }

    function renderRecent() {
        if (!$("recentList")) return;

        const a =
            state.recent;

        if (!a.length) {
            $("recentList").innerHTML = `
                <div class="empty-state">
                    ما فيه فرص حديثة حتى الآن. شغّل الماسح.
                </div>
            `;

            return;
        }

        $("recentList").innerHTML =
            a.slice(0, 30)
                .map(x => `
                    <div class="recent-card">

                        <div>
                            <strong>
                                ${escapeHTML(
                                    x.symbol
                                )}
                            </strong>

                            <span>
                                ${new Date(
                                    x.time
                                ).toLocaleString(
                                    "ar-SA"
                                )}
                            </span>
                        </div>

                        <div class="${sigClass(
                            x.signal
                        )}">
                            ${escapeHTML(
                                x.signal
                            )}
                        </div>

                        <div>
                            السعر
                            <strong>
                                ${fmt(x.price)}
                            </strong>
                        </div>

                        <div>
                            ${pct(x.change)}
                        </div>

                        <div>
                            TP1 / وقف
                            <strong>
                                ${fmt(x.tp1)}
                                /
                                ${fmt(x.sl)}
                            </strong>
                        </div>

                    </div>
                `)
                .join("");
    }

    if ($("clearRecent")) {
        $("clearRecent").onclick =
            () => {
                state.recent = [];

                localStorage.removeItem(
                    "mudarib_recent"
                );

                renderRecent();
            };
    }

    /* ========================= DASHBOARD ANALYSIS ========================= */

    async function loadAnalysis() {
        const sym =
            state.symbol;

        try {
            const d =
                await api(
                    `/api/binance/analysis?symbol=${encodeURIComponent(
                        sym
                    )}&interval=${encodeURIComponent(
                        state.interval
                    )}`
                );

            const a =
                d.analysis;

            if ($("dashSymbol")) {
                $("dashSymbol").textContent =
                    sym;
            }

            if ($("targetCoin")) {
                $("targetCoin").textContent =
                    sym;
            }

            if ($("dashPrice")) {
                $("dashPrice").textContent =
                    fmt(a.price);
            }

            if ($("dashChange")) {
                $("dashChange").textContent =
                    a.change != null
                        ? pct(a.change)
                        : "—";
            }

            if ($("dashSignal")) {
                $("dashSignal").textContent =
                    a.signal;

                $("dashSignal").className =
                    `signal-text ${sigClass(
                        a.signal
                    )}`;
            }

            if ($("bigSignal")) {
                $("bigSignal").textContent =
                    a.signal;

                $("bigSignal").className =
                    `signal-big ${sigClass(
                        a.signal
                    )}`;
            }

            if ($("scoreText")) {
                $("scoreText").textContent =
                    `${a.score}/100`;
            }

            if ($("scoreBar")) {
                $("scoreBar").style.width =
                    `${Math.max(
                        0,
                        Math.min(
                            100,
                            Number(
                                a.score || 0
                            )
                        )
                    )}%`;
            }

            if ($("entry")) {
                $("entry").textContent =
                    fmt(a.entry);
            }

            if ($("tp1")) {
                $("tp1").textContent =
                    fmt(a.tp1);
            }

            if ($("tp2")) {
                $("tp2").textContent =
                    fmt(a.tp2);
            }

            if ($("tp3")) {
                $("tp3").textContent =
                    fmt(a.tp3);
            }

            if ($("sl")) {
                $("sl").textContent =
                    fmt(a.sl);
            }

            if ($("rsi")) {
                $("rsi").textContent =
                    a.rsi != null
                        ? Number(
                            a.rsi
                        ).toFixed(1)
                        : "—";
            }

            if ($("ema20")) {
                $("ema20").textContent =
                    fmt(a.ema20);
            }

            if ($("ema50")) {
                $("ema50").textContent =
                    fmt(a.ema50);
            }

            if ($("ema200")) {
                $("ema200").textContent =
                    fmt(a.ema200);
            }

            if ($("analysisMeta")) {
                $("analysisMeta").textContent =
                    `${sym} · ${state.interval}`;
            }

            if ($("reasons")) {
                $("reasons").innerHTML =
                    (a.reasons || [])
                        .map(x => `
                            <div class="reason">
                                ${escapeHTML(x)}
                            </div>
                        `)
                        .join("");
            }

            drawChart(
                a.candles || []
            );
        } catch (e) {
            if ($("bigSignal")) {
                $("bigSignal").textContent =
                    e.message;
            }
        }
    }

    window.selectSymbol =
        s => {
            state.symbol = s;

            showSection(
                "dashboard"
            );

            loadAnalysis();
        };

    /* ========================= CHART ========================= */

    function drawChart(c) {
        const canvas =
            $("priceChart");

        if (
            !canvas ||
            typeof Chart ===
                "undefined"
        ) {
            return;
        }

        const ctx =
            canvas.getContext("2d");

        if (state.chart) {
            state.chart.destroy();
        }

        state.chart =
            new Chart(
                ctx,
                {
                    type: "line",

                    data: {
                        labels:
                            c.map(
                                x =>
                                    new Date(
                                        x.t
                                    ).toLocaleTimeString(
                                        "ar-SA",
                                        {
                                            hour: "2-digit",
                                            minute: "2-digit"
                                        }
                                    )
                            ),

                        datasets: [
                            {
                                label:
                                    state.symbol,

                                data:
                                    c.map(
                                        x =>
                                            x.c
                                    ),

                                borderWidth: 2,

                                pointRadius: 0,

                                tension: 0.2
                            }
                        ]
                    },

                    options: {
                        responsive: true,

                        maintainAspectRatio:
                            false,

                        plugins: {
                            legend: {
                                display: false
                            }
                        },

                        scales: {
                            x: {
                                display: false
                            },

                            y: {
                                grid: {
                                    color:
                                        "rgba(127,127,127,.15)"
                                }
                            }
                        }
                    }
                }
            );
    }

    /* ========================= YAHOO US MARKET ========================= */

    async function loadUSMarket() {
        const box =
            $("usMarketList");

        if (!box) return;

        box.innerHTML = `
            <div class="panel">
                ⏳ جاري تحميل الأسهم الأمريكية من Yahoo Finance...
            </div>
        `;

        try {
            const d =
                await api(
                    "/api/yahoo/us/scan?interval=15m&limit=10000"
                );

            state.usResults =
                (
                    d.results ||
                    d.data ||
                    []
                ).filter(item =>
                    item.direction === "buy" ||
                    item.direction === "sell" ||
                    item.signal === "شراء" ||
                    item.signal === "شراء قوي" ||
                    item.signal === "بيع" ||
                    item.signal === "بيع قوي"
                );

            if (
                !state.usResults.length
            ) {
                box.innerHTML = `
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
            box.innerHTML = `
                <div class="panel error">
                    تعذر تحميل الأسهم الأمريكية من Yahoo Finance:
                    ${escapeHTML(
                        error.message
                    )}
                </div>
            `;
        }
    }

    function renderUSCards(
        box,
        rows
    ) {
        box.innerHTML =
            rows.map(x => {
                const ticker =
                    x.underlyingTicker ||
                    x.ticker ||
                    x.symbol ||
                    "";

                const name =
                    x.name ||
                    x.fullName ||
                    ticker;

                const signal =
                    x.signal ||
                    (
                        x.direction === "buy"
                            ? "شراء"
                            : x.direction === "sell"
                            ? "بيع"
                            : "حيادي"
                    );

                return `
                    <div class="market-card">

                        <div class="market-card-header">

                            <div>
                                <strong>
                                    ${escapeHTML(
                                        ticker
                                    )}
                                </strong>

                                <small>
                                    ${escapeHTML(
                                        name
                                    )}
                                </small>
                            </div>

                            <span class="${sigClass(
                                signal
                            )}">
                                ${escapeHTML(
                                    signal
                                )}
                            </span>

                        </div>

                        <div class="market-price">
                            ${fmt(
                                x.price
                            )}
                        </div>

                        <div class="market-change">
                            ${pct(
                                x.change
                            )}
                        </div>

                        <div class="market-levels">

                            <div>
                                دخول
                                <strong>
                                    ${fmt(
                                        x.entry ??
                                        x.price
                                    )}
                                </strong>
                            </div>

                            <div>
                                TP1
                                <strong>
                                    ${fmt(
                                        x.tp1
                                    )}
                                </strong>
                            </div>

                            <div>
                                TP2
                                <strong>
                                    ${fmt(
                                        x.tp2
                                    )}
                                </strong>
                            </div>

                            <div>
                                وقف
                                <strong>
                                    ${fmt(
                                        x.sl
                                    )}
                                </strong>
                            </div>

                        </div>

                        <div class="market-footer">

                            <span>
                                التقييم:
                                ${
                                    x.score10 ??
                                    (
                                        x.score != null
                                            ? Number(
                                                x.score
                                            ) / 10
                                            : "—"
                                    )
                                }/10
                            </span>

                            <span>
                                ${money(
                                    x.volume
                                )}
                            </span>

                        </div>

                    </div>
                `;
            })
            .join("");
    }

    /* ========================= NEWS ========================= */

    async function loadNews() {
        if (!$("newsList")) return;

        $("newsList").innerHTML = `
            <div class="panel">
                جاري تحميل الأخبار...
            </div>
        `;

        try {
            const d =
                await api(
                    "/api/news"
                );

            $("newsList").innerHTML =
                d.news?.length
                    ? d.news.map(n => `
                        <article class="news-card">

                            <div class="news-meta">
                                ${escapeHTML(
                                    n.source || ""
                                )}
                                ·
                                ${escapeHTML(
                                    n.published || ""
                                )}
                            </div>

                            <h3>
                                <a
                                    href="${escapeHTML(
                                        n.link || "#"
                                    )}"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    ${escapeHTML(
                                        n.title || ""
                                    )}
                                </a>
                            </h3>

                            <p>
                                ${escapeHTML(
                                    n.description || ""
                                )}
                            </p>

                        </article>
                    `).join("")
                    : `
                        <div class="panel">
                            لا توجد أخبار متاحة حاليًا.
                        </div>
                    `;

        } catch (e) {
            $("newsList").innerHTML = `
                <div class="panel error">
                    ${escapeHTML(
                        e.message
                    )}
                </div>
            `;
        }
    }

    if ($("newsBtn")) {
        $("newsBtn").onclick =
            loadNews;
    }

    /* ========================= SUBSCRIPTION ========================= */

    async function loadSubscription() {
        if (!$("subscriptionStatus")) {
            return;
        }

        try {
            const d =
                await api(
                    "/api/subscription/plans"
                );

            renderPlans(d);

            const s =
                await api(
                    "/api/subscription/my"
                );

            $("subscriptionStatus").innerHTML =
                s.active
                    ? `
                        <div class="subscription-active">
                            ✅ اشتراكك فعال
                            — ${escapeHTML(
                                s.plan
                            )}
                            — ينتهي
                            ${new Date(
                                s.expires
                            ).toLocaleDateString(
                                "ar-SA"
                            )}
                        </div>
                    `
                    : `
                        <div class="subscription-inactive">
                            لا يوجد اشتراك فعال حاليًا.
                        </div>
                    `;

            renderPaymentHistory(
                s.requests || []
            );
        } catch (e) {
            $("subscriptionStatus").innerHTML = `
                <div class="panel error">
                    ${escapeHTML(
                        e.message
                    )}
                </div>
            `;
        }
    }

    function renderPlans(d) {
        if ($("payAddress")) {
            $("payAddress").value =
                d.address || "";
        }

        if (!$("plans")) return;

        $("plans").innerHTML =
            Object.entries(
                d.plans || {}
            )
                .map(
                    ([k, p]) => `
                        <div
                            class="plan-card"
                            data-plan="${escapeHTML(
                                k
                            )}"
                        >
                            <strong>
                                ${escapeHTML(
                                    p.name
                                )}
                            </strong>

                            <strong>
                                ${fmt(
                                    p.amount
                                )} USDT
                            </strong>

                            <span>
                                دفع عبر TRC20
                            </span>
                        </div>
                    `
                )
                .join("");

        document
            .querySelectorAll(
                ".plan-card"
            )
            .forEach(b => {
                b.onclick = () => {
                    choosePlan(
                        b.dataset.plan,
                        d.plans[
                            b.dataset.plan
                        ]
                    );
                };
            });
    }

    function choosePlan(k, p) {
        state.plan = k;

        if ($("paymentBox")) {
            $("paymentBox").hidden =
                false;
        }

        if ($("chosenPlan")) {
            $("chosenPlan").innerHTML = `
                الباقة المختارة:
                <strong>
                    ${escapeHTML(
                        p.name
                    )}
                </strong>
                —
                <strong>
                    ${fmt(
                        p.amount
                    )} USDT
                </strong>
            `;
        }

        if ($("qrBox")) {
            $("qrBox").innerHTML = "";
        }

        if (
            window.QRCode &&
            $("qrBox") &&
            $("payAddress")
        ) {
            QRCode.toCanvas(
                $("qrBox"),
                $("payAddress").value,
                {
                    width: 190
                },
                () => {}
            );
        }

        if ($("paymentBox")) {
            $("paymentBox").scrollIntoView({
                behavior: "smooth"
            });
        }
    }

    if ($("copyAddress")) {
        $("copyAddress").onclick =
            async () => {
                try {
                    await navigator
                        .clipboard
                        .writeText(
                            $("payAddress").value
                        );

                    $("copyAddress")
                        .textContent =
                        "تم النسخ ✓";

                    setTimeout(() => {
                        $("copyAddress")
                            .textContent =
                            "نسخ";
                    }, 1500);
                } catch {}
            };
    }

    if ($("sendPayment")) {
        $("sendPayment").onclick =
            async () => {
                if (!state.plan) {
                    return;
                }

                try {
                    const d =
                        await api(
                            "/api/subscription/request",
                            {
                                method: "POST",

                                body:
                                    JSON.stringify({
                                        plan:
                                            state.plan,

                                        txid:
                                            $("txid")
                                                ?.value
                                                .trim() ||
                                            ""
                                    })
                            }
                        );

                    if ($("paymentMsg")) {
                        $("paymentMsg").innerHTML = `
                            ${escapeHTML(
                                d.message
                            )} ✅
                        `;
                    }

                    if ($("txid")) {
                        $("txid").value = "";
                    }

                    loadSubscription();
                } catch (e) {
                    if ($("paymentMsg")) {
                        $("paymentMsg").innerHTML = `
                            ${escapeHTML(
                                e.message
                            )}
                        `;
                    }
                }
            };
    }

    function renderPaymentHistory(rows) {
        if (!$("paymentHistory")) {
            return;
        }

        $("paymentHistory").innerHTML =
            rows.length
                ? `
                    <div class="payment-history">

                        <h3>
                            طلبات الدفع
                        </h3>

                        ${rows
                            .map(
                                x => `
                                    <div class="payment-row">

                                        <strong>
                                            ${escapeHTML(
                                                x.plan
                                            )}
                                        </strong>

                                        <span>
                                            ${fmt(
                                                x.amount
                                            )}
                                            USDT
                                        </span>

                                        <span>
                                            ${
                                                x.status ===
                                                "pending"
                                                    ? "قيد المراجعة"
                                                    : x.status ===
                                                      "approved"
                                                    ? "مقبول"
                                                    : "مرفوض"
                                            }
                                        </span>

                                    </div>
                                `
                            )
                            .join("")}

                    </div>
                `
                : "";
    }

    /* ========================= THEME ========================= */

    if ($("themeBtn")) {
        $("themeBtn").onclick =
            () => {
                document.body.classList.toggle(
                    "light"
                );

                localStorage.setItem(
                    "theme",
                    document.body.classList.contains(
                        "light"
                    )
                        ? "light"
                        : "dark"
                );
            };
    }

    if (
        localStorage.getItem(
            "theme"
        ) === "light"
    ) {
        document.body.classList.add(
            "light"
        );
    }

    /* ========================= BOOT ========================= */

    (async function boot() {
        try {
            await checkAuth();
        } catch {}

        if ($("systemStatus")) {
            $("systemStatus").textContent =
                "متصل";
        }

        try {
            await runScanner();
        } catch {}

        try {
            await loadAnalysis();
        } catch {}

        try {
            await loadNews();
        } catch {}

        setInterval(() => {
            runScanner();
        }, 60000);

        setInterval(() => {
            loadNews();
        }, 600000);
    })();

})();

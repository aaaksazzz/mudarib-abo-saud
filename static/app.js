const $ = id => document.getElementById(id);

const state = {
    user: null,
    admin: false,
    interval: '15m',
    symbol: 'BTCUSDT',
    results: [],
    signals: new Set(),
    sort: 'change',
    dir: -1,
    busy: false,
    chart: null,
    recent: JSON.parse(localStorage.getItem('mudarib_recent') || '[]'),
    plan: null
};

const signalRank = {
    'شراء قوي': 5,
    'شراء': 4,
    'حيادي': 3,
    'بيع': 2,
    'بيع قوي': 1
};

/* ============================================================
   API
============================================================ */

const api = async (url, opt = {}) => {
    const r = await fetch(url, {
        ...opt,
        headers: {
            'Content-Type': 'application/json',
            ...(opt.headers || {})
        }
    });

    let d = {};

    try {
        d = await r.json();
    } catch (_) {}

    if (!r.ok || d.ok === false) {
        throw new Error(d.message || `HTTP ${r.status}`);
    }

    return d;
};

/* ============================================================
   HELPERS
============================================================ */

function fmt(v) {
    if (v == null || Number.isNaN(Number(v))) return '—';

    v = Number(v);

    if (v === 0) return '0';

    if (Math.abs(v) >= 1000) {
        return v.toLocaleString('en-US', {
            maximumFractionDigits: 2
        });
    }

    if (Math.abs(v) >= 1) {
        return v.toLocaleString('en-US', {
            maximumFractionDigits: 4
        });
    }

    return v.toLocaleString('en-US', {
        maximumFractionDigits: 8
    });
}

function pct(v) {
    v = Number(v || 0);
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function money(v) {
    v = Number(v || 0);

    if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;

    return fmt(v);
}

function sigClass(s) {
    if (s === 'شراء قوي' || s === 'شراء') return 'buy';
    if (s === 'بيع قوي' || s === 'بيع') return 'sell';
    return 'neutral';
}

/* ============================================================
   MENU / SECTIONS
============================================================ */

function closeMenu() {
    document.body.classList.remove('menu-open');
}

function showSection(id) {
    document.querySelectorAll('.section').forEach(x => {
        x.classList.toggle('active', x.id === id);
    });

    document.querySelectorAll('.nav-item').forEach(x => {
        x.classList.toggle('active', x.dataset.section === id);
    });

    const names = {
        dashboard: 'الرئيسية',
        scanner: 'ماسح الفرص',
        recent: 'الصفقات الحديثة',
        news: 'الأخبار',
        subscription: 'الاشتراك'
    };

    if ($('pageTitle')) {
        $('pageTitle').textContent = names[id] || 'الرئيسية';
    }

    closeMenu();

    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

document.querySelectorAll('.nav-item').forEach(b => {
    b.addEventListener('click', e => {
        e.preventDefault();

        const section = b.dataset.section;

        /*
         * إذا حاول الزائر فتح الاشتراك بدون تسجيل
         * نفتح تسجيل الدخول بدل إظهار صفحة فارغة.
         */
        if (section === 'subscription' && !state.user) {
            openAuth('login');
            return;
        }

        showSection(section);
    });
});

if ($('menuBtn')) {
    $('menuBtn').onclick = e => {
        e.stopPropagation();
        document.body.classList.toggle('menu-open');
    };
}

document.addEventListener('click', e => {
    if (!document.body.classList.contains('menu-open')) return;

    const sidebar = $('sidebar');
    const menu = $('menuBtn');

    if (
        sidebar &&
        !sidebar.contains(e.target) &&
        menu &&
        !menu.contains(e.target)
    ) {
        closeMenu();
    }
});

window.addEventListener('resize', () => {
    if (window.innerWidth > 1000) {
        closeMenu();
    }
});

/* ============================================================
   AUTH MODAL
============================================================ */

function clearAuthMessage() {
    if ($('authMsg')) {
        $('authMsg').innerHTML = '';
    }
}

function setAuthMode(mode) {
    const loginMode = mode === 'login';

    if ($('loginForm')) {
        $('loginForm').hidden = !loginMode;
    }

    if ($('registerForm')) {
        $('registerForm').hidden = loginMode;
    }

    if ($('loginTab')) {
        $('loginTab').classList.toggle('active', loginMode);
    }

    if ($('registerTab')) {
        $('registerTab').classList.toggle('active', !loginMode);
    }

    clearAuthMessage();
}

function openAuth(mode = 'login') {
    if (!$('authModal')) return;

    setAuthMode(mode);

    $('authModal').classList.add('show');

    /*
     * تركيز المؤشر مباشرة في أول خانة
     */
    setTimeout(() => {
        if (mode === 'login' && $('loginEmail')) {
            $('loginEmail').focus();
        }

        if (mode === 'register' && $('regName')) {
            $('regName').focus();
        }
    }, 100);
}

function closeAuth() {
    if ($('authModal')) {
        $('authModal').classList.remove('show');
    }

    clearAuthMessage();

    /*
     * تنظيف كلمات المرور
     */
    if ($('loginPassword')) {
        $('loginPassword').value = '';
    }

    if ($('regPassword')) {
        $('regPassword').value = '';
    }
}

if ($('loginBtn')) {
    $('loginBtn').onclick = e => {
        e.preventDefault();
        openAuth('login');
    };
}

if ($('registerBtn')) {
    $('registerBtn').onclick = e => {
        e.preventDefault();
        openAuth('register');
    };
}

if ($('loginTab')) {
    $('loginTab').onclick = e => {
        e.preventDefault();
        setAuthMode('login');
    };
}

if ($('registerTab')) {
    $('registerTab').onclick = e => {
        e.preventDefault();
        setAuthMode('register');
    };
}

/*
 * زر الإغلاق
 */
document.querySelectorAll('[data-close]').forEach(b => {
    b.addEventListener('click', e => {
        e.preventDefault();

        const target = b.dataset.close;

        if (target === 'authModal') {
            closeAuth();
        } else {
            const el = $(target);

            if (el) {
                el.classList.remove('show');
            }
        }
    });
});

/*
 * الضغط على خلفية النافذة يغلقها
 * لكن الضغط داخل الصندوق لا يغلقها.
 */
if ($('authModal')) {
    $('authModal').addEventListener('click', e => {
        if (e.target === $('authModal')) {
            closeAuth();
        }
    });
}

/* ============================================================
   AUTH STATE
============================================================ */

async function checkAuth() {
    /*
     * المستخدم
     */
    try {
        const d = await api('/api/auth/me');

        state.user = d.user || null;
    } catch (_) {
        /*
         * 401 للزائر طبيعي جدًا
         */
        state.user = null;
    }

    updateAuth();

    /*
     * الإدارة
     */
    try {
        const a = await api('/api/admin/me');

        state.admin = !!a.admin;

        if ($('adminLink')) {
            $('adminLink').hidden = !state.admin;
        }
    } catch (_) {
        state.admin = false;

        if ($('adminLink')) {
            $('adminLink').hidden = true;
        }
    }
}

function updateAuth() {
    const logged = !!state.user;

    if ($('userBadge')) {
        $('userBadge').textContent =
            logged ? (state.user.name || state.user.email) : 'زائر';
    }

    if ($('loginBtn')) {
        $('loginBtn').hidden = logged;
    }

    if ($('registerBtn')) {
        $('registerBtn').hidden = logged;
    }

    if ($('logoutBtn')) {
        $('logoutBtn').hidden = !logged;
    }

    if ($('subscriptionNav')) {
        $('subscriptionNav').hidden = !logged;
    }

    if ($('subscription')) {
        $('subscription').hidden = !logged;
    }

    if (logged) {
        loadSubscription();
    }
}

/* ============================================================
   LOGOUT
============================================================ */

if ($('logoutBtn')) {
    $('logoutBtn').onclick = async () => {
        try {
            await api('/api/auth/logout', {
                method: 'POST'
            });
        } catch (_) {}

        state.user = null;
        state.plan = null;

        updateAuth();
        showSection('dashboard');
    };
}

/* ============================================================
   LOGIN
============================================================ */

if ($('loginForm')) {
    $('loginForm').addEventListener('submit', async e => {
        e.preventDefault();
        e.stopPropagation();

        clearAuthMessage();

        const email = $('loginEmail')?.value.trim() || '';
        const password = $('loginPassword')?.value || '';

        if (!email || !password) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    '<span class="error">اكتب البريد وكلمة المرور.</span>';
            }

            return;
        }

        const button = $('loginForm').querySelector('button[type="submit"]');

        if (button) {
            button.disabled = true;
            button.dataset.oldText = button.textContent;
            button.textContent = 'جاري الدخول...';
        }

        try {
            const d = await api('/api/auth/login', {
                method: 'POST',
                body: JSON.stringify({
                    email,
                    password
                })
            });

            state.user = d.user || null;

            updateAuth();

            closeAuth();

            showSection('dashboard');

            /*
             * تحديث البيانات بعد الدخول
             */
            loadAnalysis();

        } catch (err) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    `<span class="error">${escapeHtml(err.message)}</span>`;
            }
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent =
                    button.dataset.oldText || 'دخول';
            }
        }
    });
}

/* ============================================================
   REGISTER
============================================================ */

if ($('registerForm')) {
    $('registerForm').addEventListener('submit', async e => {
        e.preventDefault();
        e.stopPropagation();

        clearAuthMessage();

        const name = $('regName')?.value.trim() || '';
        const email = $('regEmail')?.value.trim() || '';
        const password = $('regPassword')?.value || '';

        if (!name || !email || !password) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    '<span class="error">عبّ جميع البيانات المطلوبة.</span>';
            }

            return;
        }

        if (name.length < 2) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    '<span class="error">الاسم لازم يكون حرفين أو أكثر.</span>';
            }

            return;
        }

        if (!email.includes('@')) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    '<span class="error">اكتب بريد إلكتروني صحيح.</span>';
            }

            return;
        }

        if (password.length < 6) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    '<span class="error">كلمة المرور لازم تكون 6 أحرف على الأقل.</span>';
            }

            return;
        }

        const button = $('registerForm').querySelector('button[type="submit"]');

        if (button) {
            button.disabled = true;
            button.dataset.oldText = button.textContent;
            button.textContent = 'جاري إنشاء الحساب...';
        }

        try {
            const d = await api('/api/auth/register', {
                method: 'POST',
                body: JSON.stringify({
                    name,
                    email,
                    password
                })
            });

            state.user = d.user || null;

            updateAuth();

            closeAuth();

            showSection('dashboard');

            loadAnalysis();

        } catch (err) {
            if ($('authMsg')) {
                $('authMsg').innerHTML =
                    `<span class="error">${escapeHtml(err.message)}</span>`;
            }
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent =
                    button.dataset.oldText || 'إنشاء الحساب';
            }
        }
    });
}

/* ============================================================
   SAFE HTML
============================================================ */

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/* ============================================================
   DASHBOARD INTERVALS
============================================================ */

document.querySelectorAll('#dashIntervals button').forEach(b => {
    b.onclick = () => {
        document
            .querySelectorAll('#dashIntervals button')
            .forEach(x => x.classList.remove('active'));

        b.classList.add('active');

        state.interval = b.dataset.interval;

        loadAnalysis();
    };
});

/* ============================================================
   SCANNER INTERVALS
============================================================ */

document.querySelectorAll('#intervalChips button').forEach(b => {
    b.onclick = () => {
        document
            .querySelectorAll('#intervalChips button')
            .forEach(x => x.classList.remove('active'));

        b.classList.add('active');

        state.interval = b.dataset.interval;

        runScanner();
    };
});

/* ============================================================
   SIGNAL FILTERS
============================================================ */

document.querySelectorAll('.signal-chips button').forEach(b => {
    b.onclick = () => {
        b.classList.toggle('active');

        const s = b.dataset.signal;

        if (state.signals.has(s)) {
            state.signals.delete(s);
        } else {
            state.signals.add(s);
        }

        renderScanner();
    };
});

/* ============================================================
   SCANNER SORT
============================================================ */

if ($('sortField')) {
    $('sortField').onchange = e => {
        state.sort = e.target.value;
        renderScanner();
    };
}

if ($('sortDir')) {
    $('sortDir').onclick = () => {
        state.dir *= -1;

        $('sortDir').textContent =
            state.dir === -1 ? '↓ تنازلي' : '↑ تصاعدي';

        renderScanner();
    };
}

if ($('scannerSearch')) {
    $('scannerSearch').oninput = renderScanner;
}

if ($('scanBtn')) {
    $('scanBtn').onclick = runScanner;
}

/* ============================================================
   FILTERED SCANNER
============================================================ */

function filtered() {
    let a = [...state.results];

    const q = $('scannerSearch')
        ? $('scannerSearch').value.trim().toUpperCase()
        : '';

    if (q) {
        a = a.filter(x =>
            String(x.symbol || '').includes(q)
        );
    }

    if (state.signals.size) {
        a = a.filter(x =>
            state.signals.has(x.signal)
        );
    }

    const f = state.sort;

    a.sort((x, y) => {
        let av =
            f === 'signal'
                ? signalRank[x.signal]
                : f === 'symbol'
                    ? x.symbol
                    : x[f] ?? 0;

        let bv =
            f === 'signal'
                ? signalRank[y.signal]
                : f === 'symbol'
                    ? y.symbol
                    : y[f] ?? 0;

        if (typeof av === 'string') {
            return av.localeCompare(bv) * state.dir;
        }

        return (
            (Number(av) - Number(bv)) *
            state.dir
        );
    });

    return a;
}

/* ============================================================
   RENDER SCANNER
============================================================ */

function renderScanner() {
    if (!$('scannerBody')) return;

    const rows = filtered();

    $('scannerBody').innerHTML = rows.length
        ? rows.map(x => `
            <tr onclick="selectSymbol('${escapeHtml(x.symbol)}')">
                <td>
                    <b>${escapeHtml(String(x.symbol || '').replace('USDT', ''))}</b>
                    <small>USDT</small>
                </td>

                <td>${fmt(x.price)}</td>

                <td class="${Number(x.change) >= 0 ? 'up' : 'down'}">
                    ${pct(x.change)}
                </td>

                <td>
                    <span class="signal ${sigClass(x.signal)}">
                        ${escapeHtml(x.signal)}
                    </span>
                </td>

                <td>${x.score10 ?? '—'}/10</td>

                <td>${money(x.volume)}</td>

                <td>${escapeHtml(x.interval || '')}</td>
            </tr>
        `).join('')
        : `
            <tr>
                <td colspan="7" class="empty">
                    لا توجد نتائج مطابقة
                </td>
            </tr>
        `;
}

/* ============================================================
   RUN SCANNER
============================================================ */

async function runScanner() {
    if (state.busy) return;

    state.busy = true;

    if ($('scannerStatus')) {
        $('scannerStatus').textContent =
            'جاري فحص أعلى العملات سيولة...';
    }

    try {
        const d = await api(
            `/api/binance/scan?interval=${encodeURIComponent(state.interval)}&limit=40`
        );

        state.results = d.results || [];

        if ($('scannerStatus')) {
            $('scannerStatus').textContent =
                `تم العثور على ${state.results.length} فرصة` +
                (d.cached ? ' — نتيجة محفوظة مؤقتًا' : '');
        }

        renderScanner();
        captureRecent();

    } catch (e) {
        if ($('scannerStatus')) {
            $('scannerStatus').textContent =
                `تعذر الفحص: ${e.message}`;
        }
    } finally {
        state.busy = false;
    }
}

/* ============================================================
   RECENT
============================================================ */

function captureRecent() {
    const now = Date.now();
    const bucket = Math.floor(now / 300000);

    const old = new Set(
        state.recent.map(x => x.key)
    );

    state.results
        .filter(x => x.signal !== 'حيادي')
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

    state.recent = state.recent.slice(0, 60);

    localStorage.setItem(
        'mudarib_recent',
        JSON.stringify(state.recent)
    );

    renderRecent();
}

function renderRecent() {
    if (!$('recentList')) return;

    const a = state.recent;

    if (!a.length) {
        $('recentList').innerHTML =
            '<div class="empty-card">ما فيه فرص حديثة حتى الآن. شغّل الماسح.</div>';

        return;
    }

    $('recentList').innerHTML = a
        .slice(0, 30)
        .map(x => `
            <div class="recent-card"
                 onclick="selectSymbol('${escapeHtml(x.symbol)}')">

                <div>
                    <b>${escapeHtml(x.symbol)}</b>
                    <small>
                        ${new Date(x.time).toLocaleString('ar-SA')}
                    </small>
                </div>

                <span class="signal ${sigClass(x.signal)}">
                    ${escapeHtml(x.signal)}
                </span>

                <div>
                    <small>السعر</small>
                    <b>${fmt(x.price)}</b>
                </div>

                <div class="${Number(x.change) >= 0 ? 'up' : 'down'}">
                    ${pct(x.change)}
                </div>

                <div>
                    <small>TP1 / وقف</small>
                    <b>${fmt(x.tp1)} / ${fmt(x.sl)}</b>
                </div>
            </div>
        `)
        .join('');
}

if ($('clearRecent')) {
    $('clearRecent').onclick = () => {
        state.recent = [];

        localStorage.removeItem(
            'mudarib_recent'
        );

        renderRecent();
    };
}

/* ============================================================
   ANALYSIS
============================================================ */

async function loadAnalysis() {
    const sym = state.symbol;

    try {
        const d = await api(
            `/api/binance/analysis?symbol=${encodeURIComponent(sym)}&interval=${encodeURIComponent(state.interval)}`
        );

        const a = d.analysis;

        if ($('dashSymbol')) $('dashSymbol').textContent = sym;
        if ($('dashPrice')) $('dashPrice').textContent = fmt(a.price);
        if ($('dashChange')) $('dashChange').textContent = '—';

        if ($('dashSignal')) {
            $('dashSignal').textContent = a.signal;
            $('dashSignal').className =
                `signal-text ${sigClass(a.signal)}`;
        }

        if ($('bigSignal')) {
            $('bigSignal').textContent = a.signal;
            $('bigSignal').className =
                `signal-big ${sigClass(a.signal)}`;
        }

        if ($('scoreText')) {
            $('scoreText').textContent =
                `${a.score}/100`;
        }

        if ($('scoreBar')) {
            $('scoreBar').style.width =
                `${Math.max(0, Math.min(100, Number(a.score || 0)))}%`;
        }

        if ($('entry')) $('entry').textContent = fmt(a.entry);
        if ($('tp1')) $('tp1').textContent = fmt(a.tp1);
        if ($('tp2')) $('tp2').textContent = fmt(a.tp2);
        if ($('tp3')) $('tp3').textContent = fmt(a.tp3);
        if ($('sl')) $('sl').textContent = fmt(a.sl);

        if ($('rsi')) {
            $('rsi').textContent =
                Number(a.rsi || 0).toFixed(1);
        }

        if ($('ema20')) $('ema20').textContent = fmt(a.ema20);
        if ($('ema50')) $('ema50').textContent = fmt(a.ema50);
        if ($('ema200')) $('ema200').textContent = fmt(a.ema200);

        if ($('analysisMeta')) {
            $('analysisMeta').textContent =
                `${sym} · ${state.interval}`;
        }

        if ($('reasons')) {
            $('reasons').innerHTML =
                (a.reasons || [])
                    .map(x => `<li>${escapeHtml(x)}</li>`)
                    .join('');
        }

        drawChart(a.candles || []);

    } catch (e) {
        if ($('bigSignal')) {
            $('bigSignal').textContent =
                e.message;
        }
    }
}

window.selectSymbol = s => {
    state.symbol = s;

    showSection('dashboard');

    loadAnalysis();
};

/* ============================================================
   CHART
============================================================ */

function drawChart(c) {
    if (!$('priceChart') || typeof Chart === 'undefined') {
        return;
    }

    const ctx = $('priceChart');

    if (state.chart) {
        state.chart.destroy();
    }

    state.chart = new Chart(ctx, {
        type: 'line',

        data: {
            labels: c.map(x =>
                new Date(x.t).toLocaleTimeString(
                    'ar-SA',
                    {
                        hour: '2-digit',
                        minute: '2-digit'
                    }
                )
            ),

            datasets: [
                {
                    label: state.symbol,
                    data: c.map(x => x.c),
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: .2
                }
            ]
        },

        options: {
            responsive: true,
            maintainAspectRatio: false,

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
                        color: 'rgba(127,127,127,.15)'
                    }
                }
            }
        }
    });
}

/* ============================================================
   NEWS
============================================================ */

async function loadNews() {
    if (!$('newsList')) return;

    const box = $('newsList');

    box.innerHTML =
        '<div class="empty-card">جاري تحميل الأخبار...</div>';

    try {
        const d = await api('/api/news');

        box.innerHTML =
            d.news?.length
                ? d.news.map(n => `
                    <a class="news-card"
                       href="${escapeHtml(n.link || '#')}"
                       target="_blank"
                       rel="noopener">

                        <small>
                            ${escapeHtml(n.source || '')}
                            ·
                            ${escapeHtml(n.published || '')}
                        </small>

                        <h3>
                            ${escapeHtml(n.title || '')}
                        </h3>

                        <p>
                            ${escapeHtml(n.description || '')}
                        </p>
                    </a>
                `).join('')
                : '<div class="empty-card">لا توجد أخبار متاحة حاليًا.</div>';

    } catch (e) {
        box.innerHTML =
            `<div class="empty-card">${escapeHtml(e.message)}</div>`;
    }
}

if ($('newsBtn')) {
    $('newsBtn').onclick = loadNews;
}

/* ============================================================
   SUBSCRIPTION
============================================================ */

async function loadSubscription() {
    if (!state.user) return;

    try {
        const d = await api(
            '/api/subscription/plans'
        );

        renderPlans(d);

        const s = await api(
            '/api/subscription/my'
        );

        if ($('subscriptionStatus')) {
            $('subscriptionStatus').innerHTML =
                s.active
                    ? `
                        <div class="active-plan">
                            ✅ اشتراكك فعال —
                            ${escapeHtml(s.plan || '')}
                            —
                            ينتهي
                            ${s.expires
                                ? new Date(s.expires)
                                    .toLocaleDateString('ar-SA')
                                : '—'}
                        </div>
                    `
                    : `
                        <div class="inactive-plan">
                            لا يوجد اشتراك فعال حاليًا.
                        </div>
                    `;
        }

        renderPaymentHistory(
            s.requests || []
        );

    } catch (e) {
        if ($('subscriptionStatus')) {
            $('subscriptionStatus').innerHTML =
                `<div class="error">${escapeHtml(e.message)}</div>`;
        }
    }
}

function renderPlans(d) {
    if (!$('plans')) return;

    if ($('payAddress')) {
        $('payAddress').value =
            d.address || '';
    }

    $('plans').innerHTML =
        Object.entries(d.plans || {})
            .map(([k, p]) => `
                <button
                    type="button"
                    class="plan-card"
                    data-plan="${escapeHtml(k)}">

                    <b>${escapeHtml(p.name)}</b>

                    <strong>
                        ${fmt(p.amount)} USDT
                    </strong>

                    <small>
                        دفع عبر TRC20
                    </small>
                </button>
            `)
            .join('');

    document
        .querySelectorAll('.plan-card')
        .forEach(b => {
            b.onclick = () => {
                const key = b.dataset.plan;
                choosePlan(
                    key,
                    d.plans[key]
                );
            };
        });
}

function choosePlan(k, p) {
    state.plan = k;

    if ($('paymentBox')) {
        $('paymentBox').hidden = false;
    }

    if ($('chosenPlan')) {
        $('chosenPlan').innerHTML =
            `الباقة المختارة: <b>${escapeHtml(p.name)}</b> — <b>${fmt(p.amount)} USDT</b>`;
    }

    if ($('qrBox')) {
        $('qrBox').innerHTML = '';

        if (
            window.QRCode &&
            $('payAddress')
        ) {
            QRCode.toCanvas(
                $('qrBox'),
                $('payAddress').value,
                {
                    width: 190
                },
                () => {}
            );
        }
    }

    if ($('paymentBox')) {
        $('paymentBox').scrollIntoView({
            behavior: 'smooth'
        });
    }
}

if ($('copyAddress')) {
    $('copyAddress').onclick = async () => {
        try {
            await navigator.clipboard.writeText(
                $('payAddress').value
            );

            $('copyAddress').textContent =
                'تم النسخ ✓';

            setTimeout(() => {
                $('copyAddress').textContent =
                    'نسخ';
            }, 1500);

        } catch (_) {
            if ($('paymentMsg')) {
                $('paymentMsg').innerHTML =
                    '<span class="error">تعذر النسخ تلقائيًا.</span>';
            }
        }
    };
}

if ($('sendPayment')) {
    $('sendPayment').onclick = async () => {
        if (!state.plan) {
            if ($('paymentMsg')) {
                $('paymentMsg').innerHTML =
                    '<span class="error">اختر الباقة أولًا.</span>';
            }

            return;
        }

        try {
            const d = await api(
                '/api/subscription/request',
                {
                    method: 'POST',

                    body: JSON.stringify({
                        plan: state.plan,
                        txid: $('txid')
                            ? $('txid').value.trim()
                            : ''
                    })
                }
            );

            if ($('paymentMsg')) {
                $('paymentMsg').innerHTML =
                    `<span class="ok">${escapeHtml(d.message)} ✅</span>`;
            }

            if ($('txid')) {
                $('txid').value = '';
            }

            loadSubscription();

        } catch (e) {
            if ($('paymentMsg')) {
                $('paymentMsg').innerHTML =
                    `<span class="error">${escapeHtml(e.message)}</span>`;
            }
        }
    };
}

function renderPaymentHistory(rows) {
    if (!$('paymentHistory')) return;

    $('paymentHistory').innerHTML =
        rows.length
            ? `
                <h3>طلبات الدفع</h3>

                <div class="payment-history">
                    ${rows.map(x => `
                        <div>
                            <b>${escapeHtml(x.plan || '')}</b>

                            <span>
                                ${fmt(x.amount)} USDT
                            </span>

                            <span class="status-${escapeHtml(x.status || '')}">
                                ${
                                    x.status === 'pending'
                                        ? 'قيد المراجعة'
                                        : x.status === 'approved'
                                            ? 'مقبول'
                                            : 'مرفوض'
                                }
                            </span>
                        </div>
                    `).join('')}
                </div>
            `
            : '';
}

/* ============================================================
   THEME
============================================================ */

if ($('themeBtn')) {
    $('themeBtn').onclick = () => {
        document.body.classList.toggle('light');

        localStorage.setItem(
            'theme',
            document.body.classList.contains('light')
                ? 'light'
                : 'dark'
        );
    };
}

if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light');
}

/* ============================================================
   BOOT
============================================================ */

(async function boot() {

    await checkAuth();

    if ($('systemStatus')) {
        $('systemStatus').textContent = 'متصل';
    }

    /*
     * لا نشغل الطلبات إلا بعد معرفة حالة المستخدم.
     */
    await runScanner();

    await loadAnalysis();

    await loadNews();

    /*
     * تحديث الماسح كل دقيقة
     */
    setInterval(() => {
        runScanner();
    }, 60000);

    /*
     * تحديث الأخبار كل 10 دقائق
     */
    setInterval(() => {
        loadNews();
    }, 600000);

})();

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
  futures: [],
  usMarket: [],
  plan: null,
  homeMarket: 'crypto',
  homeResults: [],
  homeAnalysis: {}
};

const signalRank = {
  'شراء قوي': 5,
  'شراء': 4,
  'حيادي': 3,
  'بيع': 2,
  'بيع قوي': 1
};

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
  } catch {}

  if (!r.ok || d.ok === false) {
    throw new Error(d.message || `HTTP ${r.status}`);
  }

  return d;
};


/* =========================
   أدوات عامة
========================= */

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
  return s === 'شراء قوي' || s === 'شراء'
    ? 'buy'
    : s === 'بيع قوي' || s === 'بيع'
    ? 'sell'
    : 'neutral';
}

function signalTextClass(s) {
  return s === 'شراء قوي' || s === 'شراء'
    ? 'state-buy'
    : s === 'بيع قوي' || s === 'بيع'
    ? 'state-sell'
    : 'state-neutral';
}

function signalEmoji(s) {
  if (s === 'شراء قوي') return '🟢🟢';
  if (s === 'شراء') return '🟢';
  if (s === 'بيع قوي') return '🔴🔴';
  if (s === 'بيع') return '🔴';
  return '🟡';
}

function closeMenu() {
  document.body.classList.remove('menu-open');
}


/* =========================
   التنقل
========================= */

function showSection(id) {
  document.querySelectorAll('.section').forEach(section => {
    section.classList.toggle(
      'active',
      section.id === id
    );
  });

  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.toggle(
      'active',
      item.dataset.section === id
    );
  });

  const names = {
    dashboard: 'الرئيسية',
    scanner: 'ماسح الفرص',
    recent: 'صفقات السبوت',
    futures: 'صفقات الفيوتشر',
    usmarket: 'السوق الأمريكي',
    news: 'الأخبار',
    subscription: 'الاشتراك'
  };

  if ($('pageTitle')) {
    $('pageTitle').textContent =
      names[id] || 'الرئيسية';
  }

  closeMenu();

  window.scrollTo({
    top: 0,
    behavior: 'smooth'
  });

  if (id === 'futures') {
    loadFutures();
  }

  if (id === 'usmarket') {
    loadUSMarket();
  }

  if (id === 'news') {
    loadNews();
  }

  if (id === 'subscription' && state.user) {
    loadSubscription();
  }
}

window.showSection = showSection;


document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();

    const section = item.dataset.section;

    if (section) {
      showSection(section);
    }
  });
});


if ($('menuBtn')) {
  $('menuBtn').onclick = e => {
    e.stopPropagation();

    document.body.classList.toggle(
      'menu-open'
    );
  };
}


document.addEventListener('click', e => {
  if (!document.body.classList.contains('menu-open')) {
    return;
  }

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


/* =========================
   تسجيل الدخول والحساب
========================= */

function showLoginBox() {
  const loginForm = $('loginForm');
  const registerForm = $('registerForm');

  if (loginForm) {
    loginForm.hidden = false;
  }

  if (registerForm) {
    registerForm.hidden = true;
  }

  if ($('loginTab')) {
    $('loginTab').classList.add('active');
  }

  if ($('registerTab')) {
    $('registerTab').classList.remove('active');
  }

  clearAuthMessage();
}


function showRegisterBox() {
  const loginForm = $('loginForm');
  const registerForm = $('registerForm');

  if (loginForm) {
    loginForm.hidden = true;
  }

  if (registerForm) {
    registerForm.hidden = false;
  }

  if ($('loginTab')) {
    $('loginTab').classList.remove('active');
  }

  if ($('registerTab')) {
    $('registerTab').classList.add('active');
  }

  clearAuthMessage();
}


function clearAuthMessage() {
  const msg = $('authMsg');

  if (!msg) return;

  msg.textContent = '';
  msg.style.display = 'none';
  msg.className = 'auth-msg';
}


function showAuthMessage(message, type = 'error') {
  const msg = $('authMsg');

  if (!msg) return;

  msg.textContent = message;
  msg.style.display = 'block';

  msg.className =
    type === 'ok'
      ? 'auth-msg ok'
      : 'auth-msg error';
}


function openAuth(tab = 'login') {
  const modal = $('authModal');

  if (!modal) return;

  modal.hidden = false;
  modal.classList.add('show');

  if (tab === 'register') {
    showRegisterBox();
  } else {
    showLoginBox();
  }
}


function closeAuth() {
  const modal = $('authModal');

  if (!modal) return;

  modal.classList.remove('show');
  modal.hidden = true;
}


if ($('loginBtn')) {
  $('loginBtn').onclick = () => {
    openAuth('login');
  };
}


if ($('registerBtn')) {
  $('registerBtn').onclick = () => {
    openAuth('register');
  };
}


if ($('loginTab')) {
  $('loginTab').onclick = () => {
    showLoginBox();
  };
}


if ($('registerTab')) {
  $('registerTab').onclick = () => {
    showRegisterBox();
  };
}


/* إغلاق النافذة من زر X */

if ($('authModal')) {
  const closeButton =
    $('authModal').querySelector(
      '[data-close="authModal"]'
    );

  if (closeButton) {
    closeButton.onclick = closeAuth;
  }
}


/* إغلاق عند الضغط خارج البطاقة */

if ($('authModal')) {
  $('authModal').addEventListener('click', e => {
    if (e.target === $('authModal')) {
      closeAuth();
    }
  });
}


document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeAuth();
  }
});


/* =========================
   فحص تسجيل الدخول
========================= */

async function checkAuth() {
  try {
    const d =
      await api('/api/auth/me');

    state.user =
      d.user || null;

  } catch {
    state.user = null;
  }

  updateAuth();


  try {
    const d =
      await api('/api/admin/me');

    state.admin =
      !!d.admin;

    if ($('adminLink')) {
      $('adminLink').hidden =
        !state.admin;
    }

  } catch {
    state.admin = false;

    if ($('adminLink')) {
      $('adminLink').hidden = true;
    }
  }
}


/* =========================
   تحديث الحساب
========================= */

function updateAuth() {
  const logged =
    !!state.user;

  if ($('userBadge')) {
    $('userBadge').textContent =
      logged
        ? (
            state.user.name ||
            state.user.email ||
            'مستخدم'
          )
        : '👤 زائر';
  }

  if ($('loginBtn')) {
    $('loginBtn').hidden =
      logged;
  }

  if ($('registerBtn')) {
    $('registerBtn').hidden =
      logged;
  }

  if ($('logoutBtn')) {
    $('logoutBtn').hidden =
      !logged;
  }

  if ($('subscriptionNav')) {
    $('subscriptionNav').hidden =
      !logged;
  }

  if ($('subscription')) {
    $('subscription').hidden =
      !logged;
  }

  if (!logged) {
    closeMenu();
  }
}


/* =========================
   تسجيل الدخول
========================= */

if ($('loginForm')) {
  $('loginForm').onsubmit =
    async e => {
      e.preventDefault();

      const submit =
        $('loginForm').querySelector(
          'button[type="submit"]'
        );

      if (submit) {
        submit.disabled = true;
        submit.textContent =
          'جاري تسجيل الدخول...';
      }

      clearAuthMessage();

      try {
        const d =
          await api(
            '/api/auth/login',
            {
              method: 'POST',

              body:
                JSON.stringify({
                  email:
                    $('loginEmail')
                      ? $('loginEmail')
                          .value
                          .trim()
                      : '',

                  password:
                    $('loginPassword')
                      ? $('loginPassword')
                          .value
                      : ''
                })
            }
          );

        state.user =
          d.user || null;

        updateAuth();

        showAuthMessage(
          'تم تسجيل الدخول بنجاح ✅',
          'ok'
        );

        setTimeout(() => {
          closeAuth();
          showSection('dashboard');
        }, 300);

      } catch (err) {
        showAuthMessage(
          err.message ||
          'تعذر تسجيل الدخول',
          'error'
        );

      } finally {
        if (submit) {
          submit.disabled = false;
          submit.textContent =
            '🔐 تسجيل الدخول';
        }
      }
    };
}


/* =========================
   إنشاء الحساب
========================= */

if ($('registerForm')) {
  $('registerForm').onsubmit =
    async e => {
      e.preventDefault();

      const submit =
        $('registerForm').querySelector(
          'button[type="submit"]'
        );

      if (submit) {
        submit.disabled = true;
        submit.textContent =
          'جاري إنشاء الحساب...';
      }

      clearAuthMessage();

      try {
        const d =
          await api(
            '/api/auth/register',
            {
              method: 'POST',

              body:
                JSON.stringify({
                  name:
                    $('regName')
                      ? $('regName')
                          .value
                          .trim()
                      : '',

                  email:
                    $('regEmail')
                      ? $('regEmail')
                          .value
                          .trim()
                      : '',

                  password:
                    $('regPassword')
                      ? $('regPassword')
                          .value
                      : ''
                })
            }
          );

        state.user =
          d.user || null;

        updateAuth();

        showAuthMessage(
          'تم إنشاء الحساب بنجاح ✅',
          'ok'
        );

        setTimeout(() => {
          closeAuth();
          showSection('dashboard');
        }, 300);

      } catch (err) {
        showAuthMessage(
          err.message ||
          'تعذر إنشاء الحساب',
          'error'
        );

      } finally {
        if (submit) {
          submit.disabled = false;
          submit.textContent =
            '📝 إنشاء حساب';
        }
      }
    };
}


/* =========================
   تسجيل الخروج
========================= */

if ($('logoutBtn')) {
  $('logoutBtn').onclick =
    async () => {

      try {
        await api(
          '/api/auth/logout',
          {
            method: 'POST'
          }
        );
      } catch {}

      state.user = null;
      state.admin = false;

      if ($('adminLink')) {
        $('adminLink').hidden = true;
      }

      updateAuth();

      showSection('dashboard');
    };
}


/* =========================
   فريمات الرئيسية
========================= */

document
  .querySelectorAll(
    '#dashIntervals button'
  )
  .forEach(button => {

    button.onclick = () => {

      document
        .querySelectorAll(
          '#dashIntervals button'
        )
        .forEach(x =>
          x.classList.remove('active')
        );

      button.classList.add('active');

      state.interval =
        button.dataset.interval;

      loadAnalysis();
    };
  });


/* =========================
   ماسح الفرص
========================= */

document
  .querySelectorAll(
    '#intervalChips button'
  )
  .forEach(button => {

    button.onclick = () => {

      document
        .querySelectorAll(
          '#intervalChips button'
        )
        .forEach(x =>
          x.classList.remove('active')
        );

      button.classList.add('active');

      state.interval =
        button.dataset.interval;

      runScanner();
    };
  });


document
  .querySelectorAll(
    '.signal-chips button'
  )
  .forEach(button => {

    button.onclick = () => {

      button.classList.toggle('active');

      const signal =
        button.dataset.signal;

      if (state.signals.has(signal)) {
        state.signals.delete(signal);
      } else {
        state.signals.add(signal);
      }

      renderScanner();
    };
  });


if ($('sortField')) {
  $('sortField').onchange =
    e => {
      state.sort =
        e.target.value;

      renderScanner();
    };
}


if ($('sortDir')) {
  $('sortDir').onclick =
    () => {

      state.dir *= -1;

      $('sortDir').textContent =
        state.dir === -1
          ? '↓ تنازلي'
          : '↑ تصاعدي';

      renderScanner();
    };
}


if ($('scannerSearch')) {
  $('scannerSearch').oninput =
    renderScanner;
}


if ($('scanBtn')) {
  $('scanBtn').onclick =
    runScanner;
}


function filtered() {
  let rows =
    [...state.results];

  const q =
    $('scannerSearch')
      ? $('scannerSearch')
          .value
          .trim()
          .toUpperCase()
      : '';

  if (q) {
    rows =
      rows.filter(x =>
        String(
          x.symbol || ''
        ).toUpperCase().includes(q)
      );
  }

  if (state.signals.size) {
    rows =
      rows.filter(x =>
        state.signals.has(
          x.signal
        )
      );
  }

  const field =
    state.sort;

  rows.sort((x, y) => {

    let a =
      field === 'signal'
        ? signalRank[x.signal] || 0
        : field === 'symbol'
        ? x.symbol || ''
        : x[field] ?? 0;

    let b =
      field === 'signal'
        ? signalRank[y.signal] || 0
        : field === 'symbol'
        ? y.symbol || ''
        : y[field] ?? 0;

    if (
      typeof a === 'string' ||
      typeof b === 'string'
    ) {
      return String(a).localeCompare(
        String(b)
      ) * state.dir;
    }

    return (
      (Number(a) - Number(b)) *
      state.dir
    );
  });

  return rows;
}


function renderScanner() {
  const rows =
    filtered();

  if (!$('scannerBody')) return;

  $('scannerBody').innerHTML =
    rows.length

      ? rows.map(x => `

        <tr
          onclick="selectSymbol('${x.symbol}')"
        >

          <td>
            <b>
              ${String(
                x.symbol || ''
              ).replace(
                'USDT',
                ''
              )}
            </b>

            <small>
              USDT
            </small>
          </td>

          <td>
            ${fmt(x.price)}
          </td>

          <td class="${
            Number(x.change) >= 0
              ? 'up'
              : 'down'
          }">
            ${pct(x.change)}
          </td>

          <td>
            <span class="signal ${
              sigClass(x.signal)
            }">
              ${x.signal || '—'}
            </span>
          </td>

          <td>
            ${
              Number(
                x.score10 || 0
              ).toFixed(1)
            }/10
          </td>

          <td>
            ${money(x.volume)}
          </td>

          <td>
            ${
              x.interval ||
              state.interval
            }
          </td>

        </tr>

      `).join('')

      : `
        <tr>
          <td
            colspan="7"
            class="empty"
          >
            لا توجد نتائج مطابقة
          </td>
        </tr>
      `;
}


/* =========================
   الفحص
========================= */

async function runScanner() {
  if (state.busy) return;

  state.busy = true;

  if ($('scannerStatus')) {
    $('scannerStatus').textContent =
      'جاري فحص أعلى العملات سيولة...';
  }

  try {
    const d =
      await api(
        `/api/binance/scan?interval=${state.interval}&limit=40`
      );

    state.results =
      d.results || [];

    if ($('scannerStatus')) {
      $('scannerStatus').textContent =
        `تم العثور على ${state.results.length} فرصة` +
        (
          d.cached
            ? ' — نتيجة محفوظة مؤقتًا'
            : ''
        );
    }

    renderScanner();

    captureRecent();

    if (state.interval === '15m') {
      state.homeResults =
        [...state.results];

      updateHomeFromResults(
        state.homeResults
      );
    }

  } catch (e) {

    if ($('scannerStatus')) {
      $('scannerStatus').textContent =
        `تعذر الفحص: ${e.message}`;
    }

  } finally {
    state.busy = false;
  }
}


/* =========================
   صفقات السبوت
========================= */

function captureRecent() {
  const now =
    Date.now();

  const bucket =
    Math.floor(now / 300000);

  const old =
    new Set(
      state.recent.map(
        x => x.key
      )
    );

  state.results
    .filter(
      x =>
        x.signal !== 'حيادي'
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
    state.recent.slice(0, 60);

  localStorage.setItem(
    'mudarib_recent',
    JSON.stringify(
      state.recent
    )
  );

  renderRecent();
}


function renderRecent() {
  const rows =
    state.recent;

  if (!$('recentList')) return;

  if (!rows.length) {
    $('recentList').innerHTML =
      '<div class="empty-card">ما فيه صفقات سبوت حديثة حتى الآن.</div>';
    return;
  }

  $('recentList').innerHTML =
    rows.slice(0, 30).map(x => `

      <div
        class="recent-card"
        onclick="selectSymbol('${x.symbol}')"
      >

        <div>

          <b>
            ${x.symbol}
          </b>

          <small>
            ${
              new Date(
                x.time
              ).toLocaleString(
                'ar-SA'
              )
            }
          </small>

        </div>

        <span class="signal ${
          sigClass(x.signal)
        }">
          ${x.signal}
        </span>

        <div>

          <small>
            السعر
          </small>

          <b>
            ${fmt(x.price)}
          </b>

        </div>

        <div class="${
          Number(x.change) >= 0
            ? 'up'
            : 'down'
        }">

          ${pct(x.change)}

        </div>

        <div>

          <small>
            TP1 / وقف
          </small>

          <b>
            ${fmt(x.tp1)} /
            ${fmt(x.sl)}
          </b>

        </div>

      </div>

    `).join('');
}


if ($('clearRecent')) {
  $('clearRecent').onclick =
    () => {

      state.recent = [];

      localStorage.removeItem(
        'mudarib_recent'
      );

      renderRecent();
    };
}


/* =========================
   الفيوتشر
========================= */

function renderFutures() {
  const box =
    $('futuresList');

  if (!box) return;

  if (!state.futures.length) {
    box.innerHTML =
      '<div class="empty-card">لا توجد صفقات فيوتشر متاحة حاليًا.</div>';
    return;
  }

  box.innerHTML =
    state.futures.map(x => `

      <div class="recent-card futures-card">

        <div>

          <b>
            ${x.symbol || '—'}
          </b>

          <small>
            ${x.interval || '15m'}
          </small>

        </div>

        <span class="signal ${
          sigClass(x.signal)
        }">
          ${x.signal || '—'}
        </span>

        <div>

          <small>
            الدخول
          </small>

          <b>
            ${fmt(x.entry)}
          </b>

        </div>

        <div>

          <small>
            الهدف
          </small>

          <b>
            ${fmt(x.tp || x.tp1)}
          </b>

        </div>

        <div>

          <small>
            وقف الخسارة
          </small>

          <b>
            ${fmt(x.sl)}
          </b>

        </div>

        <div>

          <small>
            الرافعة
          </small>

          <b>
            ${x.leverage || 10}x
          </b>

        </div>

      </div>

    `).join('');
}


async function loadFutures() {
  const box =
    $('futuresList');

  if (!box) return;

  box.innerHTML =
    '<div class="empty-card">جاري تحميل صفقات الفيوتشر...</div>';

  try {
    const d =
      await api(
        '/api/futures/signals'
      );

    state.futures =
      d.results ||
      d.signals ||
      d.data ||
      [];

    renderFutures();

  } catch (e) {

    box.innerHTML =
      `<div class="empty-card">تعذر تحميل صفقات الفيوتشر: ${e.message}</div>`;
  }
}


if ($('refreshFutures')) {
  $('refreshFutures').onclick =
    loadFutures;
}


/* =========================
   السوق الأمريكي
========================= */

function renderUSMarket() {
  const box =
    $('usMarketList');

  if (!box) return;

  if (!state.usMarket.length) {
    box.innerHTML =
      '<div class="empty-card">لا توجد صفقات للسوق الأمريكي متاحة حاليًا.</div>';
    return;
  }

  box.innerHTML =
    state.usMarket.map(x => `

      <div class="recent-card us-market-card">

        <div>

          <b>
            ${x.symbol ||
              x.ticker ||
              '—'}
          </b>

          <small>
            ${x.name ||
              'السوق الأمريكي'}
          </small>

        </div>

        <span class="signal ${
          sigClass(x.signal)
        }">
          ${x.signal || '—'}
        </span>

        <div>

          <small>
            الدخول
          </small>

          <b>
            ${fmt(x.entry)}
          </b>

        </div>

        <div>

          <small>
            الهدف 1
          </small>

          <b>
            ${fmt(
              x.tp1 ||
              x.tp
            )}
          </b>

        </div>

        <div>

          <small>
            الهدف 2
          </small>

          <b>
            ${fmt(x.tp2)}
          </b>

        </div>

        <div>

          <small>
            وقف
          </small>

          <b>
            ${fmt(x.sl)}
          </b>

        </div>

        <div>

          <small>
            الفريم
          </small>

          <b>
            ${x.interval || '15m'}
          </b>

        </div>

      </div>

    `).join('');
}


async function loadUSMarket() {
  const box =
    $('usMarketList');

  if (!box) return;

  box.innerHTML =
    '<div class="empty-card">جاري تحميل السوق الأمريكي...</div>';

  try {
    const d =
      await api(
        '/api/usmarket/signals'
      );

    state.usMarket =
      d.results ||
      d.signals ||
      d.data ||
      [];

    renderUSMarket();

    updateUSHomeState(
      state.usMarket
    );

  } catch (e) {

    box.innerHTML =
      `<div class="empty-card">تعذر تحميل السوق الأمريكي: ${e.message}</div>`;

    if ($('usState')) {
      $('usState').textContent =
        'تعذر تحميل البيانات';
    }
  }
}


if ($('refreshUSMarket')) {
  $('refreshUSMarket').onclick =
    loadUSMarket;
}


/* =========================
   التحليل
========================= */

async function loadAnalysis() {
  const sym =
    state.symbol;

  try {
    const d =
      await api(
        `/api/binance/analysis?symbol=${encodeURIComponent(sym)}&interval=${state.interval}`
      );

    const a =
      d.analysis || {};

    state.homeAnalysis[
      state.interval
    ] = a;

    if ($('dashSymbol')) {
      $('dashSymbol').textContent =
        sym;
    }

    if ($('dashPrice')) {
      $('dashPrice').textContent =
        fmt(a.price);
    }

    if ($('dashChange')) {
      $('dashChange').textContent =
        a.change != null
          ? pct(a.change)
          : '—';
    }

    if ($('bigSignal')) {
      $('bigSignal').textContent =
        a.signal || '—';

      $('bigSignal').className =
        `signal-big ${
          sigClass(a.signal)
        }`;
    }

    if ($('scoreText')) {
      $('scoreText').textContent =
        `${Number(a.score || 0)}/100`;
    }

    if ($('scoreBar')) {
      $('scoreBar').style.width =
        `${Math.max(
          0,
          Math.min(
            100,
            Number(a.score || 0)
          )
        )}%`;
    }

    if ($('entry')) {
      $('entry').textContent =
        fmt(a.entry);
    }

    if ($('tp1')) {
      $('tp1').textContent =
        fmt(a.tp1);
    }

    if ($('tp2')) {
      $('tp2').textContent =
        fmt(a.tp2);
    }

    if ($('tp3')) {
      $('tp3').textContent =
        fmt(a.tp3);
    }

    if ($('sl')) {
      $('sl').textContent =
        fmt(a.sl);
    }

    if ($('rsi')) {
      $('rsi').textContent =
        a.rsi != null
          ? Number(a.rsi).toFixed(1)
          : '—';
    }

    if ($('ema20')) {
      $('ema20').textContent =
        fmt(a.ema20);
    }

    if ($('ema50')) {
      $('ema50').textContent =
        fmt(a.ema50);
    }

    if ($('ema200')) {
      $('ema200').textContent =
        fmt(a.ema200);
    }

    if ($('analysisMeta')) {
      $('analysisMeta').textContent =
        `${sym} · ${state.interval}`;
    }

    if ($('reasons')) {
      $('reasons').innerHTML =
        (a.reasons || [])
          .map(x => `<li>${x}</li>`)
          .join('');
    }

    drawChart(
      a.candles || []
    );

    updateHomeTimeframe(
      state.interval,
      a.signal
    );

  } catch (e) {

    if ($('bigSignal')) {
      $('bigSignal').textContent =
        'تعذر تحميل التحليل';
    }
  }
}


window.selectSymbol = symbol => {
  state.symbol =
    symbol;

  showSection(
    'dashboard'
  );

  loadAnalysis();

  loadHomeMultiTimeframe(
    symbol
  );
};


/* =========================
   الرسم البياني
========================= */

function drawChart(candles) {
  const canvas =
    $('priceChart');

  if (
    !canvas ||
    typeof Chart === 'undefined'
  ) {
    return;
  }

  if (state.chart) {
    state.chart.destroy();
    state.chart = null;
  }

  if (!candles.length) {
    return;
  }

  state.chart =
    new Chart(
      canvas,
      {
        type: 'line',

        data: {
          labels:
            candles.map(x =>
              new Date(
                x.t
              ).toLocaleTimeString(
                'ar-SA',
                {
                  hour: '2-digit',
                  minute: '2-digit'
                }
              )
            ),

          datasets: [{
            label:
              state.symbol,

            data:
              candles.map(
                x => x.c
              ),

            borderWidth: 2,

            pointRadius: 0,

            tension: 0.2
          }]
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
                color:
                  'rgba(127,127,127,.15)'
              }
            }
          }
        }
      }
    );
}


/* =========================
   الأخبار
========================= */

async function loadNews() {
  const box =
    $('newsList');

  if (!box) return;

  box.innerHTML =
    '<div class="empty-card">جاري تحميل الأخبار...</div>';

  try {
    const d =
      await api(
        '/api/news'
      );

    const news =
      d.news || [];

    box.innerHTML =
      news.length

        ? news.map(n => `

          <a
            class="news-card"
            href="${n.link || '#'}"
            target="_blank"
            rel="noopener"
          >

            <small>
              ${n.source || ''} ·
              ${n.published || ''}
            </small>

            <h3>
              ${n.title || ''}
            </h3>

            <p>
              ${n.description || ''}
            </p>

          </a>

        `).join('')

        : '<div class="empty-card">لا توجد أخبار متاحة حاليًا.</div>';

  } catch (e) {

    box.innerHTML =
      `<div class="empty-card">${e.message}</div>`;
  }
}


if ($('newsBtn')) {
  $('newsBtn').onclick =
    loadNews;
}


if ($('newsRefresh')) {
  $('newsRefresh').onclick =
    loadNews;
}


/* =========================
   الاشتراك
========================= */

async function loadSubscription() {
  if (!$('subscriptionStatus')) {
    return;
  }

  try {
    const d =
      await api(
        '/api/subscription/plans'
      );

    renderPlans(d);

    const s =
      await api(
        '/api/subscription/my'
      );

    $('subscriptionStatus').innerHTML =
      s.active

        ? `<div class="active-plan">
             ✅ اشتراكك فعال — ${s.plan}
             — ينتهي
             ${new Date(
               s.expires
             ).toLocaleDateString(
               'ar-SA'
             )}
           </div>`

        : '<div class="inactive-plan">لا يوجد اشتراك فعال حاليًا.</div>';

    renderPaymentHistory(
      s.requests || []
    );

  } catch (e) {

    if ($('subscriptionStatus')) {
      $('subscriptionStatus').innerHTML =
        `<div class="error">${e.message}</div>`;
    }
  }
}


function renderPlans(d) {
  if ($('payAddress')) {
    $('payAddress').value =
      d.address || '';
  }

  if (!$('plans')) return;

  $('plans').innerHTML =
    Object.entries(
      d.plans || {}
    )
      .map(
        ([key, plan]) => `

        <button
          class="plan-card"
          data-plan="${key}"
          type="button"
        >

          <b>
            ${plan.name}
          </b>

          <strong>
            ${plan.amount} USDT
          </strong>

          <small>
            دفع عبر TRC20
          </small>

        </button>

      `
      )
      .join('');

  document
    .querySelectorAll(
      '.plan-card'
    )
    .forEach(button => {

      button.onclick = () => {
        choosePlan(
          button.dataset.plan,
          d.plans[
            button.dataset.plan
          ]
        );
      };

    });
}


function choosePlan(key, plan) {
  state.plan =
    key;

  if ($('paymentBox')) {
    $('paymentBox').hidden =
      false;
  }

  if ($('chosenPlan')) {
    $('chosenPlan').innerHTML =
      `الباقة المختارة:
       <b>${plan.name}</b>
       —
       <b>${plan.amount} USDT</b>`;
  }

  if ($('qrBox')) {
    $('qrBox').innerHTML = '';
  }

  if (
    window.QRCode &&
    $('qrBox') &&
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

  if ($('paymentBox')) {
    $('paymentBox').scrollIntoView({
      behavior: 'smooth'
    });
  }
}


if ($('copyAddress')) {
  $('copyAddress').onclick =
    async () => {

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

      } catch {}
    };
}


if ($('sendPayment')) {
  $('sendPayment').onclick =
    async () => {

      if (!state.plan) {
        return;
      }

      try {
        const d =
          await api(
            '/api/subscription/request',
            {
              method: 'POST',

              body:
                JSON.stringify({
                  plan:
                    state.plan,

                  txid:
                    $('txid')
                      ? $('txid').value.trim()
                      : ''
                })
            }
          );

        if ($('paymentMsg')) {
          $('paymentMsg').innerHTML =
            `<span class="ok">${d.message || 'تم إرسال الطلب'} ✅</span>`;
        }

        if ($('txid')) {
          $('txid').value = '';
        }

        loadSubscription();

      } catch (e) {

        if ($('paymentMsg')) {
          $('paymentMsg').innerHTML =
            `<span class="error">${e.message}</span>`;
        }
      }
    };
}


function renderPaymentHistory(rows) {
  if (!$('paymentHistory')) return;

  $('paymentHistory').innerHTML =
    rows.length

      ? `<h3>طلبات الدفع</h3>

         <div class="payment-history">

           ${rows.map(
             x => `

             <div>

               <b>
                 ${x.plan}
               </b>

               <span>
                 ${x.amount} USDT
               </span>

               <span class="status-${x.status}">
                 ${
                   x.status === 'pending'
                     ? 'قيد المراجعة'
                     : x.status === 'approved'
                     ? 'مقبول'
                     : 'مرفوض'
                 }
               </span>

             </div>

           `
           ).join('')}

         </div>`

      : '';
}


/* =========================
   الصفحة الرئيسية
========================= */

function updateHomeFromResults(results) {
  if (!Array.isArray(results)) {
    results = [];
  }

  state.homeResults =
    results;

  const buy =
    results.filter(
      x =>
        x.signal === 'شراء' ||
        x.signal === 'شراء قوي'
    ).length;

  const sell =
    results.filter(
      x =>
        x.signal === 'بيع' ||
        x.signal === 'بيع قوي'
    ).length;

  const neutral =
    results.filter(
      x =>
        x.signal === 'حيادي'
    ).length;

  const total =
    results.length;

  if ($('buyCount')) {
    $('buyCount').textContent =
      buy;
  }

  if ($('sellCount')) {
    $('sellCount').textContent =
      sell;
  }

  if ($('neutralCount')) {
    $('neutralCount').textContent =
      neutral;
  }

  if ($('totalCount')) {
    $('totalCount').textContent =
      total;
  }

  if (total) {
    const buyPercent =
      (buy / total) * 100;

    const neutralPercent =
      (neutral / total) * 100;

    const sellPercent =
      (sell / total) * 100;

    if ($('buyMeter')) {
      $('buyMeter').style.width =
        buyPercent + '%';
    }

    if ($('neutralMeter')) {
      $('neutralMeter').style.width =
        neutralPercent + '%';
    }

    if ($('sellMeter')) {
      $('sellMeter').style.width =
        sellPercent + '%';
    }

    let direction =
      'حيادي';

    let className =
      'state-neutral';

    if (
      buy > sell &&
      buy > neutral
    ) {
      direction =
        'ميل شرائي';

      className =
        'state-buy';

    } else if (
      sell > buy &&
      sell > neutral
    ) {
      direction =
        'ميل بيعي';

      className =
        'state-sell';
    }

    if ($('marketDirection')) {
      $('marketDirection').textContent =
        direction;

      $('marketDirection').className =
        className;
    }

    if ($('cryptoState')) {
      $('cryptoState').textContent =
        direction;
    }
  }

  renderHomePulse(results);
  renderHomeOpportunities(results);
  renderHomeTicker(results);
  showStrongHomeTrade(results);
}


function renderHomePulse(results) {
  const box =
    $('marketPulse');

  if (!box) return;

  if (!results.length) {
    box.innerHTML =
      '<div class="empty-home">لا توجد بيانات حالياً.</div>';
    return;
  }

  const rows =
    [...results]
      .sort(
        (a, b) =>
          Number(b.score || 0) -
          Number(a.score || 0)
      )
      .slice(0, 8);

  box.innerHTML =
    rows.map(x => `

      <div
        class="pulse-row"
        onclick="selectSymbol('${x.symbol}')"
      >

        <div class="pulse-symbol">
          ${
            String(
              x.symbol || ''
            ).replace(
              'USDT',
              ''
            )
          }
        </div>

        <div class="${
          signalTextClass(
            x.signal
          )
        } pulse-signal">

          ${signalEmoji(x.signal)}
          ${x.signal || '—'}

        </div>

        <div>
          ${
            Number(
              x.score10 || 0
            ).toFixed(1)
          }/10
        </div>

      </div>

    `).join('');
}


function renderHomeOpportunities(results) {
  const box =
    $('homeOpportunities');

  if (!box) return;

  const rows =
    [...results]
      .filter(
        x =>
          x.signal &&
          x.signal !== 'حيادي'
      )
      .sort(
        (a, b) =>
          Number(b.score || 0) -
          Number(a.score || 0)
      )
      .slice(0, 6);

  if (!rows.length) {
    box.innerHTML =
      '<div class="empty-home">لا توجد فرصة واضحة حالياً.</div>';
    return;
  }

  box.innerHTML =
    rows.map(x => `

      <div
        class="opportunity"
        onclick="selectSymbol('${x.symbol}')"
      >

        <div>

          <b>
            ${x.symbol}
          </b>

          <small>
            ${
              x.interval ||
              state.interval
            }
          </small>

        </div>

        <div class="${
          signalTextClass(
            x.signal
          )
        }">

          ${signalEmoji(x.signal)}
          ${x.signal}

        </div>

        <div>
          ${
            Number(
              x.score10 || 0
            ).toFixed(1)
          }/10
        </div>

      </div>

    `).join('');
}


function renderHomeTicker(results) {
  const box =
    $('homeTicker');

  if (!box) return;

  const rows =
    [...results]
      .filter(
        x =>
          x.signal &&
          x.signal !== 'حيادي'
      )
      .sort(
        (a, b) =>
          Number(b.score || 0) -
          Number(a.score || 0)
      )
      .slice(0, 20);

  if (!rows.length) {
    box.innerHTML =
      '<span class="ticker-item">📡 جاري تحليل السوق...</span>';
    return;
  }

  box.innerHTML =
    rows.map(x => `

      <span class="ticker-item">

        ${signalEmoji(x.signal)}

        ${x.symbol}

        ${x.signal}

        ${
          Number(
            x.score10 || 0
          ).toFixed(1)
        }/10

      </span>

    `).join('');
}


function showStrongHomeTrade(results) {
  const rows =
    [...results]
      .filter(
        x =>
          x.signal &&
          x.signal !== 'حيادي'
      )
      .sort(
        (a, b) =>
          Number(b.score || 0) -
          Number(a.score || 0)
      );

  const x =
    rows[0];

  if (!x) return;

  if ($('strongSymbol')) {
    $('strongSymbol').textContent =
      x.symbol;
  }

  if ($('strongSignal')) {
    $('strongSignal').textContent =
      x.signal;

    $('strongSignal').className =
      `trade-signal ${
        signalTextClass(x.signal)
      }`;
  }

  if ($('strongEntry')) {
    $('strongEntry').textContent =
      fmt(
        x.entry ||
        x.price
      );
  }

  if ($('strongTP')) {
    $('strongTP').textContent =
      fmt(
        x.tp1 ||
        x.tp
      );
  }

  if ($('strongSL')) {
    $('strongSL').textContent =
      fmt(x.sl);
  }

  const score =
    Math.max(
      0,
      Math.min(
        100,
        Number(x.score || 0)
      )
    );

  if ($('strongScore')) {
    $('strongScore').textContent =
      score.toFixed(0) + '%';
  }

  if ($('strongScoreBar')) {
    $('strongScoreBar').style.width =
      score + '%';
  }

  if ($('multiTFSymbol')) {
    $('multiTFSymbol').textContent =
      x.symbol;
  }
}


/* =========================
   توافق الفريمات
========================= */

function updateHomeTimeframe(
  interval,
  signal
) {
  const ids = {
    '5m': 'tf5',
    '15m': 'tf15',
    '1h': 'tf1h',
    '4h': 'tf4h',
    '1d': 'tf1d'
  };

  const id =
    ids[interval];

  if (!id || !$(`${id}`)) {
    return;
  }

  $(`${id}`).textContent =
    signal || '—';

  $(`${id}`).className =
    signalTextClass(
      signal
    );
}


async function loadHomeMultiTimeframe(symbol) {
  if (!symbol) {
    symbol =
      state.symbol;
  }

  if ($('multiTFSymbol')) {
    $('multiTFSymbol').textContent =
      symbol;
  }

  const frames = [
    ['5m', 'tf5'],
    ['15m', 'tf15'],
    ['1h', 'tf1h'],
    ['4h', 'tf4h'],
    ['1d', 'tf1d']
  ];

  await Promise.all(
    frames.map(
      async ([interval, id]) => {

        const element =
          $(id);

        if (!element) return;

        element.textContent =
          '...';

        try {
          const d =
            await api(
              `/api/binance/analysis?symbol=${encodeURIComponent(symbol)}&interval=${interval}`
            );

          const a =
            d.analysis || {};

          state.homeAnalysis[
            interval
          ] = a;

          element.textContent =
            a.signal || '—';

          element.className =
            signalTextClass(
              a.signal
            );

        } catch {
          element.textContent =
            '—';

          element.className = '';
        }
      }
    )
  );
}


/* =========================
   حالة السوق الأمريكي
========================= */

function updateUSHomeState(rows) {
  if (!$('usState')) return;

  if (
    !Array.isArray(rows) ||
    !rows.length
  ) {
    $('usState').textContent =
      'لا توجد إشارات حالياً';
    return;
  }

  const buy =
    rows.filter(
      x =>
        x.signal === 'شراء' ||
        x.signal === 'شراء قوي'
    ).length;

  const sell =
    rows.filter(
      x =>
        x.signal === 'بيع' ||
        x.signal === 'بيع قوي'
    ).length;

  $('usState').textContent =
    buy > sell
      ? 'ميل شرائي'
      : sell > buy
      ? 'ميل بيعي'
      : 'حيادي';
}


/* =========================
   اختيار السوق الرئيسي
========================= */

function setHomeMarket(market) {
  state.homeMarket =
    market;

  document
    .querySelectorAll(
      '[data-home-market]'
    )
    .forEach(button => {
      button.classList.toggle(
        'active',
        button.dataset.homeMarket ===
          market
      );
    });

  const names = {
    crypto: 'العملات الرقمية',
    saudi: 'السوق السعودي',
    us: 'السوق الأمريكي',
    forex: 'الفوركس'
  };

  if ($('marketOverviewTitle')) {
    $('marketOverviewTitle').textContent =
      names[market] ||
      'العملات الرقمية';
  }

  if (market === 'saudi') {

    if ($('saudiState')) {
      $('saudiState').textContent =
        'بيانات السوق';
    }

    if ($('marketDirection')) {
      $('marketDirection').textContent =
        'السوق السعودي';

      $('marketDirection').className =
        'state-neutral';
    }

    return;
  }

  if (market === 'forex') {

    if ($('forexState')) {
      $('forexState').textContent =
        'بيانات السوق';
    }

    if ($('marketDirection')) {
      $('marketDirection').textContent =
        'الفوركس';

      $('marketDirection').className =
        'state-neutral';
    }

    return;
  }

  if (market === 'us') {

    if (state.usMarket.length) {
      updateUSHomeState(
        state.usMarket
      );
    }

    if ($('marketDirection')) {
      $('marketDirection').textContent =
        'السوق الأمريكي';

      $('marketDirection').className =
        'state-neutral';
    }

    return;
  }

  updateHomeFromResults(
    state.homeResults
  );
}


document
  .querySelectorAll(
    '[data-home-market]'
  )
  .forEach(button => {

    button.addEventListener(
      'click',
      () => {
        setHomeMarket(
          button.dataset.homeMarket
        );
      }
    );
  });


/* =========================
   تحديث الرئيسية
========================= */

async function refreshProfessionalHome() {

  try {
    const d =
      await api(
        '/api/binance/scan?interval=15m&limit=40'
      );

    const results =
      d.results || [];

    state.homeResults =
      results;

    if (
      state.homeMarket ===
      'crypto'
    ) {
      updateHomeFromResults(
        results
      );
    }

    if ($('homeLiveStatus')) {
      $('homeLiveStatus').textContent =
        'آخر تحديث: ' +
        new Date().toLocaleTimeString(
          'ar-SA',
          {
            hour: '2-digit',
            minute: '2-digit'
          }
        );
    }

  } catch {

    if ($('homeLiveStatus')) {
      $('homeLiveStatus').textContent =
        'تعذر تحديث بيانات السوق';
    }
  }


  try {
    const d =
      await api(
        '/api/usmarket/signals'
      );

    state.usMarket =
      d.results ||
      d.signals ||
      d.data ||
      [];

    updateUSHomeState(
      state.usMarket
    );

  } catch {

    if ($('usState')) {
      $('usState').textContent =
        'بيانات السوق';
    }
  }


  try {
    const d =
      await api(
        '/api/news'
      );

    const news =
      d.news || [];

    if ($('homeNews')) {
      $('homeNews').innerHTML =
        news.length

          ? news
              .slice(0, 6)
              .map(
                n => `

                <a
                  class="home-news-card"
                  href="${n.link || '#'}"
                  target="_blank"
                  rel="noopener"
                >

                  <small>
                    ${
                      n.source ||
                      'أخبار'
                    }
                    ·
                    ${
                      n.published ||
                      ''
                    }
                  </small>

                  <h4>
                    ${
                      n.title ||
                      'خبر'
                    }
                  </h4>

                </a>

              `
              )
              .join('')

          : '<div class="empty-home">لا توجد أخبار متاحة حالياً.</div>';
    }

  } catch {

    if ($('homeNews')) {
      $('homeNews').innerHTML =
        '<div class="empty-home">تعذر تحميل الأخبار.</div>';
    }
  }
}


window.refreshProfessionalHome =
  refreshProfessionalHome;


/* =========================
   الوضع الليلي
========================= */

if ($('themeBtn')) {
  $('themeBtn').onclick =
    () => {

      document.body.classList.toggle(
        'light'
      );

      localStorage.setItem(
        'theme',
        document.body.classList.contains(
          'light'
        )
          ? 'light'
          : 'dark'
      );
    };
}


if (
  localStorage.getItem(
    'theme'
  ) === 'light'
) {
  document.body.classList.add(
    'light'
  );
}


/* =========================
   التشغيل
========================= */

(async function boot() {

  await checkAuth();

  /*
     مهم:
     systemStatus عنصر دائرة
     فلا نكتب بداخله نص.
  */

  if ($('systemStatus')) {
    $('systemStatus').classList.add(
      'online'
    );
  }

  if ($('systemStatusText')) {
    $('systemStatusText').textContent =
      'النظام متصل';
  }

  await runScanner();

  await loadAnalysis();

  await loadHomeMultiTimeframe(
    state.symbol
  );

  await loadNews();

  renderRecent();

  await loadFutures();

  await loadUSMarket();

  await refreshProfessionalHome();


  setInterval(
    () => {
      runScanner();
    },
    60000
  );


  setInterval(
    () => {
      loadHomeMultiTimeframe(
        state.symbol
      );
    },
    60000
  );


  setInterval(
    () => {
      loadNews();
    },
    600000
  );


  setInterval(
    () => {
      loadFutures();
    },
    60000
  );


  setInterval(
    () => {
      loadUSMarket();
    },
    60000
  );


  setInterval(
    () => {
      refreshProfessionalHome();
    },
    60000
  );

})();

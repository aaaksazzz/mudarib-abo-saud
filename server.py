* {
  box-sizing: border-box;
}

:root {
  --bg: #07111f;
  --bg2: #0b1728;
  --card: #0e1c2f;
  --card2: #12233a;
  --border: rgba(255,255,255,.08);
  --text: #f4f7fb;
  --muted: #91a2b8;
  --green: #22c55e;
  --red: #ef4444;
  --yellow: #f59e0b;
  --blue: #3b82f6;
  --cyan: #06b6d4;
  --shadow: 0 10px 30px rgba(0,0,0,.20);
  --radius: 16px;
}

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family:
    Tahoma,
    Arial,
    sans-serif;
  direction: rtl;
  min-height: 100vh;
}

button,
input,
select {
  font: inherit;
}

button {
  cursor: pointer;
}

a {
  color: inherit;
  text-decoration: none;
}

/* =========================
   APP
========================= */

.app-shell {
  min-height: 100vh;
  display: flex;
}

/* =========================
   SIDEBAR
========================= */

.sidebar {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 235px;
  background: #091525;
  border-left: 1px solid var(--border);
  overflow-y: auto;
  z-index: 100;
  padding: 16px 12px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 10px 18px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}

.logo-icon {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2563eb, #06b6d4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
}

.logo-text {
  font-weight: 800;
  font-size: 16px;
}

.logo-sub {
  color: var(--muted);
  font-size: 11px;
  margin-top: 3px;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.nav button {
  width: 100%;
  border: 0;
  background: transparent;
  color: #b8c5d5;
  padding: 11px 12px;
  border-radius: 11px;
  text-align: right;
  transition: .15s ease;
}

.nav button:hover,
.nav button.active {
  background: rgba(59,130,246,.14);
  color: #fff;
}

.nav-title {
  color: #61758e;
  font-size: 10px;
  margin: 15px 10px 5px;
}

/* =========================
   MAIN
========================= */

.main {
  width: calc(100% - 235px);
  margin-right: 235px;
  min-height: 100vh;
}

/* =========================
   TOPBAR
========================= */

.topbar {
  position: sticky;
  top: 0;
  z-index: 50;
  height: 62px;
  background: rgba(7,17,31,.94);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
}

.page-title {
  font-size: 17px;
  font-weight: 800;
}

.system-status {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--green);
  font-size: 12px;
  font-weight: 700;
}

/* =========================
   CONTENT
========================= */

.content {
  padding: 20px;
  max-width: 1500px;
  margin: auto;
}

.section {
  display: none;
}

.section.active {
  display: block;
}

/* =========================
   HERO
========================= */

.hero {
  background:
    radial-gradient(circle at 10% 20%, rgba(37,99,235,.25), transparent 35%),
    radial-gradient(circle at 90% 80%, rgba(6,182,212,.16), transparent 35%),
    var(--card);
  border: 1px solid var(--border);
  border-radius: 22px;
  padding: 24px;
  box-shadow: var(--shadow);
  margin-bottom: 18px;
}

.hero h1 {
  margin: 0 0 8px;
  font-size: 26px;
}

.hero p {
  color: var(--muted);
  margin: 0;
  line-height: 1.8;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}

.market-btn {
  border: 1px solid var(--border);
  background: rgba(255,255,255,.04);
  color: #dce6f3;
  padding: 9px 13px;
  border-radius: 10px;
}

.market-btn:hover {
  background: rgba(59,130,246,.15);
  border-color: rgba(59,130,246,.4);
}

/* =========================
   LIVE STATS
========================= */

.live-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

.stat-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}

.stat-label {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 22px;
  font-weight: 900;
}

.stat-value.green {
  color: var(--green);
}

.stat-value.red {
  color: var(--red);
}

/* =========================
   MARKET CARDS
========================= */

.market-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.market-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}

.market-card h3 {
  margin: 0 0 7px;
  font-size: 14px;
}

.market-card .value {
  font-size: 20px;
  font-weight: 900;
}

.market-card .small {
  color: var(--muted);
  font-size: 11px;
  margin-top: 5px;
}

/* =========================
   SECTION HEADER
========================= */

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 22px 0 12px;
}

.section-header h2 {
  margin: 0;
  font-size: 18px;
}

.section-header p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}

/* =========================
   SIGNAL GRID
========================= */

.signals-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.signal-card {
  position: relative;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 15px;
  overflow: hidden;
}

.signal-card.buy {
  border-right: 3px solid var(--green);
}

.signal-card.sell {
  border-right: 3px solid var(--red);
}

.signal-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 13px;
}

.signal-symbol {
  font-size: 17px;
  font-weight: 900;
}

.signal-market {
  color: var(--muted);
  font-size: 10px;
  margin-top: 3px;
}

.signal-badge {
  padding: 5px 9px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 900;
}

.signal-badge.buy {
  color: #86efac;
  background: rgba(34,197,94,.13);
}

.signal-badge.sell {
  color: #fca5a5;
  background: rgba(239,68,68,.13);
}

.signal-price {
  margin-bottom: 12px;
}

.signal-price span {
  display: block;
  color: var(--muted);
  font-size: 10px;
  margin-bottom: 4px;
}

.signal-price strong {
  font-size: 20px;
}

.signal-levels {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 7px;
}

.level {
  background: rgba(255,255,255,.035);
  border-radius: 9px;
  padding: 8px;
}

.level span {
  display: block;
  color: var(--muted);
  font-size: 9px;
  margin-bottom: 4px;
}

.level strong {
  font-size: 12px;
}

.level.entry strong {
  color: #e2e8f0;
}

.level.tp strong {
  color: var(--green);
}

.level.sl strong {
  color: var(--red);
}

.signal-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 10px;
}

.score {
  font-weight: 900;
  color: var(--yellow);
}

/* =========================
   EMPTY
========================= */

.empty {
  background: var(--card);
  border: 1px dashed rgba(255,255,255,.12);
  border-radius: var(--radius);
  padding: 30px 18px;
  text-align: center;
  color: var(--muted);
}

.empty strong {
  display: block;
  color: #d8e2ef;
  margin-bottom: 6px;
}

/* =========================
   SCANNER
========================= */

.scanner-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.scanner-tools input,
.scanner-tools select {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 10px;
  padding: 10px 12px;
  outline: none;
}

.scanner-tools input {
  min-width: 180px;
  flex: 1;
}

.scan-btn,
.news-btn {
  border: 0;
  background: linear-gradient(135deg, #2563eb, #0891b2);
  color: #fff;
  padding: 10px 16px;
  border-radius: 10px;
  font-weight: 800;
}

.scan-btn:disabled,
.news-btn:disabled {
  opacity: .55;
  cursor: not-allowed;
}

.interval-chips {
  display: flex;
  gap: 5px;
}

.interval-chips button {
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--muted);
  border-radius: 9px;
  padding: 8px 11px;
}

.interval-chips button.active {
  background: rgba(59,130,246,.18);
  color: #fff;
  border-color: rgba(59,130,246,.4);
}

.scanner-status {
  color: var(--muted);
  font-size: 11px;
  margin: 8px 0 12px;
}

.table-wrap {
  width: 100%;
  overflow-x: auto;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.scanner-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 680px;
}

.scanner-table th,
.scanner-table td {
  padding: 12px 10px;
  border-bottom: 1px solid var(--border);
  text-align: right;
  font-size: 12px;
}

.scanner-table th {
  color: var(--muted);
  font-size: 10px;
  font-weight: 700;
}

.scanner-table tr:last-child td {
  border-bottom: 0;
}

.buy-text {
  color: var(--green);
  font-weight: 900;
}

.sell-text {
  color: var(--red);
  font-weight: 900;
}

.neutral-text {
  color: var(--yellow);
  font-weight: 800;
}

/* =========================
   NEWS
========================= */

.news-list {
  display: grid;
  gap: 9px;
}

.news-item {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 13px;
}

.news-item strong {
  display: block;
  font-size: 13px;
  line-height: 1.6;
}

.news-item span {
  display: block;
  color: var(--muted);
  font-size: 10px;
  margin-top: 6px;
}

/* =========================
   AUTH COMPATIBILITY
========================= */

#loginModal,
#registerModal,
#authModal,
.auth-modal {
  display: none !important;
}

/* =========================
   LOADING
========================= */

.loading {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--muted);
}

.loading::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid rgba(255,255,255,.2);
  border-top-color: var(--cyan);
  animation: spin .7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

/* =========================
   MOBILE
========================= */

@media (max-width: 1000px) {
  .sidebar {
    width: 190px;
  }

  .main {
    width: calc(100% - 190px);
    margin-right: 190px;
  }

  .signals-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .market-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 700px) {
  .app-shell {
    display: block;
  }

  .sidebar {
    position: static;
    width: 100%;
    height: auto;
    max-height: none;
    border-left: 0;
    border-bottom: 1px solid var(--border);
    padding: 8px;
  }

  .logo {
    padding: 7px;
    margin-bottom: 6px;
  }

  .nav {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
  }

  .nav-title {
    display: none;
  }

  .nav button {
    font-size: 11px;
    padding: 9px 5px;
    text-align: center;
  }

  .main {
    width: 100%;
    margin-right: 0;
  }

  .topbar {
    height: 52px;
    padding: 0 12px;
  }

  .content {
    padding: 12px;
  }

  .hero {
    padding: 17px;
    border-radius: 16px;
  }

  .hero h1 {
    font-size: 21px;
  }

  .live-stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .market-grid,
  .signals-grid {
    grid-template-columns: 1fr;
  }

  .signal-levels {
    gap: 5px;
  }

  .level {
    padding: 7px 5px;
  }

  .level strong {
    font-size: 11px;
  }

  .scanner-tools {
    flex-direction: column;
  }

  .scanner-tools input,
  .scanner-tools select,
  .scan-btn {
    width: 100%;
  }

  .interval-chips {
    width: 100%;
  }

  .interval-chips button {
    flex: 1;
  }
}

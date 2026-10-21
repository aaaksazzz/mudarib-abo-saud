#!/usr/bin/env python3
"""Standalone Binance USD-M Futures research backtest. No live orders; no site imports."""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import os
import time
import requests
import numpy as np
import pandas as pd

BASE = "https://fapi.binance.com"
INTERVAL = "15m"
DAYS = int(os.getenv("DAYS", "180"))
FEE_BPS = float(os.getenv("FEE_BPS", "5"))  # per side, configurable
SLIPPAGE_BPS = float(os.getenv("SLIPPAGE_BPS", "2"))  # per side
MIN_TRADES = int(os.getenv("MIN_TRADES", "30"))
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "standalone-research-backtest/1.0"})

def get_json(path, params=None, tries=8):
    for attempt in range(tries):
        try:
            r = SESSION.get(BASE + path, params=params, timeout=30)
            if r.status_code in (418, 429):
                time.sleep(min(60, 2 ** attempt)); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == tries - 1: raise
            time.sleep(min(20, 1.5 ** attempt))
    raise RuntimeError("Binance request retries exhausted")

def fetch_symbol(symbol, start_ms, end_ms):
    rows, cursor = [], start_ms
    while cursor < end_ms:
        data = get_json("/fapi/v1/klines", {
            "symbol": symbol, "interval": INTERVAL, "startTime": cursor,
            "endTime": end_ms, "limit": 1500
        })
        if not data: break
        rows.extend(data)
        nxt = int(data[-1][0]) + 15 * 60 * 1000
        if nxt <= cursor: break
        cursor = nxt
        time.sleep(0.25)
    if not rows: return symbol, None
    cols = ["time","open","high","low","close","volume","close_time","quote_volume",
            "trades","taker_base","taker_quote","ignore"]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["open","high","low","close","volume","quote_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.drop_duplicates("time").sort_values("time").set_index("time")
    # Binance may return the currently forming candle: drop it.
    now = pd.Timestamp.now(tz="UTC")
    df = df[df.index + pd.Timedelta(minutes=15) <= now]
    return symbol, df[["open","high","low","close","volume","quote_volume"]].dropna()

def indicators(df):
    c, h, l, v = df.close, df.high, df.low, df.volume
    out = pd.DataFrame(index=df.index)
    e20 = c.ewm(span=20, adjust=False).mean()
    e50 = c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False).mean()
    out["trend_pullback"] = np.where((c > e200) & (e20 > e50) & (c.shift(1) <= e20.shift(1)) & (c > e20), 1,
                              np.where((c < e200) & (e20 < e50) & (c.shift(1) >= e20.shift(1)) & (c < e20), -1, 0))
    hh, ll = h.shift(1).rolling(20).max(), l.shift(1).rolling(20).min()
    vmean = v.shift(1).rolling(20).mean()
    out["breakout_volume"] = np.where((c > hh) & (v > 1.5*vmean), 1,
                               np.where((c < ll) & (v > 1.5*vmean), -1, 0))
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100/(1 + gain/loss.replace(0, np.nan))
    out["mean_reversion"] = np.where((rsi < 25) & (c < e20), 1,
                              np.where((rsi > 75) & (c > e20), -1, 0))
    return out.fillna(0).astype(int)

def backtest(df, signal, symbol, strategy, split):
    # Signal at candle close, fill at next candle open. Position flips only on a new signal.
    d = df.copy()
    d["sig"] = signal.shift(1).fillna(0).astype(int)
    d["pos"] = d["sig"].replace(0, np.nan).ffill().fillna(0)
    # Flat is allowed only until first signal; opposite signal flips direction.
    d["ret"] = d.open.pct_change().fillna(0) + (d.close / d.open - 1)
    # Use next-open to next-open returns, avoiding same-candle lookahead.
    next_open = d.open.shift(-1)
    price_ret = next_open / d.open - 1
    pos = d.pos
    turnover = pos.diff().abs().fillna(pos.abs())
    costs = turnover * ((FEE_BPS + SLIPPAGE_BPS) / 10000.0)
    strat_ret = pos * price_ret - costs
    strat_ret = strat_ret.replace([np.inf, -np.inf], np.nan).dropna()
    if strat_ret.empty: return None
    # Restrict metrics to selected chronological segment; signals still use prior history.
    if split == "train":
        strat_ret = strat_ret[strat_ret.index < d.index[int(len(d)*0.70)]]
    elif split == "test":
        strat_ret = strat_ret[strat_ret.index >= d.index[int(len(d)*0.70)]]
    if len(strat_ret) < 10: return None
    equity = (1 + strat_ret).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    # Trade returns are position-change-delimited; include costs in bar returns.
    active = pos.reindex(strat_ret.index).fillna(0)
    changes = active.ne(active.shift()).cumsum()
    trade_returns = (1 + strat_ret).groupby(changes).prod() - 1
    trade_returns = trade_returns[trade_returns.index.isin(changes[active.ne(0)].unique())]
    wins = int((trade_returns > 0).sum())
    ntrades = int(len(trade_returns))
    gp = float(trade_returns[trade_returns > 0].sum())
    gl = float(-trade_returns[trade_returns < 0].sum())
    return {
        "symbol": symbol, "strategy": strategy, "split": split,
        "bars": int(len(strat_ret)), "trades": ntrades,
        "win_rate_pct": round(100*wins/ntrades, 2) if ntrades else 0,
        "net_return_pct": round(100*(float(equity.iloc[-1])-1), 2),
        "profit_factor": round(gp/gl, 3) if gl > 0 else (999 if gp > 0 else 0),
        "max_drawdown_pct": round(100*float(dd.min()), 2),
        "expectancy_pct_per_trade": round(100*float(trade_returns.mean()), 4) if ntrades else 0,
        "long_short": "both",
        "cost_bps_per_side": FEE_BPS + SLIPPAGE_BPS,
    }

def main():
    end = pd.Timestamp.now(tz="UTC").floor("15min")
    start = end - pd.Timedelta(days=DAYS)
    info = get_json("/fapi/v1/exchangeInfo")
    symbols = [s["symbol"] for s in info["symbols"]
               if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL"
               and s.get("quoteAsset") == "USDT"]
    print(f"Fetching {len(symbols)} USDT perpetual symbols, {start} to {end}; 15m")
    frames, errors = {}, []
    start_ms, end_ms = int(start.timestamp()*1000), int(end.timestamp()*1000)
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch_symbol, sym, start_ms, end_ms): sym for sym in symbols}
        for i, f in enumerate(cf.as_completed(futures), 1):
            sym = futures[f]
            try:
                _, frame = f.result()
                if frame is not None and len(frame) >= 1000: frames[sym] = frame
                else: errors.append((sym, "insufficient candles"))
            except Exception as e:
                errors.append((sym, str(e)[:200]))
            if i % 25 == 0: print(f"Fetched {i}/{len(symbols)}; usable={len(frames)}; errors={len(errors)}")
    os.makedirs("research/standalone_futures_backtest/results", exist_ok=True)
    rows = []
    for i, (sym, df) in enumerate(frames.items(), 1):
        sigs = indicators(df)
        for strategy in sigs.columns:
            for split in ("train", "test", "all"):
                result = backtest(df, sigs[strategy], sym, strategy, split)
                if result: rows.append(result)
        if i % 50 == 0: print(f"Backtested {i}/{len(frames)}")
    out = pd.DataFrame(rows)
    out.to_csv("research/standalone_futures_backtest/results/per_symbol.csv", index=False)
    if not out.empty:
        summary = out.groupby(["strategy","split"], as_index=False).agg(
            symbols=("symbol","nunique"), trades=("trades","sum"),
            net_return_pct_median=("net_return_pct","median"),
            win_rate_pct_median=("win_rate_pct","median"),
            profit_factor_median=("profit_factor","median"),
            max_drawdown_pct_median=("max_drawdown_pct","median"),
            expectancy_pct_median=("expectancy_pct_per_trade","median"))
        summary.to_csv("research/standalone_futures_backtest/results/summary.csv", index=False)
        test = out[(out.split=="test") & (out.trades >= MIN_TRADES)]
        candidates = test[(test.net_return_pct > 0) & (test.profit_factor > 1) & (test.max_drawdown_pct > -25)]
        with open("research/standalone_futures_backtest/results/report.md","w") as f:
            f.write("# Binance Futures standalone backtest\n\n")
            f.write(f"- Window: {start} to {end} UTC; {DAYS} days; 15m candles\n")
            f.write(f"- Symbols available: {len(symbols)}; successfully tested: {len(frames)}; failed/insufficient: {len(errors)}\n")
            f.write(f"- Fee assumption: {FEE_BPS} bps per side; slippage: {SLIPPAGE_BPS} bps per side. Funding not included; results are therefore incomplete for holding-cost assessment.\n")
            f.write("- Signal at candle close, entry/position return from next open; 70/30 chronological train/test split.\n")
            f.write("- **No strategy is labelled successful unless out-of-sample evidence is sufficient.** This is a research screen, not a guarantee.\n\n")
            f.write("## Aggregate median metrics\n\n")
            f.write(summary.to_markdown(index=False))
            f.write("\n\n## Out-of-sample candidate screen\n\n")
            if candidates.empty:
                f.write("No strategy/symbol passed the pre-set screen (at least "
                        f"{MIN_TRADES} trades, positive net return, PF > 1, max drawdown better than -25%). Do not call this a successful strategy.\n")
            else:
                f.write(candidates.sort_values(["profit_factor","net_return_pct"], ascending=False).head(30).to_markdown(index=False))
            f.write("\n\n## Data errors\n\n")
            for sym, err in errors[:100]: f.write(f"- {sym}: {err}\n")
    print(f"Done. Usable symbols={len(frames)}; result rows={len(rows)}; errors={len(errors)}")

if __name__ == "__main__":
    main()

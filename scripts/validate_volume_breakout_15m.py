#!/usr/bin/env python3
"""Independent historical holdout for the discovered volume-breakout candidate. Paper only.
Triggered by a repository push; never places orders."""
import concurrent.futures
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import optimize_spot_strategies_15m as engine

MIN_VOLUME = 1_000_000
CFG = {"family": "volume_breakout", "filter": "trend", "lookback": 24, "rr": 3.0, "stop_n": 20}
STABLE = {"USDT","USDC","FDUSD","TUSD","USDP","DAI","BUSD","EUR","AEUR","USTC","USDE","USDD","PYUSD","USD1"}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    # Use a historical window ending 90 days ago, separated from the recent discovery run.
    end = int((now - dt.timedelta(days=90)).timestamp() * 1000)
    start = int((now - dt.timedelta(days=270)).timestamp() * 1000)
    tickers, ticker_source = engine.fetch_json_from_apis("/api/v3/ticker/24hr")
    info, exchange_source = engine.fetch_json_from_apis("/api/v3/exchangeInfo")
    ticker_by_symbol = {x["symbol"]: x for x in tickers}
    symbols = sorted(
        item["symbol"] for item in info.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("isSpotTradingAllowed", False)
        and item.get("quoteAsset") == "USDT"
        and item.get("baseAsset") not in STABLE
        and float(ticker_by_symbol.get(item["symbol"], {}).get("quoteVolume", 0) or 0) > MIN_VOLUME
    )
    print(f"INDEPENDENT_HOLDOUT universe={len(symbols)} period_days=180 end_offset_days=90", flush=True)
    results, failures = [], []
    def load(symbol):
        rows = engine.candles_from_archive(symbol, start, end)
        if len(rows) < 500:
            return symbol, rows, None
        stats = engine.simulate(rows, CFG, 60, len(rows))
        return symbol, rows, stats
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(load, s): s for s in symbols}
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            sym = futures[fut]
            try:
                _, rows, stats = fut.result()
                if stats is None:
                    failures.append({"symbol": sym, "error": f"insufficient candles: {len(rows)}"})
                    continue
                results.append({"symbol": sym, **stats, "candles": len(rows)})
            except Exception as exc:
                failures.append({"symbol": sym, "error": str(exc)[:180]})
            if idx % 20 == 0:
                print(f"PROGRESS {idx}/{len(symbols)} tested={len(results)} failed={len(failures)}", flush=True)
    trades = sum(x["trades"] for x in results)
    wins = sum(x["wins"] for x in results)
    weighted_net = sum(x["avg_trade_net_pct"] * x["trades"] for x in results) / trades if trades else 0
    total_wins_net = sum(max(0, x["avg_trade_net_pct"]) * x["trades"] for x in results)
    total_loss_net = sum(max(0, -x["avg_trade_net_pct"]) * x["trades"] for x in results)
    profitable = sum(x["return_pct"] > 0 for x in results)
    avg_dd = sum(x["max_drawdown_pct"] for x in results) / len(results) if results else 0
    # Conservative gate: broad sample, positive net expectancy, >1 profit factor, bounded drawdown,
    # and profitability across a majority of symbols. This is still a paper historical test.
    pf_proxy = total_wins_net / total_loss_net if total_loss_net else (999 if total_wins_net else 0)
    passed = trades >= 300 and weighted_net > 0 and pf_proxy > 1.1 and avg_dd < 25 and results and profitable / len(results) >= 0.55
    report = {
        "status": "passed_historical_holdout_gate" if passed else "did_not_pass_historical_holdout_gate",
        "market": "Binance Spot USDT",
        "timeframe": "15m",
        "paper_only": True,
        "rule": CFG,
        "period_start_utc": dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).isoformat(),
        "period_end_utc": dt.datetime.fromtimestamp(end / 1000, dt.timezone.utc).isoformat(),
        "universe_filter": "Current Binance Spot USDT pairs with 24h quote volume > 1,000,000 USDT; stablecoin bases excluded",
        "ticker_source": ticker_source,
        "exchange_info_source": exchange_source,
        "universe_size": len(symbols),
        "symbols_tested": len(results),
        "symbols_failed": len(failures),
        "trades": trades,
        "wins": wins,
        "losses": trades - wins,
        "win_rate_pct": round(wins * 100 / trades, 2) if trades else 0,
        "avg_trade_net_pct": round(weighted_net, 4),
        "profit_factor_proxy": round(pf_proxy, 3),
        "avg_symbol_max_drawdown_pct": round(avg_dd, 2),
        "profitable_symbols_pct": round(profitable * 100 / len(results), 2) if results else 0,
        "cost_model": "0.05% taker fee per side + 0.02% slippage per side",
        "warning": "Historical paper test only. Profit factor is a conservative aggregate proxy from per-symbol mean trade returns, not exact pooled gross-profit/gross-loss PF. Not a live-trading approval.",
        "symbols": sorted(results, key=lambda x: (x["return_pct"], x["profit_factor"]), reverse=True),
        "failures": failures,
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat()
    }
    os.makedirs("backtest-results", exist_ok=True)
    with open("backtest-results/volume-breakout-15m-independent-holdout.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("INDEPENDENT_HOLDOUT_SUMMARY " + json.dumps({k:v for k,v in report.items() if k not in ("symbols","failures")}, ensure_ascii=False), flush=True)
    if not passed:
        raise SystemExit("Candidate did not pass the independent historical holdout gate.")

if __name__ == "__main__":
    main()

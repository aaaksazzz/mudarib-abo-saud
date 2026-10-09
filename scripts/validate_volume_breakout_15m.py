#!/usr/bin/env python3
"""Independent historical holdout for a shortlist of discovered Binance Spot strategies. Paper only."""
import concurrent.futures
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import optimize_spot_strategies_15m as engine

MIN_VOLUME = 1_000_000
CANDIDATES = [
    {"family": "volume_breakout", "filter": "trend", "lookback": 24, "rr": 3.0, "stop_n": 20},
    {"family": "volume_breakout", "filter": "trend", "lookback": 32, "rr": 2.5, "stop_n": 20},
    {"family": "breakout", "filter": "none", "lookback": 64, "rr": 2.5, "stop_n": 20},
    {"family": "momentum", "filter": "trend", "lookback": 12, "rr": 3.0, "stop_n": 20},
    {"family": "volume_breakout", "filter": "none", "lookback": 32, "rr": 3.0, "stop_n": 20},
]
STABLE = {"USDT","USDC","FDUSD","TUSD","USDP","DAI","BUSD","EUR","AEUR","USTC","USDE","USDD","PYUSD","USD1"}

def summarize(cfg, per_symbol):
    usable = [x for x in per_symbol if x["stats"]["trades"] > 0]
    trades = sum(x["stats"]["trades"] for x in usable)
    wins = sum(x["stats"]["wins"] for x in usable)
    weighted_net = sum(x["stats"]["avg_trade_net_pct"] * x["stats"]["trades"] for x in usable) / trades if trades else 0
    avg_pf = sum(x["stats"]["profit_factor"] for x in usable) / len(usable) if usable else 0
    avg_dd = sum(x["stats"]["max_drawdown_pct"] for x in usable) / len(usable) if usable else 0
    profitable = sum(x["stats"]["return_pct"] > 0 for x in usable)
    passed = trades >= 300 and weighted_net > 0 and avg_pf > 1.1 and avg_dd < 25 and usable and profitable / len(usable) >= 0.55
    return {
        "rule": cfg,
        "status": "passed_historical_holdout_gate" if passed else "did_not_pass_historical_holdout_gate",
        "symbols_with_trades": len(usable),
        "trades": trades,
        "wins": wins,
        "losses": trades - wins,
        "win_rate_pct": round(wins * 100 / trades, 2) if trades else 0,
        "avg_trade_net_pct": round(weighted_net, 4),
        "mean_symbol_profit_factor": round(avg_pf, 3),
        "mean_symbol_max_drawdown_pct": round(avg_dd, 2),
        "profitable_symbols_pct": round(profitable * 100 / len(usable), 2) if usable else 0,
        "symbols": sorted([{"symbol": x["symbol"], **x["stats"], "candles": x["candles"]} for x in usable],
                          key=lambda x: (x["return_pct"], x["profit_factor"]), reverse=True),
    }

def main():
    now = dt.datetime.now(dt.timezone.utc)
    print("DATA_SOURCE_POLICY official Binance market-data host first, then regional API mirrors; historical candles prefer Binance public archive", flush=True)
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
    print(f"INDEPENDENT_HOLDOUT candidates={len(CANDIDATES)} universe={len(symbols)} period_days=180 end_offset_days=90", flush=True)
    loaded, failures = [], []
    def load(symbol):
        rows = engine.candles_from_archive(symbol, start, end)
        if len(rows) < 500:
            return symbol, rows, None
        all_stats = [engine.simulate(rows, cfg, 60, len(rows)) for cfg in CANDIDATES]
        return symbol, rows, all_stats
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(load, s): s for s in symbols}
        for idx, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            sym = futures[fut]
            try:
                _, rows, stats = fut.result()
                if stats is None:
                    failures.append({"symbol": sym, "error": f"insufficient candles: {len(rows)}"})
                    continue
                loaded.append({"symbol": sym, "candles": len(rows), "all_stats": stats})
            except Exception as exc:
                failures.append({"symbol": sym, "error": str(exc)[:180]})
            if idx % 20 == 0:
                print(f"PROGRESS {idx}/{len(symbols)} symbols_loaded={len(loaded)} failed={len(failures)}", flush=True)
    candidate_reports = []
    for i, cfg in enumerate(CANDIDATES):
        per_symbol = [{"symbol": item["symbol"], "candles": item["candles"], "stats": item["all_stats"][i]} for item in loaded]
        candidate_reports.append(summarize(cfg, per_symbol))
    candidate_reports.sort(key=lambda x: (
        x["status"] == "passed_historical_holdout_gate",
        x["avg_trade_net_pct"],
        x["profitable_symbols_pct"],
        -x["mean_symbol_max_drawdown_pct"]
    ), reverse=True)
    for report in candidate_reports:
        report.pop("symbols", None)
        print("CANDIDATE_HOLDOUT " + json.dumps(report, ensure_ascii=False), flush=True)
    best = candidate_reports[0] if candidate_reports else None
    report = {
        "status": "passed_historical_holdout_gate" if any(x["status"] == "passed_historical_holdout_gate" for x in candidate_reports) else "no_candidate_passed_historical_holdout_gate",
        "market": "Binance Spot USDT",
        "timeframe": "15m",
        "paper_only": True,
        "period_start_utc": dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).isoformat(),
        "period_end_utc": dt.datetime.fromtimestamp(end / 1000, dt.timezone.utc).isoformat(),
        "universe_filter": "Current Binance Spot USDT pairs with 24h quote volume > 1,000,000 USDT; stablecoin bases excluded",
        "ticker_source": ticker_source,
        "exchange_info_source": exchange_source,
        "universe_size": len(symbols),
        "symbols_loaded": len(loaded),
        "symbols_failed": len(failures),
        "cost_model": "0.05% taker fee per side + 0.02% slippage per side",
        "gate": ">=300 trades, positive weighted net expectancy, mean per-symbol profit factor >1.1, mean per-symbol drawdown <25%, and >=55% profitable symbols",
        "candidate_results": candidate_reports,
        "best_candidate": best,
        "failures": failures,
        "warning": "Historical paper test only. Candidates were selected from a prior search; this holdout is a separate historical period but still does not prove future profitability or approve live trading.",
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat()
    }
    os.makedirs("backtest-results", exist_ok=True)
    with open("backtest-results/volume-breakout-15m-independent-holdout.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("INDEPENDENT_HOLDOUT_SUMMARY " + json.dumps({k:v for k,v in report.items() if k not in ("candidate_results","failures")}, ensure_ascii=False), flush=True)
    if not any(x["status"] == "passed_historical_holdout_gate" for x in candidate_reports):
        raise SystemExit("No candidate passed the independent historical holdout gate.")

if __name__ == "__main__":
    main()

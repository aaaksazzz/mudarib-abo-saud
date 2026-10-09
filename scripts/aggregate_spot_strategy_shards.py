#!/usr/bin/env python3
"""Aggregate each dedicated strategy family across its independent symbol shards."""
import datetime as dt
import glob
import json
import os

FAMILIES=("breakout","sweep","momentum","ema_trend","rsi_revert","ema_pullback","donchian_reversal","atr_breakout","volume_breakout","macd_cross")
paths=sorted(glob.glob("backtest-results/shards/**/spot-strategy-search-15m-*-shard-*.json",recursive=True))
if not paths:
    raise SystemExit("No specialist shard reports found")
reports=[json.load(open(p,encoding="utf-8")) for p in paths]
per_family=int(os.getenv("SHARD_COUNT","3"))
expected=len(FAMILIES)*per_family
if len(reports)!=expected:
    raise SystemExit(f"Expected {expected} specialist reports ({len(FAMILIES)} families x {per_family} shards), found {len(reports)}")
combined=[]
for family in FAMILIES:
    group=[r for r in reports if r.get("strategy_family")==family]
    if len(group)!=per_family:
        raise SystemExit(f"Family {family}: expected {per_family} reports, found {len(group)}")
    indexes={r.get("shard",{}).get("index") for r in group}
    if indexes!=set(range(per_family)):
        raise SystemExit(f"Family {family}: incomplete shard indexes {sorted(str(x) for x in indexes)}")
    maps=[{json.dumps(x.get("rule",{}),sort_keys=True):x for x in r.get("top_candidates",[])} for r in group]
    common=set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    for key in common:
        parts=[m[key] for m in maps]
        vals=[p.get("validation",{}) for p in parts]
        n=sum(int(v.get("trades",0)) for v in vals)
        wins=sum(int(v.get("wins",0)) for v in vals)
        weights=[int(v.get("symbols_with_trades",0)) for v in vals]
        denom=sum(weights)
        def weighted(field):
            return round(sum(float(v.get(field,0) or 0)*w for v,w in zip(vals,weights))/denom,4) if denom else 0
        validation={
          "trades":n,"wins":wins,"losses":n-wins,
          "win_rate_pct":round(100*wins/n,2) if n else 0,
          "avg_trade_net_pct":round(sum(float(v.get("avg_trade_net_pct",0))*int(v.get("trades",0)) for v in vals)/n,4) if n else 0,
          "mean_symbol_profit_factor":weighted("mean_symbol_profit_factor"),
          "mean_symbol_drawdown_pct":weighted("mean_symbol_drawdown_pct"),
          "profitable_symbols_pct":weighted("profitable_symbols_pct"),
          "mean_symbol_return_pct":weighted("mean_symbol_return_pct"),
          "symbols_with_trades":denom,"shards_passed":len(parts),"strategy_family":family
        }
        passed=n>=100 and validation["avg_trade_net_pct"]>0 and validation["mean_symbol_profit_factor"]>1.05 and validation["mean_symbol_drawdown_pct"]<35 and validation["profitable_symbols_pct"]>=50
        combined.append({"rule":parts[0]["rule"],"validation":validation,"passed_validation":passed})
combined.sort(key=lambda x:(x["passed_validation"],x["validation"]["avg_trade_net_pct"],x["validation"]["mean_symbol_profit_factor"],x["validation"]["profitable_symbols_pct"]),reverse=True)
winners=[x for x in combined if x["passed_validation"]]
out={
 "market":"Binance Spot USDT pairs","timeframe":"15m","paper_only":True,
 "specialist_families":list(FAMILIES),"workers_expected":expected,"workers_received":len(reports),
 "symbols_universe":max((r.get("universe_symbols",0) for r in reports),default=0),
 "symbols_tested_total":sum(r.get("symbols_tested",0) for r in reports),
 "candles_loaded_total":sum(r.get("candles_loaded",0) for r in reports),
 "provider_endpoints":[r.get("provider_endpoints",{}) for r in reports],
 "completed_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "best_candidate":{"status":"candidate_for_further_validation","rule":winners[0]["rule"],"validation":winners[0]["validation"]} if winners else {"status":"no_validated_profitable_candidate","message":"No strategy family passed pooled out-of-sample validation thresholds."},
 "top_candidates":combined[:30],
 "paper_only_warning":"Research backtest only; not a guarantee of future profitability. Forward-test before live trading."
}
os.makedirs("backtest-results",exist_ok=True)
with open("backtest-results/spot-strategy-search-15m.json","w",encoding="utf-8") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print("SPOT_SPECIALIST_AGGREGATE",json.dumps({k:v for k,v in out.items() if k!="top_candidates"},ensure_ascii=False))

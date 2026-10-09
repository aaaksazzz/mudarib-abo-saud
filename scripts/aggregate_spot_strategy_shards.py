#!/usr/bin/env python3
"""Pool independent validation results across shards; never promote a rule on training results alone."""
import datetime as dt
import glob
import json
import os

paths=sorted(glob.glob("backtest-results/shards/**/spot-strategy-search-15m-shard-*.json",recursive=True))
if not paths:
    raise SystemExit("No shard reports found")
reports=[json.load(open(p,encoding="utf-8")) for p in paths]
expected=int(os.getenv("SHARD_COUNT","4"))
if len(reports)!=expected:
    raise SystemExit(f"Expected {expected} shard reports, found {len(reports)}")
indexes={r.get("shard",{}).get("index") for r in reports}
if indexes != set(range(expected)):
    raise SystemExit(f"Shard reports incomplete: indexes={sorted(str(x) for x in indexes)}")
maps=[]
for report in reports:
    maps.append({json.dumps(x.get("rule",{}),sort_keys=True):x for x in report.get("top_candidates",[])})
common=set(maps[0])
for m in maps[1:]:
    common &= set(m)
combined=[]
for key in common:
    parts=[m[key] for m in maps]
    # Combine validation metrics first: a rule may narrowly miss a per-shard threshold but pass on the full independent validation sample.
    vals=[p.get("validation",{}) for p in parts]
    n=sum(int(v.get("trades",0)) for v in vals)
    wins=sum(int(v.get("wins",0)) for v in vals)
    symbol_weights=[int(v.get("symbols_with_trades",0)) for v in vals]
    denom=sum(symbol_weights)
    def weighted(field):
        return round(sum(float(v.get(field,0) or 0)*w for v,w in zip(vals,symbol_weights))/denom,4) if denom else 0
    validation={
      "trades":n,"wins":wins,"losses":n-wins,
      "win_rate_pct":round(100*wins/n,2) if n else 0,
      "avg_trade_net_pct":round(sum(float(v.get("avg_trade_net_pct",0))*int(v.get("trades",0)) for v in vals)/n,4) if n else 0,
      "mean_symbol_profit_factor":weighted("mean_symbol_profit_factor"),
      "mean_symbol_drawdown_pct":weighted("mean_symbol_drawdown_pct"),
      "profitable_symbols_pct":weighted("profitable_symbols_pct"),
      "mean_symbol_return_pct":weighted("mean_symbol_return_pct"),
      "symbols_with_trades":denom,
      "shards_passed":len(parts)
    }
    passed=n>=100 and validation["avg_trade_net_pct"]>0 and validation["mean_symbol_profit_factor"]>1.05 and validation["mean_symbol_drawdown_pct"]<35 and validation["profitable_symbols_pct"]>=50
    combined.append({"rule":parts[0]["rule"],"validation":validation,"passed_validation":passed})
combined.sort(key=lambda x:(x["passed_validation"],x["validation"]["avg_trade_net_pct"],x["validation"]["mean_symbol_profit_factor"],x["validation"]["profitable_symbols_pct"]),reverse=True)
winners=[x for x in combined if x["passed_validation"]]
out={
 "market":"Binance Spot USDT pairs","timeframe":"15m","paper_only":True,
 "shards_expected":expected,"shards_received":len(reports),
 "symbols_universe":max((r.get("universe_symbols",0) for r in reports),default=0),
 "symbols_tested_total":sum(r.get("symbols_tested",0) for r in reports),
 "candles_loaded_total":sum(r.get("candles_loaded",0) for r in reports),
 "provider_endpoints":[r.get("provider_endpoints",{}) for r in reports],
 "completed_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
 "best_candidate":{"status":"candidate_for_further_validation","rule":winners[0]["rule"],"validation":winners[0]["validation"]} if winners else {"status":"no_validated_profitable_candidate","message":"No common rule passed pooled out-of-sample validation thresholds across all shards."},
 "top_candidates":combined[:20],
 "paper_only_warning":"Research backtest only; not a guarantee of future profitability. Forward-test before live trading."
}
os.makedirs("backtest-results",exist_ok=True)
with open("backtest-results/spot-strategy-search-15m.json","w",encoding="utf-8") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print("SPOT_SHARD_AGGREGATE",json.dumps({k:v for k,v in out.items() if k!="top_candidates"},ensure_ascii=False))

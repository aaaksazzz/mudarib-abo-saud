#!/usr/bin/env python3
"""Backtest the user's contrarian SMA20 regime rule on BTCUSDT USD-M futures 1m.
Below SMA20 => LONG/BUY; above SMA20 => SHORT/SELL. Change positions only when
the close crosses the SMA regime, execute at the next candle open, include fees/slippage.
Paper backtest only; no live orders."""
import datetime as dt, json, os
from backtest_btcusdt_futures_1m_reversed_180d import load_data, BAR_MS, FEE_SIDE, SLIPPAGE_SIDE, DAYS

SYMBOL="BTCUSDT"
INTERVAL="1m"
COST_SIDE=FEE_SIDE+SLIPPAGE_SIDE  # 0.07% each executed side
ROUND_TRIP_COST=2*COST_SIDE

def make_trades(rows):
    closes=[r[4] for r in rows]
    sma=[None]*len(rows)
    for i in range(19,len(rows)):
        sma[i]=sum(closes[i-19:i+1])/20
    trades=[]
    position=None
    entry_price=None
    entry_i=None
    for i in range(19,len(rows)-1):
        if sma[i] is None or sma[i-1] is None: continue
        desired="long" if closes[i] < sma[i] else "short" if closes[i] > sma[i] else position
        if desired is None: continue
        if position is None:
            position=desired
            entry_i=i+1
            entry_price=rows[entry_i][1]
            continue
        if desired != position:
            exit_i=i+1
            exit_price=rows[exit_i][1]
            gross=(exit_price-entry_price)/entry_price if position=="long" else (entry_price-exit_price)/entry_price
            net=gross-ROUND_TRIP_COST
            trades.append({"signal_i":entry_i-1,"entry_time":rows[entry_i][0],"exit_time":rows[exit_i][0],
                           "direction":position,"entry":entry_price,"exit":exit_price,
                           "gross_pct":gross*100,"net_pct":net*100})
            position=desired
            entry_i=exit_i
            entry_price=exit_price
    if position is not None and entry_i is not None and entry_i < len(rows)-1:
        exit_i=len(rows)-1
        exit_price=rows[exit_i][4]
        gross=(exit_price-entry_price)/entry_price if position=="long" else (entry_price-exit_price)/entry_price
        net=gross-ROUND_TRIP_COST
        trades.append({"signal_i":entry_i-1,"entry_time":rows[entry_i][0],"exit_time":rows[exit_i][0],
                       "direction":position,"entry":entry_price,"exit":exit_price,
                       "gross_pct":gross*100,"net_pct":net*100})
    return trades

def summarize(trades, lo, hi):
    ts=[t for t in trades if lo <= t["signal_i"] < hi]
    equity=peak=1.0
    dd=0.0
    for t in ts:
        equity *= max(0.0,1+t["net_pct"]/100)
        peak=max(peak,equity)
        if peak>0: dd=max(dd,(peak-equity)/peak)
    wins=sum(t["net_pct"]>0 for t in ts)
    return {"trades":len(ts),"wins":wins,"losses":len(ts)-wins,
            "win_rate_pct":round(100*wins/len(ts),2) if ts else 0,
            "net_compounded_return_pct":round((equity-1)*100,2),
            "max_drawdown_pct":round(dd*100,2),
            "avg_net_trade_pct":round(sum(t["net_pct"] for t in ts)/len(ts),4) if ts else 0,
            "long_trades":sum(t["direction"]=="long" for t in ts),
            "short_trades":sum(t["direction"]=="short" for t in ts)}

def main():
    start_ms,end_ms,rows=load_data()
    expected=max(0,(end_ms-start_ms)//BAR_MS)
    if len(rows)<10000:
        raise RuntimeError(f"Insufficient data: {len(rows)} candles; expected about {expected}")
    gaps=sum(1 for a,b in zip(rows,rows[1:]) if b[0]-a[0]>BAR_MS)
    split=int(len(rows)*0.70)
    trades=make_trades(rows)
    report={
      "strategy":"SMA20 contrarian regime: close below SMA20=BUY/LONG; close above SMA20=SELL/SHORT; reverse at regime change.",
      "market":"Binance USD-M perpetual futures","symbol":SYMBOL,"timeframe":INTERVAL,
      "requested_period_days":DAYS,"candles_loaded":len(rows),"expected_candles_approx":expected,
      "coverage_pct":round(100*len(rows)/expected,2) if expected else 0,"missing_minute_gaps":gaps,
      "data_start_utc":dt.datetime.fromtimestamp(rows[0][0]/1000,dt.timezone.utc).isoformat(),
      "data_end_utc":dt.datetime.fromtimestamp(rows[-1][0]/1000,dt.timezone.utc).isoformat(),
      "split":"first 70% train / final 30% chronological holdout",
      "cost_assumptions":{"taker_fee_each_side_pct":FEE_SIDE*100,"slippage_each_side_pct":SLIPPAGE_SIDE*100,
                          "round_trip_trade_cost_pct":ROUND_TRIP_COST*100},
      "execution":"Signals from completed candle close; position change at next candle open; no stop/target; close final position at final candle close; fees/slippage charged per entry and exit.",
      "results":{"all_period":summarize(trades,0,len(rows)),"train_70pct":summarize(trades,0,split),
                 "holdout_30pct":summarize(trades,split,len(rows))},
      "warning":"Backtest is not a guarantee. Leverage/funding/liquidation are not modeled; do not enable live orders from this report alone.",
      "completed_utc":dt.datetime.now(dt.timezone.utc).isoformat()
    }
    os.makedirs("backtest-results",exist_ok=True)
    path="backtest-results/btcusdt-futures-1m-sma20-contrarian-180d.json"
    with open(path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print("FINAL_SUMMARY",json.dumps(report,ensure_ascii=False),flush=True)

if __name__=="__main__": main()

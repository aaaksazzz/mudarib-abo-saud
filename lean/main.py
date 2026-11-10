from AlgorithmImports import *
from collections import deque


class SmartTradingProResearch(QCAlgorithm):
    """Single-symbol, signal-only LEAN research baseline. Never submits orders."""

    def Initialize(self):
        self.SetStartDate(2022, 1, 1)
        self.SetEndDate(2025, 12, 31)
        self.SetCash(100000)

        asset_class = self.GetParameter("asset_class") or "crypto"
        ticker = self.GetParameter("ticker") or "BTCUSDT"
        resolution_name = (self.GetParameter("resolution") or "hour").lower()
        resolution = {
            "minute": Resolution.Minute,
            "hour": Resolution.Hour,
            "daily": Resolution.Daily,
        }.get(resolution_name, Resolution.Hour)

        if asset_class == "crypto":
            self.symbol = self.AddCrypto(ticker, resolution, Market.Binance).Symbol
        elif asset_class == "equity":
            self.symbol = self.AddEquity(ticker, resolution).Symbol
        elif asset_class == "forex":
            self.symbol = self.AddForex(ticker, resolution, Market.Oanda).Symbol
        else:
            raise ValueError("asset_class must be crypto, equity, or forex")

        self.sma = self.SMA(self.symbol, 200, resolution)
        self.atr = self.ATR(self.symbol, 14, MovingAverageType.Simple, resolution)
        self.window = RollingWindow[TradeBar](3)
        self.last_signal_end = None
        self.SetWarmUp(220, resolution)
        self.Debug("SMART_TRADING_PRO_LEAN_RESEARCH_V1 | signal-only | no orders")

    def OnData(self, data):
        if self.IsWarmingUp or not self.sma.IsReady or not self.atr.IsReady:
            return
        if not data.Bars.ContainsKey(self.symbol):
            return

        bar = data.Bars[self.symbol]
        # LEAN data bars are completed bars at this callback's resolution.
        if self.last_signal_end == bar.EndTime:
            return
        self.last_signal_end = bar.EndTime
        self.window.Add(bar)
        if not self.window.IsReady:
            return

        entry = float(bar.Close)
        ma200 = float(self.sma.Current.Value)
        atr = float(self.atr.Current.Value)
        if entry <= 0 or atr <= 0:
            return

        previous = self.window[1]
        prior = self.window[2]
        bullish = bar.Close > bar.Open and previous.Close > previous.Open
        bearish = bar.Close < bar.Open and previous.Close < previous.Open
        side = None
        if entry > ma200 and bullish and bar.Close > previous.High:
            side = "BUY"
            stop = entry - 1.5 * atr
        elif entry < ma200 and bearish and bar.Close < previous.Low:
            side = "SELL"
            stop = entry + 1.5 * atr
        else:
            return

        risk = entry - stop if side == "BUY" else stop - entry
        if risk <= 0 or risk / entry > 0.08:
            return

        sign = 1 if side == "BUY" else -1
        targets = [entry + sign * risk * multiple for multiple in (1, 2, 3)]
        payload = (
            f"STP_LEAN_SIGNAL | {self.symbol.Value} | {side} | "
            f"entry={entry:.8g} | stop={stop:.8g} | "
            f"tp1={targets[0]:.8g} | tp2={targets[1]:.8g} | "
            f"tp3={targets[2]:.8g} | risk_pct={risk / entry * 100:.3f} | "
            f"time={bar.EndTime.isoformat()}"
        )
        self.Debug(payload)
        self.Plot("Research", "Close", entry)
        self.Plot("Research", "SMA200", ma200)

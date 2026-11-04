"""Signal service - orchestrates indicator calculation across all indicators."""

from typing import Any

import pandas as pd

from dive_engine.engine.indicators.base import BaseIndicator, IndicatorResult, Signal
from dive_engine.engine.indicators.rsi import RSIIndicator
from dive_engine.engine.indicators.macd import MACDIndicator
from dive_engine.engine.indicators.bollinger import BollingerBandsIndicator
from dive_engine.engine.indicators.sma_cross import SMACrossIndicator
from dive_engine.engine.indicators.ema_cross import EMACrossIndicator
from dive_engine.engine.indicators.stochastic import StochasticIndicator
from dive_engine.engine.indicators.adx_di import ADXDIIndicator
from dive_engine.engine.indicators.cci import CCIIndicator
from dive_engine.engine.indicators.williams_r import WilliamsRIndicator
from dive_engine.engine.indicators.roc import ROCIndicator
from dive_engine.engine.indicators.mfi import MFIIndicator
from dive_engine.engine.indicators.atr_filter import ATRFilterIndicator
from dive_engine.engine.indicators.ichimoku import IchimokuIndicator
from dive_engine.engine.indicators.psar import PSARIndicator
from dive_engine.engine.indicators.obv import OBVIndicator
from dive_engine.engine.indicators.supertrend import SupertrendIndicator
from dive_engine.engine.indicators.awesome_oscillator import AwesomeOscillatorIndicator
from dive_engine.engine.indicators.cmf import CMFIndicator
from dive_engine.engine.indicators.squeeze import TTMSqueezeIndicator
from dive_engine.engine.indicators.choppiness import ChoppinessIndexIndicator
from dive_engine.engine.indicators.vwap import VWAPIndicator
from dive_engine.engine.indicators.vortex import VortexIndicator
# --- New indicators (strategy-lab R&D fleet, 2026-07-19) ---
from dive_engine.engine.indicators.keltner_breakout import KeltnerBreakoutIndicator
from dive_engine.engine.indicators.donchian_breakout import DonchianBreakoutIndicator
from dive_engine.engine.indicators.chaikin_oscillator import ChaikinOscillatorIndicator
from dive_engine.engine.indicators.elder_ray import ElderRayIndicator
from dive_engine.engine.indicators.klinger_oscillator import KlingerOscillatorIndicator
from dive_engine.engine.indicators.trix import TRIXIndicator
from dive_engine.engine.indicators.coppock_curve import CoppockCurveIndicator
from dive_engine.engine.indicators.kst import KSTIndicator
from dive_engine.engine.indicators.dpo import DPOIndicator
from dive_engine.engine.indicators.fisher_transform import FisherTransformIndicator
from dive_engine.engine.indicators.connors_rsi import ConnorsRSIIndicator
from dive_engine.engine.indicators.stoch_rsi import StochRSIIndicator
from dive_engine.engine.indicators.ultimate_oscillator import UltimateOscillatorIndicator
from dive_engine.engine.indicators.aroon_oscillator import AroonOscillatorIndicator
from dive_engine.engine.indicators.schaff_trend_cycle import SchaffTrendCycleIndicator
from dive_engine.engine.indicators.wavetrend import WaveTrendIndicator
from dive_engine.engine.indicators.relative_vigor_index import RelativeVigorIndexIndicator
from dive_engine.engine.indicators.balance_of_power import BalanceOfPowerIndicator
from dive_engine.engine.indicators.accum_dist_line import AccumDistLineIndicator
from dive_engine.engine.indicators.mass_index import MassIndexIndicator
# --- New indicators batch 2 (strategy-lab, 2026-07-19) ---
from dive_engine.engine.indicators.cmo import CMOIndicator
from dive_engine.engine.indicators.tsi import TSIIndicator
from dive_engine.engine.indicators.vwma_cross import VWMACrossIndicator
from dive_engine.engine.indicators.qstick import QstickIndicator
from dive_engine.engine.indicators.force_index import ForceIndexIndicator
from dive_engine.engine.indicators.bollinger_percent_b import BollingerPercentBIndicator
from dive_engine.engine.indicators.zscore_reversion import ZScoreReversionIndicator
from dive_engine.engine.indicators.linreg_slope import LinRegSlopeIndicator
from dive_engine.engine.indicators.atr_percentile import ATRPercentileIndicator
from dive_engine.engine.indicators.hist_vol_percentile import HistVolPercentileIndicator
from dive_engine.engine.indicators.hurst import HurstRegimeIndicator
from dive_engine.engine.indicators.range_expansion import RangeExpansionIndicator
from dive_engine.engine.indicators.kalman_trend import KalmanTrendIndicator
from dive_engine.engine.indicators.half_life_reversion import HalfLifeReversionIndicator
from dive_engine.engine.indicators.rolling_sharpe import RollingSharpeIndicator
# --- Price-action pattern library (2026-09-12) ---
from dive_engine.engine.indicators.engulfing import EngulfingIndicator
from dive_engine.engine.indicators.liquidity_sweep import LiquiditySweepIndicator
from dive_engine.engine.indicators.pivot_structure import PivotStructureIndicator
from dive_engine.engine.utils.logger import get_logger

logger = get_logger("services.signal_service")


class SignalService:
    """Runs all indicators and collects results."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.indicators: list[BaseIndicator] = self._build_indicators()

    def _build_indicators(self) -> list[BaseIndicator]:
        """Instantiate all indicator objects."""
        indicator_classes = [
            RSIIndicator,
            MACDIndicator,
            BollingerBandsIndicator,
            SMACrossIndicator,
            EMACrossIndicator,
            StochasticIndicator,
            ADXDIIndicator,
            CCIIndicator,
            WilliamsRIndicator,
            ROCIndicator,
            MFIIndicator,
            ATRFilterIndicator,
            IchimokuIndicator,
            PSARIndicator,
            OBVIndicator,
            SupertrendIndicator,
            AwesomeOscillatorIndicator,
            CMFIndicator,
            TTMSqueezeIndicator,
            ChoppinessIndexIndicator,
            VWAPIndicator,
            VortexIndicator,
            # --- New indicators (strategy-lab R&D fleet, 2026-07-19) ---
            KeltnerBreakoutIndicator,
            DonchianBreakoutIndicator,
            ChaikinOscillatorIndicator,
            ElderRayIndicator,
            KlingerOscillatorIndicator,
            TRIXIndicator,
            CoppockCurveIndicator,
            KSTIndicator,
            DPOIndicator,
            FisherTransformIndicator,
            ConnorsRSIIndicator,
            StochRSIIndicator,
            UltimateOscillatorIndicator,
            AroonOscillatorIndicator,
            SchaffTrendCycleIndicator,
            WaveTrendIndicator,
            RelativeVigorIndexIndicator,
            BalanceOfPowerIndicator,
            AccumDistLineIndicator,
            MassIndexIndicator,
            # --- New indicators batch 2 (strategy-lab, 2026-07-19) ---
            CMOIndicator,
            TSIIndicator,
            VWMACrossIndicator,
            QstickIndicator,
            ForceIndexIndicator,
            BollingerPercentBIndicator,
            ZScoreReversionIndicator,
            LinRegSlopeIndicator,
            ATRPercentileIndicator,
            HistVolPercentileIndicator,
            HurstRegimeIndicator,
            RangeExpansionIndicator,
            KalmanTrendIndicator,
            HalfLifeReversionIndicator,
            RollingSharpeIndicator,
            # --- Price-action pattern library (2026-09-12) ---
            EngulfingIndicator,
            LiquiditySweepIndicator,
            PivotStructureIndicator,
        ]
        return [cls(self.config) for cls in indicator_classes]

    def calculate_all(self, df: pd.DataFrame) -> list[IndicatorResult]:
        """Calculate all indicators on the given OHLCV DataFrame.

        Returns list of IndicatorResult objects. Failed indicators return NEUTRAL.
        """
        results: list[IndicatorResult] = []

        for indicator in self.indicators:
            try:
                result = indicator.calculate(df)
                results.append(result)
                logger.debug(
                    f"  {indicator.name}: {result.signal.value} (score={result.score}) - {result.reason}"
                )
            except Exception as e:
                logger.error(f"Indicator {indicator.name} failed: {e}")
                fallback = IndicatorResult(
                    name=indicator.name,
                    signal=Signal.NEUTRAL,
                    score=0,
                    reason=f"Calculation error: {str(e)[:100]}",
                )
                results.append(fallback)

        active = sum(1 for r in results if r.signal.value != "NEUTRAL")
        logger.info(f"Signals calculated: {len(results)} total, {active} active (non-neutral)")

        return results

    def get_indicator_names(self) -> list[str]:
        """Return list of all indicator names."""
        return [ind.name for ind in self.indicators]

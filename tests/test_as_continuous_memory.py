import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ENABLE_AUTO_SCAN"] = "false"

from app import (
    app, db, Trade, PaperExperience,
    record_paper_experience, run_as_daily_learning,
    market_scan_timeframes, frame_coverage_status,
)


class ASContinuousMemoryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def make_trade(self, status="tp3_hit", trade_id=1):
        trade = Trade(
            id=trade_id, market="futures", symbol="BTCUSDT", side="BUY",
            entry=100.0, stop=99.0, tp1=101.0, tp2=102.0, tp3=103.0,
            score=80.0, timeframe="15m",
            reason="STP PRICE ACTION QUANT V2: test",
            status=status, created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        db.session.add(trade)
        db.session.commit()
        return trade

    def test_full_tp3_is_recorded_once_at_actual_reward_risk(self):
        trade = self.make_trade("tp3_hit")
        self.assertTrue(record_paper_experience(trade))
        db.session.commit()
        self.assertFalse(record_paper_experience(trade))
        db.session.commit()
        row = PaperExperience.query.filter_by(trade_id=trade.id).one()
        self.assertEqual(row.gross_r, 3.0)
        self.assertEqual(row.outcome, "win")

    def test_full_stop_is_minus_one_r(self):
        trade = self.make_trade("stopped")
        self.assertTrue(record_paper_experience(trade))
        db.session.commit()
        row = PaperExperience.query.filter_by(trade_id=trade.id).one()
        self.assertEqual(row.gross_r, -1.0)
        self.assertEqual(row.outcome, "loss")

    def test_partial_stop_and_expired_trade_are_not_scored(self):
        partial = self.make_trade("stopped_after_tp1", 1)
        expired = self.make_trade("expired", 2)
        self.assertFalse(record_paper_experience(partial))
        self.assertFalse(record_paper_experience(expired))
        db.session.commit()
        self.assertEqual(PaperExperience.query.count(), 0)

    def test_v4_experience_is_attributed_to_the_active_engine(self):
        trade = self.make_trade("tp3_hit")
        trade.reason = "STP PRICE ACTION QUANT V2: test | engine=AS-SIGNAL-EXTRACTION-V4-20261118-ADAPTIVE"
        self.assertTrue(record_paper_experience(trade))
        db.session.commit()
        row = PaperExperience.query.filter_by(trade_id=trade.id).one()
        self.assertEqual(row.strategy_id, "as_practical_signal_extraction_v4")

    def test_every_market_has_all_six_independent_timeframes(self):
        markets = ("spot", "futures", "alpha", "us-stocks", "us-contracts", "saudi", "forex")
        frames = ("15m", "1h", "4h", "1d", "1w", "1M")
        for market in markets:
            self.assertEqual(tuple(market_scan_timeframes(market)), frames)

    def test_history_limited_frame_is_not_treated_as_provider_outage(self):
        status, required = frame_coverage_status(
            "alpha", "1w",
            {"completed": 0, "failure_reasons": {"insufficient_history": 12}},
            12,
        )
        self.assertEqual(status, "history_limited")
        self.assertEqual(required, 10)
        outage, _ = frame_coverage_status(
            "alpha", "1w",
            {"completed": 0, "failure_reasons": {"provider_timeout": 12}},
            12,
        )
        self.assertEqual(outage, "incomplete")

    def test_daily_report_uses_database_and_does_not_change_strategy(self):
        win_trade = self.make_trade("tp3_hit")
        record_paper_experience(win_trade)
        trade = self.make_trade("stopped", 2)
        record_paper_experience(trade)
        db.session.commit()
        report = run_as_daily_learning()
        self.assertEqual(report["cycle_interval"], "daily")
        self.assertEqual(report["total_resolved_experiences"], 2)
        self.assertFalse(report["production_strategy_modified"])
        self.assertFalse(report["live_order_execution"])
        self.assertEqual(report["market_timeframe_pairs"], 42)
        self.assertEqual(len(report["market_timeframe_coverage"]), 42)
        self.assertEqual(len(report["markets"]), 7)
        self.assertEqual(len(report["timeframes"]), 6)


if __name__ == "__main__":
    unittest.main()

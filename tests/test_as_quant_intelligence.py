import unittest
from as_quant_intelligence import (
    FINGERPRINT, METHOD_CATALOG, analyze_candidates, classify_regime,
    _parse,
)

def sample_rows(n=100, drift=0.25):
    rows=[]
    price=100.0
    for i in range(n):
        op=price
        price += drift + (0.25 if i%3 else -0.1)
        hi=max(op,price)+0.3
        lo=min(op,price)-0.3
        rows.append([i,op,hi,lo,price,100+(i%5)*5])
    rows.append([n,price,price+0.2,price-0.2,price,100])
    return rows

class ASQuantIntelligenceTests(unittest.TestCase):
    def test_fingerprint_and_catalog_expose_data_gaps(self):
        self.assertTrue(FINGERPRINT.startswith("AS-QUANT"))
        self.assertEqual(METHOD_CATALOG["order_flow"]["status"], "data_feed_required")
        self.assertEqual(METHOD_CATALOG["options_greeks"]["status"], "data_feed_required")

    def test_incomplete_final_bar_is_ignored(self):
        rows=sample_rows()
        self.assertEqual(len(_parse(rows)), len(rows)-1)

    def test_candidates_are_research_only_and_not_probabilities(self):
        result=analyze_candidates("futures","TEST",sample_rows(),"1h")
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"],"research_only_no_production_activation")
        for candidate in result["candidates"]:
            self.assertEqual(candidate["score_type"],"heuristic_not_probability")
            self.assertEqual(candidate["reward_risk"],3.0)

    def test_spot_does_not_emit_sell_candidates(self):
        result=analyze_candidates("spot","TEST",sample_rows(drift=-0.25),"1h")
        self.assertTrue(all(c["side"]=="BUY" for c in result["candidates"]))

    def test_insufficient_data_is_rejected(self):
        result=analyze_candidates("futures","TEST",sample_rows(30),"15m")
        self.assertFalse(result["ok"])

    def test_all_markets_and_timeframes_are_validated(self):
        self.assertFalse(analyze_candidates("unknown","X",sample_rows())["ok"])
        self.assertFalse(analyze_candidates("futures","X",sample_rows(),"5m")["ok"])

if __name__ == "__main__":
    unittest.main()

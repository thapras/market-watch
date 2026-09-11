"""python3 -m unittest fetch.test_v5  (the bitcoin tab: the feed parsers on trimmed responses, the indicator rules, the tally, the change entries)"""
import datetime as dt
import math
import unittest

from fetch import bitcoin as b
from fetch import sources


def daily(values, start="2020-01-01"):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


class Parsers(unittest.TestCase):
    def test_coinmetrics(self):
        j = {"data": [
            {"asset": "btc", "time": "2026-09-09T00:00:00.000000000Z", "PriceUSD": "80000.5", "CapMVRVCur": "1.5", "CapMrktCurUSD": "1.6e12", "IssTotUSD": "3.3e7",
             "IssTotNtv": "450", "FeeTotNtv": "3.1", "HashRate": "9e8", "AdrActCnt": "640000", "AdrBalCnt": "56000000", "SplyCur": "20082000", "FlowInExNtv": "20000", "FlowOutExNtv": "25000"},
            {"asset": "btc", "time": "2026-09-10", "PriceUSD": "76675.77", "CapMVRVCur": "1.44", "CapMrktCurUSD": "1.54e12", "IssTotUSD": "3.2e7", "FlowInExNtv": "", "FlowOutExNtv": None},
            {"asset": "btc", "time": "bad"},
        ]}
        cm = sources.parse_coinmetrics(j)
        self.assertEqual([d for d, _ in cm["price"]], ["2026-09-09", "2026-09-10"])
        self.assertAlmostEqual(cm["price"][-1][1], 76675.77)
        self.assertEqual(len(cm["flow_in"]), 1)                        # the blank and the None are dropped
        self.assertNotIn("bad", [d for d, _ in cm["price"]])
        with self.assertRaises(sources.SourceError):
            sources.parse_coinmetrics({"data": [{"time": "2026-09-10", "HashRate": "1"}]})

    def test_defillama_bybit_coingecko(self):
        rows = [{"date": str(1511913600 + 86400 * i), "totalCirculatingUSD": {"peggedUSD": 1e9 + i, "peggedEUR": 5.0}} for i in range(120)]
        st = sources.parse_defillama(rows + [{"date": "x"}, {"date": "1600000000"}])
        self.assertEqual(len(st), 120)
        self.assertEqual(st[0][0], "2017-11-29")
        with self.assertRaises(sources.SourceError):
            sources.parse_defillama(rows[:10])
        j = {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingRateTimestamp": "1789084800000"},
                                              {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingRateTimestamp": "1789056000000"},
                                              {"symbol": "BTCUSDT", "fundingRate": "-0.0003", "fundingRateTimestamp": "1789027200000"}, {"bad": 1}]}}
        periods = sources.parse_bybit_funding(j)
        self.assertEqual(len(periods), 3)
        day = sources.funding_daily(periods)
        self.assertEqual(len(day), 2)                                    # two periods fall on 10 Sep UTC, one on 11 Sep
        self.assertAlmostEqual(day[0][1], (0.0002 - 0.0003) / 2 * 3 * 365 * 100)
        self.assertAlmostEqual(day[-1][1], 0.0001 * 3 * 365 * 100)
        okx = sources.parse_okx_funding({"code": "0", "data": [{"fundingRate": "0.0001", "realizedRate": "0.00012", "fundingTime": "1789142400000"}, {"bad": 1}]})
        self.assertEqual(okx, [("2026-09-11", 0.00012)])
        with self.assertRaises(sources.SourceError):
            sources.parse_okx_funding({"code": "50011", "msg": "rate limit"})
        hl = sources.parse_hyperliquid_funding([{"coin": "BTC", "fundingRate": "0.00001", "time": 1788890400039}, {"coin": "BTC", "fundingRate": "0.00002", "time": 1788894000054}, {}])
        self.assertEqual(len(hl), 2)
        self.assertAlmostEqual(sources.funding_daily(hl, per_day=24)[0][1], 0.000015 * 24 * 365 * 100)
        g = sources.parse_coingecko_global({"data": {"market_cap_percentage": {"btc": 58.2, "eth": 11.7}, "total_market_cap": {"usd": 2.7e12}, "updated_at": 1789121067}})
        self.assertEqual(g["date"], "2026-09-11")
        self.assertAlmostEqual(g["btc_dom"], 58.2)
        with self.assertRaises(sources.SourceError):
            sources.parse_coingecko_global({"data": {"market_cap_percentage": {}}})


class Rules(unittest.TestCase):
    def test_rsi(self):
        up = b.rsi([float(i) for i in range(1, 40)])
        self.assertIsNone(up[13])
        self.assertAlmostEqual(up[-1], 100.0)
        down = b.rsi([float(40 - i) for i in range(1, 40)])
        self.assertAlmostEqual(down[-1], 0.0)
        flat = b.rsi([10.0, 11.0] * 20)
        self.assertTrue(45 < flat[-1] < 55)
        self.assertEqual(b.rsi([1.0, 2.0]), [None, None])

    def test_buckets_and_spark(self):
        s = daily([float(i) for i in range(1, 30)], "2026-08-31")                  # a Monday
        wk = b.bucket(s, "week")
        self.assertEqual(wk[0][0], "2026-09-06")                                    # the Sunday close carries the week
        self.assertEqual(len(wk), 5)
        self.assertEqual(b.bucket(s, "month")[0][0], "2026-08-31")
        self.assertEqual(len(b.spark(s, 3)), 3)

    def test_puell_thermo_mvrv_flows(self):
        iss = daily([10.0] * 400)
        pu = b.puell_series(iss)
        self.assertEqual(len(pu), 36)
        self.assertAlmostEqual(pu[-1][1], 1.0)
        price = daily([2.0] * 400)
        fee = daily([1.0] * 400)
        th = b.thermocap_series(iss, fee, price)
        self.assertAlmostEqual(th[-1][1], 400 * 12.0)                              # issuance plus one coin of fees at 2 dollars a day
        mcap = daily([100.0] * 400)
        self.assertAlmostEqual(b.multiple(mcap, th)[-1][1], 100.0 / 4800.0)
        z = b.mvrv_z_series(daily([100.0, 120.0, 140.0]), daily([1.0, 1.5, 2.0]))
        self.assertAlmostEqual(z[0][1], 0.0)
        self.assertGreater(z[-1][1], 0.0)
        ex = b.exflow_series(daily([10.0] * 40), daily([15.0] * 40), daily([1000.0] * 40))
        self.assertEqual(len(ex), 11)
        self.assertAlmostEqual(ex[-1][1], -5.0 * 30 / 1000.0 * 100.0)

    def test_log_regression(self):
        days = [(dt.date.fromisoformat(d) - b.GENESIS).days for d, _ in daily([0.0] * 800, "2015-01-01")]
        price = [((b.GENESIS + dt.timedelta(days=x)).isoformat(), 1e-12 * x ** 5) for x in days]
        reg = b.log_regression(price)
        self.assertAlmostEqual(reg["b"], 5.0, places=6)
        self.assertAlmostEqual(reg["res"][-1], 0.0, places=6)
        self.assertAlmostEqual(b.fit_at(reg, price[-1][0]), price[-1][1], delta=price[-1][1] * 1e-6)
        pts = b.band_points(price, reg, start="2016-01-01")
        self.assertTrue(all(p[3] <= p[2] <= p[4] for p in pts))

    def test_pi_cycle(self):
        bottom = daily([100.0] * 600 + [20.0] * 250, "2019-01-01")
        pi = b.pi_cycle(bottom)
        self.assertIsNotNone(pi["bottom"])
        self.assertIsNone(pi["top"])
        top = daily([10.0] * 600 + [10.0 + 0.5 * i for i in range(300)], "2019-01-01")
        pi = b.pi_cycle(top)
        self.assertIsNotNone(pi["top"])
        self.assertIsNone(b.pi_cycle(daily([1.0] * 100)))

    def test_cycle_clock(self):
        price = daily([100.0 + (i % 50) for i in range(6000)], "2010-07-18")       # through 2026-12
        clock = b.cycle_clock(price, "2026-09-11")
        self.assertEqual(clock["halving"], "2024-04-20")
        self.assertEqual(clock["since_halving"], 874)
        self.assertEqual(clock["window_halving"], ("2026-06-06", "2026-10-31"))
        self.assertEqual(clock["window_low"], ("2026-10-22", "2026-10-28"))
        self.assertEqual(len(clock["prior_drawdowns"]), 3)
        cyc = b.cycle_points(price[:5000])
        self.assertEqual([c["label"] for c in cyc], ["2012", "2016", "2020", "2024"])
        self.assertEqual(cyc[0]["pts"][0], [0, 1.0])
        self.assertEqual(len(cyc[0]["pts"]), 209)

    def test_votes_and_tally(self):
        self.assertEqual(b.vote_low_high(0.4, 0.5, 2.0), 1)
        self.assertEqual(b.vote_low_high(2.5, 0.5, 2.0), -1)
        self.assertEqual(b.vote_low_high(1.0, 0.5, 2.0), 0)
        self.assertIsNone(b.vote_low_high(None, 0.5, 2.0))
        self.assertEqual(b.vote_high_low(6.0, 5.0, 0.0), 1)
        self.assertEqual(b.vote_high_low(-1.0, 5.0, 0.0), -1)
        rows = [{"key": k, "vote": v} for k, v in (("a", 1), ("b", 1), ("c", 1), ("d", 1), ("e", -1), ("f", 0), ("g", None))]
        t = b.tally(rows)
        self.assertEqual((len(t["bull"]), len(t["bear"]), len(t["neutral"]), len(t["unscored"]), t["scored"]), (4, 1, 1, 1, 6))
        self.assertEqual(t["gap"], 3)
        self.assertEqual(t["lean"], "split")
        rows.append({"key": "h", "vote": 1})
        self.assertEqual(b.tally(rows)["lean"], "bull")

    def test_change_entries(self):
        cur = {"lean": {"state": "split"}, "tally": {"bull": 6, "bear": 4, "neutral": 11}, "votes": {"cross": 1, "puell": 0, "fng": -1, "pi": 0}}
        prev = {"v5": {"lean": {"state": "bear"}, "votes": {"cross": -1, "puell": 1, "fng": -1, "pi": None}}}
        out = b.change_entries(prev, cur, "2026-09-11T05:30")
        texts = {e["key"]: (e["tier"], e["text"]) for e in out}
        self.assertEqual(texts["btc.lean"][0], "note")
        self.assertEqual(texts["btc.vote.cross"][0], "must")
        self.assertEqual(texts["btc.vote.puell"][0], "fyi")
        self.assertNotIn("btc.vote.fng", texts)
        self.assertNotIn("btc.vote.pi", texts)                                       # unscored before: no flip
        prev["v5"]["lean"]["state"] = "bull"
        cur["lean"]["state"] = "bear"
        self.assertEqual(b.change_entries(prev, cur, "2026-09-11T05:30")[0]["tier"], "must")
        self.assertEqual(b.change_entries({}, cur, "2026-09-11T05:30"), [])
        self.assertEqual(b.change_entries({"v5": prev["v5"]}, cur, "2026-09-11T05:30")[0]["sec"], "bitcoin")

    def test_rows_contract(self):
        keys = [r[0] for r in b.ROWS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(b.SCORED), 21)
        for k in b.SCORED:
            self.assertIn(k, b.T)
        self.assertTrue(all(g in dict(b.GROUPS) for _, g, *_r in b.ROWS))
        for r in b.ROWS:
            for txt in r[2:]:
                self.assertNotIn("—", txt)
                self.assertNotIn("–", txt)
                self.assertNotIn("...", txt)

    def test_run_on_synthetic(self):
        n = 6000
        price = daily([1000.0 * (1.0 + 0.0002 * i) * (1.0 + 0.1 * math.sin(i / 90.0)) for i in range(n)], "2010-07-18")
        cm = {"price": price, "mvrv": daily([1.2] * n, "2010-07-18"), "mcap": daily([1e12] * n, "2010-07-18"), "iss_usd": daily([3e7] * n, "2010-07-18"),
              "fee_ntv": daily([3.0] * n, "2010-07-18"), "supply": daily([2e7] * n, "2010-07-18"), "flow_in": daily([100.0] * n, "2010-07-18"), "flow_out": daily([120.0] * n, "2010-07-18")}
        D = {"btc_chain": cm, "stables": daily([1e11 * (1 + 0.001 * i) for i in range(400)], "2025-08-01"), "funding": daily([8.0] * 60, "2026-07-01"),
             "crypto_fng": daily([50.0] * 400, "2025-08-01"), "dxy": {"close": daily([100.0] * 300, "2025-11-01")}, "cg_global": {"date": "2026-09-11", "btc_dom": 58.0, "eth_dom": 11.0, "total_usd": 2.7e12}}
        V = {"state": {"regime": {"composites": {"liq": {"value": 0.7}}}}, "v3": {"markets": {"btc": {"div": -2.0, "state": "down", "date": "2026-09-01"}}}}
        R = b.run(D, V, None, "2026-09-11", True, {})
        self.assertEqual([r["key"] for r in R["rows"]], [r[0] for r in b.ROWS])
        by = {r["key"]: r for r in R["rows"]}
        self.assertEqual(by["puell"]["vote"], 0)                                      # constant issuance: multiple 1.0
        self.assertEqual(by["liquidity"]["vote"], 1)
        self.assertEqual(by["position"]["vote"], -1)
        self.assertEqual(by["stables"]["vote"], 1)
        self.assertIsNone(by["search"]["vote"])
        self.assertIsNone(by["dominance"]["vote"])
        self.assertEqual(R["lean"]["raw_count"], 3)                                   # first run: taken as confirmed
        self.assertIn("scored indicators", R["read"])
        blk = b.block(R, dt.datetime(2026, 9, 11, 5, 30))
        self.assertEqual(len(blk["rows"]), len(b.ROWS))
        self.assertIn("band", blk["charts"])
        self.assertEqual(blk["lean"]["state"], R["tally"]["lean"])


if __name__ == "__main__":
    unittest.main()

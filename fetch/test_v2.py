"""python3 -m unittest fetch.test_v2  (regime, detector, conditions and change-log rules)"""
import datetime as dt
import math
import unittest

from fetch import changes as ch
from fetch import conditions as cond
from fetch import detector as det
from fetch import regime as rg


def daily(values, start="2020-01-01"):
    d0 = dt.date.fromisoformat(start)
    out, i = [], 0
    for v in values:
        while (d0 + dt.timedelta(days=i)).weekday() >= 5:
            i += 1
        out.append(((d0 + dt.timedelta(days=i)).isoformat(), v))
        i += 1
    return out


class Regime(unittest.TestCase):
    def test_rolling_z(self):
        s = daily([1.0] * 30 + [2.0])
        z = rg.rolling_z(s, 31, min_obs=10)
        self.assertIsNone(z[5][1])
        self.assertGreater(z[-1][1], 2.0)
        self.assertEqual(rg.rolling_z(daily([5.0] * 20), 20, 10)[-1][1], 0.0)

    def test_composite_and_quadrant(self):
        a = daily([float(i) for i in range(60)])
        b = daily([float(-i) for i in range(60)])
        comp = rg.composite_series([(a, "w"), (b, "w")])
        self.assertAlmostEqual(comp[-1][1], 0.0, places=6)
        self.assertEqual(rg.quadrant(0.4, -0.6)[0], "Recovery")
        self.assertEqual(rg.quadrant(-0.1, 0.2)[0], "Stagflation")
        self.assertEqual(rg.word3(0.3, "expanding", "contracting", "flat"), "expanding")
        self.assertEqual(rg.word3(-0.1, "expanding", "contracting", "flat"), "flat")


class Detector(unittest.TestCase):
    def test_rs_line_and_signal(self):
        n = 400
        spy = daily([100.0 * (1.001 ** i) for i in range(n)])
        theme = daily([100.0 * (1.001 ** i) * (1.0 + (0.002 * (i - 250) if i > 250 else 0)) for i in range(n)])
        line = det.rs_line(theme, spy)
        states = det.rs_states(line)
        sig = det.rs_signal(states)
        self.assertEqual(sig["value"], 1)
        self.assertGreater(sig["sessions"], 50)
        self.assertLess(states[100][1] if states[100][1] is not None else 0, 1)

    def test_seasonal_window(self):
        # a theme that beats the index every September to October for twenty years
        d0 = dt.date(2004, 1, 1)
        theme, spy = [], []
        day = d0
        lvl_t = lvl_s = 100.0
        while day <= dt.date(2025, 12, 31):
            if day.weekday() < 5:
                lvl_s *= 1.0002
                lvl_t *= 1.0002 * (1.002 if day.month in (9, 10) else 0.9999)
                theme.append((day.isoformat(), lvl_t)); spy.append((day.isoformat(), lvl_s))
            day += dt.timedelta(days=1)
        w = det.seasonal_window(det.Dated(theme), det.Dated(spy), "2026-09-01")
        self.assertEqual(w["value"], 1)
        self.assertGreaterEqual(w["hit"], 90)
        w2 = det.seasonal_window(det.Dated(theme), det.Dated(spy), "2026-03-01")
        self.assertEqual(w2["value"], -1)

    def test_breadth(self):
        cal = daily([1.0] * 120)
        up = daily([100.0 + i for i in range(120)])
        down = daily([200.0 - i for i in range(120)])
        members = [up] * 6 + [down] * 4
        series = det.breadth_series(members, cal, n=50, lookback=25)
        self.assertEqual(len(series), 25)
        self.assertAlmostEqual(series[-1][1], 60.0)
        self.assertEqual(det.breadth_signal([("d1", 30.0), ("d2", 45.0), ("d3", 65.0)])["value"], 1)
        self.assertEqual(det.breadth_signal([("d1", 70.0), ("d2", 55.0), ("d3", 35.0)])["value"], -1)

    def test_macro(self):
        comps = {"real21": (daily([-12.0] * 30), "10Y real yield %+.0f bp"), "dxy21": (daily([-1.5] * 30), "dollar %+.1f%%")}
        v, txt = det.macro_at(comps, "gold", comps["real21"][0][-1][0])
        self.assertEqual(v, 1)
        self.assertEqual(txt, ["10Y real yield -12 bp", "dollar -1.5%"])
        comps["dxy21"] = (daily([+1.5] * 30), "dollar %+.1f%%")
        self.assertEqual(det.macro_at(comps, "gold", comps["real21"][0][-1][0])[0], 0)
        self.assertEqual(det.macro_at(comps, "nothing", "2020-02-01")[0], None)

    def test_score_and_states(self):
        e, l, n = det.score({"rs": 1, "flow": None, "breadth": 0, "seasonal": 1, "macro": 1})
        self.assertEqual((e, l, n), (2.5, 0.0, 3))
        self.assertEqual(det.raw_state(4, 0, "developing"), "confirmed")
        self.assertEqual(det.raw_state(4, 0, "developing", evidence_ok=False), "developing")
        self.assertEqual(det.raw_state(1, 2, "confirmed"), "fading")
        self.assertEqual(det.raw_state(0, 1, "none"), "watch_exit")
        st = det.confirm_state(None, "early", "2026-08-01", True)
        self.assertEqual(st["state"], "early")
        st = det.confirm_state(st, "developing", "2026-08-02", False)
        self.assertEqual(st["state"], "early")
        st = det.confirm_state(st, "developing", "2026-08-03", False)
        st = det.confirm_state(st, "developing", "2026-08-04", False)
        self.assertEqual((st["state"], st["since"]), ("developing", "2026-08-02"))

    def test_rotation_point(self):
        n = 400
        spy = daily([100.0] * n)
        theme = daily([100.0 + (i - 300 if i > 300 else 0) for i in range(n)])
        p = det.rotation_point(theme, spy)
        self.assertGreater(p["rs"], 100)
        self.assertGreater(p["mom"], 100)
        self.assertEqual(det.quadrant_of(p["rs"], p["mom"]), "Leading")
        self.assertEqual(det.quadrant_of(98, 101), "Improving")

    def test_monthly_profile(self):
        d0 = dt.date(2005, 1, 1)
        s, lvl, day = [], 100.0, d0
        while day <= dt.date(2025, 12, 31):
            if day.weekday() < 5:
                lvl *= 1.001 if day.month == 11 else 0.9999
                s.append((day.isoformat(), lvl))
            day += dt.timedelta(days=1)
        prof = det.monthly_profile(s)
        self.assertGreater(prof[10]["avg"], 1.5)
        self.assertLess(prof[0]["avg"], 0)
        self.assertEqual(prof[10]["hit"], 100.0)


class Conditions(unittest.TestCase):
    def test_pillars_and_read(self):
        self.assertEqual(cond.half(1.34), 1.5)
        self.assertEqual(cond.half(-3.0), -2.0)
        self.assertEqual(cond.pct_to_score(85, False), -2)
        self.assertEqual(cond.pct_to_score(85, True), 2)
        self.assertEqual(cond.read(1.3, 1.6), "Aligned up")
        self.assertEqual(cond.read(1.3, -0.8), "Divergence")
        self.assertEqual(cond.read(0.8, 0.2), "Conditions ahead, up")
        self.assertEqual(cond.read(-0.2, -0.9), "Price ahead, down")
        self.assertEqual(cond.read(0.1, 0.2), "Neutral")


class Changes(unittest.TestCase):
    def test_diff_and_merge(self):
        prev = {"regime": {"flags": {"liquidity": "expanding", "cycle": "Recovery"}},
                "detector": {"gdx": {"state": "developing", "name": "Gold miners"}},
                "ranking": {"gold": {"read": "Neutral", "name": "Gold"}}, "sectors": {}}
        cur = {"regime": {"flags": {"liquidity": "contracting", "cycle": "Recovery"}, "composites": {"liq": {"value": -0.4}}},
               "detector": {"gdx": {"state": "confirmed", "name": "Gold miners", "count": 4, "on": ["Relative strength", "Macro"]}},
               "ranking": {"gold": {"read": "Aligned up", "name": "Gold", "cond": 1.0, "price": 1.2}}, "sectors": {}}
        t = "2026-08-30T05:30:00+07:00"
        out = ch.diff_states(prev, cur, t)
        tiers = sorted(c["tier"] for c in out)
        self.assertEqual(tiers, ["must", "must", "must"])
        self.assertTrue(any("contracting" in c["text"] for c in out))
        self.assertEqual(ch.diff_states(None, cur, t), [])
        merged = ch.merge([{"t": "2026-08-29T05:30:00+07:00", "d": "29 Aug", "tier": "must", "sec": "regime", "href": "#regime", "text": "old", "key": "flag.liquidity"}], out, t)
        self.assertEqual(len([c for c in merged if c["key"] == "flag.liquidity"]), 1)   # deduped inside a week
        self.assertEqual(merged[0]["t"], t)
        self.assertTrue(all("—" not in c["text"] and " - " not in c["text"] for c in merged))


if __name__ == "__main__":
    unittest.main()


class Positioning(unittest.TestCase):
    def rows(self, n=200, long_key="comm_positions_long_all", short_key="comm_positions_short_all", nc=("noncomm_positions_long_all", "noncomm_positions_short_all")):
        out = []
        d0 = dt.date(2023, 1, 3)
        for i in range(n):
            d = (d0 + dt.timedelta(weeks=i)).isoformat()
            out.append({"date": d, long_key: 100000.0 + i * 100, short_key: 300000.0 - i * 500, nc[0]: 200000.0 + i * 600, nc[1]: 100000.0, "open_interest_all": 500000.0})
        return out

    def test_cot_series_and_index(self):
        from fetch import positioning as pos
        cs = pos.cot_series("gold", self.rows())
        self.assertEqual(cs["mode"], "comm_change")
        self.assertGreater(cs["smart_input"][-1][1], 0)            # shorts falling: covering reads positive
        self.assertEqual(round(pos.cot_index(cs["crowd"])), 100)   # crowd net at a three-year high
        cs2 = pos.cot_series("copper", self.rows())
        self.assertEqual(cs2["mode"], "comm")
        self.assertEqual(cs2["smart_input"][-1], cs2["hedgers"][-1])

    def test_scores_and_alerts(self):
        from fetch import positioning as pos
        cs = pos.cot_series("gold", self.rows())
        sc = pos.market_scores("gold", cs, [], [], {})
        self.assertIsNotNone(sc["div"])
        weekly = [("2026-08-04", 1.0), ("2026-08-11", 1.6), ("2026-08-18", 1.7)]
        self.assertEqual(pos.alert_state(weekly), "up")
        self.assertIsNone(pos.alert_state(weekly[:2]))
        self.assertEqual(pos.crowd_word(0.7), "optimistic, not euphoric")
        self.assertEqual(pos.crowd_word(-1.6), "capitulating")
        self.assertIn("Alert", pos.div_read(1.8, "up"))

    def test_cta_and_flows(self):
        from fetch import positioning as pos
        up = daily([100.0 + i * 0.3 for i in range(260)])
        sig = pos.cta_signal(up)
        self.assertEqual(sig["signal"], 1)
        self.assertLess(sig["flip_level"], up[-1][1])
        down = daily([200.0 - i * 0.3 for i in range(260)])
        self.assertEqual(pos.cta_signal(down)["signal"], -1)
        calm = daily([100.0 * (1.0005 ** i) for i in range(120)])
        vc = pos.vol_control(calm)
        self.assertEqual(vc["word"], "high")
        pr = pos.pension_rebalance(daily([100.0 + i for i in range(80)], "2026-07-01"), daily([100.0] * 80, "2026-07-01"), "2026-08-28")
        self.assertIn("sell equities", pr["word"])

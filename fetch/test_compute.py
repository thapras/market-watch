"""python3 -m unittest fetch.test_compute  (from the project root)"""
import math
import unittest

from fetch import compute as c


def series(values, start_day=1):
    return [("2026-%02d-%02d" % (1 + i // 28, 1 + i % 28), v) for i, v in enumerate(values)]


class Basics(unittest.TestCase):
    def test_pct_and_change(self):
        s = series([100, 110, 121])
        self.assertAlmostEqual(c.pct(s, 1), 10.0)
        self.assertAlmostEqual(c.pct(s, 2), 21.0)
        self.assertIsNone(c.pct(s, 3))
        self.assertAlmostEqual(c.change(s, 2), 21)

    def test_ytd(self):
        s = [("2025-12-30", 100.0), ("2025-12-31", 200.0), ("2026-01-05", 210.0), ("2026-02-01", 250.0)]
        self.assertAlmostEqual(c.ytd_pct(s), 25.0)

    def test_percentile(self):
        x = list(range(1, 101))
        self.assertAlmostEqual(c.percentile(x, 100), 100.0)
        self.assertAlmostEqual(c.percentile(x[::-1], 100), 0.0)

    def test_round_half_up(self):
        self.assertEqual(c.round_half_up(0.25, 1), 0.3)
        self.assertEqual(c.round_half_up(-0.25, 1), -0.3)
        self.assertEqual(c.round_half_up(1.04, 1), 1.0)

    def test_sample_points_month(self):
        s = [("2026-%02d-%02d" % (m, d), m * 100 + d) for m in range(1, 13) for d in (5, 15, 25)]
        pts = c.sample_points(s, 12, "month")
        self.assertEqual(len(pts), 12)
        self.assertEqual(pts[0], 125)
        self.assertEqual(pts[-1], 1225)


class Rules(unittest.TestCase):
    def test_T_uptrend(self):
        x = [100 + i * 0.5 for i in range(300)]
        self.assertEqual(c.rule_T(x), 2)

    def test_T_downtrend(self):
        x = [300 - i * 0.5 for i in range(300)]
        self.assertEqual(c.rule_T(x), -2)

    def test_X_fresh_golden_cross_counts_double(self):
        x = [100 - i * 0.2 for i in range(260)] + [48 + i * 1.5 for i in range(60)]
        self.assertEqual(c.rule_X(x), 2)

    def test_X_old_dead_cross(self):
        x = [200 + i * 0.3 for i in range(260)] + [280 - i * 0.6 for i in range(200)]
        self.assertEqual(c.rule_X(x), -1)

    def test_H_bands(self):
        base = [100.0] * 250 + [60.0] + [100.0] * 49      # an old low, so a dip is not a new low
        self.assertEqual(c.rule_H(base + [99.0]), 2)
        self.assertEqual(c.rule_H(base + [92.0]), 1)
        self.assertEqual(c.rule_H(base + [85.0]), 0)
        self.assertEqual(c.rule_H(base + [75.0]), -1)
        self.assertEqual(c.rule_H([100.0] * 299 + [70.0, 69.0]), -2)

    def test_M_ranks(self):
        moms = {k: v for k, v in zip("abcdefghijklmnopq", range(17, 0, -1))}
        r = c.rule_M_ranks(moms)
        self.assertEqual([r[k] for k in "abc"], [2, 2, 2])
        self.assertEqual([r[k] for k in "def"], [1, 1, 1])
        self.assertEqual([r[k] for k in "opq"], [-2, -2, -2])
        self.assertEqual([r[k] for k in "lmn"], [-1, -1, -1])
        self.assertEqual(r["h"], 0)

    def test_tags_breakout_and_extended(self):
        x = [100.0] * 100 + [120.0]
        t = c.tags(x)
        self.assertIn("55-day breakout", t)
        self.assertIn("Extended", t)

    def test_tags_failed_breakout(self):
        x = [100.0] * 100 + [103.0] + [98.0] * 5
        self.assertIn("Failed breakout", c.tags(x))

    def test_tags_base(self):
        x = [100.0 + (i % 3) for i in range(120)]
        self.assertIn("Base", c.tags(x))

    def test_price_score(self):
        self.assertEqual(c.price_score({"T": 2, "M": 1, "X": 2, "H": 2, "B": 2}), 1.8)
        self.assertEqual(c.price_score({"T": 2, "M": None, "X": 1, "H": 0, "B": None}), 1.0)
        self.assertIsNone(c.price_score({"T": 2, "M": None, "X": None, "H": None, "B": None}))

    def test_rs_trend_cross(self):
        x = [2.0 - 0.01 * i for i in range(80)] + [1.5, 1.6, 1.7, 1.8, 1.9]
        state, since, direction = c.rs_trend(x)
        self.assertEqual(direction, "up")
        self.assertIsNotNone(since)




class StepSeries(unittest.TestCase):
    def test_last_change(self):
        s = [("2026-01-01", 1.0), ("2026-01-02", 1.0), ("2026-01-03", 1.25), ("2026-01-04", 1.25)]
        self.assertEqual(c.last_change(s), ("2026-01-03", 0.25))
        self.assertIsNone(c.last_change([("2026-01-01", 1.0), ("2026-01-02", 1.0)]))

    def test_rolling_sum(self):
        s = series([1, 2, 3, 4])
        self.assertEqual([v for _, v in c.rolling_sum(s, 2)], [3, 5, 7])
        self.assertEqual(c.rolling_sum(s, 2)[0][0], s[1][0])


class Parsers(unittest.TestCase):
    """Fixtures are trimmed copies of the real pages, so a layout change shows up here first."""
    def test_eia_weekly(self):
        from fetch import sources
        txt = ("<tr><td class='B6'>&nbsp;&nbsp;2025-Dec</td><td class='B5'>12/26&nbsp;</td><td class='B3'>415,000&nbsp;</td>"
               "<td class='B5'>01/02&nbsp;</td><td class='B3'>416,500&nbsp;</td></tr>"
               "<tr><td class='B6'>&nbsp;&nbsp;2026-Aug</td>\n <td class='B5'>08/07&nbsp;</td>\n <td class='B3'>424,410&nbsp;&nbsp;&nbsp;</td>\n"
               " <td class='B5'>08/14&nbsp;</td>\n <td class='B3'>428,815&nbsp;&nbsp;&nbsp;</td>\n <td class='B5'>&nbsp;</td>\n <td class='B3'>&nbsp;&nbsp;&nbsp;</td></tr>")
        self.assertEqual(sources.parse_eia_weekly(txt),
                         [("2025-12-26", 415000.0), ("2026-01-02", 416500.0), ("2026-08-07", 424410.0), ("2026-08-14", 428815.0)])

    def test_eia_monthly(self):
        from fetch import sources
        txt = ("<tr> <td class='B4'>&nbsp;&nbsp;2026</td> <td class='B3'>410</td> <td class='B3'>409</td> <td class='B3'></td>"
               + " <td class='B3'></td>" * 9 + "</tr>")
        self.assertEqual(sources.parse_eia_monthly(txt), [("2026-01-01", 410.0), ("2026-02-01", 409.0)])

    def test_boj_table(self):
        from fetch import sources
        txt = ("<tr><td>Series code</td><td><span>MD02'MAM1YAM2M2MO</span></td><td></td><td>MD02'MAM1NAM2M2MO</td></tr>"
               "<tr><td>Unit</td><td>%</td><td>100 million yen</td></tr>"
               "<tr><td>2026/06</td><td> 2.2</td><td>12961250</td></tr><tr><td>2026/07</td><td> 2.2</td><td>12970074</td></tr>")
        self.assertEqual(sources.parse_boj_table(txt, "MD02'MAM1NAM2M2MO"), [("2026-06-01", 12961250.0), ("2026-07-01", 12970074.0)])
        self.assertEqual(sources.parse_boj_table(txt, "MD02'MAM1YAM2M2MO")[-1], ("2026-07-01", 2.2))

    def test_multpl(self):
        from fetch import sources
        txt = ("<tr><th>Date</th><th>Value</th></tr><tr><td>Aug 28, 2026</td><td><span>&dagger;</span>\n29.72</td></tr>"
               "<tr><td>Jul 1, 2026</td><td>&#x2002;\n28.71</td></tr>")
        self.assertEqual(sources.parse_multpl(txt), [("2026-07-01", 28.71), ("2026-08-28", 29.72)])

    def test_ici(self):
        from fetch import sources
        txt = ("<h2>Assets of Money Market Funds</h2><p>Billions of dollars</p><table><tr><td></td><td>8/26/2026</td><td>8/19/2026</td>"
               "<td>$ Change*</td><td>8/12/2026</td></tr><tr><td>Government</td><td>6,547.46</td><td>6,541.15</td><td>6.31</td><td>6,539.70</td></tr>"
               "<tr><td>Total</td><td>7,934.59</td><td>7,928.48</td><td>6.11</td><td>7,927.58</td></tr></table>")
        self.assertEqual(sources.parse_ici_mmf(txt), {"date": "2026-08-26", "total": 7934.59, "prior": 7928.48, "change": 6.11})

    def test_cleveland(self):
        from fetch import sources
        j = [{"chart": {"subcaption": "2026-7", "_comment": "2026-08-28 00:00"},
              "dataset": [{"seriesname": "Core CPI Inflation", "data": [{"value": "0.2"}]},
                          {"seriesname": "Actual Core CPI Inflation", "data": [{"value": ""}, {"value": "0.13"}]}]},
             {"chart": {"subcaption": "2026-8", "_comment": "2026-08-28 00:00"},
              "dataset": [{"seriesname": "CPI Inflation", "data": [{"value": "0.11"}, {"value": "0.12"}]},
                          {"seriesname": "Core CPI Inflation", "data": [{"value": "0.15"}, {"value": "0.14"}, {"value": ""}]}]},
             {"chart": {"subcaption": "2026-9", "_comment": "2026-08-28 00:00"},
              "dataset": [{"seriesname": "Core CPI Inflation", "data": [{"value": ""}]}]}]
        r = sources.parse_cleveland_nowcast(j)
        self.assertEqual((r["month"], r["asof"], r["core_cpi"], r["cpi"], r["prior_month"], r["prior_core_actual"]),
                         ("2026-08", "2026-08-28", 0.14, 0.12, "2026-07", 0.13))


if __name__ == "__main__":
    unittest.main()

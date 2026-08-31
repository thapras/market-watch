"""The watchlist: the snapshot CLI rules and the nightly grading."""
import datetime as dt
import unittest

from . import render, watch


def series(start, n, step):
    """n weekday closes from start, compounding at step per session, starting at 100."""
    cur, v, out = dt.date.fromisoformat(start), 100.0, []
    while len(out) < n:
        if cur.weekday() < 5:
            out.append((cur.isoformat(), v))
            v *= 1.0 + step
        cur += dt.timedelta(days=1)
    return out


def sdate(s, k):
    """The date k sessions before the last close."""
    return s[-1 - k][0]


def latest_stub(keys=("gold",)):
    rank = {k: {"cond": 0.6, "price": 1.6, "read": "Aligned up", "tags": "55-day breakout",
                "rules": {"T": 2.0}, "pillars": {"L": {"v": 2.0, "title": "Liquidity +2.0"}}} for k in keys}
    return {"asOf": "2026-08-31T05:30", "rank": rank}


def fresh():
    return {"open": [], "closed": []}


class WatchCli(unittest.TestCase):
    def test_add_snapshots_the_row(self):
        w = fresh()
        msg = watch.add(latest_stub(), w, "gold", "own the monetary trade")
        self.assertIn("snapshotted gold at 2026-08-31", msg)
        e = w["open"][0]
        self.assertEqual(e["id"], "gold:2026-08-31")
        self.assertEqual(e["then"]["cond"], 0.6)
        self.assertEqual(e["then"]["pillars"]["L"], 2.0)
        self.assertEqual(e["note"], "own the monetary trade")

    def test_add_refuses_duplicates_and_bad_keys(self):
        w = fresh()
        watch.add(latest_stub(), w, "gold", "")
        with self.assertRaises(ValueError):
            watch.add(latest_stub(), w, "gold", "")
        with self.assertRaises(ValueError):
            watch.add(latest_stub(), w, "cash", "")
        with self.assertRaises(ValueError):
            watch.add(latest_stub(), w, "AAPL", "")
        with self.assertRaises(ValueError):
            watch.add(latest_stub(keys=("silver",)), w, "copper", "")   # no ranking row yet

    def test_close_moves_and_keeps(self):
        w = fresh()
        watch.add(latest_stub(), w, "gold", "")
        msg = watch.close(latest_stub(), w, "gold", "thesis played out")
        self.assertIn("closed the gold snapshot", msg)
        self.assertEqual(w["open"], [])
        self.assertEqual(w["closed"][0]["closed"], "2026-08-31")
        self.assertEqual(w["closed"][0]["close_note"], "thesis played out")
        with self.assertRaises(ValueError):
            watch.close(latest_stub(), w, "gold", "")
        watch.add(latest_stub(), w, "gold", "again")    # re-add after close is allowed
        self.assertEqual(len(w["open"]), 1)


class WatchGrading(unittest.TestCase):
    def D(self, asset_step, spx_step=0.0, n=260, yk="gold"):
        spx = series("2025-08-01", n, spx_step)
        return {"spx": {"adj": spx, "close": spx},
                yk: {"adj": series("2025-08-01", n, asset_step), "close": []}}

    def out_with(self, cond=0.6):
        o = render.Out()
        o.rank["gold"] = {"cond": cond, "price": 1.6, "read": "Aligned up"}
        o.rank["us_large"] = {"cond": 0.1, "price": 1.4, "read": "Price ahead, up"}
        return o

    def entry(self, D, key="gold", back=60, yk="gold"):
        date = sdate(D[yk]["adj"], back)
        return {"id": "%s:%s" % (key, date), "key": key, "date": date, "note": "",
                "then": {"cond": 0.6, "price": 1.6, "read": "Aligned up"}}

    def test_working_beats_the_benchmark(self):
        D = self.D(0.002, 0.0)
        o = self.out_with()
        render.render_watchlist(D, o, {"open": [self.entry(D)], "closed": []})
        r = o.v2["watchlist"]["rows"][0]
        self.assertEqual(r["verdict"], "working")
        self.assertEqual(r["sessions"], 60)
        self.assertGreater(r["rel"], 0)
        self.assertAlmostEqual(r["ret"], 1.002 ** 60 - 1.0, places=6)

    def test_early_under_21_sessions(self):
        D = self.D(0.002)
        o = self.out_with()
        render.render_watchlist(D, o, {"open": [self.entry(D, back=10)], "closed": []})
        self.assertEqual(o.v2["watchlist"]["rows"][0]["verdict"], "early")

    def test_stalled_when_conditions_hold(self):
        D = self.D(0.0, 0.002)
        o = self.out_with(cond=0.8)
        render.render_watchlist(D, o, {"open": [self.entry(D)], "closed": []})
        self.assertEqual(o.v2["watchlist"]["rows"][0]["verdict"], "stalled")

    def test_not_working_when_conditions_fade(self):
        D = self.D(0.0, 0.002)
        o = self.out_with(cond=0.1)
        render.render_watchlist(D, o, {"open": [self.entry(D)], "closed": []})
        self.assertEqual(o.v2["watchlist"]["rows"][0]["verdict"], "not working")

    def test_us_large_grades_on_absolute_return(self):
        D = self.D(0.002, 0.002)    # spx and the asset are the same series
        o = self.out_with()
        e = self.entry(D, key="us_large", yk="spx")
        render.render_watchlist(D, o, {"open": [e], "closed": []})
        r = o.v2["watchlist"]["rows"][0]
        self.assertEqual(r["verdict"], "working")
        self.assertAlmostEqual(r["rel"], r["ret"], places=9)

    def test_closed_grades_over_its_own_span(self):
        D = self.D(0.002, 0.0)
        o = self.out_with()
        e = self.entry(D, back=120)
        e["closed"], e["close_note"] = sdate(D["gold"]["adj"], 60), "done"
        render.render_watchlist(D, o, {"open": [], "closed": [e]})
        r = o.v2["watchlist"]["closed"][0]
        self.assertEqual(r["verdict"], "worked")
        self.assertEqual(r["sessions"], 60)
        self.assertAlmostEqual(r["ret"], 1.002 ** 60 - 1.0, places=6)

    def test_missing_series_carries_the_previous_grade(self):
        D = self.D(0.002)
        o = self.out_with()
        e = self.entry(D)
        prev = {"rows": [{"id": e["id"], "key": "gold", "date": e["date"], "verdict": "working",
                          "rel": 0.05, "asof_dl": "28 Aug 2026"}], "closed": []}
        del D["gold"]
        render.render_watchlist(D, o, {"open": [e], "closed": []}, prev)
        r = o.v2["watchlist"]["rows"][0]
        self.assertEqual(r["verdict"], "working")
        self.assertEqual(r["stale"], "28 Aug 2026")

    def test_missing_series_without_a_carry(self):
        D = self.D(0.002)
        del D["gold"]
        o = self.out_with()
        render.render_watchlist(D, o, {"open": [self.entry(D, yk="spx")], "closed": []})
        r = o.v2["watchlist"]["rows"][0]
        self.assertTrue(r["missing"])
        self.assertEqual(r["verdict"], "no series")


if __name__ == "__main__":
    unittest.main()

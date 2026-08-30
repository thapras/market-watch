"""python3 -m unittest fetch.test_v4  (the calendar rules, the feed parsers on trimmed pages, event studies, implied moves, surprises)"""
import datetime as dt
import unittest

from fetch import calendar as cal
from fetch import changes as ch
from fetch import events as ev
from fetch import sources


def daily(values, start="2020-01-01"):
    d0 = dt.date.fromisoformat(start)
    out, i = [], 0
    for v in values:
        while (d0 + dt.timedelta(days=i)).weekday() >= 5:
            i += 1
        out.append(((d0 + dt.timedelta(days=i)).isoformat(), v))
        i += 1
    return out


class Rules(unittest.TestCase):
    def test_time_zones(self):
        self.assertEqual(cal.time_label("2026-09-04", "08:30"), "08:30 / 19:30")
        self.assertEqual(cal.time_label("2026-09-16", "14:00"), "14:00 / 01:00 Thu")
        self.assertEqual(cal.time_label("2026-12-16", "14:00"), "14:00 / 02:00 Thu")       # standard time: twelve hours apart
        self.assertEqual(cal.convert("2026-09-10", "14:15", "CET", "ET"), ("2026-09-10", "08:15"))
        self.assertTrue(cal.dst_us(dt.date(2026, 3, 8)) and not cal.dst_us(dt.date(2026, 3, 7)))
        self.assertTrue(cal.dst_eu(dt.date(2026, 3, 29)) and not cal.dst_eu(dt.date(2026, 10, 25)))

    def test_holidays(self):
        h = cal.us_holidays(2026)
        self.assertEqual(h["2026-09-07"], "Labor Day")
        self.assertEqual(h["2026-07-03"], "Independence Day")        # 4 July on a Saturday is taken on Friday
        self.assertEqual(h["2026-04-03"], "Good Friday")
        self.assertEqual(h["2026-11-26"], "Thanksgiving")
        self.assertNotIn("2022-01-01", cal.us_holidays(2022))          # 1 January on a Saturday is not observed
        self.assertEqual(cal.business_days_between("2026-08-28", "2026-09-16"), 12)   # Labor Day skipped

    def test_release_rules(self):
        self.assertEqual(cal.payrolls_rule(2026, 8).isoformat(), "2026-09-04")
        self.assertEqual(cal.payrolls_rule(2025, 6).isoformat(), "2025-07-03")       # 4 July: Thursday
        self.assertEqual(cal.payrolls_rule(2025, 12).isoformat(), "2026-01-09")      # New Year week slips
        self.assertEqual(cal.payrolls_rule(2021, 3).isoformat(), "2021-04-02")       # Good Friday: the BLS still publishes
        self.assertEqual([d.isoformat() for d in cal.ism_dates(2026, 10)], ["2026-10-01", "2026-10-05"])
        self.assertEqual(cal.qra_rule(2025, 8).isoformat(), "2025-07-30")
        self.assertEqual(cal.qra_rule(2026, 2).isoformat(), "2026-02-04")
        self.assertEqual(cal.blackout("2026-09-15", "2026-09-16"), ("2026-09-05", "2026-09-17"))
        self.assertEqual(cal.minutes_date("2026-09-16"), "2026-10-07")
        self.assertEqual(cal.third_friday(2026, 9).isoformat(), "2026-09-18")
        self.assertEqual(cal.quarter_end(dt.date(2026, 8, 31)).isoformat(), "2026-09-30")
        self.assertEqual(cal.tax_dates(2026)[3], (dt.date(2026, 9, 15), "corporate"))
        self.assertEqual(cal.ranges("2026-08-30")["week"], ("2026-08-31", "2026-09-06"))     # Sunday: the coming week
        self.assertEqual(cal.ranges("2026-09-02")["week"], ("2026-08-31", "2026-09-06"))
        m = cal.mechanical_next("2026-08-30")
        self.assertEqual(m["tax"], "15 Sep")
        self.assertEqual(m["opex"], "14 to 18 Sep (quad witching)")
        self.assertEqual(m["qend"], "24 to 30 Sep")

    def test_ff_mapping_and_merge(self):
        ff = [{"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-09-04T08:30:00-04:00", "impact": "High", "forecast": "58K", "previous": "-23K"},
              {"title": "Unemployment Rate", "country": "USD", "date": "2026-09-04T08:30:00-04:00", "impact": "High", "forecast": "4.1%", "previous": "4.1%"},
              {"title": "Bank Holiday", "country": "GBP", "date": "2026-08-31T00:00:00-04:00", "impact": "Holiday", "forecast": "", "previous": ""},
              {"title": "Housing Starts", "country": "USD", "date": "2026-09-02T08:30:00-04:00", "impact": "Low", "forecast": "1.3M", "previous": "1.3M"}]
        rows = cal.ff_events(ff)
        self.assertEqual([r["id"] for r in rows], ["payrolls:2026-09-04", "holiday:GBP:2026-08-31"])     # housing starts is excluded
        self.assertEqual([c["label"] for c in rows[0]["cons"]], ["payrolls", "unemployment"])
        sched = cal.scheduled_events("2026-08-30", [{"start": "2026-09-15", "end": "2026-09-16", "sep": True, "scheduled": True}], [], [], ["2026-09-04"], [], [])
        merged = cal.merge(rows, sched, ("2026-08-30", "2026-09-05"))
        ids = [e["id"] for e in merged]
        self.assertIn("fomc:2026-09-16", ids)
        self.assertIn("blackout:2026-09-05", ids)
        self.assertNotIn("ism_mfg:2026-09-01", ids)          # a usual-slot row the week's feed does not carry is dropped
        pay = next(e for e in merged if e["id"] == "payrolls:2026-09-04")
        self.assertTrue(pay["confirmed"] and pay["cons"])
        self.assertEqual(merged[0]["kind"], "holiday")       # holidays sort first in their day


class Parsers(unittest.TestCase):
    """Trimmed copies of the real pages."""
    def test_fomc_calendar(self):
        txt = ('<div class="panel panel-default"><div class="panel-heading"><h4><a id="1">2026 FOMC Meetings</a></h4></div>'
               '<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>'
               '<div class="fomc-meeting__date col-xs-4">27-28</div></div>'
               '<div class="fomc-meeting--shaded row fomc-meeting"><div class="fomc-meeting--shaded fomc-meeting__month col-xs-5"><strong>March</strong></div>'
               '<div class="fomc-meeting__date col-xs-4">17-18*</div></div>'
               '<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>August</strong></div>'
               '<div class="fomc-meeting__date col-xs-4">22 (notation vote)</div></div></div>'
               '<div class="panel panel-default"><div class="panel-heading"><h4><a id="2">2025 FOMC Meetings</a></h4></div>'
               '<div class="row fomc-meeting"><div class="fomc-meeting__month col-xs-5"><strong>Apr/May</strong></div>'
               '<div class="fomc-meeting__date col-xs-4">30-1</div></div></div>')
        out = sources.parse_fomc_calendar(txt)
        self.assertEqual([(m["start"], m["end"], m["sep"]) for m in out],
                         [("2025-04-30", "2025-05-01", False), ("2026-01-27", "2026-01-28", False), ("2026-03-17", "2026-03-18", True)])
        hist = sources.parse_fomc_history('<h5 class="panel-heading">January 29-30 Meeting - 2019</h5><h5 class="panel-heading">October 4 (unscheduled) - 2019</h5>')
        self.assertEqual([(m["end"], m["scheduled"]) for m in hist], [("2019-01-30", True), ("2019-10-04", False)])

    def test_ecb_boj(self):
        txt = ("<dt> 09/09/2026 </dt> <dd> Governing Council of the ECB: monetary policy meeting in Berlin (Day 1)<br> </dd>"
               "<dt> 10/09/2026 </dt> <dd> Governing Council of the ECB: monetary policy meeting in Berlin (Day 2), followed by press conference<br> </dd>"
               "<dt> 30/09/2026 </dt> <dd> Governing Council of the ECB: non-monetary policy meeting (virtual)<br> </dd>")
        self.assertEqual(sources.parse_ecb_calendar(txt), ["2026-09-10"])
        boj = ('<h2 id="p2026">2026</h2><table><tr><td><a href="x">Jan. 22 (Thurs.), 23 (Fri.) [PDF 171KB]</a></td><td>-</td></tr>'
               '<tr><td><a href="y">June 15 (Mon.), 16 (Tues.)</a></td><td>-</td></tr></table>'
               '<h2 id="p2027">2027</h2><table><tr><td>Sept. 22 (Wed.)</td></tr></table>')
        self.assertEqual(sources.parse_boj_calendar(boj), ["2026-01-23", "2026-06-16", "2027-09-22"])

    def test_bls(self):
        txt = ('<li><a href="/news.release/archives/empsit_09042026.htm">August 2026 Employment Situation</a></li>'
               '<li><a href="/news.release/archives/empsit_08072026.htm">July 2026 Employment Situation</a></li>')
        self.assertEqual(sources.parse_bls_archive(txt, "empsit"), ["2026-08-07", "2026-09-04"])
        sched = ('<table class="release-list"><tbody><tr class="release-list-even-row"> <td>November 2025</td> <td>Dec. 16, 2025</td> <td>08:30 AM</td> </tr>'
                 '<tr class="release-list-odd-row"> <td>December 2025</td> <td>Jan. 09, 2026</td> <td>08:30 AM</td> </tr></tbody></table>')
        self.assertEqual(sources.parse_bls_schedule(sched), [("2025-12-16", "November 2025", "08:30 AM"), ("2026-01-09", "December 2025", "08:30 AM")])

    def test_treasury_and_chain(self):
        j = [{"securityType": "Bill", "securityTerm": "13-Week", "auctionDate": "2026-08-31T00:00:00", "reopening": "Yes", "offeringAmount": "92000000000"},
             {"securityType": "Note", "securityTerm": "9-Year 11-Month", "auctionDate": "2026-09-09T00:00:00", "reopening": "Yes", "offeringAmount": "42000000000"},
             {"securityType": "Bond", "securityTerm": "30-Year", "auctionDate": "2026-09-10T00:00:00", "reopening": "No", "offeringAmount": ""}]
        self.assertEqual(sources.parse_treasury_upcoming(j), [{"date": "2026-09-09", "term": "10Y", "reopening": True, "amount": 42.0},
                                                              {"date": "2026-09-10", "term": "30Y", "reopening": False, "amount": None}])
        chain = {"timestamp": "2026-08-30 01:59:42", "data": {"current_price": 7711.76, "iv30": 11.2, "last_trade_time": "2026-08-28T16:14:59", "options": [
            {"option": "SPXW260831C07700000", "iv": 0.061}, {"option": "SPXW260831P07700000", "iv": 0.062},
            {"option": "SPXW260901C07700000", "iv": 0.073}, {"option": "SPXW260901P07700000", "iv": 0.074},
            {"option": "SPXW260901C07000000", "iv": 0.2}, {"option": "SPXW260901P07000000", "iv": 0.21},
            {"option": "SPX260918C00200000", "iv": 5.69}]}}
        out = sources.parse_cboe_chain(chain)
        self.assertEqual(out["quote_date"], "2026-08-28")
        self.assertEqual([e for e, _ in out["atm"]], ["2026-08-31", "2026-09-01"])
        self.assertAlmostEqual(out["atm"][0][1], 0.0615)
        spans = ev.session_variances(out)
        self.assertEqual(spans["2026-09-01"]["sessions"], 1)
        self.assertAlmostEqual(ev.implied_move(spans, "2026-08-31"), 0.0615 / (252 ** 0.5) * 100, places=4)
        self.assertIsNone(ev.implied_move(spans, "2026-09-02"))


class Events(unittest.TestCase):
    def test_study_and_session(self):
        s = daily([100.0, 101.0, 100.0, 102.0, 103.0, 103.0, 104.0, 102.0, 101.0, 100.0] * 6)
        dates = [s[i][0] for i in range(1, 55, 5)]
        st = ev.study(dates, {"spx": {"close": s}}, s[-1][0])
        self.assertEqual(st["n"], 11)
        self.assertIn("spx", st["markets"])
        self.assertAlmostEqual(st["markets"]["spx"]["med_abs1"], 1.0, places=6)
        self.assertEqual(ev.session_for({"date": "2026-09-05", "time": None}), "2026-09-08")      # Saturday then Labor Day
        self.assertEqual(ev.session_for({"date": "2026-09-03", "time": "16:30"}), "2026-09-04")

    def test_surprise_log(self):
        payrolls = [("2026-06-01", 159000.0), ("2026-07-01", 158977.0), ("2026-08-01", 159100.0)]
        D = {"payrolls": payrolls}
        rows = [{"date": "2026-09-04", "cons": [{"series": "nfp", "forecast": "58K", "previous": "-23K"}]}]
        log, new = ev.update_log({}, rows, D, "2026-09-03")
        self.assertEqual(log["nfp"]["2026-09-04"], {"f": 58.0, "p": -23.0})
        self.assertEqual(new, [])
        log, new = ev.update_log(log, rows, D, "2026-09-04")
        self.assertEqual(len(new), 1)
        ent = log["nfp"]["2026-09-04"]
        self.assertEqual(ent["a"], 123.0)
        self.assertEqual(ent["ref"], "2026-08-01")
        self.assertAlmostEqual(ent["z"], round((123.0 - 58.0) / 75.0, 2))
        self.assertEqual(ev.parse_number("7.33M"), 7.33)
        self.assertEqual(ev.reference_period("2026-10-29", "q"), "2026-07-01")
        idx = ev.surprise_index(log, "2026-09-04")
        self.assertIsNone(idx["value"])
        self.assertEqual(idx["resolved"], 1)
        entries = ch.calendar_entries({"events": [], "state": {"tier1_soon": [], "tier2_soon": [], "surprises": [{"series": "nfp", "date": "2026-09-04", "z": 0.87, "a": 123.0, "f": 58.0}]}}, "2026-09-04T18:30")
        self.assertEqual(entries, [])                           # inside one sigma: nothing
        entries = ch.calendar_entries({"events": [], "state": {"tier1_soon": [], "tier2_soon": [], "surprises": [{"series": "nfp", "date": "2026-09-04", "z": 1.4, "a": 163.0, "f": 58.0}]}}, "2026-09-04T18:30")
        self.assertEqual(entries[0]["tier"], "must")
        self.assertIn("+163k against +58k", entries[0]["text"])


if __name__ == "__main__":
    unittest.main()

"""Nightly fetch: pull the free feeds, compute, write data/latest.json.

    python3 -m fetch.fetch                 # writes data/latest.json
    MW_CACHE=.cache python3 -m fetch.fetch # cache responses for 12 hours while developing

Exit code 1 only when nothing could be fetched at all (the page then keeps the previous file).
A series that fails is reported in "errors"; its cells are carried forward from the previous
file with a "stale" mark so the page greys them out rather than showing a placeholder again.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

from . import changes as ch
from . import render, sources, v2, v4
from .catalog import BIS, BOJ, CBOE, ECB, EIA_MONTHLY, EIA_WEEKLY, FED_FUNDS_MONTH_CODES, FRED, HOLDINGS, LONG, LONG_SINCE, YAHOO
from .positioning import COT_MARKETS

BKK = dt.timezone(dt.timedelta(hours=7))


def ff_contract(today):
    """Fed funds futures contract twelve months out, in Yahoo's symbol form."""
    y, m = today.year + 1, today.month
    return "ZQ%s%02d.CBT" % (FED_FUNDS_MONTH_CODES[m - 1], y % 100)


def nap(seconds):
    """Be polite to the feeds, but not to the dev cache."""
    if not sources.LAST_FROM_CACHE:
        time.sleep(seconds)


def fetch_all(log):
    D, errors = {}, []
    for k, sid in FRED.items():
        try:
            D[k] = sources.fred(sid, "2010-01-01")
        except Exception as e:      # noqa: BLE001
            errors.append("FRED %s (%s): %s" % (sid, k, e))
        nap(0.15)
    for k, (flow, key) in ECB.items():
        try:
            D[k] = sources.ecb(flow, key, "2010-01-01")
        except Exception as e:      # noqa: BLE001
            errors.append("ECB %s/%s (%s): %s" % (flow, key, k, e))
    for k, sym in YAHOO.items():
        try:
            D[k] = sources.yahoo(sym, "5y", since=LONG_SINCE if k in LONG else None)
        except Exception as e:      # noqa: BLE001
            errors.append("Yahoo %s (%s): %s" % (sym, k, e))
        nap(0.25)
    sym = ff_contract(dt.datetime.now(BKK).date())
    try:
        D["ff12"] = sources.yahoo(sym, "2y")
        D["ff12_sym"] = sym
    except Exception as e:          # noqa: BLE001
        errors.append("Yahoo %s (fed funds 12m): %s" % (sym, e))
    others = []
    others += [(k, "BIS %s" % a, lambda a=a: sources.bis_policy(a)) for k, a in BIS.items()]
    others += [(k, "EIA %s" % sid, lambda sid=sid: sources.eia_weekly(sid)) for k, sid in EIA_WEEKLY.items()]
    others += [(k, "EIA %s" % url, lambda url=url: sources.eia_monthly(url)) for k, url in EIA_MONTHLY.items()]
    others += [(k, "Cboe %s" % n, lambda n=n: sources.cboe_index(n)) for k, n in CBOE.items()]
    others += [(k, "BoJ %s" % t, lambda t=t, code=code: sources.boj_series(t, code)) for k, (t, code) in BOJ.items()]
    others += [(("cot_" + k), "CFTC %s" % m[1], lambda m=m: sources.cftc(m[0], m[1], "2023-01-01")) for k, m in COT_MARKETS.items()]
    others += [
        ("dix", "SqueezeMetrics DIX", sources.dix),
        ("crypto_fng", "alternative.me crypto fear and greed", sources.crypto_fng),
        ("aaii", "AAII survey page", sources.aaii),
        ("finra", "FINRA margin statistics", sources.finra_margin),
        ("bills_share", "Treasury FiscalData MSPD", sources.fiscaldata_bills_share),
        ("spx_pe", "multpl S&P 500 P/E", lambda: sources.multpl("s-p-500-pe-ratio")),
        ("mmf", "ICI money market funds", sources.ici_mmf),
        ("cpi_nowcast", "Cleveland Fed nowcast", sources.cleveland_nowcast),
        # v4: the calendar feeds
        ("ff_cal", "Forex Factory calendar", sources.ff_calendar),
        ("fomc_cal", "FOMC calendar", sources.fomc_calendar),
        ("ecb_cal", "ECB meeting calendar", sources.ecb_calendar),
        ("boj_cal", "BoJ meeting calendar", sources.boj_calendar),
        ("bls_empsit", "BLS payrolls release dates", lambda: sources.bls_release_dates("empsit")),
        ("bls_cpi", "BLS CPI release dates", lambda: sources.bls_release_dates("cpi")),
        ("td_upcoming", "TreasuryDirect upcoming auctions", sources.treasury_upcoming),
        ("spx_chain", "Cboe SPX option chain", sources.cboe_chain),
    ]
    for k, label, fn in others:
        try:
            D[k] = fn()
        except Exception as e:      # noqa: BLE001
            errors.append("%s (%s): %s" % (label, k, e))
        nap(0.2)
    log("fetched %d series, %d errors" % (len([k for k in D if k != "ff12_sym"]), len(errors)))
    return D, errors


def fetch_putcall(prev_state, today, log, errors):
    """Cboe daily put/call ratios: one JSON per session. Seeds a year on the first run, then only the days
    the log is missing. Holidays come back as errors from Cboe and are skipped."""
    hist = dict(((prev_state or {}).get("history", {}) or {}).get("pc", {}))
    end = dt.date.fromisoformat(today)
    start = end - dt.timedelta(days=(370 if not hist else 14))
    day, fetched, misses = start, 0, 0
    while day <= end:
        d = day.isoformat()
        if day.weekday() < 5 and d not in hist:
            try:
                hist[d] = sources.cboe_daily_options(d)
                fetched += 1
            except Exception:       # noqa: BLE001, a holiday or a not-yet-published day
                misses += 1
            nap(0.2)
        day += dt.timedelta(days=1)
    log("put/call: %d sessions fetched, %d skipped, %d logged" % (fetched, misses, len(hist)))
    return {d: hist[d] for d in sorted(hist)[-900:]}


def fetch_fomc_history(D, prev_state, today, log, errors):
    """The Fed's historical pages for the years the calendar page and the state do not cover (2011 on), once."""
    have = set(((prev_state or {}).get("history", {}).get("fomc") or {}).keys())
    have |= set(m["start"][:4] for m in D.get("fomc_cal") or [])
    out, first = {}, int(today[:4]) - 1
    for year in range(2011, first + 1):
        if str(year) in have:
            continue
        try:
            out[str(year)] = sources.fomc_history(year)
        except Exception as e:      # noqa: BLE001
            errors.append("FOMC history %d: %s" % (year, e))
        nap(0.3)
    if out:
        D["fomc_hist"] = out
        log("FOMC history: %d year(s) fetched" % len(out))


def fetch_members(log, errors):
    """Holdings of the SPDR funds used for breadth, then six months of closes for every member once."""
    holdings = {}
    for fund in HOLDINGS:
        try:
            holdings[fund] = [h["ticker"] for h in sources.ssga_holdings(fund)]
        except Exception as e:      # noqa: BLE001
            errors.append("SSGA holdings %s: %s" % (fund, e))
        nap(0.2)
    tickers = sorted(set(t for lst in holdings.values() for t in lst if t and t.replace(".", "").replace("-", "").isalnum()))
    prices, failed = {}, 0
    for t in tickers:
        sym = t.replace(".", "-")
        try:
            prices[t] = sources.yahoo(sym, "6mo")["adj"]
        except Exception:           # noqa: BLE001
            failed += 1
        nap(0.2)
    log("members: %d funds, %d tickers, %d without prices" % (len(holdings), len(tickers), failed))
    if failed > len(tickers) * 0.3:
        errors.append("members: %d of %d tickers failed" % (failed, len(tickers)))
    return {fund: [prices[t] for t in lst if t in prices] for fund, lst in holdings.items()}


def carry_forward(new, prev, label):
    """Keys the previous file had and this run lacks are kept, marked stale."""
    kept = 0
    for section in ("cells", "rank", "meta", "v2"):
        old = (prev or {}).get(section) or {}
        cur = new.setdefault(section, {})
        for k, v in old.items():
            if k not in cur:
                v = dict(v)
                if section != "meta":
                    v["stale"] = v.get("stale") or label
                cur[k] = v
                kept += 1
    return kept


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("data", "latest.json"))
    args = ap.parse_args(argv)

    def log(msg):
        print(msg, file=sys.stderr, flush=True)

    now = dt.datetime.now(BKK)
    D, errors = fetch_all(log)
    if len(D) < 10:
        log("too little data fetched; leaving the previous file in place")
        for e in errors:
            log("  " + e)
        return 1
    state_path = os.path.join(os.path.dirname(args.out) or ".", "state.json")
    changes_path = os.path.join(os.path.dirname(args.out) or ".", "changes.json")
    briefs_path = os.path.join(os.path.dirname(args.out) or ".", "briefs.json")
    prev_state = ch.load(state_path)
    fetch_fomc_history(D, prev_state, now.date().isoformat(), log, errors)
    members = fetch_members(log, errors)
    o = render.Out()
    render.render(D, o)
    errors += o.errors

    # v2: regime, detector, conditions, state and the change log
    today = (D["spy"]["adj"][-1][0] if "spy" in D else now.date().isoformat())
    try:
        pc = fetch_putcall(prev_state, today, log, errors)
        prev_state = dict(prev_state or {})
        prev_state["history"] = dict(prev_state.get("history", {}), pc=pc)
    except Exception as e:          # noqa: BLE001
        errors.append("put/call log: %s" % e)
    V = None
    try:
        V = v2.run(D, members, o.rank, prev_state, today, now.isoformat(timespec="minutes"))
        render.render_v2(V, o, now)
    except Exception as e:          # noqa: BLE001
        import traceback
        errors.append("v2: %s: %s" % (type(e).__name__, e))
        log(traceback.format_exc())
    # v4: the calendar, event studies, implied moves, the surprise log and the briefs
    V4 = None
    try:
        V4 = v4.run(D, V["state"] if V else prev_state, now.isoformat(timespec="minutes"), v4.load_briefs(briefs_path))
        render.render_v4(V4, o, now, V["v3"]["markets"] if V else {})
        if V:
            V["state"]["history"] = V4["history"]
            V["state"]["v4"] = V4["state"]
        log("calendar: %d events, %d tier-1 inside five days, %d surprise(s) resolved, implied moves for %d sessions" % (
            len(V4["events"]), len(V4["state"]["tier1_soon"]), len(V4["new_surprises"]), V4["implied"]["n"]))
    except Exception as e:          # noqa: BLE001
        import traceback
        errors.append("v4: %s: %s" % (type(e).__name__, e))
        log(traceback.format_exc())
    if V:
        t = now.isoformat(timespec="minutes")
        new = ch.diff_states(V["prev_for_diff"], V["state"], t) + ch.near_flips(V["state"], t)
        old_log = (ch.load(changes_path) or {}).get("changes", [])
        if V["first_run"]:
            new = [ch.entry(t, "fyi", "regime", "#regime", "State log started: alerts fire from the next run on, once a state has held for three closes.", "init")] + ch.near_flips(V["state"], t)
        new += ch.calendar_entries(V4, t)
        merged = ch.merge(old_log, new, t)
        ch.save(changes_path, {"asOf": t, "asOfLabel": now.strftime("%-d %b %Y, %H:%M BKK"), "changes": merged})
        ch.save(state_path, V["state"])
        log("state: %d themes, %d new change(s), %d in the 90-day log" % (len(V["detector"]), len(new), len(merged)))

    prev = None
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:           # noqa: BLE001
            prev = None
    payload = {
        "schema": 1,
        "asOf": now.isoformat(timespec="minutes"),
        "asOfLabel": now.strftime("%-d %b %Y, %H:%M BKK"),
        "cells": o.cells, "meta": o.meta, "rank": o.rank, "v2": o.v2,
        "errors": errors,
    }
    kept = carry_forward(payload, prev, (prev or {}).get("asOfLabel") or "an earlier run")
    payload["counts"] = {"cells": len(o.cells), "rank": len(o.rank), "stale": kept, "errors": len(errors)}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    log("wrote %s: %d cells, %d ranking rows, %d carried forward, %d errors" % (args.out, len(o.cells), len(o.rank), kept, len(errors)))
    for e in errors:
        log("  " + e)
    return 0


if __name__ == "__main__":
    sys.exit(main())

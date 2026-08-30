"""v4 pipeline: section 5. The event list for the next ten weeks from the feeds and the rules, the event studies,
the options-implied move per event session, the surprise log and index, the mechanical dates for the calendar
effects table, the reviewed briefs, and the state the change log reads (tier-1 events inside five days, tier-1
surprises beyond one sigma).
"""
import datetime as dt
import json
import os

from . import calendar as cal
from . import events as ev

SOON_DAYS = 5


def today_et(now_iso):
    """The Eastern date of the run (the run is 05:30 Bangkok, which is the previous evening in New York)."""
    t = dt.datetime.fromisoformat(now_iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone(dt.timedelta(hours=7)))
    u = t.astimezone(dt.timezone.utc)
    return (u + dt.timedelta(hours=cal.utc_offset("ET", u.date()))).date().isoformat()


def load_briefs(path):
    """data/briefs.json: {'week': {'from', 'to', 'text', 'reviewed'}, 'events': {id: {'expect', 'stronger', 'weaker', 'reviewed'}}}."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:       # noqa: BLE001, a broken brief file must not sink the run
        return {}


def fomc_meetings(D, history):
    """Meetings by year: the calendar page is authoritative for the years it shows, the historical pages fill the
    earlier years once and stay in the state."""
    by_year = {y: list(v) for y, v in (history.get("fomc") or {}).items()}
    page = D.get("fomc_cal") or []
    for y in set(m["start"][:4] for m in page):
        by_year[y] = [m for m in page if m["start"][:4] == y]
    for y, lst in (D.get("fomc_hist") or {}).items():
        by_year[y] = lst
    return by_year


def run(D, prev_state, now_iso, briefs=None):
    today = today_et(now_iso)
    prev_state = prev_state or {}
    history = dict(prev_state.get("history", {}))
    by_year = fomc_meetings(D, history)
    history["fomc"] = by_year
    fomc_all = sorted((m for lst in by_year.values() for m in lst), key=lambda m: m["start"])

    ff = D.get("ff_cal") or []
    ff_rows = cal.ff_events(ff)
    window = (min(x["date"][:10] for x in ff), max(x["date"][:10] for x in ff)) if ff else (None, None)
    sched = cal.scheduled_events(today, fomc_all, D.get("ecb_cal"), D.get("boj_cal"), D.get("bls_empsit"), D.get("bls_cpi"), D.get("td_upcoming"))
    events = [e for e in cal.merge(ff_rows, sched, window) if e["date"] >= today]

    fomc_dates = [m["end"] for m in fomc_all if m.get("scheduled")]
    studies = {}
    for key, dates in (("nfp", D.get("bls_empsit")), ("cpi", D.get("bls_cpi")), ("fomc", fomc_dates)):
        if dates:
            studies[key] = ev.study(dates, D, today)

    chain = D.get("spx_chain")
    spans = ev.session_variances(chain) if chain else {}
    base = ev.baseline(spans) if spans else None
    for e in events:
        e["session"] = ev.session_for(e)
        e["implied"] = ev.implied_move(spans, e["session"]) if (spans and e["kind"] in ("release", "cb", "auction")) else None

    log, new = ev.update_log(history.get("surprises", {}), ff_rows, D, today)
    history["surprises"] = log
    history["surprises_since"] = history.get("surprises_since") or today
    idx = dict(ev.surprise_index(log, today), since=history["surprises_since"])

    briefs = briefs or {}
    for e in events:
        b = (briefs.get("events") or {}).get(e["id"])
        e["brief"] = b if (b and any(b.get(k) for k in ("expect", "stronger", "weaker"))) else None
    rng = cal.ranges(today)
    week = briefs.get("week") or None
    if week and not (week.get("text") and week.get("from") and week.get("to") and week["from"] <= rng["week"][1] and week["to"] >= rng["week"][0]):
        week = None

    t0 = dt.date.fromisoformat(today)

    def soon(e):
        return 0 <= (dt.date.fromisoformat(e["date"]) - t0).days <= SOON_DAYS
    state = {"date": today,
             "tier1_soon": [e["id"] for e in events if e["tier"] == 1 and soon(e)],
             "tier2_soon": [e["id"] for e in events if e["tier"] == 2 and soon(e)],
             "surprises": [{"series": k, "date": d, "z": x["z"], "a": x["a"], "f": x["f"]} for k, d, x in new]}
    feeds = {k: (k in D) for k in ("ff_cal", "fomc_cal", "ecb_cal", "boj_cal", "bls_empsit", "bls_cpi", "td_upcoming", "spx_chain")}
    return {"today": today, "events": events, "ranges": rng, "studies": studies,
            "implied": {"base": base, "asof": chain.get("quote_date") if chain else None, "spot": chain.get("spot") if chain else None, "n": len(spans)},
            "surprise": idx, "mech": cal.mechanical_next(today), "week": week, "state": state, "history": history,
            "ff_window": window, "feeds": feeds, "new_surprises": new}

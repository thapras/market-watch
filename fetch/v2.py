"""v2 pipeline: the regime read, the rotation detector, sectors and the rotation map, seasonality, the
ranking's conditions score, and the run-to-run state that alerts are diffed against.

State rules: states need three consecutive daily runs to flip; a same-day rerun does not count twice;
the first run takes the raw states as they are (there is nothing to confirm against) and logs no alerts.
"""
import datetime as dt

from . import compute as c
from . import conditions as cond
from . import detector as det
from . import regime as rg
from . import v3
from .catalog import RANKING, ROTATION_MAP, SEASONALITY, SECTORS, THEMES

COND_NAMES = {"rs": "Relative strength", "flow": "Flows", "breadth": "Breadth", "seasonal": "Seasonal", "macro": "Macro"}
CARD_STATES = ("early", "developing", "confirmed", "fading", "watch_exit", "watch")


def adj(D, k):
    return D[k]["adj"] if k in D and D[k].get("adj") else None


def quadrant_history(D):
    g = rg.composite_series(rg.inputs_growth(D))
    i = rg.composite_series(rg.inputs_inflation(D))

    def at(date):
        hg, hi = det.at_or_before(g, date), det.at_or_before(i, date)
        if hg and hi and hg[1] is not None and hi[1] is not None:
            return rg.quadrant(hg[1], hi[1])[0]
        return None
    return at


def level_for(entry):
    return "2.5" if entry >= 2.5 else "2.0" if entry >= 2 else "1.0" if entry >= 1 else None


def theme_run(D, key, name, tk, t_adj, spy, comps, rule, members, today, prev, first_run, qat, seasonal_relative=True, extra=None):
    """One detector row. extra: pre-computed conditions that replace the standard ones (the cash card)."""
    sig, text, meta = {}, {}, {}
    line = det.rs_line(t_adj, spy) if t_adj and spy else []
    states = det.rs_states(line) if line else []
    rs = det.rs_signal(states) if states else {"value": 0, "since": None, "sessions": None}
    asof = t_adj[-1][0] if t_adj else today
    if extra and "rs" in extra:
        sig["rs"], text["rs"] = extra["rs"]
    elif rs["value"]:
        sig["rs"] = rs["value"]
        since = rs["since"] or asof
        text["rs"] = ("%s to S&P ratio above its 50-day since %s" if rs["value"] == 1 else "%s to S&P ratio below its 50-day since %s") % (tk, _dl(since))
        meta["rs_since"], meta["rs_sessions"] = since, rs["sessions"]
    else:
        sig["rs"], text["rs"] = None, "not enough history for the 50-day relative strength line"
    if extra and "flow" in extra:
        sig["flow"], text["flow"] = extra["flow"]
    else:
        sig["flow"], text["flow"] = None, "no free share-count feed yet, not scored"
    if extra and "breadth" in extra:
        sig["breadth"], text["breadth"] = extra["breadth"]
    elif members:
        b = det.breadth_signal(det.breadth_series(members, spy, 50, 25))
        if b["value"] is None:
            sig["breadth"], text["breadth"] = None, "members fetched but too few with history, not scored"
        else:
            sig["breadth"] = b["value"]
            meta["breadth"] = round(b["level"])
            lo, hi = min(b["low"], b["level"]), max(b["high"], b["level"])
            text["breadth"] = {1: "%d%% of members above the 50-day, up from %d%% inside four weeks (thrust)" % (b["level"], b["low"]),
                               0: "%d%% of members above the 50-day; four-week range %d to %d%% (a thrust needs under 35%% to over 60%%)" % (b["level"], lo, hi),
                               -1: "%d%% of members above the 50-day, down from %d%% in four weeks" % (b["level"], b["high"])}[b["value"]]
    else:
        sig["breadth"], text["breadth"] = None, "no free holdings file for this fund yet, not scored"
    if extra and "seasonal" in extra:
        sig["seasonal"], text["seasonal"] = extra["seasonal"]
    else:
        w = det.seasonal_window(det.Dated(t_adj), det.Dated(spy) if seasonal_relative else None, today, relative=seasonal_relative) if t_adj else {"avg": None}
        if w["avg"] is None:
            sig["seasonal"], text["seasonal"] = None, "not enough years for the eight-week window"
        else:
            sig["seasonal"] = w["value"]
            meta["seasonal"] = {"avg": round(w["avg"], 1), "hit": round(w["hit"]), "n": w["n"]}
            rel = "relative" if seasonal_relative else "absolute"
            text["seasonal"] = {1: "next 8 weeks %+.1f%% %s on average, hit rate %d%% over %d years",
                                0: "next 8 weeks %+.1f%% %s on average, hit rate %d%% over %d years, bar is 60%%",
                                -1: "next 8 weeks %+.1f%% %s on average, hit rate %d%% over %d years, a weak window"}[w["value"]] % (w["avg"], rel, round(w["hit"]), w["n"])
    if extra and "macro" in extra:
        sig["macro"], text["macro"] = extra["macro"]
    elif rule:
        mv, readings = det.macro_at(comps, rule, asof)
        if mv is None:
            sig["macro"], text["macro"] = None, "driver series missing today, not scored"
        else:
            sig["macro"] = mv
            joined = ", ".join(readings)
            text["macro"] = {1: "%s in a month (%s)", 0: "mixed: %s in a month (needs %s)", -1: "against: %s in a month (needs %s)"}[mv] % (joined, det.MACRO_LABEL[rule])
    else:
        sig["macro"], text["macro"] = None, "no driver defined for this theme on the page, not scored"
    entry, lost, count = det.score(sig)
    bt = det.backtest(t_adj, spy, states, comps, rule, qat) if (t_adj and spy and states and not extra) else {}
    ev_ok = det.evidence_ok(bt) if bt else False
    raw = det.raw_state(entry, lost, (prev or {}).get("state"), ev_ok)
    st = det.confirm_state(prev, raw, today, first_run)
    if first_run and meta.get("rs_since") and sig.get("rs") in (1, -1):
        st["since"] = st["raw_since"] = meta["rs_since"]          # the first run has no history: date the state from the RS cross
    on = [COND_NAMES[k] for k, v in sig.items() if v == 1]
    lostn = [COND_NAMES[k] for k, v in sig.items() if v == -1]
    off = [COND_NAMES[k] for k, v in sig.items() if v == 0]
    row = {"key": key, "name": name, "tk": tk, "signals": sig, "text": text, "meta": meta, "entry": entry, "lost": lost, "count": count,
           "history_from": max("2011", (t_adj[0][0][:4] if t_adj else "2011")),
           "on": on, "off": off, "lostn": lostn, "backtest": bt, "evidence_ok": ev_ok, "level": level_for(entry), "asof": asof}
    row.update(st)
    row["changed"] = st["since"]
    return row


def _dl(date):
    d = dt.date.fromisoformat(date)
    return "%d %s" % (d.day, ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.month - 1])


def cash_card(D, spy, comps, today, prev, first_run, qat, history):
    """Cash leaving the sidelines: money market outflows, destination flows (no feed), bill yields, breadth, season."""
    mm = history.get("mmf", {})
    dates = sorted(mm)
    chg = [mm[dates[i]] - mm[dates[i - 1]] for i in range(1, len(dates))][-3:]
    if len(chg) < 3:
        flow = (None, "money market assets: %d week%s of history logged, three are needed" % (len(dates), "" if len(dates) == 1 else "s"))
    elif all(x < 0 for x in chg):
        flow = (1, "three weekly money market outflows in a row (%s)" % ", ".join("%+.1f" % x for x in chg))
    elif all(x > 0 for x in chg):
        flow = (-1, "three weekly money market inflows in a row, cash is building (%s)" % ", ".join("%+.1f" % x for x in chg))
    else:
        flow = (0, "money market flows mixed over three weeks (%s)" % ", ".join("%+.1f" % x for x in chg))
    dest = (None, "US equity fund flows: no free feed yet, not scored")
    rsp, spyc = adj(D, "rsp"), spy
    if rsp and spyc:
        r = [(d, a / b) for d, a, b in c.align(rsp, spyc) if b]
        c40, c20 = c.pct(r, 40), c.pct(r, 20)
        if c40 is not None and c40 > 0:
            br = (1, "equal-weight beating cap-weight for 8 weeks (%+.1f%%)" % c40)
        elif c20 is not None and c20 > 0:
            br = (0, "equal-weight beating cap-weight for 4 weeks (%+.1f%%), needs 8" % c20)
        elif c40 is not None and c40 < -2:
            br = (-1, "cap-weight leading equal-weight by %.1f%% over 8 weeks, a narrowing tape" % -c40)
        else:
            br = (0, "equal-weight to cap-weight flat over 8 weeks (%+.1f%%)" % (c40 or 0))
    else:
        br = (None, "equal-weight to cap-weight ratio unavailable")
    row = theme_run(D, "cash", "Cash leaving the sidelines", "money market funds", spy, spy, comps, "cash", None, today, prev, first_run, qat,
                    seasonal_relative=False, extra={"rs": (None, "not a relative strength theme"), "flow": flow, "breadth": br})
    row["text"]["flow"] = flow[1]
    row["destination"] = dest[1]
    return row


def run(D, members, rank, prev_state, today, now_iso):
    spy = adj(D, "spy")
    netliq = rg.netliq_series(D)
    comps = det.macro_components(D, netliq)
    regime = rg.compute(D)
    qat = quadrant_history(D)
    prev_state = prev_state or {}
    same_day = prev_state.get("date") == today
    base_det = prev_state.get("yesterday") if same_day and prev_state.get("yesterday") is not None else prev_state.get("detector", {})
    first_run = not base_det                      # nothing to confirm against or to diff: the first day (reruns included)
    history = dict(prev_state.get("history", {}))
    if "mmf" in D:                                   # today's money market reading joins the series before the cash card reads it
        m = dict(history.get("mmf", {}))
        m[D["mmf"]["date"]] = D["mmf"]["total"]
        history["mmf"] = {d: m[d] for d in sorted(m)[-60:]}

    detector = {}
    for th in THEMES:
        t_adj = adj(D, th["y"])
        if not t_adj or not spy:
            continue
        mem = members.get(th["members"][1]) if th.get("members") else None
        detector[th["key"]] = theme_run(D, th["key"], th["name"], th["tk"], t_adj, spy, comps, th.get("macro"), mem, today,
                                        base_det.get(th["key"]), first_run, qat)
    if spy:
        detector["cash"] = cash_card(D, spy, comps, today, base_det.get("cash"), first_run, qat, history)

    sectors = {}
    for key, name in SECTORS:
        s_adj = adj(D, key)
        if not s_adj or not spy:
            continue
        pt = det.rotation_point(s_adj, spy)
        line = det.rs_line(s_adj, spy)
        rs = det.rs_signal(det.rs_states(line)) if line else {"value": 0, "since": None, "sessions": None}
        b = det.breadth_signal(det.breadth_series(members.get(key, []), spy, 50, 25)) if members.get(key) else {"value": None, "level": None}
        x = [v for _, v in D[key]["close"]]
        sectors[key] = {"name": name, "rs": round(pt["rs"], 1) if pt else None, "mom": round(pt["mom"], 1) if pt else None,
                        "quadrant": det.quadrant_of(pt["rs"], pt["mom"]) if pt else None, "rs_signal": rs,
                        "breadth": round(b["level"]) if b.get("level") is not None else None, "breadth_value": b.get("value"),
                        "ma": (c.above_below(x, 50), c.above_below(x, 200))}

    rmap = []
    for mkey, label, ykey in ROTATION_MAP:
        a = adj(D, ykey)
        if not a or not spy:
            continue
        pts = [det.rotation_point(a, spy, at) for at in (15, 10, 5, 0)]
        if any(p is None for p in pts):
            continue
        st = detector.get(mkey, {}).get("state") or detector.get({"xlp": "staples"}.get(mkey, ""), {}).get("state")
        hot = st in ("early", "developing", "confirmed", "fading", "watch_exit")
        rmap.append({"key": mkey, "label": label, "rs": round(pts[-1]["rs"], 1), "mom": round(pts[-1]["mom"], 1),
                     "tail": [[round(p["rs"], 2), round(p["mom"], 2)] for p in pts[:-1]], "hot": hot, "state": st,
                     "quadrant": det.quadrant_of(pts[-1]["rs"], pts[-1]["mom"])})

    season = []
    for name, ykey, rel in SEASONALITY:
        a = adj(D, ykey)
        if not a:
            continue
        prof = det.monthly_profile(a, 20, spy if rel else None)
        season.append({"name": name, "cells": prof, "years": max(x["n"] for x in prof)})

    V3 = v3.run(D, dict(prev_state, history=history), today)
    history = V3["history"]
    ranking_series = {key: adj(D, ykey) for key, ykey, _ in RANKING}
    cs = cond.compute(D, regime, ranking_series, today, V3["p_pillar"])
    ranking = {}
    names = dict((k, k) for k in cs)
    for key, r in cs.items():
        price = (rank.get(key) or {}).get("price")
        ranking[key] = {"cond": r["cond"], "pillars": r["pillars"], "detail": r["detail"], "n": r["n"], "price": price,
                        "read": cond.read(r["cond"], price) if (r["cond"] is not None and price is not None) else None}
    # week-on-week change from the score history
    hist_scores = history.get("scores", {})
    week_ago = (dt.date.fromisoformat(today) - dt.timedelta(days=7)).isoformat()
    ref = None
    for d in sorted(hist_scores):
        if d <= week_ago:
            ref = d
    for key, r in ranking.items():
        old = (hist_scores.get(ref) or {}).get(key) if ref else None
        r["cond_wow"] = round(r["cond"] - old[0], 1) if (old and old[0] is not None and r["cond"] is not None) else None
        r["price_wow"] = round(r["price"] - old[1], 1) if (old and old[1] is not None and r["price"] is not None) else None
        r["wow_ref"] = ref
    hist_scores[today] = {k: [r["cond"], r["price"]] for k, r in ranking.items()}
    history["scores"] = {d: hist_scores[d] for d in sorted(hist_scores)[-30:]}
    state = {
        "asOf": now_iso, "date": today,
        "detector": {k: {kk: v[kk] for kk in ("state", "since", "raw", "raw_count", "raw_since", "name", "count", "entry", "lost", "on", "lostn", "off")} for k, v in detector.items()},
        "yesterday": base_det if same_day else prev_state.get("detector", {}),
        "regime": {"flags": regime["flags"], "composites": {k: {"value": v["value"]} for k, v in regime["composites"].items()}},
        "sectors": {k: {"name": v["name"], "quadrant": v["quadrant"], "rs": v["rs"], "mom": v["mom"]} for k, v in sectors.items()},
        "ranking": {k: {"name": _rank_name(k), "read": v["read"], "cond": v["cond"], "price": v["price"]} for k, v in ranking.items()},
        "history": history, "notified": prev_state.get("notified", ""),
        "v3": V3["state"],
    }
    prev_for_diff = None if first_run else {"regime": prev_state.get("regime", {}), "detector": base_det, "sectors": prev_state.get("sectors", {}), "ranking": prev_state.get("ranking", {})}
    if same_day and not first_run:
        # a rerun on the same day: keep the day's opening states as the comparison base for tomorrow
        state["yesterday"] = base_det
    if prev_for_diff is not None:
        prev_for_diff["v3"] = prev_state.get("v3", {})
    return {"regime": regime, "detector": detector, "sectors": sectors, "map": rmap, "seasonality": season, "ranking": ranking,
            "v3": V3, "state": state, "prev_for_diff": prev_for_diff, "first_run": first_run}


RANK_NAMES = {"gold_miners": "Gold miners", "em_ex_china": "Emerging markets ex China", "us_small": "US small caps", "banks": "Banks and financials",
              "copper": "Copper and industrial metals", "gold": "Gold", "reits": "Real estate (REITs)", "japan": "Japan equities", "bitcoin": "Bitcoin",
              "silver": "Silver and silver miners", "europe": "Europe equities", "thailand": "Thailand (SET)", "ust10": "US 10-year Treasuries",
              "us_hy": "US high yield credit", "us_large": "US large caps (S&P 500)", "semis": "Semiconductors and mega-cap tech", "energy": "Energy", "cash": "Cash (T-bills)"}


def _rank_name(k):
    return RANK_NAMES.get(k, k)

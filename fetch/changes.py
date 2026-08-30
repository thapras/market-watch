"""The state store (data/state.json) and the state-change log (data/changes.json) behind the What changed strip.

Alerts fire on state changes only, never on levels. Tiers: must read (regime flags, Confirmed or Fading in
the detector, a ranking row entering or leaving Aligned, a divergence alert, a tier-1 surprise beyond one
sigma), notable (other detector and ranking changes, sector quadrant changes, the softer flags, tier-1 events
inside five days), FYI (near a flip, tier-2 events inside five days). One entry per subject per week; ninety
days kept, which is also the tuning log.
"""
import datetime as dt
import json
import os

KEEP_DAYS = 90
DEDUPE_DAYS = 7
MAX_FYI = 6
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

STATE_WORDS = {"none": "no state", "watch_exit": "Watch (exit)", "watch": "Watch", "early": "Early",
               "developing": "Developing", "confirmed": "Confirmed", "fading": "Fading"}
STATE_RANK = {"none": 0, "watch_exit": 0, "watch": 1, "early": 2, "developing": 3, "confirmed": 4, "fading": -1}


def load(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:       # noqa: BLE001
            return None
    return None


def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def _label(iso):
    d = dt.date.fromisoformat(iso[:10])
    return "%d %s" % (d.day, MONTHS[d.month - 1])


def entry(t, tier, sec, href, text, key):
    return {"t": t, "d": _label(t), "tier": tier, "sec": sec, "href": href, "text": text, "key": key}


def diff_states(prev, cur, t):
    """Compare the previous run's states with this run's. prev None means the first run: no alerts."""
    out = []
    if not prev:
        return out
    P, C = prev.get("regime", {}).get("flags", {}), cur.get("regime", {}).get("flags", {})
    comps = cur.get("regime", {}).get("composites", {})
    MUST = {"liquidity": ("liq", "Liquidity"), "cost": ("cost", "Cost of money"), "risk": ("risk", "Risk appetite"), "credit": (None, "Credit stress")}
    for flag, (ck, name) in MUST.items():
        if P.get(flag) and C.get(flag) and P[flag] != C[flag]:
            v = comps.get(ck, {}).get("value") if ck else None
            out.append(entry(t, "must", "regime", "#regime", "%s flag changed: %s to %s%s." % (name, P[flag], C[flag], " (composite %+.1f)" % v if v is not None else ""), "flag." + flag))
    if P.get("cycle") and C.get("cycle") and P["cycle"] != C["cycle"]:
        out.append(entry(t, "must", "regime", "#regime", "Cycle moved from %s to %s (%s)." % (P["cycle"], C["cycle"], C.get("cycle_detail", "")), "flag.cycle"))
    for flag, name in (("breadth", "Breadth"), ("momentum", "Momentum factor"), ("dollar", "Dollar")):
        if P.get(flag) and C.get(flag) and P[flag] != C[flag]:
            out.append(entry(t, "note", "regime", "#regime", "%s flag changed: %s to %s." % (name, P[flag], C[flag]), "flag." + flag))
    # detector themes
    PD, CD = prev.get("detector", {}), cur.get("detector", {})
    for key, cd in CD.items():
        pd = PD.get(key)
        if not pd or pd.get("state") == cd.get("state"):
            continue
        old, new = pd.get("state", "none"), cd.get("state", "none")
        name = cd.get("name", key)
        on = ", ".join(cd.get("on", [])) or "no condition on"
        if new == "confirmed" or new == "fading":
            text = "%s moved to %s (%d of 5): %s." % (name, STATE_WORDS[new], cd.get("count", 0), on) if new == "confirmed" else \
                   "%s left %s: %s. Now Fading." % (name, STATE_WORDS[old], ", ".join(cd.get("lostn", [])) or "conditions lost")
            out.append(entry(t, "must", "rotation", "#rotation", text, "theme." + key))
        else:
            out.append(entry(t, "note", "rotation", "#rotation", "%s moved from %s to %s (%d of 5): %s." % (name, STATE_WORDS[old], STATE_WORDS[new], cd.get("count", 0), on), "theme." + key))
    # sector quadrants
    PS, CS = prev.get("sectors", {}), cur.get("sectors", {})
    for key, cs in CS.items():
        ps = PS.get(key)
        if ps and ps.get("quadrant") and cs.get("quadrant") and ps["quadrant"] != cs["quadrant"]:
            tier = "note" if "Leading" in (ps["quadrant"], cs["quadrant"]) else "fyi"
            out.append(entry(t, tier, "markets", "#markets", "%s moved from %s to %s on the rotation map (relative strength %.1f, momentum %.1f)." % (cs.get("name", key), ps["quadrant"], cs["quadrant"], cs.get("rs", 0), cs.get("mom", 0)), "sector." + key))
    # section 6: divergence alerts (two consecutive weekly readings beyond the line), crowd flag, CTA flips
    P3, C3 = prev.get("v3", {}) or {}, cur.get("v3", {}) or {}
    names = {"spx": "S&P 500", "semis": "Semiconductors", "gold": "Gold", "silver": "Silver", "crude": "Crude oil", "ust10": "10Y Treasuries",
             "dxy": "US dollar", "btc": "Bitcoin", "copper": "Copper", "ndx": "Nasdaq 100", "wti": "WTI crude"}
    for key, st in (C3.get("alerts") or {}).items():
        old = (P3.get("alerts") or {}).get(key)
        if old == st:
            continue
        if st:
            out.append(entry(t, "must", "sentiment", "#sentiment", "Divergence alert: %s crossed %s1.5 for a second week (%s)." % (
                names.get(key, key), "+" if st == "up" else "-", "the crowd is fearful, smart money is buying" if st == "up" else "the crowd is long, smart money is leaving"), "div." + key))
        else:
            out.append(entry(t, "note", "sentiment", "#sentiment", "Divergence alert cleared: %s is back inside the 1.5 band." % names.get(key, key), "div." + key))
    if P3.get("crowd") and C3.get("crowd") and P3["crowd"] != C3["crowd"]:
        out.append(entry(t, "note", "regime", "#regime", "Crowd flag changed: %s to %s." % (P3["crowd"], C3["crowd"]), "flag.crowd"))
    for key, sig in (C3.get("cta") or {}).items():
        old = (P3.get("cta") or {}).get(key)
        if old is not None and old != sig:
            out.append(entry(t, "note", "sentiment", "#sentiment", "CTA trend signal flipped to %s in %s." % ("long" if sig == 1 else "short", names.get(key, key)), "cta." + key))
    # ranking reads
    PR, CR = prev.get("ranking", {}), cur.get("ranking", {})
    for key, cr in CR.items():
        pr = PR.get(key)
        if not pr or not pr.get("read") or not cr.get("read") or pr["read"] == cr["read"]:
            continue
        tier = "must" if ("Aligned" in pr["read"] or "Aligned" in cr["read"]) else "note"
        out.append(entry(t, tier, "regime", "#ranking", "%s read changed: %s to %s (conditions %+.1f, price %+.1f)." % (cr.get("name", key), pr["read"], cr["read"], cr.get("cond") or 0, cr.get("price") or 0), "rank." + key))
    return out


def near_flips(cur, t):
    """FYI entries: setups within half a condition of the next detector state, ranking scores near the band."""
    out = []
    for key, cd in cur.get("detector", {}).items():
        e, st = cd.get("entry", 0), cd.get("state", "none")
        nxt = {"none": (1, "Watch"), "watch_exit": (1, "Watch"), "watch": (2, "Early"), "early": (3, "Developing"), "developing": (4, "Confirmed")}.get(st)
        if nxt and 0 < nxt[0] - e <= 0.5 and cd.get("off"):
            out.append(entry(t, "fyi", "rotation", "#rotation", "Near a flip: %s sits at %.1f of 5; %s would move it to %s." % (cd.get("name", key), e, cd["off"][0], nxt[1]), "near." + key))
    for key, cr in cur.get("ranking", {}).items():
        for which in ("cond", "price"):
            v = cr.get(which)
            if v is not None and 0.3 <= abs(v) < 0.5:
                out.append(entry(t, "fyi", "regime", "#ranking", "Near a flip: %s %s score %+.1f is inside the 0.5 band; one more step %s changes the read from %s." % (cr.get("name", key), "conditions" if which == "cond" else "price", v, "up" if v > 0 else "down", cr.get("read", "Neutral")), "nearrank." + key))
                break
    return out[:MAX_FYI]


MAX_CAL_FYI = 4


def calendar_entries(V4, t):
    """Section 5 entries: tier-1 events inside five days (notable), tier-2 (FYI, capped), and a tier-1 surprise beyond
    one sigma on the run that resolves it (must read). Keys dedupe them for a week, so each fires once."""
    from . import calendar as cal
    out = []
    if not V4:
        return out
    by_id = {e["id"]: e for e in V4.get("events", [])}
    st = V4.get("state", {})

    def line(e):
        cons = "; ".join("%s %s" % (c["label"], c["forecast"].replace("K", "k")) for c in e.get("cons", []) if c.get("label") and c.get("forecast"))
        when = cal.day_label(e["date"]) + ((", " + e["time"] + " ET") if e.get("time") else (", " + e["time_text"].split(" / ")[0] if e.get("time_text") else ""))
        imp = ("; options price a %.1f%% S&P move" % e["implied"]) if e.get("implied") else ""
        return "Coming %s: %s%s%s." % (when, e["name"], (" (consensus " + cons + ")") if cons else "", imp)
    for eid in st.get("tier1_soon", []):
        e = by_id.get(eid)
        if e:
            out.append(entry(t, "note", "calendar", "#calendar", line(e), "cal." + eid))
    for eid in st.get("tier2_soon", [])[:MAX_CAL_FYI]:
        e = by_id.get(eid)
        if e:
            out.append(entry(t, "fyi", "calendar", "#calendar", line(e), "cal." + eid))
    for sp in st.get("surprises", []):
        spec = cal.SURPRISE.get(sp["series"])
        if not spec or spec["tier"] != 1 or sp.get("z") is None or abs(sp["z"]) <= 1.0:
            continue
        unit = spec["unit"]
        fmt = (lambda x: "%+.0fk" % x) if unit == "k" else (lambda x: "%.1f%%" % x) if unit == "%" else (lambda x: "%.2f%s" % (x, unit))
        out.append(entry(t, "must", "calendar", "#calendar", "%s surprise: %s against %s expected (%+.1f sigma)." % (spec["name"], fmt(sp["a"]), fmt(sp["f"]), sp["z"]),
                         "surprise.%s.%s" % (sp["series"], sp["date"])))
    return out


def merge(old, new, t):
    """Newest first, one entry per key inside DEDUPE_DAYS, nothing older than KEEP_DAYS."""
    cutoff = (dt.datetime.fromisoformat(t[:16]) - dt.timedelta(days=KEEP_DAYS)).isoformat()
    kept = [c for c in (old or []) if c.get("t", "") >= cutoff]
    recent = {}
    for c in kept:
        if c.get("key"):
            recent[c["key"]] = max(recent.get(c["key"], ""), c["t"])
    dedupe_cut = (dt.datetime.fromisoformat(t[:16]) - dt.timedelta(days=DEDUPE_DAYS)).isoformat()
    added = []
    for c in new:
        if c.get("key") and recent.get(c["key"], "") >= dedupe_cut:
            continue
        added.append(c)
    allc = added + kept
    allc.sort(key=lambda x: (x["t"], {"must": 0, "note": 1, "fyi": 2}[x["tier"]]), reverse=True)
    return allc

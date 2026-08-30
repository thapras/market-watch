"""Regime composites and flags (section 0 of the page, the read at a glance).

Four composites, each an equal-weighted average of three-year z-scores of the inputs the free feeds
cover. The page's explainer lists the inputs; the ones without a free feed (China credit impulse, ISM new
orders, Korea exports, the surprise index, ISM prices paid) are left out and the explainer says so.
Windows: daily inputs 756 sessions, weekly 156, monthly 36. Composites are clamped to plus or minus 3.
"""
import datetime as dt
import math

from . import compute as c


# ---------------------------------------------------------------- shared derived series
def netliq_series(D):
    """Fed balance sheet minus Treasury cash minus reverse repo, $B, weekly on the WALCL dates."""
    w, t, r = D["walcl"], D["tga"], D["rrp"]
    out = []
    for d, v in w:
        tv, rv = c.at_or_before(t, d), c.at_or_before(r, d)
        if tv and rv:
            out.append((d, v / 1000.0 - tv[1] / 1000.0 - rv[1]))
    return out


def month_end(date):
    d = dt.date.fromisoformat(date)
    return ((d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)).isoformat()


def big3_m2_usd(D):
    """US plus euro area plus Japan M2 in $T, monthly."""
    us, ez, jp = dict(D["m2"]), dict(D["ez_m2"]), D["jp_m2"]
    eur, jpy = D["eurusd"]["close"], D["usdjpy"]["close"]
    out = []
    for d, v in jp:
        fx, jf = c.at_or_before(eur, month_end(d)), c.at_or_before(jpy, month_end(d))
        if d in us and d in ez and fx and jf:
            out.append((d, us[d] / 1000.0 + ez[d] * fx[1] / 1e6 + v * 1e8 / jf[1] / 1e12))
    return out


def big3_assets_usd(D):
    """Fed plus ECB plus BoJ balance sheets in $T at month ends, on the BoJ dates."""
    boj, fed, ecb = D["boj_assets"], D["walcl"], D["ecb_assets"]
    eur, jpy = D["eurusd"]["close"], D["usdjpy"]["close"]
    out = []
    for d, v in boj:
        e = month_end(d)
        f, ec, fx, jp = c.at_or_before(fed, e), c.at_or_before(ecb, e), c.at_or_before(eur, e), c.at_or_before(jpy, e)
        if f and ec and fx and jp:
            out.append((d, f[1] / 1e6 + ec[1] * fx[1] / 1e6 + v * 1e8 / jp[1] / 1e12))
    return out


def yoy(s, k=12):
    return [(s[i][0], (s[i][1] / s[i - k][1] - 1.0) * 100.0) for i in range(k, len(s)) if s[i - k][1]]


def diff(s, k):
    return [(s[i][0], s[i][1] - s[i - k][1]) for i in range(k, len(s))]


def pct_change(s, k):
    return [(s[i][0], (s[i][1] / s[i - k][1] - 1.0) * 100.0) for i in range(k, len(s)) if s[i - k][1]]


def ratio(a, b):
    return [(d, x / y) for d, x, y in c.align(a, b) if y]


def invert(s):
    return [(d, -v) for d, v in s]


# ---------------------------------------------------------------- z-scores
def rolling_z(s, window, min_obs=None):
    """z-score of each value against the trailing window (inclusive), None until min_obs are available."""
    min_obs = min_obs or max(12, window // 3)
    out = []
    vals = [v for _, v in s]
    for i in range(len(s)):
        seg = vals[max(0, i - window + 1):i + 1]
        if len(seg) < min_obs:
            out.append((s[i][0], None))
            continue
        mean = sum(seg) / len(seg)
        var = sum((x - mean) ** 2 for x in seg) / (len(seg) - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        z = (vals[i] - mean) / sd if sd else 0.0
        out.append((s[i][0], max(-3.0, min(3.0, z))))
    return out


WINDOW = {"d": 756, "w": 156, "m": 36}


MAX_AGE = {"d": 10, "w": 21, "m": 75}      # how long an input stays usable after its date (publication lags)


def composite_series(inputs):
    """inputs: list of (series, freq). Returns the composite at every date of the first input, using each
    input's latest z at or before that date; None where fewer than two inputs are available."""
    from . import detector as det
    zs = [(rolling_z(s, WINDOW[f]), f) for s, f in inputs if s]
    if not zs:
        return []
    out = []
    for d, _ in zs[0][0]:
        vals = []
        for z, f in zs:
            hit = det.at_or_before(z, d)
            if hit and hit[1] is not None and (dt.date.fromisoformat(d) - dt.date.fromisoformat(hit[0])).days <= MAX_AGE[f]:
                vals.append(hit[1])
        out.append((d, sum(vals) / len(vals) if len(vals) >= 2 else None))
    return out


def latest(series):
    for d, v in reversed(series):
        if v is not None:
            return d, v
    return None, None


def month_end_points(series, n=7):
    """The last value in each of the last n months (the clock trail)."""
    buckets = {}
    for d, v in series:
        if v is not None:
            buckets[d[:7]] = (d, v)
    keys = sorted(buckets)[-n:]
    return [buckets[k] for k in keys]


# ---------------------------------------------------------------- the four composites
def inputs_liquidity(D):
    out = []
    try:
        out.append((diff(yoy(big3_m2_usd(D)), 3), "m"))                 # change in Big-3 M2 YoY, 3 months
    except KeyError:
        pass
    try:
        out.append((diff(netliq_series(D), 13), "w"))                    # 13-week net liquidity change, $B
    except KeyError:
        pass
    try:
        out.append((yoy(big3_assets_usd(D)), "m"))                       # big-3 central bank assets, YoY
    except KeyError:
        pass
    return out


def inputs_growth(D):
    out = []
    if "claims4" in D:
        out.append((invert(diff(D["claims4"], 13)), "w"))               # claims, 13-week change, inverted
    if "cfnai3" in D:
        out.append((D["cfnai3"], "m"))                                  # CFNAI three-month average, level
    if "payrolls" in D:
        p = D["payrolls"]
        d1 = [(p[i][0], p[i][1] - p[i - 1][1]) for i in range(1, len(p))]
        avg3 = [(x, v / 3.0) for x, v in c.rolling_sum(d1, 3)]
        out.append((diff(avg3, 3), "m"))                                # payrolls 3m average, 3-month change
    return out


def inputs_inflation(D):
    out = []
    if "core_cpi" in D:
        s = D["core_cpi"]
        out.append(([(s[i][0], ((s[i][1] / s[i - 3][1]) ** 4 - 1.0) * 100.0) for i in range(3, len(s))], "m"))
    if "t5yifr" in D:
        out.append((diff(D["t5yifr"], 63), "d"))                        # 5y5y, 3-month change
    if "wti" in D:
        out.append((pct_change(D["wti"]["close"], 63), "d"))            # oil, 3-month change
    return out


def inputs_risk(D):
    out = []
    if "vix" in D:
        out.append((invert(D["vix"]["close"]), "d"))
    if "hy" in D:
        out.append((invert(D["hy"]), "d"))
    if "copper" in D and "gold" in D:
        out.append((ratio(D["copper"]["close"], D["gold"]["close"]), "d"))
    if "sphb" in D and "splv" in D:
        out.append((ratio(D["sphb"]["adj"], D["splv"]["adj"]), "d"))
    if "spy" in D and "tlt" in D:
        out.append((ratio(D["spy"]["adj"], D["tlt"]["adj"]), "d"))
    if "cew" in D:
        out.append((D["cew"]["adj"], "d"))
    return out


def inputs_cost(D):
    """Cost of money: real yields, financial conditions and the dollar, three-month changes, easing is positive."""
    out = []
    if "dfii10" in D:
        out.append((invert(diff(D["dfii10"], 63)), "d"))
    if "nfci" in D:
        out.append((invert(diff(D["nfci"], 13)), "w"))
    if "dxy" in D:
        out.append((invert(pct_change(D["dxy"]["close"], 63)), "d"))
    return out


QUADRANTS = {
    (1, -1): ("Recovery", "growth up, inflation down"), (1, 1): ("Overheat", "growth up, inflation up"),
    (-1, 1): ("Stagflation", "growth down, inflation up"), (-1, -1): ("Reflation", "growth down, inflation down"),
}


def quadrant(g, i):
    return QUADRANTS[(1 if g >= 0 else -1, 1 if i >= 0 else -1)]


def word3(x, up, down, flat, band=0.25):
    if x is None:
        return None
    return up if x >= band else down if x <= -band else flat


def compute(D):
    """Composites, their monthly trails, the quadrant and the regime flags."""
    comps = {}
    for key, fn in (("liq", inputs_liquidity), ("growth", inputs_growth), ("infl", inputs_inflation),
                    ("risk", inputs_risk), ("cost", inputs_cost)):
        ins = fn(D)
        series = composite_series(ins)
        d, v = latest(series)
        comps[key] = {"value": round(v, 2) if v is not None else None, "date": d, "n_inputs": len(ins),
                      "trail": [(dd, round(vv, 2)) for dd, vv in month_end_points(series, 13)]}
    g, i = comps["growth"]["value"], comps["infl"]["value"]
    q = quadrant(g, i) if g is not None and i is not None else (None, None)
    flags = {
        "liquidity": word3(comps["liq"]["value"], "expanding", "contracting", "flat"),
        "cost": word3(comps["cost"]["value"], "easing", "tightening", "stable"),
        "cycle": q[0], "cycle_detail": q[1],
        "risk": word3(comps["risk"]["value"], "on", "off", "neutral"),
    }
    # breadth, momentum factor, dollar, credit: rule-based words from the price series
    def trend(a, b):
        r = ratio(D[a]["adj"], D[b]["adj"])
        x = [v for _, v in r]
        return c.ma_trend(x, 50, 10) if len(x) > 60 else (None, None)
    try:
        above, rising = trend("rsp", "spy")
        flags["breadth"] = "broadening" if above and rising else "narrowing" if (not above and not rising) else "mixed"
    except KeyError:
        flags["breadth"] = None
    try:
        above, rising = trend("mtum", "spy")
        flags["momentum"] = "leading" if above and rising else "rolling over" if not rising else "mixed"
    except KeyError:
        flags["momentum"] = None
    try:
        x = [v for _, v in D["dxy"]["close"]]
        a50, a200 = c.above_below(x, 50), c.above_below(x, 200)
        flags["dollar"] = "weakening" if (a50, a200) == ("below", "below") else "strengthening" if (a50, a200) == ("above", "above") else "mixed"
    except KeyError:
        flags["dollar"] = None
    try:
        hy = D["hy"]
        z = rolling_z(hy, 252)[-1][1]
        ch = c.change(hy, 21)
        flags["credit"] = "stress" if z is not None and z > 2.5 else "rising" if (z is not None and z > 1.5) or (ch is not None and ch > 50) else "none"
    except KeyError:
        flags["credit"] = None
    return {"composites": comps, "flags": flags}

"""Rotation detector (section 4): five conditions per theme, states, backtests, the rotation map and the
seasonality table. Rule-based only; every number here can be recomputed from the closes.

Conditions (the page's list): relative strength turn, flow acceleration, breadth thrust, seasonal window,
macro confirmation. Flows have no free share-count feed yet and are not scored. Breadth is scored where a
free holdings file exists (SPDR funds). The seasonal condition carries half weight in the state score.
"""
import bisect
import datetime as dt
import math

from . import compute as c

SESSIONS_8W = 40
STATES = ["none", "watch_exit", "watch", "early", "developing", "confirmed", "fading"]


# ---------------------------------------------------------------- helpers
def sma_list(vals, n):
    out, run = [], 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= n:
            run -= vals[i - n]
        out.append(run / n if i >= n - 1 else None)
    return out


class Dated(object):
    """Bisect-able view of a series."""
    def __init__(self, s):
        self.dates = [d for d, _ in s]
        self.vals = [v for _, v in s]

    def on_or_after(self, date):
        i = bisect.bisect_left(self.dates, date)
        return i if i < len(self.dates) else None

    def on_or_before(self, date):
        i = bisect.bisect_right(self.dates, date) - 1
        return i if i >= 0 else None


# ---------------------------------------------------------------- 1 relative strength on vol-adjusted returns
def rs_line(theme_adj, spy_adj, vol_n=60):
    """Cumulative excess return of the theme over the S&P 500, each day's excess divided by the theme's
    trailing 60-session volatility, so a high-beta theme cannot lead by construction."""
    j = c.align(theme_adj, spy_adj)
    if len(j) < vol_n + 2:
        return []
    rets = []
    for i in range(1, len(j)):
        d, a, b = j[i]
        pa, pb = j[i - 1][1], j[i - 1][2]
        if a > 0 and b > 0 and pa > 0 and pb > 0:
            rets.append((d, math.log(a / pa), math.log(b / pb)))
    line, total = [], 0.0
    for i in range(vol_n, len(rets)):
        seg = [r[1] for r in rets[i - vol_n:i]]
        mean = sum(seg) / vol_n
        sd = math.sqrt(sum((x - mean) ** 2 for x in seg) / (vol_n - 1)) or 1e-9
        total += (rets[i][1] - rets[i][2]) / sd
        line.append((rets[i][0], total))
    return line


def rs_states(line, n=50):
    """+1 above the 50-day average of the line, -1 below, per date; None until the average exists."""
    vals = [v for _, v in line]
    sma = sma_list(vals, n)
    return [(line[i][0], (1 if vals[i] > sma[i] else -1) if sma[i] is not None else None) for i in range(len(line))]


def rs_signal(states):
    """Current state, the date of the last cross and sessions since it."""
    cur = None
    for i in range(len(states) - 1, -1, -1):
        if states[i][1] is not None:
            cur = states[i][1]
            k = i
            break
    if cur is None:
        return {"value": 0, "since": None, "sessions": None}
    j = k
    while j > 0 and states[j - 1][1] == cur:
        j -= 1
    return {"value": cur, "since": states[j][0], "sessions": k - j}


# ---------------------------------------------------------------- 4 seasonal window
def forward_return(dv, start_date, days):
    """Return from the first session on or after start_date to the last session within `days` days, or None."""
    i = dv.on_or_after(start_date)
    if i is None:
        return None
    end = (dt.date.fromisoformat(start_date) + dt.timedelta(days=days)).isoformat()
    j = dv.on_or_before(end)
    if j is None or j <= i or dv.dates[j] < start_date or (dt.date.fromisoformat(dv.dates[j]) - dt.date.fromisoformat(dv.dates[i])).days < days * 0.6:
        return None
    return dv.vals[j] / dv.vals[i] - 1.0


def seasonal_window(theme, spy, today, days=56, years=20, relative=True, until_year=None):
    """Average return (relative to the index when relative) and hit rate of the next `days` days from
    today's calendar date, over the previous `years` years. until_year limits the sample (backtests)."""
    t = dt.date.fromisoformat(today)
    last_year = (until_year if until_year else t.year) - 1
    rets = []
    for y in range(last_year - years + 1, last_year + 1):
        try:
            start = t.replace(year=y)
        except ValueError:                  # 29 Feb
            start = t.replace(year=y, day=28)
        a = forward_return(theme, start.isoformat(), days)
        if a is None:
            continue
        if relative:
            b = forward_return(spy, start.isoformat(), days)
            if b is None:
                continue
            rets.append((1 + a) / (1 + b) - 1.0)
        else:
            rets.append(a)
    if len(rets) < 5:
        return {"n": len(rets), "avg": None, "hit": None, "value": 0}
    avg = sum(rets) / len(rets) * 100.0
    hit = sum(1 for r in rets if r > 0) / float(len(rets)) * 100.0
    value = 1 if (avg > 0 and hit >= 60) else -1 if (avg < 0 and hit <= 40) else 0
    return {"n": len(rets), "avg": avg, "hit": hit, "value": value}


# ---------------------------------------------------------------- 3 breadth
def breadth_series(members, calendar, n=50, lookback=25):
    """Share of members above their n-day average on each of the last `lookback` sessions of the calendar.
    members: list of adj-close series. Returns [(date, pct)] or [] when too few members have enough history."""
    cal = [d for d, _ in calendar][-lookback:]
    above = {d: [0, 0] for d in cal}
    used = 0
    for s in members:
        if len(s) < n + 5:
            continue
        vals = [v for _, v in s]
        sma = sma_list(vals, n)
        idx = {d: i for i, (d, _) in enumerate(s)}
        hit = False
        for d in cal:
            i = idx.get(d)
            if i is not None and sma[i] is not None:
                above[d][1] += 1
                above[d][0] += 1 if vals[i] > sma[i] else 0
                hit = True
        used += 1 if hit else 0
    if used < 5:
        return []
    return [(d, 100.0 * above[d][0] / above[d][1]) for d in cal if above[d][1] >= max(5, used * 0.6)]


def breadth_signal(series):
    if not series:
        return {"value": None, "level": None, "low": None, "high": None}
    vals = [v for _, v in series]
    level, low, high = vals[-1], min(vals[:-1] or vals), max(vals[:-1] or vals)
    value = 1 if (low < 35 and level > 60) else -1 if (high > 60 and level < 40) else 0
    return {"value": value, "level": level, "low": low, "high": high}


# ---------------------------------------------------------------- 5 macro confirmation
def _diff(s, k, scale=1.0):
    return [(s[i][0], (s[i][1] - s[i - k][1]) * scale) for i in range(k, len(s))]


def _pct(s, k):
    return [(s[i][0], (s[i][1] / s[i - k][1] - 1.0) * 100.0) for i in range(k, len(s)) if s[i - k][1]]


def _vs_sma(s, n):
    vals = [v for _, v in s]
    sma = sma_list(vals, n)
    return [(s[i][0], (vals[i] / sma[i] - 1.0) * 100.0) for i in range(len(s)) if sma[i]]


def macro_components(D, netliq):
    """Named component series with a formatter for the card text. All are changes, so a rule reads as a direction."""
    comps = {}
    if "dfii10" in D:
        comps["real21"] = (_diff(D["dfii10"], 21, 100.0), "10Y real yield %+.0f bp")
    if "dxy" in D:
        comps["dxy21"] = (_pct(D["dxy"]["close"], 21), "dollar %+.1f%%")
    if "t10y2y" in D:
        comps["curve21"] = (_diff(D["t10y2y"], 21, 100.0), "2s10s curve %+.0f bp")
    if "mtg" in D:
        comps["mtg4"] = (_diff(D["mtg"], 4, 100.0), "mortgage rate %+.0f bp")
    if "copper" in D and "gold" in D:
        r = [(d, a / b) for d, a, b in c.align(D["copper"]["close"], D["gold"]["close"]) if b]
        comps["cuau21"] = (_pct(r, 21), "copper to gold %+.1f%%")
    if "wti" in D:
        comps["wti200"] = (_vs_sma(D["wti"]["close"], 200), "crude %+.1f%% against its 200-day")
    if "hy" in D:
        comps["hy21"] = (_diff(D["hy"], 21, 1.0), "HY spread %+.0f bp")
    if netliq:
        comps["netliq13"] = (_diff(netliq, 13, 1.0), "net liquidity %+.0f $B in 13 weeks")
    if "dgs3mo" in D:
        comps["bill21"] = (_diff(D["dgs3mo"], 21, 100.0), "3-month bill yield %+.0f bp")
    return comps


# rule -> list of (component, wanted direction, threshold). Every component must agree for +1, all against for -1.
MACRO_RULES = {
    "gold": [("real21", "neg", 0), ("dxy21", "neg", 0)],
    "curve": [("curve21", "pos", 5)],
    "housing": [("mtg4", "neg", 5)],
    "cyclicals": [("cuau21", "pos", 0)],
    "energy": [("wti200", "pos", 0)],
    "defensive": [("hy21", "pos", 10)],
    "liquidity_real": [("netliq13", "pos", 0), ("real21", "neg", 0)],
    "real_yields": [("real21", "neg", 0)],
    "liquidity_dollar": [("netliq13", "pos", 0), ("dxy21", "neg", 0)],
    "cash": [("bill21", "neg", 5)],
}
MACRO_LABEL = {
    "gold": "real yields and the dollar falling", "curve": "curve steepening", "housing": "mortgage rates falling",
    "cyclicals": "copper to gold rising", "energy": "crude above its 200-day", "defensive": "HY spreads widening",
    "liquidity_real": "liquidity expanding, real yields falling", "real_yields": "real yields falling",
    "liquidity_dollar": "liquidity expanding, dollar falling", "cash": "bill yields falling",
}


def _sign(v, want, thr):
    s = 1 if v > thr else -1 if v < -thr else 0
    return s if want == "pos" else -s


_DATED = {}


def _dated(series):
    """Cached bisect view of a series (the backtest asks for thousands of dates)."""
    k = id(series)
    v = _DATED.get(k)
    if v is None or v[0] is not series:
        v = (series, Dated(series))
        _DATED[k] = v
    return v[1]


def at_or_before(series, date):
    dv = _dated(series)
    i = dv.on_or_before(date)
    return (dv.dates[i], dv.vals[i]) if i is not None else None


def macro_at(comps, rule, date):
    """(+1, 0, -1, or None when a component is missing), and the component readings at that date."""
    parts = MACRO_RULES.get(rule)
    if not parts:
        return None, []
    signs, readings = [], []
    for name, want, thr in parts:
        if name not in comps:
            return None, []
        hit = at_or_before(comps[name][0], date)
        if not hit or (dt.date.fromisoformat(date) - dt.date.fromisoformat(hit[0])).days > 45:
            return None, []
        signs.append(_sign(hit[1], want, thr))
        shown = round(hit[1], 1 if ".1f" in comps[name][1] else 0)
        readings.append(comps[name][1] % (0.0 if shown == 0 else shown))       # no "-0 bp"
    value = 1 if all(x == 1 for x in signs) else -1 if all(x == -1 for x in signs) else 0
    return value, readings


# ---------------------------------------------------------------- scoring and states
def score(sig):
    """Entry and exit scores from a {condition: value} dict (values +1, 0, -1 or None). Seasonal is half weight."""
    entry = lost = 0.0
    count = 0
    for k, v in sig.items():
        if v is None:
            continue
        w = 0.5 if k == "seasonal" else 1.0
        if v == 1:
            entry += w
            count += 1
        elif v == -1:
            lost += w
    return entry, lost, count


def raw_state(entry, lost, prev_state, evidence_ok=True):
    if prev_state in ("developing", "confirmed") and lost >= 2:
        return "fading"
    if entry >= 4:
        return "confirmed" if evidence_ok else "developing"
    if entry >= 3:
        return "developing"
    if entry >= 2:
        return "early"
    if entry >= 1:
        return "watch"
    if lost >= 1:
        return "watch_exit"
    return "none"


def confirm_state(prev, raw, today, first_run):
    """Three consecutive runs with the same raw state flip the official state (the page's rule)."""
    prev = prev or {}
    if first_run or not prev.get("state"):
        return {"state": raw, "since": today, "raw": raw, "raw_count": 3, "raw_since": today}
    if raw == prev.get("raw"):
        raw_count, raw_since = prev.get("raw_count", 0) + 1, prev.get("raw_since", today)
    else:
        raw_count, raw_since = 1, today
    state, since = prev["state"], prev.get("since", today)
    if raw != state and raw_count >= 3:
        state, since = raw, raw_since
    return {"state": state, "since": since, "raw": raw, "raw_count": raw_count, "raw_since": raw_since}


# ---------------------------------------------------------------- backtest
def _tstat(xs):
    n = len(xs)
    if n < 3:
        return None
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m / (sd / math.sqrt(n)) if sd else None


def backtest(theme_adj, spy_adj, states, comps, rule, quadrant_at, start="2011-01-01", horizon=SESSIONS_8W):
    """Events where the count of historical conditions (relative strength, seasonal, macro) first reaches a
    level, and the theme's excess return over the index in the next eight weeks. Breadth and flows have no
    twenty-year history, so live counts above the three-condition maximum are compared with 'all three'."""
    j = c.align(theme_adj, spy_adj)
    dv_t, dv_s = Dated([(d, a) for d, a, _ in j]), Dated([(d, b) for d, _, b in j])
    st = dict(states)
    levels = {1.0: [], 2.0: [], 2.5: []}
    last_event = {k: -10 ** 6 for k in levels}
    prev_count = 0.0
    seas_cache = {}
    for i in range(len(j) - horizon):
        d = j[i][0]
        if d < start:
            continue
        rs = st.get(d)
        rs_v = 1 if rs == 1 else 0
        key = (d[5:10], d[:4])
        if key not in seas_cache:
            seas_cache[key] = seasonal_window(dv_t, dv_s, d, until_year=int(d[:4]))["value"]
        seas_v = 0.5 if seas_cache[key] == 1 else 0
        mv, _ = macro_at(comps, rule, d) if rule else (None, [])
        macro_v = 1 if mv == 1 else 0
        count = rs_v + seas_v + macro_v
        for level in levels:
            if count >= level and prev_count < level and i - last_event[level] >= horizon:
                fwd = (j[i + horizon][1] / j[i][1]) / (j[i + horizon][2] / j[i][2]) - 1.0
                levels[level].append((d, fwd * 100.0, quadrant_at(d)))
                last_event[level] = i
        prev_count = count
    out = {}
    for level, ev in levels.items():
        xs = [x for _, x, _ in ev]
        if not xs:
            out[str(level)] = {"n": 0}
            continue
        byq = {}
        for _, x, q in ev:
            byq.setdefault(q, []).append(x)
        out[str(level)] = {"n": len(xs), "hit": 100.0 * sum(1 for x in xs if x > 0) / len(xs), "avg": sum(xs) / len(xs),
                           "worst": min(xs), "t": _tstat(xs),
                           "quadrants": {q: {"n": len(v), "hit": 100.0 * sum(1 for x in v if x > 0) / len(v)} for q, v in byq.items() if q}}
    return out


def evidence_ok(bt, level="2.5"):
    b = bt.get(level) or {}
    return bool(b.get("n", 0) >= 20 and (b.get("t") or 0) >= 2)


# ---------------------------------------------------------------- rotation map (relative rotation construction)
def rotation_point(theme_adj, spy_adj, at=0):
    """Relative strength: 100 times the 10-week average of the ratio to the S&P 500 over its one-year mean.
    Momentum: 100 times the ratio of that relative strength to its value ten weeks earlier. at = sessions back."""
    r = [(d, a / b) for d, a, b in c.align(theme_adj, spy_adj) if b]
    if at:
        r = r[:-at]
    if len(r) < 252 + 50:
        return None
    vals = [v for _, v in r]
    rs_now = 100.0 * (sum(vals[-50:]) / 50.0) / (sum(vals[-252:]) / 252.0)
    rs_then = 100.0 * (sum(vals[-100:-50]) / 50.0) / (sum(vals[-302:-50]) / 252.0)
    return {"date": r[-1][0], "rs": rs_now, "mom": 100.0 * rs_now / rs_then if rs_then else 100.0}


def quadrant_of(rs, mom):
    if rs >= 100 and mom >= 100:
        return "Leading"
    if rs < 100 and mom >= 100:
        return "Improving"
    if rs < 100 and mom < 100:
        return "Lagging"
    return "Weakening"


# ---------------------------------------------------------------- seasonality table
def monthly_profile(adj, years=20, relative_to=None):
    """Average monthly return and hit rate by calendar month over the last `years` years."""
    def month_closes(s):
        last = {}
        for d, v in s:
            last[d[:7]] = v
        return last
    a = month_closes(adj)
    b = month_closes(relative_to) if relative_to else None
    months = sorted(a)
    rets = {m: [] for m in range(1, 13)}
    cutoff = "%04d" % (int(months[-1][:4]) - years)
    for i in range(1, len(months)):
        m0, m1 = months[i - 1], months[i]
        if m1 < cutoff or not a.get(m0):
            continue
        r = a[m1] / a[m0] - 1.0
        if b is not None:
            if not b.get(m0) or not b.get(m1):
                continue
            r = (1 + r) / (b[m1] / b[m0]) - 1.0
        rets[int(m1[5:7])].append(r)
    out = []
    for m in range(1, 13):
        xs = rets[m]
        out.append({"avg": sum(xs) / len(xs) * 100.0 if xs else None, "hit": 100.0 * sum(1 for x in xs if x > 0) / len(xs) if xs else None, "n": len(xs)})
    return out

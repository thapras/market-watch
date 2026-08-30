"""Event studies, options-implied moves and the surprise log behind section 5.

Event study: for every past release date since 2011 (BLS archives for payrolls and CPI, the Fed's pages for
FOMC decisions), the close-to-close move of the S&P 500, the 10-year yield, the dollar index and gold on the
release session and over five sessions. Unconditional for now: splitting by sign of surprise needs the
consensus log, which starts with the first nightly run.

Implied move: from the Cboe SPX chain's at-the-money volatility per expiry. With daily expiries the variance
between two consecutive expiries is the variance of one session, so the session that carries an event has an
implied one-sigma move of its own; the median session in the next two weeks is the bar for calling it big.

Surprise log: Forex Factory's consensus is logged before each release, the first print is read from FRED on
the run after it, and the difference is standardized by the dispersion of past surprises for that series (a
documented prior scale until the log holds twelve). The index is the mean standardized surprise over ninety days.
"""
import bisect
import datetime as dt
import math
import re
import statistics

from . import calendar as cal

STUDY_MARKETS = [("spx", "S&P 500", "pct"), ("dgs10", "10Y yield", "bp"), ("dxy", "Dollar index", "pct"), ("gold", "Gold", "pct")]
STUDY_NAMES = {"nfp": "Nonfarm payrolls", "cpi": "US CPI", "fomc": "FOMC decision"}
SINCE = "2011-01-01"
MIN_STUDY = 10
MIN_INDEX = 6
INDEX_WINDOW = 90
RESOLVE_DAYS = 21


def series_of(D, key):
    v = D.get(key)
    if isinstance(v, dict):
        return v.get("close") or v.get("adj")
    return v


# ---------------------------------------------------------------- event study
def moves(series, date, mode):
    """(one-session, five-session) move for the session on or after date, against the prior close. None when the
    series has a gap there or too little history."""
    dates = [d for d, _ in series]
    i = bisect.bisect_left(dates, date)
    if i == 0 or i + 4 >= len(series):
        return None
    if (dt.date.fromisoformat(dates[i]) - dt.date.fromisoformat(date)).days > 4:
        return None
    base, one, five = series[i - 1][1], series[i][1], series[i + 4][1]
    if not base:
        return None
    if mode == "bp":
        return (one - base) * 100.0, (five - base) * 100.0
    return (one / base - 1.0) * 100.0, (five / base - 1.0) * 100.0


def _p(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def study(dates, D, today):
    """Per market: n, median and 90th percentile of the absolute one-session move, share of up sessions, mean, and the
    same for five sessions. dates: release dates (ISO); only those before today and since 2011 count."""
    past = [d for d in (dates or []) if SINCE <= d < today]
    out = {"n": 0, "from": past[0] if past else None, "to": past[-1] if past else None, "markets": {}}
    for key, name, mode in STUDY_MARKETS:
        s = series_of(D, key)
        if not s:
            continue
        mv = [m for m in (moves(s, d, mode) for d in past) if m]
        if len(mv) < MIN_STUDY:
            continue
        one, five = [a for a, _ in mv], [b for _, b in mv]
        out["markets"][key] = {"name": name, "mode": mode, "n": len(mv),
                               "med_abs1": statistics.median(abs(x) for x in one), "p90_abs1": _p([abs(x) for x in one], 0.9),
                               "up1": 100.0 * sum(1 for x in one if x > 0) / len(one), "mean1": statistics.mean(one),
                               "med_abs5": statistics.median(abs(x) for x in five), "up5": 100.0 * sum(1 for x in five if x > 0) / len(five),
                               "mean5": statistics.mean(five)}
        out["n"] = max(out["n"], len(mv))
    return out


# ---------------------------------------------------------------- implied moves
def session_variances(chain):
    """{expiry: {'var': variance of the span ending at that expiry, 'sessions': sessions in the span, 'iv': atm iv}}
    from the chain's at-the-money volatilities, counting sessions from the quote date."""
    q = chain.get("quote_date") or chain.get("asof")
    out, prev_t, prev_v = {}, 0, 0.0
    for exp, iv in chain.get("atm", []):
        t = cal.business_days_between(q, exp)
        if t <= 0:
            continue
        v = iv * iv * t / 252.0
        out[exp] = {"var": max(v - prev_v, 0.0), "sessions": t - prev_t, "iv": iv, "t": t}
        prev_t, prev_v = t, v
    return out


def session_for(e):
    """The US session that carries an event: the same day for anything before the close, the next session after it;
    a closed day rolls forward."""
    d = dt.date.fromisoformat(e["date"])
    if e.get("time") and e["time"] >= "16:00":
        d += dt.timedelta(days=1)
    return cal.next_business_day(d).isoformat()


def implied_move(spans, session):
    """One-sigma move in percent for a session bracketed by daily expiries, else None."""
    sp = spans.get(session)
    if not sp or sp["sessions"] != 1 or sp["var"] <= 0:
        return None
    return math.sqrt(sp["var"]) * 100.0


def baseline(spans, n=10):
    """Median single-session implied move over the next n daily expiries."""
    vals = [math.sqrt(sp["var"]) * 100.0 for _, sp in sorted(spans.items())[:n] if sp["sessions"] == 1 and sp["var"] > 0]
    return statistics.median(vals) if len(vals) >= 3 else None


# ---------------------------------------------------------------- surprises
_NUM = re.compile(r"^\s*([-+]?\d*\.?\d+)\s*([KMBT%]?)")


def parse_number(s):
    """Forex Factory strings to numbers in the unit shown: '58K' -> 58, '7.33M' -> 7.33, '0.3%' -> 0.3, '' -> None."""
    if s is None:
        return None
    m = _NUM.match(str(s).replace(",", ""))
    if not m:
        return None
    return float(m.group(1))


def reference_period(release_iso, lag):
    """First day of the reference month (lag months before the release month), or of the previous quarter for 'q'."""
    d = dt.date.fromisoformat(release_iso)
    if lag == "q":
        q0 = ((d.month - 1) // 3) * 3 + 1              # first month of the release quarter
        y, m = (d.year, q0 - 3) if q0 > 1 else (d.year - 1, 10)
        return dt.date(y, m, 1).isoformat()
    m = d.month - lag
    y = d.year
    while m < 1:
        m += 12
        y -= 1
    return dt.date(y, m, 1).isoformat()


def _shift(ref, months):
    d = dt.date.fromisoformat(ref)
    m, y = d.month - months, d.year
    while m < 1:
        m += 12
        y -= 1
    return dt.date(y, m, 1).isoformat()


def actual(D, spec, ref):
    """The first print for the reference period in the unit Forex Factory shows, or None if FRED has no observation yet."""
    s = series_of(D, spec["fred"])
    if not s:
        return None
    idx = dict(s)
    v = idx.get(ref)
    if v is None:
        return None
    how = spec["how"]
    if how == "level":
        return round(v, 2)
    if how == "level_m":
        return round(v / 1000.0, 2)
    prev = idx.get(_shift(ref, 12 if how == "yoy" else 1))
    if prev is None:
        return None
    if how == "diff":
        return round(v - prev, 1)
    return round((v / prev - 1.0) * 100.0, 1)


def scale_for(entries, spec):
    diffs = [x["a"] - x["f"] for x in entries.values() if x.get("a") is not None and x.get("f") is not None]
    if len(diffs) >= 12:
        sd = statistics.pstdev(diffs)
        if sd > 0:
            return sd, "logged"
    return spec["scale"], "prior"


def update_log(log, ff_rows, D, today):
    """Log the week's consensus for the surprise series, then resolve past entries from FRED. Returns the log and the
    entries resolved on this run as (series, date, entry)."""
    log = {k: dict(v) for k, v in (log or {}).items()}
    for e in ff_rows:
        for cns in e.get("cons", []):
            k = cns.get("series")
            if not k or k not in cal.SURPRISE:
                continue
            f = parse_number(cns.get("forecast"))
            if f is None:
                continue
            ent = dict(log.setdefault(k, {}).get(e["date"]) or {})
            if ent.get("a") is None:
                ent["f"], ent["p"] = f, parse_number(cns.get("previous"))
                log[k][e["date"]] = ent
    new = []
    t = dt.date.fromisoformat(today)
    for k, spec in cal.SURPRISE.items():
        for date, ent in sorted(log.get(k, {}).items()):
            if ent.get("a") is not None or ent.get("f") is None or date > today:
                continue
            if (t - dt.date.fromisoformat(date)).days > RESOLVE_DAYS:
                continue
            ref = reference_period(date, spec["lag"])
            a = actual(D, spec, ref)
            if a is None:
                continue
            sc, kind = scale_for(log[k], spec)
            ent = dict(ent, a=a, ref=ref, z=round((a - ent["f"]) / sc, 2), scale=kind)
            log[k][date] = ent
            new.append((k, date, ent))
    return log, new


def surprise_index(log, today, window=INDEX_WINDOW):
    """Mean standardized surprise over the window, the same a month earlier, and how much is logged."""
    t = dt.date.fromisoformat(today)
    zs = [(d, x["z"]) for k in log for d, x in log[k].items() if x.get("z") is not None]
    cur = [z for d, z in zs if (t - dt.timedelta(days=window)).isoformat() < d <= today]
    prior_end = (t - dt.timedelta(days=30)).isoformat()
    prior = [z for d, z in zs if (t - dt.timedelta(days=window + 30)).isoformat() < d <= prior_end]
    logged = [d for k in log for d, x in log[k].items() if x.get("f") is not None]
    return {"value": statistics.mean(cur) if len(cur) >= MIN_INDEX else None, "n": len(cur),
            "prior": statistics.mean(prior) if len(prior) >= MIN_INDEX else None, "n_prior": len(prior),
            "since": min(logged) if logged else None, "logged": len(logged), "resolved": len(zs), "min_n": MIN_INDEX}

"""Transforms on series (lists of (date, value), ascending). Standard library only.

Everything the page shows is one of these: a change over n observations, a
year-over-year rate, a z-score of a rolling return, a percentile of a level, a
realized volatility, a correlation, a moving-average state, or one of the five
price rules behind the ranking. Thresholds live here and stay fixed until three
months of alert logs exist (see CLAUDE.md).
"""
import datetime as dt
import math
import statistics

TRADING_DAYS = 252


# ---------------------------------------------------------------- basics
def vals(s):
    return [v for _, v in s]


def last(s, k=0):
    """(date, value) k observations back."""
    return s[-1 - k]


def change(s, n):
    """Absolute change over the last n observations, None if too short."""
    if len(s) <= n:
        return None
    return s[-1][1] - s[-1 - n][1]


def pct(s, n):
    """Percentage change over the last n observations."""
    if len(s) <= n or s[-1 - n][1] == 0:
        return None
    return (s[-1][1] / s[-1 - n][1] - 1.0) * 100.0


def at_or_before(s, date):
    """Last observation dated on or before an ISO date, or None."""
    hit = None
    for d, v in s:
        if d <= date:
            hit = (d, v)
        else:
            break
    return hit


def last_change(s):
    """Date and size of the last change in a step series (policy rates), None if it never changed."""
    for i in range(len(s) - 1, 0, -1):
        if s[i][1] != s[i - 1][1]:
            return s[i][0], s[i][1] - s[i - 1][1]
    return None


def rolling_sum(s, n):
    """Sum of the last n observations at each date, from the n-th observation on."""
    return [(s[i][0], sum(v for _, v in s[i - n + 1:i + 1])) for i in range(n - 1, len(s))]


def ytd_pct(s):
    """Change versus the last observation of the previous calendar year."""
    if not s:
        return None
    year = s[-1][0][:4]
    base = at_or_before(s, "%d-12-31" % (int(year) - 1))
    if not base or base[1] == 0:
        return None
    return (s[-1][1] / base[1] - 1.0) * 100.0


def align(a, b):
    """Inner join on date: list of (date, va, vb)."""
    bd = dict(b)
    return [(d, v, bd[d]) for d, v in a if d in bd]


def ratio(a, b):
    return [(d, x / y) for d, x, y in align(a, b) if y]


def combine(series_list, op):
    """Apply op(list_of_values) across series joined on date."""
    dicts = [dict(s) for s in series_list]
    common = set(dicts[0])
    for d in dicts[1:]:
        common &= set(d)
    return [(d, op([dd[d] for dd in dicts])) for d in sorted(common)]


def sample_points(s, n=12, mode="obs"):
    """n points for a sparkline. mode 'obs' takes the last n observations,
    'month' takes the last observation of each of the previous n-1 months plus the latest."""
    if mode == "obs":
        return [v for _, v in s[-n:]]
    buckets = {}
    for d, v in s:
        if mode == "week":
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            k = "%d-W%02d" % (y, w)
        else:
            k = d[:7]
        buckets[k] = v               # last value seen in each bucket wins
    if len(buckets) < n:
        return [v for _, v in s[-n:]]
    keys = sorted(buckets)[-n:]
    pts = [buckets[k] for k in keys]
    pts[-1] = s[-1][1]
    return pts


# ---------------------------------------------------------------- statistics
def sma(x, n):
    if len(x) < n:
        return None
    return sum(x[-n:]) / float(n)


def sma_series(x, n):
    """Moving average aligned to x; None where the window is not full."""
    out = [None] * len(x)
    if len(x) < n:
        return out
    acc = sum(x[:n])
    out[n - 1] = acc / n
    for i in range(n, len(x)):
        acc += x[i] - x[i - n]
        out[i] = acc / n
    return out


def rolling_returns(x, n):
    return [(x[i] / x[i - n] - 1.0) for i in range(n, len(x)) if x[i - n]]


def zscore_return(x, n=21, window=3 * TRADING_DAYS):
    """Current n-day return against the distribution of n-day returns over the window."""
    rr = rolling_returns(x[-(window + n):], n)
    if len(rr) < 60:
        return None
    sd = statistics.pstdev(rr)
    if sd == 0:
        return None
    z = (rr[-1] - statistics.fmean(rr)) / sd
    return max(-3.0, min(3.0, z))          # winsorized at plus or minus 3


def zscore_change(x, n=21, window=3 * TRADING_DAYS):
    """Same, for series where the change is in units (yields, spreads)."""
    seg = x[-(window + n):]
    ch = [seg[i] - seg[i - n] for i in range(n, len(seg))]
    if len(ch) < 60:
        return None
    sd = statistics.pstdev(ch)
    if sd == 0:
        return None
    return max(-3.0, min(3.0, (ch[-1] - statistics.fmean(ch)) / sd))


def percentile(x, window=TRADING_DAYS):
    """Where the last value sits in the window, 0 to 100."""
    seg = x[-window:]
    if len(seg) < 20:
        return None
    below = sum(1 for v in seg if v < seg[-1])
    return 100.0 * below / (len(seg) - 1) if len(seg) > 1 else None


def realized_vol(x, n=63, in_units=False):
    """Annualized volatility over n days: of log returns in percent, or of daily changes in units."""
    seg = x[-(n + 1):]
    if len(seg) < n // 2:
        return None
    if in_units:
        d = [seg[i] - seg[i - 1] for i in range(1, len(seg))]
        return statistics.pstdev(d) * math.sqrt(TRADING_DAYS)
    d = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0 and seg[i] > 0]
    return statistics.pstdev(d) * math.sqrt(TRADING_DAYS) * 100.0


def correlation(a, b, n=60):
    """Pearson correlation of daily returns over the last n common sessions."""
    j = align(a, b)[-(n + 1):]
    if len(j) < n // 2:
        return None
    ra = [j[i][1] / j[i - 1][1] - 1 for i in range(1, len(j))]
    rb = [j[i][2] / j[i - 1][2] - 1 for i in range(1, len(j))]
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb)


def yoy(s, k=12):
    """Year-over-year percent for a monthly series (k observations back)."""
    return pct(s, k)


def round_half_up(x, dp=1):
    if x is None:
        return None
    m = 10 ** dp
    return math.floor(abs(x) * m + 0.5) / m * (1 if x >= 0 else -1)


# ---------------------------------------------------------------- moving-average states
def above_below(x, n):
    m = sma(x, n)
    if m is None:
        return None
    return "above" if x[-1] >= m else "below"


def vs_sma_pct(x, n):
    m = sma(x, n)
    if not m:
        return None
    return (x[-1] / m - 1.0) * 100.0


def ma_trend(x, n, slope_lag):
    """(above: bool, rising: bool) for the n-day average and its slope over slope_lag sessions."""
    m = sma_series(x, n)
    if len(x) < n + slope_lag or m[-1] is None or m[-1 - slope_lag] is None:
        return None
    return (x[-1] >= m[-1], m[-1] > m[-1 - slope_lag])


def four_way(t):
    """Map (above, rising) to the -2..+2 rule score used by T and B."""
    if t is None:
        return None
    above, rising = t
    if above and rising:
        return 2
    if above:
        return 1
    if rising:
        return -1
    return -2


def rs_trend(x, n=50, slope_lag=10, lookback=21):
    """Relative-strength read of a ratio series against its own n-day average.
    Returns (state, sessions_since_cross, cross_direction) with state up / down / flat."""
    m = sma_series(x, n)
    if len(x) < n + slope_lag or m[-1] is None:
        return None
    above = x[-1] >= m[-1]
    rising = m[-1] > m[-1 - slope_lag]
    state = "up" if (above and rising) else "down" if (not above and not rising) else "flat"
    since, direction = None, None
    for k in range(1, min(lookback, len(x) - n) + 1):
        i = len(x) - 1 - k
        if m[i] is None:
            break
        was_above = x[i] >= m[i]
        if was_above != above:
            since, direction = k, ("up" if above else "down")
            break
    return state, since, direction


# ---------------------------------------------------------------- the five price rules
def rule_T(x):
    """200-day trend and slope: above a rising average +2, below a falling one -2."""
    return four_way(ma_trend(x, 200, 20))


def rule_X(x, fresh_window=63, confirm=3):
    """50-day against 200-day, three closes to confirm; a cross inside the last three months counts double."""
    s50, s200 = sma_series(x, 50), sma_series(x, 200)
    if len(x) < 200 + confirm or s200[-1] is None:
        return None
    signs = [1 if s50[i] > s200[i] else -1 for i in range(200 - 1, len(x)) if s50[i] is not None and s200[i] is not None]
    if len(signs) < confirm:
        return None
    tail = signs[-confirm:]
    if len(set(tail)) != 1:
        return 0                        # in the middle of a cross, not yet confirmed
    state = tail[0]
    since = None
    for k in range(1, len(signs)):
        if signs[-1 - k] != state:
            since = k
            break
    fresh = since is not None and since <= fresh_window
    return state * (2 if fresh else 1)


def rule_H(x):
    """Distance to the 52-week high: within 3% +2, within 10% +1, more than 20% below -1, at the low -2."""
    seg = x[-TRADING_DAYS:]
    if len(seg) < 60:
        return None
    hi, lo, c = max(seg), min(seg), seg[-1]
    d = c / hi - 1.0
    if d >= -0.03:
        return 2
    if d >= -0.10:
        return 1
    if c <= lo:
        return -2
    if d < -0.20:
        return -1
    return 0


def rule_B_ratio(ratio_x):
    """Breadth stand-in where there are no members: trend of the ratio to the S&P 500 (50-day average, 10-day slope)."""
    return four_way(ma_trend(ratio_x, 50, 10))


def momentum_12_1(x):
    """Twelve-month return skipping the last month."""
    if len(x) < TRADING_DAYS + 1 or not x[-TRADING_DAYS - 1]:
        return None
    return x[-22] / x[-TRADING_DAYS - 1] - 1.0


def rule_M_ranks(moms):
    """moms: dict key -> 12-1 return (None allowed). Top three +2, next three +1, bottom three -2, the three above them -1."""
    ranked = sorted([k for k, v in moms.items() if v is not None], key=lambda k: moms[k], reverse=True)
    out = {k: (None if moms[k] is None else 0) for k in moms}
    n = len(ranked)
    for i, k in enumerate(ranked):
        if i < 3:
            out[k] = 2
        elif i < 6:
            out[k] = 1
        elif i >= n - 3:
            out[k] = -2
        elif i >= n - 6:
            out[k] = -1
    return out


def tags(x):
    """Shown, not scored: 55 and 20-day breakouts, base, failed breakout, extended."""
    out = []
    if len(x) < 60:
        return out
    c = x[-1]
    hi20 = max(x[-21:-1])
    hi55 = max(x[-56:-1])
    if c > hi55:
        out.append("55-day breakout")
    elif c > hi20:
        out.append("20-day breakout")
    else:
        # a failed breakout is a close above the prior 55-day high inside the last ten sessions
        # that has since given the level back; 20-day levels are too frequent in a trend to count
        for i in range(len(x) - 10, len(x) - 1):
            level = max(x[i - 55:i])
            if x[i] > level and c < level:
                out.append("Failed breakout")
                break
    seg = x[-55:]
    if min(seg) > 0 and (max(seg) - min(seg)) / min(seg) < 0.08:
        out.append("Base")
    m50 = sma(x, 50)
    if m50 and c / m50 - 1.0 > 0.10:
        out.append("Extended")
    return out


def price_score(rules):
    """Equal-weight mean of the available rules, rounded half-up to one decimal."""
    got = [v for v in rules.values() if v is not None]
    if len(got) < 3:
        return None
    return round_half_up(sum(got) / float(len(got)), 1)

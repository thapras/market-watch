"""Section 6, who is positioned: smart money against the crowd, per market, from the free feeds.

Method (the page's own): three-year z-scores, winsorized at plus or minus 3, equal weighted. Smart money is
hedger positioning with the sign set so long reads positive; for gold, silver and crude the hedgers are
producers, so only the four-week change in their shorts counts (falling shorts, covering, is bullish). In equity
index and bond futures the asset managers of the TFF report stand in for hedgers and the leveraged funds for
the crowd. Divergence = smart money minus crowd; alerts at plus or minus 1.5 need two consecutive weekly readings.
Inputs with no free feed are left out of the averages and named as such in the state.

Also here: the systematic flows replication (CTA trend signals, vol-control allocation, risk parity leverage,
pension rebalancing) from the page's stated rules.
"""
import datetime as dt
import math

from . import compute as c
from . import detector as det
from . import regime as rg

WEEKS_3Y = 156
DAYS_3Y = 756
ALERT = 1.5

# market key -> (dataset, contract name, hedger side, crowd side)
COT_MARKETS = {
    "gold": ("legacy", "GOLD - COMMODITY EXCHANGE INC.", "comm_change", "noncomm"),
    "silver": ("legacy", "SILVER - COMMODITY EXCHANGE INC.", "comm_change", "noncomm"),
    "crude": ("legacy", "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE", "comm_change", "noncomm"),
    "copper": ("legacy", "COPPER- #1 - COMMODITY EXCHANGE INC.", "comm", "noncomm"),
    "dxy": ("legacy", "USD INDEX - ICE FUTURES U.S.", "comm", "noncomm"),
    "spx": ("tff", "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE", "asset_mgr", "lev_money"),
    "ndx": ("tff", "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE", "asset_mgr", "lev_money"),
    "ust10": ("tff", "UST 10Y NOTE - CHICAGO BOARD OF TRADE", "asset_mgr", "lev_money"),
    "btc": ("tff", "BITCOIN - CHICAGO MERCANTILE EXCHANGE", "asset_mgr", "lev_money"),
}
# divergence table markets -> COT key, price key (Yahoo) and the crowd and smart money extras that apply
DIV_MARKETS = [
    ("spx", "S&P 500", "spx", "spx", ["dix", "index_pc"], ["aaii", "margin", "equity_pc"]),
    ("semis", "Semiconductors", "ndx", "smh", ["dix"], ["aaii", "equity_pc"]),
    ("gold", "Gold", "gold", "gold", [], []),
    ("silver", "Silver", "silver", "silver", [], []),
    ("crude", "Crude oil", "crude", "wti", [], []),
    ("ust10", "10Y Treasuries", "ust10", "ief", [], []),
    ("dxy", "US dollar", "dxy", "dxy", [], []),
    ("btc", "Bitcoin", "btc", "btc", [], ["crypto_fng"]),
    ("copper", "Copper", "copper", "copper", [], []),
]


# ---------------------------------------------------------------- COT series
def net(rows, long_key, short_key):
    return [(r["date"], r[long_key] - r[short_key]) for r in rows if long_key in r and short_key in r]


def cot_series(key, rows):
    """{'hedgers': net series, 'crowd': net series, 'smart_input': series used in the score, 'oi': series}."""
    dataset, _, hside, cside = COT_MARKETS[key]
    if dataset == "legacy":
        hedgers = net(rows, "comm_positions_long_all", "comm_positions_short_all")
        crowd = net(rows, "noncomm_positions_long_all", "noncomm_positions_short_all")
        shorts = [(r["date"], r["comm_positions_short_all"]) for r in rows if "comm_positions_short_all" in r]
    else:
        hedgers = net(rows, "asset_mgr_positions_long", "asset_mgr_positions_short")
        crowd = net(rows, "lev_money_positions_long", "lev_money_positions_short")
        shorts = []
    if hside == "comm_change":
        # producers: the four-week change in their shorts, sign inverted so covering reads positive
        smart = [(shorts[i][0], -(shorts[i][1] - shorts[i - 4][1])) for i in range(4, len(shorts))]
    else:
        smart = hedgers
    oi = [(r["date"], r["open_interest_all"]) for r in rows if "open_interest_all" in r]
    return {"hedgers": hedgers, "crowd": crowd, "smart_input": smart, "oi": oi, "mode": hside}


def cot_index(series, window=WEEKS_3Y):
    """Percentile of the latest value inside the trailing window, 0 to 100."""
    return c.percentile([v for _, v in series], window)


# ---------------------------------------------------------------- scores
def zlast(series, window):
    z = rg.rolling_z(series, window)
    d, v = rg.latest(z)
    return v


def market_scores(key, cot, extras_sm, extras_cr, extras):
    """Smart money and crowd scores for one market from the available z-scores. Returns
    {sm, cr, div, sm_parts, cr_parts} where parts list (name, z) for the card texts."""
    sm_parts, cr_parts = [], []
    if cot:
        zs = zlast(cot["smart_input"], WEEKS_3Y)
        if zs is not None:
            sm_parts.append(("hedgers" if cot["mode"] != "asset_mgr" else "asset managers", zs))
        zc = zlast(cot["crowd"], WEEKS_3Y)
        if zc is not None:
            cr_parts.append(("speculators" if cot["mode"] != "asset_mgr" else "leveraged funds", zc))
    for name in extras_sm:
        z = extras.get(name)
        if z is not None:
            sm_parts.append((name, z))
    for name in extras_cr:
        z = extras.get(name)
        if z is not None:
            cr_parts.append((name, z))
    sm = sum(z for _, z in sm_parts) / len(sm_parts) if sm_parts else None
    cr = sum(z for _, z in cr_parts) / len(cr_parts) if cr_parts else None
    div = sm - cr if (sm is not None and cr is not None) else None
    return {"sm": sm, "cr": cr, "div": div, "sm_parts": sm_parts, "cr_parts": cr_parts}


def weekly_divergence(cot, extra_daily=None):
    """Weekly divergence history on the COT dates, from the COT components plus any daily extras
    (sampled at each COT date). Used for the two-week rule and the 'what happened before' table."""
    if not cot:
        return []
    zs = dict(rg.rolling_z(cot["smart_input"], WEEKS_3Y))
    zc = dict(rg.rolling_z(cot["crowd"], WEEKS_3Y))
    extras = [(rg.rolling_z(s, DAYS_3Y), side) for s, side in (extra_daily or [])]
    out = []
    for d, _ in cot["crowd"]:
        sm = [zs[d]] if zs.get(d) is not None else []
        cr = [zc[d]] if zc.get(d) is not None else []
        for z, side in extras:
            hit = det.at_or_before(z, d)
            if hit and hit[1] is not None and (dt.date.fromisoformat(d) - dt.date.fromisoformat(hit[0])).days <= 10:
                (sm if side == "sm" else cr).append(hit[1])
        if sm and cr:
            out.append((d, sum(sm) / len(sm) - sum(cr) / len(cr)))
    return out


def alert_state(weekly, level=ALERT):
    """'up' or 'down' when the last two weekly readings sit beyond the alert line, else None."""
    if len(weekly) < 2:
        return None
    a, b = weekly[-1][1], weekly[-2][1]
    if a >= level and b >= level:
        return "up"
    if a <= -level and b <= -level:
        return "down"
    return None


def before(weekly, price, level=ALERT, weeks=8):
    """What happened after earlier crossings of the alert line: forward eight-week return of the market."""
    if not weekly or not price:
        return {"n": 0}
    dv = det.Dated(price)
    ups, downs = [], []
    prev = 0.0
    for d, v in weekly:
        crossed_up, crossed_down = v >= level and prev < level, v <= -level and prev > -level
        prev = v
        if not (crossed_up or crossed_down):
            continue
        r = det.forward_return(dv, d, weeks * 7)
        if r is None:
            continue
        (ups if crossed_up else downs).append(r * 100.0)
    def stats(xs):
        if not xs:
            return {"n": 0}
        xs = sorted(xs)
        med = xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2.0
        return {"n": len(xs), "median": med, "positive": 100.0 * sum(1 for x in xs if x > 0) / len(xs)}
    return {"up": stats(ups), "down": stats(downs)}


def crowd_word(z):
    if z is None:
        return None
    return "euphoric" if z >= 1.5 else "optimistic, not euphoric" if z >= 0.5 else "capitulating" if z <= -1.5 else "fearful" if z <= -0.5 else "neutral"


def div_read(score, state):
    if score is None:
        return None
    if state == "up":
        return "Alert. Smart money buying what the crowd dumped."
    if state == "down":
        return "Alert. Both sides stretched, smart money leaving first."
    if score >= 1.0:
        return "Smart money ahead of the crowd; one more week beyond the line makes it an alert."
    if score <= -1.0:
        return "Crowd ahead of smart money; not extreme yet."
    if score >= 0.5:
        return "Mildly positive; no edge yet."
    if score <= -0.5:
        return "Crowd leaning long; no edge yet."
    return "No edge."


# ---------------------------------------------------------------- systematic flows
def cta_signal(close, lookbacks=(20, 50, 100, 200)):
    """Sign of the 20, 50, 100 and 200-day returns; the signal flips when three of the four agree the other way.
    Returns {signal, since, flip_level, flip_pct} where flip_level is the price that would flip it."""
    if len(close) < max(lookbacks) + 5:
        return None
    vals = [v for _, v in close]
    def state_at(i, prev):
        refs = [vals[i - k] for k in lookbacks]
        pos = sum(1 for r in refs if vals[i] > r)
        neg = len(refs) - pos
        return 1 if pos >= 3 else -1 if neg >= 3 else prev
    sig, since = 0, close[-1][0]
    states = []
    for i in range(max(lookbacks), len(vals)):
        sig = state_at(i, sig)
        states.append((close[i][0], sig))
    cur = states[-1][1]
    j = len(states) - 1
    while j > 0 and states[j - 1][1] == cur:
        j -= 1
    since = states[j][0]
    refs = sorted(vals[-1 - k] for k in lookbacks)
    flip = refs[1] if cur == 1 else refs[2]         # long flips below the second-lowest reference, short above the second-highest
    return {"signal": cur, "since": since, "flip_level": flip, "flip_pct": (flip / vals[-1] - 1.0) * 100.0}


def vol_control(close, target=12.0, n=21):
    x = [v for _, v in close]
    rv = c.realized_vol(x, n)
    if rv is None:
        return None
    alloc = min(100.0, target / rv * 100.0)
    word = "high" if alloc >= 90 else "medium" if alloc >= 60 else "low"
    return {"vol": rv, "alloc": alloc, "word": word}


def risk_parity(spy, tlt):
    corr = c.correlation(spy, tlt, 60)
    xs, xb = [v for _, v in spy], [v for _, v in tlt]
    up_s, up_b = c.above_below(xs, 100) == "above", c.above_below(xb, 100) == "above"
    if corr is None:
        return None
    if up_s and up_b and corr < 0:
        word = "high"
    elif corr > 0.3 or (not up_s and not up_b):
        word = "reducing"
    else:
        word = "medium"
    return {"corr": corr, "stocks_up": up_s, "bonds_up": up_b, "word": word}


def pension_rebalance(spy, tlt, today):
    """Quarter-to-date returns of stocks against bonds; the gap is what pensions unwind into quarter end."""
    q0 = "%s-%02d-01" % (today[:4], ((int(today[5:7]) - 1) // 3) * 3 + 1)
    def qtd(s):
        base = det.Dated(s)
        i = base.on_or_before(q0)
        if i is None:
            return None
        return (s[-1][1] / base.vals[i] - 1.0) * 100.0
    a, b = qtd(spy), qtd(tlt)
    if a is None or b is None:
        return None
    gap = a - b
    word = "sell equities, large" if gap > 6 else "sell equities, modest" if gap > 2 else "buy equities, modest" if gap < -2 else "small"
    return {"stocks": a, "bonds": b, "gap": gap, "word": word}

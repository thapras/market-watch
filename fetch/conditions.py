"""The ranking's conditions score: seven pillars on a -2 to +2 scale, weights 1, 1, 1, 1, 0.5, 1, 0.5.

L liquidity: the liquidity composite times the market's liquidity beta.
C cost of money: the cost-of-money composite (real yields, financial conditions, the dollar; easing positive)
  times the market's rate sensitivity.
Y cycle: the Investment Clock quadrant's historical preference for the market.
V valuation: percentile of the market's own valuation history, for the three markets with a free series
  (S&P 500 trailing P/E, the 10-year real yield for Treasuries, the HY spread for high yield).
F flows and P positioning: no feed yet (positioning is v3); left out of the average and shown as such.
S seasonal: the next three months from today's date over the twenty-year record.
The betas and quadrant preferences are starting points, listed here so they can be tuned from the log.
"""
from . import compute as c
from . import detector as det

WEIGHTS = {"L": 1.0, "C": 1.0, "Y": 1.0, "V": 1.0, "F": 0.5, "P": 1.0, "S": 0.5}

BETA_L = {"gold_miners": 1.5, "em_ex_china": 1.5, "us_small": 1.5, "banks": 1.0, "copper": 1.5, "gold": 1.2, "reits": 1.0,
          "japan": 1.0, "bitcoin": 2.0, "silver": 1.5, "europe": 1.0, "thailand": 1.5, "ust10": 0.5, "us_hy": 1.0,
          "us_large": 1.0, "semis": 1.5, "energy": 0.5, "cash": -1.5}
BETA_C = {"gold_miners": 1.5, "em_ex_china": 1.5, "us_small": 1.5, "banks": 0.5, "copper": 1.0, "gold": 1.5, "reits": 1.5,
          "japan": 0.5, "bitcoin": 1.5, "silver": 1.5, "europe": 1.0, "thailand": 1.0, "ust10": 1.5, "us_hy": 1.0,
          "us_large": 1.0, "semis": 1.5, "energy": 0.0, "cash": -1.5}
QUAD_PREF = {
    "Recovery": {"us_large": 2, "us_small": 2, "europe": 2, "japan": 2, "thailand": 2, "em_ex_china": 2, "banks": 2, "semis": 2,
                 "us_hy": 2, "copper": 1, "reits": 1, "bitcoin": 1, "gold": 0, "gold_miners": 0, "silver": 0, "energy": 0,
                 "ust10": -1, "cash": -2},
    "Overheat": {"copper": 2, "energy": 2, "silver": 1, "gold": 1, "gold_miners": 1, "em_ex_china": 1, "thailand": 1,
                 "us_large": 0, "us_small": 0, "banks": 0, "europe": 0, "japan": 0, "semis": 0, "bitcoin": 0, "us_hy": 0,
                 "reits": -1, "ust10": -2, "cash": -1},
    "Stagflation": {"cash": 2, "gold": 2, "gold_miners": 2, "silver": 1, "energy": 1, "ust10": 0, "copper": -1, "us_large": -1,
                    "banks": -1, "em_ex_china": -1, "thailand": -1, "europe": -1, "japan": -1, "bitcoin": -1, "reits": -1,
                    "us_small": -2, "semis": -2, "us_hy": -2},
    "Reflation": {"ust10": 2, "us_hy": 1, "reits": 1, "gold": 1, "gold_miners": 1, "silver": 0, "cash": 0, "us_large": 0,
                  "europe": 0, "japan": 0, "em_ex_china": 0, "thailand": 0, "semis": 0, "bitcoin": 0, "us_small": -1,
                  "banks": -1, "copper": -1, "energy": -2},
}
NAMES = {"L": "Liquidity", "C": "Cost of money", "Y": "Cycle", "V": "Valuation", "F": "Flows", "P": "Positioning", "S": "Seasonal"}


def half(x):
    """Round to the nearest 0.5 inside -2 to +2."""
    return max(-2.0, min(2.0, round(x * 2.0) / 2.0))


def pct_to_score(p, cheap_when_high):
    """Percentile of a valuation series to a score; expensive is negative."""
    if p is None:
        return None
    s = 2 if p >= 80 else 1 if p >= 60 else -2 if p <= 20 else -1 if p <= 40 else 0
    return s if cheap_when_high else -s


def pillar_V(D, key):
    if key == "us_large" and "spx_pe" in D:
        return pct_to_score(c.percentile([v for _, v in D["spx_pe"]], 120), False), "trailing P/E, 10-year percentile"
    if key == "ust10" and "dfii10" in D:
        return pct_to_score(c.percentile([v for _, v in D["dfii10"]], 2520), True), "10-year real yield, 10-year percentile"
    if key == "us_hy" and "hy" in D:
        return pct_to_score(c.percentile([v for _, v in D["hy"]], 756), True), "HY spread, 3-year percentile"
    return None, "no free valuation series"


def pillar_S(adj, today):
    """Next three months from today's date, twenty years: sign of the average with the hit rate as conviction."""
    if not adj:
        return None, None
    w = det.seasonal_window(det.Dated(adj), None, today, days=91, relative=False)
    if w["avg"] is None:
        return None, w
    a, h = w["avg"], w["hit"]
    s = 2 if (a > 0 and h >= 65) else 1 if (a > 0 and h >= 55) else -2 if (a < 0 and h <= 35) else -1 if (a < 0 and h <= 45) else 0
    return s, w


def compute(D, regime, ranking_series, today, p_values=None):
    """ranking_series: {key: adj-close series or None}; p_values: {key: P pillar} from section 6.
    Returns {key: {pillars, cond, n, detail}}."""
    p_values = p_values or {}
    comps = regime["composites"]
    liq, cost = comps["liq"]["value"], comps["cost"]["value"]
    quad = regime["flags"].get("cycle")
    out = {}
    for key in BETA_L:
        pillars, detail = {}, {}
        pillars["L"] = half(liq * BETA_L[key]) if liq is not None else None
        detail["L"] = "liquidity composite %+.1f times beta %.1f" % (liq, BETA_L[key]) if liq is not None else "no composite"
        pillars["C"] = half(cost * BETA_C[key]) if cost is not None else None
        detail["C"] = "cost-of-money composite %+.1f times sensitivity %.1f" % (cost, BETA_C[key]) if cost is not None else "no composite"
        pillars["Y"] = float(QUAD_PREF[quad][key]) if quad else None
        detail["Y"] = "%s quadrant preference" % quad if quad else "no quadrant"
        v, vd = pillar_V(D, key)
        pillars["V"], detail["V"] = (float(v) if v is not None else None), vd
        pillars["F"], detail["F"] = None, "no free flow feed yet"
        pv = p_values.get(key)
        pillars["P"] = float(pv) if pv is not None else None
        detail["P"] = ("section 6 divergence score, smart money minus the crowd" if pv is not None else "no futures positioning for this market")
        s, w = pillar_S(ranking_series.get(key), today) if key != "cash" else (0.0, None)
        pillars["S"] = float(s) if s is not None else None
        detail["S"] = ("next 3 months, 20 years: average %+.1f%%, hit rate %d%%" % (w["avg"], round(w["hit"]))) if w and w.get("avg") is not None else ("cash has no season" if key == "cash" else "no twenty-year history")
        num = sum(WEIGHTS[k] * v for k, v in pillars.items() if v is not None)
        den = sum(WEIGHTS[k] for k, v in pillars.items() if v is not None)
        cond = round(num / den, 1) if den else None
        out[key] = {"pillars": pillars, "detail": detail, "cond": cond, "n": sum(1 for v in pillars.values() if v is not None)}
    return out


def read(cond, price, band=0.5):
    """The page's read rule: both beyond the band the same way is Aligned, opposite is Divergence, one
    beyond with the other inside is Conditions ahead or Price ahead, else Neutral."""
    if cond is None or price is None:
        return None
    cs = 1 if cond >= band else -1 if cond <= -band else 0
    ps = 1 if price >= band else -1 if price <= -band else 0
    if cs and ps:
        return ("Aligned up" if cs > 0 else "Aligned down") if cs == ps else "Divergence"
    if cs:
        return "Conditions ahead, up" if cs > 0 else "Conditions ahead, down"
    if ps:
        return "Price ahead, up" if ps > 0 else "Price ahead, down"
    return "Neutral"

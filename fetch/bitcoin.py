"""v5: the bitcoin tab (bitcoin.html). Twenty-two scored indicators in six groups, each voting bull, bear or
neutral against fixed thresholds, tallied into a lean that follows the three-close rule and feeds the change log.

The construction follows the indicator tally in Benjamin Cowen's "Bitcoin: Bull Case Vs. Bear Case" (9 Sep 2026):
on-chain resets, the cycle clock, market and macro, trend and moving averages, social and whale activity. Only the
rows with a free feed are scored; the rest are listed as unscored so the tally is honest about what it cannot see.

Vote semantics: bull means the reset that preceded every prior cycle low is in place (or a trend rule is up), bear
means the top zone or a trend rule down, neutral is between. Thresholds are calibrated on the 2013 to 2025 cycles
(the values at each top and low are in the comments) and stay fixed until three months of logs exist. Nothing here
is a price target: the regression band is a cycle position, and the page says so.

ROWS is the contract with the page: the table on bitcoin.html lists exactly these rows, in this order.
"""
import datetime as dt
import math

from . import changes as ch
from . import compute as c
from . import detector as det

GENESIS = dt.date(2009, 1, 3)
HALVINGS = ["2012-11-28", "2016-07-09", "2020-05-11", "2024-04-20"]
CYCLE_LOWS = ["2015-01-14", "2018-12-15", "2022-11-21"]           # daily closes, Coin Metrics reference rate
# days from a halving to the next cycle low: 777 (2012 to 2015), 889 (2016 to 2018), 924 (2020 to 2022)
LOW_AFTER_HALVING = (777, 924)
# days from one cycle low to the next: 1431 (2015 to 2018), 1437 (2018 to 2022)
LOW_TO_LOW = (1431, 1437)
NEXT_HALVING_EST = "2028-04-15"                                   # 210,000 blocks at ten minutes; shown as an estimate
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Thresholds (bull, bear). Calibration, values at each cycle low and top from the daily Coin Metrics series:
#   puell    lows 0.31 0.39 0.56 0.43   tops 9.1 6.6 2.5 1.6 1.1 (falling each cycle)
#   mvrv     lows 0.56 0.69 1.00 0.78   tops 5.1 4.3 3.4 2.8 2.3
#   thermo   lows 2.1 5.1 5.9 6.5       tops 57 66 45 36 29
#   rsi_w    lows 28 29 33 32           tops 96 67 67 68 56
#   rsi_m    lows 45 45 48 41           tops 71 96 90 68 66
#   drawdown lows 85 84 71 77 percent from the prior high
#   roi1y    lows -78 -82 -73 percent   tops +2338 +814 +99
#   mayer    lows 0.40 0.51 0.65 0.71   tops 6.22 3.64 1.93 1.47 1.18 (p10 0.72, p20 0.83, p50 1.13, p80 1.52)
#   ma200w   lows 1.41 1.12 1.48 0.68   tops 15.4 5.4 3.7 2.3; the cycle minimum touched the line every time: 0.99 1.00 0.97 0.68
T = {
    "puell": (0.5, 2.0), "mvrv": (1.0, 2.5), "thermo": (7.0, 30.0), "exflow": (20.0, 80.0), "rsi_w": (35.0, 70.0), "rsi_m": (45.0, 75.0),
    "clock": (LOW_AFTER_HALVING[0], None), "drawdown": (70.0, 40.0), "roi1y": (-50.0, 100.0),
    "mayer": (0.8, 1.5), "ma200w": (1.0, 2.3), "risk": (20.0, 80.0),
    "stables": (5.0, 0.0), "funding": (0.0, 30.0), "fng": (20.0, 80.0), "position": (1.5, -1.5), "dollar": (-3.0, 3.0), "liquidity": (0.5, -0.5),
    "ma50w": (0.0, 0.0), "cross": (0.0, 0.0), "band": (0.0, 0.0), "pi": (365, 365),
}
PI_WINDOW = 365
LEAN_GAP = 4                    # bull votes minus bear votes at or beyond this is a lean; inside it the tally is split
MUST_ROWS = ("pi", "cross")     # once-a-cycle signals: their flips are must-reads; every other flip is notable

# (key, group, name, unit, bull rule, bear rule, feed)
ROWS = [
    ("puell", "onchain", "Puell multiple", "x", "under 0.5 (issuance value at a cycle low)", "over 2.0 (the 2021 and 2025 tops; earlier tops were higher)", "Coin Metrics IssTotUSD"),
    ("mvrv", "onchain", "MVRV (market cap to realized cap)", "x", "at or under 1.0 (price below the average cost basis)", "at or over 2.5 (the 2021 tops; 2025 peaked at 2.3)", "Coin Metrics CapMVRVCur"),
    ("thermo", "onchain", "ThermoCap multiple", "x", "at or under 7 (the 2018 to 2022 lows)", "at or over 30 (the 2021 and 2025 tops)", "Coin Metrics IssTotUSD, FeeTotNtv"),
    ("exflow", "onchain", "Exchange net flow, 30 days, share of supply", "%", "three-year percentile 20 or under (coins leaving exchanges)", "percentile 80 or over (coins moving to exchanges)", "Coin Metrics FlowInExNtv, FlowOutExNtv"),
    ("rsi_w", "onchain", "Weekly RSI (14)", "", "35 or under (every cycle low read 28 to 33)", "70 or over", "Coin Metrics PriceUSD, weekly closes"),
    ("rsi_m", "onchain", "Monthly RSI (14)", "", "45 or under (2015, 2018 and 2022 lows)", "75 or over", "Coin Metrics PriceUSD, monthly closes"),
    ("clock", "cycle", "Cycle clock (days since the halving)", "d", "777 or more days (inside or past the prior lows' window)", "under 777 days (before the window)", "calendar rule from the halving dates"),
    ("drawdown", "cycle", "Drawdown from the all-time high", "%", "70% or more (the shallowest cycle low was 71%)", "under 40%", "Coin Metrics PriceUSD"),
    ("roi1y", "cycle", "One-year return", "%", "minus 50% or worse (every cycle low was under minus 70%)", "plus 100% or better", "Coin Metrics PriceUSD"),
    ("mayer", "stretch", "Mayer multiple (price to the 200-day average)", "x", "at or under 0.8 (every cycle low read 0.40 to 0.71)", "at or over 1.5 (the April 2021 top; the last two tops read 1.47 and 1.18, so this line would have missed them)", "Coin Metrics PriceUSD"),
    ("ma200w", "stretch", "Price against the 200-week average", "x", "at or under 1.00 (the cycle floor: every cycle has touched or broken it)", "at or over 2.3 (the 2025 top; earlier tops reached 3.7 to 15.4)", "Coin Metrics PriceUSD, weekly closes"),
    ("risk", "stretch", "Log regression residual since 2010", "pct", "percentile 20 or under of all residuals since 2010", "percentile 80 or over", "our fit on Coin Metrics PriceUSD, not a target"),
    ("stables", "market", "Stablecoin supply, 90-day change", "%", "plus 5% or more (new dry powder)", "negative (supply contracting, as in 2022)", "DefiLlama, USD-pegged circulating"),
    ("dominance", "market", "Bitcoin dominance and total crypto market cap", "%", "", "", "CoinGecko global, logged nightly"),
    ("funding", "market", "Perpetual funding, 30-day mean, annualized", "%", "negative (shorts pay, capitulation)", "over 30% (the froth zone)", "Bybit, OKX or Hyperliquid, whichever answers"),
    ("fng", "market", "Crypto fear and greed", "", "20 or under (extreme fear)", "80 or over (extreme greed)", "alternative.me"),
    ("position", "market", "Smart money minus crowd (section 6)", "z", "plus 1.5 or more", "minus 1.5 or less", "CFTC TFF bitcoin futures, fear and greed"),
    ("dollar", "market", "Dollar index, three-month change", "%", "minus 3% or more (dollar falling)", "plus 3% or more (dollar rising)", "Yahoo DX-Y.NYB"),
    ("liquidity", "market", "Liquidity impulse (section 1 composite)", "z", "plus 0.5 or more", "minus 0.5 or less", "regime composite"),
    ("ma50w", "trend", "Close against the 50-week average", "%", "above", "below", "weekly closes"),
    ("cross", "trend", "50-day against 200-day average", "%", "golden cross (50 above 200)", "death cross (50 below 200)", "daily closes"),
    ("band", "trend", "Bull market support band (20-week SMA, 21-week EMA)", "%", "above both", "below both", "weekly closes"),
    ("pi", "trend", "Pi Cycle top and bottom", "d", "bottom cross inside a year (150-day EMA under 0.745 times the 471-day SMA)", "top cross inside a year (111-day SMA over twice the 350-day SMA)", "daily closes"),
    ("attention", "social", "Attention: Wikipedia pageviews for Bitcoin", "", "", "", "Wikimedia pageviews API, 30-day average"),
    ("apprank", "social", "Coinbase app store rank", "", "", "", "no free feed"),
    ("whales", "social", "Addresses holding 1,000 coins or more", "", "", "", "no free feed (Coin Metrics balance cohorts are paid)"),
    ("etf", "social", "Spot ETF net flows", "", "", "", "no free feed (Farside is behind Cloudflare, the iShares endpoints serve HTML)"),
]
SHORT = {"puell": "Puell multiple", "mvrv": "MVRV", "thermo": "ThermoCap multiple", "exflow": "exchange flows", "rsi_w": "weekly RSI", "rsi_m": "monthly RSI",
         "clock": "the cycle clock", "drawdown": "the drawdown", "roi1y": "the one-year return", "stables": "stablecoin supply", "dominance": "dominance",
         "risk": "the regression position", "mayer": "the Mayer multiple", "ma200w": "the 200-week average", "attention": "attention",
         "funding": "funding", "fng": "fear and greed", "position": "section 6 positioning", "dollar": "the dollar", "liquidity": "liquidity",
         "ma50w": "the 50-week average", "cross": "the 50/200 cross", "band": "the support band", "pi": "Pi Cycle",
         "apprank": "app store rank", "whales": "whale cohorts", "etf": "ETF flows"}
GROUPS = [("onchain", "On-chain resets"), ("cycle", "Cycle clock"), ("stretch", "Price against its own history"),
          ("market", "Market, leverage and macro"), ("trend", "Trend and moving averages"), ("social", "Social and whales")]
SCORED = [r[0] for r in ROWS if r[1] != "social" and r[0] != "dominance"]


# ---------------------------------------------------------------- statistics
def ema(vals, n):
    k = 2.0 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def rsi(vals, n=14):
    """Wilder's RSI, aligned to vals; None where the window is not full."""
    out = [None] * len(vals)
    if len(vals) < n + 1:
        return out
    gains = [max(vals[i] - vals[i - 1], 0.0) for i in range(1, len(vals))]
    losses = [max(vals[i - 1] - vals[i], 0.0) for i in range(1, len(vals))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def bucket(series, mode):
    """Last observation per ISO week or per month: [(date, value)]."""
    b = {}
    for d, v in series:
        if mode == "week":
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            k = "%d-W%02d" % (y, w)
        else:
            k = d[:7]
        b[k] = (d, v)
    return [b[k] for k in sorted(b)]


def spark(series, n=52):
    """One value per week, the last n weeks, rounded."""
    pts = [v for _, v in bucket(series, "week")[-n:]]
    return [round(v, 3) for v in pts]


def pctile(vals, x):
    """Where x sits among vals, 0 to 100."""
    if len(vals) < 2:
        return None
    return 100.0 * sum(1 for v in vals if v < x) / (len(vals) - 1)


def ago(series, date, days):
    """Value on or before `days` calendar days before date."""
    hit = c.at_or_before(series, (dt.date.fromisoformat(date) - dt.timedelta(days=days)).isoformat())
    return hit[1] if hit else None


def dl(date):
    d = dt.date.fromisoformat(date)
    return "%d %s" % (d.day, MONTHS[d.month - 1])


def dly(date):
    d = dt.date.fromisoformat(date)
    return "%d %s %d" % (d.day, MONTHS[d.month - 1], d.year)


# ---------------------------------------------------------------- series builders
def puell_series(iss_usd):
    v = [x for _, x in iss_usd]
    return [(iss_usd[i][0], v[i] / (sum(v[i - 364:i + 1]) / 365.0)) for i in range(364, len(v)) if sum(v[i - 364:i + 1]) > 0]


def thermocap_series(iss_usd, fee_ntv, price):
    """Cumulative miner revenue in dollars (issuance plus fees at the day's price) and the market cap multiple on it."""
    fee, px = dict(fee_ntv), dict(price)
    cum, out = 0.0, []
    for d, v in iss_usd:
        cum += v + fee.get(d, 0.0) * px.get(d, 0.0)
        out.append((d, cum))
    return out


def multiple(mcap, thermo):
    t = dict(thermo)
    return [(d, m / t[d]) for d, m in mcap if d in t and t[d] > 0]


def mvrv_z_series(mcap, mvrv):
    """(market cap minus realized cap) over the standard deviation of market cap to date."""
    r = dict(mvrv)
    out, xs, s1, s2 = [], 0, 0.0, 0.0
    for d, m in mcap:
        if d not in r or r[d] <= 0:
            continue
        xs += 1
        s1 += m
        s2 += m * m
        var = s2 / xs - (s1 / xs) ** 2
        sd = math.sqrt(var) if var > 0 else 0.0
        out.append((d, (m - m / r[d]) / sd if sd else 0.0))
    return out


def exflow_series(flow_in, flow_out, supply, n=30):
    fo, sup = dict(flow_out), dict(supply)
    net = [(d, v - fo[d]) for d, v in flow_in if d in fo]
    vals = [v for _, v in net]
    return [(net[i][0], sum(vals[i - n + 1:i + 1]) / sup[net[i][0]] * 100.0) for i in range(n - 1, len(net)) if sup.get(net[i][0])]


def log_regression(price):
    """ln(price) on ln(days since genesis), least squares over the whole history. Returns the fit, the residuals
    (aligned to price), and the 20th and 80th residual percentiles that draw the band."""
    xs = [math.log((dt.date.fromisoformat(d) - GENESIS).days) for d, _ in price]
    ys = [math.log(v) for _, v in price]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    srt = sorted(res)
    p20, p80 = srt[int(0.2 * (n - 1))], srt[int(0.8 * (n - 1))]
    return {"a": a, "b": b, "res": res, "p20": p20, "p80": p80, "pct": pctile(res, res[-1])}


def fit_at(reg, date):
    return math.exp(reg["a"] + reg["b"] * math.log((dt.date.fromisoformat(date) - GENESIS).days))


def pi_cycle(price):
    """Top: the 111-day SMA crossing above twice the 350-day SMA. Bottom: the 150-day EMA crossing below 0.745 times
    the 471-day SMA (fired 14 Jan 2015, 16 Dec 2018, 13 Jul 2022). Returns the last cross dates and today's gaps."""
    dates, px = [d for d, _ in price], [v for _, v in price]
    n = len(px)
    if n < 480:
        return None
    s111, s350, s471, e150 = c.sma_series(px, 111), c.sma_series(px, 350), c.sma_series(px, 471), ema(px, 150)
    top, bottom = None, None
    for i in range(471, n):
        if s111[i - 1] <= 2 * s350[i - 1] and s111[i] > 2 * s350[i]:
            top = dates[i]
        if e150[i - 1] >= 0.745 * s471[i - 1] and e150[i] < 0.745 * s471[i]:
            bottom = dates[i]
    return {"top": top, "bottom": bottom, "top_gap": (s111[-1] / (2 * s350[-1]) - 1.0) * 100.0, "bottom_gap": (e150[-1] / (0.745 * s471[-1]) - 1.0) * 100.0}


def cycle_clock(price, today):
    """Days since the halving, the prior lows' window projected from it and from the low-to-low spacing, the all-time
    high and the drawdown, and the last low of this cycle (the lowest close since the previous cycle low)."""
    t = dt.date.fromisoformat(today)
    halving = max(h for h in HALVINGS if h <= today)
    hd = dt.date.fromisoformat(halving)
    since_halving = (t - hd).days
    win_h = ((hd + dt.timedelta(days=LOW_AFTER_HALVING[0])).isoformat(), (hd + dt.timedelta(days=LOW_AFTER_HALVING[1])).isoformat())
    last_low = dt.date.fromisoformat(CYCLE_LOWS[-1])
    win_l = ((last_low + dt.timedelta(days=LOW_TO_LOW[0])).isoformat(), (last_low + dt.timedelta(days=LOW_TO_LOW[1])).isoformat())
    px = [v for _, v in price]
    ath = max(px)
    ath_date = price[px.index(ath)][0]
    dd = (px[-1] / ath - 1.0) * 100.0
    # the drawdown at each prior low, from the high before it
    prior = []
    for lo in CYCLE_LOWS:
        hit = c.at_or_before(price, lo)
        if hit:
            i = [d for d, _ in price].index(hit[0])
            prior.append(round((px[i] / max(px[:i]) - 1.0) * 100.0))
    return {"halving": halving, "since_halving": since_halving, "window_halving": win_h, "window_low": win_l, "ath": ath, "ath_date": ath_date,
            "since_ath": (t - dt.date.fromisoformat(ath_date)).days, "drawdown": dd, "prior_drawdowns": prior, "next_halving": NEXT_HALVING_EST,
            "since_low": (t - last_low).days}


# ---------------------------------------------------------------- votes
def vote_low_high(x, lo, hi):
    """Bull at or under lo, bear at or over hi (the reset rows)."""
    if x is None:
        return None
    return 1 if x <= lo else -1 if x >= hi else 0


def vote_high_low(x, hi, lo):
    """Bull at or over hi, bear at or under lo (the rows where high is good)."""
    if x is None:
        return None
    return 1 if x >= hi else -1 if x <= lo else 0


def vote_word(v):
    return {1: "Bull", -1: "Bear", 0: "Neutral"}.get(v, "Not scored")


def row(key, now, now_t, vote, read, spark_pts=None, lines=None, src=None, date=None, extra=None, freq="d"):
    spec = next(r for r in ROWS if r[0] == key)
    out = {"key": key, "group": spec[1], "name": spec[2], "unit": spec[3], "bull": spec[4], "bear": spec[5], "feed": spec[6],
           "short": SHORT.get(key, spec[2]), "now": None if now is None else round(now, 3), "now_t": now_t, "vote": vote, "word": vote_word(vote), "read": read,
           "spark": spark_pts or [], "lines": lines or {}, "src": src or spec[6], "date": date, "freq": freq}
    if extra:
        out.update(extra)
    return out


def indicators(D, V, history, today):
    """Every row in ROWS order. D holds the fetched series (btc_chain from Coin Metrics, stables, funding, crypto_fng,
    dxy, cg_global), V the v2 run (regime composites, section 6 markets), history the logged dominance."""
    cm = D.get("btc_chain") or {}
    price = cm.get("price") or []
    rows = []
    asof = price[-1][0] if price else today
    px = [v for _, v in price]
    wk = bucket(price, "week") if price else []
    wv = [v for _, v in wk]
    mo = bucket(price, "month") if price else []
    mv = [v for _, v in mo]

    def none_row(key, why):
        rows.append(row(key, None, "no feed", None, why, date=asof))

    # on-chain resets
    if cm.get("iss_usd") and len(cm["iss_usd"]) > 400:
        pu = puell_series(cm["iss_usd"])
        x = pu[-1][1]
        v = vote_low_high(x, *T["puell"])
        rows.append(row("puell", x, "%.2f" % x, v, {1: "Issuance value has reset to the band every cycle low sat in.", -1: "Issuance value is in the zone the last two tops peaked in.", 0: "Between the reset band and the top zone; the 2022 low read 0.43."}[v],
                        spark(pu), {"bull": T["puell"][0], "bear": T["puell"][1]}, date=pu[-1][0]))
    else:
        none_row("puell", "Coin Metrics issuance missing this run.")
    if cm.get("mvrv") and cm.get("mcap"):
        x = cm["mvrv"][-1][1]
        z = mvrv_z_series(cm["mcap"], cm["mvrv"])
        v = vote_low_high(x, *T["mvrv"])
        rows.append(row("mvrv", x, "%.2f (z %.1f)" % (x, z[-1][1]) if z else "%.2f" % x, v, {1: "Price sits below the average cost basis of every coin, as at every prior low.", -1: "Price is at or beyond the multiple of cost basis that marked the 2021 tops.", 0: "Above cost basis, below the top zone; the lows read 0.56 to 1.00."}[v],
                        spark(cm["mvrv"]), {"bull": T["mvrv"][0], "bear": T["mvrv"][1]}, date=cm["mvrv"][-1][0], extra={"z": round(z[-1][1], 2) if z else None}))
    else:
        none_row("mvrv", "Coin Metrics MVRV missing this run.")
    if cm.get("iss_usd") and cm.get("fee_ntv") and cm.get("mcap") and price:
        tm = multiple(cm["mcap"], thermocap_series(cm["iss_usd"], cm["fee_ntv"], price))
        x = tm[-1][1]
        v = vote_low_high(x, *T["thermo"])
        rows.append(row("thermo", x, "%.1f" % x, v, {1: "Market cap is back near the cumulative miner revenue multiple of the 2018 to 2022 lows.", -1: "Market cap is at a multiple of cumulative miner revenue that only tops have reached.", 0: "Between the lows' band (5 to 7) and the tops' band (29 and up)."}[v],
                        spark(tm), {"bull": T["thermo"][0], "bear": T["thermo"][1]}, date=tm[-1][0]))
    else:
        none_row("thermo", "Coin Metrics issuance or fees missing this run.")
    if cm.get("flow_in") and cm.get("flow_out") and cm.get("supply"):
        ex = exflow_series(cm["flow_in"], cm["flow_out"], cm["supply"])
        vals = [v for _, v in ex[-3 * 365:]]
        p = pctile(vals, ex[-1][1])
        v = vote_low_high(p, *T["exflow"]) if p is not None else None
        rows.append(row("exflow", ex[-1][1], "%+.2f%% (pct %d)" % (ex[-1][1], round(p)) if p is not None else "%+.2f%%" % ex[-1][1], v,
                        {1: "Coins are leaving exchanges at a pace in the bottom fifth of three years: accumulation.", -1: "Coins are moving onto exchanges at a pace in the top fifth of three years: distribution.", 0: "Exchange flows are inside their usual range.", None: "Too little history for the percentile."}[v],
                        spark(ex), {}, date=ex[-1][0], extra={"pct": None if p is None else round(p)}))
    else:
        none_row("exflow", "Coin Metrics exchange flows missing this run.")
    if len(wv) > 20:
        r = rsi(wv)
        x = r[-1]
        v = vote_low_high(x, *T["rsi_w"])
        rows.append(row("rsi_w", x, "%.0f" % x, v, {1: "Weekly momentum has washed out to where every cycle low was made.", -1: "Weekly momentum is at the level of the 2013, 2017 and 2021 tops.", 0: "Weekly momentum is between the wash-out (35) and the top zone (70)."}[v],
                        [round(y, 1) for y in r[-52:] if y is not None], {"bull": T["rsi_w"][0], "bear": T["rsi_w"][1]}, date=wk[-1][0]))
    else:
        none_row("rsi_w", "Not enough weekly closes.")
    if len(mv) > 20:
        r = rsi(mv)
        x = r[-1]
        v = vote_low_high(x, *T["rsi_m"])
        rows.append(row("rsi_m", x, "%.0f" % x, v, {1: "Monthly momentum has cooled to the 2015, 2018 and 2022 lows' level.", -1: "Monthly momentum is where the 2017 and April 2021 tops were made.", 0: "Monthly momentum is between the lows' level (45) and the top zone (75)."}[v],
                        [round(y, 1) for y in r[-36:] if y is not None], {"bull": T["rsi_m"][0], "bear": T["rsi_m"][1]}, date=mo[-1][0]))
    else:
        none_row("rsi_m", "Not enough monthly closes.")

    # cycle clock
    clock = cycle_clock(price, asof) if price else None
    if clock:
        x = clock["since_halving"]
        v = 1 if x >= LOW_AFTER_HALVING[0] else -1
        inside = LOW_AFTER_HALVING[0] <= x <= LOW_AFTER_HALVING[1]
        read = ("Inside the window the prior lows fell in (%s to %s by the halving rule; %s to %s by the low-to-low rule)." % (dl(clock["window_halving"][0]), dly(clock["window_halving"][1]), dl(clock["window_low"][0]), dly(clock["window_low"][1])) if inside
                else "Past the window the prior lows fell in (%s to %s); a low later than every prior cycle." % (dl(clock["window_halving"][0]), dly(clock["window_halving"][1])) if v == 1
                else "Before the window the prior lows fell in (%s to %s): the clock says too early for the low." % (dl(clock["window_halving"][0]), dly(clock["window_halving"][1])))
        rows.append(row("clock", x, "%d days" % x, v, read, [], {}, date=asof, extra={"clock": clock}))
        x = -clock["drawdown"]
        v = vote_high_low(x, T["drawdown"][0], T["drawdown"][1]) if x is not None else None
        rows.append(row("drawdown", x, "%.0f%% from %.0fk" % (x, clock["ath"] / 1000.0), v,
                        {1: "The drawdown matches the prior lows (%s)." % ", ".join("%d%%" % -d for d in clock["prior_drawdowns"]), -1: "The drawdown is shallower than any prior cycle low (%s); a low here would be a first." % ", ".join("%d%%" % -d for d in clock["prior_drawdowns"]), 0: "Deeper than a correction, shallower than the prior lows (%s)." % ", ".join("%d%%" % -d for d in clock["prior_drawdowns"])}[v],
                        [round(-(v_ / max(px[:i + 1]) - 1.0) * 100.0, 1) for i, v_ in enumerate(px)][-364::7], {"bull": T["drawdown"][0], "bear": T["drawdown"][1]}, date=asof))
        y = ago(price, asof, 365)
        x = (px[-1] / y - 1.0) * 100.0 if y else None
        v = vote_low_high(x, *T["roi1y"])
        roi_spark = []
        for d, p_ in wk[-52:]:
            y_ = ago(price, d, 365)
            if y_:
                roi_spark.append(round((p_ / y_ - 1.0) * 100.0, 1))
        rows.append(row("roi1y", x, "%+.0f%%" % x if x is not None else "n/a", v, {1: "A year of losses at the scale that preceded every prior low.", -1: "A year of gains at the scale of the 2025 top and beyond.", 0: "The one-year return is between the lows' reset (under minus 50%) and the top zone (plus 100%).", None: "No price a year back."}[v],
                        roi_spark, {"bull": T["roi1y"][0], "bear": T["roi1y"][1]}, date=asof))
    else:
        for k in ("clock", "drawdown", "roi1y"):
            none_row(k, "No long price series this run.")

    # price against its own history: the Mayer multiple, the 200-week average, the log regression
    if len(px) > 200:
        s200d = c.sma_series(px, 200)
        x = px[-1] / s200d[-1]
        v = vote_low_high(x, *T["mayer"])
        may = [(price[i][0], px[i] / s200d[i]) for i in range(len(px)) if s200d[i]]
        pc = pctile([m for _, m in may], x)
        rows.append(row("mayer", x, ("%.2f (pct %d)" % (x, round(pc))) if pc is not None else "%.2f" % x, v,
                        {1: "Price is at or under 0.8 times its 200-day average, the band every cycle low was made in (0.40 to 0.71).",
                         -1: "Price is half again its 200-day average, the stretch the April 2021 top reached.",
                         0: "Between the lows' band (every cycle low read under 0.72) and the top zone (1.5); the last two tops read 1.47 and 1.18."}[v],
                        [round(m, 2) for _, m in bucket(may, "week")[-52:]], {"bull": T["mayer"][0], "bear": T["mayer"][1]}, date=asof))
    else:
        none_row("mayer", "Not enough daily closes for the 200-day average.")
    if len(wv) > 200:
        s200w = c.sma_series(wv, 200)
        x = wv[-1] / s200w[-1]
        v = vote_low_high(x, *T["ma200w"])
        ratio = [(wk[i][0], wv[i] / s200w[i]) for i in range(len(wv)) if s200w[i]]
        floor_t, floor = "", {}
        if clock and clock.get("ath_date"):
            since = [(d_, r_) for d_, r_ in ratio if d_ >= clock["ath_date"]]
            if since:
                lo_d, lo_v = min(since, key=lambda t_: t_[1])
                n_at = sum(1 for _, r_ in since if r_ <= 1.0)
                floor = {"tagged": bool(n_at), "min": round(lo_v, 2), "min_date": lo_d, "weeks": n_at}
                floor_t = (" The floor was tagged this cycle: %.2f on %s, %d week%s at or under the line." % (lo_v, dly(lo_d), n_at, "" if n_at == 1 else "s")) if n_at else \
                          (" The floor has not been tagged since the %s high; the closest was %.2f on %s." % (dly(clock["ath_date"]), lo_v, dly(lo_d)))
        rows.append(row("ma200w", x, "%.2f" % x, v,
                        {1: "Price is at or under the 200-week average, the line every cycle low has touched or broken.",
                         -1: "Price is more than 2.3 times its 200-week average, the stretch the 2025 top reached.",
                         0: "Above the 200-week floor, below the top zone; at the prior lows this read 0.68 to 1.48."}[v] + floor_t,
                        [round(r_, 2) for _, r_ in ratio[-52:]], {"bull": T["ma200w"][0], "bear": T["ma200w"][1]}, date=wk[-1][0], extra={"floor": floor}))
    else:
        none_row("ma200w", "Not enough weekly closes for the 200-week average.")
    if len(price) > 1000:
        reg = log_regression(price)
        p = reg["pct"]
        v = vote_low_high(p, *T["risk"])
        rows.append(row("risk", p, "pct %d (%+.2f)" % (round(p), reg["res"][-1]), v,
                        {1: "Price sits in the bottom fifth of its distance from the long-run fit: where prior lows sat.", -1: "Price sits in the top fifth of its distance from the fit: where prior tops sat.", 0: "Price is inside the middle of its range around the fit."}[v] + " Our own fit, a cycle position, not a target.",
                        [round(r_, 2) for r_ in reg["res"][-364::7]], {"bull": reg["p20"], "bear": reg["p80"]}, date=asof, extra={"b": round(reg["b"], 2)}))
    else:
        none_row("risk", "Not enough history for the regression.")
    # market, leverage and macro
    st = D.get("stables")
    if st and len(st) > 100:
        x = c.pct(st, 90)
        v = vote_high_low(x, T["stables"][0], T["stables"][1] - 1e-9) if x is not None else None
        if v == -1 and x is not None and x >= 0:
            v = 0
        rows.append(row("stables", x, "%+.1f%% (%.0f bn)" % (x, st[-1][1] / 1e9), v, {1: "Stablecoin supply is growing at a pace that has fed every leg up.", -1: "Stablecoin supply is contracting, as it did through 2022.", 0: "Stablecoin supply is flat to slightly up."}[v],
                        [round(y_ / 1e9, 1) for y_ in [v_ for _, v_ in bucket(st, "week")[-52:]]], {}, date=st[-1][0]))
    else:
        none_row("stables", "DefiLlama missing this run.")
    g = D.get("cg_global")
    dom_hist = sorted((history or {}).get("btc_dom", {}).items())
    if g:
        rows.append(row("dominance", g["btc_dom"], "%.1f%% of %.2f tn" % (g["btc_dom"], g["total_usd"] / 1e12), None,
                        "Shown for context, not scored: no rule with a backtest. Logged nightly from %s (%d sessions so far)." % (dl(dom_hist[0][0]) if dom_hist else dl(g["date"]), len(dom_hist)),
                        [round(v_[0], 1) for _, v_ in dom_hist[-52:]], {}, date=g["date"], extra={"total": g["total_usd"], "eth_dom": g.get("eth_dom")}))
    else:
        none_row("dominance", "CoinGecko missing this run.")
    fu = D.get("funding")
    if fu and len(fu) >= 30:
        x = sum(v_ for _, v_ in fu[-30:]) / 30.0
        v = vote_low_high(x, T["funding"][0] - 1e-9, T["funding"][1])
        if x < 0:
            v = 1
        rows.append(row("funding", x, "%+.1f%% (last %+.1f%%)" % (x, fu[-1][1]), v, {1: "Shorts are paying longs: leverage has flipped to the downside, the way it does at capitulations.", -1: "Longs are paying over 30% a year to stay in: the froth zone.", 0: "Funding is positive and moderate."}[v],
                        [round(v_, 1) for _, v_ in bucket(fu, "week")[-52:]], {"bear": T["funding"][1], "bull": 0.0}, src=D.get("funding_src") or "funding feed", date=fu[-1][0]))
    else:
        none_row("funding", "No funding feed answered this run (Bybit, OKX and Hyperliquid tried in turn).")
    fng = D.get("crypto_fng")
    if fng:
        x = fng[-1][1]
        v = vote_low_high(x, *T["fng"])
        rows.append(row("fng", x, "%.0f (pct %d)" % (x, round(c.percentile([v_ for _, v_ in fng], 3 * 365) or 0)), v, {1: "Extreme fear: the crowd has given up.", -1: "Extreme greed.", 0: "Sentiment is inside its usual range."}[v],
                        [round(v_) for _, v_ in bucket(fng, "week")[-52:]], {"bull": T["fng"][0], "bear": T["fng"][1]}, date=fng[-1][0]))
    else:
        none_row("fng", "alternative.me missing this run.")
    mk = (((V or {}).get("v3") or {}).get("markets") or {}).get("btc") or {}
    d_ = mk.get("div")
    if d_ is not None:
        v = vote_high_low(d_, T["position"][0], T["position"][1])
        rows.append(row("position", d_, "%+.1f" % d_, v, {1: "Asset managers are long against a fearful crowd: the section 6 buy-side divergence.", -1: "The crowd is long while asset managers are leaving: the section 6 sell-side divergence.", 0: "Positioning and sentiment are inside the 1.5 band."}[v] + (" Alert %s." % mk["state"] if mk.get("state") else ""),
                        [], {}, src="section 6 divergence", date=mk.get("date") or asof, extra={"alert": mk.get("state")}, freq="w"))
    else:
        none_row("position", "Section 6 has no bitcoin score this run.")
    dxy = (D.get("dxy") or {}).get("close")
    if dxy:
        x = c.pct(dxy, 63)
        v = vote_low_high(x, *T["dollar"])
        rows.append(row("dollar", x, "%+.1f%%" % x, v, {1: "A falling dollar: the tailwind bitcoin has needed at every cycle turn.", -1: "A rising dollar: the headwind.", 0: "The dollar is flat over three months."}[v],
                        [round(v_, 2) for _, v_ in bucket(dxy, "week")[-52:]], {}, src="Yahoo DX-Y.NYB", date=dxy[-1][0]))
    else:
        none_row("dollar", "Dollar index missing this run.")
    liq = ((((V or {}).get("state") or {}).get("regime") or {}).get("composites") or {}).get("liq") or {}
    if liq.get("value") is not None:
        x = liq["value"]
        v = vote_high_low(x, T["liquidity"][0], T["liquidity"][1])
        rows.append(row("liquidity", x, "%+.1f" % x, v, {1: "Liquidity is expanding: the tide the M2 lead says reaches bitcoin in ten to twelve weeks.", -1: "Liquidity is contracting.", 0: "Liquidity is flat."}[v], [], {}, src="section 1 composite", date=asof))
    else:
        none_row("liquidity", "The liquidity composite is not available this run.")

    # trend and moving averages
    if len(wv) > 50 and px:
        s50 = c.sma_series(wv, 50)
        x = (wv[-1] / s50[-1] - 1.0) * 100.0
        v = 1 if x > 0 else -1
        rows.append(row("ma50w", x, "%+.1f%%" % x, v, {1: "Above the 50-week average, the line every bull market has reclaimed first.", -1: "Below the 50-week average; bear markets live under it."}[v],
                        [round((wv[i] / s50[i] - 1.0) * 100.0, 1) for i in range(len(wv) - 52, len(wv)) if s50[i]], {"bull": 0.0}, date=wk[-1][0]))
        s20, e21 = c.sma_series(wv, 20), ema(wv, 21)
        above = wv[-1] > max(s20[-1], e21[-1])
        below = wv[-1] < min(s20[-1], e21[-1])
        v = 1 if above else -1 if below else 0
        x = (wv[-1] / ((s20[-1] + e21[-1]) / 2.0) - 1.0) * 100.0
        rows.append(row("band", x, "%+.1f%%" % x, v, {1: "Above the band: the bull-market posture.", -1: "Below the band: the bear-market posture.", 0: "Inside the band: the fight."}[v],
                        [round((wv[i] / ((s20[i] + e21[i]) / 2.0) - 1.0) * 100.0, 1) for i in range(len(wv) - 52, len(wv)) if s20[i]], {"bull": 0.0}, date=wk[-1][0]))
    else:
        none_row("ma50w", "Not enough weekly closes.")
        none_row("band", "Not enough weekly closes.")
    if len(px) > 200:
        s50d, s200d = c.sma_series(px, 50), c.sma_series(px, 200)
        x = (s50d[-1] / s200d[-1] - 1.0) * 100.0
        v = 1 if x > 0 else -1
        last = None
        for i in range(len(px) - 1, 200, -1):
            if (s50d[i - 1] > s200d[i - 1]) != (s50d[i] > s200d[i]):
                last = price[i][0]
                break
        rows.append(row("cross", x, "%+.1f%% since %s" % (x, dl(last)) if last else "%+.1f%%" % x, v, {1: "Golden cross: the 50-day is above the 200-day%s." % ((" since " + dly(last)) if last else ""), -1: "Death cross: the 50-day is below the 200-day%s." % ((" since " + dly(last)) if last else "")}[v],
                        [round((s50d[i] / s200d[i] - 1.0) * 100.0, 1) for i in range(len(px) - 364, len(px), 7) if s200d[i]], {"bull": 0.0}, date=asof, extra={"since": last}))
    else:
        none_row("cross", "Not enough daily closes.")
    pi = pi_cycle(price) if px else None
    if pi:
        cutoff = (dt.date.fromisoformat(asof) - dt.timedelta(days=PI_WINDOW)).isoformat()
        v = 1 if (pi["bottom"] and pi["bottom"] >= cutoff) else -1 if (pi["top"] and pi["top"] >= cutoff) else 0
        if v == 1:
            read = "The bottom cross fired on %s, inside the last year." % dly(pi["bottom"])
        elif v == -1:
            read = "The top cross fired on %s, inside the last year." % dly(pi["top"])
        else:
            read = "Neither cross inside the last year (last bottom %s, last top %s). The bottom fires when the 150-day EMA drops %.0f%% to meet 0.745 times the 471-day SMA." % (
                dly(pi["bottom"]) if pi["bottom"] else "none", dly(pi["top"]) if pi["top"] else "none", pi["bottom_gap"] if pi["bottom_gap"] > 0 else 0)
        rows.append(row("pi", pi["bottom_gap"], "bottom gap %+.0f%%, top gap %+.0f%%" % (pi["bottom_gap"], pi["top_gap"]), v, read, [], {}, date=asof, extra={"top": pi["top"], "bottom": pi["bottom"]}))
    else:
        none_row("pi", "Not enough daily closes.")

    # attention: Wikipedia pageviews stand in for search interest, shown for context because the level is in
    # secular decline (the October 2025 high printed near the bottom of its own history) and cannot be thresholded
    wiki = D.get("wiki_btc")
    if wiki and len(wiki) > 400:
        sm = [(wiki[i][0], sum(v_ for _, v_ in wiki[i - 29:i + 1]) / 30.0) for i in range(29, len(wiki))]
        sv = [v_ for _, v_ in sm]
        p3 = c.percentile(sv, 3 * 365)
        tr = sorted(sv[-3 * 365:])
        low20 = tr[int(0.2 * (len(tr) - 1))]
        days_low = sum(1 for v_ in sv[-365:] if v_ <= low20)
        top_t = ""
        if clock and clock.get("ath_date"):
            hit = c.at_or_before(sm, clock["ath_date"])
            if hit:
                tp = pctile([v_ for d_, v_ in sm if d_ <= hit[0]], hit[1])
                if tp is not None:
                    top_t = " The %s high printed at percentile %d of attention to that date." % (dly(clock["ath_date"]), round(tp))
        rows.append(row("attention", sm[-1][1],
                        ("{:,} a day (pct {})".format(int(round(sm[-1][1])), int(round(p3)))) if p3 is not None else "{:,} a day".format(int(round(sm[-1][1]))),
                        None, "Shown for context, not scored: attention is in secular decline, so a level from one cycle says nothing about the next, and the "
                        "30-day average has sat in the bottom fifth of its three-year range on %d of the last 365 days." % days_low + top_t,
                        [round(v_) for _, v_ in bucket(sm, "week")[-52:]], {}, date=sm[-1][0]))
    else:
        none_row("attention", "Wikimedia pageviews missing this run.")
    # the rows with no free feed at all
    for key, why in (("apprank", "App store rankings have no free feed."),
                     ("whales", "Balance cohorts are a paid Coin Metrics tier."),
                     ("etf", "Farside sits behind Cloudflare and the iShares endpoints serve HTML, not JSON; issuer share counts are the probe to run.")):
        none_row(key, why + " Listed so the tally shows what it cannot see.")
    order = {k: i for i, (k, *_r) in enumerate(ROWS)}
    rows.sort(key=lambda r_: order[r_["key"]])
    return rows, clock


def tally(rows):
    bull = [r["key"] for r in rows if r["vote"] == 1]
    bear = [r["key"] for r in rows if r["vote"] == -1]
    neutral = [r["key"] for r in rows if r["vote"] == 0]
    unscored = [r["key"] for r in rows if r["vote"] is None]
    gap = len(bull) - len(bear)
    lean = "bull" if gap >= LEAN_GAP else "bear" if gap <= -LEAN_GAP else "split"
    return {"bull": bull, "bear": bear, "neutral": neutral, "unscored": unscored, "scored": len(bull) + len(bear) + len(neutral), "gap": gap, "lean": lean}


def names(keys):
    return [SHORT.get(k, k) for k in keys]


def read_text(t, rows, clock):
    """The one-paragraph rule-based read above the table."""
    by = {r["key"]: r for r in rows}
    missing = [k for k in ("puell", "mvrv", "rsi_w", "rsi_m", "mayer", "drawdown", "roi1y", "pi") if by.get(k) and by[k]["vote"] == 0]
    parts = ["%d of %d scored indicators lean bull, %d bear, %d neutral: %s." % (len(t["bull"]), t["scored"], len(t["bear"]), len(t["neutral"]),
             {"bull": "the tally leans bull", "bear": "the tally leans bear", "split": "a split, as close to a coin flip as the rules get"}[t["lean"]])]
    if t["bull"]:
        parts.append("Bull: " + ", ".join(names(t["bull"])) + ".")
    if t["bear"]:
        parts.append("Bear: " + ", ".join(names(t["bear"])) + ".")
    if missing:
        parts.append("Resets still missing: " + ", ".join(names(missing)) + ".")
    fl = (by.get("ma200w") or {}).get("floor") or {}
    if fl.get("tagged"):
        parts.append("One reset is already in: price tagged the 200-week average at %.2f on %s, %d week%s at or under the line." % (
            fl["min"], dly(fl["min_date"]), fl["weeks"], "" if fl["weeks"] == 1 else "s"))
    if clock:
        parts.append("Clock: %d days since the halving, %d%% below the high of %s." % (clock["since_halving"], round(-clock["drawdown"]), dl(clock["ath_date"])))
    return " ".join(parts)


# ---------------------------------------------------------------- charts
def band_points(price, reg, start="2012-01-01"):
    """Weekly price with the fit and the 20th and 80th residual band, for the log chart."""
    out = []
    for d, p in bucket([x for x in price if x[0] >= start], "week"):
        f = fit_at(reg, d)
        out.append([d, round(p, 2), round(f), round(f * math.exp(reg["p20"])), round(f * math.exp(reg["p80"]))])
    return out


def cycle_points(price, days=1460):
    """Price relative to the halving-day price, one point a week, per halving cycle."""
    out = []
    px = dict(price)
    for h in HALVINGS:
        base = c.at_or_before(price, h)
        if not base:
            continue
        hd = dt.date.fromisoformat(h)
        pts = []
        for k in range(0, days + 1, 7):
            d = (hd + dt.timedelta(days=k)).isoformat()
            hit = c.at_or_before(price, d)
            if not hit or hit[0] < h or (dt.date.fromisoformat(d) - dt.date.fromisoformat(hit[0])).days > 6:
                break
            pts.append([k, round(hit[1] / base[1], 4)])
        out.append({"halving": h, "label": h[:4], "pts": pts})
    return out


# ---------------------------------------------------------------- run
def strip_items(D, clock, rows):
    cm = D.get("btc_chain") or {}
    price = cm.get("price") or []
    if not price:
        return {}
    by = {r["key"]: r for r in rows}
    asof = price[-1][0]
    out = {"price": price[-1][1], "date": asof}
    for k, n in (("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)):
        y = ago(price, asof, n)
        out[k] = round((price[-1][1] / y - 1.0) * 100.0, 1) if y else None
    if clock:
        out.update({"drawdown": round(clock["drawdown"], 1), "ath": clock["ath"], "ath_date": clock["ath_date"], "since_halving": clock["since_halving"], "since_ath": clock["since_ath"]})
    for k in ("dominance", "fng", "funding"):
        if by.get(k) and by[k]["now"] is not None:
            out[k] = by[k]["now"]
    return out


def run(D, V, prev_state, today, first_run, history):
    rows, clock = indicators(D, V, history, today)
    t = tally(rows)
    prev = (prev_state or {}).get("v5") or {}
    st = det.confirm_state(prev.get("lean"), t["lean"], today, first_run or not prev)
    price = ((D.get("btc_chain") or {}).get("price")) or []
    charts = {}
    if len(price) > 1000:
        reg = log_regression(price)
        charts = {"band": band_points(price, reg), "cycles": cycle_points(price), "halvings": HALVINGS, "fit_b": round(reg["b"], 2)}
    state = {"lean": st, "votes": {r["key"]: r["vote"] for r in rows}, "tally": {"bull": len(t["bull"]), "bear": len(t["bear"]), "neutral": len(t["neutral"])}, "asof": price[-1][0] if price else today}
    return {"rows": rows, "tally": t, "lean": st, "clock": clock, "charts": charts, "strip": strip_items(D, clock, rows), "read": read_text(t, rows, clock), "state": state,
            "asof": price[-1][0] if price else today}


def log_dominance(history, g, keep=1500):
    """Dominance and total cap by date, one entry per day, kept in the state."""
    h = dict((history or {}).get("btc_dom", {}))
    if g:
        h[g["date"]] = [round(g["btc_dom"], 2), round(g["total_usd"] / 1e9, 1)]
    return {d: h[d] for d in sorted(h)[-keep:]}


def change_entries(prev_state, cur, t):
    """Lean flips (must when bull and bear swap, notable otherwise), vote flips (must for the once-a-cycle rows, notable
    to bull or bear, FYI to neutral). Nothing on the first run."""
    out = []
    p = (prev_state or {}).get("v5") or {}
    if not p or not cur:
        return out
    pl, cl = (p.get("lean") or {}).get("state"), (cur.get("lean") or {}).get("state")
    if pl and cl and pl != cl:
        tier = "must" if {pl, cl} == {"bull", "bear"} else "note"
        out.append(ch.entry(t, tier, "bitcoin", "bitcoin.html#tally", "Bitcoin tally moved from %s to %s (%d bull, %d bear, %d neutral)." % (pl, cl, cur["tally"]["bull"], cur["tally"]["bear"], cur["tally"]["neutral"]), "btc.lean"))
    n = {r[0]: r[2] for r in ROWS}
    for key, v in (cur.get("votes") or {}).items():
        old = (p.get("votes") or {}).get(key)
        if old is None or v is None or old == v:
            continue
        tier = "must" if key in MUST_ROWS else "note" if v != 0 else "fyi"
        out.append(ch.entry(t, tier, "bitcoin", "bitcoin.html#tally", "%s flipped from %s to %s." % (n.get(key, key), vote_word(old).lower(), vote_word(v).lower()), "btc.vote." + key))
    return out


def block(R, now):
    """The v2.bitcoin block the page reads."""
    if not R:
        return None
    lean = R["lean"]
    return {"asof": R["asof"], "asofLabel": dly(R["asof"]), "rows": R["rows"], "groups": GROUPS, "tally": {"bull": R["tally"]["bull"], "bear": R["tally"]["bear"], "neutral": R["tally"]["neutral"], "unscored": R["tally"]["unscored"], "scored": R["tally"]["scored"], "gap": R["tally"]["gap"], "raw": R["tally"]["lean"]},
            "lean": {"state": lean["state"], "since": lean["since"], "raw": lean["raw"], "raw_count": lean["raw_count"]}, "read": R["read"], "clock": R["clock"], "strip": R["strip"], "charts": R["charts"],
            "thresholds": {k: list(v) for k, v in T.items()}, "lean_gap": LEAN_GAP, "generated": now.isoformat(timespec="minutes")}

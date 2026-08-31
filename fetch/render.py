"""Turn fetched series into the display-ready entries the page binds to.

Output shapes (all keyed by the data attributes in index.html):
  tile   {"kind":"tile","val":html,"delta":{"t":str,"dir":"up|down|flat","vs":str},"spark":[..],"unit":str,"src":str,"dl":str}
  strip  {"kind":"strip","val":html,"d":{"t":str,"dir":..},"src":str,"dl":str}
  cell   {"t":str,"s":1|0|-1}   with row-level provenance in meta[prefix] = {"src":..,"dl":..}
  rank   {"price":float,"rules":{"T":..,"M":..,"X":..,"H":..,"B":..},"tags":str,"mom":str,"src":..,"dl":..}

Strings use an ASCII minus for negatives and no dash separators anywhere (house rule).
"""
import datetime as dt
import math

from . import compute as c
from .catalog import BAHT_WEIGHT_OZ, RANKING, YAHOO

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ---------------------------------------------------------------- formatting
def f_num(x, dp=0):
    s = "{:,.{dp}f}".format(abs(x), dp=dp)
    return ("-" if x < 0 else "") + s


def f_signed(x, dp=1, unit=""):
    if x is None:
        return None
    r = round(x, dp)
    if r == 0:
        r = 0.0
    return ("+" if r > 0 else "-" if r < 0 else "") + "{:,.{dp}f}".format(abs(r), dp=dp) + unit


def f_pct(x, dp=1):
    return f_signed(x, dp, "%")


def f_bp(x, dp=0):
    return f_signed(x, dp, " bp")


def f_money_b(x):
    """Signed billions: +$62B, -$0.4B."""
    if x is None:
        return None
    dp = 1 if abs(x) < 10 else 0
    return ("+" if x >= 0 else "-") + "$" + "{:,.{dp}f}".format(abs(x), dp=dp) + "B"


def f_k(x):
    return "%.1fk" % (x / 1000.0) if x >= 10000 else f_num(x)


def sgn(x, eps=1e-9):
    if x is None:
        return 0
    return 1 if x > eps else -1 if x < -eps else 0


def dir3(x, eps=1e-9):
    return {1: "up", -1: "down", 0: "flat"}[sgn(x, eps)]


def cell(t, s=0):
    return None if t is None else {"t": t, "s": s}


def hcell(t, h, s=0):
    """A cell with markup (the loader uses h when present, t is the plain fallback)."""
    return {"t": t, "h": h, "s": s}


def pcell(x, dp=1):
    return None if x is None else cell(f_pct(x, dp), sgn(x, 0.05 if dp == 1 else 0.005))


def bcell(x):
    return None if x is None else cell(f_bp(x), sgn(x, 0.5))


LAST_DATE = {}      # set by dl(): the ISO date behind the label most recently formatted


def dl(date, freq="d"):
    """Date label: '28 Aug' for daily ('d') and weekly ('w') readings, 'Jul 2026' for monthly ('m').
    freq=True is accepted as monthly for brevity at the call sites."""
    if freq is True:
        freq = "m"
    d = dt.date.fromisoformat(date)
    if freq == "q":
        label = "Q%d %d" % ((d.month - 1) // 3 + 1, d.year)
    elif freq == "m":
        label = "%s %d" % (MONTHS[d.month - 1], d.year)
    else:
        label = "%d %s" % (d.day, MONTHS[d.month - 1])
    LAST_DATE[label] = (date, freq)
    return label


def month_label(date):
    d = dt.date.fromisoformat(date)
    return "%s %d" % (MONTHS[d.month - 1], d.year)


def month_short(ym):
    return MONTHS[int(ym[5:7]) - 1]


def qlabel(date):
    return "Q%d" % ((int(date[5:7]) - 1) // 3 + 1)


def month_end(date):
    d = dt.date.fromisoformat(date)
    return ((d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)).isoformat()


def stamp(entry, dl_):
    """Attach the ISO date and refresh class behind a date label."""
    d, f = LAST_DATE.get(dl_, (None, "d"))
    entry["date"], entry["freq"] = d, f
    return entry


def tile(val, delta_t, delta_dir, vs, spark, unit, src, dl_):
    return stamp({"kind": "tile", "val": val, "delta": {"t": delta_t, "dir": delta_dir, "vs": vs},
                  "spark": [round(v, 3) for v in spark], "unit": unit, "src": src, "dl": dl_}, dl_)


def strip(val, d_t, d_dir, src, dl_):
    return stamp({"kind": "strip", "val": val, "d": {"t": d_t, "dir": d_dir}, "src": src, "dl": dl_}, dl_)


def small(text):
    return "<small>%s</small>" % text


# ---------------------------------------------------------------- collector
class Out(object):
    def __init__(self):
        self.cells, self.meta, self.rank, self.errors, self.v2 = {}, {}, {}, [], {}

    def put(self, key, entry):
        if entry is not None:
            self.cells[key] = entry

    def row(self, prefix, src, dl_):
        self.meta[prefix] = stamp({"src": src, "dl": dl_}, dl_)

    def guard(self, name, fn):
        try:
            fn()
        except Exception as e:      # noqa: BLE001, one bad panel must not sink the run
            self.errors.append("%s: %s: %s" % (name, type(e).__name__, e))


# ---------------------------------------------------------------- accessors
def S(D, k):
    return D[k]


def P(D, k):
    return D[k]["close"]


def A(D, k):
    return D[k]["adj"]


def yoy_series(s, k=12):
    return [(s[i][0], (s[i][1] / s[i - k][1] - 1.0) * 100.0) for i in range(k, len(s)) if s[i - k][1]]


def diff_series(a, b, scale=1.0):
    """a minus b on a's dates, b taken at or before each date."""
    out = []
    for d, v in a:
        w = c.at_or_before(b, d)
        if w:
            out.append((d, (v - w[1]) * scale))
    return out


def yahoo_src(D, k):
    return "Yahoo " + YAHOO[k]


# ---------------------------------------------------------------- 1 liquidity
def liquidity(D, o):
    def m2_us():
        y = yoy_series(S(D, "m2"))
        ch = c.change(y, 3)
        o.put("liq.m2_us", tile(f_pct(y[-1][1]), f_signed(ch, 1, " pt"), dir3(ch, 0.05), "vs 3 months ago",
                                c.sample_points(y, 12), "%", "FRED M2SL", dl(y[-1][0], True)))
    o.guard("liq.m2_us", m2_us)

    def real_m2():
        r = diff_series(yoy_series(S(D, "m2")), yoy_series(S(D, "cpi")))
        ch = c.change(r, 3)
        o.put("liq.real_m2", tile(f_pct(r[-1][1]), f_signed(ch, 1, " pt"), dir3(ch, 0.05), "vs 3 months ago",
                                  c.sample_points(r, 12), "%", "FRED M2SL, CPIAUCSL", dl(r[-1][0], True)))
        o.put("strip.real_m2", strip(f_pct(r[-1][1]), "M2 minus CPI", dir3(ch, 0.05), "FRED", dl(r[-1][0], True)))
    o.guard("liq.real_m2", real_m2)

    def netliq():
        w, t, r = S(D, "walcl"), S(D, "tga"), S(D, "rrp")
        nl = []
        for d, v in w:
            tv, rv = c.at_or_before(t, d), c.at_or_before(r, d)
            if tv and rv:
                nl.append((d, v / 1000.0 - tv[1] / 1000.0 - rv[1]))      # billions
        ch = c.change(nl, 4)
        o.put("liq.netliq", tile("$%.2f%s" % (nl[-1][1] / 1000.0, small("T")), f_money_b(ch), dir3(ch, 1), "4 weeks",
                                 [v / 1000.0 for v in c.sample_points(nl, 12)], "T", "FRED WALCL, WTREGEN, RRPONTSYD", dl(nl[-1][0], "w")))
        o.put("strip.netliq", strip("$%.2fT" % (nl[-1][1] / 1000.0), "%s, 4w" % f_money_b(ch), dir3(ch, 1), "FRED", dl(nl[-1][0], "w")))
    o.guard("liq.netliq", netliq)

    def walcl():
        w = [(d, v / 1000.0) for d, v in S(D, "walcl")]
        ch = c.change(w, 4)
        vs = "4 weeks" + (", runoff ended" if abs(ch) < 15 else "")
        o.put("liq.walcl", tile("$%.2f%s" % (w[-1][1] / 1000.0, small("T")), f_money_b(ch), dir3(ch, 5), vs,
                                [v / 1000.0 for v in c.sample_points(w, 12)], "T", "FRED WALCL", dl(w[-1][0], "w")))
    o.guard("liq.walcl", walcl)

    def rrp():
        r = S(D, "rrp")
        wk = [(d, v) for d, v in r]
        ch = c.change(r, 20)
        v = r[-1][1]
        val = ("$%.1f" % v if v < 100 else "$%s" % f_num(v)) + small("B")
        o.put("liq.rrp", tile(val, f_money_b(ch), dir3(ch, 1), "4 weeks" + (", at the floor" if v < 50 else ""),
                              c.sample_points(wk, 12, "week"), "B", "FRED RRPONTSYD", dl(r[-1][0])))
    o.guard("liq.rrp", rrp)

    def tga():
        t = [(d, v / 1000.0) for d, v in S(D, "tga")]
        ch = c.change(t, 4)
        o.put("liq.tga", tile("$%.2f%s" % (t[-1][1] / 1000.0, small("T")), f_money_b(ch), dir3(ch, 5),
                              "4 weeks, " + ("a drain" if ch > 0 else "a release"),
                              [v / 1000.0 for v in c.sample_points(t, 12)], "T", "FRED WTREGEN", dl(t[-1][0], "w")))
    o.guard("liq.tga", tga)

    def bankcredit():
        y = yoy_series(S(D, "bankcredit"), 52)
        ch = c.change(y, 13)
        o.put("liq.bankcredit", tile(f_pct(y[-1][1]), f_signed(ch, 1, " pt"), dir3(ch, 0.05), "vs 3 months ago",
                                     c.sample_points(y, 12, "month"), "%", "FRED TOTBKCR", dl(y[-1][0], "w")))
    o.guard("liq.bankcredit", bankcredit)

    def reserves():
        r = [(d, v / 1e6) for d, v in S(D, "reserves")]        # trillions
        gdp = S(D, "gdp")[-1][1] / 1000.0                       # trillions, annualized
        share = r[-1][1] / gdp * 100.0
        vs = "ample" if share >= 10 else "getting close to scarce" if share >= 9 else "scarce"
        o.put("liq.reserves", tile("$%.2f%s" % (r[-1][1], small("T")), "%.1f%% of GDP" % share, "flat", vs,
                                   c.sample_points(r, 12), "T", "FRED WRESBAL, GDP", dl(r[-1][0], "w")))
    o.guard("liq.reserves", reserves)

    def sofr_iorb():
        s = diff_series(S(D, "sofr"), S(D, "iorb"), 100.0)
        recent = [v for _, v in s[-5:]]
        tight = max(abs(v) for v in recent) >= 10
        o.put("liq.sofr_iorb", tile("%s %s" % (f_signed(s[-1][1], 0), small("bp")), "tight" if tight else "calm",
                                    "up" if tight else "flat", "daily", c.sample_points(s, 12), " bp", "FRED SOFR, IORB", dl(s[-1][0])))
    o.guard("liq.sofr_iorb", sofr_iorb)

    def bills():
        s = S(D, "bills_share")
        ch = c.change(s, 12)
        o.put("liq.bills", tile("%.1f%%" % s[-1][1], f_signed(ch, 1, " pt"), dir3(ch, 0.05), "vs a year ago",
                                c.sample_points(s, 12), "%", "Treasury FiscalData MSPD", dl(s[-1][0], True)))
    o.guard("liq.bills", bills)

    def fiscal():
        m, gdp = S(D, "deficit"), S(D, "gdp")            # $M monthly (negative is a deficit); $B annualized
        pct_gdp = []
        for d, tot in c.rolling_sum(m, 12):
            g = c.at_or_before(gdp, d)
            if g:
                pct_gdp.append((d, -tot / 1000.0 / g[1] * 100.0))
        imp = [(pct_gdp[i][0], pct_gdp[i][1] - pct_gdp[i - 12][1]) for i in range(12, len(pct_gdp))]
        o.put("liq.fiscal", tile("%s%s" % (f_signed(imp[-1][1], 1), small("% GDP")), "deficit %.1f%% of GDP" % pct_gdp[-1][1],
                                 dir3(imp[-1][1], 0.1), "12-month sum", c.sample_points(imp, 12), "", "FRED MTSDS133FMS, GDP", dl(imp[-1][0], True)))
    o.guard("liq.fiscal", fiscal)

    def m2_big3():
        us, ez, jp = dict(S(D, "m2")), dict(S(D, "ez_m2")), S(D, "jp_m2")     # $B; EUR millions; 100 million yen
        eur, jpy = P(D, "eurusd"), P(D, "usdjpy")
        tot = []
        for d, v in jp:
            fx, jf = c.at_or_before(eur, month_end(d)), c.at_or_before(jpy, month_end(d))
            if d in us and d in ez and fx and jf:
                tot.append((d, us[d] / 1000.0 + ez[d] * fx[1] / 1e6 + v * 1e8 / jf[1] / 1e12))     # $T
        y = yoy_series(tot)
        ch = c.change(y, 3)
        src = "FRED M2SL; ECB BSI; BoJ MD02; Yahoo FX"
        o.put("liq.m2_global", tile(f_pct(y[-1][1]), f_signed(ch, 1, " pt"), dir3(ch, 0.05), "vs 3 months ago, $%.1fT" % tot[-1][1],
                                    c.sample_points(y, 12), "%", src, dl(y[-1][0], True)))
        o.put("strip.m2_global", strip(f_pct(y[-1][1]), "US, euro area, Japan", dir3(ch, 0.05), src, dl(y[-1][0], True)))
    o.guard("liq.m2_global", m2_big3)

    def big3():
        boj, fed, ecb = S(D, "boj_assets"), S(D, "walcl"), S(D, "ecb_assets")
        eur, jpy = P(D, "eurusd"), P(D, "usdjpy")
        tot = []
        for d, v in boj:
            day = dt.date.fromisoformat(d)
            end = (day.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            e = end.isoformat()
            f, ec, fx, jp = c.at_or_before(fed, e), c.at_or_before(ecb, e), c.at_or_before(eur, e), c.at_or_before(jpy, e)
            if f and ec and fx and jp:
                tot.append((d, f[1] / 1e6 + ec[1] * fx[1] / 1e6 + v * 1e8 / jp[1] / 1e12))
        y = c.pct(tot, 12)
        o.put("liq.big3", tile("$%.1f%s" % (tot[-1][1], small("T")), "%s YoY" % f_pct(y), dir3(y, 0.05), "Fed, ECB, BoJ in dollars",
                               c.sample_points(tot, 12), "T", "FRED WALCL, JPNASSETS; ECB; Yahoo FX", dl(tot[-1][0], True)))
    o.guard("liq.big3", big3)


# ---------------------------------------------------------------- 2 rates
def rates(D, o):
    def pct_tile(key, skey, src, vs="1 month", strip_key=None, strip_vs="1m", dp=2):
        s = S(D, skey)
        ch = c.change(s, 21) * 100.0
        o.put(key, tile("%.*f%%" % (dp, s[-1][1]), f_bp(ch), dir3(ch, 0.5), vs, c.sample_points(s, 12, "month"), "%", src, dl(s[-1][0])))
        if strip_key:
            o.put(strip_key, strip("%.*f%%" % (dp, s[-1][1]), "%s, %s" % (f_bp(ch), strip_vs), dir3(ch, 0.5), src, dl(s[-1][0])))

    def ffu():
        s = S(D, "ffu")
        changed = None
        for i in range(len(s) - 1, 0, -1):
            if s[i][1] != s[i - 1][1]:
                changed = (s[i][0], s[i][1] - s[i - 1][1])
                break
        if changed and (dt.date.fromisoformat(s[-1][0]) - dt.date.fromisoformat(changed[0])).days <= 45:
            t, d = ("cut %d bp" if changed[1] < 0 else "hike %d bp") % abs(round(changed[1] * 100)), ("down" if changed[1] < 0 else "up")
        else:
            t, d = "hold", "flat"
        vs = "since %s" % dl(changed[0], True) if changed else ""
        o.put("rt.ffu", tile("%.2f%%" % s[-1][1], t, d, vs, c.sample_points(s, 12, "month"), "%", "FRED DFEDTARU", dl(s[-1][0])))
    o.guard("rt.ffu", ffu)

    def cuts():
        ff, effr = P(D, "ff12"), S(D, "effr")
        cs = []
        for d, p in ff:
            e = c.at_or_before(effr, d)
            if e:
                cs.append((d, (e[1] - (100.0 - p)) / 0.25))
        n = cs[-1][1]
        bp = abs(round(n * 25))
        sym = D["ff12_sym"]
        month = MONTHS["FGHJKMNQUVXZ".index(sym[2])] + " 20" + sym[3:5]
        val = "%.1f %s" % (abs(n), small("cuts" if n >= 0 else "hikes"))
        ch = c.change(cs, 21)
        o.put("rt.cuts", tile(val, f_signed(ch, 1, " cuts"), dir3(ch, 0.05), "vs 1 month ago; %d bp of %s by %s" % (bp, "cuts" if n >= 0 else "hikes", month),
                              c.sample_points(cs, 12, "week"), "", "Yahoo " + sym + ", FRED EFFR", dl(cs[-1][0])))
        d = "%.1f %s priced, 12m" % (abs(n), "cuts" if n >= 0 else "hikes")
        o.put("strip.ff", strip("%.2f%%" % S(D, "ffu")[-1][1], d, "flat", "FRED, Yahoo", dl(cs[-1][0])))
    o.guard("rt.cuts", cuts)

    o.guard("rt.dgs2", lambda: pct_tile("rt.dgs2", "dgs2", "FRED DGS2"))
    o.guard("rt.dgs10", lambda: pct_tile("rt.dgs10", "dgs10", "FRED DGS10"))
    o.guard("rt.real10", lambda: pct_tile("rt.real10", "dfii10", "FRED DFII10", "1 month, gold tailwind" if c.change(S(D, "dfii10"), 21) < 0 else "1 month, gold headwind",
                                          "strip.real10", "1m"))
    o.guard("rt.be10", lambda: pct_tile("rt.be10", "t10yie", "FRED T10YIE"))

    def us10y_strip():
        s = S(D, "dgs10")
        ch = c.change(s, 5) * 100.0
        o.put("strip.us10y", strip("%.2f%%" % s[-1][1], "%s, 1w" % f_bp(ch), dir3(ch, 0.5), "FRED DGS10", dl(s[-1][0])))
    o.guard("strip.us10y", us10y_strip)

    def curve(key, skey, src):
        s = [(d, v * 100.0) for d, v in S(D, skey)]
        ch = c.change(s, 21)
        word = "steepening" if ch > 0.5 else "flattening" if ch < -0.5 else "unchanged"
        o.put(key, tile("%s %s" % (f_signed(s[-1][1], 0), small("bp")), word, dir3(ch, 0.5), "%s, 1m" % f_bp(ch),
                        c.sample_points(s, 12, "month"), " bp", src, dl(s[-1][0])))
    o.guard("rt.s2s10", lambda: curve("rt.s2s10", "t10y2y", "FRED T10Y2Y"))
    o.guard("rt.s3m10", lambda: curve("rt.s3m10", "t10y3m", "FRED T10Y3M"))

    def f5y5y():
        s = S(D, "t5yifr")
        ch = c.change(s, 21) * 100.0
        v = s[-1][1]
        word, d = ("anchored", "flat") if 2.1 <= v <= 2.6 else (("drifting up", "up") if v > 2.6 else ("drifting down", "down"))
        o.put("rt.f5y5y", tile("%.2f%%" % v, word, d, "%s, 1m" % f_bp(ch), c.sample_points(s, 12, "month"), "%", "FRED T5YIFR", dl(s[-1][0])))
    o.guard("rt.f5y5y", f5y5y)

    def tp10():
        s = S(D, "tp10")
        ch = c.change(s, 21) * 100.0
        o.put("rt.tp10", tile("%s%%" % f_signed(s[-1][1], 2), f_bp(ch), dir3(ch, 0.5), "1 month, Kim-Wright model",
                              c.sample_points(s, 12, "month"), "%", "FRED THREEFYTP10", dl(s[-1][0], "w")))
        o.put("strip.tp10", strip("%s%%" % f_signed(s[-1][1], 2), "%s, 1m" % f_bp(ch), dir3(ch, 0.5), "FRED THREEFYTP10", dl(s[-1][0], "w")))
    o.guard("rt.tp10", tp10)

    def spread(key, skey, src, tight, stress, strip_key=None):
        s = [(d, v * 100.0) for d, v in S(D, skey)]
        v = s[-1][1]
        p = c.percentile(c.vals(s), 3 * 252)
        word, d = ("tight", "flat") if v < tight else (("stress", "up") if v > stress else ("normal", "flat"))
        vs = "3y percentile %d" % round(p) if p is not None else ""
        o.put(key, tile("%s %s" % (f_num(v), small("bp")), word, d, vs, c.sample_points(s, 12, "month"), " bp", src, dl(s[-1][0])))
        if strip_key:
            o.put(strip_key, strip("%s bp" % f_num(v), "%s, 3y pct %d" % (word, round(p)) if p is not None else word, d, src, dl(s[-1][0])))
    o.guard("rt.hy", lambda: spread("rt.hy", "hy", "FRED BAMLH0A0HYM2", 350, 500, "strip.hy"))
    o.guard("rt.ig", lambda: spread("rt.ig", "ig", "FRED BAMLC0A0CM", 100, 150))
    o.guard("rt.ccc", lambda: spread("rt.ccc", "ccc", "FRED BAMLH0A3HYC", 900, 1200))

    def hy_ig():
        r = c.ratio(S(D, "hy"), S(D, "ig"))
        ch = c.change(r, 21)
        word, d = ("stable", "flat") if abs(ch) < 0.15 else (("IG outperforming HY", "up") if ch > 0 else ("HY outperforming IG", "down"))
        o.put("rt.hy_ig", tile("%.1f%s" % (r[-1][1], small("x")), word, d, "quality preference, 1m", c.sample_points(r, 12, "month"), "x", "FRED", dl(r[-1][0])))
    o.guard("rt.hy_ig", hy_ig)

    def nfci():
        s = S(D, "nfci")
        ch = c.change(s, 4)
        v = s[-1][1]
        o.put("rt.nfci", tile(f_signed(v, 2), f_signed(ch, 2), dir3(ch, 0.01), "1 month, " + ("looser" if ch < 0 else "tighter"),
                              c.sample_points(s, 12), "", "FRED NFCI", dl(s[-1][0], "w")))
        o.put("strip.nfci", strip(f_signed(v, 2), "%s, %s 1m" % ("loose" if v < 0 else "tight", "easing" if ch < 0 else "tightening"), "flat", "FRED NFCI", dl(s[-1][0], "w")))
    o.guard("rt.nfci", nfci)

    def move():
        s = P(D, "move")
        ch = c.change(s, 21)
        v = s[-1][1]
        o.put("rt.move", tile(f_num(v), f_signed(ch, 0), dir3(ch, 0.5), "1 month, " + ("calm" if v < 100 else "elevated" if v < 120 else "stress"),
                              c.sample_points(s, 12, "month"), "", "Yahoo ^MOVE", dl(s[-1][0])))
    o.guard("rt.move", move)

    def vixts():
        j = c.align(P(D, "vix"), P(D, "vix3m"))
        r = [(d, a / b) for d, a, b in j if b]
        v1, v3 = j[-1][1], j[-1][2]
        v = r[-1][1]
        word, d = ("contango", "flat") if v < 1 else ("backwardation", "up")
        o.put("rt.vixts", tile("%.2f" % v, word, d, "VIX %.1f / VIX3M %.1f" % (v1, v3), c.sample_points(r, 12, "week"), "", "Yahoo ^VIX, ^VIX3M", dl(r[-1][0])))
        mood = "calm" if v1 < 20 else "elevated" if v1 < 30 else "stress"
        o.put("strip.vix", strip("%.1f %s" % (v1, small("%.2f" % v)), "%s, %s" % (word, mood), d, "Yahoo ^VIX, ^VIX3M", dl(r[-1][0])))
    o.guard("rt.vixts", vixts)

    def sbcorr():
        spy, tlt = A(D, "spy"), A(D, "tlt")
        now = c.correlation(spy, tlt, 60)
        j = c.align(spy, tlt)
        pts = []
        months = sorted(set(d[:7] for d, _, _ in j))[-12:]
        for m in months:
            sub = [(d, a, b) for d, a, b in j if d[:7] <= m]
            pts.append(c.correlation([(d, a) for d, a, _ in sub], [(d, b) for d, _, b in sub], 60))
        pts[-1] = now
        ago = c.correlation(spy[:-63], tlt[:-63], 60)
        ch = now - ago if ago is not None else None
        o.put("rt.sbcorr", tile(f_signed(now, 2), f_signed(ch, 2), dir3(ch, 0.01), "3 months, 60-day window",
                                [p for p in pts if p is not None], "", "Yahoo SPY, TLT", dl(j[-1][0])))
    o.guard("rt.sbcorr", sbcorr)

    def impcorr():
        s = S(D, "cor3m")
        ch = c.change(s, 21)
        o.put("rt.impcorr", tile("%.1f" % s[-1][1], f_signed(ch, 1), dir3(ch, 0.5), "1 month, COR3M",
                                 c.sample_points(s, 12, "week"), "", "Cboe COR3M", dl(s[-1][0])))
    o.guard("rt.impcorr", impcorr)

    def mtg():
        s = S(D, "mtg")
        ch = c.change(s, 4) * 100.0
        o.put("rt.mtg", tile("%.2f%%" % s[-1][1], f_bp(ch), dir3(ch, 0.5), "1 month" + (", homebuilder tailwind" if ch < 0 else ""),
                             c.sample_points(s, 12, "month"), "%", "FRED MORTGAGE30US", dl(s[-1][0], "w")))
    o.guard("rt.mtg", mtg)

    # v4.1: the two charts of section 2, the curve and the futures path
    def curve_v2():
        blk = curve_block(D)
        if blk:
            o.v2.setdefault("rates", {})["curve"] = blk
    o.guard("rates.curve", curve_v2)

    def path_v2():
        blk = path_block(D)
        if blk:
            o.v2.setdefault("rates", {})["path"] = blk
    o.guard("rates.path", path_v2)


CURVE_TENORS = [("1m", "dgs1mo"), ("3m", "dgs3mo"), ("1y", "dgs1"), ("2y", "dgs2"), ("5y", "dgs5"), ("10y", "dgs10"), ("30y", "dgs30")]


def curve_block(D):
    """The Treasury curve now, a month ago and a year ago on the tenors with a free series; None below four tenors."""
    have = [(lab, k) for lab, k in CURVE_TENORS if D.get(k)]
    if len(have) < 4:
        return None
    end = max(D[k][-1][0] for _, k in have)
    d_end = dt.date.fromisoformat(end)
    m1, y1 = (d_end - dt.timedelta(days=30)).isoformat(), (d_end - dt.timedelta(days=365)).isoformat()
    tenors, now, a, b = [], [], [], []
    for lab, k in have:
        s = D[k]
        cur, p1, p2 = c.at_or_before(s, end), c.at_or_before(s, m1), c.at_or_before(s, y1)
        if not cur:
            continue
        tenors.append(lab)
        now.append(round(cur[1], 2))
        a.append(round(p1[1], 2) if p1 else None)
        b.append(round(p2[1], 2) if p2 else None)
    if len(tenors) < 4:
        return None
    ids = ", ".join(FRED_ID.get(k, k) for _, k in have)
    return {"tenors": tenors, "now": now, "m1": a, "y1": b, "date": dl(end), "m1_date": dl(m1), "y1_date": "%s %s" % (dl(y1), y1[:4]),
            "src": "FRED " + ids, "dl": dl(end), "iso": end}


def path_block(D):
    """Fed funds path from the futures strip: one implied rate per month, FOMC months marked, the effective rate as the anchor."""
    strip_ = sorted(D.get("ff_strip") or [], key=lambda r: r["ym"])
    if len(strip_) < 6:
        return None
    effr = S(D, "effr")[-1] if D.get("effr") else None
    meetings = set(m["end"][:7] for m in (D.get("fomc_cal") or []) if m.get("scheduled", True))
    pts = [{"ym": r["ym"], "label": "%s %s" % (MONTHS[int(r["ym"][5:7]) - 1], r["ym"][:4]), "rate": round(100.0 - r["close"], 2), "fomc": r["ym"] in meetings}
           for r in strip_]
    last = max(r["date"] for r in strip_)
    out = {"points": pts, "date": dl(last), "iso": last, "src": "Yahoo ZQ fed funds futures" + (", FRED EFFR" if effr else ""), "n": len(pts)}
    if effr:
        out["effr"], out["effr_date"] = round(effr[1], 2), dl(effr[0])
        out["steps"] = round((effr[1] - pts[-1]["rate"]) / 0.25, 1)      # positive = cuts priced by the last month
    return out


FRED_ID = {"dgs1mo": "DGS1MO", "dgs3mo": "DGS3MO", "dgs1": "DGS1", "dgs2": "DGS2", "dgs5": "DGS5", "dgs10": "DGS10", "dgs30": "DGS30"}


# ---------------------------------------------------------------- strip items from prices
def strip_prices(D, o):
    def one(key, ykey, fmt, src):
        s = P(D, ykey)
        ch = c.pct(A(D, ykey), 21)
        o.put(key, strip(fmt(s[-1][1]), "%s, 1m" % f_pct(ch), dir3(ch, 0.05), src, dl(s[-1][0])))
    o.guard("strip.dxy", lambda: one("strip.dxy", "dxy", lambda v: "%.1f" % v, "Yahoo DXY"))
    o.guard("strip.usdjpy", lambda: one("strip.usdjpy", "usdjpy", lambda v: "%.1f" % v, "Yahoo JPY=X"))
    o.guard("strip.gold", lambda: one("strip.gold", "gold", lambda v: f_num(v), "Yahoo GC=F"))
    o.guard("strip.wti", lambda: one("strip.wti", "wti", lambda v: "%.1f" % v, "Yahoo CL=F"))
    o.guard("strip.spx", lambda: one("strip.spx", "spx", lambda v: f_num(v), "Yahoo ^GSPC"))
    o.guard("strip.btc", lambda: one("strip.btc", "btc", lambda v: f_k(v), "Yahoo BTC-USD"))

    def cu_au():
        r = [(d, v * 1000.0) for d, v in c.ratio(P(D, "copper"), P(D, "gold"))]
        ch = c.pct(r, 21)
        o.put("strip.cu_au", strip("%.2f" % r[-1][1], "%s, 1m" % f_pct(ch), dir3(ch, 0.05), "Yahoo HG=F, GC=F", dl(r[-1][0])))
    o.guard("strip.cu_au", cu_au)


# ---------------------------------------------------------------- 3 markets: tables
def price_row(o, prefix, close, adj, level_text, src, dl_, cols):
    """Common table columns from a price series. cols is the subset wanted."""
    x, xl = c.vals(adj), c.vals(close)
    o.row(prefix, src, dl_)
    if "level" in cols:
        o.put(prefix + ".level", cell(level_text))
    for name, n in (("1w", 5), ("1m", 21), ("3m", 63), ("12m", 252)):
        if name in cols:
            o.put(prefix + "." + name, pcell(c.pct(adj, n)))
    if "ytd" in cols:
        o.put(prefix + ".ytd", pcell(c.ytd_pct(adj)))
    if "z" in cols:
        z = c.zscore_return(x)
        o.put(prefix + ".z", cell(f_signed(z, 1)) if z is not None else None)
    if "vol" in cols:
        v = c.realized_vol(x, 63)
        o.put(prefix + ".vol", cell("%d%%" % round(v)) if v is not None else None)
    if "pct" in cols:
        p = c.percentile(xl, 252)
        o.put(prefix + ".pct", cell("%d" % round(p)) if p is not None else None)
    if "trend" in cols:
        a, b = c.above_below(xl, 50), c.above_below(xl, 200)
        o.put(prefix + ".trend", cell("%s / %s" % (a, b)) if a and b else None)
    if "vs200" in cols:
        v = c.vs_sma_pct(xl, 200)
        o.put(prefix + ".vs200", cell(f_signed(v, 0, "%"), sgn(v, 0.5)) if v is not None else None)


def yield_row(o, prefix, s, src, cols):
    x = c.vals(s)
    o.row(prefix, src, dl(s[-1][0]))
    o.put(prefix + ".level", cell("%.2f%%" % x[-1]))
    for name, n in (("1w", 5), ("1m", 21), ("3m", 63), ("12m", 252)):
        if name in cols:
            ch = c.change(s, n)
            o.put(prefix + "." + name, bcell(ch * 100.0) if ch is not None else None)
    if "z" in cols:
        z = c.zscore_change(x)
        o.put(prefix + ".z", cell(f_signed(z, 1)) if z is not None else None)
    if "vol" in cols:
        v = c.realized_vol(x, 63, in_units=True)
        o.put(prefix + ".vol", cell("%d bp" % round(v * 100)) if v is not None else None)
    if "pct" in cols:
        p = c.percentile(x, 252)
        o.put(prefix + ".pct", cell("%d" % round(p)) if p is not None else None)
    if "trend" in cols:
        o.put(prefix + ".trend", cell("%s / %s" % (c.above_below(x, 50), c.above_below(x, 200))))


LEVEL = {
    "spx": lambda v: f_num(v), "ndx": lambda v: f_num(v), "rut": lambda v: f_num(v), "stoxx": lambda v: f_num(v),
    "n225": lambda v: f_num(v), "eem": lambda v: "%.1f" % v, "hyg": lambda v: "%.1f" % v, "gold": lambda v: f_num(v),
    "silver": lambda v: "%.2f" % v, "copper": lambda v: "%.2f" % v, "wti": lambda v: "%.2f" % v, "btc": lambda v: f_k(v),
    "dxy": lambda v: "%.1f" % v, "usdjpy": lambda v: "%.1f" % v, "cew": lambda v: "%.1f" % v,
    "spxew": lambda v: f_num(v), "csi300": lambda v: f_num(v), "hsi": lambda v: f_num(v), "set": lambda v: f_num(v),
    "plat": lambda v: f_num(v), "pall": lambda v: f_num(v), "brent": lambda v: "%.2f" % v, "natgas": lambda v: "%.2f" % v,
    "ironore": lambda v: f_num(v), "eurusd": lambda v: "%.3f" % v, "usdcny": lambda v: "%.2f" % v, "usdthb": lambda v: "%.2f" % v,
}


def scorecard(D, o):
    cols = ("level", "1w", "1m", "3m", "12m", "z", "vol", "pct", "trend")
    for k in ("spx", "ndx", "rut", "stoxx", "n225", "eem", "hyg", "gold", "silver", "copper", "wti", "btc", "dxy", "usdjpy", "cew"):
        o.guard("sc." + k, lambda k=k: price_row(o, "sc." + k, P(D, k), A(D, k), LEVEL[k](P(D, k)[-1][1]), yahoo_src(D, k), dl(P(D, k)[-1][0]), cols))
    o.guard("sc.us10y", lambda: yield_row(o, "sc.us10y", S(D, "dgs10"), "FRED DGS10", cols))


def trend_word(x, n=50, lag=10):
    t = c.ma_trend(x, n, lag)
    if t is None:
        return None
    above, rising = t
    return cell("▲ rising", 1) if (above and rising) else cell("▼ falling", -1) if (not above and not rising) else cell("■ flat", 0)


def currencies(D, o):
    for k in ("dxy", "eurusd", "usdjpy", "usdcny", "usdthb", "cew"):
        def fx(k=k):
            s = P(D, k)
            price_row(o, "fx." + k, s, A(D, k), LEVEL[k](s[-1][1]), yahoo_src(D, k), dl(s[-1][0]), ("level", "1m", "3m"))
            o.put("fx.%s.trend" % k, trend_word(c.vals(s)))
        o.guard("fx." + k, fx)

    def broad():
        s = S(D, "broadusd")
        o.row("fx.broad", "FRED DTWEXBGS", dl(s[-1][0], "w"))
        o.put("fx.broad.level", cell("%.1f" % s[-1][1]))
        o.put("fx.broad.1m", pcell(c.pct(s, 21)))
        o.put("fx.broad.3m", pcell(c.pct(s, 63)))
        o.put("fx.broad.trend", trend_word(c.vals(s)))
    o.guard("fx.broad", broad)


RATIOS = [
    ("cu_au", "copper", "gold", 1000.0, 2), ("au_spx", "gold", "spx", 1.0, 3), ("spy_tlt", "spy", "tlt", 1.0, 2),
    ("hyg_ief", "hyg", "ief", 1.0, 2), ("xly_xlp", "xly", "xlp", 1.0, 2), ("eem_spy", "eem", "spy", 1.0, 3),
    ("btc_au", "btc", "gold", 1.0, 1), ("oil_au", "wti", "gold", 1.0, 4), ("ag_au", "silver", "gold", 1.0, 4),
]


def ratios(D, o):
    for key, a, b, scale, dp in RATIOS:
        def one(key=key, a=a, b=b, scale=scale, dp=dp):
            r = [(d, v * scale) for d, v in c.ratio(P(D, a), P(D, b))]
            o.row("ratio." + key, "Yahoo %s, %s" % (YAHOO[a], YAHOO[b]), dl(r[-1][0]))
            o.put("ratio.%s.level" % key, cell(("%%.%df" % dp) % r[-1][1] + (" oz" if key == "btc_au" else "")))
            o.put("ratio.%s.1m" % key, pcell(c.pct(r, 21)))
            t = c.ma_trend(c.vals(r), 50, 10)
            if t:
                o.put("ratio.%s.trend" % key, cell("▲", 1) if (t[0] and t[1]) else cell("▼", -1) if (not t[0] and not t[1]) else cell("■", 0))
        o.guard("ratio." + key, one)


def rs_cell(r):
    """Relative strength read with the cross date when it is recent."""
    t = c.rs_trend(c.vals(r))
    if t is None:
        return None
    state, since, direction = t
    if since is not None and direction == "up":
        return cell("▲ crossed %s" % dl(r[-1 - since][0]), 1)
    if since is not None and direction == "down":
        return cell("▼ lost %s" % dl(r[-1 - since][0]), -1)
    return {"up": cell("▲ rising", 1), "down": cell("▼ falling", -1), "flat": cell("■ flat", 0)}[state]


def basket(D, keys):
    """Equal-weight total-return index of several ETFs (daily rebalanced)."""
    series = [A(D, k) for k in keys]
    j = c.combine(series, lambda xs: xs)
    out, level = [], 100.0
    for i, (d, xs) in enumerate(j):
        if i:
            prev = j[i - 1][1]
            level *= 1.0 + sum(x / p - 1.0 for x, p in zip(xs, prev)) / len(xs)
        out.append((d, level))
    return out


def factors(D, o):
    pairs = [("value_growth", "iwd", "iwf"), ("small_large", "iwm", "spy"), ("beta_lowvol", "sphb", "splv"),
             ("mom_mkt", "mtum", "spy"), ("qual_mkt", "qual", "spy"), ("eq_cap", "rsp", "spy")]
    for key, a, b in pairs:
        def one(key=key, a=a, b=b):
            r = c.ratio(A(D, a), A(D, b))
            o.row("fac." + key, "Yahoo %s, %s" % (YAHOO[a], YAHOO[b]), dl(r[-1][0]))
            o.put("fac.%s.1m" % key, pcell(c.pct(r, 21)))
            o.put("fac.%s.3m" % key, pcell(c.pct(r, 63)))
            o.put("fac.%s.rs" % key, rs_cell(r))
        o.guard("fac." + key, one)

    def cyc_def():
        r = c.ratio(basket(D, ("xli", "xlb", "xly", "xlf")), basket(D, ("xlp", "xlu", "xlv")))
        o.row("fac.cyc_def", "Yahoo XLI, XLB, XLY, XLF against XLP, XLU, XLV", dl(r[-1][0]))
        o.put("fac.cyc_def.1m", pcell(c.pct(r, 21)))
        o.put("fac.cyc_def.3m", pcell(c.pct(r, 63)))
        o.put("fac.cyc_def.rs", rs_cell(r))
    o.guard("fac.cyc_def", cyc_def)


def precious(D, o):
    cols = ("level", "1w", "1m", "ytd", "vs200")
    for k in ("gold", "silver", "plat", "pall"):
        o.guard("pm." + k, lambda k=k: price_row(o, "pm." + k, P(D, k), A(D, k), LEVEL[k](P(D, k)[-1][1]), yahoo_src(D, k), dl(P(D, k)[-1][0]), cols))

    def gs_ratio():
        r = c.ratio(P(D, "gold"), P(D, "silver"))
        o.row("pm.gs_ratio", "Yahoo GC=F, SI=F", dl(r[-1][0]))
        o.put("pm.gs_ratio.level", cell("%.1f" % r[-1][1]))
        o.put("pm.gs_ratio.1w", cell(f_signed(c.change(r, 5), 1)))
        o.put("pm.gs_ratio.1m", cell(f_signed(c.change(r, 21), 1)))
        base = c.at_or_before(r, "%d-12-31" % (int(r[-1][0][:4]) - 1))
        o.put("pm.gs_ratio.ytd", cell(f_signed(r[-1][1] - base[1], 1)) if base else None)
    o.guard("pm.gs_ratio", gs_ratio)

    def baht_gold():
        b = [(d, v * BAHT_WEIGHT_OZ) for d, v in c.combine([P(D, "gold"), P(D, "usdthb")], lambda xs: xs[0] * xs[1])]
        price_row(o, "pm.baht_gold", b, b, f_num(b[-1][1]), "Yahoo GC=F, THB=X (computed)", dl(b[-1][0]), ("level", "1w", "1m", "ytd"))
    o.guard("pm.baht_gold", baht_gold)


def energy(D, o):
    cols = ("level", "1w", "1m", "ytd", "vs200")
    for k in ("wti", "brent", "natgas"):
        o.guard("en." + k, lambda k=k: price_row(o, "en." + k, P(D, k), A(D, k), LEVEL[k](P(D, k)[-1][1]), yahoo_src(D, k), dl(P(D, k)[-1][0]), cols))

    def crack():
        s = c.combine([P(D, "rbob"), P(D, "heat"), P(D, "wti")], lambda xs: (2 * xs[0] * 42 + xs[1] * 42 - 3 * xs[2]) / 3.0)
        o.row("en.crack", "Yahoo RB=F, HO=F, CL=F (3-2-1, computed)", dl(s[-1][0]))
        o.put("en.crack.level", cell("%.2f" % s[-1][1]))
        o.put("en.crack.1w", cell(f_signed(c.change(s, 5), 2), sgn(c.change(s, 5), 0.005)))
        o.put("en.crack.1m", cell(f_signed(c.change(s, 21), 2), sgn(c.change(s, 21), 0.005)))
    o.guard("en.crack", crack)

    def stock_row(row, key, src):
        s = [(d, v / 1000.0) for d, v in S(D, key)]          # million barrels
        o.row(row, src, dl(s[-1][0], "w"))
        o.put(row + ".level", cell("%.1f mb" % s[-1][1]))
        for name, n in (("1w", 1), ("1m", 4)):
            ch = c.change(s, n)
            o.put(row + "." + name, cell(f_signed(ch, 1, " mb"), sgn(ch, 0.05)) if ch is not None else None)
        base = c.at_or_before(s, "%d-12-31" % (int(s[-1][0][:4]) - 1))
        o.put(row + ".ytd", cell(f_signed(s[-1][1] - base[1], 1, " mb"), sgn(s[-1][1] - base[1], 0.05)) if base else None)
        v = c.vs_sma_pct(c.vals(s), 40)                      # 40 weeks, the 200-day equivalent
        o.put(row + ".vs200", cell(f_signed(v, 0, "%"), sgn(v, 0.5)) if v is not None else None)
    o.guard("en.stocks", lambda: stock_row("en.stocks", "crude_stocks", "EIA WCESTUS1 (commercial crude, excluding SPR)"))
    o.guard("en.spr", lambda: stock_row("en.spr", "spr", "EIA WCSSTUS1 (Strategic Petroleum Reserve)"))

    def rigs():
        s = S(D, "oil_rigs")
        o.row("en.rigs", "EIA monthly rig count (Baker Hughes)", dl(s[-1][0], True))
        o.put("en.rigs.level", cell("%d" % round(s[-1][1])))
        o.put("en.rigs.1w", cell(""))
        ch = c.change(s, 1)
        o.put("en.rigs.1m", cell(f_signed(ch, 0), sgn(ch, 0.5)) if ch is not None else None)
        base = c.at_or_before(s, "%d-12-31" % (int(s[-1][0][:4]) - 1))
        o.put("en.rigs.ytd", cell(f_signed(s[-1][1] - base[1], 0), sgn(s[-1][1] - base[1], 0.5)) if base else None)
        o.put("en.rigs.vs200", cell(""))
    o.guard("en.rigs", rigs)


def industrial(D, o):
    cols = ("level", "1w", "1m", "ytd", "vs200")
    o.guard("im.copper", lambda: price_row(o, "im.copper", P(D, "copper"), A(D, "copper"), LEVEL["copper"](P(D, "copper")[-1][1]), "Yahoo HG=F", dl(P(D, "copper")[-1][0]), cols))
    o.guard("im.ironore", lambda: price_row(o, "im.ironore", P(D, "ironore"), A(D, "ironore"), LEVEL["ironore"](P(D, "ironore")[-1][1]), "Yahoo TIO=F", dl(P(D, "ironore")[-1][0]), cols))
    for k in ("wheat", "corn", "soy"):
        def grain(k=k):
            s = [(d, v / 100.0) for d, v in P(D, k)]        # cents to dollars per bushel
            price_row(o, "im." + k, s, s, "%.2f" % s[-1][1], yahoo_src(D, k), dl(s[-1][0]), cols)
        o.guard("im." + k, grain)

    def cu_au():
        r = [(d, v * 1000.0) for d, v in c.ratio(P(D, "copper"), P(D, "gold"))]
        price_row(o, "im.cu_au", r, r, "%.2f" % r[-1][1], "Yahoo HG=F, GC=F", dl(r[-1][0]), ("level", "1w", "1m", "ytd"))
    o.guard("im.cu_au", cu_au)
    o.guard("im.uranium", lambda: price_row(o, "im.uranium", P(D, "sruuf"), A(D, "sruuf"), "$%.2f" % P(D, "sruuf")[-1][1],
                                            "Yahoo SRUUF (Sprott Physical Uranium Trust, a spot proxy)", dl(P(D, "sruuf")[-1][0]), cols))


def indices(D, o):
    cols = ("level", "1w", "1m", "3m", "ytd", "vs200")
    for k in ("spx", "ndx", "spxew", "rut", "stoxx", "n225", "csi300", "hsi", "eem", "set"):
        o.guard("idx." + k, lambda k=k: price_row(o, "idx." + k, P(D, k), A(D, k), LEVEL[k](P(D, k)[-1][1]), yahoo_src(D, k), dl(P(D, k)[-1][0]), cols))


def sectors(D, o):
    for k in ("xlk", "xlc", "xly", "xlp", "xlv", "xlf", "xli", "xle", "xlb", "xlu", "xlre"):
        def one(k=k):
            s, a = P(D, k), A(D, k)
            o.row("sec." + k, yahoo_src(D, k) + ", SPY", dl(s[-1][0]))
            o.put("sec.%s.1m" % k, pcell(c.pct(a, 21)))
            o.put("sec.%s.3m" % k, pcell(c.pct(a, 63)))
            o.put("sec.%s.rs" % k, rs_cell(c.ratio(a, A(D, "spy"))))
            o.put("sec.%s.ma" % k, cell("%s / %s" % (c.above_below(c.vals(s), 50), c.above_below(c.vals(s), 200))))
        o.guard("sec." + k, one)


def themes(D, o):
    rows = [("smh", "smh"), ("mags", "mags"), ("gdx", "gdx"), ("sil", "sil"), ("ura", "ura"), ("xop", "xop"), ("ita", "ita"),
            ("cibr", "cibr"), ("kbe", "kbe"), ("kre", "kre"), ("xhb", "xhb"), ("xbi", "xbi"), ("staples", "xlp"), ("xlu", "xlu"), ("btc", "btc")]
    for key, k in rows:
        def one(key=key, k=k):
            a = A(D, k)
            o.row("th." + key, yahoo_src(D, k) + ", SPY", dl(a[-1][0]))
            o.put("th.%s.1w" % key, pcell(c.pct(a, 5)))
            o.put("th.%s.1m" % key, pcell(c.pct(a, 21)))
            o.put("th.%s.3m" % key, pcell(c.pct(a, 63)))
            o.put("th.%s.rs" % key, rs_cell(c.ratio(a, A(D, "spy"))))
        o.guard("th." + key, one)


def global_yields(D, o):
    def us():
        s = S(D, "dgs10")
        o.row("gy.us", "FRED DGS10, DFII10", dl(s[-1][0]))
        o.put("gy.us.10y", cell("%.2f%%" % s[-1][1]))
        o.put("gy.us.1m", bcell(c.change(s, 21) * 100.0))
        o.put("gy.us.real", cell("%.2f%%" % S(D, "dfii10")[-1][1]))
    o.guard("gy.us", us)
    for key, yk, ck, name in (("de", "de10", "de_cpi", "IRLTLT01DEM156N"), ("jp", "jp10", "jp_cpi", "IRLTLT01JPM156N"), ("uk", "uk10", "uk_cpi", "IRLTLT01GBM156N")):
        def one(key=key, yk=yk, ck=ck, name=name):
            s = S(D, yk)
            d, v = s[-1]
            o.row("gy." + key, "FRED %s (OECD, monthly)" % name, dl(d, True))
            o.put("gy.%s.10y" % key, cell("%.2f%%" % v))
            o.put("gy.%s.1m" % key, bcell(c.change(s, 1) * 100.0))
            day = dt.date.fromisoformat(d)
            end = ((day.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)).isoformat()
            us10 = c.at_or_before(S(D, "dgs10"), end)
            if us10:
                o.put("gy.%s.spread" % key, bcell((v - us10[1]) * 100.0))
            if ck in D:
                cpi = c.at_or_before(S(D, ck), d)
                if cpi:
                    o.put("gy.%s.real" % key, cell("%.2f%%" % (v - cpi[1])))
        o.guard("gy." + key, one)


STANCE = {
    "easing": ("Easing", '<span class="chip up"><span class="g">\u25bc</span>Easing</span>'),
    "tightening": ("Tightening", '<span class="chip warn"><span class="g">\u25b2</span>Tightening</span>'),
    "hold": ("On hold", '<span class="chip"><span class="g">\u25a0</span>On hold</span>'),
}


def central_banks(D, o):
    """Policy rate, last move and stance from the rate series itself. Stance is a rule: the direction of
    the last move if it came within twelve months of the latest observation, otherwise on hold.
    Next decision and market pricing stay placeholders until the calendar (v4) and OIS feeds exist."""
    def bank(row, key, src, fmt):
        s = S(D, key)
        o.row(row, src, dl(s[-1][0], True))          # a policy rate holds until the next decision; monthly tolerance
        o.put(row + ".rate", cell(fmt(s[-1][1])))
        mv = c.last_change(s)
        if not mv:
            o.put(row + ".last", cell("no change since %s" % s[0][0][:4]))
            o.put(row + ".stance", hcell(*STANCE["hold"]))
            return
        d, delta = mv
        bp = int(round(delta * 100))
        o.put(row + ".last", cell("%s %d bp, %s" % ("Hike" if bp > 0 else "Cut", abs(bp), month_label(d))))
        days = (dt.date.fromisoformat(s[-1][0]) - dt.date.fromisoformat(d)).days
        st = "hold" if days > 365 else "tightening" if bp > 0 else "easing"
        o.put(row + ".stance", hcell(*STANCE[st]))
    o.guard("cb.fed", lambda: bank("cb.fed", "ffu", "FRED DFEDTARU (target range, upper)", lambda v: "%.2f to %.2f" % (v - 0.25, v)))
    o.guard("cb.ecb", lambda: bank("cb.ecb", "ecb_dfr", "FRED ECBDFR (deposit facility)", lambda v: "%.2f" % v))
    o.guard("cb.boj", lambda: bank("cb.boj", "boj_rate", "BIS WS_CBPOL JP (overnight call rate target)", lambda v: "%.2f" % v))
    o.guard("cb.boe", lambda: bank("cb.boe", "boe_rate", "BIS WS_CBPOL GB (Bank Rate)", lambda v: "%.2f" % v))
    o.guard("cb.pboc", lambda: bank("cb.pboc", "pboc_rate", "BIS WS_CBPOL CN (one-year loan prime rate)", lambda v: "%.2f" % v))
    o.guard("cb.bot", lambda: bank("cb.bot", "bot_rate", "BIS WS_CBPOL TH (one-day repo rate)", lambda v: "%.2f" % v))


def growth(D, o):
    def claims():
        s = S(D, "claims4")
        o.row("gp.claims", "FRED IC4WSA", dl(s[-1][0], "w"))
        o.put("gp.claims.now", cell("%dk" % round(s[-1][1] / 1000.0)))
        o.put("gp.claims.prior", cell("%dk" % round(s[-2][1] / 1000.0)))
    o.guard("gp.claims", claims)

    def sahm():
        s = S(D, "sahm")
        o.row("gp.sahm", "FRED SAHMREALTIME", dl(s[-1][0], True))
        o.put("gp.sahm.now", cell("%.2f" % s[-1][1]))
        o.put("gp.sahm.prior", cell("%.2f" % s[-2][1]))
    o.guard("gp.sahm", sahm)

    def gdpnow():
        g, a = S(D, "gdpnow"), S(D, "gdp_actual")
        o.row("gp.gdpnow", "FRED GDPNOW, A191RL1Q225SBEA", dl(g[-1][0], "q"))
        o.put("gp.gdpnow.now", cell("%s %s" % (qlabel(g[-1][0]), f_pct(g[-1][1])), sgn(g[-1][1], 0.05)))
        o.put("gp.gdpnow.prior", cell("%s %s" % (qlabel(a[-1][0]), f_pct(a[-1][1]))))        # the last actual print
    o.guard("gp.gdpnow", gdpnow)

    def cpinow():
        n = S(D, "cpi_nowcast")
        o.row("gp.cpinow", "Cleveland Fed inflation nowcast", dl(n["asof"]))
        o.put("gp.cpinow.now", cell("%s %s" % (month_short(n["month"]), f_pct(n["core_cpi"], 2)), sgn(n["core_cpi"], 0.005)))
        prior = n.get("prior_core_actual")
        o.put("gp.cpinow.prior", cell("%s %s" % (month_short(n["prior_month"]), f_pct(prior, 2))) if prior is not None else cell(""))   # the actual print
    o.guard("gp.cpinow", cpinow)

    def cfnai():
        s = S(D, "cfnai3")
        o.row("gp.cfnai", "FRED CFNAIMA3", dl(s[-1][0], True))
        o.put("gp.cfnai.now", cell(f_signed(s[-1][1], 2), sgn(s[-1][1], 0.005)))
        o.put("gp.cfnai.prior", cell(f_signed(s[-2][1], 2), sgn(s[-2][1], 0.005)))
    o.guard("gp.cfnai", cfnai)

    def payrolls():
        p = S(D, "payrolls")
        d = [(p[i][0], p[i][1] - p[i - 1][1]) for i in range(1, len(p))]
        avg = [(x, v / 3.0) for x, v in c.rolling_sum(d, 3)]
        o.row("gp.payrolls", "FRED PAYEMS (computed)", dl(avg[-1][0], True))
        o.put("gp.payrolls.now", cell(f_signed(avg[-1][1], 0, "k"), sgn(avg[-1][1], 0.5)))
        o.put("gp.payrolls.prior", cell(f_signed(avg[-2][1], 0, "k"), sgn(avg[-2][1], 0.5)))
    o.guard("gp.payrolls", payrolls)


def pct_label(p, span):
    """'10-year percentile 91'; the ends are named so 0 and 100 read as what they are."""
    if p is None:
        return None
    r = int(round(p))
    tail = " (%s low)" % span if r == 0 else " (%s high)" % span if r == 100 else ""
    return "%s percentile %d%s" % (span, r, tail)


def valuation(D, o):
    def pe():
        s = S(D, "spx_pe")
        o.row("val.spx_pe", "multpl (trailing twelve-month P/E)", dl(s[-1][0], True))
        o.put("val.spx_pe.now", cell("%.1fx" % s[-1][1]))
        o.put("val.spx_pe.hist", cell(pct_label(c.percentile(c.vals(s), 120), "10-year")))
    o.guard("val.spx_pe", pe)

    def erp():
        s, y = S(D, "spx_pe"), S(D, "dgs10")
        pts = []
        for d, v in s:
            yv = c.at_or_before(y, month_end(d)) if v else None
            if yv:
                pts.append((d, 100.0 / v - yv[1]))
        o.row("val.erp", "multpl P/E, FRED DGS10 (computed)", dl(pts[-1][0], True))
        o.put("val.erp.now", cell("%s pt" % f_signed(pts[-1][1], 2), sgn(pts[-1][1], 0.005)))
        o.put("val.erp.hist", cell(pct_label(c.percentile(c.vals(pts), 240), "20-year")))
    o.guard("val.erp", erp)


def flows(D, o):
    def mmf():
        m = S(D, "mmf")
        o.row("flow.mmf", "ICI weekly money market fund assets", dl(m["date"], "w"))
        e = cell(f_signed(m["change"], 1), sgn(m["change"], 0.05))
        e["v"] = round(m["change"], 2)
        o.put("flow.mmf.v", e)
        o.put("flow.mmf.total", cell("$%.2fT" % (m["total"] / 1000.0)))
    o.guard("flow.mmf", mmf)


# ---------------------------------------------------------------- the ranking's price side
def ranking(D, o):
    moms, rows = {}, {}
    for key, yk, bk in RANKING:
        def one(key=key, yk=yk, bk=bk):
            adj = A(D, yk)
            x = c.vals(adj)
            if bk == "skip":
                B = None
            else:
                r = c.ratio(adj, A(D, bk)) if bk else c.ratio(A(D, "rsp"), A(D, "spy"))
                B = c.rule_B_ratio(c.vals(r))
            moms[key] = c.momentum_12_1(x)
            rows[key] = {"T": c.rule_T(x), "X": c.rule_X(x), "H": c.rule_H(x), "B": B,
                         "level": x[-1] if x else None,
                         "tags": c.tags(x), "src": yahoo_src(D, yk), "dl": dl(adj[-1][0])}
        o.guard("rank." + key, one)
    M = c.rule_M_ranks(moms)
    for key, r in rows.items():
        rules = {"T": r["T"], "M": M.get(key), "X": r["X"], "H": r["H"], "B": r["B"]}
        o.rank[key] = stamp({"price": c.price_score(rules), "rules": rules, "level": r.get("level"), "tags": ", ".join(r["tags"]),
                             "mom": f_pct(moms[key] * 100.0) if moms.get(key) is not None else "", "src": r["src"], "dl": r["dl"]}, r["dl"])


def render(D, o):
    for fn in (liquidity, rates, strip_prices, scorecard, currencies, ratios, factors, precious, energy, industrial,
               indices, sectors, themes, global_yields, central_banks, growth, valuation, flows, ranking):
        o.guard(fn.__name__, lambda fn=fn: fn(D, o))
    return o


# ---------------------------------------------------------------- v2: regime, detector, conditions
STATE_CHIP = {
    "none": ("Quiet", '<span class="chip"><span class="g">\u25cb</span>Quiet</span>'),
    "watch": ("Watch", '<span class="chip"><span class="g">\u25cf</span>Watch</span>'),
    "watch_exit": ("Watch (exit)", '<span class="chip"><span class="g">\u25cf</span>Watch (exit)</span>'),
    "early": ("Early", '<span class="chip up"><span class="g">\u25b2</span>Early</span>'),
    "developing": ("Developing", '<span class="chip accent"><span class="g">\u25b2</span>Developing</span>'),
    "confirmed": ("Confirmed", '<span class="chip accent" style="font-weight:700"><span class="g">\u25b2</span>Confirmed</span>'),
    "fading": ("Fading", '<span class="chip serious"><span class="g">\u25bc</span>Fading</span>'),
}
QUAD_CHIP = {
    "Leading": '<span class="chip accent"><span class="g">\u25b2</span>Leading</span>',
    "Improving": '<span class="chip up"><span class="g">\u25b2</span>Improving</span>',
    "Weakening": '<span class="chip warn"><span class="g">\u25bc</span>Weakening</span>',
    "Lagging": '<span class="chip serious"><span class="g">\u25bc</span>Lagging</span>',
}
READ_CHIP = {
    "Aligned up": ("chip up", "\u25b2"), "Aligned down": ("chip serious", "\u25bc"),
    "Conditions ahead, up": ("chip accent", "\u25b2"), "Conditions ahead, down": ("chip warn", "\u25bc"),
    "Price ahead, up": ("chip accent", "\u25b2"), "Price ahead, down": ("chip warn", "\u25bc"),
    "Divergence": ("chip warn", "\u25c6"), "Neutral": ("chip", "\u25cf"),
}
FLAG_CHIP = {
    "liquidity": {"expanding": ("chip up", "\u25b2"), "contracting": ("chip serious", "\u25bc"), "flat": ("chip", "\u25cf")},
    "cost": {"easing": ("chip up", "\u25b2"), "tightening": ("chip serious", "\u25bc"), "stable": ("chip", "\u25cf")},
    "risk": {"on": ("chip accent", "\u25cf"), "off": ("chip serious", "\u25bc"), "neutral": ("chip", "\u25cf")},
    "breadth": {"broadening": ("chip up", "\u25b2"), "narrowing": ("chip warn", "\u25b2"), "mixed": ("chip", "\u25cf")},
    "momentum": {"leading": ("chip up", "\u25b2"), "rolling over": ("chip warn", "\u25b2"), "mixed": ("chip", "\u25cf")},
    "dollar": {"weakening": ("chip", "\u25cf"), "strengthening": ("chip", "\u25cf"), "mixed": ("chip", "\u25cf")},
    "credit": {"none": ("chip", "\u25cf"), "rising": ("chip warn", "\u25b2"), "stress": ("chip serious", "\u25bc")},
}
FLAG_NAME = {"liquidity": "Liquidity", "cost": "Cost of money", "risk": "Risk appetite", "breadth": "Breadth",
             "momentum": "Momentum factor", "dollar": "Dollar", "credit": "Credit stress"}
NEXT_STATE = {"none": "Watch", "watch_exit": "Watch", "watch": "Early", "early": "Developing", "developing": "Confirmed"}
NEXT_LEVEL = {"none": 1, "watch_exit": 1, "watch": 2, "early": 3, "developing": 4}


def lc(name):
    """Lower the first letter for prose; keeps AI, SET and tickers intact."""
    return name[:1].lower() + name[1:] if name else name


def sentence(text):
    return text[:1].upper() + text[1:] if text else text


def join_names(names):
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def meter_html(count, fade=False):
    return '<span class="meter%s">%s</span>' % (" fade" if fade else "", "".join('<i class="on"></i>' if i < count else "<i></i>" for i in range(5)))


def rs_cell_text(rs):
    v, since, sessions = rs.get("value"), rs.get("since"), rs.get("sessions")
    if not v:
        return None
    if since and sessions is not None and sessions <= 30:
        return cell(("\u25b2 crossed %s" if v == 1 else "\u25bc lost %s") % dl(since), 1 if v == 1 else -1)
    return cell("\u25b2 rising" if v == 1 else "\u25bc falling", 1 if v == 1 else -1)


def regime_line(R, detector):
    f = R["flags"]
    parts = []
    if f.get("liquidity"):
        parts.append("Liquidity %s" % f["liquidity"])
    if f.get("cost"):
        parts.append("cost of money %s" % f["cost"])
    if f.get("risk"):
        r = "risk appetite %s" % f["risk"]
        if f.get("breadth") == "narrowing":
            r += " but breadth narrowing"
        elif f.get("breadth") == "broadening":
            r += ", breadth broadening"
        parts.append(r)
    line = ", ".join(parts) + "." if parts else ""
    if f.get("cycle"):
        line += " Cycle: %s (%s)." % (f["cycle"], f.get("cycle_detail", ""))
    by = {}
    for k, v in detector.items():
        by.setdefault(v.get("state"), []).append(v["name"])
    bits = []
    if by.get("fading"):
        bits.append("%s leadership is fading" % join_names([lc(n) for n in by["fading"]]))
    dev = by.get("confirmed", []) + by.get("developing", [])
    if dev:
        bits.append("%s %s developing" % (join_names([lc(n) for n in dev]), "is" if len(dev) == 1 else "are"))
    if by.get("early"):
        bits.append("%s %s early" % (join_names([lc(n) for n in by["early"]]), "is" if len(by["early"]) == 1 else "are"))
    if bits:
        line += " " + sentence("; ".join(bits)) + "."
    return line.strip()


def rotation_read(detector):
    by = {}
    for k, v in detector.items():
        by.setdefault(v.get("state"), []).append(lc(v["name"]) if k != "cash" else "cash leaving the sidelines")
    dev = by.get("developing", [])
    s = []
    if dev:
        s.append("%s rotation%s developing: into %s." % (len(dev), "" if len(dev) == 1 else "s", join_names(dev)))
    else:
        s.append("No rotation is developing yet.")
    if by.get("early"):
        s.append("%s %s early." % (sentence(join_names(by["early"])), "is" if len(by["early"]) == 1 else "are"))
    if by.get("fading"):
        s.append("%s leadership is fading." % sentence(join_names(by["fading"])))
    if by.get("watch_exit"):
        s.append("%s %s the quiet exit%s." % (sentence(join_names(by["watch_exit"])), "is" if len(by["watch_exit"]) == 1 else "are", "" if len(by["watch_exit"]) == 1 else "s"))
    s.append(("Confirmed: %s." % join_names(by["confirmed"])) if by.get("confirmed") else "Nothing is confirmed yet.")
    s.append("Flows are not scored (no free share-count feed); breadth is scored where a free holdings file exists.")
    return " ".join(s)


def card_for(row):
    st = row["state"]
    word, chip_html = STATE_CHIP[st]
    lines = []
    order = ("rs", "flow", "macro", "breadth", "seasonal") if row["key"] != "cash" else ("flow", "destination", "macro", "breadth", "seasonal")
    for k in order:
        if k == "destination":
            lines.append({"mark": "\u25cb", "cls": "no", "text": "Destination: " + row.get("destination", "")})
            continue
        v = row["signals"].get(k)
        mark, cls = ("\u2713", "") if v == 1 else ("\u2715", "lost") if v == -1 else ("\u25cb", "no")
        lines.append({"mark": mark, "cls": cls, "text": "%s: %s" % ({"rs": "Relative strength", "flow": "Flows", "macro": "Macro", "breadth": "Breadth", "seasonal": "Seasonal"}[k], row["text"].get(k, ""))})
    bt = row.get("backtest") or {}
    b = bt.get(row.get("level") or "") or {}
    so, meta = "", ""
    since_year = row.get("history_from", "2011")
    if b.get("n"):
        so = "At %s of the three backtested conditions, %s beat the S&P 500 over the next eight weeks %d%% of the time (n=%d since %s), average %+.1f%% relative." % (
            row["level"].rstrip("0").rstrip(".") if row["level"] != "2.5" else "all three", row["tk"], round(b["hit"]), b["n"], since_year, b["avg"])
        q = row.get("quadrant")
        qs = (b.get("quadrants") or {}).get(q) if q else None
        meta = "n=%d since %s, hit %d%%, avg %+.1f%% excess, worst %+.1f%%, t=%.1f%s; live" % (
            b["n"], since_year, round(b["hit"]), b["avg"], b["worst"], b["t"] or 0, ("; in %s regime %d%% (n=%d)" % (q, round(qs["hit"]), qs["n"])) if qs else "")
    elif row["key"] == "cash":
        so = "Sideline cash re-entering after a cut is the confirmation a broadening rally needs; the money market series is logged weekly from here, so the flow condition needs three weeks of history."
        meta = "no backtest for this composite card; live"
    else:
        so = "No backtest events at this signal count since %s." % since_year
        meta = "live"
    if st in NEXT_STATE:
        need = NEXT_LEVEL[st] - row["entry"]
        pend = row.get("off") or []
        so += " %s needs %.1f more condition%s%s." % (NEXT_STATE[st], need, "" if need <= 1 else "s", (": pending " + join_names(pend).lower()) if pend else "")
    elif st == "confirmed":
        so += " Confirmed: the evidence bar (n of 20, t of 2) is met."
    elif st == "fading":
        so += " Fading is a leader losing two conditions (%s); it resolves either way, so it is a timing question, not a thesis question." % join_names(row.get("lostn") or []).lower()
    return {"key": row["key"], "name": row["name"], "tk": row["tk"], "state": st, "word": word, "chip": chip_html, "count": row["count"],
            "since": dl(row["since"]) if row.get("since") else "", "fade": st in ("fading", "watch_exit"), "lines": lines, "so": so, "meta": meta}


def render_v2(V, o, now):
    R, detector, sectors = V["regime"], V["detector"], V["sectors"]
    comps = R["composites"]
    # strip: risk appetite score
    rv = comps["risk"]["value"]
    if rv is not None:
        mood = ("risk-on" if rv >= 0.25 else "risk-off" if rv <= -0.25 else "neutral") + (", extreme" if abs(rv) >= 1.5 else ", not extreme")
        o.put("strip.risk", strip(f_signed(rv, 1), mood, dir3(rv, 0.25), "six inputs, 3-year z-scores", dl(comps["risk"]["date"])))
    # regime block
    flags = {}
    for k, table in FLAG_CHIP.items():
        w = R["flags"].get(k)
        if w and w in table:
            cls, g = table[w]
            flags[k] = {"text": "%s: %s" % (FLAG_NAME[k], w), "cls": cls, "g": g}
    if R["flags"].get("cycle"):
        flags["cycle"] = {"text": "Cycle: %s (%s)" % (R["flags"]["cycle"], R["flags"].get("cycle_detail", "")), "cls": "chip accent", "g": "\u25cf"}
    comp_out = {}
    for k in ("liq", "growth", "infl", "risk"):
        v = comps[k]["value"]
        comp_out[k] = None if v is None else {"v": v, "t": f_signed(v, 1), "left": round(max(0, min(100, (v + 2) / 4 * 100)), 1),
                                              "title": "%d inputs, three-year z-scores, as of %s" % (comps[k]["n_inputs"], dl(comps[k]["date"]))}
        if comp_out[k]:
            # v4.1: the twelve-month trail behind the dot (month ends, the live value replaces the current month)
            tr = [x for x in comps[k]["trail"] if x[1] is not None]
            if tr and comps[k]["date"] and tr[-1][0][:7] >= comps[k]["date"][:7]:
                tr = tr[:-1]
            tr = tr[-12:]
            comp_out[k]["trail"] = [x[1] for x in tr] + [v]
            comp_out[k]["trail_from"] = "%s %s" % (MONTHS[int(tr[0][0][5:7]) - 1], tr[0][0][:4]) if tr else ""
    trail = []
    gt = dict((d[:7], v) for d, v in comps["growth"]["trail"])
    it = dict((d[:7], v) for d, v in comps["infl"]["trail"])
    months = sorted(set(gt) & set(it))
    gv, iv = comps["growth"]["value"], comps["infl"]["value"]
    latest_month = max(comps["growth"]["date"] or "", comps["infl"]["date"] or "")[:7]
    if months and latest_month and months[-1] >= latest_month:
        months = months[:-1]                     # the live point replaces the current month's end point
    for m in months[-6:]:
        trail.append([gt[m], it[m], "%s" % MONTHS[int(m[5:7]) - 1]])
    if gv is not None and iv is not None:
        trail.append([gv, iv, "now"])
    clock = {"trail": trail, "quadrant": R["flags"].get("cycle"), "detail": R["flags"].get("cycle_detail")} if len(trail) >= 2 else None
    if V.get("v3") and V["v3"]["crowd"].get("word"):
        w = V["v3"]["crowd"]["word"]
        cls, g = {"euphoric": ("chip serious", "\u25b2"), "optimistic, not euphoric": ("chip warn", "\u25b2"), "neutral": ("chip", "\u25cf"),
                  "fearful": ("chip up", "\u25bc"), "capitulating": ("chip up", "\u25bc")}[w]
        flags["crowd"] = {"text": "Crowd: %s" % w, "cls": cls, "g": g}
    o.v2["regime"] = {"line": regime_line(R, detector), "label": "The read at a glance (rule-based, live)", "flags": flags, "composites": comp_out, "clock": clock,
                      "asof": dl(comps["risk"]["date"]) if comps["risk"]["date"] else ""}
    # themes table cells and cards
    for key, row in detector.items():
        if key == "cash":
            continue
        pre = "th." + key
        rsc = rs_cell_text({"value": row["signals"].get("rs"), "since": row["meta"].get("rs_since"), "sessions": row["meta"].get("rs_sessions")})
        if rsc:
            o.put(pre + ".rs", rsc)
        o.put(pre + ".flowz", cell("no feed"))
        b = row["meta"].get("breadth")
        o.put(pre + ".breadth", cell("%d%%" % b) if b is not None else cell("no file"))
        se = row["meta"].get("seasonal")
        if se:
            sv = row["signals"].get("seasonal")
            o.put(pre + ".seasonal", cell("%s, hit %d%%" % ("Positive" if sv == 1 else "Weak" if sv == -1 else "Mixed", se["hit"]), sv or 0))
        o.put(pre + ".signals", hcell("%d of 5" % row["count"], meter_html(row["count"], row["state"] in ("fading", "watch_exit"))))
        word, chip_html = STATE_CHIP[row["state"]]
        o.put(pre + ".state", hcell(word, chip_html))
    for key, sc in sectors.items():
        pre = "sec." + key
        rsc = rs_cell_text(sc["rs_signal"])
        if rsc:
            o.put(pre + ".rs", rsc)
        o.put(pre + ".ma", cell("%s / %s" % sc["ma"]))
        o.put(pre + ".flowz", cell("no feed"))
        o.put(pre + ".breadth", cell("%d%%" % sc["breadth"]) if sc.get("breadth") is not None else cell("no file"))
        if sc.get("quadrant"):
            o.put(pre + ".quadrant", hcell(sc["quadrant"], QUAD_CHIP[sc["quadrant"]]))
    cards = []
    cutoff = (now.date() - dt.timedelta(days=30)).isoformat()
    prio = {"confirmed": 0, "developing": 1, "fading": 2, "early": 3, "watch_exit": 4, "watch": 5}
    for key, row in detector.items():
        if row["state"] in ("early", "developing", "confirmed", "fading", "watch_exit") or (row["state"] == "watch" and row.get("since", "") >= cutoff):
            row["quadrant"] = R["flags"].get("cycle")
            cards.append((row.get("changed", ""), prio.get(row["state"], 9), row["name"], card_for(row)))
    cards.sort(key=lambda x: (x[1], x[0] and "".join(chr(255 - ord(ch)) for ch in x[0]), x[2]))   # state first, then newest
    rmap = []
    for m in V["map"]:
        st = m.get("state")
        rmap.append({"key": m["key"], "label": m["label"], "rs": m["rs"], "mom": m["mom"], "tail": m["tail"], "hot": m["hot"],
                     "title": "%s: relative strength %.1f, momentum %.1f, %s%s" % (m["label"], m["rs"], m["mom"], m["quadrant"].lower(), (", " + STATE_CHIP[st][0].lower()) if m["hot"] and st else "")})
    season_rows = []
    for r in V["seasonality"]:
        cells = []
        for m in r["cells"]:
            if m["avg"] is None:
                cells.append({"t": "", "v": 0, "title": "no data"})
            else:
                cells.append({"t": "%.1f" % m["avg"], "v": round(m["avg"], 2), "title": "hit rate %d%% over %d years" % (round(m["hit"]), m["n"])})
        season_rows.append({"name": r["name"], "cells": cells, "years": r["years"]})
    o.v2["rotation"] = {"read": rotation_read(detector), "cards": [cd[3] for cd in cards[:12]], "map": rmap,
                        "season": {"month": now.month, "rows": season_rows}, "asof": V["detector"].get("smh", {}).get("asof") or ""}
    if V.get("v3"):
        render_v3(V["v3"], o, now)
    # ranking: conditions score, pillars, read
    for key, r in V["ranking"].items():
        rk = o.rank.setdefault(key, {})
        rk["cond"] = r["cond"]
        rk["pillars"] = {p: {"v": v, "title": "%s %s: %s" % (cond_name(p), f_signed(v, 1) if v is not None else "not scored", r["detail"].get(p, ""))} for p, v in r["pillars"].items()}
        rk["read"] = r["read"]
        if r["read"]:
            cls, g = READ_CHIP[r["read"]]
            label = r["read"].split(",")[0]
            rk["read_html"] = '<span class="%s"><span class="g">%s</span>%s</span>' % (cls, g, label)
        rk["cond_wow"], rk["price_wow"], rk["wow_ref"] = r.get("cond_wow"), r.get("price_wow"), r.get("wow_ref")
        rk["n_pillars"] = r["n"]
        if "price" not in rk:
            rk["price"] = r.get("price")


def cond_name(p):
    return {"L": "Liquidity", "C": "Cost of money", "Y": "Cycle", "V": "Valuation", "F": "Flows", "P": "Positioning", "S": "Seasonal"}[p]


# ---------------------------------------------------------------- v3: positioning and sentiment
def k_(x):
    return "%+.0fk" % (x / 1000.0)


def pct_cell(p, n=None, min_n=None):
    if p is None:
        return cell("logging%s" % (", %d so far" % n if n else ""))
    return cell("%d" % round(p))


def render_v3(V, o, now):
    M, X, cta, fl = V["markets"], V["extras"], V["cta"], V["flows"]
    src_cot = {"comm_change": "CFTC legacy report, commercials", "comm": "CFTC legacy report, commercials", "asset_mgr": "CFTC TFF report, asset managers"}
    # smart money rows
    for rk, mk in (("sm_gold", "gold"), ("sm_silver", "silver"), ("sm_crude", "crude"), ("sm_spx", "spx"), ("sm_ust10", "ust10"), ("sm_dxy", "dxy")):
        m = M.get(mk)
        if not m or m.get("hedgers_net") is None:
            continue
        o.row("pos." + rk, src_cot[m["mode"]], dl(m["date"], "w"))
        o.put("pos.%s.now" % rk, cell(k_(m["hedgers_net"]), sgn(m["hedgers_net"])))
        o.put("pos.%s.pct" % rk, pct_cell(m["hedgers_pct"]))
    if "dix" in X:
        o.row("pos.sm_dix", "SqueezeMetrics DIX", dl(X["dix"]["date"]))
        o.put("pos.sm_dix.now", cell("%.0f%%" % X["dix"]["now"]))
        o.put("pos.sm_dix.pct", pct_cell(X["dix"]["pct"]))
    if "index_pc" in X:
        o.row("pos.sm_index_pc", "Cboe daily statistics, index put/call, 10-day average", dl(X["index_pc"]["date"]))
        o.put("pos.sm_index_pc.now", cell("%.2f" % X["index_pc"]["now"]))
        o.put("pos.sm_index_pc.pct", pct_cell(X["index_pc"]["pct"], X["index_pc"]["n"]))
    if "gex" in X:
        o.row("pos.sm_gamma", "SqueezeMetrics GEX (gamma exposure)", dl(X["gex"]["date"]))
        o.put("pos.sm_gamma.now", cell("%s, $%.1fB" % ("long" if X["gex"]["now"] > 0 else "short", abs(X["gex"]["now"]) / 1e9), sgn(X["gex"]["now"])))
        o.put("pos.sm_gamma.pct", pct_cell(X["gex"]["pct"]))
    # crowd rows
    if "aaii" in X:
        a = X["aaii"]
        o.row("pos.cr_aaii", "AAII survey page (bulls %.1f%%, bears %.1f%%)" % (a["bull"], a["bear"]), dl(a["date"], "w"))
        o.put("pos.cr_aaii.now", cell("%+.0f" % a["now"], sgn(a["now"], 0.5)))
        o.put("pos.cr_aaii.pct", pct_cell(a["pct"], a["n"]))
    if "margin" in X:
        m = X["margin"]
        o.row("pos.cr_margin", "FINRA margin statistics, debit balances%s" % ((", %+.1f%% YoY" % m["yoy"]) if m.get("yoy") is not None else ""), dl(m["date"], True))
        o.put("pos.cr_margin.now", cell("$%.2fT" % (m["now"] / 1e6)))
        o.put("pos.cr_margin.pct", pct_cell(m["pct"], m["n"]) if m["n"] < 36 else pct_cell(m["pct"]))
    if "equity_pc" in X:
        o.row("pos.cr_equity_pc", "Cboe daily statistics, equity put/call, 10-day average", dl(X["equity_pc"]["date"]))
        o.put("pos.cr_equity_pc.now", cell("%.2f" % X["equity_pc"]["now"]))
        o.put("pos.cr_equity_pc.pct", pct_cell(X["equity_pc"]["pct"], X["equity_pc"]["n"]))
    if "crypto_fng" in X:
        o.row("pos.cr_crypto", "alternative.me crypto fear and greed", dl(X["crypto_fng"]["date"]))
        o.put("pos.cr_crypto.now", cell("%d" % round(X["crypto_fng"]["now"])))
        o.put("pos.cr_crypto.pct", pct_cell(X["crypto_fng"]["pct"]))
    if M.get("crude") and M["crude"].get("crowd_net") is not None:
        m = M["crude"]
        o.row("pos.cr_spec_crude", "CFTC legacy report, non-commercials", dl(m["date"], "w"))
        o.put("pos.cr_spec_crude.now", cell(k_(m["crowd_net"]), sgn(m["crowd_net"])))
        o.put("pos.cr_spec_crude.pct", pct_cell(m["crowd_pct"]))
    # divergence table and dots
    dots = []
    for key, m in M.items():
        pre = "div." + key
        if m.get("date"):
            o.row(pre, "CFTC %s" % ("TFF" if m["mode"] == "asset_mgr" else "legacy") + " plus the daily inputs listed in the cells", dl(m["date"], "w"))
        smt, crt = [], []
        if m.get("hedgers_net") is not None:
            who = {"comm_change": "Producers", "comm": "Hedgers", "asset_mgr": "Asset managers"}[m["mode"]]
            smt.append("%s net %s, pct %d" % (who, k_(m["hedgers_net"]), round(m["hedgers_pct"] or 0)))
            if m["mode"] == "comm_change":
                zc = [z for n, z in m["sm_parts"] if n == "hedgers"]
                if zc:
                    smt.append("four-week short change z %+.1f" % zc[0])
        for n, z in m["sm_parts"]:
            if n == "dix":
                smt.append("DIX pct %d" % round(X["dix"]["pct"]))
            if n == "index_pc":
                smt.append("index put/call z %+.1f" % z)
        if m.get("crowd_net") is not None:
            who = "Leveraged funds" if m["mode"] == "asset_mgr" else "Speculators"
            crt.append("%s net %s, pct %d" % (who, k_(m["crowd_net"]), round(m["crowd_pct"] or 0)))
        for n, z in m["cr_parts"]:
            if n == "aaii":
                crt.append("AAII spread z %+.1f" % z)
            if n == "margin":
                crt.append("margin debt z %+.1f" % z)
            if n == "equity_pc":
                crt.append("equity put/call z %+.1f (inverted)" % z)
            if n == "crypto_fng":
                crt.append("crypto fear and greed %d, pct %d" % (round(X["crypto_fng"]["now"]), round(X["crypto_fng"]["pct"])))
        if "aaii" in X and key in ("spx", "semis") and not any(n == "aaii" for n, _ in m["cr_parts"]):
            crt.append("AAII spread %+.0f (logging, %d week%s)" % (X["aaii"]["now"], X["aaii"]["n"], "" if X["aaii"]["n"] == 1 else "s"))
        if key == "semis":
            smt.insert(0, "Nasdaq 100 futures as the proxy")
        o.put(pre + ".sm", cell("; ".join(smt) if smt else "no free smart money input"))
        o.put(pre + ".cr", cell("; ".join(crt) if crt else "no free crowd input"))
        d = m.get("div")
        if d is not None:
            o.put(pre + ".score", cell(f_signed(d, 1), sgn(d, 0.05)))
            o.put(pre + ".read", cell(pos_read(d, m["state"])))
            b = m.get("before") or {}
            side = "up" if d >= 0.5 else "down" if d <= -0.5 else None
            if side and b.get(side, {}).get("n"):
                st = b[side]
                o.put(pre + ".before", cell("%d crossing%s %s1.5 in three years: next 8 weeks median %+.1f%%, positive %d%% of the time." % (
                    st["n"], "" if st["n"] == 1 else "s", "above +" if side == "up" else "below -", st["median"], round(st["positive"]))))
            elif side:
                o.put(pre + ".before", cell("No crossing %s1.5 in the three years of weekly data." % ("above +" if side == "up" else "below -")))
            else:
                o.put(pre + ".before", cell("Inside the band; nothing to compare."))
            dots.append({"key": key, "name": m["name"], "score": round(d, 2), "x": bool(m["state"])})
        else:
            o.put(pre + ".score", cell("n/a"))
            o.put(pre + ".read", cell("One side has no free input yet."))
            o.put(pre + ".before", cell(""))
    dots.sort(key=lambda x: -x["score"])
    # systematic flows
    for key, r in cta.items():
        pre = "cta." + key
        o.row(pre, "Trend model on the closes: sign of 20, 50, 100 and 200-day returns, majority rule", dl(r["date"]))
        o.put(pre + ".signal", hcell("Long" if r["signal"] == 1 else "Short", '<span class="chip %s"><span class="g">%s</span>%s</span>' % (
            "up" if r["signal"] == 1 else "serious", "\u25b2" if r["signal"] == 1 else "\u25bc", "Long" if r["signal"] == 1 else "Short")))
        o.put(pre + ".since", cell(dl(r["since"])))
        if r.get("is_yield"):
            o.put(pre + ".flip", cell("%.2f%% yield" % r["flip_level"]))
        else:
            o.put(pre + ".flip", cell("%s (%+.1f%%)" % (f_num(r["flip_level"], 2 if r["flip_level"] < 10 else 0), r["flip_pct"])))
    if fl.get("volctl"):
        v = fl["volctl"]
        o.row("flow2.volctl", "S&P 500 closes, 21-day realized volatility against a 12% target", dl(now.date().isoformat()))
        o.put("flow2.volctl.state", cell(v["word"]))
        o.put("flow2.volctl.read", cell("Realized vol %.0f%% against a 12%% target: allocation %.0f%% of the cap. A vol spike cuts it mechanically." % (v["vol"], v["alloc"])))
    if fl.get("rp"):
        v = fl["rp"]
        o.row("flow2.rp", "SPY and TLT: 100-day trends and 60-day correlation", dl(now.date().isoformat()))
        o.put("flow2.rp.state", cell(v["word"]))
        o.put("flow2.rp.read", cell("Stocks %s their 100-day, bonds %s theirs, correlation %+.2f: %s." % (
            "above" if v["stocks_up"] else "below", "above" if v["bonds_up"] else "below", v["corr"],
            "levered up, vulnerable to a positive-correlation shock" if v["word"] == "high" else "cutting leverage" if v["word"] == "reducing" else "leverage middling")))
    if fl.get("gamma"):
        g = fl["gamma"]
        o.row("flow2.gamma", "SqueezeMetrics GEX", dl(g["date"]))
        o.put("flow2.gamma.state", cell("long" if g["now"] > 0 else "short"))
        o.put("flow2.gamma.read", cell("Gamma exposure $%.1fB, 3-year percentile %d: %s." % (abs(g["now"]) / 1e9, round(g["pct"]), "dealers sell rallies and buy dips, which dampens moves" if g["now"] > 0 else "dealers chase moves, which amplifies them")))
    if fl.get("pension"):
        v = fl["pension"]
        o.row("flow2.pension", "SPY and TLT quarter-to-date returns", dl(now.date().isoformat()))
        o.put("flow2.pension.state", cell(v["word"]))
        o.put("flow2.pension.read", cell("Quarter to date stocks %+.1f%%, bonds %+.1f%%: a gap of %.1f points for pensions to rebalance into quarter end." % (v["stocks"], v["bonds"], abs(v["gap"]))))
    # section read
    crowd = V["crowd"]
    active = [(k, m) for k, m in M.items() if m.get("state")]
    parts = []
    if crowd.get("word"):
        parts.append("The crowd is %s (S&P 500 crowd score %+.1f)." % (crowd["word"], crowd["z"]))
    if active:
        parts.append("Divergence alerts: %s." % join_names(["%s (%+.1f, %s)" % (m["name"].lower() if k != "spx" and k != "ust10" else m["name"], m["div"], "smart money buying" if m["state"] == "up" else "smart money leaving") for k, m in active]))
    else:
        scored = sorted([(m["div"], m["name"]) for m in M.values() if m.get("div") is not None])
        if scored:
            parts.append("No divergence alert is active; the widest gaps are %s (%+.1f) and %s (%+.1f)." % (scored[-1][1], scored[-1][0], scored[0][1], scored[0][0]))
    longs = [r["name"] for r in cta.values() if r["signal"] == 1]
    shorts = [r["name"] for r in cta.values() if r["signal"] == -1]
    if cta:
        parts.append("Trend followers are long %s%s." % (join_names(longs) if longs else "nothing", (" and short %s" % join_names(shorts)) if shorts else ""))
    if fl.get("volctl"):
        parts.append("Vol-control allocation is %s." % fl["volctl"]["word"])
    o.v2["positioning"] = {"read": " ".join(parts), "dots": dots, "asof": dl(V["cot_date"], "w") if V.get("cot_date") else ""}


def pos_read(score, state):
    from . import positioning as pos
    return pos.div_read(score, state)


# ---------------------------------------------------------------- v4: the calendar (section 5)
def _cons_value(v):
    v = (v or "").strip()
    return v.replace("K", "k") if v.endswith("K") else v


def cons_line(e):
    """'payrolls 58k, unemployment 4.1%, wages m/m 0.3%; options price ±0.8%' for the event cell."""
    parts = ["%s %s" % (c["label"], _cons_value(c["forecast"])) for c in e.get("cons", []) if c.get("label") and c.get("forecast")]
    line = ", ".join(parts)
    if e.get("implied") and e["tier"] == 1:
        line += ("; " if line else "") + "options price ±%.1f%%" % e["implied"]
    return line


def expect_rule(e, V4, V3):
    """The Expect column when no reviewed brief exists: consensus and prior, the event study, the implied move, positioning."""
    from . import calendar as cal
    from . import events as ev
    bits = []
    cons = ["%s %s%s" % (c["label"], _cons_value(c["forecast"]), (" (prior %s)" % _cons_value(c["previous"])) if c.get("previous") else "")
            for c in e.get("cons", []) if c.get("label") and c.get("forecast")]
    if cons:
        bits.append("Consensus: " + ", ".join(cons) + ".")
    st = (V4.get("studies") or {}).get(e.get("study")) if e.get("study") else None
    if st and st.get("markets", {}).get("spx"):
        m = st["markets"]
        line = "Past releases since %s (n=%d): the S&P moves %.1f%% on the day at the median, %.1f%% in the worst tenth" % (
            st["from"][:4], st["n"], m["spx"]["med_abs1"], m["spx"]["p90_abs1"])
        if m.get("dgs10"):
            line += "; the 10Y %.0f bp" % m["dgs10"]["med_abs1"]
        if m.get("gold"):
            line += "; gold %.1f%%" % m["gold"]["med_abs1"]
        bits.append(line + ".")
    if e.get("implied"):
        base = (V4.get("implied") or {}).get("base")
        bits.append("Options price ±%.1f%% for the session%s." % (e["implied"], (" against ±%.1f%% for a normal one" % base) if base else ""))
    pos = []
    for mk in e.get("markets", []):
        m = (V3 or {}).get("markets", {}).get(mk) or {}
        d = m.get("div")
        if d is not None and (m.get("state") or abs(d) >= 1.0):
            pos.append("%s %+.1f (%s)" % (m["name"], d, "smart money buying" if d > 0 else "smart money leaving"))
    if pos:
        bits.append("Positioning: " + ", ".join(pos) + ".")
    if e["key"] == "qend" and (V3 or {}).get("flows", {}).get("pension"):
        pn = V3["flows"]["pension"]
        bits.append("Quarter to date stocks %+.1f%%, bonds %+.1f%%: a %.1f point gap for pensions to rebalance." % (pn["stocks"], pn["bonds"], abs(pn["gap"])))
    if e["key"] in cal.EXPECT_TEXT:
        bits.append(cal.EXPECT_TEXT[e["key"]])
    if e["key"] == "fomc" and "dot plot" in e["name"]:
        bits.append("The projections and the dots matter more than the decision itself.")
    if e.get("kind") == "auction":
        bits.append("A demand test for the long end: a tail over 2 bp pushes yields up.")
    if not e.get("confirmed"):
        bits.append("Usual slot, not yet confirmed by a feed.")
    return " ".join(bits)


def week_rule(events, V4):
    """The week-ahead paragraph when no reviewed brief exists."""
    from . import calendar as cal
    lo, hi = V4["ranges"]["week"]
    wk = [e for e in events if lo <= e["date"] <= hi]
    t1 = [e for e in wk if e["tier"] == 1]
    t2 = [e for e in wk if e["tier"] == 2]
    closed = [e for e in wk if e["kind"] == "holiday"]
    parts = []
    if t1:
        parts.append("%s tier-1 event%s this week: %s." % (["No", "One", "Two", "Three", "Four", "Five"][min(len(t1), 5)] if len(t1) <= 5 else str(len(t1)), "" if len(t1) == 1 else "s",
                                                          join_names(["%s on %s" % (e["name"], cal.day_label(e["date"])) for e in t1])))
        top = max(t1, key=lambda e: (e.get("implied") or 0, -t1.index(e)))
        if top.get("implied"):
            base = (V4.get("implied") or {}).get("base")
            parts.append("The session to watch is %s: options price ±%.1f%% for the S&P%s." % (
                cal.day_label(top["date"]), top["implied"], (", against ±%.1f%% for a normal session" % base) if base else ""))
    else:
        parts.append("No tier-1 event this week.")
    if t2:
        parts.append("Tier 2: %s." % join_names(["%s (%s)" % (e["name"], cal.DAYS[dt.date.fromisoformat(e["date"]).weekday()]) for e in t2[:6]]) + (" And %d more." % (len(t2) - 6) if len(t2) > 6 else ""))
    if closed:
        parts.append("Closed: %s." % join_names(["%s (%s)" % (e["name"].split(":")[0].replace(" closed", "").replace("US markets", "US"), cal.DAYS[dt.date.fromisoformat(e["date"]).weekday()]) for e in closed]))
    return " ".join(parts)


def render_v4(V4, o, now, V3=None):
    from . import calendar as cal
    from . import events as ev
    today = V4["today"]
    rng = V4["ranges"]
    rows = []
    for e in V4["events"]:
        which = next((k for k, (a, b) in rng.items() if a <= e["date"] <= b), None)
        if not which and e["date"] < rng["week"][0]:
            which = "week"                          # the rest of today, before the week starts
        if not which:
            continue
        b = e.get("brief")
        if b:
            brief = {"expect": b.get("expect", ""), "stronger": b.get("stronger", ""), "weaker": b.get("weaker", ""),
                     "src": "reviewed %s" % dl(b["reviewed"]) if b.get("reviewed") else "draft, not reviewed"}
        else:
            stronger, weaker = cal.DRIVER_TEXT.get(e.get("driver") or "", ("", ""))
            brief = {"expect": expect_rule(e, V4, V3), "stronger": stronger, "weaker": weaker, "src": "rule"}
        name = e["name"] + ("" if e["confirmed"] or e["kind"] == "holiday" else " (usual slot, to confirm)")
        rows.append({"id": e["id"], "key": e["key"], "date": e["date"], "day": cal.day_label(e["date"]),
                     "time": e["time_text"] if e.get("time_text") else cal.time_label(e["date"], e.get("time")),
                     "name": name, "cons": cons_line(e), "touches": ("Touches: " + e["touches"]) if e.get("touches") else "",
                     "tier": e["tier"], "dim": e["kind"] == "holiday", "confirmed": bool(e["confirmed"]), "src": e["src"],
                     "range": which, "brief": brief, "implied": round(e["implied"], 2) if e.get("implied") else None})
    # event-study table
    studies = []
    for key in ("nfp", "cpi", "fomc"):
        st = (V4.get("studies") or {}).get(key)
        if not st or not st.get("markets"):
            continue
        cells = {}
        for mk, m in st["markets"].items():
            if m["mode"] == "bp":
                cells[mk] = {"med": "%.0f bp" % m["med_abs1"], "p90": "%.0f bp" % m["p90_abs1"], "up": "%.0f%%" % m["up1"], "med5": "%.0f bp" % m["med_abs5"], "n": m["n"]}
            else:
                cells[mk] = {"med": "%.1f%%" % m["med_abs1"], "p90": "%.1f%%" % m["p90_abs1"], "up": "%.0f%%" % m["up1"], "med5": "%.1f%%" % m["med_abs5"], "n": m["n"]}
        nxt = next((e for e in V4["events"] if e.get("study") == key), None)
        studies.append({"key": key, "name": ev.STUDY_NAMES[key], "n": st["n"], "from": month_label(st["from"]) if st.get("from") else "", "cells": cells,
                        "next": {"date": cal.short_label(nxt["date"]), "implied": ("±%.1f%%" % nxt["implied"]) if nxt.get("implied") else "not priced yet (no daily expiry)"} if nxt else None})
    # week-ahead read
    week = V4.get("week")
    if week:
        read = {"label": "Week ahead, %s (reviewed %s)" % (cal.span_label(week["from"], week["to"]), dl(week["reviewed"]) if week.get("reviewed") else "draft"), "text": week["text"], "src": "reviewed"}
    else:
        read = {"label": "Week ahead, %s (rule-based)" % cal.span_label(rng["week"][0], rng["week"][1]), "text": week_rule(V4["events"], V4), "src": "rule"}
    imp = V4.get("implied") or {}
    feeds = V4.get("feeds") or {}
    names = {"ff_cal": "Forex Factory", "fomc_cal": "Federal Reserve", "ecb_cal": "ECB", "boj_cal": "Bank of Japan", "bls_empsit": "BLS (payrolls)",
             "bls_cpi": "BLS (CPI)", "td_upcoming": "TreasuryDirect", "spx_chain": "Cboe SPX chain"}
    o.v2["calendar"] = {
        "today": today, "asof": dl(today), "ranges": rng, "rows": rows, "studies": studies, "read": read,
        "implied": {"base": ("±%.1f%%" % imp["base"]) if imp.get("base") else None, "asof": dl(imp["asof"]) if imp.get("asof") else None},
        "feeds": {"live": [names[k] for k, ok in feeds.items() if ok], "failed": [names[k] for k, ok in feeds.items() if not ok]},
        "ff_window": V4.get("ff_window"), "counts": {"rows": len(rows), "tier1": sum(1 for r in rows if r["tier"] == 1), "reviewed": sum(1 for r in rows if r["brief"]["src"] != "rule")},
    }
    # growth pulse: the in-house surprise index
    sp = V4.get("surprise") or {}
    o.row("gp.surprise", "in-house: Forex Factory consensus against FRED first prints, mean standardized surprise over 90 days (US only; no free consensus feed with actuals for the euro area or China)", dl(today))
    if sp.get("value") is not None:
        o.put("gp.surprise.now", cell("%+.1fσ (n=%d)" % (sp["value"], sp["n"]), sgn(sp["value"], 0.05)))
        o.put("gp.surprise.prior", cell(("%+.1fσ" % sp["prior"]) if sp.get("prior") is not None else "n/a", sgn(sp.get("prior"), 0.05) if sp.get("prior") is not None else 0))
    else:
        o.put("gp.surprise.now", cell("logging: %d of %d resolved" % (sp.get("resolved", 0), sp.get("min_n", 6))))
        o.put("gp.surprise.prior", cell(("logging since %s" % dl(sp["since"])) if sp.get("since") else "no consensus logged yet"))
    # calendar effects: the Next column
    mech = V4.get("mech") or {}
    o.row("ce", "calendar rules: NYSE holidays, third Fridays, quarter ends, the tax calendar, the FOMC dates", dl(today))
    for k in ("tom", "opex", "qend", "tax", "buyback", "cycle"):
        if mech.get(k):
            o.put("ce.%s.next" % k, cell(mech[k]))
    bo = next((e for e in V4["events"] if e["key"] == "blackout"), None)
    if bo:
        o.put("ce.blackout.next", cell(cal.span_label(bo["date"], bo["end"]) if bo.get("end") else cal.short_label(bo["date"])))


# ---------------------------------------------------------------- the watchlist: snapshots graded against the page
WL_EARLY_SESSIONS = 21          # the surprise index's resolve window: under it, too soon to grade
WL_COND_BAND = 0.5              # the ranking's read band


def wl_verdict(rel, sessions, cond_now):
    """Open snapshots: early, working, stalled or not working, from the page's own thresholds."""
    if sessions is None or sessions < WL_EARLY_SESSIONS:
        return "early"
    if rel is not None and rel > 0:
        return "working"
    if cond_now is not None and cond_now >= WL_COND_BAND:
        return "stalled"
    return "not working"


def wl_grade(D, yk, date, end=None):
    """Return and sessions from a snapshot date to the latest close (or to end), or None."""
    if not yk or yk not in D or "spx" not in D or not date:
        return None
    s, b = A(D, yk), A(D, "spx")
    if end:
        s = [p for p in s if p[0] <= end]
        b = [p for p in b if p[0] <= end]
    if not s or not b:
        return None
    base, sbase = c.at_or_before(s, date), c.at_or_before(b, date)
    if not (base and sbase and base[1] and sbase[1]):
        return None
    return {"ret": s[-1][1] / base[1] - 1.0, "spx": b[-1][1] / sbase[1] - 1.0,
            "sessions": sum(1 for d, _ in s if d > date), "dl": dl(s[-1][0])}


def render_watchlist(D, o, watch, prev=None):
    """o.v2['watchlist'] from data/watchlist.json: every snapshot graded against the S&P 500.

    watch is the hand-initiated file (fetch.watch writes it; this function never does); prev is the
    previous run's block, the carry for a row whose price feed failed this run. US large caps, the
    benchmark itself, grade on absolute return. Closed snapshots grade over snapshot to close."""
    W = watch or {}
    prev_rows = {r.get("id"): r for r in (((prev or {}).get("rows") or []) + ((prev or {}).get("closed") or []))}
    wl_keys = {k: yk for k, yk, _ in RANKING}
    rows, closed = [], []
    for e in list(W.get("open") or []) + list(W.get("closed") or []):
        is_closed = bool(e.get("closed"))
        rk = o.rank.get(e.get("key")) or {}
        row = {"id": e.get("id"), "key": e.get("key"), "date": e.get("date"),
               "dl": dl(e["date"]) if e.get("date") else "", "note": e.get("note") or "",
               "then": e.get("then") or {},
               "now": {"cond": rk.get("cond"), "price": rk.get("price"), "read": rk.get("read")}}
        if is_closed:
            row["closed"], row["closed_dl"] = e["closed"], dl(e["closed"])
            row["close_note"] = e.get("close_note") or ""
        g = wl_grade(D, wl_keys.get(e.get("key")), e.get("date"), e.get("closed"))
        if g:
            rel = g["ret"] if e.get("key") == "us_large" else g["ret"] - g["spx"]
            row.update({"ret": g["ret"], "spx": g["spx"], "rel": rel,
                        "sessions": g["sessions"], "asof_dl": g["dl"]})
            if is_closed:
                row["verdict"] = "early" if g["sessions"] < WL_EARLY_SESSIONS else ("worked" if rel > 0 else "did not work")
            else:
                row["verdict"] = wl_verdict(rel, g["sessions"], rk.get("cond"))
        elif e.get("id") in prev_rows:
            row = dict(prev_rows[e["id"]])
            row["stale"] = row.get("stale") or row.get("asof_dl") or "an earlier run"
        else:
            row["missing"], row["verdict"] = True, "no series"
        (closed if is_closed else rows).append(row)
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    closed.sort(key=lambda r: r.get("closed") or "", reverse=True)
    o.v2["watchlist"] = {"rows": rows, "closed": closed, "src": "graded against Yahoo ^GSPC"}

"""Section 5: the calendar rules and the event catalog.

Everything here is a rule or a table. Dates come from three places, in this order of trust: a feed that
confirms the date (Forex Factory for the current week, the Fed, ECB and BoJ pages, the BLS archives,
TreasuryDirect), a schedule rule for the usual slot (ISM on the first and third business day, payrolls three
Fridays after the reference week, the QRA on the Wednesday nearest the first of the refunding month), and
mechanical dates that follow from the calendar itself (quarter end, corporate tax dates, quad witching, the
Fed blackout and minutes from the meeting dates). A row from a rule is marked unconfirmed until a feed
confirms it. The tier table is the one printed on the page: tier 1 moves everything, tier 2 moves one market,
everything else stays off.

Time zones are fixed rules (US and EU daylight saving), so no tzdata is needed.
"""
import datetime as dt

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HORIZON_DAYS = 70


# ---------------------------------------------------------------- time zones
def _sunday_on_or_after(d):
    return d + dt.timedelta(days=(6 - d.weekday()) % 7)


def _sunday_on_or_before(d):
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def dst_us(d):
    """Second Sunday of March to the first Sunday of November."""
    return _sunday_on_or_after(dt.date(d.year, 3, 8)) <= d < _sunday_on_or_after(dt.date(d.year, 11, 1))


def dst_eu(d):
    """Last Sunday of March to the last Sunday of October."""
    return _sunday_on_or_before(dt.date(d.year, 3, 31)) <= d < _sunday_on_or_before(dt.date(d.year, 10, 31))


def utc_offset(zone, d):
    if zone == "ET":
        return -4 if dst_us(d) else -5
    if zone == "CET":
        return 2 if dst_eu(d) else 1
    return {"JST": 9, "BKK": 7, "UTC": 0}[zone]


def convert(date_iso, hhmm, zone_from, zone_to):
    """(date ISO, 'HH:MM') in one zone to the other."""
    d = dt.date.fromisoformat(date_iso)
    h, m = [int(x) for x in hhmm.split(":")]
    t = dt.datetime(d.year, d.month, d.day, h, m) + dt.timedelta(hours=utc_offset(zone_to, d) - utc_offset(zone_from, d))
    return t.date().isoformat(), t.strftime("%H:%M")


def time_label(date_iso, hhmm):
    """'14:00 / 01:00 Thu': Eastern, then Bangkok with the weekday when it rolls over."""
    if not hhmm:
        return ""
    bd, bt = convert(date_iso, hhmm, "ET", "BKK")
    tail = "" if bd == date_iso else " " + DAYS[dt.date.fromisoformat(bd).weekday()]
    return "%s / %s%s" % (hhmm, bt, tail)


def day_label(date_iso):
    d = dt.date.fromisoformat(date_iso)
    return "%s %d %s" % (DAYS[d.weekday()], d.day, MONTHS[d.month - 1])


def short_label(date_iso):
    d = dt.date.fromisoformat(date_iso)
    return "%d %s" % (d.day, MONTHS[d.month - 1])


def span_label(a, b):
    """'24 to 30 Sep' or '30 Sep to 5 Oct'."""
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    if da.month == db.month:
        return "%d to %d %s" % (da.day, db.day, MONTHS[da.month - 1])
    return "%s to %s" % (short_label(a), short_label(b))


# ---------------------------------------------------------------- day rules
def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return dt.date(y, month, day)


def nth_weekday(y, m, weekday, n):
    first = dt.date(y, m, 1)
    return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def last_weekday(y, m, weekday):
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    last = nxt - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d):
    """Saturday holidays are taken on Friday, Sunday ones on Monday (NYSE rule; 1 January on a Saturday is not observed)."""
    if d.weekday() == 5:
        return None if (d.month == 1 and d.day == 1) else d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def us_holidays(y):
    """NYSE holidays for a year: {ISO date: name}."""
    out = {}
    for d, name in ((dt.date(y, 1, 1), "New Year's Day"), (dt.date(y, 6, 19), "Juneteenth"), (dt.date(y, 7, 4), "Independence Day"),
                    (dt.date(y, 12, 25), "Christmas")):
        o = _observed(d)
        if o:
            out[o.isoformat()] = name
    out[nth_weekday(y, 1, 0, 3).isoformat()] = "Martin Luther King Day"
    out[nth_weekday(y, 2, 0, 3).isoformat()] = "Presidents' Day"
    out[(easter(y) - dt.timedelta(days=2)).isoformat()] = "Good Friday"
    out[last_weekday(y, 5, 0).isoformat()] = "Memorial Day"
    out[nth_weekday(y, 9, 0, 1).isoformat()] = "Labor Day"
    out[nth_weekday(y, 11, 3, 4).isoformat()] = "Thanksgiving"
    return out


_HOL = {}


def holidays_for(y):
    if y not in _HOL:
        _HOL[y] = us_holidays(y)
    return _HOL[y]


def is_business_day(d):
    return d.weekday() < 5 and d.isoformat() not in holidays_for(d.year)


def next_business_day(d):
    while not is_business_day(d):
        d += dt.timedelta(days=1)
    return d


def prev_business_day(d):
    while not is_business_day(d):
        d -= dt.timedelta(days=1)
    return d


def business_days_between(a, b):
    """Sessions after a, up to and including b (a and b ISO dates)."""
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    n, d = 0, da + dt.timedelta(days=1)
    while d <= db:
        if is_business_day(d):
            n += 1
        d += dt.timedelta(days=1)
    return n


def business_day(y, m, k):
    """The k-th business day of a month."""
    d, n = dt.date(y, m, 1), 0
    while True:
        if is_business_day(d):
            n += 1
            if n == k:
                return d
        d += dt.timedelta(days=1)


def payrolls_rule(y, m):
    """The Employment Situation for reference month (y, m): the third Friday after the week holding the 12th
    (the reference week ends on Saturday; add twenty days). A Friday in the New Year week slips a week; a federal
    holiday (not Good Friday, when the BLS still publishes) moves it to Thursday. Checked against the BLS
    archive since 2015: only shutdown delays and one-off slips differ."""
    sat = dt.date(y, m, 12)
    sat += dt.timedelta(days=(5 - sat.weekday()) % 7)
    fri = sat + dt.timedelta(days=20)
    if (fri.month == 12 and fri.day == 31) or (fri.month == 1 and fri.day <= 3):
        fri += dt.timedelta(days=7)
    hol = holidays_for(fri.year)
    if fri.isoformat() in hol and hol[fri.isoformat()] != "Good Friday":
        return fri - dt.timedelta(days=1)
    return fri


def ism_dates(y, m):
    """(manufacturing, services): the first and third business day of the month, 10:00 ET."""
    return business_day(y, m, 1), business_day(y, m, 3)


def qra_rule(y, m):
    """The refunding announcement: the Wednesday nearest the first of February, May, August and November."""
    first = dt.date(y, m, 1)
    back = (first.weekday() - 2) % 7
    fwd = (2 - first.weekday()) % 7
    return first - dt.timedelta(days=back) if back <= fwd else first + dt.timedelta(days=fwd)


def quarter_end(d):
    """Last business day of the quarter holding d."""
    q_end_month = ((d.month - 1) // 3 + 1) * 3
    last = last_weekday(d.year, q_end_month, 4)          # last Friday, then walk back over holidays
    last = dt.date(d.year, q_end_month, 1) + dt.timedelta(days=32)
    last = last.replace(day=1) - dt.timedelta(days=1)
    return prev_business_day(last)


def tax_dates(y):
    """Corporate quarterly dates (15 Mar, Jun, Sep, Dec) and the individual deadline (15 Apr), rolled forward."""
    out = []
    for m in (3, 4, 6, 9, 12):
        out.append((next_business_day(dt.date(y, m, 15)), "individual" if m == 4 else "corporate"))
    return out


def blackout(start_iso, end_iso):
    """The Fed's rule: the second Saturday before the meeting to the Thursday after it."""
    s, e = dt.date.fromisoformat(start_iso), dt.date.fromisoformat(end_iso)
    first_sat = s - dt.timedelta(days=(s.weekday() - 5) % 7)
    return (first_sat - dt.timedelta(days=7)).isoformat(), (e + dt.timedelta(days=(3 - e.weekday()) % 7 or 7)).isoformat()


def minutes_date(end_iso):
    return (dt.date.fromisoformat(end_iso) + dt.timedelta(days=21)).isoformat()


def third_friday(y, m):
    return nth_weekday(y, m, 4, 3)


def next_quad_witching(d):
    for y in (d.year, d.year + 1):
        for m in (3, 6, 9, 12):
            f = third_friday(y, m)
            if f >= d:
                return f


def next_opex(d):
    for k in range(0, 3):
        y, m = d.year + (d.month - 1 + k) // 12, (d.month - 1 + k) % 12 + 1
        f = third_friday(y, m)
        if f >= d:
            return f


def turn_of_month(d):
    """The next window: last session of a month to the third session of the next month."""
    for k in range(0, 2):
        y, m = d.year + (d.month - 1 + k) // 12, (d.month - 1 + k) % 12 + 1
        last = (dt.date(y, m, 1) + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
        last = prev_business_day(last)
        ny, nm = y + (m == 12), m % 12 + 1
        third = business_day(ny, nm, 3)
        if third >= d:
            return last, third


def qend_window(d):
    """Last five sessions of the quarter."""
    end = quarter_end(d)
    if end < d:
        end = quarter_end(end + dt.timedelta(days=7))
    start, n = end, 1
    while n < 5:
        start -= dt.timedelta(days=1)
        if is_business_day(start):
            n += 1
    return start, end


def buyback_window(d):
    """About two weeks before quarter end to about four weeks after (the bulk of the reports)."""
    end = quarter_end(d)
    if end + dt.timedelta(days=28) < d:
        end = quarter_end(end + dt.timedelta(days=7))
    return end - dt.timedelta(days=16), end + dt.timedelta(days=28)


def cycle_label(y):
    phase = {0: "an election", 1: "a post-election", 2: "a midterm", 3: "a pre-election"}[y % 4]
    if y % 4 == 2:
        return "Q4 %d onward" % y
    return "%d is %s year; the next midterm year is %d" % (y, phase, y + (2 - y % 4) % 4)


# ---------------------------------------------------------------- the catalog
# Rows: key -> what the page shows. tier 1 moves everything, 2 moves one market, 0 is a closed market (dimmed).
# ff: Forex Factory titles that feed the row, as (country, title, series key for the surprise log or None, label).
# study: the event-study key. markets: section 6 divergence rows the brief reads positioning from.
ROWS = {
    "payrolls": {"name": "Nonfarm payrolls", "tier": 1, "touches": "All", "driver": "growth", "time": "08:30", "study": "nfp",
                 "markets": ["spx", "ust10", "dxy", "gold"],
                 "ff": [("USD", "Non-Farm Employment Change", "nfp", "payrolls"), ("USD", "Unemployment Rate", "unrate", "unemployment"),
                        ("USD", "Average Hourly Earnings m/m", "ahe", "wages m/m")]},
    "cpi": {"name": "US CPI", "tier": 1, "touches": "All", "driver": "inflation", "time": "08:30", "study": "cpi",
            "markets": ["spx", "ust10", "dxy", "gold"],
            "ff": [("USD", "CPI m/m", "cpi_mm", "m/m"), ("USD", "Core CPI m/m", "core_cpi_mm", "core m/m"), ("USD", "CPI y/y", "cpi_yy", "y/y")]},
    "fomc": {"name": "FOMC decision", "tier": 1, "touches": "All", "driver": "fed", "time": "14:00", "study": "fomc",
             "markets": ["spx", "ust10", "dxy", "gold"],
             "ff": [("USD", "Federal Funds Rate", None, "rate"), ("USD", "FOMC Statement", None, None), ("USD", "FOMC Press Conference", None, None),
                    ("USD", "FOMC Economic Projections", None, None)]},
    "boj": {"name": "Bank of Japan decision", "tier": 1, "touches": "JPY, Nikkei, global carry", "driver": "boj", "time": None,
            "time_text": "midday Tokyo / about 10:00", "markets": ["dxy", "spx"],
            "ff": [("JPY", "BOJ Policy Rate", None, "policy rate"), ("JPY", "Monetary Policy Statement", None, None), ("JPY", "BOJ Press Conference", None, None)]},
    "qra": {"name": "Treasury quarterly refunding announcement (QRA)", "tier": 1, "touches": "Net liquidity, term premium, everything long duration",
            "driver": "qra", "time": "08:30", "markets": ["ust10"], "ff": []},
    "jackson": {"name": "Jackson Hole symposium", "tier": 1, "touches": "All", "driver": "fed", "time": None, "markets": ["spx", "ust10", "dxy", "gold"],
                "ff": [("USD", "Jackson Hole Symposium", None, None)]},
    "qend": {"name": "Quarter end: pension rebalancing", "tier": 1, "touches": "All", "driver": None, "time": None, "markets": ["spx", "ust10"], "ff": []},
    "ism_mfg": {"name": "ISM manufacturing", "tier": 2, "touches": "Industrials, materials, copper, 10Y", "driver": "growth", "time": "10:00",
                "markets": ["copper", "ust10"], "ff": [("USD", "ISM Manufacturing PMI", None, "headline"), ("USD", "ISM Manufacturing Prices", None, "prices paid")]},
    "ism_svc": {"name": "ISM services", "tier": 2, "touches": "All", "driver": "growth", "time": "10:00", "markets": ["spx", "ust10"],
                "ff": [("USD", "ISM Services PMI", None, "headline")]},
    "jolts": {"name": "JOLTS job openings", "tier": 2, "touches": "Rates, small caps", "driver": "growth", "time": "10:00", "markets": ["ust10"],
              "ff": [("USD", "JOLTS Job Openings", "jolts", "openings")]},
    "pce": {"name": "PCE inflation, income and spending", "tier": 2, "touches": "Rates, gold, small caps", "driver": "inflation", "time": "08:30",
            "markets": ["ust10", "gold"], "ff": [("USD", "Core PCE Price Index m/m", "core_pce_mm", "core m/m"), ("USD", "Personal Spending m/m", None, "spending")]},
    "retail": {"name": "US retail sales", "tier": 2, "touches": "Consumer sectors, rates", "driver": "growth", "time": "08:30", "markets": ["spx", "ust10"],
               "ff": [("USD", "Retail Sales m/m", "retail_mm", "m/m"), ("USD", "Core Retail Sales m/m", None, "ex autos")]},
    "gdp": {"name": "US GDP, advance estimate", "tier": 2, "touches": "Rates, dollar, cyclicals", "driver": "growth", "time": "08:30", "markets": ["ust10", "dxy"],
            "ff": [("USD", "Advance GDP q/q", "gdp_adv", "q/q annualized"), ("USD", "Advance GDP Price Index q/q", None, "price index")]},
    "fomc_minutes": {"name": "FOMC minutes", "tier": 2, "touches": "Rates", "driver": "fed", "time": "14:00", "markets": ["ust10"],
                     "ff": [("USD", "FOMC Meeting Minutes", None, None)]},
    "ecb": {"name": "ECB decision, press conference 08:45", "tier": 2, "touches": "EUR, European equities, banks", "driver": "ecb", "time": "08:15",
            "markets": ["dxy"], "ff": [("EUR", "Main Refinancing Rate", None, "refi rate"), ("EUR", "Monetary Policy Statement", None, None), ("EUR", "ECB Press Conference", None, None)]},
    "boe": {"name": "Bank of England decision", "tier": 2, "touches": "GBP, gilts", "driver": "boe", "time": "07:00", "markets": ["dxy"],
            "ff": [("GBP", "Official Bank Rate", None, "bank rate"), ("GBP", "MPC Official Bank Rate Votes", None, "votes"), ("GBP", "Monetary Policy Summary", None, None)]},
    "ez_cpi": {"name": "Euro area CPI flash", "tier": 2, "touches": "EUR, ECB pricing", "driver": "inflation_eu", "time": None, "markets": ["dxy"],
               "ff": [("EUR", "CPI Flash Estimate y/y", None, "headline y/y"), ("EUR", "Core CPI Flash Estimate y/y", None, "core y/y")]},
    "china_pmi": {"name": "China official PMIs", "tier": 2, "touches": "Copper, EM, China equities", "driver": "china", "time": None, "markets": ["copper"],
                  "ff": [("CNY", "Manufacturing PMI", None, "manufacturing"), ("CNY", "Non-Manufacturing PMI", None, "non-manufacturing")]},
    "china_pmi_private": {"name": "China RatingDog manufacturing PMI (formerly Caixin)", "tier": 2, "touches": "Copper, EM", "driver": "china", "time": None,
                          "markets": ["copper"], "ff": [("CNY", "RatingDog Manufacturing PMI", None, "manufacturing"), ("CNY", "Caixin Manufacturing PMI", None, "manufacturing")]},
    "china_prices": {"name": "China CPI and PPI", "tier": 2, "touches": "Copper, EM, luxury", "driver": "china", "time": None, "markets": ["copper"],
                     "ff": [("CNY", "CPI y/y", None, "CPI y/y"), ("CNY", "PPI y/y", None, "PPI y/y")]},
    "china_activity": {"name": "China activity data", "tier": 2, "touches": "Copper, EM, luxury, China equities", "driver": "china", "time": None, "markets": ["copper"],
                       "ff": [("CNY", "Industrial Production y/y", None, "industrial production"), ("CNY", "Retail Sales y/y", None, "retail sales"),
                              ("CNY", "Fixed Asset Investment ytd/y", None, "investment")]},
    "china_credit": {"name": "China credit data (new loans, financing, M2)", "tier": 2, "touches": "Copper, EM, the credit impulse", "driver": "china", "time": None,
                     "markets": ["copper"], "ff": [("CNY", "New Loans", None, "new loans"), ("CNY", "M2 Money Supply y/y", None, "M2 y/y")]},
    "china_trade": {"name": "China trade balance", "tier": 2, "touches": "Copper, EM", "driver": "china", "time": None, "markets": ["copper"],
                    "ff": [("CNY", "Trade Balance", None, "balance"), ("CNY", "USD-Denominated Trade Balance", None, "balance")]},
    "china_gdp": {"name": "China GDP", "tier": 2, "touches": "Copper, EM, China equities", "driver": "china", "time": None, "markets": ["copper"],
                  "ff": [("CNY", "GDP q/y", None, "q/y")]},
    "tankan": {"name": "BoJ Tankan", "tier": 2, "touches": "JPY, Nikkei", "driver": "boj", "time": None, "markets": ["dxy"],
               "ff": [("JPY", "Tankan Manufacturing Index", None, "large manufacturers"), ("JPY", "Tankan Non-Manufacturing Index", None, "non-manufacturers")]},
    "opec": {"name": "OPEC+ meeting", "tier": 2, "touches": "Oil, energy equities", "driver": "oil", "time": None, "markets": ["crude"],
             "ff": [("All", "OPEC-JMMC Meetings", None, None), ("All", "OPEC Meetings", None, None)]},
    "eia": {"name": "EIA crude inventories", "tier": 2, "touches": "Oil", "driver": "oil_inv", "time": "10:30", "markets": ["crude"],
            "ff": [("USD", "Crude Oil Inventories", None, "change, mb")]},
    "auction": {"name": "Treasury auction", "tier": 2, "touches": "Rates, tech, REITs", "driver": "auction", "time": "13:00", "markets": ["ust10"], "ff": []},
    "tax": {"name": "US corporate tax payments (quarterly)", "tier": 2, "touches": "Net liquidity, bank reserves, bills", "driver": None, "time": None, "markets": [], "ff": []},
    "quad": {"name": "Quad witching and index rebalances", "tier": 2, "touches": "Equities, VIX", "driver": None, "time": "16:00", "markets": ["spx"], "ff": []},
    "blackout": {"name": "Fed communications blackout begins", "tier": 2, "touches": "Rates", "driver": None, "time": None, "markets": [], "ff": []},
    "holiday": {"name": "Market closed", "tier": 0, "touches": "", "driver": None, "time": None, "markets": [], "ff": []},
}

FF_INDEX = {}
for _key, _row in ROWS.items():
    for _country, _title, _series, _label in _row["ff"]:
        FF_INDEX[(_country, _title)] = (_key, _series, _label)

# Surprise series: FRED series key in catalog.FRED, how the actual is read, its unit against Forex Factory's string,
# the reference-period lag in months (quarters for GDP) and a prior scale for standardizing until the log has twelve.
SURPRISE = {
    "nfp": {"fred": "payrolls", "how": "diff", "unit": "k", "lag": 1, "scale": 75.0, "name": "Payrolls", "tier": 1},
    "unrate": {"fred": "unrate", "how": "level", "unit": "%", "lag": 1, "scale": 0.1, "name": "Unemployment rate", "tier": 1},
    "ahe": {"fred": "ahe", "how": "pct", "unit": "%", "lag": 1, "scale": 0.1, "name": "Average hourly earnings m/m", "tier": 1},
    "cpi_mm": {"fred": "cpi", "how": "pct", "unit": "%", "lag": 1, "scale": 0.1, "name": "CPI m/m", "tier": 1},
    "core_cpi_mm": {"fred": "core_cpi", "how": "pct", "unit": "%", "lag": 1, "scale": 0.1, "name": "Core CPI m/m", "tier": 1},
    "cpi_yy": {"fred": "cpi_nsa", "how": "yoy", "unit": "%", "lag": 1, "scale": 0.1, "name": "CPI y/y", "tier": 1},
    "core_pce_mm": {"fred": "core_pce", "how": "pct", "unit": "%", "lag": 1, "scale": 0.1, "name": "Core PCE m/m", "tier": 2},
    "retail_mm": {"fred": "retail", "how": "pct", "unit": "%", "lag": 1, "scale": 0.5, "name": "Retail sales m/m", "tier": 2},
    "jolts": {"fred": "jolts", "how": "level_m", "unit": "M", "lag": 2, "scale": 0.3, "name": "JOLTS openings", "tier": 2},
    "gdp_adv": {"fred": "gdp_actual", "how": "level", "unit": "%", "lag": "q", "scale": 0.6, "name": "GDP advance", "tier": 2},
}

# Rule-based columns: what a stronger or weaker print does, from the page's own driver logic. "Stronger" is hotter
# data or a more hawkish central bank; the reviewed brief replaces these lines.
DRIVER_TEXT = {
    "growth": ("Yields and the dollar up; cyclicals, copper and banks lead; bonds, gold and utilities lag.",
               "Bonds, gold, staples and utilities up; small caps and cyclicals down; cut odds firm."),
    "inflation": ("Yields and the dollar up; gold, small caps and long-duration tech down; cut odds fade.",
                  "Cut path firm: gold, miners, small caps and homebuilders up; dollar down."),
    "fed": ("Hawkish: yields and the dollar up, curve flattens; gold, small caps and EM down.",
            "Dovish: gold, miners, homebuilders, small caps and EM up; dollar down; banks mixed."),
    "ecb": ("Hawkish: euro up, dollar down, European banks up.", "Dovish: euro down, bunds up."),
    "boj": ("Hawkish: yen up, Nikkei down, global carry unwinds, gold and tech dip.", "Dovish: yen down, Nikkei up, carry trades relax."),
    "boe": ("Hawkish: sterling up, gilts down.", "Dovish: sterling down, gilts up."),
    "inflation_eu": ("Euro up, bunds down, ECB cut odds fade.", "Euro down, bunds up."),
    "china": ("Copper, miners, EM and luxury up.", "Weaker demand against stimulus hopes: copper and EM down, mixed for gold."),
    "oil": ("A pause or a cut in supply: crude up, producers rally.", "A larger add: crude down, the energy exit signal firms."),
    "oil_inv": ("A larger build: crude down.", "A draw: crude and producers up."),
    "auction": ("Strong demand: yields down, everything long duration up.", "A tail: 10Y up, bear steepener, tech and REITs down."),
    "qra": ("Coupon increases: 10Y and term premium up, tech and REITs down, dollar up.",
            "Bills-heavy with coupons flat: net liquidity up, gold and small caps up."),
}

EXPECT_TEXT = {
    "qend": "Rebalancing sells the quarter's winner into the last sessions; the pension gap in section 6 sizes it.",
    "tax": "Treasury cash rises $100B or more and bank reserves fall; net liquidity dips for about two weeks. It matters when SOFR minus IORB moves above +10 bp.",
    "quad": "Largest option expiry of the quarter. Dealer hedging that pinned the market comes off; moves often widen the week after.",
    "blackout": "No official guidance until the Thursday after the meeting; cut odds move on data and press reports only.",
    "holiday": "Thinner liquidity in the other regions; moves exaggerate.",
    "fomc_minutes": "The dissent count and the balance sheet discussion matter more than the recap.",
    "jackson": "The Chair's speech sets the tone into the September meeting.",
}

HOLIDAY_MARKET = {"USD": "US markets closed", "CNY": "China mainland markets closed", "JPY": "Tokyo closed", "GBP": "London closed",
                  "EUR": "Europe (part) closed", "CHF": "Zurich closed", "CAD": "Toronto closed", "AUD": "Sydney closed", "NZD": "Wellington closed"}


# ---------------------------------------------------------------- building the list
def _event(key, date, **kw):
    row = ROWS[key]
    e = {"id": "%s:%s" % (key, date), "key": key, "date": date, "name": row["name"], "tier": row["tier"], "touches": row["touches"],
         "driver": row["driver"], "time": row.get("time"), "time_text": row.get("time_text"), "study": row.get("study"),
         "markets": row.get("markets", []), "cons": [], "confirmed": False, "src": "", "note": "", "kind": "release"}
    e.update(kw)
    return e


def ff_events(ff):
    """Forex Factory entries mapped to catalog rows, grouped by row and date, plus the holidays it lists."""
    rows, order = {}, []
    for x in ff:
        date, t = x["date"][:10], x["date"][11:16]
        if x["impact"] == "Holiday":
            market = HOLIDAY_MARKET.get(x["country"])
            if not market:
                continue
            eid = "holiday:%s:%s" % (x["country"], date)
            if eid not in rows:
                rows[eid] = _event("holiday", date, id=eid, name="%s: %s" % (market, x["title"]), kind="holiday", confirmed=True,
                                   src="Forex Factory", region=x["country"], time=None)
                order.append(eid)
            continue
        hit = FF_INDEX.get((x["country"], x["title"]))
        if not hit:
            continue
        key, series, label = hit
        eid = "%s:%s" % (key, date)
        if eid not in rows:
            rows[eid] = _event(key, date, confirmed=True, src="Forex Factory", region=x["country"], kind="cb" if key in ("fomc", "ecb", "boj", "boe") else "release")
            if ROWS[key].get("time") is None and ROWS[key].get("time_text") is None:
                rows[eid]["time"] = t
            order.append(eid)
        if label is not None and (x["forecast"] or x["previous"] or series):
            rows[eid]["cons"].append({"label": label, "forecast": x["forecast"], "previous": x["previous"], "series": series})
    for e in rows.values():                # consensus items in the catalog's order, not the feed's
        labels = [lab for _, _, _, lab in ROWS[e["key"]]["ff"]]
        e["cons"].sort(key=lambda c: labels.index(c["label"]) if c["label"] in labels else 99)
    return [rows[i] for i in order]


def scheduled_events(today, fomc, ecb, boj, bls_empsit, bls_cpi, auctions, horizon=HORIZON_DAYS):
    """Rows from the central bank pages, the BLS lists, TreasuryDirect and the rules, inside the horizon."""
    d0 = dt.date.fromisoformat(today)
    d1 = d0 + dt.timedelta(days=horizon)
    inside = lambda iso: d0.isoformat() <= iso <= d1.isoformat()       # noqa: E731
    out = []
    for m in fomc or []:
        if not m.get("scheduled"):
            continue
        if inside(m["end"]):
            e = _event("fomc", m["end"], confirmed=True, src="Federal Reserve", kind="cb", note="projections and dot plot; press conference 14:30" if m.get("sep") else "press conference 14:30")
            if m.get("sep"):
                e["name"] = "FOMC decision, projections and dot plot"
            out.append(e)
        bo = blackout(m["start"], m["end"])
        if inside(bo[0]):
            out.append(_event("blackout", bo[0], confirmed=True, src="Federal Reserve meeting dates, blackout rule", kind="mech",
                              name="Fed communications blackout begins (to %s)" % short_label(bo[1]), end=bo[1]))
        mi = minutes_date(m["end"])
        if inside(mi):
            out.append(_event("fomc_minutes", mi, confirmed=False, src="three weeks after the meeting (usual slot)", kind="release",
                              name="FOMC minutes (%s meeting)" % MONTHS[int(m["end"][5:7]) - 1]))
    for d in ecb or []:
        if inside(d):
            out.append(_event("ecb", d, confirmed=True, src="ECB", kind="cb"))
    for d in boj or []:
        if inside(d):
            out.append(_event("boj", d, confirmed=True, src="Bank of Japan", kind="cb"))
    for d in bls_empsit or []:
        if inside(d):
            out.append(_event("payrolls", d, confirmed=True, src="BLS schedule"))
    # payrolls beyond the BLS list: the rule
    have = set(bls_empsit or [])
    for k in range(0, 4):
        y, m = d0.year + (d0.month - 1 + k) // 12, (d0.month - 1 + k) % 12 + 1
        r = payrolls_rule(y, m).isoformat()
        if inside(r) and r not in have and not any(abs((dt.date.fromisoformat(h) - dt.date.fromisoformat(r)).days) <= 10 for h in have):
            out.append(_event("payrolls", r, confirmed=False, src="usual slot (three Fridays after the reference week)"))
    for d in bls_cpi or []:
        if inside(d):
            out.append(_event("cpi", d, confirmed=True, src="BLS schedule"))
    for a in auctions or []:
        if inside(a["date"]):
            out.append(_event("auction", a["date"], id="auction:%s:%s" % (a["term"], a["date"]), confirmed=True, src="TreasuryDirect", kind="auction",
                              name="%s Treasury auction%s" % ({"10Y": "10-year", "20Y": "20-year", "30Y": "30-year"}[a["term"]], " (reopening)" if a["reopening"] else "")))
    for k in range(0, 4):
        y, m = d0.year + (d0.month - 1 + k) // 12, (d0.month - 1 + k) % 12 + 1
        mfg, svc = ism_dates(y, m)
        if inside(mfg.isoformat()):
            out.append(_event("ism_mfg", mfg.isoformat(), confirmed=False, src="usual slot (first business day)"))
        if inside(svc.isoformat()):
            out.append(_event("ism_svc", svc.isoformat(), confirmed=False, src="usual slot (third business day)"))
        if m in (2, 5, 8, 11):
            q = qra_rule(y, m).isoformat()
            if inside(q):
                out.append(_event("qra", q, confirmed=False, src="usual slot (the Wednesday nearest the first of the month)"))
        if m in (3, 6, 9, 12):
            f = third_friday(y, m).isoformat()
            if inside(f):
                out.append(_event("quad", f, confirmed=True, src="third Friday of the quarter's last month", kind="mech"))
            qe = quarter_end(dt.date(y, m, 1)).isoformat()
            if inside(qe):
                e = _event("qend", qe, confirmed=True, src="last business day of the quarter", kind="mech")
                if m == 9:
                    e["name"] = "Quarter end: pension rebalancing; US fiscal year ends"
                out.append(e)
    for y in (d0.year, d0.year + 1):
        for d, kind in tax_dates(y):
            if inside(d.isoformat()):
                out.append(_event("tax", d.isoformat(), confirmed=True, src="tax calendar", kind="mech",
                                  name="US corporate tax payments (quarterly)" if kind == "corporate" else "US individual tax deadline"))
        for iso, name in holidays_for(y).items():
            if inside(iso):
                out.append(_event("holiday", iso, id="holiday:USD:%s" % iso, name="US markets closed: %s" % name, kind="holiday", confirmed=True, src="NYSE calendar", region="USD"))
        for iso, name in ((dt.date(y, 10, 1).isoformat(), "China mainland markets closed 1 to 7 Oct: National Day"),):
            if inside(iso):
                out.append(_event("holiday", iso, id="holiday:CNY:%s" % iso, name=name, kind="holiday", confirmed=True, src="mainland exchange calendar", region="CNY"))
    return out


def merge(ff_rows, sched_rows, ff_window):
    """Forex Factory rows win inside the week they cover; scheduled rows fill the rest. Same key and date merge."""
    by_id = {}
    for e in sched_rows:
        by_id[e["id"]] = e
    for e in ff_rows:
        if e["id"] in by_id:
            base = by_id[e["id"]]
            base["cons"] = e["cons"] or base["cons"]
            base["src"] = ("Forex Factory, confirms the " + base["src"]) if not base["confirmed"] else (base["src"] + " and Forex Factory")
            base["confirmed"] = True
            if base.get("time") is None and base.get("time_text") is None and e.get("time"):
                base["time"] = e["time"]
        else:
            by_id[e["id"]] = e
    lo, hi = ff_window
    ff_keys = set(k for k, _, _ in FF_INDEX.values())
    ff_ids = set(e["id"] for e in ff_rows)
    out = []
    for e in by_id.values():
        if lo and hi and lo <= e["date"] <= hi and e["key"] in ff_keys and e["id"] not in ff_ids and e["kind"] not in ("mech", "auction", "holiday") and e["key"] != "fomc_minutes" and not e["confirmed"]:
            continue            # a usual-slot row the week's feed does not carry: the feed is right, drop the guess
        out.append(e)
    out.sort(key=lambda e: (e["date"], sort_time(e), -e["tier"]))
    return out


def sort_time(e):
    """Holidays first, then rows with a clock time, then Tokyo-midday rows (the evening before in New York) first of all."""
    if e["kind"] == "holiday":
        return "00:00"
    if e.get("time_text"):
        return "00:01"
    return e.get("time") or "23:59"


def week_start(today):
    d = dt.date.fromisoformat(today)
    if d.weekday() >= 5:
        d += dt.timedelta(days=7 - d.weekday())
    else:
        d -= dt.timedelta(days=d.weekday())
    return d


def ranges(today):
    """The three tabs: this week (Monday to Sunday), the next two weeks, the next two months."""
    w = week_start(today)
    return {"week": (w.isoformat(), (w + dt.timedelta(days=6)).isoformat()),
            "two_weeks": ((w + dt.timedelta(days=7)).isoformat(), (w + dt.timedelta(days=20)).isoformat()),
            "two_months": ((w + dt.timedelta(days=21)).isoformat(), (dt.date.fromisoformat(today) + dt.timedelta(days=HORIZON_DAYS)).isoformat())}


def mechanical_next(today):
    """The Next column of the calendar effects table."""
    d = dt.date.fromisoformat(today)
    tom = turn_of_month(d)
    opex = next_opex(d)
    quad = next_quad_witching(d)
    qw = qend_window(d)
    bb = buyback_window(d)
    tax = next((t for y in (d.year, d.year + 1) for t, _ in tax_dates(y) if t >= d), None)
    return {"tom": span_label(tom[0].isoformat(), tom[1].isoformat()),
            "opex": "%s%s" % (span_label((opex - dt.timedelta(days=4)).isoformat(), opex.isoformat()), " (quad witching)" if opex == quad else ""),
            "qend": span_label(qw[0].isoformat(), qw[1].isoformat()),
            "tax": short_label(tax.isoformat()) if tax else "",
            "buyback": span_label(bb[0].isoformat(), bb[1].isoformat()),
            "cycle": cycle_label(d.year)}

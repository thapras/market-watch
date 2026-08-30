"""Data sources for Market Watch. Standard library only.

Free feeds, no API keys:
  FRED       fredgraph CSV endpoint (fred.stlouisfed.org/graph/fredgraph.csv)
  Yahoo      chart endpoint (query1.finance.yahoo.com/v8/finance/chart)
  ECB        data portal SDMX CSV (data-api.ecb.europa.eu)
  BIS        data portal SDMX CSV, central bank policy rates (stats.bis.org)
  EIA        weekly and monthly history tables (www.eia.gov/dnav); the CSV downloads sit behind
             signed redirects, the HTML history pages do not
  Cboe       index history CSVs (cdn.cboe.com)
  Treasury   FiscalData API, Monthly Statement of the Public Debt (api.fiscaldata.treasury.gov)
  BoJ        time-series HTML tables (stat-search.boj.or.jp)
  multpl     monthly S&P 500 P/E table (www.multpl.com)
  ICI        weekly money market fund release (www.ici.org)
  Cleveland  Fed inflation nowcast chart file (www.clevelandfed.org), about 7 MB
  SSGA       daily holdings workbooks for the SPDR ETFs (www.ssga.com), xlsx read with zipfile
  CFTC       Commitments of Traders through the Socrata API (publicreporting.cftc.gov), legacy and TFF
  Cboe       daily put/call ratios, one JSON per day (cdn.cboe.com/data/us/options/market_statistics/daily)
  AAII       the current week's survey from the page (www.aaii.com); history is logged run by run
  FINRA      margin statistics table (www.finra.org), about thirteen months
  DIX        SqueezeMetrics dark pool index and gamma exposure CSV (squeezemetrics.com)
  alt.me     crypto fear and greed index (api.alternative.me)

A series is a list of (date, value) tuples, ISO dates ascending, no gaps filled,
no missing values. Everything downstream works on that shape.

FRED sits behind Akamai, which stalls clients that claim to be a browser without
looking like one. A plain client User-Agent is accepted; keep it that way.
"""
import csv
import datetime as dt
import hashlib
import html as html_mod
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

UA = "MarketWatch/0.1 (personal markets dashboard; nightly fetch)"
TIMEOUT = 40
CACHE_DIR = os.environ.get("MW_CACHE")        # optional: cache responses for 12 hours while developing
CACHE_TTL = 12 * 3600
LAST_FROM_CACHE = False       # set by get(): the fetch loops skip their polite sleep after a cache hit


class SourceError(Exception):
    pass


def get(url, retries=2):
    """GET a URL as text, with retries and the optional dev cache."""
    path = None
    if CACHE_DIR:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".txt")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
            with open(path, encoding="utf-8") as f:
                global LAST_FROM_CACHE
                LAST_FROM_CACHE = True
                return f.read()
    LAST_FROM_CACHE = False
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read().decode("utf-8", "replace")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(body)
            return body
        except urllib.error.HTTPError as e:
            last = e
            if 400 <= e.code < 500:         # not found or refused: retrying will not help
                break
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:      # noqa: BLE001, we want to retry on anything transient
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise SourceError("%s: %s" % (url, last))


def _clean(pairs):
    """Sort ascending, drop duplicates (keep the last), drop None and NaN (the BIS files carry NaN on weekends)."""
    seen = {}
    for d, v in pairs:
        if v is None:
            continue
        v = float(v)
        if v != v:
            continue
        seen[d] = v
    return sorted(seen.items())


# ---------------------------------------------------------------- FRED
def fred(series_id, start="2010-01-01"):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s" % (series_id, start)
    txt = get(url)
    rows = list(csv.reader(io.StringIO(txt)))
    if not rows or not rows[0] or "observation_date" not in rows[0][0]:
        raise SourceError("FRED %s: unexpected response: %s" % (series_id, txt[:80].replace("\n", " ")))
    out = []
    for r in rows[1:]:
        if len(r) < 2 or r[1] in ("", "."):
            continue
        try:
            out.append((r[0], float(r[1])))
        except ValueError:
            continue
    if not out:
        raise SourceError("FRED %s: no observations" % series_id)
    return _clean(out)


# ---------------------------------------------------------------- Yahoo
def yahoo(symbol, rng="5y", since=None):
    """Daily closes. Returns {'close': series, 'adj': series, 'currency': str}.
    since='2005-01-01' asks for daily data from that date (range=max would come back monthly)."""
    if since:
        p1 = int(dt.datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())
        p2 = int(time.time()) + 86400
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=%d&period2=%d&interval=1d" % (
            urllib.parse.quote(symbol), p1, p2)
    else:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=1d" % (
            urllib.parse.quote(symbol), rng)
    j = json.loads(get(url))
    chart = j.get("chart") or {}
    if chart.get("error"):
        raise SourceError("Yahoo %s: %s" % (symbol, chart["error"]))
    res = (chart.get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise SourceError("Yahoo %s: empty result" % symbol)
    off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    close = q.get("close") or []
    adj = ((res["indicators"].get("adjclose") or [{}])[0].get("adjclose")) or close
    def day(t):
        return (dt.datetime.utcfromtimestamp(t) + dt.timedelta(seconds=off)).strftime("%Y-%m-%d")
    closes = _clean((day(t), c) for t, c in zip(ts, close))
    adjs = _clean((day(t), a) for t, a in zip(ts, adj))
    if len(closes) < 30:
        raise SourceError("Yahoo %s: only %d closes" % (symbol, len(closes)))
    return {"close": closes, "adj": adjs, "currency": (res.get("meta") or {}).get("currency")}


# ---------------------------------------------------------------- ECB
def _ecb_period(p):
    """'2026-07' -> '2026-07-01'; '2026-W34' -> Friday of that ISO week; daily stays."""
    if len(p) == 7 and p[4] == "-":
        return p + "-01"
    if "-W" in p:
        y, w = p.split("-W")
        return dt.date.fromisocalendar(int(y), int(w), 5).isoformat()
    return p


def ecb(flow, key, start="2010-01-01"):
    url = "https://data-api.ecb.europa.eu/service/data/%s/%s?format=csvdata&startPeriod=%s" % (flow, key, start)
    txt = get(url)
    rows = list(csv.DictReader(io.StringIO(txt)))
    out = []
    for r in rows:
        v = r.get("OBS_VALUE")
        if v in (None, ""):
            continue
        out.append((_ecb_period(r["TIME_PERIOD"]), float(v)))
    if not out:
        raise SourceError("ECB %s/%s: no observations" % (flow, key))
    return _clean(out)


# ---------------------------------------------------------------- BIS (policy rates)
def bis_policy(area, start="2019-01-01"):
    """Daily central bank policy rate from the BIS data portal (WS_CBPOL), percent.
    Note: for China the BIS series is the one-year loan prime rate."""
    url = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.%s?format=csv&startPeriod=%s&detail=dataonly" % (area, start)
    txt = get(url)
    out = []
    for r in csv.DictReader(io.StringIO(txt)):
        v = r.get("OBS_VALUE")
        if v in (None, ""):
            continue
        out.append((r["TIME_PERIOD"], float(v)))
    if not out:
        raise SourceError("BIS %s: no observations" % area)
    return _clean(out)


# ---------------------------------------------------------------- EIA (history tables)
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _strip(cell):
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", cell)).replace("\xa0", " ").strip()


def parse_eia_weekly(txt):
    """Weekly history table: one row per month (class B6), then date (B5) and value (B3) pairs."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        m = re.search(r"class='B6'>(?:&nbsp;|\s)*(\d{4})-([A-Z][a-z]{2})", row)
        if not m:
            continue
        year, month = int(m.group(1)), _MONTHS.index(m.group(2)) + 1
        for mm, dd, val in re.findall(r"class='B5'>\s*(\d{2})/(\d{2})(?:&nbsp;|\s)*</td>\s*<td class='B3'>\s*([\d,]+(?:\.\d+)?)", row):
            y = year + (1 if (int(mm) == 1 and month == 12) else -1 if (int(mm) == 12 and month == 1) else 0)
            out.append(("%d-%s-%s" % (y, mm, dd), float(val.replace(",", ""))))
    return _clean(out)


def parse_eia_monthly(txt):
    """Monthly history table: one row per year (class B4) with twelve value cells (B3)."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        m = re.search(r"class='B4'>(?:&nbsp;|\s)*(\d{4})\s*</td>", row)
        if not m:
            continue
        year = int(m.group(1))
        cells = re.findall(r"<td class='B3'>(.*?)</td>", row, re.S)
        for i, v in enumerate(cells[:12]):
            v = _strip(v).replace(",", "")
            if re.match(r"^-?\d+(\.\d+)?$", v):
                out.append(("%d-%02d-01" % (year, i + 1), float(v)))
    return _clean(out)


def eia_weekly(series_id):
    txt = get("https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=%s&f=W" % series_id)
    out = parse_eia_weekly(txt)
    if not out:
        raise SourceError("EIA %s: no observations parsed" % series_id)
    return out


def eia_monthly(url):
    out = parse_eia_monthly(get(url))
    if not out:
        raise SourceError("EIA %s: no observations parsed" % url)
    return out


# ---------------------------------------------------------------- Cboe (index histories)
def cboe_index(name):
    """Daily closes of a Cboe index from its history CSV (DATE, ..., CLOSE)."""
    txt = get("https://cdn.cboe.com/api/global/us_indices/daily_prices/%s_History.csv" % name)
    out = []
    for r in list(csv.reader(io.StringIO(txt)))[1:]:
        if len(r) < 2:
            continue
        try:
            out.append((dt.datetime.strptime(r[0].strip(), "%m/%d/%Y").date().isoformat(), float(r[-1])))
        except ValueError:
            continue
    if not out:
        raise SourceError("Cboe %s: no observations" % name)
    return _clean(out)


# ---------------------------------------------------------------- Treasury FiscalData
def fiscaldata_bills_share():
    """Treasury bills as a share of marketable debt outstanding, percent, monthly (MSPD table 1)."""
    url = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/debt/mspd/mspd_table_1"
           "?fields=record_date,security_type_desc,security_class_desc,total_mil_amt"
           "&filter=security_type_desc:in:(Marketable,Total%20Marketable)&sort=-record_date&page%5Bsize%5D=5000")
    j = json.loads(get(url))
    bills, total = {}, {}
    for r in j.get("data", []):
        d = r.get("record_date")
        try:
            v = float(r.get("total_mil_amt"))
        except (TypeError, ValueError):
            continue
        if r.get("security_type_desc") == "Total Marketable":
            total[d] = v
        elif r.get("security_class_desc") == "Bills":
            bills[d] = v
    out = [(d, bills[d] / total[d] * 100.0) for d in bills if total.get(d)]
    if not out:
        raise SourceError("FiscalData MSPD: no bills share computed")
    return _clean(out)


# ---------------------------------------------------------------- Bank of Japan
def parse_boj_table(txt, code):
    """One series out of a BoJ time-series HTML table: the 'Series code' row names the columns,
    data rows start with YYYY/MM. Dates become the first of the month."""
    codes, out = None, []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cells = [_strip(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        cells = [c for c in cells if c]
        if not cells:
            continue
        if cells[0].lower().startswith("series code"):
            codes = cells[1:]
            continue
        if codes and re.match(r"^\d{4}/\d{2}$", cells[0]) and code in codes:
            i = codes.index(code) + 1
            if i < len(cells):
                try:
                    out.append((cells[0].replace("/", "-") + "-01", float(cells[i].replace(",", ""))))
                except ValueError:
                    continue
    return _clean(out)


def boj_series(table, code):
    """table like 'md02_m_1_en' (money stock, monthly), code like "MD02'MAM1NAM2M2MO" (M2, 100 million yen)."""
    txt = get("https://www.stat-search.boj.or.jp/ssi/mtshtml/%s.html" % table)
    out = parse_boj_table(txt, code)
    if not out:
        raise SourceError("BoJ %s %s: no observations parsed" % (table, code))
    return out


# ---------------------------------------------------------------- multpl (valuation tables)
def parse_multpl(txt):
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cells = [_strip(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) < 2:
            continue
        try:
            d = dt.datetime.strptime(cells[0], "%b %d, %Y").date().isoformat()
            v = float(cells[1].split()[-1].replace(",", ""))
        except (ValueError, IndexError):
            continue
        out.append((d, v))
    return _clean(out)


def multpl(slug):
    """Monthly table from multpl.com, e.g. 's-p-500-pe-ratio' (trailing twelve-month P/E) or 'shiller-pe'."""
    out = parse_multpl(get("https://www.multpl.com/%s/table/by-month" % slug))
    if not out:
        raise SourceError("multpl %s: no observations parsed" % slug)
    return out


# ---------------------------------------------------------------- ICI (money market funds)
def parse_ici_mmf(txt):
    """Latest weekly totals from the ICI release page: {'date', 'total', 'prior', 'change'} in $ billions."""
    t = re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", txt)))
    i = t.find("Assets of Money Market Funds")
    if i < 0:
        raise SourceError("ICI: assets table not found")
    seg = t[i:i + 4000]
    dates = re.findall(r"(\d{1,2}/\d{1,2}/\d{4})", seg)
    m = re.search(r"Total ([\d,]+\.?\d*) ([\d,]+\.?\d*) (-?[\d,]+\.?\d*)", seg)
    if not m or not dates:
        raise SourceError("ICI: totals not found")
    num = lambda x: float(x.replace(",", ""))     # noqa: E731
    return {"date": dt.datetime.strptime(dates[0], "%m/%d/%Y").date().isoformat(),
            "total": num(m.group(1)), "prior": num(m.group(2)), "change": num(m.group(3))}


def ici_mmf():
    return parse_ici_mmf(get("https://www.ici.org/research/stats/mmf"))


# ---------------------------------------------------------------- Cleveland Fed (inflation nowcast)
def parse_cleveland_nowcast(j):
    """The chart file is a list of monthly charts (subcaption 'YYYY-M'); each has nowcast and actual series.
    Returns the newest month with a core CPI nowcast, plus the prior month's actual print."""
    charts = [ch for ch in j if isinstance(ch, dict) and ch.get("chart")]

    def month_of(ch):
        y, m = ch["chart"].get("subcaption", "").split("-")
        return "%s-%02d" % (y, int(m))

    def last_value(ch, name):
        for ds in ch.get("dataset", []):
            if ds.get("seriesname") == name:
                vals = [x.get("value") for x in ds.get("data", []) if x.get("value") not in ("", None)]
                return float(vals[-1]) if vals else None
        return None

    for k in range(len(charts) - 1, 0, -1):
        core = last_value(charts[k], "Core CPI Inflation")
        if core is None:
            continue
        prev = charts[k - 1]
        return {"month": month_of(charts[k]), "asof": charts[k]["chart"].get("_comment", "")[:10],
                "core_cpi": core, "cpi": last_value(charts[k], "CPI Inflation"),
                "prior_month": month_of(prev), "prior_core_actual": last_value(prev, "Actual Core CPI Inflation")}
    raise SourceError("Cleveland Fed: no nowcast found")


def cleveland_nowcast():
    url = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json"
    return parse_cleveland_nowcast(json.loads(get(url)))


# ---------------------------------------------------------------- SSGA (SPDR holdings)
def _xlsx_rows(blob):
    """Rows of the first sheet of an xlsx as {column letter: text}, keyed by row number."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    strings = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode("utf-8", "replace"), re.S):
            strings.append(html_mod.unescape("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")
    rows = {}
    for col, row, attrs, val in re.findall(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(?:<f>.*?</f>)?<v>(.*?)</v></c>)', sheet, re.S):
        if val == "":
            continue
        if 't="s"' in attrs:
            try:
                val = strings[int(val)]
            except (ValueError, IndexError):
                continue
        rows.setdefault(int(row), {})[col] = val
    return rows


def parse_ssga_holdings(blob):
    """Holdings as [{'ticker', 'name', 'weight', 'sector'}], from the row after the 'Ticker' header."""
    rows = _xlsx_rows(blob)
    header = None
    for n in sorted(rows):
        vals = {v.strip().lower(): k for k, v in rows[n].items()}
        if "ticker" in vals and "name" in vals:
            header, cols = n, vals
            break
    if header is None:
        raise SourceError("SSGA holdings: header row not found")
    out = []
    for n in sorted(rows):
        if n <= header:
            continue
        r = rows[n]
        tk = r.get(cols["ticker"], "").strip()
        if not tk or tk == "-":
            continue
        try:
            w = float(r.get(cols.get("weight", ""), "0") or 0)
        except ValueError:
            w = 0.0
        out.append({"ticker": tk, "name": r.get(cols["name"], "").strip(), "weight": w,
                    "sector": r.get(cols.get("sector", ""), "").strip()})
    if not out:
        raise SourceError("SSGA holdings: no rows parsed")
    return out


def ssga_holdings(fund):
    """fund like 'spy', 'xhb'. Daily holdings workbook from SSGA."""
    url = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-%s.xlsx" % fund
    path = None
    if CACHE_DIR:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".bin")
        if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
            with open(path, "rb") as f:
                return parse_ssga_holdings(f.read())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        blob = r.read()
    if path:
        with open(path, "wb") as f:
            f.write(blob)
    return parse_ssga_holdings(blob)


# ---------------------------------------------------------------- CFTC (Socrata)
CFTC_DATASETS = {"legacy": "6dca-aqww", "tff": "gpe5-46if"}


def cftc(dataset, market, since="2023-01-01"):
    """Weekly rows for one contract, ascending by report date. dataset 'legacy' or 'tff'."""
    where = "market_and_exchange_names='%s' AND report_date_as_yyyy_mm_dd > '%s'" % (market.replace("'", "''"), since)
    url = "https://publicreporting.cftc.gov/resource/%s.json?%s" % (CFTC_DATASETS[dataset], urllib.parse.urlencode(
        {"$where": where, "$order": "report_date_as_yyyy_mm_dd ASC", "$limit": "1000"}))
    rows = json.loads(get(url))
    out = []
    for r in rows:
        d = (r.get("report_date_as_yyyy_mm_dd") or "")[:10]
        if not d:
            continue
        row = {"date": d}
        for k, v in r.items():
            try:
                row[k] = float(v)
            except (TypeError, ValueError):
                pass
        out.append(row)
    if not out:
        raise SourceError("CFTC %s %s: no rows" % (dataset, market))
    out.sort(key=lambda x: x["date"])
    return out


# ---------------------------------------------------------------- Cboe daily put/call
def parse_cboe_daily(txt):
    j = json.loads(txt)
    out = {}
    for r in j.get("ratios", []):
        name, val = (r.get("name") or "").upper(), r.get("value")
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if name.startswith("TOTAL"):
            out["total"] = v
        elif name.startswith("INDEX"):
            out["index"] = v
        elif name.startswith("EQUITY"):
            out["equity"] = v
    if "total" not in out:
        raise SourceError("Cboe daily: no ratios")
    return out


def cboe_daily_options(date):
    """{'total','index','equity'} put/call ratios for one session (ISO date); SourceError on a non-session."""
    return parse_cboe_daily(get("https://cdn.cboe.com/data/us/options/market_statistics/daily/%s_daily_options" % date, retries=0))


# ---------------------------------------------------------------- AAII (current week)
def parse_aaii(txt):
    out = {}
    for key, cls in (("bull", "bull"), ("neutral", "neut"), ("bear", "bear")):
        m = re.search(r'class="ssv2-snum %s">\s*([\d.]+)%%' % cls, txt)
        if not m:
            raise SourceError("AAII: %s not found" % key)
        out[key] = float(m.group(1))
    m = re.search(r"[Ww]eek ending ([A-Z][a-z]+ \d{1,2}, \d{4})", txt)
    if not m:
        raise SourceError("AAII: week ending date not found")
    out["date"] = dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    out["spread"] = out["bull"] - out["bear"]
    return out


def aaii():
    return parse_aaii(get("https://www.aaii.com/sentimentsurvey"))


# ---------------------------------------------------------------- FINRA margin statistics
def parse_finra_margin(txt):
    """Monthly debit balances in margin accounts, $ millions, from the statistics table."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cells = [_strip(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(cells) < 2:
            continue
        m = re.match(r"^([A-Z][a-z]{2})-(\d{2})$", cells[0])
        if not m:
            continue
        try:
            v = float(cells[1].replace(",", ""))
        except ValueError:
            continue
        month = _MONTHS.index(m.group(1)) + 1
        out.append(("20%s-%02d-01" % (m.group(2), month), v))
    if not out:
        raise SourceError("FINRA: no rows parsed")
    return _clean(out)


def finra_margin():
    return parse_finra_margin(get("https://www.finra.org/investors/learn-to-invest/advanced-investing/margin-statistics"))


# ---------------------------------------------------------------- DIX and GEX
def dix():
    """{'dix': series (0 to 1), 'gex': series ($), 'price': series} from the SqueezeMetrics CSV."""
    rows = list(csv.DictReader(io.StringIO(get("https://squeezemetrics.com/monitor/static/DIX.csv"))))
    out = {"dix": [], "gex": [], "price": []}
    for r in rows:
        try:
            out["dix"].append((r["date"], float(r["dix"])))
            out["gex"].append((r["date"], float(r["gex"])))
            out["price"].append((r["date"], float(r["price"])))
        except (KeyError, ValueError):
            continue
    if not out["dix"]:
        raise SourceError("DIX: no rows")
    return {k: _clean(v) for k, v in out.items()}


# ---------------------------------------------------------------- crypto fear and greed
def crypto_fng():
    j = json.loads(get("https://api.alternative.me/fng/?limit=1200&format=json"))
    out = []
    for r in j.get("data", []):
        try:
            out.append((dt.datetime.utcfromtimestamp(int(r["timestamp"])).date().isoformat(), float(r["value"])))
        except (KeyError, ValueError):
            continue
    if not out:
        raise SourceError("alternative.me: no rows")
    return _clean(out)


# ================================================================ v4: the calendar feeds
# Forex Factory's public JSON (this week only, Sunday to Saturday, no actuals), the Fed's FOMC calendar and its
# historical pages, the ECB and BoJ meeting pages, the BLS release archives and schedules (payrolls, CPI),
# TreasuryDirect's upcoming auctions, and the Cboe delayed SPX option chain (about 12 MB) for implied moves.
_MONTH_NUM = {m.lower(): i + 1 for i, m in enumerate(_MONTHS)}
_MONTH_NUM.update({"sept": 9, "january": 1, "february": 2, "march": 3, "april": 4, "june": 6, "july": 7, "august": 8,
                   "september": 9, "october": 10, "november": 11, "december": 12})


def _month_num(name):
    key = name.strip().rstrip(".").lower()
    if key in _MONTH_NUM:
        return _MONTH_NUM[key]
    return _MONTH_NUM.get(key[:3])


def ff_calendar():
    """Forex Factory's calendar for the current week: title, country code, ISO datetime with the Eastern offset,
    impact (High, Medium, Low, Holiday), forecast and previous as the strings shown on the site."""
    j = json.loads(get("https://nfs.faireconomy.media/ff_calendar_thisweek.json"))
    out = []
    for e in j:
        if not e.get("title") or not e.get("date"):
            continue
        out.append({"title": e["title"].strip(), "country": (e.get("country") or "").strip(), "date": e["date"],
                    "impact": (e.get("impact") or "").strip(), "forecast": (e.get("forecast") or "").strip(),
                    "previous": (e.get("previous") or "").strip()})
    if not out:
        raise SourceError("Forex Factory: empty calendar")
    return out


def _fomc_span(month_text, day_text, year):
    """('Apr/May', '30-1', 2019) -> ('2019-04-30', '2019-05-01'); ('October', '4', 2019) -> one day."""
    months = [_month_num(m) for m in month_text.split("/")]
    days = day_text.replace("*", "").strip()
    if not months or None in months:
        return None
    if "-" in days:
        d1, d2 = [int(x) for x in days.split("-")[:2]]
        return dt.date(year, months[0], d1).isoformat(), dt.date(year, months[-1], d2).isoformat()
    d = dt.date(year, months[0], int(days)).isoformat()
    return d, d


def parse_fomc_calendar(txt):
    """Meetings from the Fed's calendar page: [{'start', 'end', 'sep': projections meeting, 'scheduled'}], ascending.
    Notation votes are skipped; unscheduled meetings are kept with scheduled False."""
    out = []
    for panel in re.split(r'<div class="panel panel-default">', txt)[1:]:
        m = re.search(r"(\d{4}) FOMC Meetings", panel)
        if not m:
            continue
        year = int(m.group(1))
        for month, day in re.findall(r'fomc-meeting__month[^>]*>\s*(?:<strong>)?([^<]+?)(?:</strong>)?\s*</div>\s*<div class="fomc-meeting__date[^>]*>([^<]*)<', panel):
            day = html_mod.unescape(day).strip()
            if "notation" in day.lower():
                continue
            span = _fomc_span(month, re.sub(r"\(.*?\)", "", day), year)
            if span:
                out.append({"start": span[0], "end": span[1], "sep": "*" in day, "scheduled": "unscheduled" not in day.lower()})
    if not out:
        raise SourceError("FOMC calendar: no meetings parsed")
    return sorted(out, key=lambda x: x["start"])


def parse_fomc_history(txt):
    """Meetings from one of the Fed's historical year pages (h5 headings such as 'January 29-30 Meeting - 2019')."""
    out = []
    for month, day, note, year in re.findall(r"<h5[^>]*>\s*([A-Za-z/]+)\s+([\d-]+)\s*(\([^)]*\))?\s*(?:Meeting)?\s*-\s*(\d{4})", txt):
        span = _fomc_span(month, day, int(year))
        if span:
            out.append({"start": span[0], "end": span[1], "sep": False, "scheduled": "unscheduled" not in note.lower()})
    return sorted(out, key=lambda x: x["start"])


def fomc_calendar():
    return parse_fomc_calendar(get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"))


def fomc_history(year):
    return parse_fomc_history(get("https://www.federalreserve.gov/monetarypolicy/fomchistorical%d.htm" % year))


def parse_ecb_calendar(txt):
    """Decision days from the ECB's Governing Council calendar: the second day of each monetary policy meeting."""
    out = []
    for d, m, y, text in re.findall(r"<dt>\s*(\d{2})/(\d{2})/(\d{4})\s*</dt>\s*<dd>(.*?)</dd>", txt, re.S):
        t = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", " ", text))).strip().lower()
        if "monetary policy meeting" in t and "non-monetary" not in t and "(day 1)" not in t:
            out.append("%s-%s-%s" % (y, m, d))
    if not out:
        raise SourceError("ECB calendar: no meetings parsed")
    days = sorted(set(out))
    # a meeting listed without day markers shows both days: keep the second
    return [d for i, d in enumerate(days) if i + 1 == len(days) or (dt.date.fromisoformat(days[i + 1]) - dt.date.fromisoformat(d)).days > 1]


def ecb_calendar():
    return parse_ecb_calendar(get("https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"))


def parse_boj_calendar(txt):
    """Decision days from the BoJ's meeting schedule: the last day of each meeting, per year table."""
    out = []
    parts = re.split(r'<h2 id="p(\d{4})">', txt)
    for i in range(1, len(parts) - 1, 2):
        year, body = int(parts[i]), parts[i + 1]
        table = re.search(r"<table.*?</table>", body, re.S)
        if not table:
            continue
        for row in re.findall(r"<tr.*?</tr>", table.group(0), re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if not cells:
                continue
            first = re.sub(r"\s+", " ", html_mod.unescape(re.sub("<[^>]+>", " ", cells[0]))).strip()
            m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2})\s*\([^)]*\)(?:\s*,\s*(\d{1,2})\s*\([^)]*\))?", first)
            if not m:
                continue
            mon = _month_num(m.group(1))
            if not mon:
                continue
            day = int(m.group(3) or m.group(2))
            out.append(dt.date(year, mon, day).isoformat())
    if not out:
        raise SourceError("BoJ calendar: no meetings parsed")
    return sorted(set(out))


def boj_calendar():
    return parse_boj_calendar(get("https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"))


def parse_bls_archive(txt, kind):
    """Release dates from a BLS news-release archive page: every archives/<kind>_MMDDYYYY.htm link, past and scheduled."""
    out = set()
    for mm, dd, yyyy in re.findall(r"archives/%s_(\d{2})(\d{2})(\d{4})\.htm" % re.escape(kind), txt):
        try:
            out.add(dt.date(int(yyyy), int(mm), int(dd)).isoformat())
        except ValueError:
            continue
    if not out:
        raise SourceError("BLS archive %s: no release dates parsed" % kind)
    return sorted(out)


def parse_bls_schedule(txt):
    """[(release date, reference month text, time text)] from a BLS schedule page's release-list table."""
    out = []
    for ref, date, time_ in re.findall(r"<tr[^>]*>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*<td>([^<]*)</td>\s*</tr>", txt):
        m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})", date.strip())
        if not m:
            continue
        mon = _month_num(m.group(1))
        if not mon:
            continue
        out.append((dt.date(int(m.group(3)), mon, int(m.group(2))).isoformat(), ref.strip(), time_.strip()))
    if not out:
        raise SourceError("BLS schedule: no rows parsed")
    return sorted(out)


def bls_release_dates(kind):
    """kind 'empsit' (payrolls) or 'cpi': the archive page (history since 1994 plus the pre-listed schedule) and the
    current schedule page, merged. Returns sorted ISO dates."""
    dates = set(parse_bls_archive(get("https://www.bls.gov/bls/news-release/%s.htm" % kind), kind))
    try:
        dates.update(d for d, _, _ in parse_bls_schedule(get("https://www.bls.gov/schedule/news_release/%s.htm" % kind)))
    except SourceError:
        pass
    return sorted(dates)


_TD_TERMS = {"10Y": ("10-Year", "9-Year 11-Month", "9-Year 10-Month"), "20Y": ("20-Year", "19-Year 11-Month", "19-Year 10-Month"),
             "30Y": ("30-Year", "29-Year 11-Month", "29-Year 10-Month")}


def parse_treasury_upcoming(j):
    """Announced coupon auctions of the long tenors: [{'date', 'term', 'reopening', 'amount'}]."""
    out = []
    for r in j:
        if r.get("securityType") not in ("Note", "Bond"):
            continue
        term = next((k for k, names in _TD_TERMS.items() if r.get("securityTerm") in names), None)
        if not term:
            continue
        try:
            amount = float(r["offeringAmount"]) / 1e9 if r.get("offeringAmount") else None
        except ValueError:
            amount = None
        out.append({"date": (r.get("auctionDate") or "")[:10], "term": term, "reopening": r.get("reopening") == "Yes", "amount": amount})
    return sorted(out, key=lambda x: x["date"])


def treasury_upcoming():
    return parse_treasury_upcoming(json.loads(get("https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json")))


def parse_cboe_chain(j):
    """At-the-money implied volatility per expiry from a Cboe delayed-quotes chain: {'spot', 'asof', 'iv30',
    'atm': [(expiry ISO, iv percent)]}. The ATM strike is the one nearest spot with both a call and a put quote."""
    data = j.get("data") or {}
    spot = data.get("current_price")
    if not spot:
        raise SourceError("Cboe chain: no spot")
    by_exp = {}
    for o in data.get("options") or []:
        m = re.match(r"^[A-Z]+(\d{6})([CP])(\d{8})$", o.get("option", ""))
        if not m:
            continue
        iv = o.get("iv")
        if not iv or iv <= 0:
            continue
        if iv > 3:                  # percent rather than a fraction
            iv = iv / 100.0
        exp = "20%s-%s-%s" % (m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:])
        strike = int(m.group(3)) / 1000.0
        by_exp.setdefault(exp, {}).setdefault(strike, {})[m.group(2)] = float(iv)
    atm = []
    for exp in sorted(by_exp):
        pairs = [(abs(k - spot), k, v) for k, v in by_exp[exp].items() if "C" in v and "P" in v]
        if not pairs:
            continue
        _, k, v = min(pairs)
        if abs(k - spot) / spot > 0.02:
            continue
        atm.append((exp, (v["C"] + v["P"]) / 2.0))
    if not atm:
        raise SourceError("Cboe chain: no at-the-money quotes")
    quote_date = (data.get("last_trade_time") or j.get("timestamp") or "")[:10]
    return {"spot": float(spot), "asof": (j.get("timestamp") or "")[:10], "quote_date": quote_date, "iv30": data.get("iv30"), "atm": atm}


def cboe_chain(symbol="_SPX"):
    return parse_cboe_chain(json.loads(get("https://cdn.cboe.com/api/global/delayed_quotes/options/%s.json" % symbol)))

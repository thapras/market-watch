"""What gets fetched. Keys are the short names used throughout render.py."""

# Yahoo daily closes, five years. Key -> symbol.
YAHOO = {
    # indices and broad ETFs
    "spx": "^GSPC", "ndx": "^NDX", "rut": "^RUT", "stoxx": "^STOXX", "n225": "^N225",
    "csi300": "000300.SS", "hsi": "^HSI", "set": "^SET.BK", "spxew": "^SPXEW",
    "spy": "SPY", "rsp": "RSP", "eem": "EEM", "emxc": "EMXC", "vgk": "VGK", "ewj": "EWJ",
    "hyg": "HYG", "ief": "IEF", "tlt": "TLT",
    # commodities (front-month futures)
    "gold": "GC=F", "silver": "SI=F", "plat": "PL=F", "pall": "PA=F", "copper": "HG=F",
    "wti": "CL=F", "brent": "BZ=F", "natgas": "NG=F", "rbob": "RB=F", "heat": "HO=F",
    "wheat": "ZW=F", "corn": "ZC=F", "soy": "ZS=F", "ironore": "TIO=F",
    # crypto, currencies, volatility
    "btc": "BTC-USD", "dxy": "DX-Y.NYB", "usdjpy": "JPY=X", "eurusd": "EURUSD=X",
    "usdcny": "CNY=X", "usdthb": "THB=X", "cew": "CEW",
    "vix": "^VIX", "vix3m": "^VIX3M", "move": "^MOVE",
    # factors
    "iwd": "IWD", "iwf": "IWF", "iwm": "IWM", "sphb": "SPHB", "splv": "SPLV", "mtum": "MTUM", "qual": "QUAL",
    # sectors
    "xlk": "XLK", "xlc": "XLC", "xly": "XLY", "xlp": "XLP", "xlv": "XLV", "xlf": "XLF",
    "xli": "XLI", "xle": "XLE", "xlb": "XLB", "xlu": "XLU", "xlre": "XLRE",
    # themes
    "smh": "SMH", "mags": "MAGS", "gdx": "GDX", "sil": "SIL", "ura": "URA", "xop": "XOP",
    "ita": "ITA", "cibr": "CIBR", "kbe": "KBE", "kre": "KRE", "xhb": "XHB", "xbi": "XBI", "pbj": "PBJ",
    # uranium spot proxy (Sprott Physical Uranium Trust, US dollar line)
    "sruuf": "SRUUF",
}

# FRED series. Key -> series id.
FRED = {
    "m2": "M2SL", "cpi": "CPIAUCSL", "walcl": "WALCL", "tga": "WTREGEN", "rrp": "RRPONTSYD",
    "bankcredit": "TOTBKCR", "reserves": "WRESBAL", "sofr": "SOFR", "iorb": "IORB",
    "ffu": "DFEDTARU", "effr": "EFFR", "gdp": "GDP",
    "dgs2": "DGS2", "dgs10": "DGS10", "dgs3mo": "DGS3MO", "t10y2y": "T10Y2Y", "t10y3m": "T10Y3M",
    "dfii10": "DFII10", "t10yie": "T10YIE", "t5yifr": "T5YIFR", "tp10": "THREEFYTP10",
    "hy": "BAMLH0A0HYM2", "ig": "BAMLC0A0CM", "ccc": "BAMLH0A3HYC", "nfci": "NFCI",
    "mtg": "MORTGAGE30US", "broadusd": "DTWEXBGS", "sahm": "SAHMREALTIME", "claims4": "IC4WSA",
    "ecb_dfr": "ECBDFR", "boj_assets": "JPNASSETS",
    "de10": "IRLTLT01DEM156N", "jp10": "IRLTLT01JPM156N", "uk10": "IRLTLT01GBM156N",
    "de_cpi": "CPALTT01DEM659N", "jp_cpi": "CPALTT01JPM659N", "uk_cpi": "CPALTT01GBM659N",
    # growth pulse and fiscal
    "gdpnow": "GDPNOW", "gdp_actual": "A191RL1Q225SBEA", "cfnai3": "CFNAIMA3", "payrolls": "PAYEMS",
    "deficit": "MTSDS133FMS", "core_cpi": "CPILFESL",
    # v4: first prints for the surprise log (unemployment, hourly earnings, CPI NSA for the y/y, core PCE, retail sales, JOLTS)
    "unrate": "UNRATE", "ahe": "CES0500000003", "cpi_nsa": "CPIAUCNS", "core_pce": "PCEPILFE", "retail": "RSAFS", "jolts": "JTSJOL",
}

# BIS policy rates (WS_CBPOL). Key -> reference area. China's series is the one-year loan prime rate.
BIS = {"boj_rate": "JP", "boe_rate": "GB", "pboc_rate": "CN", "bot_rate": "TH"}

# EIA history tables. Weekly: key -> series id on the dnav petroleum pages. Monthly: key -> page URL.
EIA_WEEKLY = {"crude_stocks": "WCESTUS1", "spr": "WCSSTUS1"}          # thousand barrels
EIA_MONTHLY = {"oil_rigs": "https://www.eia.gov/dnav/ng/hist/e_ertrro_xr0_nus_cM.htm"}   # Baker Hughes count

# Cboe index histories. Key -> index name.
CBOE = {"cor3m": "COR3M"}

# Bank of Japan time-series tables. Key -> (table, series code).
BOJ = {"jp_m2": ("md02_m_1_en", "MD02'MAM1NAM2M2MO")}                 # M2, monthly average, 100 million yen

# ECB data portal. Key -> (flow, series key).
ECB = {
    "ez_m2": ("BSI", "M.U2.Y.V.M20.X.1.U2.2300.Z01.E"),      # euro area M2, EUR millions, monthly
    "ecb_assets": ("ILM", "W.U2.C.T000000.Z5.Z01"),            # Eurosystem total assets, EUR millions, weekly
}

# The twelve-month ranking: row key -> (Yahoo key for the price rules, breadth stand-in).
# Cash has no price score. The breadth rule uses the ratio to SPY where there are no members;
# US large caps use equal-weight against cap-weight (RSP/SPY); the two bond rows skip the rule
# ("skip"), since a bond's ratio to equities measures the equity cycle, not breadth.
RANKING = [
    ("gold_miners", "gdx", "spy"),
    ("em_ex_china", "emxc", "spy"),
    ("us_small", "iwm", "spy"),
    ("banks", "xlf", "spy"),
    ("copper", "copper", "spy"),
    ("gold", "gold", "spy"),
    ("reits", "xlre", "spy"),
    ("japan", "ewj", "spy"),
    ("bitcoin", "btc", "spy"),
    ("silver", "silver", "spy"),
    ("europe", "vgk", "spy"),
    ("thailand", "set", "spy"),
    ("ust10", "ief", "skip"),
    ("us_hy", "hyg", "skip"),
    ("us_large", "spx", None),
    ("semis", "smh", "spy"),
    ("energy", "xle", "spy"),
]

FED_FUNDS_MONTH_CODES = "FGHJKMNQUVXZ"

# Thai gold is quoted per baht-weight of 96.5% fine gold: 15.244 g at 96.5% purity, in troy ounces.
BAHT_WEIGHT_OZ = 15.244 / 31.1035 * 0.965


# ---------------------------------------------------------------- v2: regime and detector
# Yahoo keys fetched with twenty years of daily history (seasonality, backtests, the ranking's seasonal pillar).
LONG = ["spx", "spy", "smh", "mags", "gdx", "sil", "ura", "xop", "ita", "cibr", "kbe", "kre", "xhb", "xbi", "xlp", "xlu", "btc",
        "xlk", "xlc", "xly", "xlv", "xlf", "xli", "xle", "xlb", "xlre", "iwm", "rsp", "tlt", "gold", "silver", "wti", "natgas",
        "copper", "dxy", "emxc", "ewj", "vgk", "set", "ief", "hyg", "sphb", "splv", "mtum", "cew", "vix"]
LONG_SINCE = "2005-01-01"

# Detector themes (section 4 and the themes table). members: where the breadth members come from,
# ("ssga", fund) for a SPDR holdings workbook, None when no free holdings file exists yet (VanEck, Global X,
# iShares, First Trust and Roundhill themes). macro: the driver rule in detector.MACRO_RULES, None when the page names none.
THEMES = [
    {"key": "smh", "name": "Semiconductors", "tk": "SMH", "y": "smh", "members": None, "macro": "liquidity_real"},
    {"key": "mags", "name": "Mega-cap tech and AI", "tk": "MAGS", "y": "mags", "members": None, "macro": "liquidity_real"},
    {"key": "gdx", "name": "Gold miners", "tk": "GDX", "y": "gdx", "members": None, "macro": "gold"},
    {"key": "sil", "name": "Silver miners", "tk": "SIL", "y": "sil", "members": None, "macro": "gold"},
    {"key": "ura", "name": "Uranium", "tk": "URA", "y": "ura", "members": None, "macro": None},
    {"key": "xop", "name": "Oil and gas producers", "tk": "XOP", "y": "xop", "members": ("ssga", "xop"), "macro": "energy"},
    {"key": "ita", "name": "Defense and aerospace", "tk": "ITA", "y": "ita", "members": None, "macro": None},
    {"key": "cibr", "name": "Cybersecurity", "tk": "CIBR", "y": "cibr", "members": None, "macro": None},
    {"key": "kbe", "name": "Banks", "tk": "KBE", "y": "kbe", "members": None, "macro": "curve"},
    {"key": "kre", "name": "Regional banks", "tk": "KRE", "y": "kre", "members": None, "macro": "curve"},
    {"key": "xhb", "name": "Homebuilders", "tk": "XHB", "y": "xhb", "members": ("ssga", "xhb"), "macro": "housing"},
    {"key": "xbi", "name": "Biotech", "tk": "XBI", "y": "xbi", "members": None, "macro": "real_yields"},
    {"key": "staples", "name": "Consumer staples", "tk": "XLP", "y": "xlp", "members": ("ssga", "xlp"), "macro": "defensive"},
    {"key": "xlu", "name": "Utilities", "tk": "XLU", "y": "xlu", "members": ("ssga", "xlu"), "macro": "defensive"},
    {"key": "btc", "name": "Bitcoin", "tk": "BTC", "y": "btc", "members": None, "macro": "liquidity_dollar"},
]

# S&P 500 sectors: key (also the SPDR fund whose holdings file gives the members), name on the page.
SECTORS = [
    ("xlk", "Technology"), ("xlc", "Communication services"), ("xly", "Consumer discretionary"), ("xlp", "Consumer staples"),
    ("xlv", "Health care"), ("xlf", "Financials"), ("xli", "Industrials"), ("xle", "Energy"), ("xlb", "Materials"),
    ("xlu", "Utilities"), ("xlre", "Real estate"),
]

# Holdings workbooks to fetch for breadth: the eleven sector SPDRs, SPY itself, and the SPDR themes.
HOLDINGS = ["spy", "xlk", "xlc", "xly", "xlp", "xlv", "xlf", "xli", "xle", "xlb", "xlu", "xlre", "xhb", "xop"]

# Rotation map: fifteen themes in the page's order. (map key, label on the map, Yahoo key, detector or sector key)
ROTATION_MAP = [
    ("smh", "Semis", "smh"), ("xlk", "Tech", "xlk"), ("xlf", "Financials", "xlf"), ("xli", "Industrials", "xli"),
    ("xlc", "Comm services", "xlc"), ("gdx", "Gold miners", "gdx"), ("xhb", "Homebuilders", "xhb"), ("iwm", "Small caps", "iwm"),
    ("xlb", "Materials", "xlb"), ("xlp", "Staples", "xlp"), ("xlre", "Real estate", "xlre"), ("xlu", "Utilities", "xlu"),
    ("xly", "Discretionary", "xly"), ("xlv", "Health care", "xlv"), ("xop", "Energy", "xop"),
]

# Seasonality table rows: (row name on the page, Yahoo key, relative to SPY?)
SEASONALITY = [
    ("S&P 500", "spx", False), ("Semiconductors", "smh", False), ("Gold", "gold", False), ("Gold miners", "gdx", False),
    ("Silver", "silver", False), ("WTI crude", "wti", False), ("Natural gas", "natgas", False), ("Copper", "copper", False),
    ("Staples vs S&P", "xlp", True), ("Homebuilders", "xhb", False), ("Dollar index", "dxy", False), ("Bitcoin", "btc", False),
]

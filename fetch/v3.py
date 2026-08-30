"""v3 pipeline: positioning and sentiment (section 6) from the free feeds, the crowd flag, the ranking's
P pillar, the divergence alert states and the systematic flows table."""
import datetime as dt

from . import compute as c
from . import conditions as cond
from . import detector as det
from . import positioning as pos
from . import regime as rg

P_MAP = {"gold": "gold", "silver": "silver", "copper": "copper", "energy": "crude", "us_large": "spx", "semis": "semis",
         "ust10": "ust10", "bitcoin": "btc"}
CTA = [("spx", "S&P 500", "spx", False), ("ndx", "Nasdaq 100", "ndx", False), ("ust10", "10Y Treasury note", "dgs10", True),
       ("gold", "Gold", "gold", False), ("wti", "WTI crude", "wti", False), ("dxy", "Dollar index", "dxy", False), ("copper", "Copper", "copper", False)]


def avg10(hist, field):
    """Ten-session average series of a daily put/call field from the logged history."""
    dates = sorted(hist)
    vals = [(d, hist[d][field]) for d in dates if hist[d].get(field) is not None]
    return [(vals[i][0], sum(v for _, v in vals[i - 9:i + 1]) / 10.0) for i in range(9, len(vals))]


def run(D, prev_state, today):
    prev = (prev_state or {}).get("v3", {})
    history = dict((prev_state or {}).get("history", {}))
    # logged series: AAII weekly, FINRA monthly, Cboe daily
    aaii_h = dict(history.get("aaii", {}))
    if "aaii" in D:
        aaii_h[D["aaii"]["date"]] = D["aaii"]["spread"]
    margin_h = dict(history.get("margin", {}))
    for d, v in D.get("finra", []):
        margin_h[d] = v
    pc_h = dict(history.get("pc", {}))
    history["aaii"], history["margin"], history["pc"] = aaii_h, {d: margin_h[d] for d in sorted(margin_h)[-120:]}, {d: pc_h[d] for d in sorted(pc_h)[-900:]}

    # extras as z-scores
    extras, extra_meta = {}, {}
    if "dix" in D:
        s = D["dix"]["dix"]
        extras["dix"] = pos.zlast(s, pos.DAYS_3Y)
        extra_meta["dix"] = {"now": s[-1][1] * 100.0, "pct": c.percentile([v for _, v in s], pos.DAYS_3Y), "date": s[-1][0]}
        g = D["dix"]["gex"]
        extra_meta["gex"] = {"now": g[-1][1], "pct": c.percentile([v for _, v in g], pos.DAYS_3Y), "date": g[-1][0]}
    ipc, epc = avg10(pc_h, "index"), avg10(pc_h, "equity")
    if len(ipc) >= 60:
        extras["index_pc"] = pos.zlast(ipc, pos.DAYS_3Y)
    if ipc:
        extra_meta["index_pc"] = {"now": ipc[-1][1], "pct": c.percentile([v for _, v in ipc], pos.DAYS_3Y) if len(ipc) >= 60 else None, "date": ipc[-1][0], "n": len(ipc)}
    if len(epc) >= 60:
        extras["equity_pc"] = pos.zlast([(d, -v) for d, v in epc], pos.DAYS_3Y)
    if epc:
        extra_meta["equity_pc"] = {"now": epc[-1][1], "pct": c.percentile([v for _, v in epc], pos.DAYS_3Y) if len(epc) >= 60 else None, "date": epc[-1][0], "n": len(epc)}
    aaii_s = sorted(aaii_h.items())
    if len(aaii_s) >= 26:
        extras["aaii"] = pos.zlast(aaii_s, pos.WEEKS_3Y)
    if "aaii" in D:
        extra_meta["aaii"] = {"now": D["aaii"]["spread"], "bull": D["aaii"]["bull"], "bear": D["aaii"]["bear"], "date": D["aaii"]["date"],
                              "pct": c.percentile([v for _, v in aaii_s], pos.WEEKS_3Y) if len(aaii_s) >= 26 else None, "n": len(aaii_s)}
    margin_s = sorted(margin_h.items())
    if len(margin_s) >= 12:
        extras["margin"] = pos.zlast(margin_s, 36)
        yoy = None
        prev_year = dict(margin_s).get("%d%s" % (int(margin_s[-1][0][:4]) - 1, margin_s[-1][0][4:]))
        if prev_year:
            yoy = (margin_s[-1][1] / prev_year - 1.0) * 100.0
        extra_meta["margin"] = {"now": margin_s[-1][1], "pct": c.percentile([v for _, v in margin_s], 36), "date": margin_s[-1][0], "n": len(margin_s), "yoy": yoy}
    if "crypto_fng" in D:
        s = D["crypto_fng"]
        extras["crypto_fng"] = pos.zlast(s, pos.DAYS_3Y)
        extra_meta["crypto_fng"] = {"now": s[-1][1], "pct": c.percentile([v for _, v in s], pos.DAYS_3Y), "date": s[-1][0]}

    # COT
    cots = {}
    for key in pos.COT_MARKETS:
        rows = D.get("cot_" + key)
        if rows:
            cots[key] = pos.cot_series(key, rows)
    cot_date = max((v["crowd"][-1][0] for v in cots.values() if v["crowd"]), default=None)

    markets, alerts = {}, {}
    for key, name, cot_key, price_key, extra_sm, extra_cr in pos.DIV_MARKETS:
        cot = cots.get(cot_key)
        sc = pos.market_scores(key, cot, extra_sm, extra_cr, extras)
        daily = []
        if "dix" in extra_sm and "dix" in D:
            daily.append((D["dix"]["dix"], "sm"))
        if "crypto_fng" in extra_cr and "crypto_fng" in D:
            daily.append((D["crypto_fng"], "cr"))
        weekly = pos.weekly_divergence(cot, daily) if cot else []
        state = pos.alert_state(weekly)
        price = D[price_key]["adj"] if price_key in D and D[price_key].get("adj") else (D.get(price_key) if isinstance(D.get(price_key), list) else None)
        bt = pos.before(weekly, price) if weekly else {"n": 0}
        h_pct = pos.cot_index(cot["hedgers"]) if cot else None
        c_pct = pos.cot_index(cot["crowd"]) if cot else None
        markets[key] = {"name": name, "cot_key": cot_key, "sm": sc["sm"], "cr": sc["cr"], "div": sc["div"], "sm_parts": sc["sm_parts"], "cr_parts": sc["cr_parts"],
                        "state": state, "before": bt, "weekly_n": len(weekly), "weekly_last": weekly[-1] if weekly else None,
                        "hedgers_net": cot["hedgers"][-1][1] if cot and cot["hedgers"] else None, "hedgers_pct": h_pct,
                        "crowd_net": cot["crowd"][-1][1] if cot and cot["crowd"] else None, "crowd_pct": c_pct, "mode": cot["mode"] if cot else None,
                        "date": cot["crowd"][-1][0] if cot and cot["crowd"] else None}
        alerts[key] = state
    crowd_z = markets["spx"]["cr"] if "spx" in markets else None
    crowd = {"z": crowd_z, "word": pos.crowd_word(crowd_z)}

    # systematic flows
    cta = {}
    for key, name, ykey, is_yield in CTA:
        s = D[ykey] if is_yield else (D[ykey]["close"] if ykey in D else None)
        if not s:
            continue
        sig = pos.cta_signal(s)
        if not sig:
            continue
        if is_yield:
            sig = dict(sig, signal=-sig["signal"], flip_pct=None)          # rising yields is short bonds
        cta[key] = dict(sig, name=name, is_yield=is_yield, last=s[-1][1], date=s[-1][0])
    flows = {}
    if "spx" in D:
        flows["volctl"] = pos.vol_control(D["spx"]["close"])
    if "spy" in D and "tlt" in D:
        flows["rp"] = pos.risk_parity(D["spy"]["adj"], D["tlt"]["adj"])
        flows["pension"] = pos.pension_rebalance(D["spy"]["adj"], D["tlt"]["adj"], today)
    if "gex" in extra_meta:
        flows["gamma"] = extra_meta["gex"]

    p_pillar = {}
    for rk, mk in P_MAP.items():
        d = (markets.get(mk) or {}).get("div")
        p_pillar[rk] = cond.half(d) if d is not None else None

    state = {"alerts": alerts, "crowd": crowd["word"], "cta": {k: v["signal"] for k, v in cta.items()}, "cot_date": cot_date}
    return {"markets": markets, "extras": extra_meta, "crowd": crowd, "cta": cta, "flows": flows, "p_pillar": p_pillar,
            "state": state, "history": history, "cot_date": cot_date, "prev": prev}

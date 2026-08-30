"""The Sunday brief: print the week's inputs, or write the skeleton the reviewed columns go into.

    python3 -m fetch.brief            # the week ahead from data/latest.json and data/state.json, as markdown
    python3 -m fetch.brief --write    # writes data/briefs.json with the rule-based columns as the starting draft
                                      # (existing reviewed entries are kept)

The page merges data/briefs.json on the next fetch: an event whose entry has text in expect, stronger or
weaker shows those columns tagged with the reviewed date; the week paragraph replaces the rule-based read
while its from and to dates cover the current week. Rows without an entry keep the rule-based columns and
say so. Voice: calm, direct, conditionals only, no predictions.
"""
import argparse
import datetime as dt
import json
import os
import sys

from . import changes as ch


def load(data_dir):
    latest = ch.load(os.path.join(data_dir, "latest.json")) or {}
    state = ch.load(os.path.join(data_dir, "state.json")) or {}
    briefs = ch.load(os.path.join(data_dir, "briefs.json")) or {}
    return latest, state, briefs


def week_rows(cal):
    return [r for r in cal.get("rows", []) if r.get("range") == "week"]


def print_brief(latest, state, briefs, out=sys.stdout):
    cal = (latest.get("v2") or {}).get("calendar")
    if not cal:
        print("No calendar block in data/latest.json: run the fetcher first.", file=out)
        return 1
    lo, hi = cal["ranges"]["week"]
    p = lambda *a: print(*a, file=out)          # noqa: E731
    p("# Week ahead, %s to %s (data as of %s)" % (lo, hi, latest.get("asOfLabel", "")))
    p("")
    p("Current read (%s): %s" % (cal["read"]["src"], cal["read"]["text"]))
    p("")
    v3 = state.get("v3") or {}
    if v3.get("alerts"):
        active = [k for k, s in v3["alerts"].items() if s]
        p("Positioning alerts active: %s. Crowd: %s. CTA signals: %s." % (", ".join(active) or "none", v3.get("crowd", ""), ", ".join("%s %s" % (k, "long" if s == 1 else "short") for k, s in (v3.get("cta") or {}).items())))
    det = state.get("detector") or {}
    hot = [(k, v["state"]) for k, v in det.items() if v.get("state") not in (None, "none")]
    if hot:
        p("Detector states: %s." % ", ".join("%s %s" % (k, s) for k, s in hot))
    reg = (latest.get("v2") or {}).get("regime") or {}
    if reg.get("line"):
        p("Regime line: %s" % reg["line"])
    p("")
    for r in week_rows(cal):
        b = r["brief"]
        p("## %s, %s: %s (tier %s)" % (r["day"], r["time"] or "no clock time", r["name"], r["tier"] or "closed"))
        if r.get("cons"):
            p("- Consensus and pricing: %s" % r["cons"])
        if r.get("touches"):
            p("- %s" % r["touches"])
        p("- Source: %s%s" % (r["src"], "" if r["confirmed"] else " (usual slot, not confirmed)"))
        p("- Columns now (%s):" % b["src"])
        p("  - Expect: %s" % b["expect"])
        if b.get("stronger"):
            p("  - Stronger: %s" % b["stronger"])
        if b.get("weaker"):
            p("  - Weaker: %s" % b["weaker"])
        p("- id: `%s`" % r["id"])
        p("")
    if cal.get("studies"):
        p("## Event studies (unconditional, since 2011)")
        for s in cal["studies"]:
            c = s["cells"]
            p("- %s (n=%d): S&P median %s, worst tenth %s, up %s; 10Y %s; dollar %s; gold %s. Next %s: %s." % (
                s["name"], s["n"], c.get("spx", {}).get("med", ""), c.get("spx", {}).get("p90", ""), c.get("spx", {}).get("up", ""),
                c.get("dgs10", {}).get("med", ""), c.get("dxy", {}).get("med", ""), c.get("gold", {}).get("med", ""),
                (s.get("next") or {}).get("date", ""), (s.get("next") or {}).get("implied", "")))
        p("")
    p("Normal session, options-implied: %s (chain as of %s)." % (cal.get("implied", {}).get("base") or "n/a", cal.get("implied", {}).get("asof") or "n/a"))
    p("")
    p("Write the reviewed columns into data/briefs.json (python3 -m fetch.brief --write creates the skeleton), then run the fetcher.")
    return 0


def write_skeleton(latest, briefs, path, today):
    cal = (latest.get("v2") or {}).get("calendar")
    if not cal:
        print("No calendar block in data/latest.json: run the fetcher first.", file=sys.stderr)
        return 1
    lo, hi = cal["ranges"]["week"]
    out = {"week": dict(briefs.get("week") or {}), "events": dict(briefs.get("events") or {})}
    if not out["week"] or out["week"].get("to", "") < lo:
        out["week"] = {"from": lo, "to": hi, "text": "", "reviewed": None}
    for r in week_rows(cal):
        if r["id"] in out["events"] or r.get("dim"):
            continue
        b = r["brief"]
        out["events"][r["id"]] = {"name": r["name"], "day": r["day"], "expect": b["expect"], "stronger": b.get("stronger", ""), "weaker": b.get("weaker", ""), "reviewed": None}
    # drop entries older than the week (the log keeps what matters)
    out["events"] = {k: v for k, v in out["events"].items() if k.split(":")[-1] >= lo}
    ch.save(path, out)
    print("wrote %s: %d event(s) for %s to %s; set reviewed to today's date on the entries you have checked" % (path, len(out["events"]), lo, hi))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("MW_DATA", "data"))
    ap.add_argument("--write", action="store_true", help="write the skeleton to data/briefs.json")
    args = ap.parse_args(argv)
    latest, state, briefs = load(args.data)
    if args.write:
        return write_skeleton(latest, briefs, os.path.join(args.data, "briefs.json"), dt.date.today().isoformat())
    return print_brief(latest, state, briefs)


if __name__ == "__main__":
    sys.exit(main())

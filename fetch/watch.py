"""The watchlist: snapshot a ranked market as it stands, and grade it from then on.

    python3 -m fetch.watch                        # print the list, with grades if the fetcher has run
    python3 -m fetch.watch add gold --note "..."  # snapshot gold's current row from data/latest.json
    python3 -m fetch.watch close gold --note "..."# close the open gold snapshot (kept, grade frozen)

data/watchlist.json is written by this command only (directly, through /watch in a working session,
or by the watch issue workflow, which runs it). The fetcher reads the file and writes the graded
rows into data/latest.json; it never adds, edits or removes entries. Snapshots grade the page's
reads against what happened next; they are not positions, advice or price targets.
"""
import argparse
import os
import sys

from . import changes as ch
from .catalog import RANKING

WL_KEYS = [k for k, _, _ in RANKING]


def load(data_dir):
    latest = ch.load(os.path.join(data_dir, "latest.json")) or {}
    watch = ch.load(os.path.join(data_dir, "watchlist.json")) or {"open": [], "closed": []}
    watch.setdefault("open", [])
    watch.setdefault("closed", [])
    return latest, watch


def snapshot(rank_entry):
    """The attributes frozen with a snapshot: both scores, the read, the tags, every pillar and rule."""
    rk = rank_entry or {}
    pillars = {p: (v or {}).get("v") for p, v in (rk.get("pillars") or {}).items()}
    return {"cond": rk.get("cond"), "price": rk.get("price"), "read": rk.get("read"),
            "tags": rk.get("tags"), "rules": rk.get("rules"), "pillars": pillars}


def add(latest, watch, key, note):
    """Append an open snapshot of key to watch. Returns a message; raises ValueError when refused."""
    key = (key or "").strip().lower()
    if key not in WL_KEYS:
        raise ValueError("%r is not a snapshotable market. Valid keys: %s. Cash has no price series to grade."
                         % (key, ", ".join(WL_KEYS)))
    rank = (latest or {}).get("rank") or {}
    if key not in rank:
        raise ValueError("data/latest.json has no ranking row for %r yet: run the fetcher first." % key)
    for e in watch["open"]:
        if e["key"] == key:
            raise ValueError("%s is already on the watchlist (snapshot %s). Close it before snapshotting again." % (key, e["date"]))
    date = ((latest.get("asOf") or "")[:10]) or None
    if not date:
        raise ValueError("data/latest.json carries no asOf date: run the fetcher first.")
    entry = {"id": "%s:%s" % (key, date), "key": key, "date": date,
             "note": (note or "").strip(), "then": snapshot(rank[key])}
    watch["open"].append(entry)
    t = entry["then"]
    scores = "conditions %s, price %s, read %s" % (t.get("cond"), t.get("price"), t.get("read") or "none")
    return "snapshotted %s at %s (%s). Grades appear after the next data run." % (key, date, scores)


def close(latest, watch, key, note):
    """Close the open snapshot for key. Returns a message; raises ValueError when there is none."""
    key = (key or "").strip().lower()
    for i, e in enumerate(watch["open"]):
        if e["key"] == key:
            date = ((latest or {}).get("asOf") or "")[:10] or e["date"]
            e["closed"], e["close_note"] = date, (note or "").strip()
            watch["closed"].append(watch["open"].pop(i))
            return "closed the %s snapshot from %s at %s. It keeps its grade over that span." % (key, e["date"], date)
    raise ValueError("no open snapshot for %r. Open: %s." % (key, ", ".join(e["key"] for e in watch["open"]) or "none"))


def show(latest, watch, out=sys.stdout):
    rows = {r["id"]: r for r in (((latest.get("v2") or {}).get("watchlist") or {}).get("rows") or [])}
    p = lambda *a: print(*a, file=out)          # noqa: E731
    if not watch["open"] and not watch["closed"]:
        p("The watchlist is empty. Add: python3 -m fetch.watch add <key>. Keys: %s." % ", ".join(WL_KEYS))
        return
    for e in watch["open"]:
        g = rows.get(e["id"]) or {}
        t = e.get("then") or {}
        line = "%s  snapshot %s  then C %s P %s %s" % (e["key"], e["date"], t.get("cond"), t.get("price"), t.get("read") or "")
        if g.get("verdict"):
            line += "  |  now C %s P %s, %s vs S&P 500 over %s sessions: %s" % (
                (g.get("now") or {}).get("cond"), (g.get("now") or {}).get("price"),
                ("%+.1f%%" % (g["rel"] * 100.0)) if g.get("rel") is not None else "n/a",
                g.get("sessions"), g["verdict"])
        else:
            line += "  |  not graded yet (run the fetcher)"
        p(line)
        if e.get("note"):
            p("    note: %s" % e["note"])
    for e in watch["closed"]:
        p("%s  closed %s (snapshot %s)%s" % (e["key"], e.get("closed"), e["date"],
                                             ": " + e["close_note"] if e.get("close_note") else ""))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=["add", "close", "list"], default="list")
    ap.add_argument("key", nargs="?")
    ap.add_argument("--note", default="")
    ap.add_argument("--data", default=os.environ.get("MW_DATA", "data"))
    args = ap.parse_args(argv)
    latest, watch = load(args.data)
    if args.action == "list":
        show(latest, watch)
        return 0
    if not args.key:
        print("which market? valid keys: %s" % ", ".join(WL_KEYS), file=sys.stderr)
        return 2
    try:
        msg = add(latest, watch, args.key, args.note) if args.action == "add" else close(latest, watch, args.key, args.note)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    ch.save(os.path.join(args.data, "watchlist.json"), watch)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())

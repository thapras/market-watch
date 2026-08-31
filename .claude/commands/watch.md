---
description: Snapshot a ranked market to the watchlist, close one, or review the grades
---

# /watch: the watchlist

A snapshot freezes a market's ranking row as it stands (both scores, the read, the tags, every
pillar and rule) in `data/watchlist.json`. The nightly fetcher grades every snapshot against the
S&P 500 from that day on and writes the graded rows into `data/latest.json` for the panel under
the ranking. The point is evidence: do the page's reads lead performance or not.

## Actions

- **Add** (`/watch add <key> [note]`): run `python3 -m fetch.watch add <key> --note "<note>"`.
  Valid keys are the ranking rows (`python3 -m fetch.watch` lists them on error); cash is not
  snapshotable (no price series). Show Ham the stored entry, then commit `data/watchlist.json`
  with a message like `watch: add gold` and push.
- **Close** (`/watch close <key> [note]`): run `python3 -m fetch.watch close <key> --note "..."`.
  The entry keeps its grade over snapshot to close and moves to the closed fold. Commit as
  `watch: close gold` and push.
- **Review** (`/watch` alone): run `python3 -m fetch.watch` and read the grades back with a short,
  calm summary: what is working, what is stalled, whether any read looks wrong ahead of threshold
  tuning. No trades, no targets.

The page's + saves a snapshot on the reader's device only (localStorage, graded in the browser);
`/watch add`, the CLI, or a saved row's sync link is what writes the repo log the nightly run grades.

## Guardrails

- `data/watchlist.json` is written by `fetch.watch` only (here or through the watch issue
  workflow). Never hand-edit it, never generate entries from rules, never snapshot on a schedule:
  a snapshot is Ham's deliberate call, that is what makes the log meaningful.
- Grades appear after the next data run. To see them today, run
  `MW_CACHE=.cache python3 -m fetch.fetch` before reading the list, and commit the refreshed
  `data/latest.json` together with the watchlist.
- The grade thresholds (21 sessions, the 0.5 conditions band, the S&P 500 benchmark) follow the
  page's stated rules; they stay fixed until three months of grades exist, then tune from the log.

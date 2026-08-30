---
description: Sunday brief for section 5 (the week-ahead paragraph and the Expect / Stronger / Weaker columns), reviewed before it goes on the page
---

# /brief: the Sunday brief for the calendar

Twenty minutes, once a week, Sunday evening Bangkok time. The page already carries rule-based columns for every
event (consensus, the event study, the options-implied move, positioning); this session replaces them with a
reviewed brief for the week ahead.

## Steps

1. Refresh the inputs if the data file is older than today: `MW_CACHE=.cache python3 -m fetch.fetch`.
2. Print the week's inputs: `python3 -m fetch.brief`. Read it whole before drafting: the regime line, the
   positioning alerts, the detector states, then each event with its consensus, prior, implied move and the
   unconditional event study.
3. Write the skeleton: `python3 -m fetch.brief --write` creates or extends `data/briefs.json` with one entry
   per event of the week (rule-based text as the starting point) and a `week` entry.
4. Draft, in the file, per event:
   - **Expect**: what the print decides on this page (which chip, which alert, which read), the consensus and
     the bar for a big reaction (the implied move against the event study). One to three sentences.
   - **Stronger** and **Weaker**: what moves, which page rows it touches, in the page's own terms (rate-cut
     trade, steepener, carry, the detector states). Conditionals only, no predictions, no price targets.
   - The **week** paragraph: the theme of the week in two to four sentences, the decider, what is closed.
   Voice: calm, direct, no hype. No em dashes, en dashes, connector hyphens or middots; no ellipsis.
   Keep every entry under about forty words per column so the row does not sprawl.
5. Show Ham the full draft as a table (event, Expect, Stronger, Weaker) plus the week paragraph, and wait
   for the review. Apply the edits.
6. Set `reviewed` to today's date (ISO) on every entry Ham approved, and on `week`. Leave `reviewed` null on
   anything not approved: the page shows it as a draft.
7. Run the fetcher again so `data/latest.json` carries the brief, then open the page over http and check the
   rows read cleanly (no wrapped label cut off, no ellipsis).
8. Commit `data/briefs.json` and `data/latest.json` together with a message like `brief: week of 31 Aug`.

## Guardrails

- The brief interprets the page's own numbers; it does not import an outside view, a forecast, or a target.
- Only events already on the calendar get an entry. To add an event type, change the tier table in
  `fetch/calendar.py` and the tier text on the page together.
- If a consensus figure on the page looks wrong, fix the feed mapping, not the brief.

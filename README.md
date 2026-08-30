# Market Watch

A personal global-markets monitor: is money supply growing, what does it cost, where is it sitting, where is it starting to move, what could move it next, and how smart money is positioned against the crowd. One static page, six questions in reading order, a twelve-month conditions ranking, a ten-week event calendar with a reviewed weekly brief, and a build plan at the bottom of the page.

Live page: **https://thapras.github.io/market-watch/** from the repo **https://github.com/thapras/market-watch**, rebuilt by the nightly Action at 05:30 Bangkok.

## How it runs

- `index.html` is the whole page. It reads `data/latest.json` and fills every bound element (the regime strip, the liquidity and rates tiles, the market tables, the price side of the ranking). Anything the file does not cover keeps its placeholder and is tagged **sample**; a reading older than its refresh interval is greyed and dated.
- `fetch/` is the nightly script, standard library only, no API keys:
  - `sources.py` pulls FRED (fredgraph CSV), Yahoo Finance (chart endpoint), the ECB data portal, BIS policy rates (SDMX CSV), EIA history tables (weekly petroleum stocks, monthly rig count), Cboe index histories (COR3M), Treasury FiscalData (bills share of marketable debt), the Bank of Japan time-series tables (M2), multpl (S&P 500 trailing P/E), the ICI weekly money market release and the Cleveland Fed inflation nowcast file. Each parser is a pure function with a unit test on a trimmed copy of the real page, so a layout change fails the test before it fails the page.
  - `compute.py` holds the transforms and the five price rules behind the ranking. Thresholds stay fixed until three months of alert logs exist.
  - `regime.py` builds the four composites (liquidity impulse, growth momentum, inflation momentum, risk appetite) from three-year z-scores, the cycle quadrant and the regime flags.
  - `detector.py` scores every theme on the five conditions (relative strength on vol-adjusted returns, flows, breadth thrust from holdings files, the eight-week seasonal window over twenty years, macro confirmation), runs the backtests, places the rotation map and builds the seasonality table. `conditions.py` is the ranking's seven-pillar conditions score. `v2.py` runs them and keeps the run-to-run state.
  - `positioning.py` and `v3.py` are section 6: smart money against the crowd per market from CFTC positioning (legacy commercials and non-commercials, TFF asset managers and leveraged funds through the Socrata API), DIX and gamma exposure, Cboe put/call ratios, the AAII survey, FINRA margin debt and the crypto fear and greed index; divergence alerts need two consecutive weekly readings beyond 1.5; plus the systematic flows replication (CTA trend signals with flip levels, vol-control allocation, risk parity leverage, pension rebalancing).
  - `calendar.py`, `events.py` and `v4.py` are section 5: the event list for the next ten weeks (Forex Factory's public JSON for the current week's times and consensus, the Fed, ECB and Bank of Japan meeting pages, the BLS release archives for payrolls and CPI, TreasuryDirect's announced auctions, and rules for the usual slots and the mechanical dates: ISM, the QRA, quarter end, tax dates, quad witching, the Fed blackout and minutes), filtered by the tier table printed on the page; event studies per release since 2011; the options-implied move per event session from the Cboe SPX chain (the variance between consecutive daily expiries is one session's); the surprise log (consensus logged before each release, the first print read from FRED after it, standardized) and the in-house US surprise index. `brief.py` prints the Sunday inputs and writes the skeleton of `data/briefs.json`, the reviewed brief the page merges over the rule-based columns.
  - `changes.py` diffs states between runs into `data/changes.json` (the What changed strip), adds the calendar entries (tier-1 events inside five days as notable, tier-2 as FYI, a tier-1 surprise beyond one sigma as a must-read), and `notify.py` sends must-reads (ntfy, Telegram or email, whichever secrets exist).
  - `render.py` turns series and states into the display strings, chips, cards and sparklines the page binds to.
  - `fetch.py` is the entry point; it writes `data/latest.json`, `data/state.json` and `data/changes.json`, and carries forward the last good value, marked stale, for any feed that fails.
- `.github/workflows/fetch.yml` runs it at 05:30 Bangkok, sends the digest when a must-read exists and a channel secret is set (`NTFY_TOPIC`, or `TELEGRAM_BOT_TOKEN` plus `TELEGRAM_CHAT_ID`, or `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`), and commits the three data files. With GitHub Pages serving the `main` branch, the page updates on its own.

## Run it locally

```
python3 -m unittest fetch.test_compute fetch.test_v2 fetch.test_v4   # the rules, the parsers, the detector, regime and calendar logic
MW_CACHE=.cache python3 -m fetch.fetch          # writes data/latest.json, caches responses for 12 hours
python3 -m http.server 8765 --bind 127.0.0.1    # then open http://127.0.0.1:8765/
python3 -m fetch.brief                          # Sunday: the week's inputs; --write creates the data/briefs.json skeleton
```

The Sunday brief (`/brief` in a Claude session started in this folder) takes about twenty minutes: read the inputs, draft the Expect, Stronger and Weaker columns per event and the week paragraph in `data/briefs.json`, review, set `reviewed` to the date, run the fetcher, commit. Rows without a reviewed entry show the rule-based columns (consensus and prior, the event study, the options bar, positioning) and say so.

Open the page over http, not `file://`, or the browser will refuse to load the data file and every figure stays a placeholder.

## Data contract (`data/latest.json`)

- `asOf`, `asOfLabel`: when the script ran, Bangkok time.
- `cells`: keyed by the `data-tile`, `data-strip` and `data-cell` attributes in the page. Tiles carry `val` (HTML), `delta`, `spark`, `unit`; strip items carry `val` and `d`; table cells carry `t` (text) and `s` (sign), optionally `h` (markup, used for the stance chips) and `v` (a number that also drives a bar, used for fund flows). Every entry carries `src`, `dl` (date label), `date` (ISO) and `freq` (`d` daily, `w` weekly, `m` monthly, `q` quarterly), which the page uses to grey out readings older than their refresh interval.
- `meta`: provenance per table row prefix (for example `sc.spx`).
- `rank`: the price score, the five rule scores, tags and 12-1 momentum per ranking row.
- `v2`: the regime read (line, flags, composites, clock trail), the rotation block (read, alert cards, map positions, seasonality cells), the positioning block (read, divergence dots), and the calendar block (`rows` with day, time, name, consensus line, touches, tier, the three brief columns and their source, the tab range; `studies`; the week-ahead `read`; the implied-move baseline; which feeds answered); the ranking's conditions score, pillars and read ride on `rank`; section 6 tables are ordinary `cells` under `pos.`, `div.`, `cta.` and `flow2.`; the surprise index and the calendar effects dates are `cells` under `gp.surprise` and `ce.`.
- `errors`, `counts`: what failed and how much was carried forward.

`data/state.json` is the run-to-run memory: detector states with the date they were entered and the raw state count behind the three-close rule, regime flags, sector quadrants, ranking reads, the score history for the week-on-week change, the money market series, the logged put/call, AAII and margin debt series (the page's three-year percentiles for those grow as the log does), the divergence alert states, the FOMC meeting dates by year (the historical pages are read once), the surprise log (`history.surprises`, per series and release date: forecast, prior, actual, reference period, standardized surprise), the calendar state (tier-1 and tier-2 events inside five days, surprises resolved on the run), and when the last digest went out. `data/briefs.json` is hand-written (through `/brief`) and only read by the fetcher. `data/changes.json` is the ninety-day state-change log the page shows against your last read: `{t, d, tier, sec, href, text, key}` per entry, tiers `must`, `note`, `fyi`, one entry per subject per week. Alerts fire on state changes only; the first run logs nothing but the start.

## What is still a placeholder, and why

Global M2 is shown as the US, euro area and Japan in dollars: China's M2 has no free monthly feed (the NBS API blocks non-browser clients and its DBnomics mirror runs months behind). Also without a free feed: the PBoC balance sheet, PMIs and the ISM, Korea's 20-day exports, the Baltic Dry Index, gold ETF and central bank holdings, LME stocks and spreads, OPEC spare capacity, the EUR/USD basis, forward P/E and revisions, and fund flows beyond money market funds. The surprise index is in-house and US only (Forex Factory's feed carries consensus but no actuals, and FRED carries the US first prints; the euro area and China have no free pair). On the calendar, earnings dates have no keyless feed (Yahoo's calendar needs a session crumb) and are not listed; Finnhub and FMP need API keys. The event study is unconditional until the consensus log holds 24 releases.

Free data only, no backend, no database. Scope guard: a regime and rotation monitor, no trade execution, no single-stock analysis, no price targets.

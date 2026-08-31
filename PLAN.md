# Market Watch build plan

> Cut from the production page on 31 Aug 2026 (the page keeps the six questions only). This is the plan as
> it stood on the page, lightly converted to markdown; the original markup is in git history (index.html
> up to commit 5d78534). Estimates below predate the build: v1 to v4.1 actually shipped 30 Aug 2026.

# How this gets built, right-sized

Static page, one nightly script, free data only, no backend and no database. Each phase is useful on its own; v1 alone replaces the placeholders with live numbers. About thirteen to seventeen weekends in total at eight to ten hours a week.

**Recommendation:**Build v1 next. Live numbers in the regime strip, the scorecard, liquidity, rates and markets are what make the weekly routine real, and they now cover most of what a professional desk reads each morning; the detector, regime and positioning layers are only worth tuning against data you have been reading for a few weeks.

## Phases

- **v0** (today): **This page.** Layout, the six questions, the detection logic, the calendar template and the sentiment method, all with placeholder numbers.

- **v1** (4 to 5 weekends): **Live numbers.** A Python script (FRED API, yfinance, CFTC and EIA CSVs, NY Fed, CBOE) runs nightly on GitHub Actions and writes data/latest.json; the page reads it and fills the tiles and tables. The scorecard, z-scores, factor spreads, ratios, currencies, term premium, NFCI and the VIX term structure come from the same feeds, so most of what a desk reads daily is live from v1. The price rules behind the ranking (200-day trend, 12-1 momentum, 50/200 state, 52-week high, breadth, breakout tags) are simple transforms of the same closes, so the price-confirmation score is live from v1 too, at the cost of about one extra weekend. Hosted as a static site on a private URL.

- **v2** (4.5 to 5.5 weekends): **Rotation detector and regime.** Vol-adjusted relative strength, ETF flows from share counts, breadth from holdings files, de-trended seasonality from twenty years of daily closes, the four composites and the cycle clock, the conditions score of the ranking with its weekly change, the CTA and vol-control replication, the growth pulse and the FactSet valuation pull. Scores, states, backtest statistics and the alert log. Every state change is appended to data/changes.json (ninety days, which is also the tuning log); the page shows what changed since your last read, with a count per section in the bar. The morning digest, Bangkok time, goes out only when there is a must-read, and must-reads also push over a Telegram bot or ntfy from the same Action: about half a weekend plus an hour for the channel.

- **v3** (2 to 3 weekends): **Sentiment and positioning.** COT index and TFF report from the CFTC, AAII, NAAIM, Investors Intelligence and BofA headlines, put/call by participant, margin debt, search interest, dealer gamma from open interest, the divergence score and its alerts. Refreshes Friday nights.

- **v4** (2 to 3 weekends): **Calendar, event studies and briefs.** Nightly pull of the release calendar filtered to tiers 1 and 2 (Forex Factory for the week, the central bank pages, the BLS lists, TreasuryDirect, rules for the usual slots), the in-house surprise index from logged consensus against FRED first prints, event studies per release since 2011, options-implied moves per session from the SPX chain; rule-based expectation columns on every row, replaced by the Sunday brief (drafted in a Claude session from consensus, positioning and the event study, reviewed before it is saved).

## Data sources and refresh

| Panel | Series | Free source | Refresh | Phase |
|---|---|---|---|---|
| Liquidity | M2, Fed balance sheet, TGA, RRP, bank credit | FRED API | Weekly | v1 |
| Liquidity | Euro area and Japan M2 (China M2 has no free monthly feed; China TSF open) | ECB data portal, BoJ time series | Monthly | v1 |
| Rates | Treasury yields, TIPS, breakevens, spreads, mortgage | FRED API | Daily | v1 |
| Rates | Implied cuts | Fed funds futures via the Yahoo chart endpoint | Daily | v1 |
| Markets | Indices, sector and theme ETFs, futures, FX, bitcoin | Yahoo chart endpoint | Daily | v1 |
| Markets | Money market fund assets (weekly change as the flow proxy); other fund flows open | ICI weekly release | Weekly | v1 |
| Markets | Crude and SPR stocks, oil rig count (monthly); OPEC spare capacity open | EIA history tables (weekly report, Baker Hughes count) | Weekly | v1 |
| Rotation | Holdings files for breadth (SPDR funds), twenty years of closes for seasonality and backtests; ETF share counts for flows still open | SSGA holdings workbooks, Yahoo chart endpoint | Daily | v2 |
| Sentiment | Hedger and speculator positioning, nine markets | CFTC Socrata API (legacy and TFF) | Weekly, Fri | v3 |
| Sentiment | AAII survey, Cboe put/call, FINRA margin debt, DIX and GEX, crypto fear and greed live; search, insiders and NAAIM have no free feed | AAII page, Cboe daily JSON, FINRA, SqueezeMetrics, alternative.me | Weekly | v3 |
| Calendar | Releases, consensus, meeting dates, auctions, implied moves; earnings dates have no keyless feed | Forex Factory JSON, Fed, ECB and BoJ pages, BLS archives, TreasuryDirect, Cboe SPX chain | Nightly | v4 |
| Liquidity | Bank reserves, SOFR, IORB, bills share, fiscal impulse | FRED (WRESBAL, SOFR, IORB, MTSDS133FMS), Treasury FiscalData (Monthly Statement of the Public Debt) | Daily, monthly | v1 |
| Rates | Term premium, 3m10y, 5y5y, NFCI, CCC spread | FRED (THREEFYTP10 Kim-Wright, T10Y3M, T5YIFR, NFCI, BAMLH0A3HYC) | Daily, weekly | v1 |
| Volatility | VIX term structure, implied correlation, MOVE | Yahoo (VIX, VIX3M, MOVE), Cboe history CSV (COR3M) | Daily | v1 |
| Markets | Scorecard, factor ETFs, ratios, currencies, global yields | Yahoo chart endpoint, FRED, BIS policy rates | Daily | v1 |
| Ranking | Price rules: 200-day, 12-1 momentum, 50/200, 52-week high, breadth, breakout tags | yfinance closes, issuer holdings files | Daily | v1 |
| Notifications | State-change log, per-section unread counts, digest, push | GitHub Actions cron, Gmail SMTP app password, Telegram bot or ntfy.sh (all free) | Nightly, must-read only | v2 |
| Growth pulse | Nowcasts, claims, Sahm, CFNAI, payrolls live; the US surprise index is in-house from v4; PMIs, Korea exports and Baltic Dry have no free feed | FRED, Cleveland Fed nowcast file, the consensus log | Weekly | v1 |
| Valuation | Trailing P/E and equity risk premium live; forward P/E, revisions and expected growth need FactSet | multpl, FRED | Monthly | v1 |
| Systematic flows | CTA trend, vol-control, risk parity, pension rebalancing and dealer gamma live; buybacks and 0DTE share open | Own replication on the closes, SqueezeMetrics GEX | Daily | v3 |
| Sentiment | TFF asset managers and leveraged funds live; NAAIM, Investors Intelligence and BofA have no free feed | CFTC Socrata API | Weekly | v3 |

**Paid data deliberately skipped:**EPFR fund flows (share-count proxy instead), Bloomberg terminal series (FRED and yfinance cover the rest), SpotGamma (dealer gamma read from public option open interest is good enough for a flag).

## The quant standard applied here

What separates a dashboard from a screen full of prices. Each rule is cheap to implement and expensive to skip.

1. **Standardize everything.** Every reading is shown with its three-year z-score or percentile (five years for monthly series), winsorized at plus or minus 3. Levels stay visible next to the transform so nothing hides behind it.

2. **Composites are equal-weighted.** Optimized weights overfit; four equal-weighted z-scores per composite, membership fixed in advance, changed only with a written reason.

3. **Condition on regime.** Two direction-based axes (growth and inflation momentum) plus liquidity place the cycle; every hit rate is reported unconditionally and for the current quadrant, and the alert shows the lower of the two.

4. **Evaluate signals properly.** Hit rate, average excess return, t-statistic, information coefficient (rank correlation of signal and the next eight-week return), decay profile from one to thirteen weeks, and turnover. Nothing is Confirmed below n of 20 and t of 2.

5. **Event studies, not anecdotes.** Surprise z = (actual minus consensus) divided by the dispersion of forecasts; average one-day and five-day moves per asset, split by sign, with n; the options-implied move is the bar for "big".

6. **Seasonality is de-trended and weighted half.** Subtract the unconditional mean, show hit rate and t-stat, never use it alone. Calendar effects with a mechanical cause (tax dates, expiry, rebalancing) rank above pure seasonality.

7. **No look-ahead.** Backtests use publication dates, not reference dates (July M2 is known in late August); walk-forward evaluation; 10 bp transaction cost assumed; the live alert log is the out-of-sample test.

8. **Vol-adjust before comparing.** Relative strength and momentum are measured on returns divided by 60-day realized volatility, so high-beta themes do not win by construction.

9. **Show the timestamp.** Every panel carries its data date; a panel older than its refresh interval greys out rather than showing a stale number as current.

## Open decisions, for review

Each has a recommendation so nothing waits on a discussion. Change any of them and the plan still holds.

- **Alert channel.** Email digest at 07:00 Bangkok for daily state changes, nothing real-time. **Recommendation:**email first; a Telegram bot later if the digest gets ignored. LINE's Messaging API works too but is heavier to set up than it is worth for one reader.

- **Thai exposure.** The SET, the baht, Bank of Thailand and baht gold as one row each, since that is how gold is quoted locally. **Recommendation:**include them in v1; they cost four extra series.

- **Free data only.** ETF flows come from share counts, not from EPFR; breadth from holdings files, not from a data vendor. **Recommendation:**accept the proxies; they track the paid series closely enough for a state machine with three-day confirmation.

- **Thresholds.** The five detector bars and the two divergence lines are starting values. **Recommendation:**leave them alone for three months, then tune from the alert log, not from memory.

- **Scope guard.** No trade execution, no single-stock analysis, no price targets. **Recommendation:**keep it a regime and rotation monitor; everything that would make it a trading system doubles the build time.

- **Where it lives.** A static site on a private URL, rebuilt nightly by the same GitHub Action that fetches the data. **Recommendation:**GitHub Pages; no server to maintain.

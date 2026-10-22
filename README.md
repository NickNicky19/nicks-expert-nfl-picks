# Nick's Expert NFL Picks

**Live site:** https://nicknicky19.github.io/nicks-expert-nfl-picks/

NFL props against real sportsbook lines, fantasy projections, live scoring and play-by-play, league sync and trade ideas, styled after Sleeper.
A scheduled daily Python build writes static JSON, and a static page on GitHub Pages reads it.

This is Nick's edition of [Joshua Moy's original project](https://github.com/joshuam0y/joshua-moy-expert-nfl-picks). The projection code, existing archives, and historical track record came from that project. Newly published results are generated in this repository; the historical record should not be presented as picks originally made by Nick.

## What's on the page

- **Real lines**: every prop uses DraftKings' line (via ESPN) when posted, then Sleeper Picks' line, and only then our
  own estimate (labeled "est"). Cards show where DraftKings opened, DraftKings' live line during the game, and our line.
- **Live scores and play-by-play**: tap a game for the field, last play, quarter scores, win probability, every drive
  and play (scoring, big plays, turnovers, flags), the box score and fantasy leaders. Polled from ESPN every 15 to
  30 seconds.
- **Live stats and fantasy points**: Sleeper's live feed (one small request for every player), scored with Sleeper's
  standard PPR or half PPR (a switch on the page) for QB, RB, WR and TE, and ESPN's standard scoring for kickers and
  defenses. Checked against Sleeper's and ESPN's own totals.
- **Game lines**: DraftKings spread, total, moneylines and implied team points, live odds during games, and ours next
  to them: every player's projection added up into team scores (`pull/gamemodel.py`), with leans graded at the final.
- **Scoring**: Sleeper PPR (default) or half, ESPN PPR or half, or any Sleeper league's exact settings (find leagues by
  username or league ID). Kickers and defenses always use ESPN standard scoring.
- **News**: ESPN headlines tagged with players, an injury report by game, and each player's latest notes.
- **Game logs**: each player's games this season with snaps and share of the team's snaps, then Sleeper's projection
  for every remaining week (and his bye), in the chosen scoring.
- **Rest of season and trades**: a rest-of-season ranking, and a trade calculator that values players by
  rest-of-season points above waiver-level replacement for your league's size, lineup and bench.
- **League tab**: start/sit for this week (players whose games have started stay locked), live matchups, standings,
  every roster and free agents. **League sync**: enter a Sleeper username (or an ESPN league ID; private ESPN leagues
  work in Chrome when signed in to espn.com) to load every roster: your best lineup, your rank at each
  position, and 1-for-1 / 2-for-1 trades with every team that improve your starting lineup and are fair for both
  sides (their lineup can't get worse). Top targets per position, position ranks (WR14), both lineups after a trade, and an
  AI trade builder.
- **Ask AI**: a built-in chat (Google Gemini, through the Worker) that sees your league, roster, our top picks and the
  trade you're looking at, and answers in a few plain sentences.
- **Past weeks**: a week picker above the scores. Each finished week (`output/data/weeks/`, built once by
  `pull/build.py`) has final scores, DraftKings' game lines and closing player lines, and every stat line, so past
  game pages show the box score, play-by-play, fantasy points and each prop's result.
- **Future weeks and teams**: the week picker runs through week 18 (upcoming games with DraftKings' line and a
  fantasy preview). The Teams tab has every team's schedule, ESPN depth chart and injuries (`output/data/teams.json`,
  rebuilt every update). The League tab shows your fantasy schedule for the rest of the season with projected scores.
- **FLEX filters** everywhere positions are filtered, using your league's flex rules.
- **Injuries by game**: each game page lists both teams' injuries (ESPN's report for every position plus Sleeper's
  statuses, IR included).
- **Injuries in depth**: expected return, games missed, snap shares, a status timeline recorded every build
  (`data/cache/injury_timeline.json`) and who plays more if a player sits.
- **Matchup difficulty**: opponent rank against each position this season, and rest-of-season schedule strength.
- **Compare**: two players side by side with a start recommendation.
- **Top Overs / Top Unders**: the biggest gaps between our number (Sleeper's projection, adjusted) and the real line.
  They lock at kickoff.
- **Fantasy**: rankings by position, FLEX, K and DEF, projected and live.
- **Injuries**: Sleeper's designations each update, plus ESPN's game-day news (inactives) as soon as it's posted.
- **Track Record**: picks and leans graded after each game, and our lines compared with DraftKings' on every finished
  game this season.

## How lines are made

DraftKings' line is used whenever there is one, then Sleeper Picks'. Our projection is Sleeper's projection times a
matchup factor: how players at the same position with a similar season average have done against this defense this
season, compared with their own averages (`pull/matchup.py`), pulled toward neutral when there are few games. Last
season is never used. A lean compares our projection with the real line; without a real line there's no lean.
`python tools/compare_lines.py` compares DraftKings' closing lines with a matchup-adjusted season average on every
finished game this season.

Leans can't be backtested: Sleeper revises past weeks' projections after the games, so the track record only grades
what was saved before kickoff.

## Phase 2 review branch

The retained production model is unchanged. Phase 2 records exact matchup inputs,
compares raw Sleeper and the clone at matched times for receptions, rushing
attempts and passing yards, and saves an experimental probability challenger in
shadow mode. Each player/game/statistic counts once, even with many captures.
Accuracy needs confirmed finals and participation; initial outcomes are pending.
Calibration and profitability are unproven, and promotion is disabled.

Sleeper normal-line selection captures retain contract, line, side, offered leg
multiplier, collection/source timestamps and rule provenance. Missing full entry
payout/settlement information remains explicit. No odds, EV, paid service or new
account is added. See [UPGRADE_NOTES.md](UPGRADE_NOTES.md),
[evaluation rules](docs/EVALUATION_PROTOCOL.md), [offer scope](docs/OFFER_CAPTURE.md),
[diagnosis](docs/PHASE2_DIAGNOSIS.md) and [recovery](ROLLBACK.md).

The separate day/timing and over/under study is **registered but not implemented**
at the safe handoff. See [timing protocol](docs/TIMING_PROTOCOL.md) and
[implementation handoff](docs/IMPLEMENTATION_HANDOFF.md). Automatic implementation
is disabled. The existing hourly audit uses PR #1; a tested cooperative remote
writer gate is provided, while native GitHub-triggered environment/gate adoption
remains unverified. No scheduler, API-key requirement or replacement repo was added.

## Running it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/build_recorded.py  # unchanged builder plus exact input receipts
.venv/bin/python tools/verify.py --offline
.venv/bin/python tools/phase2_capture.py --mode live
.venv/bin/python tools/verify.py    # also runs network scoring diagnostics
cd output && python3 -m http.server 8000
```

`tools/verify.py` checks four things:

- PPR matches Sleeper's own totals on every cached player-week.
- Lines rebuild exactly from earlier weeks only.
- The full recorded builder population and frozen-game input origins match.
- The output is consistent.
- Live ESPN scoring matches Sleeper's final PPR for finished games.

## Files

| Path | What it does |
| --- | --- |
| `pull/sources.py` | Sleeper and ESPN requests |
| `pull/scoring.py` | fantasy scoring (all positions), prop categories, line factors |
| `pull/books.py` | DraftKings lines via ESPN, Sleeper Picks lines |
| `pull/build.py` | builds `output/data/week.json`, the weekly archive and the track record |
| `pull/grade.py` | grades archived weeks |
| `pull/matchup.py` | matchup factors from this season's games |
| `pull/gamemodel.py` | our game projection: team scores, spread, total, moneyline |
| `pull/news.py` | ESPN's injury report |
| `tools/verify.py`, `tools/compare_lines.py` | checks, DraftKings comparison |
| `tools/build_recorded.py` | exact retained-builder input recording |
| `tools/scorecard.py`, `tools/shadow.py` | unique prospective comparison and shadow probability scoring |
| `tools/offers.py`, `tools/phase2_capture.py` | narrow source capture and evidence pipeline |
| `data/forward`, `data/verification`, `data/shadow`, `data/offers`, `data/outcomes` | create-only evidence |
| `config/evaluation-policy.json` | versioned evaluation/promotion rules |
| `output/` | the site (`index.html`, `app.js`, `style.css`) and its data |
| `data/cache/` | trimmed weekly stats (finished weeks are fetched once) |
| `.github/workflows/hourly.yml` | daily scheduled build, commit and Pages deploy; manual/code-change runs retained |

Data comes from the Sleeper API (projections, stats, players, injuries, Picks lines) and ESPN (scores,
play-by-play, box scores, injuries, DraftKings lines). This is for fun, not betting advice.

Nick's edition is maintained at [NickNicky19/nicks-expert-nfl-picks](https://github.com/NickNicky19/nicks-expert-nfl-picks). Original project and historical results: [joshuam0y/joshua-moy-expert-nfl-picks](https://github.com/joshuam0y/joshua-moy-expert-nfl-picks).

## GitHub Pages

The `hourly.yml` workflow has one scheduled website refresh per day, targeting
**8:06 a.m. America/Chicago**, with daylight-saving changes handled by GitHub.
GitHub may delay or drop a scheduled run; this is a target, not a completion-time
guarantee. Deliberate manual refresh/recovery and main code-change runs may also
occur. The historical filename and **Hourly update** display name are retained
for existing references. Use **Actions → Hourly update → Run workflow → main**
for a deliberate manual refresh. The shared `hourly-update` concurrency lock
and required checks remain in force. Ticker's schedule and dispatch loop are
retired; its retained entrypoint is inert.

Daily server-generated snapshots provide fewer pregame observations and may
leave lines, forecasts and grading updates older between successful builds.
Historical forecasts, selections and outcomes remain preserved. The registered
24-hour, 6-hour and 90-minute checkpoints still require an eligible observation
at or before the checkpoint and no more than 60 minutes old. Daily scheduling
will miss more checkpoints; record missing/unknown coverage under the existing
policy. Never use a later observation to fill a checkpoint or relax freshness.
Selection weekday, kickoff weekday and pregame lead time remain distinct.

Apply this cadence to both main and PR #1's development workflow before their
later integration. The recovery-suite cadence guard must pass on the actual
integration tree; do not restore the old hourly/half-hour cron or Ticker loop.
This scheduling change does not activate Phase 2, its experiments or seed
preparation. GitHub Pages continues using the existing deployment process.

## Yahoo sign-in and the AI chat (optional)

`worker/` is a small Cloudflare Worker that keeps the two secrets the static site can't: the Yahoo app
secret (for "Sign in with Yahoo"; Yahoo's API doesn't allow requests from web pages) and a Google Gemini API key
(for the chat). Both features stay hidden on the site until `WORKER_URL` in `output/app.js` points at Nick's own Worker. The copied site does not call the original project's Worker.

1. `cd worker && npx wrangler login`, then `npx wrangler deploy` (prints the Worker's address).
2. Create a Yahoo app at https://developer.yahoo.com/apps/create/ (Web Application, Fantasy Sports: Read,
   redirect URI `<worker address>/yahoo/callback`).
3. Get a Gemini API key at https://aistudio.google.com/apikey.
4. `npx wrangler secret put YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET` and `GEMINI_API_KEY`.
5. Set `WORKER_URL` in `output/app.js` to the new Worker's address and publish that change. Keep all secrets out of Git.


## Phase 2 reporting checkpoint (2026-10-22)

The current public website and this development checkpoint are different releases.
The public Phase 1 Props/Record/My Picks features and the daily scheduling change
do not establish deployment of the Phase 2 grading/reporting upgrade. This local
checkpoint is implemented but final combined checks, exact-source CI, source and
artifact review, and release authorization are still pending.

The proposed development report adds weekly/cumulative recorded Top Over/Under
and qualifying-lean grading, exact category/side/source/timing groups, separately
recorded Biggest-lean and Projected-points strategies, and an aggregate
all-category forecast-accuracy section. Display sorts alone are not recorded
strategies. Historical observations do not acquire new strategy membership.
The rich all-category evaluation rows remain local; only the typed aggregate
contract is prepared for the public report. Numerical accuracy, TD probability
scores and selection hit rates remain separate measurements.

The separate paper-first Parlay Builder implementation supports 2–6 saved legs,
category and Over/Under/Mixed filters, immutable ticket revisions and separate
leg/ticket statistical results. It uses one reference source per ticket, avoids
repeated players and same-game combinations, and may return NO_ACTION. Local
save time is an owner-device clock, not independently timestamped pregame proof.
It provides no executable-offer, venue-settlement, ticket-probability, EV or ROI
claim. Its source and public behavior require their own completed checks and
release review; a development implementation is not a deployed feature.

The release remains blocked on representative cloud preparation and operating
validation, a coherent production-rooted artifact, exact public-content review,
and the combined deployment/public Props/Record/cache/My Picks/recovery decision.
The existing canonical requirements and research roadmap remain in
`docs/EVALUATION_PROTOCOL.md`; no additional scheduler or roadmap is introduced.


## Validated source and current-data checks

The development execution contract keeps complete regression coverage in source
CI and verifies its exact code/test/workflow/configuration, retained fixture and
installed-dependency bindings before a Phase 2 update. Current data is freshly
validated every run through the unchanged generation and Pages checks; a green
source run cannot qualify missing or corrupt evidence. Source/runtime changes
without matching passed checks fail closed. See the current
[implementation handoff](docs/IMPLEMENTATION_HANDOFF.md) for source versus
operating costs, integration status and release verification. Daily scheduling,
manual recovery and Ticker retirement remain unchanged.

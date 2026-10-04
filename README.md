# NFL Player Props

Player prop lines, PPR fantasy projections and live scoring for every NFL game, styled after Sleeper.
It's a companion to [mlb-player-props](https://github.com/joshuam0y/mlb-player-props) and is built the same way:
a Python build writes static JSON every hour, and a static page on GitHub Pages reads it.

## What's on the page

- **Live scores**: every game's score, clock, down and distance, and possession, polled from ESPN every 30 seconds
  while games are on.
- **Live stats and PPR**: each player's box score from ESPN, scored with Sleeper's standard PPR, including
  2-point conversions. Props show live progress; an over is marked cleared once it passes the line.
- **Props**: lines for passing, rushing and receiving categories, anytime TD chance, and fantasy points.
  Each prop opens to show the player's last 8 games against the line. You can also type in your own line.
- **Top Overs / Top Unders**: the biggest gaps between Sleeper's projection and the line. They lock at kickoff.
- **Fantasy**: PPR rankings by position and FLEX, projected and live.
- **Track Record**: picks and leans graded after each game goes final.

## How lines are made

The line is `k x average of the player's last 8 games`, rounded to a .5. Only games before this week count.
`k` is set per category (`pull/scoring.py`). A plain average put the result under the line about 63% of the time.
Each `k` was fit on 2025 to make that 50/50, then checked on 2026 games the fit never saw
(`python tools/calibrate.py` reruns both steps).

A lean compares Sleeper's projection, scaled by the same `k`, to the line.

Leans can't be backtested. Sleeper revises past weeks' projections after the games, so the track record only
grades what was saved before kickoff. It starts from the first week this ran live.

## Running it

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python pull/build.py      # writes output/data/
.venv/bin/python tools/verify.py    # checks scoring, point-in-time lines and live scoring
cd output && python3 -m http.server 8000
```

`tools/verify.py` checks four things:

- PPR matches Sleeper's own totals on every cached player-week.
- Lines rebuild exactly from earlier weeks only.
- The output is consistent.
- Live ESPN scoring matches Sleeper's final PPR for finished games.

## Files

| Path | What it does |
| --- | --- |
| `pull/sources.py` | Sleeper and ESPN requests |
| `pull/scoring.py` | PPR scoring, prop categories, line factors |
| `pull/build.py` | builds `output/data/week.json`, the weekly archive and the track record |
| `pull/grade.py` | grades archived weeks |
| `tools/verify.py`, `tools/calibrate.py` | checks and line calibration |
| `output/` | the site (`index.html`, `app.js`, `style.css`) and its data |
| `data/cache/` | trimmed weekly stats (finished weeks are fetched once) |
| `.github/workflows/hourly.yml` | hourly build, commit and Pages deploy |

Data comes from the Sleeper API (projections, stats, players, injuries) and ESPN's public scoreboard and game
summaries. Lines are not from a sportsbook. This is for fun and practice, not betting advice.

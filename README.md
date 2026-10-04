# NFL Player Props

Player prop lines, PPR fantasy projections and live scoring for every NFL game, styled after Sleeper.
It's a companion to [mlb-player-props](https://github.com/joshuam0y/mlb-player-props) and is built the same way:
a Python build writes static JSON every hour, and a static page on GitHub Pages reads it.

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
- **Game logs**: each player's games this season with snaps and share of the team's snaps.
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
| `pull/scoring.py` | fantasy scoring (all positions), prop categories, line factors |
| `pull/books.py` | DraftKings lines via ESPN, Sleeper Picks lines |
| `pull/build.py` | builds `output/data/week.json`, the weekly archive and the track record |
| `pull/grade.py` | grades archived weeks |
| `pull/matchup.py` | matchup factors from this season's games |
| `pull/gamemodel.py` | our game projection: team scores, spread, total, moneyline |
| `pull/news.py` | ESPN's injury report |
| `tools/verify.py`, `tools/compare_lines.py` | checks, DraftKings comparison |
| `output/` | the site (`index.html`, `app.js`, `style.css`) and its data |
| `data/cache/` | trimmed weekly stats (finished weeks are fetched once) |
| `.github/workflows/hourly.yml` | hourly build, commit and Pages deploy |

Data comes from the Sleeper API (projections, stats, players, injuries, Picks lines) and ESPN (scores,
play-by-play, box scores, injuries, DraftKings lines). This is for fun, not betting advice.

Made by Joshua Moy.

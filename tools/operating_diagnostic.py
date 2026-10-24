"""Nonpublishing diagnostic candidate. Fictional workload; never a real forecast.

Source installation and hosted execution require the accompanying owner approval.
Validators, report builders and integrity checks are real. External HTTP, clocks, filesystem destinations, local archive transport and an explicitly attributed fictional participation adapter are declared below.
"""
import argparse
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import resource
import os
from collections import Counter
import shutil
import socket
import subprocess
import sys
import time
from unittest.mock import patch

BASE = "b3de2fbd88ba3247b407a856972285ad10527b99"
CAMPAIGN = "NFL-WEB-OPERATING-SEED-THREE-20261020-B3"
SEED_HOUR = 77
SEED_REVISION = 1
NEXT_REVISION = 2
SAMPLE_SECONDS = 135
START = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
FULL = dict(games=14, per_team=20, snapshots=277, outcomes=49, generations=24)
VALID_FROZEN_SMALL = dict(games=2, per_team=20, snapshots=7, outcomes=3, generations=2)
SMALL = dict(games=14, per_team=20, snapshots=7, outcomes=3, generations=2)
NOTICE = "WHOLLY_FICTIONAL_NOT_PROSPECTIVE_NOT_PREDICTIVE_EVIDENCE"
PHASE_HOURS = (0, 5.5, 23.5, 29.5, 47.5, 71.5, 75.5)
PHASE_ALLOCATIONS = (35, 35, 35, 35, 35, 34, 34)
HISTORICAL_CLOCKS = {
    4: ("2026-10-20T18:00:00Z", "2026-10-21T12:00:00Z", "2026-10-21T16:30:00Z",
        "2026-10-24T18:00:00Z", "2026-10-25T12:00:00Z", "2026-10-25T16:30:00Z"),
    5: ("2026-10-28T18:00:00Z", "2026-10-29T12:00:00Z", "2026-10-29T16:30:00Z"),
}
# Closed software-test inputs, chosen for parser/side/ranking coverage, not results.
SLEEPER_CASES = (
    ("pass_yd", "fictional-01-00", 150.5),
    ("pass_cmp", "fictional-00-01", 12.5),
    ("pass_att", "fictional-01-01", 20.5),
    ("pass_td", "fictional-01-00", 1.0),
    ("pass_int", "fictional-00-00", 0.5),
    ("rush_yd", "fictional-00-03", 22.5),
    ("rush_att", "fictional-00-04", 7.5),
    ("rush_att", "fictional-00-03", 6.5),
    ("rec", "fictional-00-09", 1.5),
    ("rec_yd", "fictional-00-11", 39.5),
    ("rush_rec_yd", "fictional-00-04", 45.0),
    ("pass_yd", "fictional-00-00", "twice_raw"),
    ("pass_cmp", "fictional-00-00", "under"),
    ("pass_att", "fictional-00-00", "under"),
    ("pass_td", "fictional-00-00", "under"),
    ("pass_int", "fictional-01-01", "under"),
    ("rush_yd", "fictional-00-05", "under"),
    ("rush_att", "fictional-00-06", "under"),
    ("rec", "fictional-00-12", "under"),
    ("rec_yd", "fictional-00-13", "under"),
    ("rush_rec_yd", "fictional-00-12", "under"),
)
PHASE_FOCUS = {
    "QB": ("pass_yd", "pass_cmp", "pass_att", "pass_td", "pass_int", "rush_yd", "pass_yd"),
    "RB": ("rush_yd", "rush_att", "rec", "rec_yd", "rush_rec_yd", "rec", "rush_yd"),
    "WR": ("rec", "rec_yd", "rush_rec_yd", "rec", "rec_yd", "rush_rec_yd", "rec"),
    "TE": ("rec", "rec_yd", "rec", "rec_yd", "rec", "rec_yd", "rec"),
}
GROUP_DIMENSION_FLOORS = dict(category=1505, category_side=2957, selection_weekday=112)


def phase_contract():
    return dict(schema_version="fictional-coverage-directed-inputs-v1", start=START.isoformat(),
        phase_hours=PHASE_HOURS, allocations=PHASE_ALLOCATIONS, focus=PHASE_FOCUS,
        side_rule="over iff (team index + roster slot + phase index) is even",
        focus_line="floor(max(min_pick, raw_projection - sign*3*category_scale)) + 0.5",
        other_line="max(0.5, round(raw_projection*(0.67 if espn_id odd else1.35))+0.5)",
        week_scope="Prior non-target offers retained; targeted source cases apply to Weeks4/5/6",
        push_control="DK slot7 rec uses fixed SHA-derived integer; primary fictional-00-07 line9 actual9",
        sleeper_contract="Week6 same category rule, matching paired sides, upcoming games only; Weeks4/5 prior4.5",
        freeze_rule="DK phase no later than last phase before kickoff; saved contracts also freeze in unchanged builder",
        projection_reader="Week6 modern presence-aware projection=True; legacy callable unchanged; Weeks4/5 prior reader unchanged",
        sign="+1 over, -1 under", reception_control=dict(player="fictional-00-03", line=5.5),
        source_omissions="retain slot10 DK omission and existing WR/TE reception fallback",
        outcome_rule="unchanged predeclared revision1 rec3, revision2 rec8; no offer uses outcomes",
        historical_clocks=HISTORICAL_CLOCKS, sleeper_cases=SLEEPER_CASES,
        targeted_dk_omissions="Only exact SLEEPER_CASES category/player pairs",
        under_rule="max(min_pick, floor(raw*1.5)+0.5); twice_raw=ceil(raw*2)",
        full_observations=dict(historical=9, week6_phase=243, original_cutover=1, corrected=24, total=277),
        phase_recording="Actual unchanged build at every phase+j whole seconds; no cloned/reclocked board")



def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def git(root, *args):
    if any(a in ("push", "pull") for a in args):
        raise RuntimeError("Remote mutation is forbidden")
    return subprocess.check_output(["git", "-C", str(root), "-c", "user.name=FictionalDiagnostic",
        "-c", "user.email=fictional@example.invalid", "-c", "core.hooksPath=/dev/null", *args],
        stderr=subprocess.PIPE).decode().strip()


def bind(code):
    sys.path[:0] = [str(code / "tools"), str(code / "pull")]
    import build, build_recorded, reliability, evidence, partial_week, phase2_capture
    import selection_publication, scorecard, source_evidence
    return dict(build=build, recorded=build_recorded, rel=reliability, ev=evidence,
        partial=partial_week, capture=phase2_capture, publication=selection_publication,
        score=scorecard, source=source_evidence)


class Provider:
    """Strict, deterministic fake HTTP responses, with no real teams or people."""
    def __init__(self, modules, dimensions, at=START, week=6):
        self.m, self.d, self.at, self.week = modules, dimensions, at, week
        self.calls = 0
        self.revision = 0
        self.roster = {}
        roles = ["QB", "QB", *(["RB"] * 5), *(["WR"] * 7), *(["TE"] * 4), "K", "DEF"]
        for team in range(dimensions["games"] * 2):
            for j in range(dimensions["per_team"]):
                pid = f"fictional-{team:02}-{j:02}"
                self.roster[pid] = dict(full_name=f"Fictional {team:02} Player {j:02}",
                    team=f"F{team:02}", position=roles[j], active=True, depth_chart_order=1,
                    espn_id=str(900000 + team * 100 + j), injury_status=None)

    def kick(self, season, week, game):
        if season == 2026 and week == 4:
            return datetime(2026, 10, 21 if game < 7 else 25, 18, tzinfo=timezone.utc)
        if season == 2026 and week == 5:
            return datetime(2026, 10, 29, 18, tzinfo=timezone.utc)
        hours=(30 if game < 2 else 76 if game < 9 else 78) if self.d["games"] == 14 else (30 if game == 0 else 102)
        if game == self.d["games"]-1:hours=102
        return START + timedelta(days=(season-2026)*365+(week-6)*7,hours=hours)

    def stats(self, pid, season, week, projection=False):
        p = self.roster[pid]
        n = int(sha(f"{pid}/{season}/{week}".encode())[:8], 16)
        b = self.m["build"]
        s = dict.fromkeys(b.scoring.STAT_KEYS, 0)
        s.update(gp=1, off_snp=52 + n % 9, tm_off_snp=70, pass_att=25 + n % 15,
            pass_cmp=16 + n % 9, pass_yd=180 + n % 150, pass_td=n % 4,
            pass_int=n % 2, rush_att=4 + n % 12, rush_yd=8 + n % 90,
            rush_td=n % 2, rec=2 + n % 8, rec_yd=10 + n % 100,
            rec_td=n % 2, fum_lost=n % 2)
        if p["position"] != "QB":
            for k in ("pass_att", "pass_cmp", "pass_yd", "pass_td", "pass_int"):
                s[k] = 0
        if self.revision and pid == "fictional-00-03" and week == 6:
            s["rec"] = {1:3,2:8}[self.revision]
        elif pid == "fictional-00-03" and week == 6:
            s["rec"] = 7
        if projection:
            for k in ("pass_yd", "rush_yd", "rec_yd", "rec", "rush_td", "rec_td", "pass_td"):
                s[k] += ((n % 93) + 1) / 100
        if not projection:
            slot = int(pid[-2:])
            if slot in (2,8):
                # No contradictory offensive activity in DNP/unknown controls.
                for key in s:
                    if key != "tm_off_snp": s[key] = 0
            if slot == 5: s["rush_yd"] = -2
            if slot == 6: s.update(rec=0,rush_yd=0)
        s["pts_ppr"] = (b.scoring.ppr_points(s, projection=projection)
                         if hasattr(b.scoring, "PRESENCE_VERSION") else b.scoring.ppr_points(s))
        s["pts_half_ppr"] = s["pts_ppr"] - .5*s["rec"]
        if not projection and int(pid[-2:]) == 4 and self.revision and season == 2026 and week == 6:
            s.update(rec=None,pts_ppr=None,pts_half_ppr=None)  # Genuinely incomplete fictional total.
        return s

    def scoreboard(self, season, week):
        events = []
        for g in range(self.d["games"]):
            kick = self.kick(season, week, g)
            state = "post" if self.at >= kick + timedelta(hours=4) else "in" if self.at >= kick else "pre"
            status = dict(state=state, completed=state == "post", name={"post":"STATUS_FINAL","in":"STATUS_IN_PROGRESS","pre":"STATUS_SCHEDULED"}[state],
                          shortDetail={"post":"Final","in":"In Progress","pre":"Scheduled"}[state])
            sides = [dict(homeAway=side, score="24", team=dict(id=str(t + 1), abbreviation=f"F{t:02}"))
                     for side, t in (("home", 2 * g), ("away", 2 * g + 1))]
            comp = dict(id=f"99{season}{week:02}{g:02}", status=dict(type=status), competitors=sides)
            events.append(dict(id=comp["id"], date=kick.isoformat(), status=dict(type=status), competitions=[comp]))
        return dict(events=events, season=dict(year=season, type=2), week=dict(number=week))

    def projection_value(self, pid, key):
        scoring=self.m['build'].scoring
        values=self.stats(pid,2026,self.week,True)
        if self.week==6 and hasattr(scoring,'PRESENCE_VERSION'):
            return scoring.stat_value(key,values,projection=True)
        return scoring.stat_value(key,values)

    def offer_line(self, pid, key, value, venue):
        """Predeclared fictional offers; never production or fitted economics."""
        import math
        p=self.roster[pid];slot=int(pid[-2:])
        prior=max(.5,round(value*(.67 if int(p['espn_id'])%2 else 1.35))+.5)
        # Fixed software equality controls, not future-information forecasting.
        push_line=2+int(sha(f"{pid}/2026/{self.week}".encode())[:8],16)%8
        if self.week in (4,5):
            return 4.5 if venue=='sleeper' else push_line if key=='rec' and slot==7 else prior
        if self.week!=6:raise RuntimeError('Undeclared fictional offer week')
        if pid=='fictional-00-03' and key=='rec':return 5.5
        if venue=='dk' and key=='rec' and slot==7:return push_line
        game=int(p['team'][1:])//2
        cutoff=min(self.at,self.kick(2026,self.week,game)-timedelta(microseconds=1))
        phase=max((i for i,h in enumerate(PHASE_HOURS) if cutoff>=START+timedelta(hours=h)),default=0)
        focus=PHASE_FOCUS.get(p['position'],(None,)*7)[phase]
        if key!=focus:return prior
        sign=1 if (int(p['team'][1:])+slot+phase)%2==0 else -1
        return math.floor(max(self.m['build'].scoring.CATEGORIES[key]['min_pick'],
            value-sign*3*self.m['build'].scoring.CATEGORIES[key]['scale']))+.5

    def targeted_sleeper(self):
        import math
        result = {}
        for key, pid, rule in SLEEPER_CASES:
            if pid not in self.roster:
                continue
            value = self.projection_value(pid, key)
            if value is None:
                raise RuntimeError('Declared source case has no supported projection')
            minimum = self.m['build'].scoring.CATEGORIES[key]['min_pick']
            line = (math.ceil(value*2) if rule == 'twice_raw' else
                    max(minimum, math.floor(value*1.5)+.5) if rule == 'under' else rule)
            result[(pid, key)] = line
        return result

    def sleeper_payload(self, original):
        reverse = {v:k for k,v in self.m['build'].books.SLEEPER_MARKETS.items()}
        cases = self.targeted_sleeper()
        # Replace only the designated category/player pair; keep other rec cases.
        kept = [market for market in original if (market['options'][0]['subject_id'],
                self.m['build'].books.SLEEPER_MARKETS[market['options'][0]['wager_type']]) not in cases]
        for (pid, key), line in cases.items():
            player = self.roster[pid]; game = int(player['team'][1:])//2
            if self.at >= self.kick(2026, self.week, game):
                continue
            kept.append(dict(status='active', updated_at=int(self.at.timestamp()*1000), options=[dict(
                status='active', outcome_type='over_under', sport='nfl', subject_type='player', subject_id=pid,
                subject_position=player['position'], wager_type=reverse[key], line_type='normal',
                game_status='pre_game', outcome=side, outcome_value=line, payout_multiplier='1.8',
                game_id=f'992026{self.week:02}{game:02}', line_id=f'coverage-{self.week}-{pid}-{key}-{side}',
                season=2026, season_type='regular', subject_team=player['team'],
                market_type=f'{reverse[key]}_over_under_player_{pid}') for side in ('over','under')]))
        return kept

    def get(self, url, params=None, **unused):
        self.calls += 1
        b = self.m["build"]
        if url.endswith("/v1/state/nfl"):
            return dict(season="2026", week=self.week, season_type="regular")
        if url.endswith("/v1/players/nfl"):
            return copy.deepcopy(self.roster)
        if "/stats/nfl/" in url or "/projections/nfl/" in url:
            season, week = map(int, url.split("/")[-2:])
            return [dict(player_id=pid, team=p["team"], opponent=f"F{int(p['team'][1:]) ^ 1:02}",
                game_id=f"99{season}{week:02}{int(p['team'][1:]) // 2:02}",
                season=season, week=week, player=dict(position=p["position"]), stats=self.stats(pid, season, week, "/projections/" in url))
                for pid, p in self.roster.items()]
        if url.endswith("/scoreboard"):
            return self.scoreboard(int(params["dates"]), int(params["week"]))
        if url.endswith("/propBets"):
            gid = url.split("/events/")[1].split("/")[0]
            game = int(gid[-2:])
            keys = list(b.books.MARKETS)
            items = []
            targeted = self.targeted_sleeper()
            for pid, p in self.roster.items():
                if int(p["team"][1:]) // 2 != game:
                    continue
                for name in keys:
                    key = b.books.MARKETS[name]
                    slot = int(pid[-2:])
                    if slot == 10 or key == "rec" and p["position"] in ("WR", "TE") and slot % 3 == 2:
                        continue  # Real source/ref coverage through existing precedence.
                    if (pid, key) in targeted:
                        continue  # Prospective exact-pair source coverage; DK precedence is unchanged.
                    value = self.projection_value(pid, key)
                    if value is not None:
                        line = self.offer_line(pid, key, value, "dk")
                        items.append(dict(type=dict(name=name), athlete={"$ref": "/athletes/" + p["espn_id"]},
                            open=dict(target=dict(value=line)), current=dict(target=dict(value=line))))
            return dict(items=items)
        if url == b.books.SLEEPER_LINES:
            original = [dict(status="active", updated_at=int(self.at.timestamp()*1000), options=[dict(status="active", outcome_type="over_under", sport="nfl", subject_type="player", subject_id=pid,
                    subject_position=p["position"], wager_type="receptions", line_type="normal",
                    game_status="pre_game", outcome=side, outcome_value=(4.5 if self.week in (4,5) else self.offer_line(pid,"rec",self.projection_value(pid,"rec"),"sleeper")), payout_multiplier="1.8",
                    game_id=f"99{2026}{self.week:02}{int(p['team'][1:])//2:02}", line_id=f"fictional-{pid}-{side}",
                    season=2026, season_type="regular", subject_team=p["team"],
                    market_type=f"receptions_over_under_player_{pid}")
                    for side in ("over", "under")]) for pid, p in self.roster.items()
                    if p["position"] in ("WR", "TE") and int(pid[-2:]) % 3 == 2
                    and self.at < self.kick(2026,self.week,int(p["team"][1:])//2)]
            return self.sleeper_payload(original)
        if url.endswith("/odds"):
            return dict(items=[dict(provider=dict(id="100"), spread=-3.5, overUnder=47.5)])
        if url.endswith("/injuries"):
            return dict(injuries=[])
        if url.endswith("/teams"):
            return dict(sports=[dict(leagues=[dict(teams=[dict(team=dict(id=str(i + 1)))
                for i in range(self.d["games"] * 2)])])])
        if url.endswith("/depthcharts"):
            t = int(url.split("/")[-2]) - 1
            return dict(team=dict(abbreviation=f"F{t:02}", displayName=f"Fictional Team {t}"), depthchart=[])
        raise RuntimeError("Undeclared external input: " + url.split("?")[0])


@contextlib.contextmanager
def external(modules, provider, root):
    """Only HTTP, fixture filesystem destinations and fictional source clocks."""
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return provider.at
    def denied(*args, **kwargs):
        raise RuntimeError("Network denied by fictional diagnostic")
    import requests
    b = modules["build"]
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(requests.sessions.Session, "request", denied))
        stack.enter_context(patch.object(socket.socket, "connect", denied))
        stack.enter_context(patch.object(socket.socket, "connect_ex", denied))
        stack.enter_context(patch.object(b.sources, "get_json", provider.get))
        for module in (modules[k] for k in ("build", "recorded", "capture", "score")):
            if hasattr(module, "datetime"):
                stack.enter_context(patch.object(module, "datetime", Clock))
        stack.enter_context(patch.object(b, "now_utc", lambda: provider.at))
        for name, value in dict(ROOT=root, OUT=root / "output/data", CACHE=root / "data/cache",
                                ARCHIVE=root / "output/data/archive", WEEKS=root / "output/data/weeks").items():
            stack.enter_context(patch.object(b, name, value))
        stack.enter_context(patch.object(b.books, "ATHLETES", root / "data/cache/espn_athletes.json"))
        yield


def plan(modules, root, board, at, modern):
    rel, ev, partial = modules["rel"], modules["ev"], modules["partial"]
    if modern:
        import data_integrity_v2 as di
        api, version, validator = di, di.PLAN, di.VALIDATOR
    else:
        api, version, validator = partial, partial.PLAN_VERSION, partial.VERSION
    # The caller provides the exact complete schedule/status, including all games.
    status = modules["source"].record_scoreboard(modules["_provider"].scoreboard(2026, 6),
        dict(dates=2026, week=6, seasontype=2), at)
    ev.write(root, "verification/partial-schedule-baselines", dict(schema_version="partial-schedule-baseline-v1",
        season=2026, week=6, status=status))
    p = dict(schema_version=version, plan_id="FICTIONAL_DIAGNOSTIC_" + ("V2" if modern else "V1"),
        model="sleeper-matchup-data-integrity-v2" if modern else "original_sleeper_matchup_baseline",
        season=2026, week=6, plan_prepared_at=rel.stamp(at), effective_not_before=rel.stamp(at),
        expires_at=rel.stamp(at + timedelta(days=3)), validator_contract=validator,
        engine_files=api.engine_files(root) if modern else rel.engine_hashes(root),
        initial_complete_board_sha256=rel.digest(board),
        games=[{k:g[k] for k in ("id", "home", "away", "kickoff")} for g in board["games"]],
        legacy_exemptions=[dict(game_id=g["id"], forecast_contract_sha256=rel.digest(partial.game_contract(board,g["id"])),
            reason="FICTIONAL_UNRECORDED_LEGACY_NOT_REAL_EXEMPTION") for g in board["games"]
            if rel.utc(g["kickoff"]) < at] if modules["_provider"].d["games"] == 14 else [],
        completion_status_max_age_seconds=60,
        full_board_verified=False, complete_week_qualified=False, experimental_recording_enabled=False,
        schedule_status_payload_sha256=rel.digest(status), schedule_status_observed_at=status["collected_at"])
    spec = dict(plan=p, plan_sha256=rel.digest(p), validator_sha256=api.code_sha256(),
                owner_authorization="FICTIONAL_ONLY_NOT_A_REAL_ACTIVATION")
    original = ev.write(root, "verification/partial-plan-boards", dict(schema_version="partial-plan-board-v1",
        season=2026, week=6, board=board))
    spec["initial_board_receipt"] = original.relative_to(root).as_posix()
    rel.atomic_json(root / "config/phase2.json", dict(capture_enabled=True,
        experimental_recording_enabled=False, challenger_production_enabled=False,
        production_model=p["model"], verification_mode=validator, partial_week=spec))
    return spec


def copy_source(code, root):
    for lane in ("pull", "tools", "config"):
        shutil.copytree(code / lane, root / lane, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "output").mkdir(exist_ok=True)
    for p in ((code / "output").iterdir() if (code / "output").is_dir() else []):
        if p.is_file():
            shutil.copyfile(p, root / "output" / p.name)


def legacy_seed(code, root, dimensions):
    m=bind(code); provider=Provider(m,dimensions);m['_provider']=provider
    for week, clocks in HISTORICAL_CLOCKS.items():
        provider.week=week
        for clock in clocks:
            provider.at=m['rel'].utc(clock)
            with external(m,provider,root):m['recorded'].record_build(root)
            historical=m['rel'].load_json(root/'output/data/week.json')
            if m['rel'].utc(historical['generated_at']) != provider.at:
                raise RuntimeError('Historical generation clock changed')
            m['rel'].capture(historical,{k:historical[k] for k in ('season','week','generated_at')},
                root,provider.at,m['rel'].engine_hashes(root),mode='live')
    from offers import capture_offers
    provider.week=6
    phase_records=[]
    for phase,hour in enumerate(PHASE_HOURS):
        provider.at=START+timedelta(hours=hour)
        prior=m['rel'].load_json(root/'output/data/week.json')
        frozen={g['id']:m['partial'].game_contract(prior,g['id']) for g in prior['games'] if prior['week']==6 and m['rel'].utc(g['kickoff'])<=provider.at}
        with external(m,provider,root):m['build'].run()
        board=m['rel'].load_json(root/'output/data/week.json')
        if m['rel'].utc(board['generated_at'])!=provider.at:raise RuntimeError('Phase generation clock changed')
        if any(m['partial'].game_contract(board,gid)!=contract for gid,contract in frozen.items()):raise RuntimeError('Started phase contract changed')
        count=1 if dimensions['snapshots']==7 else PHASE_ALLOCATIONS[phase]
        phase_records.append(dict(phase=phase,generated_at=board['generated_at'],board_sha256=m['rel'].digest(board),
            observations=count,started_game_ids=sorted(g['id'] for g in board['games'] if g['state']!='pre')))
        offer=m['ev'].write(root,'offers',capture_offers(board,dict(status='available',collected_at=m['rel'].stamp(provider.at),markets=provider.get(m['build'].books.SLEEPER_LINES)),{pid:{'season':2026,'week':6,'team':v['team'],'game_id':f'99202606{int(v["team"][1:])//2:02}'} for pid,v in provider.roster.items()},m['rel'].load_json(root/'config/sleeper-rules-provenance.json')))
        phase_records[-1]['offer_receipt']=offer.relative_to(root).as_posix()
        for j in range(count):
            provider.at=START+timedelta(hours=hour,seconds=j)
            if j:
                with external(m,provider,root):m['build'].run()
            d=m['rel'].load_json(root/'output/data/week.json')
            if m['rel'].utc(d['generated_at']) != provider.at:
                raise RuntimeError('Observation was not genuinely built at its clock')
            if any(m['partial'].game_contract(d,gid)!=contract for gid,contract in frozen.items()):
                raise RuntimeError('Started observation contract changed')
            m['rel'].capture(d,{k:d[k] for k in ('season','week','generated_at')},root,provider.at,m['rel'].engine_hashes(root),mode='live')
    put(root/'FICTIONAL_PHASES.json',dict(contract=phase_contract(),contract_sha256=sha(encoded(phase_contract())),phases=phase_records))
    # Small fixture retains valid-frozen-origin stress. Full fixture has nine genuine fictional missing origins.
    provider.at=START+timedelta(hours=SEED_HOUR) if dimensions['games']==14 else START
    if dimensions['games']==14:
        with external(m,provider,root):m['recorded'].record_build(root)
        board=m['rel'].load_json(root/'output/data/week.json')
    spec=plan(m,root,board,provider.at,False)
    expected=9 if dimensions['games']==14 else 0
    if len(spec['plan']['legacy_exemptions'])!=expected:raise RuntimeError('Legacy fixture population')
    with external(m,provider,root):
        registration,_=m['partial'].register_plan(root,spec,provider.at,source_sha='bf3ec09129e918b73641a65af5f05ecd5559139a',initial_board=board)
        closing=m['source'].record_scoreboard(provider.scoreboard(2026,6),dict(dates=2026,week=6,seasontype=2),provider.at)
        m['partial'].record_bundle(root,board,m['rel'].load_json(root/'output/data/matchup-proof.json'),closing,spec,registration.relative_to(root).as_posix(),m['capture'].read_native_baseline,clock=lambda:provider.at)
    from offers import capture_offers
    original_inputs=m['ev'].read(root/m['rel'].load_json(root/'output/data/matchup-proof.json')['latest_inputs'])
    m['ev'].write(root,'offers',capture_offers(board,original_inputs['offer_observation'],original_inputs['projection_metadata'],m['rel'].load_json(root/'config/sleeper-rules-provenance.json')))


def commit(root):
    # Existing updater data lanes plus explicit fixture-only adapter provenance; no remote writes.
    git(root, "add", "output/data", "data/cache")
    for lane in ("forward", "history", "verification", "shadow", "offers", "outcomes"):
        if (root / "data" / lane).exists():
            git(root, "add", "data/" + lane)
    if (root/"FICTIONAL_PARTICIPATION_ADAPTER.json").exists():
        git(root,"add","FICTIONAL_PARTICIPATION_ADAPTER.json")
    if subprocess.call(["git", "-C", str(root), "diff", "--cached", "--quiet"]) != 0:
        git(root, "commit", "-qm", "Fictional diagnostic data; never publish")


def fixture(code, root, small=False):
    if root.exists():
        raise RuntimeError("Fixture destination must be new")
    root.mkdir(parents=True)
    put(root / "FICTIONAL_ONLY.json", dict(notice=NOTICE, campaign=CAMPAIGN, dimensions=SMALL if small else FULL, reviewed_source=BASE, construction_code=git(code,"rev-parse","HEAD")))
    dimensions = SMALL if small else FULL
    source_check(code)
    m = bind(code)
    import data_integrity_v2 as di
    # Model inputs are generated; source/Git object reads are fixed public source only.
    with di.legacy_source(code) as old:
        copy_source(old, root)
        legacy_env = dict(os.environ)
        legacy_env.pop("GITHUB_SHA", None)  # Actual retained export has no current checkout commit.
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "legacy", "--code", str(old),
            "--root", str(root), *( ["--small"] if small else [])], check=True, stdout=subprocess.DEVNULL, env=legacy_env)
    copy_source(code, root)
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", "https://github.com/NickNicky19/nicks-expert-nfl-picks.git")
    # Local source-object import is required by actual source/archive validators.
    git(root, "fetch", "--quiet", str(code), git(code, "rev-parse", "HEAD"))
    git(root, "update-ref", "refs/fixture/source", git(code, "rev-parse", "HEAD"))
    git(root, "add", ".")
    git(root, "commit", "-qm", "Wholly fictional initial fixture; no real data copied")
    import diagnostic_seed
    provider=Provider(m,dimensions,START+timedelta(hours=SEED_HOUR))
    diagnostic_seed.legacy_backup_fixture(root,sys.modules[__name__],m,provider)
    git(root,'add','FICTIONAL_LEGACY_BASELINE.json');commit(root)
    subprocess.run([sys.executable, str(Path(__file__).resolve()), "modern", "--code", str(root),
        "--root", str(root), *(["--small"] if small else [])], check=True, stdout=subprocess.DEVNULL)
    return root


def modern_seed(root, dimensions):
    m = bind(root)
    provider = Provider(m, dimensions, START + timedelta(hours=SEED_HOUR,seconds=5))
    m["_provider"] = provider
    board = m["rel"].load_json(root / "output/data/week.json")
    plan(m, root, board, provider.at, True)
    git(root,"add","config/phase2.json")
    git(root,"commit","-qm","Fictional corrected plan, not production activation")
    with external(m, provider, root), patch.object(m["capture"], "_public_archive_commit",
            side_effect=lambda ref, tree: assert_local_tree(root, ref, tree)):
        for i in range(dimensions["generations"]):
            provider.at = START + timedelta(hours=SEED_HOUR, seconds=(i+1) * 5)
            provider.revision = int(i >= dimensions["generations"] // 2)
            m["capture"].run_capture(root, build_first=True)
            if i == 0:
                add_participation_observation(root, m, provider)
            commit(root)
            put(root.parent / "progress.json", dict(generation=i+1, target=dimensions["generations"],
                wall_clock=datetime.now(timezone.utc).isoformat()))


def add_participation_observation(root, m, provider):
    """Supported fictional attributed adapter; NOT Sleeper ingestion proof."""
    at = provider.at + timedelta(seconds=1)
    changes = []
    for path in sorted((root / "data/cache").glob("stats_2026_*.json")):
        cache = m["rel"].load_json(path)
        before = sha(path.read_bytes())
        for pid, entry in cache.items():
            if pid.startswith("fictional-") and int(pid[-2:]) == 2:
                if entry.get("stats",{}).get("gp",0) or entry.get("stats",{}).get("off_snp",0):
                    raise RuntimeError("Contradictory fictional DNP input")
                entry.update(participation_status="dnp", participation_source="fictional_attributed_participation_adapter_v1")
        m["rel"].atomic_json(path, cache)
        changes.append(dict(path=path.relative_to(root).as_posix(),before=before,after=sha(path.read_bytes())))
    pairs = m["publication"].all_ten_outcome_identities(root, at)
    paths = m["score"].snapshot_outcomes(root,pairs,at)
    put(root / "FICTIONAL_PARTICIPATION_ADAPTER.json", dict(notice=NOTICE,observed_at=m["rel"].stamp(at),
        claim="SUPPORTED_SAVED_CACHE_ADAPTER_NOT_UPSTREAM_INGESTION",changes=changes,
        receipts=[p.relative_to(root).as_posix() for p in paths]))


def assert_local_tree(root, ref, tree):
    if git(root, "rev-parse", ref + "^{tree}") != tree:
        raise RuntimeError("Fictional archive commit/tree mismatch")


REFERENCE_CONTEXT_IDS = ['0183e948ab4360a97e8eb02b9fddbad17c6cc11fbf2fdd7d98d0cce191b1994d', '02515da245258676e12ce48f384a33a09b2c572a5a7e5071b5fa584a55e7fb77', '038a965fa85d8eef70c86dfe84c82ad71da117138ba89bdd10dd3c703f48857a', '03c2a3ed953c54b8d52d9cb998af69e0b3ddb26f7bc87b6638c615e0ecf7d5ae', '03d4267f2f291b91f48a208b4fda6f984440de51cbe37a96d0c9812aa36f942f', '05e5c8f4a81b9c0b0cd23eb3443a3de6f65e4e304c95d9e513e4a55422719fd4', '08f5075e23fb90d09636c2f6d466502d036cb5c8d7c27e83b9688aecd5a1837b', '0ab48ecc68cfdbc387817e48beb10f238505faf94f0994bacb3077f470265083', '0b205690db797f398230ec3554765fde8bcdc8817cec76bb067808f5313c2cf7', '0c63e02505d61b76d27a9fb34765637824d30aa8de05d6f80942203d684f650d', '1a7255ca0058c854cf020eb02cf8d78990f864f53f179a8087d14955594f0d12', '1ff2858e75d9b4f82203e89fe17ed4b8078f65ec28b7f028f19930bf8d8d69c3', '221092c9e6a68e65e6247af9df0cc488915e9c67c9a53028b86e21fb2db5cf2e', '22cdce400b2bf684380ec11052f617325e549e7fda08d3eef0200b9012203e6d', '29bf6d7e9385cb47f114ed9cfd8f3b6d3e197244cdeb55a5334f31bcb3851921', '2cb1620c2f51651c962f146b0384591f04dc8edcd49cc663b4b9566ea91dfa68', '2f494b34574ea74fc479f8505578e8612acc5979e4c6d7f93d8d0f070db6edf3', '3044a32a344d888607afddeee4580a22f588e751f6175f3111a64a63f595eb3d', '3101c09f6e7a0eb35906ae27aef1c817fe1c2265590a830eee9774d20423603f', '31edbe9d739e106429c404f7d8f3dc9b11366d096aa59c77b5a4136c9d8c2e11', '37e6b8abffd03d23881dd8428fcfc2668475fa13c25b7dbf68e4bc09229ee0b6', '3864b4185932a5cdef2c2888075555ede1c3c1e9029abc4eb5685fdb41e31c6c', '38abb10ec32c83855e74e2e8ecf723ab14975cba121227c8ccd2fcad0189e894', '38b6f786ea8b5ef2d42d7094281ab023bf76cd1b7838f6e95184a221ede6afd5', '395f4013843e898f3a01a22170a281fce8d28acd6d8206e353277d9fc1b65d34', '39bffb1552c0c983f38d5e11f54289da3f745bf92951108343d0d102b2ba93a6', '3a257b28d922250c0b0774513524a996837a4f76a2926aed24f2dddce9070abe', '3cb571fb423837c909dc35a4bb567c495997988d310eafa42daf4cd65c5ef889', '43c792be68164e97b2e834b7fe061027e74e1a8c705efa93a2673d5a56658bf9', '48d6bcdd6e29ce6adfe2472a2cb70fba204720f16fd1912a77265a93e5145459', '4e4015571ceb5ba47f8b49dbbf461659311823f1c585107cdf76329a3985555f', '515abf81825732f1ec186552eca4faed21302fa5df44891918d0e38107e882c3', '570e837b894327c7152d80ca8fba6e4c2754ca77d579c6809c372a3ac72c2318', '5eb9b8b124977bbb67946a6871e7f110aab672233bb08828629271a78e334de1', '63a28e68aa08a60bd4722a177f7d484de57bda6a4b76a4104ccb9201c388b2fa', '6eb049bb88974849e084d03bc4f3ec10780fe778cf9f9b53dfbb801ab888a999', '7232f81ade6a0df8b4162d886a94d6b16e06b3ad68c776f372b05319909bb086', '7553197ae8da08da2df904361932638501f258d0ce9ad36a1878650600a4426b', '78a980057ad617dd38eb658229a66da41f45b75440b64d635a1536bd560a90da', '79f39e49a85aecfa0773fa4112d5c2dd926f83a6495c80e70b3de60b4c7b9eb5', '7de5a7445f332ce7e354c357a82ea7150122053bcdd53f71da957cd852a84b9d', '7eb6d7503cd05a3b59abbd89be6ee73b69852f09e4bff395bc76fedf4aecee2b', '851d54d6fde7390308a492db1a329ad5393623f5768bcb6164fd7566a605f6b5', '875605da910d5b03efbf9835605d75797e63d3efe26946487f15cebbba794197', '88f703e4092cb5e1022eb5cc199b333ba8a9aceebe8efbfdcfccaab30107b3ca', '8a0fe565e4d0d8a8cf5b92c5b91fb79b7559eaf94535e2017708b1f3f86a802f', '8fa40967d7d42c74159a58eeaa385e9efcf4b8b439a6f49ec63516604f4cb5d9', '91202aec9c025cac998f0b33f819c6bbc899b37c371ac9869da07c75b10f200c', '9302004f06fddd32c69dc5e7226361cdd9986c07ce85dc6f5a9e24f1c13ba25e', '98183ce290bae25ddaca15ceab54c758020faa9e3bc0ff15eff0a9542548b45c', '9a203dfa424fe6ca2d6593d5cb3cb9d8a6ca8bf06bd9b551bf8d50d42dff7f58', '9b02fd012c002004f2a718917eac49c24073e7cb77872930e28f5af88c5b663f', 'a35894d27c59d2646d98e56dcf33bbfd4aed15efb910dc418f2c818f955bb882', 'a8ba1015c089699ed0cc694e39c61e9d3045569ca90535ba2a1573006e8a3497', 'a9848fdad562636e207d9c75e5cfc57fdebbee209627ff09865d26aac6a6cc52', 'ac87693372c8c699b35d0c1dea8f09d6121d7d78f912e39c76ca9324725ed77b', 'b120d8ee968cf88289f7fafbe613e8b2b2a98d426f56efb126ae5fb04f3e4566', 'b189c3ea08e853a28dd7402ee42819899c4b47beb184b7c8b6f5773a065d35df', 'b6a789236d8051f36939aa2dc09a5606523caf82998b32963b5c7a08319bc6d8', 'cb86d3674e289e2ec775f54be531325662ee7a250ed88b639013c18e2a33d7d0', 'cf8bac85d035fe37e887a822b98e0665e470c4c863ce21141c2c4e42d7da46a5', 'd180c49a22916e9c64989450b9f814cd1a3d28215f18557084bd50ba9baa2166', 'd4159d5e1ef971ee6329792d185a5c91ad9d52409184340c282980472b3ef246', 'd5258be20700cb0d9e0d18ccef0d298a9c1cad3252b52478089f62fd97b99c47', 'dab73e07b8dafb40c5220dcaeea23f9b0f7b47fc4a1958a968213fa1a3507d58', 'e000c30abb7b5cf400ae7b1393fc51f82ca26286e516adc3c2eb907642276e13', 'eb479076bfbe88b7857293387cc59d6039ed9efb7f207f65d267c1059932cbc0', 'ebac7df9fd88b01579391ccbdf53e7387de45257e336aca08b9ecc4fe4efe728', 'ed7fa607e1c7aed32eeeecd69cb6daeb836147f75d9957c4299a63007c333abe', 'eeac2da5d457d8f618f0b1d0d3ef69cdea7e8670fbf7e9a22a370f8b41b87a00', 'ef38df88304c817f6549947470544bcc66e47e5dfbdd6da823658dbbfe55b09b', 'efcc24bb959710c520279870aa944bbc8fb33832f32a4db1e880e81bdab6a354', 'f15f459cc224806265482f431d26844ec769851d7dc1f188d6d4a3538f8f9d0d', 'f342e76bf5fd10b4424faffbd0587c399bdd984892c46bec920625d77a98e64d', 'ff71ce2e79563477653da0406e4015d5e396530e29c9b7511024349ceb517782']
REFERENCE_INDEX_SHA256 = '01c3bab8ebef9c106eff7a60d356b4732ee899086ff89403aa0ab640d62733f7'

ENVELOPE = dict(rows=18700, groups=5301, outcomes=1537, contexts=75,
    summary_partitions=174, row_chunks=75, native=277, offer=25, outcome_receipts=49,
    verification=190, complete_generations=24, report_files=3276,
    stored_report_bytes=420938216, row_decoded_bytes=76925861, row_encoded_bytes=19792421,
    summary_decoded_bytes=8464981, summary_encoded_bytes=1116192,
    outcome_decoded_bytes=1321055, outcome_encoded_bytes=139732,
    historical_pack_bytes=374513664, historical_objects=18354)


REQUIRED_SETS=dict(status_counts={'win','loss','push','dnp','pending','unresolved','no_action','not_due'},
    models={'original_sleeper_matchup_baseline','sleeper-matchup-data-integrity-v2','archive_engine_unverified'},
    provenance={'local_pregame_membership_observation','inherited_or_unclocked_archive'},
    checkpoints={'24h','6h','90m','history'}, sources={'all','dk','ours','sleeper','unknown'},
    cohorts={'all_qualifying_leans','top_picks','top_at_all_lean_decision','non_top_at_all_lean_decision'},
    periods={'2026-w04','2026-w05','2026-w06','cumulative'},
    categories={'pass_yd','pass_td','pass_cmp','pass_att','pass_int','rush_yd','rush_att','rec','rec_yd','rush_rec_yd'})

def reference_contexts():
    import itertools
    contexts={}
    for (model,provenance,engine),view,checkpoint,source in itertools.product([
        ('original_sleeper_matchup_baseline','local_pregame_membership_observation','e8e8823f460e074485ee91a0dc1c1cfc43877146c4498ef074d15d2b5a735d07'),
        ('archive_engine_unverified','inherited_or_unclocked_archive',None)],
        ('top_picks','all_qualifying_leans','top_at_all_lean_decision','non_top_at_all_lean_decision'),
        ('history','24h','6h','90m'),('all','dk','ours','sleeper','unknown')):
        d=dict(model_version=model,provenance_class=provenance,engine_sha256=engine,view=view,checkpoint=checkpoint,
            line_source_scope=source,policy_version='phase2-timing-v1',policy_sha256='ad7e14681fee0b4f43683c2b7e358060a261ef3b3f22103c3c558783626e16ea')
        key=sha(encoded(d))
        if key in REFERENCE_CONTEXT_IDS:contexts[key]=d
    if set(contexts)!=set(REFERENCE_CONTEXT_IDS):raise RuntimeError('Incomplete exact reference-context correspondence')
    return contexts


def admission_decisions(metrics):
    numeric={k:(type(metrics.get(k)) is int and metrics[k]>=minimum) for k,minimum in ENVELOPE.items()}
    categorical={k:(isinstance(metrics.get(k),(list,dict)) and values<=set(metrics[k])) for k,values in REQUIRED_SETS.items()}
    categorical.update(outcome_revisions=type(metrics.get('outcome_revisions')) is int and metrics['outcome_revisions']>0,
        original_contexts=metrics.get('missing_reference_contexts')==[],
        recorders_inactive=metrics.get('experimental_recorders_inactive') is True,
        original_schema=metrics.get('verification_schema_inventory',{}).get('matchup-inputs-v2',0)>0,
        corrected_schema=metrics.get('verification_schema_inventory',{}).get('matchup-inputs-v3',0)>0,
        archives=type(metrics.get('archive_dependencies')) is int and metrics['archive_dependencies']>=22,
        scope_schema=all(metrics.get('verification_schema_inventory',{}).get(v,0)>0 for v in (
            'partial-week-input-reproduction-v1','partial-week-completion-v1','partial-scope-data-integrity-v2','partial-completion-data-integrity-v2')),
        original_comparator=metrics.get('corrected_original_comparator_overlap')==0)

    population=metrics.get('latest_scope_classifications')=={'retained_legacy_original_proof_missing':9,'new_pregame_original_inputs_verified':5} and metrics.get('game_states')=={'post':2,'in':7,'pre':5}
    expected={kind:[f'99202606{i:02}' for i in indices] for kind,indices in (
        ('retained_legacy_original_proof_missing',range(9)),('new_pregame_original_inputs_verified',range(9,14)))}
    population=population and metrics.get('qualified_game_ids')==expected and metrics.get('game_state_ids')=={
        'post':expected['retained_legacy_original_proof_missing'][:2],
        'in':expected['retained_legacy_original_proof_missing'][2:],
        'pre':expected['new_pregame_original_inputs_verified']}

    return dict(numeric=numeric,categorical=categorical,all_numeric_pass=all(numeric.values()),categorical_pass=all(categorical.values()),population_pass=population)


def tree_bytes(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())


def inventory(root):
    return {p.relative_to(root).as_posix():sha(p.read_bytes()) for lane in ('data','output','config','pull','tools')
        for p in (root/lane).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def workload(root, m):
    base=root/'output/data/selection-grading'; rel=m['rel']; pub=m['publication']
    pointer=rel.load_json(base/'latest.json')
    summary,rows,outcomes=pub.publication_contents(base,pointer)
    index=rel.load_json(base/pointer['summary']['path'])
    final=rel.load_json(base/pointer['outcomes']['path'])
    parts=index['summary_partitions']; outs=final['periods']; tables=summary['summary']['tables']
    working=rel.load_json(base/'hosting.json')
    checked={}; registry=m['capture']._registry(base,working,_checked=checked)
    # Validate every COMPLETE generation against its source/proof/clock closure.
    for descriptor in registry.values():
        m['capture']._manifest(base,descriptor,root=root,_checked=checked)
    result=dict(rows=len(rows),groups=len(tables),outcomes=len(outcomes),
        group_dimensions=dict(Counter(t['dimension'] for t in tables)),
        contexts=len(index['contexts']),missing_reference_contexts=sorted(set(REFERENCE_CONTEXT_IDS)-set(index['contexts'])),summary_partitions=len(parts),row_chunks=len(pointer['rows']),
        complete_generations=len(registry),archive_dependencies=0,
        report_files=sum(p.is_file() for p in base.rglob('*')),stored_report_bytes=tree_bytes(base),
        status_counts=dict(Counter(r['result'] for r in rows)),
        outcome_status_counts=dict(Counter(r['status'] for r in outcomes)),
        outcome_revisions=sum(bool(r.get('outcome_revision')) for r in rows),
        forecast_known_rows=sum(r.get('raw_projection') is not None and r.get('adjusted_projection') is not None for r in rows),
        no_action_reasons=dict(Counter(r['reason'] for r in rows if r['result']=='no_action')),
        models=sorted({r['model_version'] for r in rows}),
        provenance=sorted({r['provenance_class'] for r in rows}),
        cohorts=sorted({r['view'] for r in tables}),checkpoints=sorted({r['checkpoint'] for r in rows}),
        periods=sorted({r['period'] for r in tables}),sources=sorted({r['line_source_scope'] for r in tables}),
        categories=sorted({r['category'] for r in rows}),
        row_decoded_bytes=sum(d['decoded_bytes'] for d in pointer['rows']),
        row_encoded_bytes=sum(d['encoded_bytes'] for d in pointer['rows']),
        summary_decoded_bytes=sum(d['decoded_bytes'] for d in parts),
        summary_encoded_bytes=sum(d['encoded_bytes'] for d in parts),
        outcome_decoded_bytes=sum(d['decoded_bytes'] for d in outs),
        outcome_encoded_bytes=sum(d['encoded_bytes'] for d in outs),
        pointer_bytes=(base/'latest.json').stat().st_size,
        summary_index_bytes=(base/pointer['summary']['path']).stat().st_size,
        outcome_index_bytes=(base/pointer['outcomes']['path']).stat().st_size,
        public_semantics_sha256=rel.digest(dict(summary=summary,rows=rows,outcomes=outcomes)),
        source_head=git(root,'rev-parse','HEAD'),source_tree=git(root,'rev-parse','HEAD^{tree}'),
        working_tree_bytes=tree_bytes(root),source_object_alternates=(root/'.git/objects/info/alternates').exists())
    for key,lane in [('native','forward'),('offer','offers'),('outcome_receipts','outcomes'),('verification','verification')]:
        result[key]=sum(1 for _ in (root/'data'/lane).rglob('*.json.gz'))
    result['git_objects_before_pack']=dict(line.split(': ',1) for line in git(root,'count-objects','-v').splitlines())
    # No real players/teams/game IDs may enter the fictional working inputs.
    native=[m['ev'].read(p) for p in (root/'data/forward').rglob('*.json.gz')]
    if any(not r['player_id'].startswith('fictional-') or not r['game_id'].startswith('99') for p in native for r in p['rows']):
        raise RuntimeError('Nonfictional input identity')
    completion=m['ev'].read(root/rel.load_json(root/'output/data/health.json')['phase2']['partial_completion_receipt'])
    scope=m['ev'].read(root/completion['scope_receipt'])
    result['latest_scope_classifications']=dict(Counter(g['classification'] for g in scope['game_population']))
    result['game_states']=dict(Counter(g['state'] for g in rel.load_json(root/'output/data/week.json')['games']))
    result['game_state_ids']={state:sorted(g['id'] for g in rel.load_json(root/'output/data/week.json')['games'] if g['state']==state) for state in ('post','in','pre')}
    verification_files=[p for p in (root/'data/verification').rglob('*') if p.is_file()]
    result['verification_receipts_gzip']=result['verification']
    result['verification']=len(verification_files)  # Reference includes 188 receipts + 2 plain metadata files.
    result['verification_schema_inventory']=dict(Counter(
        (m['ev'].read(p) if p.name.endswith('.json.gz') else rel.load_json(p)).get('schema_version','unversioned_metadata')
        for p in verification_files))
    result['primary_evidence_bytes']=sum(tree_bytes(root/'data'/lane) for lane in ('forward','offers','outcomes','verification'))
    selected=[d for d in (working['latest'],working['previous']) if d is not None]
    archive_records=m['capture']._git_archive(root,registry,{k for k,v in registry.items() if v not in selected},_checked=checked)
    result['archive_dependency_inventory']=[dict(report=k,**v) for k,v in sorted(archive_records.items())]
    result['archive_dependencies']=len(result['archive_dependency_inventory'])
    result['context_descriptors']=index['contexts']
    if any(rel.digest(v)!=k for k,v in index['contexts'].items()):raise RuntimeError('Context descriptor identity')
    references=reference_contexts();correspondence=[]
    for key,descriptor in sorted(index['contexts'].items()):
        ref=copy.deepcopy(descriptor)
        if ref['model_version']=='sleeper-matchup-data-integrity-v2':
            ref.update(model_version='original_sleeper_matchup_baseline',engine_sha256='e8e8823f460e074485ee91a0dc1c1cfc43877146c4498ef074d15d2b5a735d07')
        ref_id=rel.digest(ref)
        correspondence.append(dict(fixture_id=key,fixture_descriptor=descriptor,reference_id=ref_id if ref_id in references else None,
            reference_descriptor=references.get(ref_id),changed_fields=[k for k in descriptor if descriptor[k]!=ref[k]]))
    result['context_correspondence']=correspondence
    result['input_schema_inventory']=dict(Counter(m['ev'].read(p).get('schema_version') for p in (root/'data/verification').rglob('*.json.gz') if 'matchup-inputs' in p.as_posix()))
    result['experimental_recorders_inactive']=rel.load_json(root/'config/phase2.json')['experimental_recording_enabled'] is False
    result['frozen_contracts']={g['id']:rel.digest(m['partial'].game_contract(rel.load_json(root/'output/data/week.json'),g['id'])) for g in rel.load_json(root/'output/data/week.json')['games'] if g['state']!='pre'}
    result['qualified_game_ids']={kind:sorted(g['game_id'] for g in scope['game_population'] if g['classification']==kind) for kind in sorted({g['classification'] for g in scope['game_population']})}
    # Real scorecard consumer enforces original-model identity independently of recording flags.
    policy=rel.load_json(root/'config/evaluation-policy.json')
    import data_integrity_v2 as corrected
    with corrected.legacy_source(root) as original_source:
        hashes=rel.engine_hashes(original_source)
    pairs,coverage=m['score'].paired_forecasts(native,policy,hashes)
    original_pairs,_=m['score'].paired_forecasts([r for r in native if r['schema_version']=='baseline-capture-v1'],policy,hashes)
    expected_excluded=sum(len(r['rows']) for r in native if r['schema_version']=='baseline-capture-v2')
    if coverage['excluded'].get('corrected_model_outside_registered_experiment',0)!=expected_excluded:raise RuntimeError('Corrected original-comparator exclusion differs')
    result['corrected_original_comparator_overlap']=0 if pairs==original_pairs else 1
    result['registered_three_target_claim']='ORIGINAL_COMPARATOR_CONSUMER_CHECKED_NO_CORRECTED_OVERLAP'
    return result


def admit(code,root,result,small=False):
    m=bind(root)
    before=inventory(root)
    marker=json.loads((root/'FICTIONAL_ONLY.json').read_text())
    provider=Provider(m,marker['dimensions'],START+timedelta(hours=SEED_HOUR,seconds=5*marker['dimensions']['generations']))
    with external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        metrics=workload(root,m)
        pages=root.parent/'admission-pages'
        if pages.exists(): raise RuntimeError('Fresh admission Pages root required')
        m['capture'].stage_pages(root,pages)
        metrics['staged_bytes']=tree_bytes(pages)
        tar=root.parent/'admission-artifact.tar'
        subprocess.run(['tar','--dereference','--hard-dereference','--directory',str(pages),'-cf',str(tar),'--exclude=.git','--exclude=.github','.'],check=True)
        metrics['uploader_tar_bytes']=tar.stat().st_size
    if inventory(root)!=before: raise RuntimeError('Admission changed retained original bytes')
    # Packing is local representation work; source objects and fictional growth
    # stay separately identified, and no .git tree is offered as fictional data.
    started=time.monotonic();git(root,'gc','--quiet');metrics['git_pack_seconds']=time.monotonic()-started
    metrics['packed_bytes']=sum(p.stat().st_size for p in (root/'.git/objects/pack').glob('*.pack'))
    metrics['git_objects_after_pack']=dict(line.split(': ',1) for line in git(root,'count-objects','-v').splitlines())
    metrics['historical_pack_bytes']=metrics['packed_bytes']
    metrics['historical_objects']=int(metrics['git_objects_after_pack']['in-pack'])
    restart=root.parent/'restart-checkout'
    tick=time.monotonic()
    subprocess.run(['git','clone','--quiet','--no-hardlinks',str(root),str(restart)],check=True)
    git(restart,'remote','set-url','origin','https://github.com/NickNicky19/nicks-expert-nfl-picks.git')
    metrics['clean_checkout_seconds']=time.monotonic()-tick
    metrics['clean_checkout_bytes']=tree_bytes(restart)
    fresh=result.parent/'RESTART.json'
    subprocess.run([sys.executable,__file__,'recheck','--code',str(restart),'--root',str(restart),'--result',str(fresh)],check=True)
    rebuilt=json.loads(fresh.read_text())
    if rebuilt['semantic_sha256']!=metrics['public_semantics_sha256']:raise RuntimeError('Restart semantics changed')
    metrics['cold_restart']='PASS_NEW_PROCESS_NO_SHARED_TRUST'
    comparisons={k:dict(retained=v,fixture=metrics.get(k),meets=(metrics[k]>=v if k in metrics else None)) for k,v in ENVELOPE.items()}
    decisions=admission_decisions(metrics)
    coverage=decisions['categorical_pass']
    physical_match=decisions['all_numeric_pass']
    reference_branch=decisions['population_pass']
    result_data=dict(notice=NOTICE,reviewed_source=BASE,construction_code=git(code,'rev-parse','HEAD'),
        metrics=metrics,comparison=comparisons,required_decisions=decisions,status=('SMOKE_ONLY' if small else 'ADMITTED' if coverage and physical_match and reference_branch else 'NOT_ADMITTED'),
        structural_coverage=coverage,physical_envelope_match=physical_match,reference_qualification_population_match=reference_branch,small=small,
        original_inventory_sha256=sha(encoded(before)),immutable_bytes_unchanged=True,
        limitation='Physical byte differences must be explained; no entropy or duplicate padding may manufacture admission.')
    put(result,result_data)
    return result_data


def correction_declaration(root,m):
    base=root/'output/data/selection-grading';pointer=m['rel'].load_json(base/'latest.json')
    _,rows,outcomes=m['publication'].publication_contents(base,pointer)
    affected=[r for r in rows if r['player_id']=='fictional-00-03' and r['week']==6 and r['category']=='rec' and r['action']=='SELECT']
    if not affected or any(r['actual']!=3 for r in affected):raise RuntimeError('Seed does not have predeclared revision1')
    expected=[]
    for r in affected:
        grade='push' if r['line']==8 else 'win' if (8>r['line'])==(r['side']=='over') else 'loss'
        expected.append(dict(decision_key=r['decision_key'],cohort=r['cohort'],previous=r['result'],expected=grade,line=r['line'],side=r['side']))
    if not any(r['previous']!=r['expected'] for r in expected):raise RuntimeError('Predeclared material revision has no grade delta')
    return dict(revision_before=SEED_REVISION,revision_after=NEXT_REVISION,player_id='fictional-00-03',category='rec',before=3,after=8,expected=expected),rows,outcomes

def check_correction(root,m,declaration,old_rows,old_outcomes):
    base=root/'output/data/selection-grading';pointer=m['rel'].load_json(base/'latest.json')
    _,rows,outcomes=m['publication'].publication_contents(base,pointer)
    def key(r):return r['decision_key'],r['cohort']
    now={key(r):r for r in rows}
    if len(now)!=len(rows):raise RuntimeError('Ambiguous decision keys')
    expected={(r['decision_key'],r['cohort']):r for r in declaration['expected']}
    columns=('actual','result','raw_projection','adjusted_projection','line','side','game_id','player_id','category','season','week')
    changed=[]
    for before in old_rows:
        k=key(before)
        if k not in now:raise RuntimeError('Material revision removed prior decision')
        after=now[k]
        if k in expected:
            if after['actual']!=8 or after['result']!=expected[k]['expected']:raise RuntimeError('Material correction grade mismatch')
            if any(before[c]!=after[c] for c in columns if c not in ('actual','result')):raise RuntimeError('Frozen contract changed')
            changed.append(k)
        elif any(before[c]!=after[c] for c in columns):raise RuntimeError('Unrelated decision/grade changed')
    return dict(status='PASS_ACTUAL_SAVED_CONSUMERS',changed_decisions=len(changed),expected=declaration,
        original_outcome_count=len(old_outcomes),new_outcome_count=len(outcomes))


def sample(code,root,result):
    """One cold isolated connected update; caller supplies whole-job stages."""
    m=bind(root); marker=json.loads((root/'FICTIONAL_ONLY.json').read_text())
    if marker['notice']!=NOTICE: raise RuntimeError('Not the reviewed fictional fixture')
    provider=Provider(m,marker['dimensions'],START+timedelta(hours=SEED_HOUR,seconds=SAMPLE_SECONDS));provider.revision=NEXT_REVISION
    r=dict(notice=NOTICE,stages={},status='RUNNING')
    def stage(name,action):
        start=time.monotonic()
        try:return action()
        finally:r['stages'][name]=time.monotonic()-start;put(result,r)
    with external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        declaration,old_rows,old_outcomes=correction_declaration(root,m)
        before_board=m['rel'].load_json(root/'output/data/week.json')
        before_contracts={g['id']:m['partial'].game_contract(before_board,g['id']) for g in before_board['games']}
        put(result.parent/'MATERIAL_CORRECTION.predeclared.json',declaration)
        before_inventory={p.relative_to(root).as_posix():sha(p.read_bytes()) for lane in ('forward','offers','outcomes','verification') for p in (root/'data'/lane).rglob('*') if p.is_file()}
        stage('preserve_existing_grading',lambda:subprocess.run([sys.executable,str(root/'tools/preserve_legacy.py')],cwd=root,check=True))
        stage('recorded_build_capture_report',lambda:m['capture'].run_capture(root,build_first=True))
        stage('explicit_generation_validation',lambda:m['capture'].validate_generation(root))
        r['material_correction']=check_correction(root,m,declaration,old_rows,old_outcomes)
        after_board=m['rel'].load_json(root/'output/data/week.json')
        if before_contracts!={g['id']:m['partial'].game_contract(after_board,g['id']) for g in after_board['games']}:raise RuntimeError('Outcome correction altered frozen forecast/membership contracts')
        if any(not (root/name).is_file() or sha((root/name).read_bytes())!=digest for name,digest in before_inventory.items()):raise RuntimeError('Prior original evidence changed')
        stage('local_git_commit',lambda:commit(root))
        pages=root.parent/'sample-pages'
        stage('pages_staging_archive_checks',lambda:m['capture'].stage_pages(root,pages))
        stage('uploader_tar',lambda:subprocess.run(['tar','--dereference','--hard-dereference','--directory',str(pages),'-cvf',str(root.parent/'sample-artifact.tar'),'--exclude=.git','--exclude=.github','.'],check=True,stdout=subprocess.DEVNULL))
    r.update(status='PASS_DATAFLOW_ONLY_NOT_WHOLE_JOB',fake_http_responses=provider.calls,provider_requests=0,
        self_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        child_max_rss_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    put(result,r)


def required_checks(code):
    return [(sys.executable,'-m','unittest','discover','-s','tests','-v'),
        (sys.executable,'-m','compileall','-q','pull','tools'),
        ('node','--check','output/app.js'),('node','--check','output/reliability-ui.js'),
        ('node','tests/test-ui.cjs'),('node','tests/test-about.cjs'),('git','diff','--check')]


def job(code,root,result,sample_number):
    """Future hosted-only job entry; not invoked during local preparation."""
    if os.environ.get('GITHUB_RUN_ATTEMPT')!='1' or sample_number not in (1,2,3):
        raise RuntimeError('Exactly three first-attempt samples required')
    if os.environ.get('GITHUB_SHA')!=git(code,'rev-parse','HEAD'):
        raise RuntimeError('Actual checkout differs from event source')
    if os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch': raise RuntimeError('Manual diagnostic only')
    identity=source_check(code)
    if os.environ.get('DIAGNOSTIC_RESOURCE_BACKEND')!='root-supervised-cgroup-v1':raise RuntimeError('Hosted resource preflight required')
    if Path(__file__).resolve()!=code/'tools/operating_diagnostic.py':raise RuntimeError('Job must use actual installed harness')
    for name in ('GH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY','OPENAI_API_KEY'):
        if os.environ.get(name):raise RuntimeError('Forbidden injected credential name')
    expected=Path(os.environ['RUNNER_TEMP']).resolve()/('nfl-operating-'+str(sample_number))
    if root!=expected/'fixture' or result!=expected/'RESULT.json' or root.exists():
        raise RuntimeError('Only a new exact runner-local fixture destination is allowed')
    if os.environ.get('CAMPAIGN_ID')!=CAMPAIGN or os.environ.get('GITHUB_ACTOR_ID')!='208912933':
        raise RuntimeError('Wrong authenticated campaign actor/identity')
    result.parent.mkdir(parents=True,exist_ok=True)
    require_offline()
    root.parent.mkdir(parents=True,exist_ok=True)
    result.parent.mkdir(parents=True,exist_ok=True)
    monitor=Resources(root.parent,critical_paths=[code,Path(__file__).parent,Path('/tmp'),Path.home()]);monitor.start()
    stages={};start=time.monotonic();status='FAIL';failure=None
    def stage(name,command):
        tick=time.monotonic()
        try:bounded(command,code,result.parent/(name+'.log'),max(.01,1200-(time.monotonic()-start)))
        finally:stages[name]=dict(start=tick-start,end=time.monotonic()-start,seconds=time.monotonic()-tick)
    try:
        stage('seed_retrieval',[sys.executable,__file__,'retrieve','--code',str(code),'--root',str(root)])
        stage('seed_restoration',[sys.executable,__file__,'restore','--code',str(code),'--root',str(root)])
        stage('workload_admission',[sys.executable,__file__,'admit','--code',str(code),'--root',str(root),'--result',str(result.parent/'admission.json')])
        if json.loads((result.parent/'admission.json').read_text())['status']!='ADMITTED':
            raise RuntimeError('Fixture not admitted; no timed sample substitution')
        for number,command in enumerate(required_checks(code)):
            stage('required_check_'+str(number+1),list(command))
        stage('connected_update_and_packaging',[sys.executable,__file__,'sample','--code',str(code),'--root',str(root),'--result',str(result.parent/'dataflow.json')])
        final_identity=source_check(code)
        if final_identity!=identity:raise RuntimeError('Execution source changed during job')
        status='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING'
    except BaseException as error:
        failure=type(error).__name__;raise
    finally:
        tick=time.monotonic()
        # Only generated job-local work is cleaned; checkout/evidence elsewhere are untouched.
        if root.exists(): shutil.rmtree(root)
        for name in ('retrieved-seed','admission-pages','sample-pages','restart-checkout','restart-pages'):
            q=root.parent/name
            if q.exists():shutil.rmtree(q)
        for name in ('admission-artifact.tar','sample-artifact.tar'):
            (root.parent/name).unlink(missing_ok=True)
        resources=monitor.finish()
        stages['cleanup']=dict(start=tick-start,end=time.monotonic()-start,seconds=time.monotonic()-tick)
        import importlib.metadata
        versions={name:importlib.metadata.version(name) for name in ('requests','urllib3','certifi','charset-normalizer','idna')}
        versions.update(python=sys.version,node=subprocess.check_output(['node','--version'],text=True).strip())
        put(result,dict(status=status,failure_class=failure,sample=sample_number,campaign=CAMPAIGN,
            run_id=int(os.environ['GITHUB_RUN_ID']),run_attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
            source=git(code,'rev-parse','HEAD'),source_tree=identity['tree'],source_manifest_sha256=identity['source_manifest_sha256'],
            harness_sha256=sha(Path(__file__).read_bytes()),seed_manifest_sha256=os.environ.get('SEED_MANIFEST_SHA256'),
            dependency_hashes={p.name:sha(p.read_bytes()) for p in Path(__file__).parent.glob('diagnostic_*.py')},versions=versions,stages=stages,
            harness_wall_seconds=time.monotonic()-start,planning_seconds=960,timeout_seconds=1200,resources=resources,
            excludes=['queue','earlier_setup','later_checkout_post_actions','live_provider_network','remote_push','artifact_upload','Pages_deployment'],
            whole_job_verdict='PENDING_ACTIONS_COMPLETED_AT_AND_RESOURCE_REVIEW'))
        print(json.dumps(json.loads(result.read_text()),sort_keys=True),flush=True)

def source_check(code):
    head=git(code,'rev-parse','HEAD')
    git(code,'merge-base','--is-ancestor',BASE,head)
    allowed={'tools/operating_diagnostic.py','tools/diagnostic_network_guard.py','tools/diagnostic_seed.py','tools/diagnostic_resources.py','.github/workflows/reliability-tests.yml'}
    changed=set(git(code,'diff','--name-only',BASE,head).splitlines())
    if not changed<=allowed:raise RuntimeError('Unapproved diagnostic source delta')
    if git(code,'status','--porcelain','--untracked-files=no'):raise RuntimeError('Dirty source checkout')
    files={}
    for lane in ('pull','tools','config'):
        for item in (code/lane).rglob('*'):
            if item.is_file() and '__pycache__' not in item.parts and item.suffix!='.pyc':
                files[item.relative_to(code).as_posix()]=sha(item.read_bytes())
    helper=files['tools/data_integrity_v2.py']
    if helper!='7fb3ed03ff5b22dbe1aa9a0db4ae830fe540ace732e0a0199b0e82c93533cf49':
        raise RuntimeError('Changed reviewed validator helper')
    return dict(head=head,tree=git(code,'rev-parse','HEAD^{tree}'),source_manifest_sha256=sha(encoded(files)),files=files)


def recheck(root,result):
    """New-process, copied-checkout proof/publication/archive reconstruction."""
    m=bind(root);marker=json.loads((root/'FICTIONAL_ONLY.json').read_text())
    provider=Provider(m,marker['dimensions'],START+timedelta(hours=SEED_HOUR,seconds=5*marker['dimensions']['generations']))
    with external(m,provider,root),patch.object(m['capture'],'_public_archive_commit',side_effect=lambda ref,tree:assert_local_tree(root,ref,tree)):
        generation=m['capture'].validate_generation(root)
        base=root/'output/data/selection-grading'
        pointer=m['rel'].load_json(base/'latest.json')
        summary,rows,outcomes=m['publication'].publication_contents(base,pointer)
        m['capture'].stage_pages(root,root.parent/'restart-pages')
    put(result,dict(status='PASS_SAVED_RECONSTRUCTION',generation=generation['generation_sha256'],
        semantic_sha256=m['rel'].digest(dict(summary=summary,rows=rows,outcomes=outcomes)),source=git(root,'rev-parse','HEAD')))


def require_offline():
    import errno
    state=Path('/proc/self/status').read_text()
    if 'NoNewPrivs:\t1' not in state or 'Seccomp:\t2' not in state:
        raise RuntimeError('Required inherited kernel isolation absent')
    try:
        channel=socket.socket();channel.close()
    except OSError as error:
        if error.errno!=errno.EPERM:raise
    else:raise RuntimeError('Socket creation was not denied')


def assess(metadata,result):
    """Assess actual post-completion API records; never infer PASS from exit alone.

    authorization is the separately approved invocation record, not a job's own
    assertion. The owner must supply independently fetched run/jobs/results.
    API second-resolution bounds are conservative; no near-boundary tolerance.
    """
    import math
    import re
    value=json.loads(metadata.read_text());run=value['run'];jobs=value['jobs']
    approval=value['authorization'];seen={};samples=[];intervals=[];job_ids=set()
    expected=dict(campaign=CAMPAIGN,run_id=run['id'],head_sha=run['head_sha'],
        branch='upgrade/phase2-reproducible-comparison',workflow_path='.github/workflows/reliability-tests.yml',
        actor_id=208912933,attempt=1,diagnostic_mode='campaign',
        seed_manifest_sha256=value['seed_manifest_sha256'],harness_sha256=value['harness_sha256'],
        dependency_hashes=value['dependency_hashes'],source_manifest_sha256=value['source_manifest_sha256'])
    if approval!=expected:raise RuntimeError('Invocation approval/API identity mismatch')
    if (run['event']!='workflow_dispatch' or run['run_attempt']!=1 or run['status']!='completed'
        or run['head_branch']!=expected['branch'] or run['actor']['id']!=expected['actor_id']
        or run['path']!=expected['workflow_path'] or not re.fullmatch('[0-9a-f]{40}',run['head_sha'])):
        raise RuntimeError('Wrong campaign event/attempt/source/actor/workflow')
    def instant(text):
        at=datetime.fromisoformat(text.replace('Z','+00:00'))
        if at.tzinfo is None:raise RuntimeError('Clock lacks timezone')
        return at
    def number(v):
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:
            raise RuntimeError('Invalid duration')
        return v
    created=instant(run['created_at']);started=instant(run['run_started_at'])
    if started<created:raise RuntimeError('Negative queue interval')
    required={'seed_retrieval','seed_restoration','workload_admission','connected_update_and_packaging','cleanup'}
    required.update('required_check_'+str(n) for n in range(1,8))
    if set(value['samples'])!={'1','2','3'}:raise RuntimeError('Exactly three result slots required')
    for job in jobs:
        match=re.fullmatch(r'Operating sample ([123])',job['name'])
        if not match:
            if job['conclusion']!='skipped':raise RuntimeError('Unexpected competing job')
            continue
        n=int(match[1])
        if n in seen:raise RuntimeError('Duplicate sample')
        seen[n]=True
        if job['id'] in job_ids:raise RuntimeError('Duplicate actual job ID')
        job_ids.add(job['id'])
        if type(job.get('run_attempt')) is not int or job['run_attempt']!=approval['attempt']:
            raise RuntimeError('Job attempt mismatch')
        if job['run_id']!=run['id'] or job['head_sha']!=run['head_sha']:
            raise RuntimeError('Job/run checkout mismatch')
        if job['status']!='completed' or not job.get('completed_at'):
            raise RuntimeError('Whole-job timestamps pending')
        begin=instant(job['started_at']);end=instant(job['completed_at'])
        if begin<started or end<begin:raise RuntimeError('Incoherent job clocks')
        intervals.append((begin,end,n))
        wall=(end-begin).total_seconds();report=value['samples'][str(n)]
        if not isinstance(report,dict):raise RuntimeError('Missing sample result')
        if report.get('run_id')!=run['id'] or type(report.get('run_attempt')) is not int or report['run_attempt']!=1:
            raise RuntimeError('Result/run/attempt mismatch')
        if type(report.get('sample')) is not int or report.get('source')!=run['head_sha'] or report.get('campaign')!=CAMPAIGN or report.get('sample')!=n:
            raise RuntimeError('Sample/source/campaign identity mismatch')
        elapsed=number(report['harness_wall_seconds']);stages=report['stages']
        if set(stages)!=required:raise RuntimeError('Incomplete stage boundary')
        last=0.;summed=0.
        for stage in sorted(stages.values(),key=lambda s:s['start']):
            a,b,d=(number(stage[k]) for k in ('start','end','seconds'))
            if b<a or a<last or b>elapsed or abs((b-a)-d)>.001:
                raise RuntimeError('Overlapping or incoherent exclusive stages')
            last=b;summed+=d
        if elapsed>wall+2:raise RuntimeError('Harness duration exceeds whole-job interval')
        complete=report.get('status')=='LOCAL_BOUNDARY_COMPLETE_EXTERNAL_JOB_TIMESTAMPS_PENDING'
        success=complete and job['conclusion']=='success'
        # Integer API endpoints can each differ by <1s; use the upper bound.
        upper=wall+2;lower=max(0,wall-2)
        planning='PASS' if success and upper<=960 else 'FAIL'
        measured=value.get('resource_reports',{}).get(str(n),{})
        bound=measured.get('run_id')==run['id'] and measured.get('sample')==n and measured.get('source')==run['head_sha'] and measured.get('harness_sha256')==report.get('harness_sha256') and measured.get('seed_manifest_sha256')==report.get('seed_manifest_sha256')
        from diagnostic_resources import report_verdict
        resources=report_verdict(measured) if bound else 'UNKNOWN_RESOURCE_IDENTITY_OR_TREE'
        if report.get('seed_manifest_sha256')!=value['seed_manifest_sha256'] or report.get('harness_sha256')!=value['harness_sha256'] or report.get('dependency_hashes')!=value['dependency_hashes'] or report.get('source_manifest_sha256')!=value['source_manifest_sha256']:raise RuntimeError('Seed/harness/dependency identity differs from approved campaign')
        wanted=dict(requests='2.34.2',urllib3='2.8.0',certifi='2026.7.22',**{'charset-normalizer':'3.5.2','idna':'3.20'})
        actual_versions=report.get('versions',{})
        if any(actual_versions.get(k)!=v for k,v in wanted.items()) or actual_versions.get('python','').split()[0:1]!=['3.12.15'] or actual_versions.get('node')!='v22.23.3':raise RuntimeError('Runtime/dependency version mismatch')
        samples.append(dict(sample=n,job_id=job['id'],conclusion=job['conclusion'],
            complete_harness=complete,whole_job_seconds=wall,whole_job_upper_seconds=upper,
            whole_job_lower_seconds=lower,planning=planning,resources=resources,
            accounted_harness_seconds=elapsed,exclusive_stage_seconds=summed,
            unassigned_inside_harness_seconds=elapsed-summed,
            outside_harness_residual_seconds=wall-elapsed,
            residual_uncertainty_seconds=2))
    if set(seen)!={1,2,3}:raise RuntimeError('Exactly three samples required')
    intervals.sort()
    if [n for a,b,n in intervals]!=[1,2,3] or any(intervals[i][0]<intervals[i-1][1] for i in (1,2)):
        raise RuntimeError('Samples not cold serial in approved order')
    put(result,dict(campaign=CAMPAIGN,source=run['head_sha'],run_id=run['id'],
        samples=sorted(samples,key=lambda x:x['sample']),initial_queue_seconds=(started-created).total_seconds(),
        matrix_wait='Separate; per-job queue timestamp not supplied by this API',
        operating='PASS_OFFLINE_COMPUTE_ONLY' if run['conclusion']=='success' and all(
            x['planning']=='PASS' and x['resources']=='PASS' for x in samples) else 'NOT_QUALIFIED',
        excludes=['live_providers','remote_write','upload','Pages','public_cache','season_long_operation']))


class Resources:
    """Sampled process-tree aggregates; never mislabel historical kernel peaks."""
    def __init__(self,path,critical_paths=()):
        import threading
        self.path=path;self.critical_paths=[path,*critical_paths];self.monitor_error=None;self.stop_event=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
        self.data=dict(samples=0,max_tree_rss_bytes=0,max_tree_pss_bytes=0,max_cgroup_current=0,
            min_free_disk_bytes=None,sample_interval_seconds=.25,aggregate_peak='SAMPLED_NOT_EXACT',
            initial=self.read_limits())
    def read_limits(self):
        from diagnostic_resources import resolve,critical
        try:
            mount,c,ancestors=resolve();scope='RESOLVED_OBSERVED_NOT_ATTRIBUTABLE'
        except (OSError,ValueError,RuntimeError):c=None;scope='UNRESOLVED_ANCESTORS_NO_TRUST'
        def read(name):
            if c is None:return None
            try:return (c/name).read_text().strip()
            except OSError:return None
        return dict(memory_limit=read('memory.max'),memory_current=read('memory.current'),
            historical_memory_peak=read('memory.peak'),events=read('memory.events'),cpu_quota=read('cpu.max'),
            scope=scope,filesystems=critical(self.critical_paths),filesystem=shutil.disk_usage(self.path)._asdict())
    def loop(self):
        try:self._loop()
        except BaseException as error:self.monitor_error=type(error).__name__
    def _loop(self):
        while not self.stop_event.is_set():
            parents={}
            for entry in Path('/proc').iterdir():
                if entry.name.isdigit():
                    try:parents[int(entry.name)]=int((entry/'stat').read_text().rsplit(')',1)[1].split()[1])
                    except (OSError,ValueError,IndexError):pass
            ids={os.getpid()}
            for unused in range(len(parents)):
                added={pid for pid,ppid in parents.items() if ppid in ids}-ids
                if not added:break
                ids.update(added)
            rss=pss=0
            for pid in ids:
                try:
                    status=(Path('/proc')/str(pid)/'status').read_text().splitlines()
                    rss+=next((int(x.split()[1])*1024 for x in status if x.startswith('VmRSS:')),0)
                    roll=(Path('/proc')/str(pid)/'smaps_rollup').read_text().splitlines()
                    pss+=next((int(x.split()[1])*1024 for x in roll if x.startswith('Pss:')),0)
                except (OSError,ValueError):pass
            limits=self.read_limits();free=limits['filesystem']['free']
            self.data['samples']+=1
            self.data['max_tree_rss_bytes']=max(rss,self.data['max_tree_rss_bytes'])
            self.data['max_tree_pss_bytes']=max(pss,self.data['max_tree_pss_bytes'])
            try:self.data['max_cgroup_current']=max(int(limits['memory_current']),self.data['max_cgroup_current'])
            except (TypeError,ValueError):pass
            self.data['min_free_disk_bytes']=min(free,self.data['min_free_disk_bytes'] or free)
            self.stop_event.wait(.25)
    def start(self):self.thread.start()
    def finish(self):
        self.stop_event.set();self.thread.join(3);self.data['final']=self.read_limits()
        self.data['self_peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        self.data['largest_child_peak_rss_kib']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        self.data['headroom_policy']=dict(minimum_free_bytes=2*1024**3,minimum_free_fraction=.20,
            no_new_oom_events=True,attributable_aggregate_peak_required_for_PASS=True)
        failures=[]
        if self.monitor_error or self.thread.is_alive():failures.append('MONITOR_FAILURE')
        for fs in self.data['final']['filesystems'].values():
            if fs['free']<max(2*1024**3,.2*fs['total']):failures.append('CRITICAL_FILESYSTEM_HEADROOM')
        def events(text):return dict(line.split() for line in (text or '').splitlines())
        initial_events=events(self.data['initial']['events']);final_events=events(self.data['final']['events'])
        deltas={k:int(v)-int(initial_events.get(k,0)) for k,v in final_events.items()}
        self.data['event_deltas']=deltas
        if any(deltas.get(k,0)>0 for k in ('oom','oom_kill','oom_group_kill')):failures.append('OOM')
        total=self.data['initial']['filesystem']['total']
        if (self.data['min_free_disk_bytes'] or 0)<max(2*1024**3,.2*total):failures.append('DISK_HEADROOM')
        try:
            limit=int(self.data['initial']['memory_limit'])
            if limit-self.data['max_cgroup_current']<max(2*1024**3,.2*limit):failures.append('MEMORY_HEADROOM')
        except (TypeError,ValueError):pass
        self.data['observed_headroom_failures']=failures
        self.data['resource_verdict']='FAIL_'+','.join(failures) if failures else 'UNKNOWN_NO_ATTRIBUTABLE_KERNEL_PEAK'
        put(self.path/'RESOURCES.json',self.data)
        return self.data


def bounded(command,cwd,log,timeout):
    import signal
    with log.open('wb') as output:
        process=subprocess.Popen(command,cwd=cwd,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            rc=process.wait(timeout=timeout)
        except BaseException:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
            raise
    if rc:raise subprocess.CalledProcessError(rc,command)


def prepare(code,root,result,small):
    """ONE bounded local construction/admission; not a performance campaign."""
    require_offline()
    if root.exists():raise RuntimeError("New preparation root required")
    root.parent.mkdir(parents=True,exist_ok=True)
    result.parent.mkdir(parents=True,exist_ok=True)
    frozen_harness=sha(Path(__file__).read_bytes())
    monitor=Resources(root.parent,critical_paths=[code,Path(__file__).parent,Path('/tmp'),Path.home()]);monitor.start();start=time.monotonic();stages={};status='FAIL'
    # Local preparation ceiling, not a change to the hosted 1,200-second limit.
    ceiling=1800
    try:
        for name,action,extra in [('construction','fixture',[]),('admission','admit',['--result',str(result.parent/'ADMISSION.json')])]:
            tick=time.monotonic()
            try:bounded([sys.executable,__file__,action,'--code',str(code),'--root',str(root),*extra,*(['--small'] if small else [])],code,result.parent/(name+'.log'),max(.01,ceiling-(tick-start)))
            finally:stages[name]=dict(start=tick-start,end=time.monotonic()-start,seconds=time.monotonic()-tick)
        admission=json.loads((result.parent/'ADMISSION.json').read_text())
        status='SMOKE_PASS_NOT_ADMITTED' if small else 'PREPARATION_COMPLETE' if admission['status']=='ADMITTED' else 'WORKLOAD_NOT_ADMITTED'
    except BaseException as error:
        status='BOUNDED_PREPARATION_FAILED_'+type(error).__name__
        raise
    finally:
        resources=monitor.finish()
        if sha(Path(__file__).read_bytes())!=frozen_harness:status='INVALIDATED_HARNESS_CHANGED'
        put(result,dict(notice=NOTICE,status=status,reviewed_source=BASE,code=git(code,'rev-parse','HEAD'),
            harness_sha256_at_start=frozen_harness,harness_sha256_at_end=sha(Path(__file__).read_bytes()),small=small,exclusive_stages=stages,
            total_seconds=time.monotonic()-start,ceiling_seconds=ceiling,
            resources=resources,hosted_qualification=False,artifacts_preserved=True))


def retrieve_seed(code,root):
    import diagnostic_seed as seed
    ref=os.environ['SEED_COMMIT']
    if len(ref)!=40 or any(c not in '0123456789abcdef' for c in ref):raise RuntimeError('Exact approved seed commit required')
    oid=git(code,'rev-parse',ref+':seed/TRANSPORT.json')
    if git(code,'cat-file','-t',oid)!='blob' or int(git(code,'cat-file','-s',oid))>1024**2:raise RuntimeError('Transport descriptor bound')
    raw=subprocess.check_output(['git','-C',str(code),'cat-file','blob',oid])
    if sha(raw)!=os.environ['SEED_TRANSPORT_SHA256']:raise RuntimeError('Approved transport contract mismatch')
    seed.retrieve(code,root.parent/'retrieved-seed',json.loads(raw),os.environ['SEED_COMMIT'])

def restore_seed(code,root):
    import diagnostic_seed as seed
    manifest=seed.restore(root.parent/'retrieved-seed',root,os.environ['SEED_MANIFEST_SHA256'])
    if not manifest['full_admitted'] or manifest['application_source']!=BASE:raise RuntimeError('Not the admitted source-bound full seed')

    # Installed harness source is distinct from immutable construction source.
    actual=git(code,'rev-parse','HEAD')
    git(root,'fetch','--quiet',str(code),actual)
    git(root,'update-ref','refs/diagnostic/execution-source',actual)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("legacy", "modern", "fixture", "sample", "admit", "job", "prepare", "recheck", "assess", "retrieve", "restore"))
    p.add_argument("--code", type=Path, required=True)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--small", action="store_true")
    p.add_argument("--result", type=Path)
    p.add_argument("--sample-number",type=int)
    p.add_argument("--metadata",type=Path)
    a = p.parse_args()
    if a.action == "legacy":
        legacy_seed(a.code.resolve(), a.root.resolve(), SMALL if a.small else FULL)
    elif a.action == "fixture":
        fixture(a.code.resolve(), a.root.resolve(), a.small)
    elif a.action == "modern":
        modern_seed(a.root.resolve(), SMALL if a.small else FULL)
    elif a.action == "sample":
        sample(a.code.resolve(), a.root.resolve(), a.result)
    elif a.action == "admit":
        outcome=admit(a.code.resolve(),a.root.resolve(),a.result,a.small)
        if not a.small and outcome["status"]!="ADMITTED":sys.exit(3)
    elif a.action == "recheck":
        recheck(a.root.resolve(),a.result)
    elif a.action == "assess":
        assess(a.metadata,a.result)
    elif a.action == "retrieve":
        retrieve_seed(a.code.resolve(),a.root.resolve())
    elif a.action == "restore":
        restore_seed(a.code.resolve(),a.root.resolve())
    elif a.action == "job":
        job(a.code.resolve(),a.root.resolve(),a.result,a.sample_number)
    else:
        prepare(a.code.resolve(),a.root.resolve(),a.result,a.small)


if __name__ == "__main__":
    main()

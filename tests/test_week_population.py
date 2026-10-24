"""Fictional source documents only: no live NFL evidence or model outcomes."""
import copy
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import zlib

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "pull")]
import week_population as population
from evidence import read, write
from reliability import IntegrityError, digest, stamp, utc
from scorecard import _verified_week_complete, latest_outcomes, score, snapshot_outcomes
from source_evidence import record_scoreboard

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
KICKOFF = datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)


def fixtures(first=KICKOFF, week=7, spacing=timedelta(hours=6)):
    """Full fictional 14-game slate and four byes using pinned club identities."""
    names = sorted(population.CLUBS_2026)
    byes = names[-4:]
    events, games = [], []
    for i in range(14):
        away, home = names[2*i:2*i+2]
        kickoff = first + spacing*i
        status = {"state": "pre", "completed": False, "shortDetail": "Scheduled"}
        events.append({"id": str(10000+i), "date": stamp(kickoff), "competitions": [{
            "status": {"type": status}, "competitors": [
                {"homeAway": "home", "team": {"displayName": home}},
                {"homeAway": "away", "team": {"displayName": away}}]}]})
        games.append({"id": f"00000000-0000-0000-0000-{i+1:012x}", "season": 2026, "week": week,
                      "seasonType": "REG", "weekType": "REG", "status": "SCHEDULED", "time": stamp(kickoff),
                      "awayTeam": {"fullName": away, "id": population.CLUBS_2026[away]},
                      "homeTeam": {"fullName": home, "id": population.CLUBS_2026[home]}})
    espn = {"fixture": "FICTIONAL_ONLY", "season": {"year": 2026, "type": 2},
            "week": {"number": week, "teamsOnBye": [{"displayName": n} for n in byes]}, "events": events}
    metadata = {"season": 2026, "week": week, "seasonType": "REG", "weekType": "REG",
                "dateBegin": stamp(first), "dateEnd": stamp(first + spacing*13),
                "teamsOnBye": [{"fullName": n, "id": population.CLUBS_2026[n]} for n in byes]}
    queries = [{"queryKey": ["useFetchFootballWeeklyGameDetails", {"season": "2026", "seasonType": "REG", "week": week}],
                "state": {"status": "success", "data": games}},
               {"queryKey": ["useFetchExperienceWeekSelectorBySeason", {"season": "2026"}],
                "state": {"status": "success", "data": {"data": [metadata]}}}]
    return espn, queries


def nfl_html(queries, fragmented=False):
    data = "0:" + json.dumps({"fictionalFixture": True, "queries": queries}) + "\n"
    chunks = [data[:len(data)//2], data[len(data)//2:]] if fragmented else [data]
    return "<html>Fictional test document" + "".join(
        "<script>self.__next_f.push(" + json.dumps([1, chunk]) + ")</script>" for chunk in chunks) + "</html>"


class Response:
    def __init__(self, content, url, status=200):
        self.content, self.url, self.status_code = content, url, status
        self.headers = {"Date": "Tue, 20 Oct 2026 12:00:00 GMT"}


def fictional_receipt(first=KICKOFF, week=7, captured_at=NOW, spacing=timedelta(hours=6)):
    """Create a genuine v1-format receipt from wholly fictional saved responses."""
    espn, queries = fixtures(first, week, spacing)
    def get(url, params, **kwargs):
        assert kwargs["allow_redirects"] is False
        if url == population.SCOREBOARD_URL:
            return Response(json.dumps(espn).encode(), url + "?" + urlencode(params))
        return Response(nfl_html(queries).encode(), url)
    with tempfile.TemporaryDirectory() as directory, \
            patch.object(population.requests, "get", side_effect=get), \
            patch.object(population, "datetime") as clock:
        clock.now.return_value = captured_at
        return read(population.capture_week(Path(directory), 2026, week))


class PopulationCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.espn, self.queries = fixtures()

    def get(self, url, params, **kwargs):
        self.assertFalse(kwargs["allow_redirects"])
        if url == population.SCOREBOARD_URL:
            return Response(json.dumps(self.espn).encode(), url + "?" + urlencode(params))
        return Response(nfl_html(self.queries).encode(), url)

    def capture(self, *, get=None, times=None, now=NOW, week=7):
        instants = iter(times or [])
        with patch.object(population.requests, "get", side_effect=get or self.get), \
                patch.object(population, "datetime") as clock:
            clock.now.side_effect = lambda _: next(instants, now)
            return population.capture_week(self.root, 2026, week)

    def reject(self, pattern=None, **kwargs):
        before = set((self.root / "data/week_population_diagnostics").rglob("*.json.gz"))
        with self.assertRaises(IntegrityError) as caught:
            self.capture(**kwargs)
        if pattern:
            self.assertRegex(str(caught.exception), pattern)
        paths = list((self.root / "data/week_population_diagnostics").rglob("*.json.gz"))
        self.assertTrue(paths)
        new = sorted(set(paths) - before)
        diagnostic = read(new[-1]) if new else next(read(p) for p in paths if read(p)["reason"] == str(caught.exception))
        self.assertEqual(diagnostic["status"], "BLOCKED_NOT_A_POPULATION_RECEIPT")
        return diagnostic

    def mutate_payload(self, fn):
        payload = read(self.capture())
        fn(payload)
        payload["source_document_sha256"] = digest(payload["source_document"])
        with self.assertRaises(IntegrityError):
            population.validate_receipt(payload)

    def test_complete_independent_documents_and_original_reader_contract(self):
        path = self.capture()
        payload = read(path)
        document = population.validate_receipt(payload)
        self.assertEqual(len(document["games"]), 14)
        self.assertEqual(len(document["official_week"]["byes"]), 4)
        self.assertEqual(document["club_identities"], population.CLUBS_2026)
        self.assertEqual(path.name, digest(payload) + ".json.gz")
        self.assertEqual(payload["source_timestamp"], None)
        self.assertEqual(payload["collected_at"], stamp(NOW))
        self.assertEqual(document["source_observations"]["espn"]["body"], json.dumps(self.espn))
        self.assertEqual(document["espn_decoded_json_sha256"], digest(self.espn))
        self.assertIn("Fictional test document", document["source_observations"]["nfl"]["body"])
        self.assertFalse((self.root / "output").exists())

    def test_partial_and_jointly_truncated_lists_cannot_self_certify(self):
        for which in ("espn", "nfl", "both"):
            with self.subTest(which=which):
                self.espn, self.queries = fixtures()
                if which in ("espn", "both"):
                    self.espn["events"].pop(5)
                if which in ("nfl", "both"):
                    self.queries[0]["state"]["data"].pop(5)
                self.reject("INCOMPLETE_.*CLUB_BYE_PARTITION")
        self.assertFalse(list((self.root / "data/week_populations").rglob("*.json.gz")))

    def test_duplicate_and_extra_games_rejected(self):
        for name in ("espn", "nfl"):
            with self.subTest(name=name):
                self.espn, self.queries = fixtures()
                rows = self.espn["events"] if name == "espn" else self.queries[0]["state"]["data"]
                rows.append(copy.deepcopy(rows[0]))
                self.reject()

    def test_duplicate_provider_id_on_different_teams_rejected(self):
        for name in ("espn", "nfl"):
            with self.subTest(name=name):
                self.espn, self.queries = fixtures()
                rows = self.espn["events"] if name == "espn" else self.queries[0]["state"]["data"]
                rows[1]["id"] = rows[0]["id"]
                self.reject()

    def test_full_identity_and_time_match_not_just_counts(self):
        self.queries[0]["state"]["data"][5]["time"] = stamp(KICKOFF + timedelta(hours=31))
        self.reject("INDEPENDENT_MEMBERSHIP_DISAGREEMENT")
        self.espn, self.queries = fixtures()
        game = self.queries[0]["state"]["data"][5]
        game["homeTeam"], game["awayTeam"] = game["awayTeam"], game["homeTeam"]
        self.reject("INDEPENDENT_MEMBERSHIP_DISAGREEMENT")

    def test_unknown_club_and_changed_official_identity_rejected(self):
        for change in ({"fullName": "Fictional unknown club"}, {"id": "fictional-wrong-club-id"}):
            with self.subTest(change=change):
                self.espn, self.queries = fixtures()
                self.queries[0]["state"]["data"][0]["homeTeam"].update(change)
                self.reject("UNMAPPED_OR_CHANGED_NFL_CLUB")

    def test_bye_missing_duplicate_and_playing_club_conflict_rejected(self):
        for operation in ("missing", "duplicate", "playing"):
            with self.subTest(operation=operation):
                self.espn, self.queries = fixtures()
                byes = self.queries[1]["state"]["data"]["data"][0]["teamsOnBye"]
                if operation == "missing": byes.pop()
                if operation == "duplicate": byes.append(copy.deepcopy(byes[0]))
                if operation == "playing": byes[0] = self.queries[0]["state"]["data"][0]["awayTeam"]
                self.reject()

    def test_inconsistent_espn_byes_rejected(self):
        self.espn["week"]["teamsOnBye"][0]["displayName"] = self.espn["events"][0]["competitions"][0]["competitors"][0]["team"]["displayName"]
        self.reject("DUPLICATE_OR_UNKNOWN_ESPN_BYE")

    def test_empty_document_is_not_a_complete_week(self):
        self.queries[0]["state"]["data"] = []
        self.reject("EMPTY_NFL_WEEK")
        self.espn, self.queries = fixtures()
        self.espn["events"] = []
        self.reject("EMPTY_ESPN_WEEK")

    def test_wrong_provider_periods_and_boolean_week_rejected(self):
        changes = [("espn", "year", 2025), ("espn", "type", 1), ("espn_week", "number", 6),
                   ("nfl_query", "week", 6), ("nfl_query", "season", "2025"),
                   ("nfl_game", "week", 6), ("nfl_game", "seasonType", "POST"),
                   ("selector", "season", "2025"), ("metadata", "week", True)]
        for target, key, value in changes:
            with self.subTest(target=target,key=key):
                self.espn, self.queries = fixtures()
                objects = {"espn": self.espn["season"], "espn_week": self.espn["week"],
                           "nfl_query": self.queries[0]["queryKey"][1], "nfl_game": self.queries[0]["state"]["data"][0],
                           "selector": self.queries[1]["queryKey"][1], "metadata": self.queries[1]["state"]["data"]["data"][0]}
                objects[target][key] = value
                self.reject()

    def test_wrong_week_boundaries_rejected(self):
        self.queries[1]["state"]["data"]["data"][0]["dateEnd"] = stamp(KICKOFF + timedelta(hours=79))
        self.reject("NFL_WEEK_BOUNDARY_MISMATCH")

    def test_cancelled_postponed_or_started_sources_are_not_frozen(self):
        for status in ("CANCELLED", "POSTPONED", "IN_PROGRESS"):
            with self.subTest(status=status):
                self.espn, self.queries = fixtures()
                self.queries[0]["state"]["data"][0]["status"] = status
                self.reject("NFL_NOT_SCHEDULED")
        self.espn, self.queries = fixtures()
        self.espn["events"][0]["competitions"][0]["status"]["type"].update(shortDetail="Postponed")
        self.reject("ESPN_NOT_SCHEDULED")

    def test_duplicate_or_partial_official_queries_fail_closed(self):
        self.queries.append(copy.deepcopy(self.queries[0]))
        self.reject("MISSING_OR_AMBIGUOUS_NFL_QUERY")
        self.espn, self.queries = fixtures()
        self.queries[0]["state"]["status"] = "pending"
        self.reject("INCOMPLETE_NFL_QUERY")

    def test_fragmented_flight_and_unrelated_page_javascript(self):
        def get(url,params,**kwargs):
            response=self.get(url,params,**kwargs)
            if "nfl.com" in url:
                response.content=("<script>throw new Error('MUST NEVER EXECUTE')</script>"+nfl_html(self.queries,True)).encode()
            return response
        self.assertEqual(len(read(self.capture(get=get))["source_document"]["games"]),14)

    def test_redirect_default_page_and_extra_query_parameters_rejected(self):
        for final in ("https://www.nfl.com/schedules", "https://example.invalid/schedules/2026/by-week/week-7",
                      "https://www.nfl.com/schedules/2026/by-week/week-7?week=6"):
            with self.subTest(final=final):
                def get(url,params,**kwargs):
                    response=self.get(url,params,**kwargs)
                    if "nfl.com" in url:response.url=final
                    return response
                self.reject("SOURCE_REDIRECT_OR_WRONG_URL",get=get)

    def test_http_failure_request_failure_and_successful_empty_remain_distinct(self):
        observations=[]
        for kind in ("http", "request", "empty"):
            with self.subTest(kind=kind):
                def get(url,params,**kwargs):
                    if "nfl.com" in url:
                        if kind=="request":raise requests.Timeout('fictional only')
                        return Response(b'' if kind=="empty" else b'fictional outage',url,200 if kind=="empty" else 503)
                    return self.get(url,params,**kwargs)
                diag=self.reject(get=get)
                observations.append(diag['source_observations']['nfl'])
                self.assertIn('body',diag['source_observations']['espn'])
        self.assertEqual([o['status'] for o in observations],['http_failure','request_failure','available'])
        self.assertFalse(list((self.root/'data/week_populations').rglob('*.json.gz')))

    def test_malformed_non_utf8_duplicate_and_nonfinite_json_rejected(self):
        for body in (b'not json',b'\xff',b'{"events":[],"events":[]}',b'{"value":NaN}'):
            with self.subTest(body=body):
                def get(url,params,**kwargs):
                    response=self.get(url,params,**kwargs)
                    if url==population.SCOREBOARD_URL:response.content=body
                    return response
                self.reject(get=get)

    def test_exact_kickoff_and_later_capture_rejected(self):
        for now in (KICKOFF,KICKOFF+timedelta(seconds=1)):
            with self.subTest(now=now):self.reject("CAPTURE_NOT_BEFORE_FIRST_KICKOFF",now=now)

    def test_game_starts_during_source_collection_or_final_seal(self):
        for count in (5,7):
            with self.subTest(count=count):
                before=KICKOFF-timedelta(seconds=1)
                self.reject("CAPTURE_NOT_BEFORE_FIRST_KICKOFF",times=[before]*count+[KICKOFF]*5,now=KICKOFF)

    def test_stale_client_observations_rejected(self):
        self.reject("STALE_OR_REVERSED_CAPTURE_CLOCKS",times=[NOW]*5+[NOW+timedelta(seconds=121)]*5)

    def test_saved_future_source_and_reversed_request_clocks_rejected(self):
        for field,value in (("source_timestamp",stamp(NOW+timedelta(seconds=1))),
                            ("started_at",stamp(NOW+timedelta(seconds=1))),
                            ("collected_at",stamp(NOW+timedelta(seconds=1)))):
            with self.subTest(field=field):
                self.mutate_payload(lambda p:p['source_document']['source_observations']['espn'].update({field:value}))

    def test_unknown_provider_clocks_not_inferred_from_http_date(self):
        payload=read(self.capture())
        for obs in payload['source_document']['source_observations'].values():
            self.assertIsNone(obs['source_timestamp']);self.assertEqual(obs['source_timestamp_status'],'NOT_ESTABLISHED')
            self.assertIn('http_date',obs)

    def test_dst_offsets_compare_instants_and_do_not_create_false_matches(self):
        first=datetime(2026,11,1,6,30,tzinfo=timezone.utc)
        self.espn,self.queries=fixtures(first,week=9)
        self.espn['events'][0]['date']='2026-11-01T01:30:00-05:00'
        self.queries[0]['state']['data'][0]['time']='2026-11-01T00:30:00-06:00'
        payload=read(self.capture(week=9));self.assertEqual(utc(payload['source_document']['games'][0]['kickoff']),first)
        self.queries[0]['state']['data'][0]['time']='2026-11-01T01:30:00-06:00'
        self.queries[1]['state']['data']['data'][0]['dateBegin']=stamp(first+timedelta(hours=1))
        self.reject('INDEPENDENT_MEMBERSHIP_DISAGREEMENT',week=9)

    def test_naive_timestamps_rejected(self):
        self.espn['events'][0]['date']='2026-10-23T00:15:00'
        self.reject()

    def test_corrupt_body_and_forged_derived_games_rejected(self):
        self.mutate_payload(lambda p:p['source_document']['source_observations']['espn'].update(body='{}'))
        self.mutate_payload(lambda p:p['source_document']['games'][0].update(id='999999'))
        self.mutate_payload(lambda p:p['source_document']['club_identities'].update({'Fictional extra':'bad'}))

    def test_code_version_schema_and_document_hash_are_bound(self):
        for field,value in (('adapter_code_sha256','0'*64),('adapter_version','different'),('mode','replay'),
                            ('population_scope','OBSERVED_SUBSET'),('schema_version','wrong')):
            with self.subTest(field=field):self.mutate_payload(lambda p:p.update({field:value}))
        p=read(self.capture());p['source_document_sha256']='0'*64
        with self.assertRaises(IntegrityError):population.validate_receipt(p)

    def test_retry_preserves_old_bytes_and_same_content_is_idempotent(self):
        first=self.capture();before=first.read_bytes()
        self.assertEqual(self.capture(),first);self.assertEqual(first.read_bytes(),before)
        second=self.capture(now=NOW+timedelta(seconds=1))
        self.assertNotEqual(first,second);self.assertEqual(first.read_bytes(),before)
        self.assertEqual(len(list((self.root/'data/week_populations').rglob('*.json.gz'))),2)

    def test_changed_schedule_and_event_identity_preserve_original_and_record_conflict(self):
        first=self.capture();before=first.read_bytes()
        self.espn['events'][5]['date']=stamp(KICKOFF+timedelta(hours=31))
        self.queries[0]['state']['data'][5]['time']=self.espn['events'][5]['date']
        self.reject('FROZEN_POPULATION_CONFLICT')
        self.assertEqual(first.read_bytes(),before)
        self.espn,self.queries=fixtures()
        self.queries[0]['state']['data'][5]['id']='00000000-0000-0000-0000-999999999999'
        self.reject('FROZEN_POPULATION_CONFLICT');self.assertEqual(first.read_bytes(),before)

    def test_corrupted_existing_evidence_never_overwritten(self):
        first=self.capture();envelope=json.loads(gzip.decompress(first.read_bytes()))
        envelope['payload_sha256']='0'*64;first.write_bytes(gzip.compress(json.dumps(envelope).encode()));before=first.read_bytes()
        self.reject();self.assertEqual(first.read_bytes(),before)

    def test_rehashed_prior_document_with_bad_source_binding_cannot_be_reused(self):
        first=self.capture();original=first.read_bytes();forged=read(first)
        forged['source_document']['source_observations']['espn']['body']='{}'
        forged['source_document_sha256']=digest(forged['source_document'])
        other=write(self.root,'week_populations',forged);before=other.read_bytes()
        self.reject('SOURCE_BODY_CHECKSUM_MISMATCH')
        self.assertEqual(first.read_bytes(),original);self.assertEqual(other.read_bytes(),before)

    def _outcomes(self, with_population=True):
        if with_population:self.capture()
        final=copy.deepcopy(self.espn)
        for e in final['events']:e['competitions'][0]['status']['type'].update(state='post',completed=True,shortDetail='Final')
        observed=KICKOFF+timedelta(days=5)
        board={'season':2026,'week':7,'games':[{'id':e['id'],'kickoff':e['date'],'state':'post','detail':'Final'} for e in final['events']]}
        status=record_scoreboard(final,{'dates':2026,'seasontype':2,'week':7},observed)
        (self.root/'output/data').mkdir(parents=True,exist_ok=True);(self.root/'data/cache').mkdir(parents=True,exist_ok=True)
        (self.root/'output/data/week.json').write_text(json.dumps(board))
        (self.root/'output/data/game-status.json').write_text(json.dumps({'weeks':{'2026_07':status}}))
        (self.root/'data/cache/stats_2026_07.json').write_text(json.dumps({'fictional-player':{'team':'AAA','stats':{'gp':1,'rec':3}}}))
        row={'season':2026,'week':7,'game_id':board['games'][0]['id'],'player_id':'fictional-player','category':'rec','team':'AAA',
             'kickoff':board['games'][0]['kickoff'],'raw_projection':4,'adjusted_projection':5,'captured_at':stamp(NOW)}
        key=(2026,7,row['game_id'],row['player_id'],'rec');pairs={key:row}
        path,=snapshot_outcomes(self.root,pairs,observed);payload=read(path)
        outcome=latest_outcomes([payload])[key]
        return payload,outcome,pairs,key

    def test_existing_snapshot_reader_links_new_capture_to_full_final_membership(self):
        payload,outcome,_,_=self._outcomes()
        self.assertTrue(_verified_week_complete(payload));self.assertTrue(outcome['week_confirmed_complete'])
        self.assertEqual(outcome['actual'],3)
        self.assertEqual(payload['week_game_populations'][0]['payload']['adapter_version'],population.VERSION)
        payload['games'].pop();self.assertFalse(_verified_week_complete(payload))

    def test_missing_membership_keeps_valid_point_and_zero_completed_weeks(self):
        _,outcome,pairs,key=self._outcomes(False)
        self.assertEqual(outcome['actual'],3);self.assertFalse(outcome['week_confirmed_complete'])
        policy=json.loads((ROOT/'config/evaluation-policy.json').read_text())
        result=score(pairs,{key:outcome},{'unique_opportunities':1},policy)
        self.assertEqual(result['categories']['rec']['raw_sleeper']['n'],1)
        self.assertEqual(result['categories']['rec']['uncertainty']['completed_weeks'],0)

    def test_membership_alone_cannot_complete_cancelled_nonfinal_or_changed_games(self):
        payload,_,_,_=self._outcomes()
        for kind in ('cancelled','nonfinal','changed'):
            with self.subTest(kind=kind):
                altered=copy.deepcopy(payload)
                if kind=='cancelled':altered['games'][0]['detail']='Cancelled'
                if kind=='nonfinal':altered['games'][0]['state']='pre'
                if kind=='changed':altered['games'][0]['kickoff']=stamp(KICKOFF+timedelta(hours=1))
                self.assertFalse(_verified_week_complete(altered))

    def test_cli_requires_isolation_and_accepts_no_live_clock_override(self):
        with patch.object(population.requests,'get') as get,patch('sys.stderr',new_callable=io.StringIO):
            for extra in (['--replay-at',stamp(NOW)],['--collected-at',stamp(NOW)],['--now',stamp(NOW)]):
                with self.assertRaises(SystemExit) as err:population.main(['--root',str(self.root),'--season','2026','--week','7',*extra])
                self.assertEqual(err.exception.code,2)
            with self.assertRaises(IntegrityError):population.capture_week(ROOT,2026,7)
            with self.assertRaises(IntegrityError):population.capture_week(self.root,2025,7)
            get.assert_not_called()


class PopulationConsumerRegressionTests(unittest.TestCase):
    """Actual consumers must validate original source semantics, not outer hashes."""

    def setUp(self):
        self.population = fictional_receipt()
        self.policy = json.loads((ROOT / 'config/evaluation-policy.json').read_text())

    def pairs(self, week=7):
        row = {'season': 2026, 'week': week, 'game_id': '10000',
               'player_id': 'fictional-player', 'category': 'rec', 'team': 'AAA',
               'kickoff': stamp(KICKOFF), 'raw_projection': 4, 'adjusted_projection': 5,
               'captured_at': stamp(NOW)}
        return {(2026, week, '10000', 'fictional-player', 'rec'): row}

    def snapshot(self, populations, *, week=7, extra=None, read_error=None, raw_read_error=False, bad_input=None):
        final, _ = fixtures(week=week)
        for event in final['events']:
            event['competitions'][0]['status']['type'].update(state='post', completed=True, shortDetail='Final')
        observed = KICKOFF + timedelta(days=5)
        board = {'season': 2026, 'week': week, 'games': [
            {'id': e['id'], 'kickoff': e['date'], 'state': 'post', 'detail': 'Final'}
            for e in final['events']]}
        status = record_scoreboard(final, {'dates': 2026, 'seasontype': 2, 'week': week}, observed)
        cache = {'fictional-player': {'team': 'AAA', 'stats': {'gp': 1, 'rec': 3}}}
        if bad_input == 'statistic':
            cache['fictional-player']['stats']['rec'] = 'not-a-number'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'output/data').mkdir(parents=True)
            (root / 'data/cache').mkdir(parents=True)
            (root / 'output/data/week.json').write_text('invalid' if bad_input == 'board' else json.dumps(board))
            (root / 'output/data/game-status.json').write_text(json.dumps({'weeks': {f'2026_{week:02d}': status}}))
            (root / f'data/cache/stats_2026_{week:02d}.json').write_text(
                'invalid' if bad_input == 'cache' else json.dumps(cache))
            for payload in populations:
                write(root, 'week_populations', payload)
            if extra is not None:
                path = root / f'data/week_populations/2026/w{week:02d}' / ('0' * 64 + '.json.gz')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(extra)
            before = {p: p.read_bytes() for p in root.rglob('*.json.gz')}
            def population_read(path):
                if read_error is not None and path.name == '0' * 64 + '.json.gz':
                    raise read_error
                return read(path)
            original_read_bytes = Path.read_bytes
            def file_bytes(path):
                if raw_read_error and path.name == '0' * 64 + '.json.gz':
                    raise PermissionError('fictional private file-read message')
                return original_read_bytes(path)
            with patch('scorecard.read', side_effect=population_read), \
                    patch.object(Path, 'read_bytes', autospec=True, side_effect=file_bytes), \
                    patch.object(population.requests, 'get', side_effect=AssertionError('No refetch')) as get:
                path, = snapshot_outcomes(root, self.pairs(week), observed)
                result = read(path)
                get.assert_not_called()
            self.assertEqual({p: p.read_bytes() for p in before}, before)
        # The source/cache/population files are now unavailable to consumption.
        return result

    def assert_scored(self, saved, complete):
        before = copy.deepcopy(saved)
        week = saved['week']
        with patch.object(population.requests, 'get', side_effect=AssertionError('No refetch')) as get:
            self.assertEqual(_verified_week_complete(saved), complete)
            outcomes = latest_outcomes([saved])
            report = score(self.pairs(week), outcomes, {'unique_opportunities': 1}, self.policy)
            get.assert_not_called()
        selected = next(iter(outcomes.values()))
        self.assertEqual((selected['status'], selected['actual']), ('resolved', 3))
        self.assertEqual(selected['week_confirmed_complete'], complete)
        self.assertEqual(len(selected['week_completion_snapshot_sha256']), int(complete))
        category = report['categories']['rec']
        self.assertEqual(category['raw_sleeper']['n'], 1)
        self.assertEqual(category['raw_sleeper']['mae'], 1)
        self.assertEqual(category['unchanged_clone']['mae'], 2)
        self.assertEqual(category['uncertainty']['completed_weeks'], int(complete))
        self.assertIsNone(category['uncertainty']['interval'])
        self.assertEqual(saved, before)
        return selected

    def invalid_cases(self):
        name = sorted(population.CLUBS_2026)[0]
        return [
            ('wrong_adapter_code_digest', lambda p: p.update(adapter_code_sha256='0' * 64)),
            ('missing_source_observations', lambda p: p['source_document'].pop('source_observations')),
            ('changed_body_without_matching_body_hash', lambda p: p['source_document']['source_observations']['espn'].update(body='{}')),
            ('wrong_source_request_week', lambda p: p['source_document']['source_observations']['espn']['request']['params'].update(week=6)),
            ('reversed_capture_clocks', lambda p: p.update(capture_started_at=stamp(NOW + timedelta(seconds=1)))),
            ('changed_club_identity_mapping', lambda p: p['source_document']['club_identities'].update({name: 'wrong-identity'}))]

    def test_valid_retained_v1_fresh_and_saved_consumers_qualify_offline(self):
        self.assertEqual(population.code_sha256(), '1e50c60ce2636f4534a63f517341c393bac19b8df7cbd2b1fcba1e9eed16c40e')
        original = copy.deepcopy(self.population)
        saved = self.snapshot([self.population])
        self.assertTrue(saved['rows'][0]['week_confirmed_complete'])
        self.assert_scored(saved, True)
        # Older otherwise valid saved outcomes lacked this additive diagnostic.
        saved.pop('week_population_read_errors')
        self.assert_scored(saved, True)
        self.assertEqual(self.population, original)

    def test_all_six_rehashed_invalid_cases_fail_fresh_and_saved_consumption(self):
        valid = self.snapshot([self.population])
        for name, mutate in self.invalid_cases():
            with self.subTest(case=name):
                altered = copy.deepcopy(self.population)
                mutate(altered)
                altered['source_document_sha256'] = digest(altered['source_document'])
                with self.assertRaises(IntegrityError):
                    population.validate_receipt(altered)
                fresh = self.snapshot([altered])
                self.assertFalse(fresh['rows'][0]['week_confirmed_complete'])
                self.assert_scored(fresh, False)
                forged = copy.deepcopy(valid)
                forged['week_game_populations'] = [{'payload_sha256': digest(altered), 'payload': altered}]
                self.assertTrue(forged['rows'][0]['week_confirmed_complete'])
                # Persist the altered outcome with a freshly computed outer
                # envelope as well; ordinary byte corruption is not the issue.
                with tempfile.TemporaryDirectory() as directory:
                    forged = read(write(Path(directory), 'outcomes', forged))
                self.assert_scored(forged, False)
                # A valid sibling must not hide this invalid source record.
                self.assert_scored(self.snapshot([self.population, altered]), False)

    def test_legacy_unknown_and_replay_contracts_never_use_generic_fallback(self):
        changes = [lambda p: p.update(schema_version='unsupported'),
                   lambda p: p.update(adapter_version='fictional-future-v2'),
                   lambda p: p.update(adapter_code_sha256='f' * 64),
                   lambda p: [p.pop(k) for k in ('adapter_version', 'adapter_code_sha256')],
                   lambda p: p.update(mode='replay')]
        for change in changes:
            altered = copy.deepcopy(self.population)
            change(altered)
            for siblings in ([altered], [self.population, altered]):
                with self.subTest(contract={k: altered.get(k) for k in ('schema_version', 'adapter_version', 'mode')}, mixed=len(siblings) > 1):
                    self.assert_scored(self.snapshot(siblings), False)
        self.assert_scored(self.snapshot([]), False)

    def test_source_valid_membership_conflict_cannot_choose_a_winning_receipt(self):
        other = copy.deepcopy(self.population)
        _, queries = fixtures()
        queries[0]['state']['data'][0]['id'] = '00000000-0000-0000-0000-999999999999'
        obs = other['source_document']['source_observations']
        obs['nfl']['body'] = nfl_html(queries)
        obs['nfl']['body_sha256'] = hashlib.sha256(obs['nfl']['body'].encode()).hexdigest()
        other['source_document'] = population._document(obs, 2026, 7, NOW, NOW)
        other['source_document_sha256'] = digest(other['source_document'])
        population.validate_receipt(other)
        self.assert_scored(self.snapshot([other]), True)
        for siblings in ([self.population, other], [other, self.population]):
            self.assert_scored(self.snapshot(siblings), False)

    def test_optional_population_corruption_preserves_points_and_saved_read_errors(self):
        good = gzip.compress(json.dumps({'payload_sha256': digest(self.population), 'payload': self.population}).encode())
        bad_envelope = gzip.compress(json.dumps({'payload_sha256': '0' * 64, 'payload': self.population}).encode())
        corruptions = [b'FICTIONAL_NOT_GZIP', good[:-8], gzip.compress(b'\xff'),
                       gzip.compress(b'not-json'), gzip.compress(b'[]'),
                       gzip.compress(b'{"payload":{},"payload":{}}'),
                       gzip.compress(b'{"payload":NaN}'), bad_envelope, good]
        for content in corruptions:
            for populations in ([], [self.population]):
                with self.subTest(digest=hashlib.sha256(content).hexdigest(), mixed=bool(populations)):
                    saved = self.snapshot(populations, extra=content)
                    errors = saved['week_population_read_errors']
                    self.assertEqual(len(errors), 1)
                    self.assertEqual(errors[0]['raw_file_sha256'], hashlib.sha256(content).hexdigest())
                    self.assertEqual(set(errors[0]), {'path', 'error_type', 'raw_file_sha256'})
                    self.assert_scored(saved, False)

    def test_unreadable_and_deflate_read_failures_are_narrowly_recorded(self):
        for error in (PermissionError('fictional private message must not be saved'), zlib.error('fictional deflate failure')):
            saved = self.snapshot([self.population], extra=b'FICTIONAL', read_error=error)
            self.assertEqual(saved['week_population_read_errors'][0]['error_type'], type(error).__name__)
            self.assertNotIn(str(error), json.dumps(saved))
            self.assert_scored(saved, False)

    def test_failure_before_population_bytes_are_read_preserves_point_outcome(self):
        saved = self.snapshot([self.population], extra=b'FICTIONAL', raw_read_error=True)
        error, = saved['week_population_read_errors']
        self.assertEqual(error['error_type'], 'PermissionError')
        self.assertIsNone(error['raw_file_sha256'])
        self.assertNotIn('fictional private file-read message', json.dumps(saved))
        self.assert_scored(saved, False)

    def test_validator_unavailable_or_modified_cannot_reinterpret_saved_v1(self):
        saved = self.snapshot([self.population])
        for failure in ('different-code', 'unreadable-code'):
            with self.subTest(failure=failure), patch.object(population, 'code_sha256',
                    **({'return_value': '0' * 64} if failure == 'different-code' else {'side_effect': OSError('fixture')})):
                self.assert_scored(saved, False)
        self.assert_scored(saved, True)

    def test_read_error_metadata_is_fail_closed_and_saved_flags_are_not_authority(self):
        saved = self.snapshot([self.population])
        for errors in ([{'error_type': 'FICTIONAL'}], {}, None, 'invalid'):
            bad = copy.deepcopy(saved)
            bad['week_population_read_errors'] = errors
            self.assert_scored(bad, False)
        saved['rows'][0]['week_confirmed_complete'] = False
        self.assert_scored(saved, True)

    def test_population_tolerance_does_not_hide_board_cache_stat_or_outcome_errors(self):
        for bad in ('board', 'cache', 'statistic'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.snapshot([self.population], extra=b'bad-gzip', bad_input=bad)
        saved = self.snapshot([self.population])
        saved['rows'][0]['actual'] = 9
        with self.assertRaises(IntegrityError):
            latest_outcomes([saved])

    def test_eight_invalid_source_weeks_keep_points_without_opening_registered_gate(self):
        pairs, outcomes = {}, {}
        for week in range(1, 9):
            altered = fictional_receipt(week=week)
            altered['adapter_code_sha256'] = '0' * 64
            saved = self.snapshot([altered], week=week)
            pairs.update(self.pairs(week))
            outcomes.update(latest_outcomes([saved]))
        report = score(pairs, outcomes, {}, self.policy)
        category = report['categories']['rec']
        self.assertEqual(category['raw_sleeper']['n'], 8)
        self.assertEqual(category['uncertainty']['completed_weeks'], 0)
        self.assertEqual(category['uncertainty']['excluded_incomplete_outcomes'], 8)
        self.assertIsNone(category['uncertainty']['interval'])


if __name__ == '__main__':
    unittest.main()

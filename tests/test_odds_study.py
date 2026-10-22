"""Wholly fictional paper-study controls. No key, provider or GitHub access."""
import copy
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

import odds_study as s

T = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
FAKE_KEY = "FICTIONAL_TEST_KEY_0123456789"


def fixture():
    prop = {"key": "rec", "proj": 6.0, "adj": 7.0, "line": 5.5, "line_from": "dk", "lean": "over"}
    board = {"season": 2026, "week": 9, "generated_at": s.stamp(T - timedelta(hours=2)),
             "games": [{"id": "fiction-game", "kickoff": s.stamp(T + timedelta(days=1)),
                        "home": "CHI", "away": "NE", "state": "pre"}],
             "players": [{"id": "fiction-player", "name": "Fiction Player", "team": "CHI", "pos": "WR",
                          "game_id": "fiction-game", "props": [prop]}],
             "picks": {"over": [{"game_id": "fiction-game", "player_id": "fiction-player", "key": "rec",
                                  "direction": "over", "line": 5.5, "line_from": "dk", "proj": 6.0, "adj": 7.0}], "under": []}}
    meta = {k: board[k] for k in ("season", "week", "generated_at")}
    return board, meta


def snapshot(board=None, meta=None):
    b, m = fixture()
    return s.make_snapshot(s.canonical(board or b), s.canonical(meta or m),
        {"commit": "a" * 40, "tree": "b" * 40, "pages_bytes_match_git": True}, T)


def event(i=0):
    return {"id": "fiction-event-" + str(i), "sport_key": "americanfootball_nfl",
            "commence_time": s.stamp(T + timedelta(days=1, hours=i)),
            "home_team": "Chicago Bears", "away_team": "New England Patriots"}


def body(e=None, line=5.5):
    e = e or event()
    return {**e, "bookmakers": [{"key": key, "last_update": s.stamp(T - timedelta(seconds=30)),
        "markets": [{"key": "player_receptions", "last_update": s.stamp(T - timedelta(seconds=15)),
        "outcomes": [{"name": "Over", "description": "Fiction Player", "point": line, "price": over},
                     {"name": "Under", "description": "Fiction Player", "point": line, "price": under}]}]}
        for key, over, under in (("book-a", 2.2, 1.8), ("book-b", 2.0, 2.0), ("book-c", 2.0, 2.0))]}


def quotes(data=None):
    data = data or body()
    return s.normalize(data, event(), snapshot(), s.stamp(T), s.sha(s.canonical(data)))[0]


def rules():
    return {(book, "player_receptions"): {"statistic": "rec", "period": "full_game", "overtime": True,
             "action_void": "FICTIONAL_EQUAL_ACTION_RULE", "source_sha256": "c" * 64}
            for book in ("book-a", "book-b", "book-c")}


def dense_fixture(players=30, books=20):
    """Distinct fictional contracts; bounded response, expanded comparison graph."""
    b, m = fixture(); original = b["players"][0]; b["players"] = []
    for i in range(players):
        p = copy.deepcopy(original)
        p.update(id=f"fiction-player-{i}", name=f"Fiction Receiver {i}")
        p["props"].append(dict(p["props"][0], key="rec_yd", proj=50.0, adj=55.0, line=49.5))
        b["players"].append(p)
    b["picks"] = {"over": [], "under": []}; e = event(); response = dict(e, bookmakers=[])
    for i in range(books):
        markets = []
        for market, line in (("player_receptions", 5.5), ("player_reception_yds", 49.5)):
            outcomes = [{"name": side, "description": p["name"], "point": line, "price": 2.0}
                        for p in b["players"] for side in ("Over", "Under")]
            markets.append({"key": market, "last_update": s.stamp(T), "outcomes": outcomes})
        response["bookmakers"].append({"key": f"fiction-book-{i}", "last_update": s.stamp(T), "markets": markets})
    return b, m, response


class FakeLedger:
    def __init__(self, fail=False):
        self.records = []; self.previous = None; self.fail = fail

    def begin(self):
        if self.fail:
            raise s.Stop("BATCH_ALREADY_CLAIMED_OR_AMBIGUOUS")
        return self.append("CLAIM", {})

    def append(self, kind, details):
        self.records.append((kind, copy.deepcopy(details)))
        self.previous = {"id": len(self.records), "body_sha256": s.sha(s.canonical([kind, details]))}
        return self.previous


class FakeProvider:
    def __init__(self, count=1, remaining=176, fail=False, contradictory=False, cost=11):
        self.events = [event(i) for i in range(count)]; self.remaining = remaining; self.used = 0
        self.calls = []; self.fail = fail; self.contradictory = contradictory; self.cost = cost

    def request(self, event_id=None):
        self.calls.append(event_id)
        if event_id and self.fail:
            raise s.Stop("PROVIDER_REQUEST_UNCERTAIN_NO_RETRY")
        last = self.cost if event_id else 0
        if event_id and not self.contradictory:
            self.remaining -= last; self.used += last
        return {"http_status": 200, "started_at": s.stamp(T), "retrieved_at": s.stamp(T),
                "headers": {"x-requests-remaining": str(self.remaining), "x-requests-used": str(self.used),
                            "x-requests-last": str(last)},
                "body": s.canonical(body(next(e for e in self.events if e["id"] == event_id)) if event_id else self.events),
                "complete_original_entity": True, "route": "event_odds" if event_id else "events", "event_id": event_id}


class FakeGitHub:
    def __init__(self):
        self.comments = []; self.posts = 0; self.ambiguous = False; self.edit = False; self.forged = False

    def get(self, path, payload=None):
        if payload is not None:
            self.posts += 1
            c = {"id": len(self.comments) + 1, "body": payload["body"],
                 "user": {"id": s.BOT, "type": "Bot"}, "created_at": s.stamp(T), "updated_at": s.stamp(T)}
            c["html_url"] = "https://github.com/" + s.REPO + "/pull/1#issuecomment-" + str(c["id"])
            self.comments.append(c)
            if self.ambiguous:
                raise s.Stop("GITHUB_REQUEST_UNCERTAIN")
            return copy.deepcopy(c)
        if path.startswith("/issues/1/comments?"):
            return copy.deepcopy(self.comments)
        c = copy.deepcopy(self.comments[int(path.rsplit("/", 1)[1]) - 1])
        if self.edit: c["updated_at"] = "changed"
        if self.forged: c["user"]["id"] = 999
        return c


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "study"; self.root.mkdir()
        b, m = fixture(); self.snapshot = snapshot()
        s.write_file(self.root, "forecast/week.json", s.canonical(b))
        s.write_file(self.root, "forecast/meta.json", s.canonical(m))
        s.write_file(self.root, "SNAPSHOT.json", s.canonical(self.snapshot))

    def run_batch(self, provider=None, ledger=None, clock=lambda: T):
        self.provider = provider or FakeProvider(); self.ledger = ledger or FakeLedger()
        return s.collect_batch(self.root, self.snapshot, self.provider, self.ledger, clock=clock,
                               secrets=(FAKE_KEY,))

    def seal(self, report):
        return s.seal_bundle(self.root, report, (FAKE_KEY,))

    def rehash(self, name, value):
        (self.root / name).write_bytes(s.canonical(value))
        manifest = s.parse((self.root / "MANIFEST.json").read_bytes())
        for f in manifest["files"]:
            raw = (self.root / f["path"]).read_bytes(); f.update(bytes=len(raw), sha256=s.sha(raw))
        (self.root / "MANIFEST.json").write_bytes(s.canonical(manifest))

    def test_contract_is_exact_eleven_and_single_region(self):
        self.assertEqual(len(s.MARKETS), 11)
        self.assertEqual(s.MAX_CREDITS, 176)
        self.assertNotIn("fpts", s.MARKETS.values())
        self.assertNotIn("player_rush_tds", s.MARKETS)

    def dense_batch(self, players=30, books=20):
        b, m, data = dense_fixture(players, books); self.snapshot = snapshot(b, m)
        for name, value in (("forecast/week.json", b), ("forecast/meta.json", m), ("SNAPSHOT.json", self.snapshot)):
            (self.root / name).write_bytes(s.canonical(value))
        class DenseProvider(FakeProvider):
            def request(self, event_id=None):
                r = super().request(event_id)
                if event_id:
                    r["body"] = s.canonical(data)
                return r
        provider = DenseProvider()
        return self.run_batch(provider=provider), data

    def test_bounded_many_book_report_is_consumable_without_losing_contracts(self):
        report, data = self.dense_batch()
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(len(report["quotes"]), 2400)
        self.assertEqual(len({q["id"] for q in report["quotes"]}), 2400)
        self.assertEqual(len(report["comparisons"]), 2400)
        self.assertLess(len(s.canonical(data)), s.BODY_LIMIT)
        raw = (self.root / "REPORT.json").read_bytes()
        self.assertLess(len(raw), 32 * s.MIB)
        with self.assertRaisesRegex(s.Stop, "JSON_STRUCTURE_LIMIT"):
            s.parse(raw, 32 * s.MIB)  # still the original provider-entity bound
        self.assertEqual(s.parse(raw, 32 * s.MIB, node_limit=s.REPORT_NODES), report)
        digest = self.seal(report)
        self.assertEqual(s.verify_bundle(self.root, digest)["batch_status"], "COMPLETE")
        self.assertEqual(s.summary(self.root)["quotes"], 2400)
        original = (self.root / "responses/01.body").read_bytes()
        self.assertEqual(original, s.canonical(data))
        out = self.root.parent / "dense.tar.gz"
        self.assertEqual(s.bundle(self.root, out)["batch_status"], "COMPLETE")
        self.assertEqual((self.root / "responses/01.body").read_bytes(), original)

    def test_actual_derived_node_bound_stops_and_replays_failure_with_originals(self):
        report, data = self.dense_batch(players=50, books=30)
        self.assertEqual(report["status"], "FAILED_SAFE")
        self.assertEqual(report["reason"], "DERIVED_REPORT_LIMIT_SOURCE_RETAINED")
        self.assertEqual(report["reserved_credits"], 11)
        self.assertEqual(report["known_request_credits"], 11)
        self.assertEqual(len(self.provider.calls), 3)  # two free discoveries + one event
        self.assertEqual(report["quotes"], [])
        raw = (self.root / "responses/01.body").read_bytes()
        rows = s.normalize(s.parse(raw), event(), self.snapshot, s.stamp(T), s.sha(raw))[0]
        derived = {"quotes": rows, "comparisons": s.compare(self.snapshot, rows)}
        self.assertEqual(len(rows), 6000)
        self.assertLessEqual(len(s.canonical(derived)), 32 * s.MIB)
        with self.assertRaisesRegex(s.Stop, "JSON_STRUCTURE_LIMIT"):
            s.structure(derived, s.DERIVED_NODES)
        self.seal(report)
        self.assertEqual(s.verify_bundle(self.root)["batch_status"], "FAILED_SAFE")
        self.assertEqual(raw, s.canonical(data))
        self.assertEqual(s.summary(self.root)["batch_status"], "FAILED_SAFE")

    def test_report_parser_and_entity_parser_keep_distinct_finite_node_limits(self):
        raw = s.canonical([0] * s.ENTITY_NODES)
        self.assertLess(len(raw), s.BODY_LIMIT)
        with self.assertRaisesRegex(s.Stop, "JSON_STRUCTURE_LIMIT"):
            s.parse(raw)
        self.assertEqual(len(s.parse(raw, node_limit=s.REPORT_NODES)), s.ENTITY_NODES)
        with self.assertRaisesRegex(s.Stop, "JSON_STRUCTURE_LIMIT"):
            s.parse(s.canonical([0] * s.REPORT_NODES), node_limit=s.REPORT_NODES)

    def test_fabricated_derived_complexity_failure_is_not_a_saved_pass(self):
        report = self.run_batch(); report["status"] = "FAILED_SAFE"
        report["reason"] = "DERIVED_REPORT_LIMIT_SOURCE_RETAINED"
        report["quotes"] = []; report["comparisons"] = []
        (self.root / "REPORT.json").write_bytes(s.canonical(report)); self.seal(report)
        with self.assertRaisesRegex(s.Stop, "FALSE_DERIVED_SIZE_FAILURE"):
            s.verify_bundle(self.root)

    def test_snapshot_preserves_zero_null_signed_values_and_clocks(self):
        b, m = fixture(); b["players"][0]["props"][0].update(proj=0, adj=None, line=0.5)
        x = snapshot(b, m)
        self.assertEqual(x["rows"][0]["raw_forecast"], 0)
        self.assertIsNone(x["rows"][0]["adjusted_forecast"])
        self.assertEqual(x["forecast_generated_at"], b["generated_at"])

    def test_top_membership_requires_exact_saved_source_forecast_line_and_side(self):
        for field, value in (("line_from", "sleeper"), ("proj", 99), ("adj", None), ("line", 6.5), ("lean", "under")):
            with self.subTest(field=field):
                b, m = fixture(); b["players"][0]["props"][0][field] = value
                x = snapshot(b, m)
                self.assertFalse(x["rows"][0]["top_over"])
                self.assertEqual(x["original_top_contracts"], b["picks"])

    def test_exact_top_is_supported_without_reranking(self):
        self.assertTrue(self.snapshot["rows"][0]["top_over"])
        self.assertFalse(self.snapshot["rows"][0]["top_under"])

    def test_duplicate_top_contract_rejected(self):
        b, m = fixture(); b["picks"]["over"] *= 2
        with self.assertRaises(s.Stop): snapshot(b, m)

    def test_snapshot_future_or_period_mismatch_rejected(self):
        b, m = fixture(); m["week"] += 1
        with self.assertRaises(s.Stop): snapshot(b, m)
        b, m = fixture(); b["generated_at"] = m["generated_at"] = s.stamp(T + timedelta(seconds=1))
        with self.assertRaises(s.Stop): snapshot(b, m)

    def test_snapshot_pages_must_match_pinned_git(self):
        b, m = fixture()
        with self.assertRaises(s.Stop):
            s.make_snapshot(s.canonical(b), s.canonical(m), {"commit": "a" * 40, "tree": "b" * 40,
                            "pages_bytes_match_git": False}, T)

    def test_discovery_selects_only_earliest_sixteen_in_eight_days(self):
        es = [event(i) for i in reversed(range(20))]
        es.append({**event(30), "commence_time": s.stamp(T - timedelta(seconds=1))})
        es.append({**event(31), "commence_time": s.stamp(T + timedelta(days=9))})
        picked = s.choose_events(es, T)
        self.assertEqual([e["id"] for e in picked], [event(i)["id"] for i in range(16)])

    def test_duplicate_events_or_wrong_sport_rejected(self):
        for es in ([event(), event()], [event(), {**event(), "id": "duplicate-game-other-id"}],
                   [{**event(), "sport_key": "basketball_nba"}]):
            with self.assertRaises(s.Stop): s.choose_events(es, T)

    def test_normalization_exact_game_player_stat_line_side_and_book(self):
        q = quotes(); self.assertEqual(len(q), 6)
        self.assertEqual({r["game_id"] for r in q}, {"fiction-game"})
        self.assertEqual({r["player_id"] for r in q}, {"fiction-player"})
        self.assertEqual({r["category"] for r in q}, {"rec"})
        self.assertEqual({r["line"] for r in q}, {"5.5"})
        for row in q:
            d = dict(row); ident = d.pop("id"); self.assertEqual(ident, s.sha(s.canonical(d)))

    def test_new_collection_clock_changes_quote_identity(self):
        b = body(); a = quotes(b)
        c = s.normalize(b, event(), snapshot(), s.stamp(T + timedelta(seconds=1)), s.sha(s.canonical(b)))[0]
        self.assertNotEqual(a[0]["id"], c[0]["id"])

    def test_wrong_response_event_or_kickoff_fails(self):
        for field, val in (("id", "other"), ("commence_time", s.stamp(T + timedelta(days=2)))):
            b = body(); b[field] = val
            with self.assertRaises(s.Stop): quotes(b)

    def test_unresolved_player_is_retained_not_guessed(self):
        b = body(); b["bookmakers"][0]["markets"][0]["outcomes"][0]["description"] = "Other Person"
        q = quotes(b); self.assertIsNone(q[0]["player_id"])
        self.assertEqual(s.compare(snapshot(), q)[0]["reason"], "UNRESOLVED_IDENTITY_OR_STATISTIC")

    def test_duplicate_normalized_quote_does_not_overwrite_side(self):
        b = body(); o = b["bookmakers"][0]["markets"][0]["outcomes"]
        o.append({**o[0], "description": "FICTION PLAYER"})
        with self.assertRaises(s.Stop): quotes(b)

    def test_live_unknown_rules_remain_unvalued(self):
        r = s.compare(snapshot(), quotes())
        self.assertEqual({x["reason"] for x in r}, {"UNVERIFIED_OR_INCOMPATIBLE_RULES"})
        self.assertTrue(all(x["market_derived_ev_per_unit"] is None for x in r))

    def test_supported_reference_excludes_offering_book_and_uses_actual_prices(self):
        q = quotes(); r = s.compare(snapshot(), q, rules=rules())[0]
        self.assertAlmostEqual(r["market_reference_probability"], .5)
        self.assertAlmostEqual(r["market_derived_ev_per_unit"], .1)
        self.assertNotIn(q[0]["id"], r["reference_quote_ids"])
        self.assertNotIn(q[1]["id"], r["reference_quote_ids"])
        self.assertFalse(r["reference_is_model_probability"])

    def test_missing_side_integer_push_and_stale_quote_remain_unvalued(self):
        b = body(); b["bookmakers"][0]["markets"][0]["outcomes"].pop()
        self.assertEqual(s.compare(snapshot(), quotes(b), rules=rules())[0]["reason"], "MISSING_OFFERING_BOOK_SIDE")
        self.assertEqual(s.compare(snapshot(), quotes(body(line=5)), rules=rules())[0]["reason"], "INTEGER_PUSH_PROBABILITY_UNKNOWN")
        b = body(); b["bookmakers"][1]["markets"][0]["last_update"] = s.stamp(T - timedelta(hours=1))
        self.assertEqual(s.compare(snapshot(), quotes(b), rules=rules())[0]["reason"], "PROVIDER_QUOTE_CLOCK_UNSUPPORTED")

    def test_different_line_or_period_cannot_supply_a_reference(self):
        q = quotes()
        for x in q[2:]: x["line"] = "6.5"
        self.assertEqual(s.compare(snapshot(), q, rules=rules())[0]["reason"], "NO_OTHER_COMPLETE_BOOK_PAIR")
        q = quotes()
        for x in q[2:]: x["period"] = "first_half"
        self.assertEqual(s.compare(snapshot(), q, rules=rules())[0]["reason"], "NO_OTHER_COMPLETE_BOOK_PAIR")

    def test_anytime_td_has_no_invented_under_or_model_probability(self):
        b = body(); b["bookmakers"] = b["bookmakers"][:1]
        b["bookmakers"][0]["markets"] = [{"key": "player_anytime_td", "outcomes": [{"name": "Yes", "description": "Fiction Player", "price": 2.0}]}]
        q = quotes(b); self.assertEqual(len(q), 1); self.assertEqual(q[0]["side"], "yes")
        self.assertIsNone(s.compare(snapshot(), q)[0]["market_reference_probability"])

    def test_forecast_age_and_threshold_differences_are_explicit(self):
        r = s.compare(snapshot(), quotes(body(line=6.5)))[0]
        self.assertEqual(r["forecast_age_seconds"], 7200)
        self.assertFalse(r["threshold_matches"]); self.assertEqual(r["saved_line"], 5.5)

    def test_http_client_exact_private_auth_and_no_retry(self):
        response = mock.MagicMock(); response.__enter__.return_value = response
        response.status = 200; response.headers = {}; response.read.return_value = b"[]"
        opener = mock.Mock(); opener.open.return_value = response
        p = s.Provider(FAKE_KEY, opener); result = p.request("fiction-event")
        request = opener.open.call_args.args[0]
        self.assertIn("api.the-odds-api.com/v4/", request.full_url)
        self.assertIn("regions=us", request.full_url)
        self.assertNotIn(FAKE_KEY, repr(result)); self.assertEqual(opener.open.call_count, 1)
        opener.open.side_effect = RuntimeError("request failed https://evil/?apiKey=" + FAKE_KEY)
        with self.assertRaisesRegex(s.Stop, "PROVIDER_REQUEST_UNCERTAIN_NO_RETRY") as error: p.request("fiction-event")
        self.assertNotIn(FAKE_KEY, str(error.exception)); self.assertEqual(opener.open.call_count, 2)

    def test_encoded_secret_error_is_withheld_before_retention(self):
        response = mock.MagicMock(); response.__enter__.return_value = response
        response.status = 400; response.headers = {"Content-Encoding": "gzip"}
        response.read.return_value = gzip.compress(FAKE_KEY.encode())
        opener = mock.Mock(); opener.open.return_value = response
        with self.assertRaisesRegex(s.Stop, "UNSUPPORTED_CONTENT_ENCODING_WITHHELD"):
            s.Provider(FAKE_KEY, opener).request()

    def test_plain_encoded_and_json_escaped_secret_blocks(self):
        for raw in (FAKE_KEY.encode(), s.canonical({"error": FAKE_KEY}),
                    s.canonical({"x": s.base64.b64encode(FAKE_KEY.encode()).decode()})):
            with self.assertRaisesRegex(s.Stop, "SECRET_BLOCKED"): s.assert_no_secret(raw, (FAKE_KEY,))

    def test_quota_requires_actual_integer_headers_and_coherent_counters(self):
        with self.assertRaises(s.Stop): s.quota({"x-requests-remaining": "NaN"})
        with self.assertRaises(s.Stop): s.quota_transition({"used": 0, "remaining": 176}, {"used": 0, "remaining": 176, "last": 11}, 11)

    def test_full_batch_maximum_is_sixteen_requests_176_credits(self):
        r = self.run_batch(FakeProvider(count=17)); self.assertEqual(r["status"], "COMPLETE")
        self.assertEqual(r["reserved_credits"], 176); self.assertEqual(r["known_request_credits"], 176)
        self.assertEqual(sum(x is not None for x in self.provider.calls), 16)
        self.assertEqual(len([x for x in self.ledger.records if x[0] == "RESERVE"]), 16)
        self.seal(r); self.assertEqual(s.verify_bundle(self.root)["known_request_credits"], 176)

    def test_insufficient_existing_credits_stops_before_charge(self):
        r = self.run_batch(FakeProvider(remaining=10)); self.assertEqual(r["reason"], "INSUFFICIENT_VERIFIED_CREDITS")
        self.assertEqual(r["reserved_credits"], 0); self.assertFalse(any(self.provider.calls))
        self.seal(r); s.verify_bundle(self.root)

    def test_failed_native_request_retains_reservation_and_never_retries(self):
        r = self.run_batch(FakeProvider(fail=True)); self.assertEqual(r["reserved_credits"], 11)
        self.assertEqual(sum(x is not None for x in self.provider.calls), 1)
        self.assertEqual(r["known_request_credits"], 0); self.assertEqual(r["status"], "FAILED_SAFE")
        self.seal(r); self.assertEqual(s.verify_bundle(self.root)["batch_status"], "FAILED_SAFE")

    def test_conflicting_quota_stops_and_retains_original_body(self):
        r = self.run_batch(FakeProvider(contradictory=True)); self.assertEqual(r["reason"], "QUOTA_COUNTERS_CHANGED_OR_AMBIGUOUS")
        self.assertEqual(sum(x is not None for x in self.provider.calls), 1)
        self.assertTrue((self.root / "responses/01.body").exists())
        self.seal(r); s.verify_bundle(self.root)

    def test_duplicate_claim_prevents_even_discovery(self):
        r = self.run_batch(ledger=FakeLedger(fail=True)); self.assertEqual(self.provider.calls, [])
        self.assertEqual(r["reserved_credits"], 0)

    def test_kickoff_crossing_retains_reservation_without_replacement(self):
        values = iter([T, T, T + timedelta(days=1), T + timedelta(days=1), T + timedelta(days=1)])
        r = self.run_batch(clock=lambda: next(values))
        self.assertEqual(r["reserved_credits"], 11)
        self.assertFalse(any(self.provider.calls))
        self.seal(r); s.verify_bundle(self.root)

    def test_secret_in_response_forbids_artifact_seal(self):
        p = FakeProvider()
        def bad(_=None):
            return {**FakeProvider().request(), "body": s.canonical({"error": FAKE_KEY})}
        p.request = bad
        r = self.run_batch(p); self.assertEqual(r["reason"], "SECRET_BLOCKED")
        with self.assertRaises(s.Stop): self.seal(r)
        self.assertFalse((self.root / "MANIFEST.json").exists())

    def test_unclaimed_failed_batch_has_no_export_seal(self):
        r = self.run_batch(ledger=FakeLedger(fail=True))
        with self.assertRaisesRegex(s.Stop, "UNCLAIMED_BATCH_NOT_EXPORTABLE"): self.seal(r)

    def test_budget_is_not_unlocked_by_later_quota_increase(self):
        p = FakeProvider(remaining=10); original = p.request; count = 0
        def request(e=None):
            nonlocal count
            count += 1
            if count == 2: p.remaining = 176
            return original(e)
        p.request = request
        r = self.run_batch(p)
        self.assertEqual(r["initial_credit_ceiling"], 10)
        self.assertEqual(r["reserved_credits"], 0); self.assertFalse(any(p.calls))

    def test_changed_or_absent_markets_do_not_authorize_another_request(self):
        p = FakeProvider(); original = p.request
        def empty(e=None):
            r = original(e)
            if e: r["body"] = s.canonical({**event(), "bookmakers": []})
            return r
        p.request = empty; r = self.run_batch(p)
        self.assertEqual(r["status"], "COMPLETE"); self.assertEqual(r["quotes"], [])
        self.assertEqual(sum(x is not None for x in p.calls), 1)
        self.seal(r); s.verify_bundle(self.root)

    def test_event_changed_after_population_freeze_is_not_substituted(self):
        p = FakeProvider(); original = p.request; count = 0
        def change(e=None):
            nonlocal count
            count += 1; r = original(e)
            if count == 2: r["body"] = s.canonical([{**event(), "commence_time": s.stamp(T + timedelta(days=2))}])
            return r
        p.request = change; r = self.run_batch(p)
        self.assertEqual(r["reserved_credits"], 0); self.assertFalse(any(p.calls))

    def test_complete_response_hash_and_clock_are_both_bound(self):
        with self.assertRaisesRegex(s.Stop, "QUOTE_PRECEDES_SAVED_SNAPSHOT"):
            s.normalize(body(), event(), snapshot(), s.stamp(T - timedelta(seconds=1)), "d" * 64)

    def test_ledger_ambiguous_post_reconciles_once_without_second_post(self):
        api = FakeGitHub(); api.ambiguous = True; ledger = s.Ledger(api, {"batch_id": s.BATCH})
        ledger.begin(); self.assertEqual(api.posts, 1); self.assertEqual(ledger.previous["id"], 1)

    def test_ledger_prior_claim_and_duplicate_dispatch_reject(self):
        api = FakeGitHub(); s.Ledger(api, {"batch_id": s.BATCH}).begin()
        with self.assertRaisesRegex(s.Stop, "BATCH_ALREADY_CLAIMED_OR_AMBIGUOUS"):
            s.Ledger(api, {"batch_id": s.BATCH}).begin()
        self.assertEqual(api.posts, 1)

    def test_ledger_modified_record_blocks_next_reservation(self):
        api = FakeGitHub(); ledger = s.Ledger(api, {"batch_id": s.BATCH}); ledger.begin(); api.edit = True
        with self.assertRaisesRegex(s.Stop, "PRIOR_LEDGER_RECORD_CHANGED"):
            ledger.append("RESERVE", {})
        self.assertEqual(api.posts, 1)

    def test_forged_ledger_readback_is_not_a_reservation(self):
        api = FakeGitHub(); api.forged = True
        with self.assertRaisesRegex(s.Stop, "LEDGER_READBACK_UNVERIFIED"):
            s.Ledger(api, {"batch_id": s.BATCH}).begin()

    def test_storage_comment_requires_actual_numeric_capacity_review_and_hardstop(self):
        p = {"schema_version": "odds-study-storage-authorization-v1", "source": "a" * 40,
             "batch_id": s.BATCH, "artifact_max_bytes": s.BUNDLE_LIMIT, "retention_days": 7,
             "no_additional_cost_verified": True, "remaining_storage_verified": True,
             "paid_usage_hard_stop_verified": True, "available_no_cost_storage_bytes": 136 * s.MIB,
             "source_review_completed": True, "source_review_sha256": "c" * 64,
             "public_artifact_contents_approved": True, "cloud_retrieval_recipient": "EXISTING_CODEX_CLOUD",
             "account_evidence_sha256": "b" * 64, "valid_until": s.stamp(T + timedelta(hours=1))}
        def comment(v):
            return {"id": 1, "user": {"id": s.OWNER, "type": "User"}, "created_at": "same", "updated_at": "same",
                    "html_url": "https://github.com/" + s.REPO + "/pull/1#issuecomment-1",
                    "body": "### ODDS_STUDY_STORAGE_AUTHORIZATION\n\n```json\n" + s.canonical(v).decode() + "\n```\n"}
        with mock.patch.object(s, "now", return_value=T):
            self.assertEqual(s.validate_storage(comment(p), {"source": "a" * 40})["id"], 1)
            for key, val in (("available_no_cost_storage_bytes", 136 * s.MIB - 1),
                             ("paid_usage_hard_stop_verified", False), ("source_review_completed", False),
                             ("retention_days", 90), ("source", "e" * 40),
                             ("valid_until", s.stamp(T - timedelta(seconds=1)))):
                with self.subTest(field=key), self.assertRaises(s.Stop):
                    s.validate_storage(comment({**p, key: val}), {"source": "a" * 40})

    def test_non_actions_and_wrong_source_cannot_enter_live_route(self):
        with mock.patch.dict(s.os.environ, {}, clear=True):
            with self.assertRaisesRegex(s.Stop, "UNAPPROVED_EXECUTION_CONTEXT"):
                s.execution_context("a" * 40)

    def test_no_storage_permission_stops_before_provider_or_source_gate(self):
        context = {"source": "a" * 40}
        api = mock.Mock(); api.get.return_value = {}
        with mock.patch.object(s, "execution_context", return_value=context), \
             mock.patch.object(s.subprocess, "check_output", return_value="a" * 40), \
             mock.patch.object(s, "GitHub", return_value=api), \
             mock.patch.object(s, "validate_run_inventory"), \
             mock.patch.object(s, "Provider") as provider, \
             mock.patch.dict(s.os.environ, {"GH_TOKEN": "FICTIONAL_TOKEN", "ODDS_API_KEY": FAKE_KEY}):
            with self.assertRaises(s.Stop): s.collect(self.root, "a" * 40, 1)
            provider.assert_not_called()

    def test_output_bounds_and_symlink_are_rejected_without_truncation(self):
        with mock.patch.object(s, "BUNDLE_LIMIT", s.MIB + 8):
            with self.assertRaisesRegex(s.Stop, "BATCH_SIZE_LIMIT"):
                s.write_file(self.root, "REPORT.json", b"0123456789")
        (self.root / "responses").symlink_to(Path(self.temp.name), target_is_directory=True)
        with self.assertRaisesRegex(s.Stop, "SYMLINK_OUTPUT"):
            s.write_file(self.root, "responses/01.body", b"safe")

    def test_originals_saved_replay_and_deterministic_archive(self):
        r = self.run_batch(); manifest = self.seal(r); v = s.verify_bundle(self.root)
        self.assertEqual(v["manifest_sha256"], manifest)
        self.assertEqual((self.root / "responses/01.body").read_bytes(), s.canonical(body()))
        a = Path(self.temp.name) / "a.tar.gz"; b = Path(self.temp.name) / "b.tar.gz"
        self.assertEqual(s.bundle(self.root, a)["archive_sha256"], s.bundle(self.root, b)["archive_sha256"])
        fresh = Path(self.temp.name) / "fresh"; fresh.mkdir()
        with s.tarfile.open(a) as archive: archive.extractall(fresh, filter="data")
        self.assertEqual(s.verify_bundle(fresh), v)

    def test_self_consistently_rehashed_quote_forgery_fails(self):
        r = self.run_batch(); self.seal(r); r["quotes"][0]["decimal_price"] = "9.9"
        r["comparisons"] = s.compare(self.snapshot, r["quotes"])
        self.rehash("REPORT.json", r)
        with self.assertRaises(s.Stop): s.verify_bundle(self.root)

    def test_self_consistently_rehashed_zero_accounting_fails(self):
        r = self.run_batch(); self.seal(r); r.update(reserved_credits=0, known_request_credits=0, calls=[], reservations=[])
        self.rehash("REPORT.json", r)
        with self.assertRaises(s.Stop): s.verify_bundle(self.root)

    def test_self_consistently_rehashed_population_fails(self):
        r = self.run_batch(); self.seal(r); r["events"] = []
        self.rehash("REPORT.json", r)
        with self.assertRaises(s.Stop): s.verify_bundle(self.root)

    def test_self_consistently_deleted_calls_cannot_report_complete_coverage(self):
        r = self.run_batch(); self.seal(r); r["calls"] = []
        self.rehash("REPORT.json", r)
        with self.assertRaisesRegex(s.Stop, "INCOMPLETE_COMPLETED_CALL_COVERAGE"): s.verify_bundle(self.root)

    def test_uncertain_request_cannot_be_relabelled_complete(self):
        r = self.run_batch(FakeProvider(fail=True)); self.seal(r)
        r.update(status="COMPLETE", reason=None, credits_for_uncertain_requests=None)
        self.rehash("REPORT.json", r)
        with self.assertRaisesRegex(s.Stop, "UNCERTAIN_REQUEST_IS_NOT_COMPLETE"): s.verify_bundle(self.root)

    def test_unchanged_discovery_cannot_be_relabelled_a_changed_event_skip(self):
        r = self.run_batch(FakeProvider(fail=True)); self.seal(r)
        r.update(status="COMPLETE", reason=None, credits_for_uncertain_requests=None,
                 reserved_credits=0, reservations=[])
        r["calls"][0]["status"] = "EVENT_CHANGED_SKIP_NO_REPLACEMENT"
        self.rehash("REPORT.json", r)
        with self.assertRaisesRegex(s.Stop, "FALSE_EVENT_CHANGED_SKIP"): s.verify_bundle(self.root)

    def test_expected_external_manifest_identity_is_checked(self):
        r = self.run_batch(); digest = self.seal(r)
        self.assertEqual(s.verify_bundle(self.root, digest)["manifest_sha256"], digest)
        with self.assertRaisesRegex(s.Stop, "EXTERNAL_MANIFEST_IDENTITY_MISMATCH"):
            s.verify_bundle(self.root, "0" * 64)

    def test_corrupt_missing_extra_and_symlink_files_fail(self):
        r = self.run_batch(); self.seal(r)
        (self.root / "private.txt").write_text("unapproved")
        with self.assertRaises(s.Stop): s.verify_bundle(self.root)
        (self.root / "private.txt").unlink()
        (self.root / "responses/01.body").write_bytes(b"corrupt")
        with self.assertRaises(s.Stop): s.verify_bundle(self.root)

    def test_public_summary_is_closed_and_has_no_quote_or_key(self):
        r = self.run_batch(); self.seal(r); out = s.summary(self.root)
        self.assertEqual(out["schema_version"], "odds-study-summary-v1")
        self.assertNotIn(FAKE_KEY, s.canonical(out).decode()); self.assertIsInstance(out["quotes"], int)
        self.assertNotIn("Fiction Player", s.canonical(out).decode())

    def test_malformed_nonfinite_and_duplicate_json_rejected(self):
        for data in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{bad'):
            with self.assertRaises(s.Stop): s.parse(data)

    def test_storage_booleans_alone_do_not_establish_prerequisite(self):
        c = {"id": 1, "user": {"id": s.OWNER, "type": "User"}, "created_at": "x", "updated_at": "x",
             "html_url": "https://github.com/" + s.REPO + "/pull/1#issuecomment-1",
             "body": '### ODDS_STUDY_STORAGE_AUTHORIZATION\n\n```json\n{"no_additional_cost_verified":true}\n```\n'}
        with self.assertRaises(s.Stop): s.validate_storage(c, {"source": "a" * 40})

    def test_no_network_or_secret_needed_for_contract_and_help(self):
        with mock.patch.object(s.urllib.request.OpenerDirector, "open", side_effect=AssertionError("network")):
            with mock.patch("sys.stdout", new=io.StringIO()) as output:
                self.assertEqual(s.main(["contract"]), 0)
            self.assertNotIn("apiKey", output.getvalue())

    def test_actual_collection_wrapper_and_ledger_with_only_external_boundaries_mocked(self):
        import source_ci
        p = {"schema_version": "odds-study-storage-authorization-v1", "source": "a" * 40,
             "batch_id": s.BATCH, "artifact_max_bytes": s.BUNDLE_LIMIT, "retention_days": 7,
             "no_additional_cost_verified": True, "remaining_storage_verified": True,
             "paid_usage_hard_stop_verified": True, "available_no_cost_storage_bytes": 136 * s.MIB,
             "source_review_completed": True, "source_review_sha256": "c" * 64,
             "public_artifact_contents_approved": True, "cloud_retrieval_recipient": "EXISTING_CODEX_CLOUD",
             "account_evidence_sha256": "b" * 64, "valid_until": s.stamp(T + timedelta(hours=1))}
        auth = {"id": 1, "user": {"id": s.OWNER, "type": "User"}, "created_at": "same", "updated_at": "same",
                "html_url": "https://github.com/" + s.REPO + "/pull/1#issuecomment-1",
                "body": "### ODDS_STUDY_STORAGE_AUTHORIZATION\n\n```json\n" + s.canonical(p).decode() + "\n```\n"}
        class API(FakeGitHub):
            def get(self, path, payload=None):
                if path.startswith("/actions/workflows/"):
                    return {"total_count": 1, "workflow_runs": [{"id": 17}]}
                if path == "/actions/runs/17":
                    return {"id": 17, "head_sha": "a" * 40, "run_attempt": 1, "actor": {"id": s.OWNER},
                            "event": "workflow_dispatch", "path": s.WORKFLOW}
                return super().get(path, payload)
        api = API(); api.comments.append(auth); provider = FakeProvider()
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "GITHUB_REPOSITORY": s.REPO,
               "GITHUB_REPOSITORY_ID": "1411185749", "GITHUB_ACTOR_ID": str(s.OWNER), "GITHUB_RUN_ATTEMPT": "1",
               "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF_NAME": "upgrade/phase2-reproducible-comparison",
               "GITHUB_SHA": "a" * 40, "GITHUB_WORKFLOW_REF": s.REPO + "/" + s.WORKFLOW + "@refs/heads/upgrade/phase2-reproducible-comparison",
               "GITHUB_RUN_ID": "17", "GH_TOKEN": "FICTIONAL_GITHUB_TOKEN_987654321", "ODDS_API_KEY": FAKE_KEY}
        with mock.patch.dict(s.os.environ, env, clear=True), mock.patch.object(s, "now", return_value=T), \
             mock.patch.object(s, "GitHub", return_value=api), mock.patch.object(s, "Provider", return_value=provider), \
             mock.patch.object(s.subprocess, "check_output", return_value="a" * 40), \
             mock.patch.object(source_ci, "verify", return_value={"source_ci_commit": "a" * 40, "run_id": 9}) as source_gate:
            result = s.collect(self.root, "a" * 40, 1)
            self.assertNotIn("ODDS_API_KEY", s.os.environ); self.assertNotIn("GH_TOKEN", s.os.environ)
        self.assertEqual(result["status"], "COMPLETE"); self.assertEqual(result["known_request_credits"], 11)
        self.assertEqual(source_gate.call_count, 1)
        self.assertEqual(s.verify_bundle(self.root)["batch_status"], "COMPLETE")
        self.assertEqual(len(api.comments), 5)  # owner authority + claim/population/reservation/completion

    def test_failed_collect_status_does_not_become_cli_success(self):
        with mock.patch.object(s, "collect", return_value={"status": "FAILED_SAFE"}), \
             mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(s.main(["collect", "--directory", str(self.root), "--code-sha", "a" * 40,
                                     "--storage-comment-id", "1"]), 2)


if __name__ == "__main__":
    unittest.main()

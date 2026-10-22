"""Separate, single-use NFL paper-odds study. Never imported by an updater.

Provider credentials are read only by ``collect`` in the guarded Actions step.
No network occurs on import, in comparison, or in saved-bundle verification.
"""
import argparse
import base64
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

VERSION = "nfl-paper-odds-study-v1"
BATCH = "NFL-WEB-ODDS-ONCE-20261022"
REPO = "NickNicky19/nicks-expert-nfl-picks"
WORKFLOW = ".github/workflows/one-time-odds-study.yml"
OWNER = 208912933
BOT = 41898282
MAX_CREDITS, MAX_GAMES, DAYS = 176, 16, 8
MIB = 1024 ** 2
BODY_LIMIT, BUNDLE_LIMIT = 4 * MIB, 128 * MIB
# A derived report includes every normalized quote plus comparison references;
# it is not one provider entity. Keep both roles finite and keep all byte caps.
ENTITY_NODES, REPORT_NODES = 150000, 500000
DERIVED_NODES = REPORT_NODES - 20000  # fixed <=16-event envelope has ample reserve
MARKETS = {
    "player_pass_yds": "pass_yd", "player_pass_tds": "pass_td",
    "player_pass_completions": "pass_cmp", "player_pass_attempts": "pass_att",
    "player_pass_interceptions": "pass_int", "player_rush_yds": "rush_yd",
    "player_rush_attempts": "rush_att", "player_receptions": "rec",
    "player_reception_yds": "rec_yd", "player_rush_reception_yds": "rush_rec_yd",
    "player_anytime_td": "anytime_td",
}
TEAMS = dict(zip(
    ("Arizona Cardinals|Atlanta Falcons|Baltimore Ravens|Buffalo Bills|Carolina Panthers|"
     "Chicago Bears|Cincinnati Bengals|Cleveland Browns|Dallas Cowboys|Denver Broncos|"
     "Detroit Lions|Green Bay Packers|Houston Texans|Indianapolis Colts|Jacksonville Jaguars|"
     "Kansas City Chiefs|Las Vegas Raiders|Los Angeles Chargers|Los Angeles Rams|Miami Dolphins|"
     "Minnesota Vikings|New England Patriots|New Orleans Saints|New York Giants|New York Jets|"
     "Philadelphia Eagles|Pittsburgh Steelers|San Francisco 49ers|Seattle Seahawks|"
     "Tampa Bay Buccaneers|Tennessee Titans|Washington Commanders").split("|"),
    "ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LV LAC LAR MIA MIN NE NO NYG NYJ PHI PIT SF SEA TB TEN WAS".split()))
SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
FILE = re.compile(r"(?:forecast/(?:week|meta)\.json|SNAPSHOT\.json|REPORT\.json|"
                  r"discovery/[0-9]{2}\.json|responses/[0-9]{2}\.body|"
                  r"requests/(?:discovery-)?[0-9]{2}(?:\.intent)?\.json)\Z")


class Stop(Exception):
    """Only a closed diagnostic code may reach command-line output."""
    def __init__(self, code):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,80}", code):
            code = "INTERNAL_ERROR"
        self.code = code
        super().__init__(code)


def require(value, code):
    if not value:
        raise Stop(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _pairs(values):
    result = {}
    for k, v in values:
        require(k not in result, "DUPLICATE_JSON_KEY")
        result[k] = v
    return result


def structure(value, node_limit=ENTITY_NODES):
    pending = [(value, 0)]; nodes = 0
    while pending:
        v, depth = pending.pop(); nodes += 1
        require(depth <= 24 and nodes <= node_limit, "JSON_STRUCTURE_LIMIT")
        if type(v) is dict:
            pending.extend((x, depth + 1) for x in v.values())
        elif type(v) is list:
            pending.extend((x, depth + 1) for x in v)


def parse(raw, limit=BODY_LIMIT, *, node_limit=ENTITY_NODES):
    require(type(raw) is bytes and len(raw) <= limit, "BOUNDED_JSON_REQUIRED")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Stop("NONFINITE_JSON")))
        # Bound traversal as well as input bytes. Unknown nested provider objects
        # remain original bytes; they do not become executable configuration.
        structure(value, node_limit)
        return value
    except Stop:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise Stop("MALFORMED_JSON") from None


def instant(value):
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(t.tzinfo is not None and t.utcoffset() == timedelta(0), "UTC_CLOCK_REQUIRED")
        return t
    except (AttributeError, ValueError, TypeError):
        raise Stop("INVALID_CLOCK") from None


def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now():
    return datetime.now(timezone.utc)


def number(value):
    require(type(value) in (int, float, str) and not isinstance(value, bool), "INVALID_NUMBER")
    try:
        d = Decimal(str(value))
        require(d.is_finite() and abs(d) <= Decimal("1000000"), "INVALID_NUMBER")
        return d
    except InvalidOperation:
        raise Stop("INVALID_NUMBER") from None


def normalized_name(value):
    require(type(value) is str and 0 < len(value) <= 160, "INVALID_PLAYER_NAME")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[.'’,]", "", value).split())


def assert_no_secret(raw, secrets):
    """Never redact originals in place. Unsafe originals are withheld entirely."""
    for secret in secrets:
        if not secret:
            continue
        variants = {secret, urllib.parse.quote(secret, safe=""),
                    urllib.parse.quote_plus(secret), json.dumps(secret)[1:-1],
                    base64.b64encode(secret.encode()).decode()}
        require(not any(v.encode().lower() in raw.lower() for v in variants), "SECRET_BLOCKED")
        try:
            decoded = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            continue
        require(secret not in json.dumps(decoded, ensure_ascii=False), "SECRET_BLOCKED")


def read_file(path, limit=BUNDLE_LIMIT):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    with path.open("rb") as f:
        raw = f.read(limit + 1)
    require(len(raw) <= limit, "FILE_SIZE_LIMIT")
    return raw


def write_file(root, name, raw, secrets=()):
    require(FILE.fullmatch(name) is not None, "UNAPPROVED_OUTPUT")
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "INVALID_OUTPUT_ROOT")
    assert_no_secret(raw, secrets)
    require(sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) + len(raw)
            <= BUNDLE_LIMIT - MIB, "BATCH_SIZE_LIMIT")
    path = root / name
    require(not path.parent.is_symlink(), "SYMLINK_OUTPUT")
    path.parent.mkdir(exist_ok=True)
    with path.open("xb") as f:
        f.write(raw)
    return {"path": name, "bytes": len(raw), "sha256": sha(raw)}


def make_snapshot(board_raw, meta_raw, binding, observed):
    board, meta = parse(board_raw, 8 * MIB), parse(meta_raw, MIB)
    require(type(board) is dict and type(meta) is dict, "INVALID_SNAPSHOT")
    require(COMMIT.fullmatch(binding.get("commit", "")) and COMMIT.fullmatch(binding.get("tree", "")),
            "SNAPSHOT_SOURCE_REQUIRED")
    require(binding.get("pages_bytes_match_git") is True, "WEBSITE_GIT_MISMATCH")
    require(board.get("season") == meta.get("season") and board.get("week") == meta.get("week")
            and board.get("generated_at") == meta.get("generated_at"), "SNAPSHOT_PERIOD_MISMATCH")
    require(instant(board["generated_at"]) <= observed, "FUTURE_FORECAST_CLOCK")
    games = {}; rows = []; seen = set()
    for game in board.get("games", []):
        require(type(game) is dict and type(game.get("id")) is str and game["id"] not in games,
                "DUPLICATE_OR_INVALID_GAME")
        instant(game["kickoff"])
        require(game["home"] != game["away"] and game["state"] in ("pre", "in", "post"), "INVALID_GAME")
        games[game["id"]] = {k: game[k] for k in ("id", "kickoff", "home", "away", "state")}
    tops = {}
    for side in ("over", "under"):
        for pick in board.get("picks", {}).get(side, []):
            require(pick.get("direction", side) == side, "TOP_SIDE_MISMATCH")
            key = (pick["game_id"], pick["player_id"], pick["key"], side)
            require(key not in tops, "DUPLICATE_TOP_CONTRACT")
            tops[key] = pick
    for player in board.get("players", []):
        require(player.get("game_id") in games and type(player.get("id")) is str, "INVALID_PLAYER_GAME")
        game = games[player["game_id"]]
        require(player.get("team") in (game["home"], game["away"]), "PLAYER_TEAM_MISMATCH")
        for prop in player.get("props", []):
            if prop.get("key") not in MARKETS.values():
                continue
            key = (game["id"], player["id"], prop["key"])
            require(key not in seen, "DUPLICATE_FORECAST")
            seen.add(key)
            row = {"season": board["season"], "week": board["week"], "game_id": game["id"],
                   "player_id": player["id"], "player_name": player["name"], "team": player["team"],
                   "position": player.get("pos"), "kickoff": game["kickoff"], "category": prop["key"],
                   "raw_forecast": prop.get("proj"), "adjusted_forecast": prop.get("adj"),
                   "line": prop.get("line"), "line_source": prop.get("line_from", "ours"),
                   "side": prop.get("lean"), "forecast_generated_at": board["generated_at"],
                   "top_over": False, "top_under": False, "top_contract_status": {}}
            for field in ("raw_forecast", "adjusted_forecast", "line"):
                if row[field] is not None:
                    number(row[field])
            for side in ("over", "under"):
                pick = tops.get((*key, side))
                exact = pick is not None and prop.get("lean") == side and all(k in pick and k in prop and pick[k] == prop[k]
                                                 for k in ("line", "line_from", "proj", "adj"))
                row["top_" + side] = exact
                row["top_contract_status"][side] = "EXACT" if exact else "DIFFERENT_OR_UNSUPPORTED_CONTRACT" if pick else "NOT_SELECTED"
            row["id"] = sha(canonical(row)); rows.append(row)
    return {"schema_version": "odds-website-snapshot-v1", "source": binding,
            "board_sha256": sha(board_raw), "meta_sha256": sha(meta_raw),
            "forecast_generated_at": board["generated_at"], "frozen_at": stamp(observed),
            "season": board["season"], "week": board["week"], "games": list(games.values()),
            "rows": rows, "original_top_contracts": board.get("picks", {}),
            "selection_claim": "SAVED_WEBSITE_SNAPSHOT_NOT_FIRST_SELECTION_PROOF"}


def choose_events(events, cutoff):
    require(type(events) is list and len(events) <= 1000, "INVALID_EVENT_POPULATION")
    result = []; ids = set(); contracts = set()
    for e in events:
        require(type(e) is dict and SAFE_NAME.fullmatch(e.get("id", "")), "INVALID_EVENT_ID")
        require(e["id"] not in ids, "DUPLICATE_EVENT")
        ids.add(e["id"])
        require(e.get("sport_key") == "americanfootball_nfl", "WRONG_SPORT")
        t = instant(e["commence_time"])
        contract = (e["home_team"], e["away_team"], t)
        require(contract not in contracts and e["home_team"] != e["away_team"], "AMBIGUOUS_EVENT_GAME")
        contracts.add(contract)
        if cutoff < t <= cutoff + timedelta(days=DAYS):
            result.append({k: e[k] for k in ("id", "sport_key", "commence_time", "home_team", "away_team")})
    return sorted(result, key=lambda e: (instant(e["commence_time"]), e["id"]))[:MAX_GAMES]


def quota(headers):
    result = {}
    for key, label in (("x-requests-remaining", "remaining"), ("x-requests-used", "used"),
                       ("x-requests-last", "last")):
        v = headers.get(key)
        require(type(v) is str and re.fullmatch(r"[0-9]{1,10}", v), "UNVERIFIED_QUOTA")
        result[label] = int(v)
    return result


def quota_transition(before, after, expected_cost):
    require(after["last"] == expected_cost
            and after["used"] == before["used"] + expected_cost
            and after["remaining"] == before["remaining"] - expected_cost,
            "QUOTA_COUNTERS_CHANGED_OR_AMBIGUOUS")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return None


class Provider:
    """One HTTP attempt; key-bearing transport URLs never leave this object."""
    def __init__(self, key, opener=None):
        require(type(key) is str and 16 <= len(key) <= 256 and key.isascii()
                and not any(ord(x) < 33 for x in key), "MISSING_PROVIDER_SECRET")
        self._key = key
        self._open = (opener or urllib.request.build_opener(NoRedirect())).open

    def request(self, event=None):
        require(event is None or SAFE_NAME.fullmatch(event), "INVALID_EVENT_ID")
        route = "/v4/sports/americanfootball_nfl/events" + ("/" + event + "/odds" if event else "")
        params = {"apiKey": self._key, "dateFormat": "iso"}
        if event:
            params.update(regions="us", markets=",".join(MARKETS), oddsFormat="decimal")
        request = urllib.request.Request("https://api.the-odds-api.com" + route + "?" +
            urllib.parse.urlencode(params), headers={"Accept": "application/json", "Accept-Encoding": "identity"})
        start = now(); response = None
        try:
            try:
                response = self._open(request, timeout=15)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                status = response.status if hasattr(response, "status") else response.code
                raw = response.read(BODY_LIMIT + 1)
                headers = {k.lower(): v for k, v in response.headers.items()
                           if k.lower() in ("x-requests-remaining", "x-requests-used", "x-requests-last", "date", "content-encoding")}
            # Unsupported compression can hide a credential in an error body.
            # Withhold the entity before it can enter any retention path.
            require(headers.get("content-encoding", "identity").lower() in ("identity", ""),
                    "UNSUPPORTED_CONTENT_ENCODING_WITHHELD")
            assert_no_secret(raw, (self._key,))
            assert_no_secret(canonical(headers), (self._key,))
            require(len(raw) <= BODY_LIMIT, "RESPONSE_SIZE_LIMIT")
            return {"http_status": status, "started_at": stamp(start), "retrieved_at": stamp(now()),
                    "headers": headers, "body": raw, "complete_original_entity": True,
                    "route": "event_odds" if event else "events", "event_id": event}
        except Stop:
            raise
        except BaseException:
            # Never stringify HTTPError/URLError/Request, which can contain apiKey.
            raise Stop("PROVIDER_REQUEST_UNCERTAIN_NO_RETRY") from None


def normalize(response, event, snapshot, retrieved_at, body_sha256):
    require(instant(retrieved_at) >= instant(snapshot["frozen_at"]), "QUOTE_PRECEDES_SAVED_SNAPSHOT")
    require(SHA.fullmatch(body_sha256), "SOURCE_BODY_IDENTITY_REQUIRED")
    require(response["id"] == event["id"] and response.get("sport_key") == event["sport_key"]
            and response["home_team"] == event["home_team"] and response["away_team"] == event["away_team"]
            and instant(response["commence_time"]) == instant(event["commence_time"]), "EVENT_RESPONSE_MISMATCH")
    home, away = TEAMS.get(event["home_team"]), TEAMS.get(event["away_team"])
    games = [g for g in snapshot["games"] if (g["home"], g["away"]) == (home, away)
             and instant(g["kickoff"]) == instant(event["commence_time"])] if home and away else []
    game = games[0] if len(games) == 1 else None
    names = defaultdict(dict)
    if game:
        for row in snapshot["rows"]:
            if row["game_id"] == game["id"]:
                names[normalized_name(row["player_name"])][row["player_id"]] = row
    rows = []; unsupported = Counter(); seen = set(); books = set()
    require(type(response.get("bookmakers")) is list and len(response["bookmakers"]) <= 100, "BOOKMAKER_LIMIT")
    for book in response["bookmakers"]:
        key = book.get("key", "")
        require(SAFE_NAME.fullmatch(key) and key not in books, "DUPLICATE_OR_INVALID_BOOK")
        books.add(key)
        for market in book.get("markets", []):
            category = MARKETS.get(market.get("key"))
            if not category:
                unsupported["UNREQUESTED_MARKET"] += 1; continue
            require(type(market.get("outcomes")) is list and len(market["outcomes"]) <= 5000, "OUTCOME_LIMIT")
            for o in market["outcomes"]:
                if o.get("name") not in ("Over", "Under", "Yes", "No"):
                    unsupported["UNSUPPORTED_SIDE"] += 1; continue
                expected = ("Yes", "No") if category == "anytime_td" else ("Over", "Under")
                if o["name"] not in expected:
                    unsupported["UNSUPPORTED_SIDE"] += 1; continue
                desc = o.get("description")
                try:
                    name = normalized_name(desc); price = number(o.get("price"))
                    line = Decimal("0.5") if category == "anytime_td" and o.get("point") is None else number(o.get("point"))
                    require(price > 1 and line >= 0, "UNSUPPORTED_PRICE_OR_LINE")
                except Stop:
                    unsupported["INVALID_PLAYER_PRICE_OR_LINE"] += 1; continue
                candidates = names.get(name, {})
                player = next(iter(candidates.values())) if len(candidates) == 1 else None
                status = "MATCHED_NAME_WITHIN_EXACT_GAME" if player else "UNRESOLVED_PLAYER_OR_GAME"
                if player and category == "pass_int" and player.get("position") != "QB":
                    player = None; status = "UNSUPPORTED_INTERCEPTION_POSITION"
                if category == "anytime_td":
                    status = "TD_RULE_SEMANTICS_UNVERIFIED"
                row = {"event_id": event["id"], "game_id": game["id"] if game else None,
                       "player_id": player["player_id"] if player else None, "player_name": desc,
                       "team": player["team"] if player else None, "book": key,
                       "market": market["key"], "category": category, "period": "full_game",
                       "kickoff": event["commence_time"], "line": str(line),
                       "side": o["name"].lower(), "decimal_price": str(price),
                       "book_updated_at": book.get("last_update"), "market_updated_at": market.get("last_update"),
                       "identity_status": status, "rules_status": "UNVERIFIED",
                       "provider_player_id": None, "source_clock_independently_authenticated": False,
                       "retrieved_at": retrieved_at, "source_body_sha256": body_sha256}
                identity = (row["event_id"], row["book"], row["market"], name, row["line"], row["side"])
                require(identity not in seen, "DUPLICATE_QUOTE_CONTRACT")
                seen.add(identity); row["id"] = sha(canonical(row)); rows.append(row)
    return rows, dict(unsupported)


def compare(snapshot, quotes, *, rules=None):
    """Rules must be separately retained evidence; live v1 supplies none.

    A fixture may supply explicit full-game, overtime/statistic, action/void and
    push definitions to exercise supported arithmetic. This is no certification
    of venue rules and never estimates probabilities from model means.
    """
    groups = defaultdict(list); result = []; rules = rules or {}
    for q in quotes:
        groups[tuple(q[k] for k in ("event_id", "game_id", "player_id", "category", "period", "line"))].append(q)
    snapshots = {(r["game_id"], r["player_id"], r["category"]): r for r in snapshot["rows"]}
    for q in quotes:
        row = snapshots.get((q["game_id"], q["player_id"], q["category"]))
        record = {"quote_id": q["id"], "snapshot_row_id": row["id"] if row else None,
                  "price": q["decimal_price"], "book": q["book"], "line": q["line"],
                  "side": q["side"], "status": "UNVALUED", "reason": None,
                  "market_reference_probability": None, "market_derived_ev_per_unit": None,
                  "reference_quote_ids": [], "reference_is_model_probability": False,
                  "claim": "PAPER_MARKET_DERIVED_NOT_PROVEN_EDGE_NOT_EXECUTABLE"}
        result.append(record)
        if not row or q["identity_status"] != "MATCHED_NAME_WITHIN_EXACT_GAME":
            record["reason"] = "UNRESOLVED_IDENTITY_OR_STATISTIC"; continue
        record.update(saved_raw_forecast=row["raw_forecast"], saved_adjusted_forecast=row["adjusted_forecast"],
                      saved_line=row["line"], saved_side=row["side"], saved_line_source=row["line_source"],
                      saved_top_over=row["top_over"], saved_top_under=row["top_under"],
                      threshold_matches=row["line"] is not None and number(row["line"]) == number(q["line"]),
                      side_matches=row["side"] == q["side"],
                      forecast_age_seconds=(instant(q["retrieved_at"]) - instant(row["forecast_generated_at"])).total_seconds())
        if instant(q["retrieved_at"]) >= instant(row["kickoff"]):
            record["reason"] = "KICKOFF_CROSSED"; continue
        if number(q["line"]) == number(q["line"]).to_integral_value():
            record["reason"] = "INTEGER_PUSH_PROBABILITY_UNKNOWN"; continue
        key = tuple(q[k] for k in ("event_id", "game_id", "player_id", "category", "period", "line"))
        per_book = defaultdict(dict)
        for other in groups[key]:
            per_book[other["book"]][other["side"]] = other
        offering_pair = per_book[q["book"]]
        if set(offering_pair) != {"over", "under"}:
            record["reason"] = "MISSING_OFFERING_BOOK_SIDE"; continue
        references = []
        for book, pair in sorted(per_book.items()):
            if book == q["book"] or set(pair) != {"over", "under"}:
                continue
            # No inferred operator independence, pooling across thresholds or
            # prices from the offering book enters its own reference.
            probabilities = {s: Decimal(1) / number(pair[s]["decimal_price"]) for s in pair}
            p = probabilities[q["side"]] / sum(probabilities.values())
            references.append((book, p, [pair[s]["id"] for s in ("over", "under")]))
        if not references:
            record["reason"] = "NO_OTHER_COMPLETE_BOOK_PAIR"; continue
        record["reference_quote_ids"] = [i for _, _, ids in references for i in ids]
        relevant = list(offering_pair.values()) + [v for b, _, _ in references for v in per_book[b].values()]
        try:
            clocks = [instant(v.get("market_updated_at") or v.get("book_updated_at")) for v in relevant]
            retrieval = instant(q["retrieved_at"])
            require(all(t <= retrieval and (retrieval - t).total_seconds() <= 300 for t in clocks),
                    "PROVIDER_QUOTE_CLOCK_UNSUPPORTED")
        except Stop:
            record["reason"] = "PROVIDER_QUOTE_CLOCK_UNSUPPORTED"; continue
        rule_keys = {(q["book"], q["market"])} | {(book, q["market"]) for book, _, _ in references}
        contracts = [rules.get(k) for k in sorted(rule_keys)]
        if (any(type(c) is not dict for c in contracts) or
                any(set(c) != {"statistic", "period", "overtime", "action_void", "source_sha256"} for c in contracts) or
                any(c["statistic"] != q["category"] or c["period"] != "full_game" or c["overtime"] is not True
                    or not c["action_void"] or not SHA.fullmatch(c["source_sha256"]) for c in contracts) or
                len({c["action_void"] for c in contracts}) != 1):
            record["reason"] = "UNVERIFIED_OR_INCOMPATIBLE_RULES"; continue
        p = sum(x[1] for x in references) / Decimal(len(references))
        record.update(status="MARKET_DERIVED_PAPER_ESTIMATE", reason=None,
                      market_reference_probability=float(p),
                      market_derived_ev_per_unit=float(p * number(q["decimal_price"]) - 1),
                      book_independence="NOT_ESTABLISHED", reference_method="MEAN_OF_OTHER_BOOK_PROPORTIONAL_TWO_SIDE_DEVIG")
    return result


def derivation_fits(snapshot, quotes):
    """Producer and failure replay use the same finite byte AND node contract."""
    value = {"quotes": quotes, "comparisons": compare(snapshot, quotes)}
    if len(canonical(value)) > 32 * MIB:
        return False
    try:
        structure(value, DERIVED_NODES)
    except Stop as error:
        if error.code != "JSON_STRUCTURE_LIMIT":
            raise
        return False
    return True


class GitHub:
    """No unrestricted routes, redirects, retries, update or delete methods."""
    def __init__(self, token):
        require(bool(token), "MISSING_GITHUB_TOKEN")
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect())

    def get(self, path, payload=None):
        require(re.fullmatch(r"/(?:issues/1/comments(?:\?per_page=100&page=[0-9]+)?|issues/comments/[0-9]+|"
                            r"actions/runs/[0-9]+|actions/workflows/one-time-odds-study.yml/runs\?per_page=100&page=[0-9]+)", path),
                "UNAPPROVED_GITHUB_ROUTE")
        require(payload is None or path == "/issues/1/comments", "UNAPPROVED_GITHUB_WRITE")
        request = urllib.request.Request("https://api.github.com/repos/" + REPO + path,
            data=canonical(payload) if payload is not None else None,
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"},
            method="POST" if payload is not None else "GET")
        try:
            with self._opener.open(request, timeout=15) as response:
                raw = response.read(4 * MIB + 1)
            assert_no_secret(raw, (self._token,))
            return parse(raw)
        except Stop:
            raise
        except BaseException:
            raise Stop("GITHUB_REQUEST_UNCERTAIN") from None


def execution_context(code_sha):
    exact = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
             "GITHUB_REPOSITORY": REPO, "GITHUB_REPOSITORY_ID": "1411185749",
             "GITHUB_ACTOR_ID": str(OWNER), "GITHUB_RUN_ATTEMPT": "1",
             "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF_NAME": "upgrade/phase2-reproducible-comparison"}
    require(all(os.environ.get(k) == v for k, v in exact.items()), "UNAPPROVED_EXECUTION_CONTEXT")
    require(COMMIT.fullmatch(code_sha) and os.environ.get("GITHUB_SHA") == code_sha, "WRONG_EXECUTED_SOURCE")
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPO + "/" + WORKFLOW + "@refs/heads/upgrade/phase2-reproducible-comparison",
            "WRONG_EXECUTED_WORKFLOW")
    run = os.environ.get("GITHUB_RUN_ID", "")
    require(re.fullmatch(r"[1-9][0-9]*", run), "MISSING_RUN_IDENTITY")
    return {"run_id": int(run), "attempt": 1, "source": code_sha, "workflow": WORKFLOW,
            "repository": REPO, "actor_id": OWNER, "batch_id": BATCH}


class Ledger:
    MARKER = "### ODDS_STUDY_LEDGER\n"
    def __init__(self, github, context):
        self.github, self.context = github, context
        self.previous = None

    def comments(self):
        all_comments = []
        for page in range(1, 11):
            values = self.github.get("/issues/1/comments?per_page=100&page=" + str(page))
            require(type(values) is list, "INVALID_COMMENT_INVENTORY")
            all_comments.extend(values)
            if len(values) < 100:
                return all_comments
        raise Stop("INCOMPLETE_COMMENT_INVENTORY")

    def begin(self):
        for c in self.comments():
            if c.get("body", "").startswith(self.MARKER) and BATCH in c["body"]:
                raise Stop("BATCH_ALREADY_CLAIMED_OR_AMBIGUOUS")
        return self.append("CLAIM", {"max_credits": MAX_CREDITS, "max_games": MAX_GAMES})

    def append(self, kind, details):
        if self.previous:
            previous = self.github.get("/issues/comments/" + str(self.previous["id"]))
            require(sha(previous.get("body", "").encode()) == self.previous["body_sha256"]
                    and previous.get("created_at") == previous.get("updated_at")
                    and previous.get("user", {}).get("id") == BOT, "PRIOR_LEDGER_RECORD_CHANGED")
        authority = self.context.get("storage_authorization")
        if authority:
            approved = validate_storage(self.github.get("/issues/comments/" + str(authority["id"])), self.context)
            require(approved["body_sha256"] == authority["body_sha256"], "STORAGE_AUTHORITY_CHANGED")
        payload = {"schema_version": "odds-study-ledger-v1", **self.context,
                   "kind": kind, "previous": self.previous, "details": details}
        body = self.MARKER + "\n```json\n" + canonical(payload).decode() + "\n```\n"
        try:
            c = self.github.get("/issues/1/comments", {"body": body})
        except Stop:
            # POST may have succeeded. Reconcile exact unique content once;
            # never issue another POST and never spend before readback.
            matches = [v for v in self.comments() if v.get("body") == body]
            require(len(matches) == 1, "LEDGER_WRITE_AMBIGUOUS")
            c = matches[0]
        c = self.github.get("/issues/comments/" + str(c["id"]))
        require(c.get("body") == body and c.get("created_at") == c.get("updated_at")
                and c.get("user", {}).get("id") == BOT and c["user"].get("type") == "Bot"
                and c.get("html_url") == "https://github.com/" + REPO + "/pull/1#issuecomment-" + str(c["id"]),
                "LEDGER_READBACK_UNVERIFIED")
        self.previous = {"id": c["id"], "body_sha256": sha(body.encode())}
        return self.previous


def validate_storage(comment, context):
    require(comment.get("user", {}).get("id") == OWNER and comment["user"].get("type") == "User"
            and comment.get("created_at") == comment.get("updated_at"), "STORAGE_AUTHORITY_UNVERIFIED")
    require(comment.get("html_url") == "https://github.com/" + REPO + "/pull/1#issuecomment-" + str(comment.get("id")),
            "STORAGE_AUTHORITY_UNVERIFIED")
    body = comment.get("body", "")
    require(body.startswith("### ODDS_STUDY_STORAGE_AUTHORIZATION\n"), "STORAGE_APPROVAL_REQUIRED")
    blocks = re.findall(r"```json\s*\n(.*?)\n```", body, re.S)
    require(len(blocks) == 1, "STORAGE_APPROVAL_REQUIRED")
    p = parse(blocks[0].encode())
    require(p.get("schema_version") == "odds-study-storage-authorization-v1"
            and p.get("batch_id") == BATCH and p.get("source") == context["source"]
            and p.get("artifact_max_bytes") == BUNDLE_LIMIT and p.get("retention_days") == 7
            and p.get("no_additional_cost_verified") is True and p.get("remaining_storage_verified") is True
            and p.get("paid_usage_hard_stop_verified") is True
            and type(p.get("available_no_cost_storage_bytes")) is int and p["available_no_cost_storage_bytes"] >= 136 * MIB
            and p.get("source_review_completed") is True and SHA.fullmatch(p.get("source_review_sha256", ""))
            and p.get("public_artifact_contents_approved") is True
            and p.get("cloud_retrieval_recipient") == "EXISTING_CODEX_CLOUD"
            and SHA.fullmatch(p.get("account_evidence_sha256", "")), "STORAGE_PREREQUISITE_UNMET")
    require(instant(p["valid_until"]) > now(), "STORAGE_APPROVAL_EXPIRED")
    return {"id": comment["id"], "body_sha256": sha(body.encode()), "authorization": p}


def validate_run_inventory(github, context):
    runs = []
    for page in range(1, 11):
        value = github.get("/actions/workflows/one-time-odds-study.yml/runs?per_page=100&page=" + str(page))
        items = value.get("workflow_runs")
        require(type(items) is list and type(value.get("total_count")) is int, "INCOMPLETE_RUN_INVENTORY")
        runs.extend(items)
        if len(runs) >= value["total_count"]:
            break
    else:
        raise Stop("INCOMPLETE_RUN_INVENTORY")
    require(len(runs) == 1 and runs[0]["id"] == context["run_id"], "PRIOR_OR_COMPETING_INVOCATION")
    r = github.get("/actions/runs/" + str(context["run_id"]))
    require(r.get("head_sha") == context["source"] and r.get("run_attempt") == 1
            and r.get("actor", {}).get("id") == OWNER and r.get("event") == "workflow_dispatch"
            and r.get("path") == WORKFLOW, "ACTUAL_RUN_IDENTITY_UNVERIFIED")


def collect_batch(directory, snapshot, provider, ledger, *, clock=now, secrets=()):
    """Worst-case reservations are never refunded or reused, including failure."""
    root = Path(directory); reserved = 0; actual = 0; calls = []; unsupported = Counter(); quotes = []
    status = "COMPLETE"; reason = None; start = clock(); events = []; ceiling = 0; reservations = []; population_cutoff = None; claimed = False
    try:
        ledger.begin()
        claimed = True
        response = provider.request()
        save_response(root, response, 0, discovery=True, secrets=secrets)
        require(response["http_status"] == 200, "DISCOVERY_HTTP_FAILURE")
        q = quota(response["headers"]); actual += q["last"]
        require(q["last"] == 0, "DISCOVERY_UNEXPECTEDLY_CHARGED")
        initial_quota = q; ceiling = min(MAX_CREDITS, q["remaining"])
        population_cutoff = response["retrieved_at"]
        events = choose_events(parse(response["body"]), instant(population_cutoff))
        ledger.append("POPULATION", {"event_ids": [e["id"] for e in events],
            "population_sha256": sha(canonical(events)), "snapshot_sha256": sha(canonical(snapshot)),
            "forecast_generated_at": snapshot["forecast_generated_at"], "initial_quota": initial_quota})
        for i, event in enumerate(events, 1):
            observed = clock()
            if observed >= instant(event["commence_time"]):
                calls.append({"event_id": event["id"], "status": "STARTED_SKIP_NO_REPLACEMENT", "observed_at": stamp(observed)}); continue
            # Bounded uncharged refresh before each reservation, no charged
            # markets-discovery endpoint and no polling/background continuation.
            fresh = provider.request()
            save_response(root, fresh, i, discovery=True, secrets=secrets)
            require(fresh["http_status"] == 200, "DISCOVERY_HTTP_FAILURE")
            previous = q; q = quota(fresh["headers"]); actual += q["last"]
            require(q["last"] == 0, "DISCOVERY_UNEXPECTEDLY_CHARGED")
            quota_transition(previous, q, 0)
            current = [e for e in parse(fresh["body"]) if e.get("id") == event["id"]]
            if len(current) != 1 or any(current[0].get(k) != event[k] for k in event):
                calls.append({"event_id": event["id"], "status": "EVENT_CHANGED_SKIP_NO_REPLACEMENT"}); continue
            require(reserved + len(MARKETS) <= ceiling and q["remaining"] >= len(MARKETS), "INSUFFICIENT_VERIFIED_CREDITS")
            request = {"event_id": event["id"], "region": "us", "markets": list(MARKETS), "odds_format": "decimal"}
            ledger.append("RESERVE", {"ordinal": i, "request_sha256": sha(canonical(request)),
                "event_id": event["id"], "reserved": len(MARKETS), "reserved_total": reserved + len(MARKETS),
                "verified_remaining": q["remaining"]})
            reserved += len(MARKETS)
            intent = {"event_id": event["id"], "request": request, "ordinal": i,
                      "reservation": ledger.previous, "reserved_at": stamp(clock()), "retry_allowed": False,
                      "reserved_credits": len(MARKETS), "quota_before": q, "reserved_total": reserved}
            reservations.append(intent)
            write_file(root, f"requests/{i:02d}.intent.json", canonical(intent), secrets)
            observed = clock()
            if observed >= instant(event["commence_time"]):
                calls.append({"event_id": event["id"], "status": "STARTED_AFTER_RESERVATION_NO_REQUEST", "observed_at": stamp(observed)}); continue
            call = {"event_id": event["id"], "status": "REQUEST_UNCERTAIN_RESERVATION_RETAINED"}
            calls.append(call)
            r = provider.request(event["id"])
            save_response(root, r, i, secrets=secrets)
            previous = q; q = quota(r["headers"]); actual += q["last"]
            call.update(status="RESPONSE_RECEIVED", quota=q,
                        body_sha256=sha(r["body"]), retrieved_at=r["retrieved_at"])
            require(q["last"] <= len(MARKETS), "CREDIT_BOUND_VIOLATION")
            quota_transition(previous, q, q["last"])
            require(r["http_status"] == 200, "EVENT_HTTP_FAILURE_NO_RETRY")
            require(r["headers"].get("content-encoding", "identity") in ("identity", ""), "UNSUPPORTED_CONTENT_ENCODING")
            rows, excluded = normalize(parse(r["body"]), event, snapshot, r["retrieved_at"], sha(r["body"]))
            # Source originals remain complete and immutable if derived expansion
            # exceeds this finite study's budget; do not spend on another game.
            require(derivation_fits(snapshot, quotes + rows),
                    "DERIVED_REPORT_LIMIT_SOURCE_RETAINED")
            quotes.extend(rows); unsupported.update(excluded)
    except Stop as error:
        status, reason = "FAILED_SAFE", error.code
    except BaseException:
        status, reason = "FAILED_SAFE", "INTERNAL_ERROR"
    report = {"schema_version": VERSION, "batch_id": BATCH, "status": status, "reason": reason,
              "started_at": stamp(start), "finished_at": stamp(clock()), "reserved_credits": reserved,
              "initial_credit_ceiling": ceiling, "events": events,
              "population_cutoff": population_cutoff,
              "reservations": reservations,
              "claimed": claimed,
              "known_request_credits": actual, "credits_for_uncertain_requests": "UNKNOWN_RESERVATION_RETAINED" if status != "COMPLETE" else None,
              "calls": calls, "quotes": quotes, "comparisons": compare(snapshot, quotes),
              "unsupported": dict(unsupported), "snapshot_sha256": sha(canonical(snapshot)),
              "forecast_regenerated": False, "financial_parlay_valuation": "UNAVAILABLE",
              "rules": "NO_VENUE_RULES_AUTHENTICATED_LIVE_EV_UNVALUED", "key_rotation_performed": False}
    report["collection_identity"] = getattr(ledger, "context", {})
    if reason == "SECRET_BLOCKED":
        return report  # No artifact seal or upload after an unsafe original.
    structure(report, REPORT_NODES)
    write_file(root, "REPORT.json", canonical(report), secrets)
    return report


def save_response(root, response, ordinal, *, discovery=False, secrets=()):
    # No URL, unrestricted header, request object or exception is serialized.
    kind = "discovery" if discovery else "responses"
    name = f"{kind}/{ordinal:02d}." + ("json" if discovery else "body")
    require(len(response["body"]) <= (MIB if discovery else BODY_LIMIT), "RESPONSE_SIZE_LIMIT")
    if discovery:
        require(sum(p.stat().st_size for p in (Path(root) / "discovery").glob("*.json")) + len(response["body"]) <= 8 * MIB,
                "DISCOVERY_SIZE_LIMIT")
    write_file(root, name, response["body"], secrets)
    receipt = {k: response[k] for k in ("http_status", "started_at", "retrieved_at", "headers",
               "complete_original_entity", "route", "event_id")}
    receipt.update(body_sha256=sha(response["body"]), body_bytes=len(response["body"]),
                   source_time_claim="PROVIDER_HEADER_NOT_INDEPENDENTLY_AUTHENTICATED")
    write_file(root, "requests/" + ("discovery-" if discovery else "") + f"{ordinal:02d}.json", canonical(receipt), secrets)


def seal_bundle(directory, report, secrets=()):
    root = Path(directory); files = []
    require(report.get("reason") != "SECRET_BLOCKED", "SECRET_BLOCKED")
    require(report.get("claimed") is True, "UNCLAIMED_BATCH_NOT_EXPORTABLE")
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "SYMLINK_OUTPUT")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        require(FILE.fullmatch(name) is not None, "UNAPPROVED_OUTPUT")
        raw = read_file(path); assert_no_secret(raw, secrets)
        files.append({"path": name, "bytes": len(raw), "sha256": sha(raw)})
    require(sum(f["bytes"] for f in files) <= BUNDLE_LIMIT - MIB, "BATCH_SIZE_LIMIT")
    manifest = {"schema_version": "odds-study-bundle-v1", "batch_id": BATCH,
                "status": report["status"], "files": files,
                "upload_eligible": True, "secret_scan": "ALL_ALLOWLISTED_ACTUAL_BYTES_BEFORE_SEAL",
                "retention_days": 7, "original_entities_not_redacted": True}
    raw = canonical(manifest); assert_no_secret(raw, secrets)
    with (root / "MANIFEST.json").open("xb") as f:
        f.write(raw)
    return sha(raw)


def verify_bundle(directory, expected_manifest_sha256=None):
    root = Path(directory); manifest = parse(read_file(root / "MANIFEST.json"))
    if expected_manifest_sha256 is not None:
        require(SHA.fullmatch(expected_manifest_sha256) and sha(read_file(root / "MANIFEST.json")) == expected_manifest_sha256,
                "EXTERNAL_MANIFEST_IDENTITY_MISMATCH")
    require(manifest.get("schema_version") == "odds-study-bundle-v1" and manifest.get("batch_id") == BATCH
            and manifest.get("upload_eligible") is True and manifest.get("retention_days") == 7, "UNSUPPORTED_BUNDLE")
    expected = {"MANIFEST.json"}; total = 0
    require(len(manifest["files"]) <= 150, "BUNDLE_FILE_COUNT_LIMIT")
    for item in manifest["files"]:
        name = item["path"]
        require(FILE.fullmatch(name) and name not in expected, "DUPLICATE_OR_UNAPPROVED_OUTPUT")
        expected.add(name); raw = read_file(root / name)
        require(sha(raw) == item["sha256"] and len(raw) == item["bytes"], "CHANGED_BUNDLE_BYTES")
        total += len(raw)
    require(total <= BUNDLE_LIMIT - MIB and {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} == expected,
            "BUNDLE_INVENTORY_MISMATCH")
    snapshot = parse(read_file(root / "SNAPSHOT.json"), 16 * MIB)
    b, m = read_file(root / "forecast/week.json"), read_file(root / "forecast/meta.json")
    rebuilt = make_snapshot(b, m, snapshot["source"], instant(snapshot["frozen_at"]))
    require(rebuilt == snapshot, "SAVED_SNAPSHOT_MISMATCH")
    report = parse(read_file(root / "REPORT.json"), 64 * MIB, node_limit=REPORT_NODES)
    require(report.get("schema_version") == VERSION and report.get("batch_id") == BATCH
            and report.get("status") in ("COMPLETE", "FAILED_SAFE") and report.get("claimed") is True,
            "UNSUPPORTED_STUDY_REPORT")
    require(report["snapshot_sha256"] == sha(canonical(snapshot)) and report["comparisons"] == compare(snapshot, report["quotes"]),
            "SAVED_COMPARISON_MISMATCH")
    initial_receipt = root / "requests/discovery-00.json"
    if initial_receipt.exists():
        first = parse(read_file(initial_receipt)); raw_events = read_file(root / "discovery/00.json")
        require(first["body_sha256"] == sha(raw_events) and first["body_bytes"] == len(raw_events), "DISCOVERY_RECEIPT_MISMATCH")
        if first["http_status"] == 200:
            first_q = quota(first["headers"])
            expected_events = choose_events(parse(raw_events), instant(first["retrieved_at"])) if first_q["last"] == 0 else []
            require(expected_events == report["events"], "SAVED_POPULATION_MISMATCH")
            require(report["initial_credit_ceiling"] == (min(MAX_CREDITS, first_q["remaining"]) if first_q["last"] == 0 else 0),
                    "CREDIT_CEILING_MISMATCH")
            if first_q["last"] == 0:
                require(report["population_cutoff"] == first["retrieved_at"], "POPULATION_CLOCK_MISMATCH")
    elif report["status"] == "COMPLETE":
        raise Stop("MISSING_INITIAL_DISCOVERY")
    reservations = report["reservations"]; expected_reserved = 0; ordinals = set()
    for intent in reservations:
        ordinal = intent["ordinal"]
        require(type(ordinal) is int and 1 <= ordinal <= len(report["events"]) and ordinal not in ordinals, "RESERVATION_IDENTITY_MISMATCH")
        ordinals.add(ordinal); expected_reserved += len(MARKETS)
        e = report["events"][ordinal - 1]
        require(intent["event_id"] == e["id"] and intent["request"] == {"event_id": e["id"], "region": "us", "markets": list(MARKETS), "odds_format": "decimal"}
                and intent["reserved_credits"] == len(MARKETS) and intent["reserved_total"] == expected_reserved
                and intent["quota_before"]["remaining"] >= len(MARKETS)
                and SHA.fullmatch(intent["reservation"]["body_sha256"]) and type(intent["reservation"]["id"]) is int,
                "RESERVATION_IDENTITY_MISMATCH")
        intent_path = root / "requests" / f"{ordinal:02d}.intent.json"
        require(parse(read_file(intent_path)) == intent, "RESERVATION_RECEIPT_MISMATCH")
        instant(intent["reserved_at"])
    require(report["reserved_credits"] == expected_reserved <= report["initial_credit_ceiling"] <= MAX_CREDITS,
            "CREDIT_RESERVATION_MISMATCH")
    known = 0
    for p in sorted((root / "requests").glob("*.json")):
        if p.name.endswith(".intent.json"):
            continue
        receipt = parse(read_file(p))
        try:
            known += quota(receipt["headers"])["last"]
        except Stop:
            require(report["status"] != "COMPLETE", "UNVERIFIED_COMPLETED_QUOTA")
    require(report["known_request_credits"] == known, "SAVED_CREDIT_ACCOUNTING_MISMATCH")
    if report["status"] == "COMPLETE":
        require(known <= expected_reserved and report["reason"] is None, "CREDIT_BOUND_VIOLATION")
    calls = {}; eligible_ids = {e["id"] for e in report["events"]}
    for call in report["calls"]:
        require(call["event_id"] in eligible_ids and call["event_id"] not in calls, "CALL_IDENTITY_MISMATCH")
        calls[call["event_id"]] = call
        ordinal, e = next((i, e) for i, e in enumerate(report["events"], 1) if e["id"] == call["event_id"])
        disposition = call["status"]
        require(disposition in ("RESPONSE_RECEIVED", "REQUEST_UNCERTAIN_RESERVATION_RETAINED",
                "STARTED_SKIP_NO_REPLACEMENT", "STARTED_AFTER_RESERVATION_NO_REQUEST", "EVENT_CHANGED_SKIP_NO_REPLACEMENT"),
                "UNSUPPORTED_CALL_DISPOSITION")
        if report["status"] == "COMPLETE":
            require(disposition != "REQUEST_UNCERTAIN_RESERVATION_RETAINED", "UNCERTAIN_REQUEST_IS_NOT_COMPLETE")
        if disposition in ("RESPONSE_RECEIVED", "REQUEST_UNCERTAIN_RESERVATION_RETAINED", "STARTED_AFTER_RESERVATION_NO_REQUEST"):
            require(ordinal in ordinals, "MISSING_CALL_RESERVATION")
        else:
            require(ordinal not in ordinals, "SKIPPED_CALL_HAS_RESERVATION")
        if disposition == "RESPONSE_RECEIVED":
            require((root / "responses" / f"{ordinal:02d}.body").is_file()
                    and (root / "requests" / f"{ordinal:02d}.json").is_file(), "MISSING_RECEIVED_BODY")
        if disposition == "EVENT_CHANGED_SKIP_NO_REPLACEMENT":
            original = read_file(root / "discovery" / f"{ordinal:02d}.json")
            proof = parse(read_file(root / "requests" / f"discovery-{ordinal:02d}.json"))
            require(proof["body_sha256"] == sha(original) and proof["http_status"] == 200, "INVALID_SKIP_DISCOVERY")
            matches = [v for v in parse(original) if v.get("id") == e["id"]]
            require(len(matches) != 1 or any(matches[0].get(k) != e[k] for k in e), "FALSE_EVENT_CHANGED_SKIP")
        if call["status"] in ("STARTED_SKIP_NO_REPLACEMENT", "STARTED_AFTER_RESERVATION_NO_REQUEST"):
            require(instant(call["observed_at"]) >= instant(e["commence_time"]), "FALSE_STARTED_SKIP")
    if report["status"] == "COMPLETE":
        require(set(calls) == eligible_ids, "INCOMPLETE_COMPLETED_CALL_COVERAGE")
    # Re-read original entities and reconstruct actual normalization. Self-
    # consistently changing a report and its manifest is not a semantic proof.
    rebuilt_quotes = []; rebuilt_unsupported = Counter(); successful_entities = 0
    events = {e["id"]: e for e in report["events"]}
    for path in sorted((root / "responses").glob("*.body")):
        n = path.stem; body = read_file(path, BODY_LIMIT)
        receipt = parse(read_file(root / "requests" / (n + ".json")))
        require(receipt["body_sha256"] == sha(body) and receipt["body_bytes"] == len(body)
                and receipt["complete_original_entity"] is True, "RESPONSE_RECEIPT_MISMATCH")
        call = calls.get(receipt["event_id"])
        require(call is not None, "MISSING_RESPONSE_CALL")
        try:
            event_q = quota(receipt["headers"])
        except Stop:
            require(report["status"] != "COMPLETE", "UNVERIFIED_COMPLETED_QUOTA")
        else:
            require(call["status"] == "RESPONSE_RECEIVED" and call.get("body_sha256") == sha(body)
                    and call.get("quota") == event_q and call.get("retrieved_at") == receipt["retrieved_at"],
                    "SAVED_CALL_ACCOUNTING_MISMATCH")
        if receipt["http_status"] != 200:
            continue
        require(receipt["event_id"] in events, "WRONG_RESPONSE_EVENT")
        try:
            require(int(n) in ordinals, "MISSING_RESPONSE_RESERVATION")
            fresh_receipt = parse(read_file(root / "requests" / ("discovery-" + n + ".json")))
            fresh_q = quota(fresh_receipt["headers"]); event_q = quota(receipt["headers"])
            require(event_q["last"] <= len(MARKETS), "CREDIT_BOUND_VIOLATION")
            quota_transition(fresh_q, event_q, event_q["last"])
            rows, unsupported = normalize(parse(body), events[receipt["event_id"]], snapshot,
                                          receipt["retrieved_at"], sha(body))
        except Stop:
            require(report["status"] != "COMPLETE", "INVALID_COMPLETED_RESPONSE")
            continue
        if report["reason"] == "DERIVED_REPORT_LIMIT_SOURCE_RETAINED" and len(rebuilt_quotes) == len(report["quotes"]):
            require(not derivation_fits(snapshot, rebuilt_quotes + rows),
                    "FALSE_DERIVED_SIZE_FAILURE")
            continue
        rebuilt_quotes.extend(rows); rebuilt_unsupported.update(unsupported); successful_entities += 1
    require(rebuilt_quotes == report["quotes"] and dict(rebuilt_unsupported) == report["unsupported"], "SAVED_NORMALIZATION_MISMATCH")
    return {"status": "VERIFIED_SAVED_BUNDLE", "batch_status": report["status"], "files": len(expected),
            "decoded_bytes": total, "manifest_sha256": sha(read_file(root / "MANIFEST.json")),
            "reserved_credits": report["reserved_credits"], "known_request_credits": report["known_request_credits"]}


def summary(directory):
    verified = verify_bundle(directory)
    report = parse(read_file(Path(directory) / "REPORT.json"), 64 * MIB, node_limit=REPORT_NODES)
    unsupported = dict(Counter(r["reason"] for r in report["comparisons"] if r["reason"]) + Counter(report["unsupported"]))
    result = {"schema_version": "odds-study-summary-v1", **verified,
              "quotes": len(report["quotes"]), "comparisons": len(report["comparisons"]),
              "valued": sum(r["market_derived_ev_per_unit"] is not None for r in report["comparisons"]),
              "unsupported": sum(unsupported.values()), "unsupported_reasons": unsupported,
              "key_rotation_performed": False,
              "provider_requests": sum(c["status"] in ("REQUEST_UNCERTAIN_RESERVATION_RETAINED", "RESPONSE_RECEIVED") for c in report["calls"])}
    require(len(canonical(result)) <= 65536, "SUMMARY_SIZE_LIMIT")
    return result


def bundle(directory, output):
    verified = verify_bundle(directory); root = Path(directory)
    with Path(output).open("xb") as target:
        with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(root.rglob("*")):
                    if not path.is_file():
                        continue
                    raw = read_file(path); info = tarfile.TarInfo(path.relative_to(root).as_posix())
                    info.size = len(raw); info.mode = 0o644; info.mtime = 0
                    archive.addfile(info, io.BytesIO(raw))
    require(Path(output).stat().st_size <= BUNDLE_LIMIT, "ARCHIVE_SIZE_LIMIT")
    return {**verified, "archive_sha256": sha(read_file(output)), "archive_bytes": Path(output).stat().st_size}


def freeze(root, output, main_sha):
    require(COMMIT.fullmatch(main_sha), "SNAPSHOT_SOURCE_REQUIRED")
    raw = {}; retrievals = {}
    for kind in ("week", "meta"):
        raw[kind] = subprocess.check_output(["git", "-C", str(root), "show", main_sha + ":output/data/" + kind + ".json"])
        request = urllib.request.Request("https://nicknicky19.github.io/nicks-expert-nfl-picks/data/" + kind + ".json",
                                         headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity"})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            website = response.read(8 * MIB + 1)
            retrievals[kind] = {"retrieved_at": stamp(now()), "http_date": response.headers.get("Date"),
                                "claim": "PUBLIC_RETRIEVAL_NOT_ORIGINAL_PROVIDER_PUBLICATION_TIME"}
        require(website == raw[kind], "WEBSITE_GIT_MISMATCH")
    tree = subprocess.check_output(["git", "-C", str(root), "rev-parse", main_sha + "^{tree}"], text=True).strip()
    snapshot = make_snapshot(raw["week"], raw["meta"], {"commit": main_sha, "tree": tree,
        "pages_bytes_match_git": True, "public_retrievals": retrievals,
        "claim": "ACTUALLY_RETRIEVED_PUBLIC_BYTES_EQUAL_PINNED_GIT_DATA"}, now())
    Path(output).mkdir(mode=0o700)
    for kind in ("week", "meta"):
        write_file(output, "forecast/" + kind + ".json", raw[kind])
    write_file(output, "SNAPSHOT.json", canonical(snapshot))
    return {"status": "FROZEN_ORIGINAL_WEBSITE_SNAPSHOT", "snapshot_sha256": sha(canonical(snapshot)),
            "source": main_sha, "forecast_generated_at": snapshot["forecast_generated_at"]}


def collect(directory, code_sha, storage_comment_id):
    context = execution_context(code_sha)
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == code_sha, "WRONG_EXECUTED_SOURCE")
    token = os.environ.pop("GH_TOKEN", ""); key = os.environ.pop("ODDS_API_KEY", "")
    github = GitHub(token)
    validate_run_inventory(github, context)
    storage = validate_storage(github.get("/issues/comments/" + str(storage_comment_id)), context)
    import source_ci
    source_api = source_ci.GitHub(); source_api.token = token
    source_proof = source_ci.verify(Path.cwd(), api=source_api)
    snapshot = parse(read_file(Path(directory) / "SNAPSHOT.json"), 16 * MIB)
    rebuilt = make_snapshot(read_file(Path(directory) / "forecast/week.json"),
        read_file(Path(directory) / "forecast/meta.json"), snapshot["source"], instant(snapshot["frozen_at"]))
    require(snapshot == rebuilt, "CHANGED_SNAPSHOT")
    ledger = Ledger(github, {**context, "source_ci": source_proof,
                            "storage_authorization": {k: storage[k] for k in ("id", "body_sha256")}})
    report = collect_batch(directory, snapshot, Provider(key), ledger, clock=now, secrets=(key, token))
    require(report["claimed"], "UNCLAIMED_BATCH_NOT_EXPORTABLE")
    digest = seal_bundle(directory, report, (key, token))
    ledger.append("COMPLETED_OR_STOPPED", {"manifest_sha256": digest, "status": report["status"],
        "reserved_credits": report["reserved_credits"], "known_request_credits": report["known_request_credits"]})
    return {"status": report["status"], "manifest_sha256": digest,
            "reserved_credits": report["reserved_credits"], "known_request_credits": report["known_request_credits"]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("contract", "freeze", "collect", "verify", "bundle", "summary"))
    p.add_argument("--root", type=Path, default=Path.cwd()); p.add_argument("--output", type=Path)
    p.add_argument("--directory", type=Path); p.add_argument("--main-sha"); p.add_argument("--code-sha")
    p.add_argument("--storage-comment-id", type=int)
    p.add_argument("--expected-manifest-sha256")
    a = p.parse_args(argv)
    try:
        if a.command == "contract":
            value = {"schema_version": VERSION, "batch_id": BATCH, "markets": MARKETS, "region": "us",
                     "max_credits": MAX_CREDITS, "max_games": MAX_GAMES, "next_days": DAYS,
                     "max_output_bytes": BUNDLE_LIMIT, "retention_days": 7, "live_acquisition": "STORAGE_PREREQUISITE_REQUIRED"}
        elif a.command == "freeze":
            value = freeze(a.root, a.output, a.main_sha)
        elif a.command == "collect":
            value = collect(a.directory, a.code_sha, a.storage_comment_id)
        elif a.command == "verify":
            value = verify_bundle(a.directory, a.expected_manifest_sha256)
        elif a.command == "summary":
            value = summary(a.directory)
        else:
            value = bundle(a.directory, a.output)
        print(canonical(value).decode())
        return 2 if a.command == "collect" and value["status"] != "COMPLETE" else 0
    except BaseException as error:
        print(canonical({"status": "STUDY_STOPPED", "code": error.code if isinstance(error, Stop) else "INTERNAL_ERROR",
                         "retry_authorized": False}).decode()); return 2


if __name__ == "__main__":
    raise SystemExit(main())

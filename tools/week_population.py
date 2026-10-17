"""Manual prospective full-week membership capture; no forecasts or scheduler.

Only the checked 2026 regular-season source/club contract is supported. A local
receipt proves what these two public sources returned, not provider authenticity,
forecast accuracy, a completed week, or publication on the website.
"""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit

import requests

from evidence import read, write
from reliability import IntegrityError, _pairs, digest, stamp, utc
from source_evidence import SCOREBOARD_URL, normalized_games

ROOT = Path(__file__).resolve().parents[1]
VERSION = "week-population-espn-nfl-v1"
SOURCE = "independently_matched_ESPN_and_official_NFL_full_week"
BODY_HASH = "sha256-http-decoded-utf8-body-v1"
JSON_HASH = "sha256-canonical-decoded-json-v1"
MAX_COLLECTION_SECONDS = 120
# Pinned from the official 2026 Week 7 games/bye partition, observed on
# 2026-10-15T23:57:36.548178Z. Full HTTP-decoded document SHA-256:
# 83762c55619e031b884b3c559d4a7f9eda31eac3377c1982b052ca0f80deec71.
# https://www.nfl.com/schedules/2026/by-week/week-7
# A different season/club identity contract needs a reviewed adapter version.
CLUBS_2026 = {
    "Arizona Cardinals": "10403800-517c-7b8c-65a3-c61b95d86123",
    "Atlanta Falcons": "10400200-f401-4e53-5175-0974e4f16cf7",
    "Baltimore Ravens": "10400325-48de-3d6a-be29-8f829437f4c8",
    "Buffalo Bills": "10400610-c40e-a673-1743-2ce2a5d5d731",
    "Carolina Panthers": "10400750-259b-33ac-eee3-a3852e83cd1f",
    "Chicago Bears": "10400810-db30-43d6-221c-620006f3ca19",
    "Cincinnati Bengals": "10400920-57c1-7656-e77e-1af3d900483e",
    "Cleveland Browns": "10401050-5e38-b907-1be1-55b91b19c057",
    "Dallas Cowboys": "10401200-a308-98ca-ad5f-95df2fefea68",
    "Denver Broncos": "10401400-b89b-96e5-55d1-caa7e18de3d8",
    "Detroit Lions": "10401540-f97c-2d19-6fcd-fac6490a48b7",
    "Green Bay Packers": "10401800-ab22-323d-721a-cee4713c4c2d",
    "Houston Texans": "10402120-b0bc-693d-098a-803014096eb0",
    "Indianapolis Colts": "10402200-2ea3-84c3-e627-6a6b3b39d56d",
    "Jacksonville Jaguars": "10402250-89fe-7b86-ef98-9062cd354256",
    "Kansas City Chiefs": "10402310-a47e-10ea-7442-16b633633637",
    "Las Vegas Raiders": "10402520-96bf-e9f2-4f68-8521ca896060",
    "Los Angeles Chargers": "10404400-3b35-073f-197e-194bb8240723",
    "Los Angeles Rams": "10402510-8931-0d5f-9815-79bb79649a65",
    "Miami Dolphins": "10402700-1662-d8ad-f45c-0b0ea460d045",
    "Minnesota Vikings": "10403000-5851-f9d5-da45-78365a05b6b0",
    "New England Patriots": "10403200-69ab-9ea6-5af5-e240fbc08bea",
    "New Orleans Saints": "10403300-f235-cf9b-6d3a-2f182be48dd1",
    "New York Giants": "10403410-997c-9c75-256b-3b012f468bd0",
    "New York Jets": "10403430-1bc3-42c4-c7d8-39f38aed5f12",
    "Philadelphia Eagles": "10403700-b939-3cbd-3d16-24d4d6742fa2",
    "Pittsburgh Steelers": "10403900-8251-6892-d81c-4348525c2d47",
    "San Francisco 49ers": "10404500-e7cb-7fce-3f10-4eeb269bd179",
    "Seattle Seahawks": "10404600-adcd-28ac-5826-b4d95ec2a228",
    "Tampa Bay Buccaneers": "10404900-d59e-b449-ef75-961e09ca027e",
    "Tennessee Titans": "10402100-447f-396e-8149-0a434ffb2f23",
    "Washington Commanders": "10405110-ec3c-669e-2614-db3dc1736e95",
}


class CaptureError(IntegrityError):
    pass


def require(condition, reason):
    if not condition:
        raise CaptureError(reason)


def strict_json(text):
    def invalid(_):
        raise CaptureError("NONFINITE_SOURCE_JSON")
    return json.loads(text, object_pairs_hook=_pairs, parse_constant=invalid)


def code_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_requests(season, week):
    require(type(season) is int and season == 2026 and type(week) is int and 1 <= week <= 18,
            "UNREVIEWED_SEASON_OR_INVALID_WEEK")
    return {"espn": {"url": SCOREBOARD_URL,
                     "params": {"dates": season, "seasontype": 2, "week": week, "limit": 1000}},
            "nfl": {"url": f"https://www.nfl.com/schedules/{season}/by-week/week-{week}", "params": {}}}


def fetch_source(request):
    """Keep the full HTTP-decoded body, actual clocks and failures; no retries."""
    observation = {"request": copy.deepcopy(request), "started_at": stamp(datetime.now(timezone.utc)),
                   "source_timestamp": None, "source_timestamp_status": "NOT_ESTABLISHED"}
    try:
        response = requests.get(request["url"], params=request["params"], timeout=25,
                                allow_redirects=False, headers={"User-Agent": "nicks-expert-nfl-picks population-capture"})
        body = response.content
        observation.update(collected_at=stamp(datetime.now(timezone.utc)), final_url=response.url,
                           http_status=response.status_code, http_date=response.headers.get("Date"),
                           body_sha256=hashlib.sha256(body).hexdigest(), body_hash_format=BODY_HASH)
        try:
            observation["body"] = body.decode("utf-8")
        except UnicodeError:
            observation.update(status="parsing_failure", body_base64=base64.b64encode(body).decode("ascii"))
        else:
            observation["status"] = "available" if response.status_code == 200 else "http_failure"
    except requests.RequestException as err:
        observation.update(status="request_failure", error_type=type(err).__name__,
                           collected_at=stamp(datetime.now(timezone.utc)))
    return observation


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts, self.parts = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.parts = []

    def handle_data(self, data):
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.parts is not None:
            self.scripts.append("".join(self.parts))
            self.parts = None


def nfl_queries(body):
    """Decode the known public Next Flight JSON only; never execute page JS."""
    parser = Scripts()
    parser.feed(body)
    decoder = json.JSONDecoder(object_pairs_hook=_pairs,
                               parse_constant=lambda _: require(False, "NONFINITE_SOURCE_JSON"))
    chunks = []
    for script in parser.scripts:
        for match in re.finditer(r"self\.__next_f\.push\(", script):
            value, end = decoder.raw_decode(script, match.end())
            require(script[end:].lstrip().startswith(")"), "UNSUPPORTED_NFL_SCRIPT")
            require(isinstance(value, list) and value, "UNSUPPORTED_NFL_FLIGHT")
            if value[0] == 1:
                require(len(value) == 2 and isinstance(value[1], str), "UNSUPPORTED_NFL_FLIGHT")
                chunks.append(value[1])
    require(chunks, "MISSING_NFL_DATA")
    stack = []
    for line in "".join(chunks).splitlines():
        payload = line.partition(":")[2]
        if payload.startswith(("[", "{", '"')):
            stack.append(strict_json(payload))
    queries = []
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if "queryKey" in value:
                queries.append(value)
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
        elif isinstance(value, str) and value.startswith(("{", "[")):
            try:
                stack.append(strict_json(value))
            except json.JSONDecodeError:
                pass  # Ordinary rendered text is not a query document.
    return queries


def _one_query(queries, name):
    matches = [q for q in queries if isinstance(q.get("queryKey"), list) and q["queryKey"]
               and q["queryKey"][0] == name]
    require(len(matches) == 1, "MISSING_OR_AMBIGUOUS_NFL_QUERY")
    q = matches[0]
    require(q["state"].get("status") == "success", "INCOMPLETE_NFL_QUERY")
    return q["queryKey"][1], q["state"]["data"]


def _nfl_schedule(body, season, week):
    queries = nfl_queries(body)
    params, games = _one_query(queries, "useFetchFootballWeeklyGameDetails")
    require(params.get("season") == str(season) and params.get("seasonType") == "REG"
            and type(params.get("week")) is int and params["week"] == week, "WRONG_NFL_PERIOD")
    selector, weeks = _one_query(queries, "useFetchExperienceWeekSelectorBySeason")
    require(selector.get("season") == str(season), "WRONG_NFL_SELECTOR_PERIOD")
    require(isinstance(weeks, dict) and isinstance(weeks.get("data"), list), "MISSING_NFL_WEEK_METADATA")
    matches = [w for w in weeks["data"] if w.get("season") == season and w.get("week") == week
               and w.get("seasonType") == "REG" and w.get("weekType") == "REG"]
    require(len(matches) == 1, "AMBIGUOUS_NFL_WEEK_METADATA")
    metadata = matches[0]
    require(type(metadata["season"]) is int and type(metadata["week"]) is int, "WRONG_NFL_PERIOD")
    require(isinstance(games, list) and games, "EMPTY_NFL_WEEK")
    members, used_clubs, ids = {}, set(), set()

    def club(team):
        name = team["fullName"]
        require(name in CLUBS_2026 and team["id"] == CLUBS_2026[name], "UNMAPPED_OR_CHANGED_NFL_CLUB")
        require(name not in used_clubs, "DUPLICATE_NFL_CLUB")
        used_clubs.add(name)
        return name

    for game in games:
        require(type(game["season"]) is int and game["season"] == season and type(game["week"]) is int
                and game["week"] == week and game["seasonType"] == game["weekType"] == "REG", "WRONG_NFL_PERIOD")
        require(game["status"] == "SCHEDULED", "NFL_NOT_SCHEDULED")
        gid = game["id"]
        require(isinstance(gid, str) and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", gid)
                and gid not in ids, "DUPLICATE_OR_INVALID_NFL_GAME_ID")
        ids.add(gid)
        away, home = club(game["awayTeam"]), club(game["homeTeam"])
        key = (away, home, stamp(utc(game["time"])))
        require(key not in members, "AMBIGUOUS_NFL_GAME")
        members[key] = gid
    require(isinstance(metadata.get("teamsOnBye"), list), "MISSING_NFL_BYES")
    byes = sorted(club(team) for team in metadata["teamsOnBye"])
    require(used_clubs == set(CLUBS_2026), "INCOMPLETE_NFL_CLUB_BYE_PARTITION")
    times = [utc(key[2]) for key in members]
    require(utc(metadata["dateBegin"]) == min(times) and utc(metadata["dateEnd"]) == max(times),
            "NFL_WEEK_BOUNDARY_MISMATCH")
    return members, byes, {"season": season, "week": week, "season_type": "REG",
                            "first_kickoff": stamp(min(times)), "last_kickoff": stamp(max(times)), "byes": byes}


def _espn_schedule(body, season, week):
    response = strict_json(body)
    require(type(response["season"]["year"]) is int and response["season"]["year"] == season
            and type(response["season"]["type"]) is int and response["season"]["type"] == 2
            and type(response["week"]["number"]) is int and response["week"]["number"] == week,
            "WRONG_ESPN_PERIOD")
    status = normalized_games(response)
    require(status, "EMPTY_ESPN_WEEK")
    members, clubs = {}, set()
    for event in response["events"]:
        gid = event["id"]
        require(re.fullmatch(r"[0-9]+", gid), "INVALID_ESPN_GAME_ID")
        require(status[gid]["state"] == "pre" and status[gid]["completed"] is False
                and not any(s in status[gid]["detail"].lower() for s in ("cancel", "postpon", "suspend")),
                "ESPN_NOT_SCHEDULED")
        competitors = event["competitions"][0]["competitors"]
        require(isinstance(competitors, list) and len(competitors) == 2, "AMBIGUOUS_ESPN_TEAMS")
        sides = {}
        for competitor in competitors:
            side, name = competitor["homeAway"], competitor["team"]["displayName"]
            require(side in ("home", "away") and side not in sides and name in CLUBS_2026 and name not in clubs,
                    "AMBIGUOUS_OR_DUPLICATE_ESPN_CLUB")
            sides[side] = name
            clubs.add(name)
        key = (sides["away"], sides["home"], stamp(utc(event["date"])))
        require(key not in members, "AMBIGUOUS_ESPN_GAME")
        members[key] = gid
    byes = response["week"]["teamsOnBye"]
    require(isinstance(byes, list), "MISSING_ESPN_BYES")
    names = []
    for team in byes:
        name = team["displayName"]
        require(name in CLUBS_2026 and name not in clubs, "DUPLICATE_OR_UNKNOWN_ESPN_BYE")
        clubs.add(name)
        names.append(name)
    require(clubs == set(CLUBS_2026), "INCOMPLETE_ESPN_CLUB_BYE_PARTITION")
    return members, sorted(names), digest(response)


def _document(observations, season, week, started, sealed):
    expected = source_requests(season, week)
    require(set(observations) == set(expected), "MISSING_SOURCE_OBSERVATION")
    require(started <= sealed and (sealed - started).total_seconds() <= MAX_COLLECTION_SECONDS,
            "STALE_OR_REVERSED_CAPTURE_CLOCKS")
    for key, obs in observations.items():
        require(obs["status"] == "available" and obs["http_status"] == 200, "SOURCE_UNAVAILABLE")
        require(obs["request"] == expected[key], "WRONG_SOURCE_REQUEST")
        final = urlsplit(obs["final_url"])
        target = urlsplit(expected[key]["url"])
        require((final.scheme, final.netloc, final.path, final.fragment) ==
                (target.scheme, target.netloc, target.path, "")
                and sorted(parse_qsl(final.query, keep_blank_values=True)) ==
                sorted((k, str(v)) for k, v in expected[key]["params"].items()), "SOURCE_REDIRECT_OR_WRONG_URL")
        require(started <= utc(obs["started_at"]) <= utc(obs["collected_at"]) <= sealed,
                "INVALID_SOURCE_COLLECTION_CLOCKS")
        if obs.get("source_timestamp") is not None:
            require(utc(obs["source_timestamp"]) <= utc(obs["collected_at"]), "FUTURE_SOURCE_CLOCK")
        require(obs.get("source_timestamp_status") == "NOT_ESTABLISHED", "UNSUPPORTED_SOURCE_CLOCK_CLAIM")
        require(isinstance(obs.get("body"), str) and obs["body_hash_format"] == BODY_HASH
                and hashlib.sha256(obs["body"].encode("utf-8")).hexdigest() == obs["body_sha256"],
                "SOURCE_BODY_CHECKSUM_MISMATCH")
    nfl, nfl_byes, metadata = _nfl_schedule(observations["nfl"]["body"], season, week)
    espn, espn_byes, decoded_sha = _espn_schedule(observations["espn"]["body"], season, week)
    require(set(nfl) == set(espn) and nfl_byes == espn_byes, "INDEPENDENT_MEMBERSHIP_DISAGREEMENT")
    require(sealed < min(utc(key[2]) for key in nfl), "CAPTURE_NOT_BEFORE_FIRST_KICKOFF")
    games = [{"id": espn[key], "nfl_id": nfl[key], "away": key[0], "home": key[1], "kickoff": key[2]}
             for key in sorted(nfl, key=lambda k: (utc(k[2]), espn[k]))]
    return {"season": season, "week": week, "games": games, "official_week": metadata,
            "club_identity_season": 2026, "club_identities": copy.deepcopy(CLUBS_2026),
            "club_identities_sha256": digest(CLUBS_2026), "source_observations": copy.deepcopy(observations),
            "espn_decoded_json_sha256": decoded_sha, "espn_json_hash_format": JSON_HASH,
            "membership_check": "EXACT_INDEPENDENT_TEAMS_KICKOFFS_AND_FULL_CLUB_BYE_PARTITION"}


def validate_receipt(payload):
    """Re-derive the receipt from its retained documents, never current sources."""
    try:
        require(payload["schema_version"] == "week-game-population-v1" and payload["mode"] == "live"
                and payload["adapter_version"] == VERSION and payload["adapter_code_sha256"] == code_sha256()
                and payload["source"] == SOURCE and payload["population_scope"] == "FULL_NFL_REGULAR_SEASON_WEEK"
                and payload["source_timestamp"] is None, "UNSUPPORTED_POPULATION_RECEIPT")
        document = payload["source_document"]
        require(payload["source_document_sha256"] == digest(document), "POPULATION_DOCUMENT_CHECKSUM_MISMATCH")
        derived = _document(document["source_observations"], payload["season"], payload["week"],
                            utc(payload["capture_started_at"]), utc(payload["collected_at"]))
        require(document == derived, "POPULATION_DOCUMENT_DIFFERS_FROM_SOURCES")
        return derived
    except CaptureError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as err:
        raise CaptureError("MALFORMED_POPULATION_EVIDENCE") from err


def _membership(document):
    return sorted((g["id"], g.get("nfl_id"), g.get("away"), g.get("home"), stamp(utc(g["kickoff"])))
                  for g in document["games"])


def capture_week(root, season, week):
    """Manual live capture into an explicit isolated root; no supplied clock."""
    root = Path(root).resolve()
    require(not root.is_relative_to(ROOT), "ISOLATED_ROOT_REQUIRED")
    requests_by_source = source_requests(season, week)
    started = datetime.now(timezone.utc)
    observations = {}
    try:
        for name, request in requests_by_source.items():
            observations[name] = fetch_source(request)
        # Parse before taking the seal clock, so validation cannot backdate a
        # request that completes at/after kickoff. Revalidate at actual sealing.
        prelim = datetime.now(timezone.utc)
        _document(observations, season, week, started, prelim)
        sealed = datetime.now(timezone.utc)
        document = _document(observations, season, week, started, sealed)
        payload = {"schema_version": "week-game-population-v1", "mode": "live", "season": season, "week": week,
                   "adapter_version": VERSION, "adapter_code_sha256": code_sha256(),
                   "capture_started_at": stamp(started), "collected_at": stamp(sealed), "source_timestamp": None,
                   "source": SOURCE, "population_scope": "FULL_NFL_REGULAR_SEASON_WEEK",
                   "source_document": document, "source_document_sha256": digest(document)}
        validate_receipt(payload)
        for path in sorted((root / "data/week_populations" / str(season) / f"w{week:02d}").glob("*.json.gz")):
            prior = read(path)
            require(path.name == digest(prior) + ".json.gz", "PRIOR_POPULATION_PATH_MISMATCH")
            require(prior.get("season") == season and prior.get("week") == week and prior.get("mode") == "live"
                    and prior.get("source_document_sha256") == digest(prior["source_document"]),
                    "INVALID_PRIOR_POPULATION")
            validate_receipt(prior)
            require(_membership(prior["source_document"]) == _membership(document), "FROZEN_POPULATION_CONFLICT")
        # Account for prior-receipt validation too; do not use the earlier seal
        # to certify a capture which becomes too late during that work.
        sealed = datetime.now(timezone.utc)
        payload["collected_at"] = stamp(sealed)
        validate_receipt(payload)
        path = write(root, "week_populations", payload)
        require(read(path) == payload, "POPULATION_READBACK_MISMATCH")
        return path
    except (IntegrityError, ValueError, TypeError, KeyError, AttributeError, IndexError) as err:
        diagnostic = {"schema_version": "week-game-population-diagnostic-v1", "mode": "live",
                      "season": season, "week": week, "adapter_version": VERSION,
                      "adapter_code_sha256": code_sha256(), "collected_at": stamp(datetime.now(timezone.utc)),
                      "capture_started_at": stamp(started), "status": "BLOCKED_NOT_A_POPULATION_RECEIPT",
                      "reason": str(err) if isinstance(err, IntegrityError) else "MALFORMED_SOURCE_RESPONSE",
                      "source_observations": observations}
        write(root, "week_population_diagnostics", diagnostic)
        raise CaptureError(diagnostic["reason"]) from err


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Explicit isolated validation/evidence root")
    parser.add_argument("--season", required=True, type=int, choices=[2026])
    parser.add_argument("--week", required=True, type=int, choices=range(1, 19))
    args = parser.parse_args(argv)
    try:
        path = capture_week(args.root, args.season, args.week)
    except IntegrityError as err:
        parser.exit(1, f"Population capture blocked: {err}\n")
    payload = read(path)
    print(json.dumps({"receipt": str(path), "payload_sha256": digest(payload), "games": len(payload["source_document"]["games"]),
                      "first_kickoff": payload["source_document"]["official_week"]["first_kickoff"],
                      "collected_at": payload["collected_at"], "scope": "LOCAL_PREGAME_MEMBERSHIP_NOT_COMPLETED_OUTCOMES_OR_PUBLICATION"}))


if __name__ == "__main__":
    main()

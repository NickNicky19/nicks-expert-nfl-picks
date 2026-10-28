"""Saved ESPN decoded-JSON integrity, not upstream authenticity/completeness.

The retained recorder hashes the full decoded provider response. This contract
stores that response and derives its status map; it never substitutes a hash of
normalized games or calls this a fingerprint of raw HTTP wire bytes.
"""
import copy

from reliability import IntegrityError, digest, stamp, utc

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
STATUS_SCHEMA = "espn-status-response-v1"
HASH_FORMAT = "sha256-canonical-decoded-json-v1"


def _request_period(params):
    if not isinstance(params, dict):
        raise IntegrityError("Missing scoreboard request period")
    season, week = params.get("dates"), params.get("week")
    if (type(season) is not int or not 2000 <= season <= 2200
            or type(week) is not int or not 1 <= week <= 18
            or type(params.get("seasontype")) is not int or params["seasontype"] != 2):
        raise IntegrityError("Wrong scoreboard regular-season request period")
    return season, week


def normalized_games(response):
    """Use the exact fields consumed by the retained ESPN status recorder."""
    if not isinstance(response, dict) or not isinstance(response.get("events"), list):
        raise IntegrityError("Missing provider events")
    games = {}
    try:
        for event in response["events"]:
            gid = event["id"]
            if not isinstance(gid, str) or not gid.strip() or gid in games:
                raise IntegrityError("Missing or duplicate provider game ID")
            competitions = event["competitions"]
            if not isinstance(competitions, list) or len(competitions) != 1:
                raise IntegrityError("Ambiguous provider competition")
            status = competitions[0]["status"]["type"]
            utc(event["date"])
            if (status.get("state") not in ("pre", "in", "post")
                    or type(status.get("completed")) is not bool
                    or not isinstance(status.get("shortDetail"), str)):
                raise IntegrityError("Invalid provider game status")
            games[gid] = {"kickoff": event["date"], "state": status["state"],
                          "completed": status["completed"], "detail": status["shortDetail"]}
    except (KeyError, TypeError, IndexError, AttributeError) as err:
        raise IntegrityError("Malformed provider event") from err
    return games


def record_scoreboard(response, params, collected_at, *, mode="live", source=SCOREBOARD_URL):
    """Copy one actually observed decoded response; no clock/source backfill."""
    if mode not in ("live", "replay") or source != SCOREBOARD_URL:
        raise IntegrityError("Unsupported scoreboard observation source/mode")
    _request_period(params)
    saved = copy.deepcopy(response)
    return {"schema_version": STATUS_SCHEMA, "mode": mode, "source": source,
            "request": copy.deepcopy(params), "collected_at": stamp(utc(collected_at)),
            "response_hash_format": HASH_FORMAT, "response_sha256": digest(saved),
            "response": saved, "games": normalized_games(saved)}


def verified_status(status, season, week, mode, observed_at):
    """Raise on unbound/legacy proof; retain it as unverified, never repair it."""
    try:
        if (status.get("schema_version") != STATUS_SCHEMA or status.get("mode") != mode
                or status.get("source") != SCOREBOARD_URL
                or status.get("response_hash_format") != HASH_FORMAT
                or _request_period(status["request"]) != (season, week)):
            raise IntegrityError("Unsupported or mismatched source-status contract")
        response = status["response"]
        if status.get("response_sha256") != digest(response):
            raise IntegrityError("Provider decoded-response checksum mismatch")
        # Request identity alone cannot establish which period the provider
        # returned. Require the saved provider's own period metadata too.
        provider_season, provider_week = response["season"], response["week"]
        if (type(provider_season.get("year")) is not int or provider_season["year"] != season
                or type(provider_season.get("type")) is not int or provider_season["type"] != 2
                or type(provider_week.get("number")) is not int or provider_week["number"] != week):
            raise IntegrityError("Provider response belongs to another season/week")
        games = normalized_games(response)
        if status.get("games") != games:
            raise IntegrityError("Normalized game status differs from saved provider response")
        if utc(status["collected_at"]) > utc(observed_at):
            raise IntegrityError("Source-status observation is in the future")
        return games
    except (KeyError, TypeError, AttributeError) as err:
        raise IntegrityError("Missing source-status provenance") from err

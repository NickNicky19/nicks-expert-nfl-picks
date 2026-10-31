"""DRAFT closed numeric MAE wire and owner-verified capture projection.

Legacy feeds, selection, probabilities, EV and ranking are untouched. Validation
checks structure and semantics; production authority comes only from trusted
owner verifiers configured as code, never booleans/receipts supplied by clients.
No network, fitting, storage write, publication or actual admission occurs here.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re

try:
    from .next_checkpoint_median_policy_v2_view import consumer_view, FUNCTIONAL_VERSION
except ImportError:
    from next_checkpoint_median_policy_v2_view import consumer_view, FUNCTIONAL_VERSION

COUNT = frozenset({"pass_td","pass_cmp","pass_att","pass_int","rush_att","rec"})
NUMERIC = COUNT | frozenset({"pass_yd","rush_yd","rec_yd","rush_rec_yd"})

FEED = "stat-point-mae-public-feed-v2-draft2"
CATALOG = "stat-point-mae-public-catalog-v2-draft2"
REGISTRY = "stat-point-mae-source-registry-v2-draft2"
CAPTURE = "stat-point-mae-frozen-capture-v2-draft2"
PRODUCT, METRIC = "stat_point_mae_v2", "MAE"
CANDIDATE_SCHEMA = "owned-core-full-law-mae-candidates-v2-draft2"
MAX_ROWS, MAX_BYTES = 5000, 4 << 20
HASH = re.compile(r"[a-f0-9]{64}\Z")
UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
POINT_TYPES = {("point_median", "full_cdf_lower_median"), ("point_mean", "expected_mean")}
ENTRY_KEYS = frozenset("target scoring_target method_id base_learner_id model_version artifact_sha256 model_bytes_sha256 procedure_version base_procedure_version point_profile_sha256 source_policy_sha256 source_contract_sha256 forecast_product prediction_functional public_roles original_contract_version".split())
SOURCE_KEYS = frozenset("identity_bridge_sha256 target model_version procedure_version point_profile_sha256 source_policy_sha256 source_contract_sha256 source_receipt_sha256 feature_capture_receipt_sha256 feature_binding_sha256 query_projection_sha256 query_source_sha256 information_cutoff_utc feature_capture_completed_at public_roles".split())
CAT_KEYS = frozenset("schema_version selection_product selection_metric registered_at owner_admission_receipt_sha256 entries".split())
REG_KEYS = frozenset("schema_version registered_at owner_admission_receipt_sha256 records".split())
ROW_KEYS = frozenset("website_game_id sleeper_id identity_bridge_sha256 identity_binding_sha256 team opponent retained_capture schema_version selection_product selection_metric consumer_contract_version season week game_id player_id target scoring_target position horizon conditional_on method_id base_learner_id model_version artifact_sha256 model_bytes_sha256 procedure_version base_procedure_version point_profile_sha256 selection_sha256 source_policy_sha256 source_contract_sha256 source_registry_sha256 source_receipt_sha256 feature_capture_receipt_sha256 feature_binding_sha256 query_projection_sha256 query_source_sha256 candidate_sha256 capture_receipt_sha256 capture_body_sha256 information_cutoff_utc feature_capture_completed_at feature_max_source_available_utc issued_at persistence_completed_at readback_completed_at issue_deadline_utc kickoff_utc selected_projection projection_label forecast_product prediction_functional expected_mean expected_mean_kind functional_proof mean_eligible trained_prior_only fallback fallback_reason original_contract_version public_roles".split())
FEED_KEYS = frozenset("season week schema_version selection_product selection_metric created_at catalog catalog_sha256 source_registry source_registry_sha256 rows owner_export_receipt_sha256".split())
RECEIPT_KEYS = frozenset("website_game_id sleeper_id identity_bridge_sha256 identity_binding_sha256 team opponent schema_version state horizon candidate_sha256 capture_receipt_sha256 capture_body_sha256 selection_sha256 identity model_version procedure_version point_profile_sha256 source_policy_sha256 source_registry_sha256 query_projection_sha256 information_cutoff_utc issued_at persistence_completed_at readback_completed_at issue_deadline_utc kickoff_utc".split())
_CAPABILITY = object()


def require(ok, code):
    if not ok:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def candidate_digest(value):
    """Exact immutable adapter domain (ASCII escapes), independent of imports."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def strict_json(body):
    require(type(body) in (bytes, str) and len(body) <= MAX_BYTES, "BOUNDED_JSON_REQUIRED")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    def invalid(_):
        raise ValueError("NONFINITE_JSON")
    return json.loads(body, object_pairs_hook=unique, parse_constant=invalid)


def clock(value):
    require(type(value) is str and UTC.fullmatch(value) is not None, "EXACT_UTC_CLOCK_REQUIRED")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def h(value):
    return type(value) is str and HASH.fullmatch(value) is not None


def ident(value):
    return (type(value) is str and 0 < len(value) <= 128 and value == value.strip()
        and value.lower() not in {"nan","nat","none","null","undefined"}
        and all(ord(c) >= 33 and ord(c) != 127 for c in value))


def roles(value):
    return type(value) is list and 0 < len(value) <= 6 and len(value) == len(set(value)) and all(ident(x) for x in value)


def hashes(row):
    return all(h(value) for key, value in row.items() if key.endswith("sha256") or key in {"model_version", "procedure_version", "base_procedure_version"})


def _entry_key(row):
    return tuple(row[k] for k in ("target", "method_id", "model_version", "procedure_version", "forecast_product", "prediction_functional"))


def validate_catalog(catalog):
    require(type(catalog) is dict and set(catalog) == CAT_KEYS and catalog["schema_version"] == CATALOG
        and catalog["selection_product"] == PRODUCT and catalog["selection_metric"] == METRIC
        and h(catalog["owner_admission_receipt_sha256"]), "CLOSED_MAE_CATALOG_REQUIRED")
    clock(catalog["registered_at"])
    entries = catalog["entries"]
    require(type(entries) is list and 0 < len(entries) <= 64, "BOUNDED_CATEGORY_SUBSET_CATALOG_REQUIRED")
    seen = set()
    for row in entries:
        require(type(row) is dict and set(row) == ENTRY_KEYS and hashes(row)
            and row["target"] in NUMERIC and row["scoring_target"] == row["target"]
            and row["artifact_sha256"] == row["model_version"] and roles(row["public_roles"])
            and all(ident(row[k]) for k in ("method_id", "base_learner_id", "original_contract_version"))
            and (row["forecast_product"], row["prediction_functional"]) in POINT_TYPES,
            "CLOSED_NUMERIC_TYPED_CATALOG_ENTRY_REQUIRED")
        key = _entry_key(row)
        require(key not in seen, "DUPLICATE_CATALOG_ENTRY")
        seen.add(key)
    return catalog


def validate_registry(registry):
    require(type(registry) is dict and set(registry) == REG_KEYS and registry["schema_version"] == REGISTRY
        and h(registry["owner_admission_receipt_sha256"]), "CLOSED_SOURCE_REGISTRY_REQUIRED")
    clock(registry["registered_at"])
    require(type(registry["records"]) is list and 0 < len(registry["records"]) <= 128,
        "BOUNDED_SOURCE_REGISTRY_REQUIRED")
    seen = set()
    for row in registry["records"]:
        require(type(row) is dict and set(row) == SOURCE_KEYS and hashes(row)
            and row["target"] in NUMERIC and roles(row["public_roles"]), "CLOSED_SAFE_SOURCE_BINDING_REQUIRED")
        require(clock(row["information_cutoff_utc"]) <= clock(row["feature_capture_completed_at"]),
            "SOURCE_FEATURE_CLOCK_ORDER")
        key = digest(row)
        require(key not in seen, "DUPLICATE_SOURCE_BINDING")
        seen.add(key)
    return registry


def _typed(row):
    return dict(schema_version="stat-point-mae-v2", selection_product=PRODUCT, selection_metric=METRIC,
        consumer_contract_version="stat-point-mae-v2", target=row["target"], scoring_target=row["scoring_target"],
        game_id=row["game_id"], player_id=row["player_id"], horizon=row["horizon"],
        model_version=row["model_version"], procedure_version=row["procedure_version"],
        source_policy_sha256=row["source_policy_sha256"], capture_receipt_sha256=row["capture_receipt_sha256"],
        information_cutoff_utc=row["information_cutoff_utc"], issued_at=row["issued_at"],
        issue_deadline_utc=row["issue_deadline_utc"], kickoff_utc=row["kickoff_utc"],
        feature_max_source_available_utc=row["feature_max_source_available_utc"], trained_prior_only=row["trained_prior_only"],
        forecast_value=row["selected_projection"], forecast_product=row["forecast_product"],
        prediction_functional=row["prediction_functional"], functional_proof=row["functional_proof"],
        separate_expected_mean=row["expected_mean"], mean_eligible=row["mean_eligible"],
        fallback=row["fallback"], fallback_reason=row["fallback_reason"], original_contract_version=row["original_contract_version"])


def validate_row(row, catalog, registry, *, created_at):
    require(type(row) is dict and set(row) == ROW_KEYS and hashes(row), "CLOSED_PUBLIC_POINT_ROW_REQUIRED")
    require(row["schema_version"] == row["consumer_contract_version"] == "stat-point-mae-v2"
        and row["selection_product"] == PRODUCT and row["selection_metric"] == METRIC
        and row["target"] in NUMERIC and row["scoring_target"] == row["target"]
        and row["horizon"] == "player_game" and row["conditional_on"] == "played"
        and row["artifact_sha256"] == row["model_version"]
        and type(row["season"]) is int and 1900 <= row["season"] <= 2200
        and type(row["week"]) is int and 1 <= row["week"] <= 22
        and all(ident(row[k]) for k in ("game_id", "player_id", "position", "website_game_id", "sleeper_id", "team", "opponent"))
        and roles(row["public_roles"]) and row["position"] in row["public_roles"], "TYPED_POINT_IDENTITY_ROLE_REQUIRED")
    matches = [x for x in catalog["entries"] if _entry_key(x) == _entry_key(row)]
    require(len(matches) == 1 and all(row[k] == matches[0][k] for k in ENTRY_KEYS), "ROW_OUTSIDE_ADMITTED_CATALOG")
    require(row["source_registry_sha256"] == digest(registry)
        and any(all(row[k] == source[k] for k in SOURCE_KEYS) for source in registry["records"]),
        "ROW_OUTSIDE_ADMITTED_SOURCE_REGISTRY")
    require(finite(row["selected_projection"]) and finite(row["expected_mean"])
        and row["expected_mean_kind"] == "full_law_expected_mean"
        and (row["target"] not in COUNT or min(row["selected_projection"], row["expected_mean"]) >= 0),
        "FINITE_SUPPORTED_POINT_AND_SEPARATE_LAW_MEAN_REQUIRED")
    require(all(type(row[k]) is bool for k in ("mean_eligible", "trained_prior_only", "fallback", "retained_capture"))
        and type(row["fallback_reason"]) is str and len(row["fallback_reason"]) <= 500
        and (not row["fallback"] or bool(row["fallback_reason"]))
        and (row["fallback"] or row["fallback_reason"] == "")
        and (not row["trained_prior_only"] or row["fallback"]), "EXACT_FALLBACK_CONTRACT_REQUIRED")
    info, captured, issued, persisted, readback, deadline, kickoff, created = map(clock, (
        row["information_cutoff_utc"], row["feature_capture_completed_at"], row["issued_at"],
        row["persistence_completed_at"], row["readback_completed_at"], row["issue_deadline_utc"],
        row["kickoff_utc"], created_at))
    require(clock(catalog["registered_at"]) <= issued and clock(registry["registered_at"]) <= issued
        and info <= captured <= issued <= persisted < deadline < kickoff
        and persisted <= readback <= created and (created < kickoff or row["retained_capture"]), "EXACT_ISSUE_PERSISTENCE_READBACK_CLOCKS_REQUIRED")
    if row["feature_max_source_available_utc"] is not None:
        require(clock(row["feature_max_source_available_utc"]) <= info, "FEATURE_AFTER_INFORMATION_CUTOFF")
    if row["forecast_product"] == "point_mean":
        require(row["prediction_functional"] == "expected_mean" and row["mean_eligible"] is True
            and row["selected_projection"] == row["expected_mean"] and row["functional_proof"] is None,
            "MEAN_MUST_REMAIN_ACTUAL_LAW_MEAN")
    else:
        proof = row["functional_proof"]
        require(type(proof) is dict and set(proof) == {"extractor_version", "cdf_below", "cdf_at"}
            and proof["extractor_version"] == FUNCTIONAL_VERSION
            and finite(proof["cdf_below"]) and finite(proof["cdf_at"])
            and 0 <= proof["cdf_below"] < .5 <= proof["cdf_at"] <= 1
            and float(row["selected_projection"]).is_integer(), "FULL_LAW_LOWER_MEDIAN_BRACKET_REQUIRED")
    view = consumer_view(_typed(row))
    require(view["selected_projection"] == row["selected_projection"]
        and view["expected_mean"] == row["expected_mean"] and view["projection_label"] == row["projection_label"],
        "COMMON_CONSUMER_VALUE_OR_LABEL_CHANGED")
    return row


def validate_feed(feed):
    require(type(feed) is dict and set(feed) == FEED_KEYS and feed["schema_version"] == FEED
        and feed["selection_product"] == PRODUCT and feed["selection_metric"] == METRIC
        and h(feed["owner_export_receipt_sha256"]) and len(canonical(feed)) <= MAX_BYTES,
        "CLOSED_NEW_MAE_FEED_REQUIRED")
    catalog, registry = validate_catalog(feed["catalog"]), validate_registry(feed["source_registry"])
    require(feed["catalog_sha256"] == digest(catalog) and feed["source_registry_sha256"] == digest(registry),
        "EXACT_CATALOG_SOURCE_REGISTRY_DIGEST_REQUIRED")
    require(type(feed["rows"]) is list and 0 < len(feed["rows"]) <= MAX_ROWS, "BOUNDED_PUBLIC_ROWS_REQUIRED")
    seen = set()
    for row in feed["rows"]:
        validate_row(row, catalog, registry, created_at=feed["created_at"])
        require((row["season"],row["week"]) == (feed["season"],feed["week"]), "EXACT_FEED_ROW_SEASON_WEEK")
        key = ("CANONICAL",row["game_id"],row["player_id"],row["target"])
        web = ("WEBSITE",row["website_game_id"],row["sleeper_id"],row["target"])
        require(key not in seen and web not in seen, "DUPLICATE_CANONICAL_OR_WEBSITE_OPPORTUNITY")
        seen.add(key);seen.add(web)
    return feed


class OwnerCapability:
    __slots__ = ("kind", "_body", "_verifier", "_sealed_kind", "_sealed_sha256")

    def __init__(self, kind, document, verifier, key):
        require(key is _CAPABILITY, "OWNER_CAPABILITY_REQUIRED")
        self.kind, self._body, self._verifier = kind, canonical(document), verifier
        self._sealed_kind, self._sealed_sha256 = kind, hashlib.sha256(self._body).hexdigest()

    def __reduce__(self):
        raise ValueError("OWNER_CAPABILITY_MUST_NOT_BE_SERIALIZED")

    @property
    def document(self):
        return strict_json(self._body)

    @property
    def sha256(self):
        return hashlib.sha256(self._body).hexdigest()

    def verify(self):
        require(self.kind == self._sealed_kind and hashlib.sha256(self._body).hexdigest() == self._sealed_sha256,
            "OWNER_CAPABILITY_BYTES_CHANGED")
        require(self._verifier(self.kind, self._body) is None, "INDEPENDENT_OWNER_VERIFICATION_REQUIRED")


def admit_registry(document, *, verify_owner_registry):
    require(callable(verify_owner_registry), "OWNER_REGISTRY_VERIFIER_REQUIRED")
    validate_registry(document)
    capability = OwnerCapability("SOURCE_REGISTRY", document, verify_owner_registry, _CAPABILITY)
    capability.verify()
    return capability


def admit_catalog(document, registry, *, verify_owner_catalog):
    require(type(registry) is OwnerCapability and registry.kind == "SOURCE_REGISTRY"
        and callable(verify_owner_catalog), "OWNER_CATALOG_AND_REGISTRY_REQUIRED")
    registry.verify(); validate_catalog(document)
    for entry in document["entries"]:
        fields = set(ENTRY_KEYS) & set(SOURCE_KEYS)
        require(any(all(entry[k] == source[k] for k in fields) for source in registry.document["records"]),
            "CATALOG_NOT_IN_OWNER_SOURCE_REGISTRY")
    capability = OwnerCapability("CATALOG", document, verify_owner_catalog, _CAPABILITY)
    capability.verify()
    return capability


def finalize_capture(candidate, receipt, catalog, registry, *, verify_owner_capture):
    """Trusted owner independently verifies frozen bytes/readback/selection first."""
    require(type(catalog) is type(registry) is OwnerCapability and catalog.kind == "CATALOG"
        and registry.kind == "SOURCE_REGISTRY" and callable(verify_owner_capture), "OWNER_CAPTURE_CAPABILITIES_REQUIRED")
    catalog.verify(); registry.verify(); receipt = deepcopy(receipt)
    value = deepcopy(candidate); candidate_sha = value.pop("candidate_sha256", None)
    require(h(candidate_sha) and candidate_digest(value) == candidate_sha, "IMMUTABLE_PRIVATE_CANDIDATE_REQUIRED")
    require(type(receipt) is dict and set(receipt) == RECEIPT_KEYS and receipt["schema_version"] == CAPTURE
        and receipt["state"] == "FROZEN_AND_READ_BACK" and hashes(receipt), "EXACT_FROZEN_READBACK_RECEIPT_REQUIRED")
    require(value["schema_version"] == "stat-point-mae-v2" and value["candidate_schema"] == CANDIDATE_SCHEMA
        and value["selection_product"] == PRODUCT
        and value["selection_metric"] == METRIC and value["public_export_authorized"] is False
        and value["public_scope_eligible"] is True and value["operational_eligible"] is True
        and value["evidence_lane"] == "original_pregame" and value["conditional_on"] == "played"
        and value["participation_state"] == "unknown", "ACTUAL_ELIGIBLE_PRIVATE_POINT_REQUIRED")
    require(receipt["candidate_sha256"] == candidate_sha and receipt["source_registry_sha256"] == registry.sha256
        and receipt["identity"] == {k: value[k] for k in ("season", "week", "game_id", "player_id", "target")}
        and all(receipt[k] == value[k] for k in ("horizon", "model_version", "procedure_version", "point_profile_sha256",
            "source_policy_sha256", "query_projection_sha256", "information_cutoff_utc", "issued_at", "issue_deadline_utc", "kickoff_utc")),
        "CAPTURE_DOES_NOT_BIND_THIS_CANDIDATE")
    require(verify_owner_capture(canonical(receipt), candidate_sha, catalog.sha256, registry.sha256) is None,
        "INDEPENDENT_CAPTURE_READBACK_SELECTION_REQUIRED")
    row = {k: value[k] for k in ROW_KEYS if k in value}
    source = next((s for s in registry.document["records"] if s["target"] == value["target"]
        and s["model_version"] == value["model_version"] and s["procedure_version"] == value["procedure_version"]
        and s["query_projection_sha256"] == value["query_projection_sha256"]), None)
    require(source is not None, "CURRENT_CANDIDATE_SOURCE_NOT_ADMITTED")
    require(all(receipt[k] == value[k] for k in ("team","opponent"))
        and all(ident(receipt[k]) for k in ("website_game_id","sleeper_id"))
        and receipt["identity_bridge_sha256"] == source["identity_bridge_sha256"],
        "OWNER_VERIFIED_WEBSITE_IDENTITY_REQUIRED")
    row.update({k:receipt[k] for k in ("website_game_id","sleeper_id","identity_bridge_sha256","identity_binding_sha256")})
    row.update(source, retained_capture=clock(receipt["readback_completed_at"])>=clock(value["kickoff_utc"]), schema_version="stat-point-mae-v2", consumer_contract_version="stat-point-mae-v2",
        artifact_sha256=value["model_version"], selected_projection=value["forecast_value"],
        expected_mean=value["separate_expected_mean"], expected_mean_kind="full_law_expected_mean",
        mean_eligible=True, candidate_sha256=candidate_sha,
        source_registry_sha256=registry.sha256, source_contract_sha256=digest(value["source_contract"]),
        capture_receipt_sha256=receipt["capture_receipt_sha256"], capture_body_sha256=receipt["capture_body_sha256"],
        selection_sha256=receipt["selection_sha256"], persistence_completed_at=receipt["persistence_completed_at"],
        readback_completed_at=receipt["readback_completed_at"])
    require(row["source_receipt_sha256"] == value["source_receipt"]["sha256"]
        and row["feature_capture_receipt_sha256"] == value["feature_capture_receipt"]["sha256"]
        and row["feature_binding_sha256"] == value["feature_binding"]["sha256"]
        and row["feature_capture_completed_at"] == value["original_forecast"]["source_capture_completed_at"],
        "SOURCE_REGISTRY_MUST_BIND_ACTUAL_PRIVATE_REFERENCES")
    row["projection_label"] = consumer_view(_typed(row))["projection_label"]
    validate_row(row, catalog.document, registry.document, created_at=receipt["readback_completed_at"])
    capture = OwnerCapability("FROZEN_POINT", row,
        lambda _kind, _body: verify_owner_capture(canonical(receipt), candidate_sha, catalog.sha256, registry.sha256), _CAPABILITY)
    capture.verify()
    return capture


def export_feed(captures, catalog, registry, *, created_at, owner_export_receipt_sha256, verify_owner_export):
    require(type(catalog) is type(registry) is OwnerCapability and catalog.kind == "CATALOG"
        and registry.kind == "SOURCE_REGISTRY" and callable(verify_owner_export), "OWNER_EXPORT_CAPABILITIES_REQUIRED")
    catalog.verify(); registry.verify()
    require(type(captures) is list and 0 < len(captures) <= MAX_ROWS
        and all(type(c) is OwnerCapability and c.kind == "FROZEN_POINT" for c in captures), "OWNER_FROZEN_CAPTURES_REQUIRED")
    for capture in captures:
        capture.verify()
    rows=[capture.document for capture in captures]
    require(len({(r["season"],r["week"]) for r in rows})==1,"ONE_CAPTURE_SEASON_WEEK_REQUIRED")
    for row in rows:
        if clock(created_at)>=clock(row["kickoff_utc"]): row["retained_capture"]=True
    feed = dict(schema_version=FEED, selection_product=PRODUCT, selection_metric=METRIC,
        season=rows[0]["season"],week=rows[0]["week"],
        created_at=created_at, catalog=catalog.document, catalog_sha256=catalog.sha256,
        source_registry=registry.document, source_registry_sha256=registry.sha256,
        rows=rows, owner_export_receipt_sha256=owner_export_receipt_sha256)
    validate_feed(feed)
    require(verify_owner_export(canonical(feed), catalog.sha256, registry.sha256) is None,
        "INDEPENDENT_OWNER_EXPORT_REQUIRED")
    return feed

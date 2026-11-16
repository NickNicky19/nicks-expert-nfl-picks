"""Validate/render the public production-method metadata view.

This is a reporting view of retained registries and evidence. It makes no
provider requests, fits, predictions, grades, selections or admission changes.
The JSON is the frozen metadata projection; Markdown is rendered from it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

SCHEMA = "original-site-production-method-history-v1"
TARGETS = {
    "pass_yd": "Passing yards", "pass_td": "Passing touchdowns",
    "pass_cmp": "Completions", "pass_att": "Pass attempts",
    "pass_int": "Interceptions thrown", "rush_yd": "Rushing yards",
    "rush_att": "Rushing attempts", "rec": "Receptions",
    "rec_yd": "Receiving yards", "rush_rec_yd": "Rush + receiving yards",
    "anytime_td": "Inherited rushing-or-receiving anytime TD",
    "nick-chart-ppr-v1": "Exact nick-chart-ppr-v1",
}
LIMIT = 8 << 20


def load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("bounded regular catalog file required")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def validate(doc: dict) -> None:
    if doc.get("schema_version") != SCHEMA or doc.get("kind") != "METADATA_REPORT_NOT_FORECAST_OR_RUNTIME_REGISTRY":
        raise ValueError("metadata schema/kind")
    if set(doc["categories"]) != set(TARGETS):
        raise ValueError("all twelve exact contracts required")
    if doc["completeness"]["status"] not in {"PARTIAL", "COMPLETE_WITHIN_LISTED_SOURCES"}:
        raise ValueError("bounded completeness statement required")

    groups = {}
    for group in ["families", "procedures", "executions"]:
        values = doc[group]
        ids = [value["inventory_id"] for value in values]
        if len(set(ids)) != len(ids) or any(not isinstance(key, str) or not key for key in ids):
            raise ValueError("unique metadata record IDs required")
        groups[group] = set(ids)
    for item in doc["procedures"]:
        if item["family_id"] not in groups["families"]:
            raise ValueError("procedure family missing")
        if not set(item["category_links"]) <= set(TARGETS):
            raise ValueError("procedure target contract")
        if set(item["contract_compatibility"]) != set(item["category_links"]):
            raise ValueError("exact/related target compatibility must be explicit")
        if "nick-chart-ppr-v1" in item["category_links"] and "COMPATIBLE_OR_CAPABILITY" in item["contract_compatibility"]["nick-chart-ppr-v1"]:
            raise ValueError("this catalog has no admitted exact-chart product; do not substitute league scores")
        for field in ["canonical_id", "aliases", "predecessors", "output_type", "role_scope",
                      "inputs", "history_update_rule", "selection_calibration_fallback",
                      "milestones", "verification_scope", "five_week_status", "source_refs"]:
            if field not in item:
                raise ValueError("procedure metadata missing: " + field)
    for item in doc["executions"]:
        if not set(item["procedure_ids"]) <= groups["procedures"]:
            raise ValueError("execution procedure missing")
        if not set(item["category_links"]) <= set(TARGETS):
            raise ValueError("execution target contract")
        if "evidence_tier" not in item or "verification_scope" not in item or "metrics" not in item:
            raise ValueError("execution scope/metrics required")
    for item in doc["categories"].values():
        if not set(item["procedure_ids"]) <= groups["procedures"]:
            raise ValueError("category procedure link")
        if not set(item["execution_ids"]) <= groups["executions"]:
            raise ValueError("category execution link")

    # This public view must never transport protected rows, secrets or private
    # execution/cache locations from an otherwise accessible historical receipt.
    body = json.dumps(doc, ensure_ascii=False, allow_nan=False)
    if re.search(r"(?:/tmp/|/workspace/|file://|s3://|sediment://|github_pat_[A-Za-z0-9_]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|[?&](?:sig|token)=[^\s\"&]+)", body):
        raise ValueError("public metadata contains a private locator/secret")
    if doc["report_effects"] != {"forecast_changed": False, "policy_changed": False,
                                 "new_research_fit": False, "new_grading": False,
                                 "new_primary_admission": False}:
        raise ValueError("report must not claim runtime/scientific execution")


def cell(value) -> str:
    if value is None or value == "":
        return "NOT_RETAINED"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def brief(value, limit=340):
    value = cell(value)
    return value if len(value) <= limit else value[:limit - 1] + "… (detail in JSON)"


def render(doc: dict) -> str:
    validate(doc)
    families = {item["inventory_id"]: item for item in doc["families"]}
    procedures = {item["inventory_id"]: item for item in doc["procedures"]}
    executions = {item["inventory_id"]: item for item in doc["executions"]}
    lines = ["# Original website: recoverable production-method history", "",
             "[Matching complete JSON detail](index.json)", "",
             doc["scope_statement"], "", doc["interpretation"], "",
             "This derived metadata view does not control the website or run a model, grader or selector. "
             "Catalog record counts are not independent models, players, games or tested weeks. "
             "Unretained fields remain NOT_RETAINED; they are never filled with zero.", "",
             "Report snapshot: " + cell(doc["report_generated_UTC"]) + ". "
             "Current production code/data reference: `" + doc["production_snapshot"]["commit"] + "`.", "",
             "## Current use and release separation", "", doc["current_use_summary"], "",
             "|Level|Metadata records|Meaning|", "|---|---:|---|",
             f"|Family/mechanism|{len(families)}|Underlying idea, retaining original ownership and aliases.|",
             f"|Exact procedure/product|{len(procedures)}|Output, role, inputs, history, policy and fallback variants beneath families.|",
             f"|Execution/evaluation|{len(executions)}|Retained runs, reports, captures, failures and grading versions; not repeated football observations.|", ""]
    for category, label in TARGETS.items():
        entry = doc["categories"][category]
        items = [procedures[key] for key in entry["procedure_ids"]]
        family_ids = sorted({item["family_id"] for item in items})
        lines += ["## " + label, "", cell(entry["contract_statement"]), "",
                  "|Product decision field|Current scoped receipt|", "|---|---|",
                  "|Highest observed comparable method(s)|" + brief(entry["assessment"]["observed"]) + "|",
                  "|Best-supported eligible choice|" + brief(entry["assessment"]["eligible"]) + "|",
                  "|Operationally ready|" + brief(entry["assessment"]["ready"]) + "|",
                  "|Actually live / disposition|" + brief(entry["assessment"]["live"]) + "|", "",
                  "### Identified families and procedures", "",
                  "|Family / mechanism|Status within these sources|Exact procedure/product IDs (detail in JSON)|",
                  "|---|---|---|"]
        for fid in family_ids:
            family = families[fid]
            members = [p for p in items if p["family_id"] == fid]
            labels = sorted({p.get("canonical_id") or p["name"] for p in members})
            states = sorted({cell(p["state"]) for p in members})
            relationship = family.get("formula", family.get("relationship", "See procedure information/relationship in JSON"))
            lines.append("|" + cell(family["name"]) + ". " + brief(relationship, 190) + "|" +
                         brief("; ".join(states), 290) + "|" +
                         "; ".join("`" + cell(label) + "`" for label in labels) +
                         f". {len(members)} exact product/configuration entries in JSON (`{fid}`).|")
        if not family_ids:
            lines.append("|No compatible implemented product located|" + cell(entry["gap"]) + "|N/A|")
        lines += ["", "### Retained execution and evaluation", "",
                  f"{len(entry['execution_ids'])} linked execution/view records are retained in the JSON category entry. "
                  "Shared multi-category executions appear once in the index below; their totals are not this category's accuracy.", "",
                  "|Category-specific record|Period/population|Retained result / execution stage|Evidence scope|",
                  "|---|---|---|---|"]
        shown = 0
        for eid in entry["execution_ids"]:
            execution = executions[eid]
            if len(execution["category_links"]) != 1:
                continue
            shown += 1
            lines.append("|`" + eid + "`|" + brief(execution["period_population"], 240) + "|" +
                         brief(execution["summary"], 320) + "|" + brief(execution["evidence_tier"], 150) + "|")
        if not shown:
            lines.append("|See linked shared records|Exact source scope retained in JSON|No separate category-only score inferred.|No substitute target or invented score.|")
        lines += ["", "Long formulas, settings, source hashes, complete retained metrics, unknown/fallback counts, "
                  "scored/missing W1–9 cells, five-week status and owner actions are in the matching JSON. "
                  "Related incompatible products are explicitly labelled; they do not qualify this target.", ""]
    lines += ["## Shared execution index", "",
              "Each retained execution/view is listed once here. Repeated categories, report views, refreshes and books "
              "are not independent NFL games. Original and corrected grades remain separate. Full metrics and scopes are in JSON.", "",
              "|Execution ID|Categories / period|Result or stage|Verification scope|", "|---|---|---|---|"]
    for eid, execution in executions.items():
        links = execution["category_links"]
        scope = ", ".join(links) if len(links) <= 2 else f"Shared {len(links)}-category view (exact links in JSON)"
        lines.append("|`" + eid + "`|" + cell(scope) + "; " +
                     brief(execution["period_population"], 90) + "|" + brief(execution["summary"], 190) +
                     "|" + brief(execution["verification_scope"], 100) + "|")
    lines += ["", "## Completeness and exclusions", "", "**" + doc["completeness"]["status"] + "**", "",
              doc["completeness"]["statement"], "", "Sources examined:", ""]
    for source in doc["completeness"]["examined"]:
        lines.append("- " + cell(source))
    lines += ["", "Remaining gaps/conflicts (no release-wide waiting condition):", ""]
    for gap in doc["completeness"]["gaps"]:
        lines.append("- " + cell(gap))
    lines += ["", "## Existing owner actions", ""]
    for action in doc["owner_actions"]:
        lines.append("- **" + cell(action["owner"]) + ":** " + cell(action["action"]))
    lines += ["", "The current A/B/C pilots remain with their registered owners and cumulative limits. "
              "Their execution does not wait for this catalog, C acknowledgment or perfect lifetime history. "
              "This report imports no protected training context, model weights, raw restricted offers or private execution locators.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    doc = load(args.catalog)
    markdown = render(doc)
    if args.check:
        if not args.markdown.is_file() or args.markdown.read_text() != markdown:
            raise ValueError("Markdown does not match the frozen JSON metadata view")
    else:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown)
    print(json.dumps({"state": "MATCHING_METADATA_VIEW_VALIDATED", "families": len(doc["families"]),
                      "procedures": len(doc["procedures"]), "executions": len(doc["executions"]),
                      "categories": len(doc["categories"]), "completeness": doc["completeness"]["status"]}))


if __name__ == "__main__":
    main()

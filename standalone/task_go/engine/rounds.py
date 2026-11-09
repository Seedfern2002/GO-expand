"""Accumulate retrieval rounds and verify reading progress from saved evidence."""

import json
import re
from pathlib import Path

from .knowledge import read_json, sha256, validate_batches, workspace_file

USAGE_FIELDS = ("search_queries", "sources_opened", "paper_identities_opened", "literature_candidate_statements")


def identities(row):
    values = []
    for field in ("pmid", "pmcid", "doi"):
        value = str(row.get(field) or "").strip()
        if not value:
            continue
        if field == "pmid":
            value = re.sub(r"^PMID:", "", value, flags=re.I)
            if not value.isdigit():
                raise ValueError("Expected a numeric PMID")
        elif field == "pmcid":
            value = value.upper()
            if not re.fullmatch(r"PMC\d+", value):
                raise ValueError("Expected a PMC identifier")
        else:
            value = re.sub(r"^(?:https?://(?:dx\.)?doi.org/|doi:)", "", value, flags=re.I).lower()
            if not re.fullmatch(r"10\.\d{4,9}/\S+", value):
                raise ValueError("Expected a DOI")
        values.append(field + ":" + value)
    if not values:
        raise ValueError("Paper inspection needs a PMID, PMCID or DOI")
    return values


def paper_counts(observations):
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for row in observations:
        ids = identities(row)
        for key in ids[1:]:
            parent[find(key)] = find(ids[0])
    groups, primary, full = set(), set(), set()
    for row in observations:
        key = find(identities(row)[0])
        groups.add(key)
        if row["is_primary"]:
            primary.add(key)
            if row["inspection_level"] == "full_text":
                full.add(key)
    return {"unique_inspected_papers": len(groups), "inspected_primary": len(primary),
            "full_text_inspected_primary": len(full)}


def tool_output_text(events_path):
    outputs = []
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item", {})
            if event.get("type") == "item.completed" and item.get("type") == "command_execution":
                outputs.append(item.get("aggregated_output", ""))
    return "\n".join(outputs)


def read_inspections(path, root, events_path):
    """Require source-bound passages actually exposed through the round's tools."""
    output = tool_output_text(events_path)
    observations, texts = [], {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        identities(row)
        if not isinstance(row.get("is_primary"), bool):
            raise ValueError(f"Inspection {number} needs an explicit primary-paper flag")
        if row.get("inspection_level") not in {"abstract", "full_text"}:
            raise ValueError("Inspection level must be abstract or full_text")
        if row.get("decision") not in {"extract", "exclude", "defer"} or not row.get("reason"):
            raise ValueError("Inspection needs a screening decision and reason")
        snapshot = workspace_file(root, row["snapshot_path"])
        if snapshot not in texts:
            texts[snapshot] = (sha256(snapshot), snapshot.read_text())
        digest, text = texts[snapshot]
        if digest != row["snapshot_sha256"]:
            raise ValueError("Inspected text snapshot hash mismatch")
        passages = row.get("passages", [])
        if not passages:
            raise ValueError("Inspection needs saved scientific passages")
        abstract, body = [], []
        for passage in passages:
            quote = passage.get("quote", "")
            if len(quote.strip()) < 20 or quote not in text or not passage.get("locator") or not passage.get("section"):
                raise ValueError("Inspected passage must match its saved scientific text")
            visible = [quote, json.dumps(quote, ensure_ascii=False)[1:-1], json.dumps(quote, ensure_ascii=True)[1:-1]]
            if not any(value in output for value in visible):
                raise ValueError("Inspected passage was not exposed in this round's tool output")
            (abstract if "abstract" in passage["section"].lower() else body).append(quote)
        if not abstract:
            raise ValueError("Record an inspected abstract passage for each paper")
        if row["inspection_level"] == "full_text" and (
            not body or not any(all(q not in a for a in abstract) for q in body)
        ):
            raise ValueError("Full-text inspection needs an additional body passage")
        observations.append(row)
    return observations


def merge_candidates(previous, result):
    active = {batch["id"]: batch for batch in previous.get("batches", [])}
    for name in result.get("supersedes_batch_ids", []):
        if name not in active:
            raise ValueError("Superseded batch must already exist")
        del active[name]
    for batch in result["batches"]:
        if batch["id"] in active and active[batch["id"]] != batch:
            raise ValueError("Publish batch revisions under a new batch ID")
        active[batch["id"]] = batch
    return {"schema_version": "3.0", "task_id": result["task_id"], "batches": list(active.values()),
            "coverage": result["coverage"], "open_questions": result["open_questions"]}


def measured_usage(root):
    searches = 0
    for path in (root / "rounds").glob("retriever_*/events.jsonl"):
        for line in path.read_text().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item", {})
            action = item.get("action", {})
            if event.get("type") == "item.completed" and item.get("type") == "web_search" and action.get("type") == "search":
                searches += len(action.get("queries") or [action.get("query", item.get("query"))])
    ledger = read_json(root / "download_ledger.json") if (root / "download_ledger.json").exists() else {}
    urls = [row.get("url", "") for row in ledger.get("sources", [])]
    searches += sum("/rest/search?" in url or "/esearch.fcgi?" in url for url in urls)
    return {"search_queries": searches, "downloaded_bytes": ledger.get("downloaded_bytes", 0),
            "distinct_download_urls": len(set(urls))}


def next_action(task, progress, round_number, maximum_rounds, stalled_rounds, stall_limit):
    budget = task["retrieval_budget"]
    reached = progress.get("inspected_primary", 0) >= budget.get("target_papers_inspected", 0) and (
        progress.get("full_text_inspected_primary", 0) >= budget.get("target_full_text_papers_inspected", 0)
    )
    if reached:
        return "targets_met"
    for key, limit in [("search_queries", "max_search_queries"), ("sources_opened", "max_sources_opened"),
                       ("paper_identities_opened", "max_papers"), ("literature_candidate_statements", "max_candidate_records"),
                       ("downloaded_bytes", "max_download_bytes")]:
        if limit in budget and progress.get(key, 0) >= budget[limit]:
            return "resource_limit:" + key
    if stalled_rounds >= stall_limit:
        return "stalled_reading"
    if round_number >= maximum_rounds:
        return "round_limit"
    return "continue"


def validate_round(task, result, root, directory, state):
    if result["task_id"] != task["task_id"]:
        raise ValueError("Task identity changed")
    input_manifest = root / "inputs/manifest.json"
    if input_manifest.exists():
        frozen = read_json(input_manifest)
        if sha256(root / "task.json") != frozen["task_sha256"]:
            raise ValueError("The scientific task changed during acquisition")
        for item in frozen["files"]:
            if sha256(workspace_file(root, item["path"])) != item["sha256"]:
                raise ValueError("An original scientific input or cached source changed")
    previous = state.get("candidates", {"batches": []})
    # Earlier round products remain hash-bound even when a new revision supersedes them.
    for batch in previous.get("batches", []):
        if sha256(workspace_file(root, batch["records_path"])) != batch["records_sha256"]:
            raise ValueError("An earlier published batch changed")
    candidates = merge_candidates(previous, result)
    plan = read_json(root / "stages/planner/result.json")
    plan_ids = {a["id"] for a in plan["augmentations"]}
    if len({b["id"] for b in result["batches"]}) != len(result["batches"]):
        raise ValueError("Round batch IDs must be unique")
    if len(result["coverage"]) != len(plan_ids) or {c["plan_item_id"] for c in result["coverage"]} != plan_ids:
        raise ValueError("Every plan item needs a coverage entry")
    if any(b["plan_item_id"] not in plan_ids for b in candidates["batches"]):
        raise ValueError("Unknown plan item in batch")
    for batch in candidates["batches"]:
        workspace_file(root, batch["provenance_path"])
    validation = validate_batches(task, candidates["batches"], root)
    new = read_inspections(workspace_file(root, result["paper_inspections_path"]), root, directory / "events.jsonl")
    for row in new:
        row["verified_round_directory"] = str(directory.relative_to(root))
    observations = state.get("observations", []) + new
    counts = paper_counts(observations)
    usage = read_json(workspace_file(root, result["usage_path"]))
    for key in USAGE_FIELDS:
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < state.get("progress", {}).get(key, 0):
            raise ValueError("Usage counters must be cumulative nonnegative integers")
    measured = measured_usage(root)
    published_literature = sum(value["literature_records"] for value in validation.values())
    if usage["literature_candidate_statements"] < published_literature:
        raise ValueError("Literature usage undercounts published candidate statements")
    if usage["search_queries"] < measured["search_queries"]:
        raise ValueError("Search usage undercounts recorded tool/API requests")
    if usage["sources_opened"] < max(counts["unique_inspected_papers"], measured["distinct_download_urls"]):
        raise ValueError("Source usage undercounts inspected papers or downloaded artifacts")
    if usage["paper_identities_opened"] < counts["unique_inspected_papers"]:
        raise ValueError("Paper usage undercounts inspected identities")
    progress = {**counts, **usage, "downloaded_bytes": measured["downloaded_bytes"],
                "active_batches": len(candidates["batches"]),
                "active_records": sum(v["record_count"] for v in validation.values())}
    for key, limit in [("search_queries", "max_search_queries"), ("sources_opened", "max_sources_opened"),
                       ("paper_identities_opened", "max_papers"), ("literature_candidate_statements", "max_candidate_records")]:
        if progress[key] > task["retrieval_budget"][limit]:
            raise ValueError("Cumulative retrieval budget exceeded: " + key)
    return {"candidates": candidates, "observations": observations, "progress": progress,
            "validation": validation}

"""Evidence-backed knowledge assembly, separate from downstream evaluation.

The compiler never selects knowledge using predictions or response metrics.
Leakage audits are independent artifacts, outside this module and agent workflow.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import pickle
import re


RELATIONS = {
    "annotated_to", "member_of_pathway", "member_of_complex",
    "predicted_member_of_complex", "positively_regulates", "negatively_regulates",
    "binds", "associated_with", "expressed_in",
}
EVIDENCE_CLASSES = {"database_derived", "literature_extracted", "analysis_inferred"}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_rows(path, rows):
    with Path(path).open("w") as stream:
        for row in rows:
            stream.write(encoded(row) + "\n")


def workspace_file(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Expected an existing workspace file: {name}")
    return path


def universe_for(task, root):
    path = workspace_file(root, task["scope"]["gene_universe_path"])
    genes = read_json(path)[task["scope"]["gene_field"]]
    if not genes or any(not isinstance(g, str) or not g for g in genes) or len(genes) != len(set(genes)):
        raise ValueError("Gene universe must contain unique, nonempty gene identifiers")
    return genes, path


def validate_contract(task, plan):
    contract = plan["knowledge_contract"]
    policy = task["compilation"]
    if contract != policy:
        raise ValueError("Executable knowledge contract must match the task's predeclared compilation policy")
    if not set(policy["allowed_relations"]) <= RELATIONS:
        raise ValueError("Unsupported relationship in compilation policy")
    if not set(policy["allowed_evidence_classes"]) <= EVIDENCE_CLASSES:
        raise ValueError("Unsupported evidence class")
    projection = policy["projection"]
    if projection["adapter"] != "gene_attributes":
        raise ValueError("Unsupported task projection adapter")
    if not set(projection["membership_relations"]) <= {
        "annotated_to", "member_of_pathway", "member_of_complex", "predicted_member_of_complex"
    } or not set(projection["membership_relations"]) <= set(policy["allowed_relations"]):
        raise ValueError("Projection accepts only declared membership relationships")
    if projection["singleton_policy"] not in {"retain", "exclude_new"}:
        raise ValueError("Unknown singleton policy")
    if projection["context_policy"] not in {"preserve", "compatible"}:
        raise ValueError("Unknown context policy")
    return policy


def read_records(path, task, root, digest_cache=None):
    """Independently validate every row and materialized evidence locator.

    These are structural/provenance checks; biological interpretation is reviewed
    separately by the reviewer. A matching quotation does not establish causality.
    """
    genes, _ = universe_for(task, root)
    genes = set(genes)
    policy = task["compilation"]
    cache = digest_cache if digest_cache is not None else {}
    seen, records = set(), []
    required = {"id", "subject_id", "subject_label", "object_id", "object_label", "relation",
                "polarity", "context", "evidence_class", "evidence", "projection_eligible"}
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        r = json.loads(line)
        if not required <= r.keys():
            raise ValueError(f"Missing statement fields at {path}:{number}")
        for key in ("id", "subject_id", "subject_label", "object_id", "object_label"):
            if not isinstance(r[key], str) or not r[key]:
                raise ValueError(f"Invalid {key} at {path}:{number}")
        if r["id"] in seen or r["subject_label"] not in genes:
            raise ValueError("Duplicate record ID or gene outside fixed universe")
        seen.add(r["id"])
        stable_id = ":" in r["object_id"] or re.fullmatch(r"R-HSA-\d+(?:\.\d+)?", r["object_id"])
        if not stable_id or r["relation"] not in policy["allowed_relations"]:
            raise ValueError("Object must have a namespace and relation must be declared")
        if r["object_id"].startswith("GO:") and policy.get("ontology_path"):
            from .ontology import Ontology
            ontology_path = workspace_file(root, policy["ontology_path"])
            if (ontology_path, "ontology") not in cache:
                cache[(ontology_path, "ontology")] = Ontology.read(ontology_path)
                cache[ontology_path] = sha256(ontology_path)
            try:
                term = cache[(ontology_path, "ontology")].resolve(r["object_id"])
            except KeyError as error:
                raise ValueError("Unknown GO term in candidate statement") from error
            if term.obsolete or term.id != r["object_id"]:
                raise ValueError("Candidate must use an active canonical GO identifier")
        if r["evidence_class"] not in policy["allowed_evidence_classes"]:
            raise ValueError("Undeclared evidence class")
        if r["polarity"] not in {"positive", "negative", "not_applicable", "unknown"}:
            raise ValueError("Invalid assertion polarity")
        if not isinstance(r["projection_eligible"], bool) or not isinstance(r["context"], dict):
            raise ValueError("Invalid eligibility or biological context")
        if not r["evidence"] or not isinstance(r["evidence"], list):
            raise ValueError("Every statement requires materialized evidence")
        for evidence in r["evidence"]:
            keys = {"source_name", "source_version", "source_uri", "study_id", "locator",
                    "snapshot_path", "snapshot_sha256", "assertion_type"}
            if not keys <= evidence.keys() or any(not isinstance(evidence[k], str) or not evidence[k] for k in keys):
                raise ValueError("Incomplete source/study provenance")
            if evidence["assertion_type"] not in {"database_record", "experimental_result", "interpretation", "hypothesis"}:
                raise ValueError("Unknown evidence assertion type")
            snapshot = workspace_file(root, evidence["snapshot_path"])
            if snapshot not in cache:
                cache[snapshot] = sha256(snapshot)
            if cache[snapshot] != evidence["snapshot_sha256"]:
                raise ValueError("Evidence snapshot checksum mismatch")
            if r["evidence_class"] == "literature_extracted":
                quote = evidence.get("quote")
                if (snapshot, "text") not in cache:
                    cache[(snapshot, "text")] = snapshot.read_text()
                if not isinstance(quote, str) or len(quote.strip()) < 20 or quote not in cache[(snapshot, "text")]:
                    raise ValueError("Literature evidence requires a verbatim passage in its saved text snapshot")
            elif evidence["locator"].startswith("line:"):
                # The connector is responsible for identifier-mapping semantics.
                if snapshot not in cache or (snapshot, "lines") not in cache:
                    with snapshot.open() as stream:
                        cache[(snapshot, "lines")] = sum(1 for _ in stream)
                n = int(evidence["locator"].split(":", 1)[1])
                if not 1 <= n <= cache[(snapshot, "lines")]:
                    raise ValueError("Evidence source line does not exist")
        records.append(r)
    return records


def validate_batches(task, batches, root):
    """Recompute counts from source rows rather than trusting agent reports."""
    genes, _ = universe_for(task, root)
    reports, cache = {}, {}
    all_ids, literature_count, papers = set(), 0, set()
    for batch in batches:
        path = workspace_file(root, batch["records_path"])
        if sha256(path) != batch["records_sha256"]:
            raise ValueError("Batch checksum mismatch")
        records = read_records(path, task, root, cache)
        literature_count += sum(r["evidence_class"] == "literature_extracted" for r in records)
        papers.update(e["source_uri"] for r in records if r["evidence_class"] == "literature_extracted" for e in r["evidence"])
        ids = {r["id"] for r in records}
        if ids & all_ids:
            raise ValueError("Record IDs must be unique across acquisition batches")
        all_ids.update(ids)
        coverage = read_json(workspace_file(root, batch["coverage_report_path"]))
        validation = read_json(workspace_file(root, batch["validation_report_path"]))
        expected = {"universe_size": len(genes), "genes_screened": len(genes),
                    "genes_annotated": len({r["subject_label"] for r in records}), "record_count": len(records)}
        if any(coverage.get(k) != v for k, v in expected.items()):
            raise ValueError("Reported coverage differs from independently counted rows")
        if validation.get("validated_rows") != len(records) or validation.get("failed_rows") != 0:
            raise ValueError("Published batch must contain only validated rows; quarantine failures separately")
        reports[batch["id"]] = {**expected, "validated_rows": len(records), "failed_rows": 0,
                                "literature_records": sum(r["evidence_class"] == "literature_extracted" for r in records),
                                "validation_scope": "structure, source hashes, locators and quotations"}
    if literature_count > task["retrieval_budget"]["max_candidate_records"] or len(papers) > task["retrieval_budget"]["max_papers"]:
        raise ValueError("Task-level literature statement or paper budget exceeded")
    return reports


def validate_knowledge_review(task, candidates, review, root):
    """An approved batch is an exact subset of acquired, independently valid rows."""
    batches = {b["id"]: b for b in candidates["batches"]}
    if len(review["batch_decisions"]) != len(batches) or {d["batch_id"] for d in review["batch_decisions"]} != set(batches):
        raise ValueError("Review must cover every acquisition batch")
    validate_batches(task, candidates["batches"], root)
    paths, cache = [], {}
    for decision in review["batch_decisions"]:
        if decision["verdict"] != "accept":
            continue
        batch = batches[decision["batch_id"]]
        acquired = {r["id"]: r for r in read_records(workspace_file(root, batch["records_path"]), task, root, cache)}
        approved_path = workspace_file(root, decision["approved_records_path"])
        if sha256(approved_path) != decision["approved_records_sha256"]:
            raise ValueError("Approved record checksum mismatch")
        approved = read_records(approved_path, task, root, cache)
        if any(r != acquired.get(r["id"]) for r in approved):
            raise ValueError("Reviewer may approve subsets; new or edited claims require acquisition revision")
        audit = read_json(workspace_file(root, decision["audit_report_path"]))
        literature = {r["id"] for r in approved if r["evidence_class"] == "literature_extracted"}
        if literature and (decision.get("review_method") != "full_record_review" or not literature <= set(audit.get("reviewed_record_ids", []))):
            raise ValueError("Every approved literature claim requires explicit record review")
        paths.append(approved_path)
    alias_path = review.get("equivalences_path")
    if bool(alias_path) != bool(review.get("equivalences_sha256")):
        raise ValueError("Equivalence path and checksum must be provided together")
    if alias_path and sha256(workspace_file(root, alias_path)) != review["equivalences_sha256"]:
        raise ValueError("Equivalence artifact checksum mismatch")
    return paths


def assemble(records, equivalences=()):
    """Merge exact statements/evidence while preserving context and polarity.

    Equivalence is an explicit reviewed mapping, never inferred from overlapping
    gene sets. Related/broader/narrower concepts are not equivalences.
    """
    aliases = {}
    for m in equivalences:
        if m.get("relationship") != "equivalent" or not m.get("evidence"):
            raise ValueError("Concept merge requires reviewed equivalence evidence")
        if any(not isinstance(m.get(k), str) or ":" not in m[k] for k in ("alias_id", "canonical_id")):
            raise ValueError("Equivalence identifiers require namespaces")
        if m["alias_id"] in aliases:
            raise ValueError("Duplicate equivalence alias")
        aliases[m["alias_id"]] = m["canonical_id"]
    def canonical(term):
        seen = set()
        while term in aliases:
            if term in seen:
                raise ValueError("Cyclic equivalence mapping")
            seen.add(term)
            term = aliases[term]
        return term
    for term in aliases:
        canonical(term)
    groups = {}
    for record in records:
        obj = canonical(record["object_id"])
        key = encoded([record["subject_label"], record["subject_id"], obj, record["relation"], record["polarity"], record["context"]])
        if key not in groups:
            groups[key] = {"id": "STMT:" + hashlib.sha256(key.encode()).hexdigest()[:24],
                           "subject_id": record["subject_id"], "subject_label": record["subject_label"],
                           "object_id": obj, "object_labels": [], "original_object_ids": [],
                           "relation": record["relation"], "polarity": record["polarity"],
                           "context": record["context"], "record_ids": [], "evidence": [],
                           "evidence_classes": [], "projection_eligible": False}
        row = groups[key]
        for field, value in [("object_labels", record["object_label"]), ("original_object_ids", record["object_id"]),
                             ("record_ids", record["id"]), ("evidence_classes", record["evidence_class"])]:
            if value not in row[field]:
                row[field].append(value)
        for evidence in record["evidence"]:
            if evidence not in row["evidence"]:
                row["evidence"].append(evidence)
        supported = any(e["assertion_type"] in {"database_record", "experimental_result"} for e in record["evidence"])
        row["projection_eligible"] |= record["projection_eligible"] and supported
    for row in groups.values():
        row["study_ids"] = sorted({e["study_id"] for e in row["evidence"]})
        row["identified_study_count"] = sum(not study.startswith("UNRESOLVED:") for study in row["study_ids"])
        for field in ("object_labels", "original_object_ids", "record_ids", "evidence_classes"):
            row[field].sort()
    return sorted(groups.values(), key=lambda r: r["id"])


def conflicts_in(statements):
    groups = defaultdict(list)
    for s in statements:
        key = encoded([s["subject_label"], s["object_id"], s["relation"], s["context"]])
        groups[key].append(s)
    return [{"statement_ids": [s["id"] for s in rows], "reason": "assertion_and_explicit_negation"}
            for rows in groups.values()
            if "negative" in {s["polarity"] for s in rows}
            and {"positive", "not_applicable"} & {s["polarity"] for s in rows}]


def project_attributes(statements, genes, base, policy, task_context):
    attributes = {g: set(base.get(g, [])) for g in genes}
    reasons, members = Counter(), defaultdict(set)
    conflicting = {sid for conflict in conflicts_in(statements) for sid in conflict["statement_ids"]}
    for s in statements:
        reason = None
        if s["id"] in conflicting:
            reason = "conflicting_assertions"
        elif not s["projection_eligible"]:
            reason = "evidence_only"
        elif s["relation"] not in policy["membership_relations"]:
            reason = "relation_not_projected"
        elif s["polarity"] not in {"positive", "not_applicable"}:
            reason = "polarity_not_projected"
        elif policy["context_policy"] == "compatible":
            for key in ("taxon_id", "cell_type", "tissue", "condition"):
                value = s["context"].get(key)
                # General-human exports do not establish activity in the task cell.
                if key == "cell_type" and s["context"].get("source_scope") == "general_human":
                    continue
                if value and value not in {"unknown", "not_applicable"} and task_context.get(key) and value != task_context[key]:
                    reason = "incompatible_context"
                    break
        if reason:
            reasons[reason] += 1
            continue
        term = s["object_id"]
        term = term if term.startswith("GO:") else "EXTERNAL:" + term
        members[term].add(s["subject_label"])
    base_terms = set().union(*attributes.values()) if attributes else set()
    for term, carriers in sorted(members.items()):
        if policy["singleton_policy"] == "exclude_new" and term not in base_terms and len(carriers) == 1:
            reasons["new_singleton_memberships_excluded"] += 1
            continue
        for gene in carriers:
            attributes[gene].add(term)
    return attributes, dict(reasons)


def compile_knowledge(task, plan, records_paths, root, output, provenance_paths=(), equivalences_path=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Use a new compilation directory; existing products are immutable")
    policy = validate_contract(task, plan)
    genes, universe_path = universe_for(task, root)
    inputs = {universe_path, workspace_file(root, policy["baseline_annotations_path"])}
    if policy.get("ontology_path"):
        inputs.add(workspace_file(root, policy["ontology_path"]))
    records, cache = [], {}
    for name in records_paths:
        path = workspace_file(root, name)
        inputs.add(path)
        records.extend(read_records(path, task, root, cache))
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Record IDs must be unique across approved batches")
    inputs.update(p for p in cache if isinstance(p, Path))
    inputs.update(workspace_file(root, p) for p in provenance_paths)
    equivalences = []
    if equivalences_path:
        path = workspace_file(root, equivalences_path)
        inputs.add(path)
        equivalences = read_json(path)
    initial_hashes = {p: sha256(p) for p in inputs}
    statements = assemble(records, equivalences)
    baseline_path = workspace_file(root, policy["baseline_annotations_path"])
    if baseline_path.suffix == ".pkl":
        # Only trusted, local project annotation snapshots may use pickle.
        with baseline_path.open("rb") as stream:
            base = pickle.load(stream)
    else:
        base = read_json(baseline_path)
    if any(not isinstance(base.get(g, []), (list, set, tuple)) or any(not isinstance(t, str) for t in base.get(g, [])) for g in genes):
        raise ValueError("Invalid baseline gene annotation sets")
    context = {**task.get("biological_context", {}), "taxon_id": task["organism"]["taxon_id"]}
    attributes, exclusions = project_attributes(statements, genes, base, policy["projection"], context)
    output.mkdir(parents=True)
    write_json(output / "task.json", task)
    write_json(output / "plan.json", plan)
    write_rows(output / "statements.jsonl", statements)
    write_rows(output / "conflicts.jsonl", conflicts_in(statements))
    write_rows(output / "gene_attributes.jsonl", ({"gene": g, "attributes": sorted(attributes[g])} for g in genes))
    evidence = {hashlib.sha256(encoded(e).encode()).hexdigest(): e for s in statements for e in s["evidence"]}
    write_rows(output / "evidence.jsonl", ({"id": key, **e} for key, e in sorted(evidence.items())))
    carriers = Counter(term for terms in attributes.values() for term in terms)
    base_memberships = sum(len(set(base.get(g, []))) for g in genes)
    metrics = {"genes": len(genes), "input_records": len(records), "canonical_statements": len(statements),
               "evidence_records": len(evidence), "distinct_attributes": len(carriers),
               "gene_attribute_memberships": sum(carriers.values()), "baseline_memberships": base_memberships,
               "added_memberships": sum(carriers.values()) - base_memberships,
               "single_gene_attributes": sum(n == 1 for n in carriers.values()), "projection_exclusions": exclusions,
               "leakage_audit": "external_to_pipeline; no clearance asserted"}
    write_json(output / "validation.json", {"passed": True, "validated_rows": len(records), "failed_rows": 0,
                                           "scope": "structure, provenance, exact evidence and projection invariants"})
    write_json(output / "summary.json", metrics)
    inputs.add(Path(__file__).resolve())
    manifest = {"schema_version": "3.0", "task_id": task["task_id"], "knowledge_contract": policy,
                "inputs": [{"path": str(p), "sha256": sha256(p)} for p in sorted(inputs)],
                "files": [{"path": p.name, "sha256": sha256(p)} for p in sorted(output.iterdir()) if p.is_file()],
                "leakage_audit": "independent external audit; not performed by augmentation agents"}
    # Verify input stability across the complete assembly, including cached evidence.
    if any(sha256(p) != digest for p, digest in cache.items() if isinstance(p, Path)):
        raise ValueError("Evidence changed during compilation")
    if any(sha256(p) != digest for p, digest in initial_hashes.items()):
        raise ValueError("Compilation input changed during assembly")
    write_json(output / "freeze_manifest.json", manifest)
    return metrics

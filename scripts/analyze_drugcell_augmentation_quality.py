"""Audit frozen DrugCell augmentation content and its exported representation.

This read-only audit of experiment inputs writes separate analytical artifacts.
It uses ontology annotations and provenance; response labels and scores play no
role in classifying knowledge. Exact gene-set equality describes representation
redundancy in the fixed universe and does not assert biological equivalence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path

import drugcell_ontology as ontology


def records(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def read_obo(path):
    terms, current = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("["):
            current = {} if line == "[Term]" else None
        elif current is not None and ": " in line:
            key, value = line.split(": ", 1)
            if key == "id":
                current.update(id=value, parents=set(), obsolete=False)
                terms[value] = current
            elif key in {"name", "namespace"}:
                current[key] = value
            elif key == "is_obsolete":
                current["obsolete"] = value == "true"
            elif key == "is_a":
                current["parents"].add(value.split()[0])
            elif key == "relationship" and value.startswith("part_of "):
                current["parents"].add(value.split()[1])
    return terms


def histogram(values):
    values = list(values)
    return {"1": sum(x == 1 for x in values),
            "2-4": sum(2 <= x <= 4 for x in values),
            "5-9": sum(5 <= x <= 9 for x in values),
            "10-29": sum(10 <= x <= 29 for x in values),
            "30+": sum(x >= 30 for x in values)}


def table(path, rows):
    rows = list(rows)
    if rows:
        with path.open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)


def verify_sources(snapshot, baseline_pairs):
    """Reconcile every approved database assertion to its saved source row."""
    provenance = snapshot / "provenance"
    approved = provenance / "review/reviewer_002"
    result = {}
    experimental = {"EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"}
    pair_codes = defaultdict(set)
    for batch, source in [("goa_human_r1", "goa_human.gaf"),
                          ("complexportal_human_r1", "complexportal_9606.tsv")]:
        pending = defaultdict(list)
        for record in records(approved / (batch + ".approved.jsonl")):
            for evidence in record["evidence"]:
                line = int(evidence["locator"].split(":")[1])
                pending[line].append((record, evidence))
        errors, checked, interacting_taxa = [], 0, Counter()
        for number, line in enumerate((provenance / "acquisition/sources" / source).open(), 1):
            if number not in pending:
                continue
            fields = line.rstrip("\n").split("\t")
            for record, evidence in pending.pop(number):
                checked += 1
                if batch.startswith("goa"):
                    comparisons = {"protein": (fields[1], evidence["original_protein_id"]),
                                   "GO": (fields[4], evidence["original_go_id"]),
                                   "evidence": (fields[6], evidence["source_evidence_code"]),
                                   "qualifier": (fields[3], evidence["qualifier"]),
                                   "symbol": (fields[2], evidence["source_gene_symbol"]),
                                   "species": (fields[12].split("|")[0], "taxon:9606"), "aspect": (fields[8], "P")}
                    if "|" in fields[12]:
                        interacting_taxa[fields[12].split("|", 1)[1]] += 1
                    pair_codes[(record["subject_label"], record["object_id"])].add(fields[6])
                    if "NOT" in fields[3].split("|"):
                        errors.append({"id": record["id"], "reason": "negated_source_membership"})
                else:
                    comparisons = {"complex": ("ComplexPortal:" + fields[0], record["object_id"]),
                                   "species": (fields[3], "9606"),
                                   "expanded_participants": (fields[18], evidence["expanded_participant_list"])}
                    participants = {p.split("(")[0] for p in fields[18].split("|")}
                    if evidence["original_protein_id"] not in participants:
                        errors.append({"id": record["id"], "reason": "protein_not_source_participant"})
                for key, (observed, expected) in comparisons.items():
                    if observed != expected:
                        errors.append({"id": record["id"], "field": key,
                                       "observed": observed, "expected": expected})
        result[batch] = {"source_evidence_rows_checked": checked, "mismatches": errors,
                         "missing_source_lines": sorted(pending),
                         "source_interacting_taxon_counts": dict(interacting_taxa)}
    novel_codes = {p: codes for p, codes in pair_codes.items() if p not in baseline_pairs}
    result["GOA_novel_evidence"] = {
        "unique_new_pairs": len(novel_codes),
        "any_experimental": sum(bool(codes & experimental) for codes in novel_codes.values()),
        "without_experimental": sum(not bool(codes & experimental) for codes in novel_codes.values()),
        "NAS_only": sum(codes == {"NAS"} for codes in novel_codes.values()),
        "ISS_only": sum(codes == {"ISS"} for codes in novel_codes.values()),
        "IBA_only": sum(codes == {"IBA"} for codes in novel_codes.values()),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment, out = args.experiment.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshot = experiment / "knowledge_snapshot"
    genes = ontology.read_gene_map(experiment / "source_inputs/gene2ind.txt")
    baseline = ontology.read_ontology(experiment / "baseline/drugcell_ont.txt", genes)
    augmented = ontology.read_ontology(experiment / "augmentation/drugcell_ont.txt", genes)
    obo = read_obo(snapshot / "provenance/inputs/go.obo")
    aliases = json.loads((experiment / "projection_inputs/external_identifier_map.json").read_text())

    @lru_cache(None)
    def ancestors(term):
        result = {term}
        for parent in obo.get(term, {}).get("parents", ()):
            result.update(ancestors(parent))
        return frozenset(result)

    def projected_id(term):
        term = term if term.startswith("GO:") else "EXTERNAL:" + term
        return aliases.get(term, term)

    baseline_pairs = {(gene, term) for term, gs in baseline["propagated"].items() for gene in gs}
    snapshot_pairs = {(row["gene"], aliases.get(term, term)) for row in records(snapshot / "gene_attributes.jsonl")
                      for term in row["attributes"]}
    new_pairs = snapshot_pairs - baseline_pairs
    new_terms = augmented["terms"] - baseline["terms"]
    labels, pair_sources, term_sources = {}, defaultdict(set), defaultdict(set)
    source_pairs, source_rows = defaultdict(set), Counter()
    source_evidence, source_qualifiers = defaultdict(Counter), defaultdict(Counter)
    qualifier_pairs = defaultdict(set)
    literature, context_rows, pair_contexts = [], [], defaultdict(set)
    semantic_errors = []
    all_statements = list(records(snapshot / "statements.jsonl"))
    for row in all_statements:
        obj = projected_id(row["object_id"])
        labels[obj] = " | ".join(row["object_labels"])
        names = {e.get("source_name", "unknown") for e in row["evidence"]}
        if row["projection_eligible"]:
            pair = (row["subject_label"], obj)
            pair_sources[pair].update(names)
            term_sources[obj].update(names)
            for name in names:
                source_pairs[name].add(pair)
            pair_contexts[pair].add(json.dumps(row["context"], sort_keys=True))
            if row["polarity"] != "positive":
                semantic_errors.append({"id": row["id"], "reason": "projected_nonpositive"})
            if obj.startswith("GO:") and (obj not in obo or obo[obj].get("obsolete")
                                            or obo[obj].get("namespace") != "biological_process"):
                semantic_errors.append({"id": row["id"], "reason": "invalid_projected_GO"})
        if "literature_extracted" in row["evidence_classes"]:
            literature.append(row)
            pair = (row["subject_label"], obj)
            context_rows.append({
                "statement": row["id"], "gene": row["subject_label"],
                "relation": row["relation"], "term": obj, "label": labels[obj],
                "projected": row["projection_eligible"], "new_vs_baseline": pair not in baseline_pairs,
                "study_ids": "|".join(row["study_ids"]),
                "cell_line": row["context"].get("cell_line", "unknown"),
                "compound": row["context"].get("compound", "unknown"),
                "genotype": row["context"].get("genotype", "unknown"),
            })
    approved = snapshot / "provenance/review/reviewer_002"
    for path in sorted(approved.glob("*.approved.jsonl")):
        for row in records(path):
            names = {e.get("source_name", "unknown") for e in row["evidence"]}
            for name in names:
                source_rows[name] += 1
            for evidence in row["evidence"]:
                name = evidence.get("source_name", "unknown")
                source_evidence[name][evidence.get("source_evidence_code", "unspecified")] += 1
                source_qualifiers[name][evidence.get("qualifier", "unspecified")] += 1
                if row["projection_eligible"]:
                    qualifier_pairs[evidence.get("qualifier", "unspecified")].add(
                        (row["subject_label"], projected_id(row["object_id"])))

    sources = []
    for source, pairs in sorted(source_pairs.items()):
        novel = pairs - baseline_pairs
        unique_new = {p for p in novel if pair_sources[p] == {source}}
        sources.append({"source": source, "approved_records": source_rows[source],
                        "projectable_unique_pairs": len(pairs), "new_pairs": len(novel),
                        "source_exclusive_new_pairs": len(unique_new),
                        "new_genes": len({g for g, _ in novel}),
                        "new_terms": len({t for _, t in novel if t in new_terms})})

    term_evidence_genes = defaultdict(set)
    for gene, term in pair_sources:
        term_evidence_genes[term].add(gene)
    equality = defaultdict(list)
    baseline_sets = defaultdict(list)
    for term, gs in baseline["propagated"].items():
        baseline_sets[frozenset(gs)].append(term)
    for term, gs in augmented["propagated"].items():
        equality[frozenset(gs)].append(term)
    duplicate_groups = [v for v in equality.values() if len(v) > 1]
    rows = []
    for term in sorted(augmented["terms"]):
        gs, children = augmented["propagated"][term], augmented["children"][term]
        support = sorted(term_evidence_genes[term])
        group = equality[frozenset(gs)]
        rows.append({"term": term, "label": obo.get(term, {}).get("name", labels.get(term, "unknown")),
                     "new": term in new_terms, "kind": "GO" if term.startswith("GO:") else "external",
                     "sources": "|".join(sorted(term_sources[term])),
                     "direct_genes": len(augmented["direct"][term]), "propagated_genes": len(gs),
                     "children": len(children),
                     "min_parent_minus_child_genes": min((len(gs - augmented["propagated"][c])
                                                          for c in children), default=""),
                     "same_gene_set_nodes": len(group),
                     "same_as_baseline_gene_set": bool(baseline_sets.get(frozenset(gs))),
                     "gene_set": "|".join(sorted(gs)), "direct_evidence_genes": "|".join(support)})
    table(out / "terms.tsv", rows)
    table(out / "sources.tsv", sources)
    table(out / "literature.tsv", context_rows)
    table(out / "duplicate_gene_sets.tsv", (
        {"genes": "|".join(sorted(gs)), "terms": "|".join(sorted(ts)),
         "n_genes": len(gs), "n_terms": len(ts), "new_terms": sum(t in new_terms for t in ts)}
        for gs, ts in sorted(equality.items(), key=lambda item: (-len(item[1]), sorted(item[0])))
        if len(ts) > 1))

    category_roots = ["GO:0006281", "GO:0007049", "GO:0006915", "GO:0007165",
                      "GO:0006338", "GO:0006914", "GO:0045454", "GO:0006805",
                      "GO:0006855", "GO:0015811", "GO:0007399", "GO:0007610",
                      "GO:0003008", "GO:0032502", "GO:0002376"]
    categories = []
    for root in category_roots:
        ts = {t for t in new_terms if root in ancestors(t)}
        ps = {(g, t) for g, t in new_pairs if root in ancestors(t)}
        categories.append({"root": root, "label": obo.get(root, {}).get("name", "unknown"),
                           "new_GO_terms": len(ts), "explicit_new_pairs": len(ps),
                           "genes": len({g for g, _ in ps})})
    table(out / "thematic_categories.tsv", categories)

    new_rows = [r for r in rows if r["new"]]
    go_rows = [r for r in new_rows if r["kind"] == "GO"]
    external_rows = [r for r in new_rows if r["kind"] == "external"]
    raw_edges = [(t, g) for t, g in augmented["memberships"] - baseline["memberships"]]
    supported_new = {(g, t) for g, t in new_pairs if pair_sources[(g, t)]}
    lit_pairs = {(r["subject_label"], projected_id(r["object_id"])) for r in literature
                 if r["projection_eligible"]}
    lit_novel = lit_pairs - baseline_pairs
    new_graph_pairs = {(g, t) for t, gs in augmented["propagated"].items() for g in gs} - baseline_pairs
    root = augmented["root"]
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "experiment": str(experiment),
        "scope": "Frozen biological content and graph representation; causal attribution of test changes is outside this audit",
        "new_terms": len(new_terms), "new_GO_terms": len(go_rows), "new_external_terms": len(external_rows),
        "new_terms_gene_count_histogram": histogram(r["propagated_genes"] for r in new_rows),
        "GO_gene_count_histogram": histogram(r["propagated_genes"] for r in go_rows),
        "external_gene_count_histogram": histogram(r["propagated_genes"] for r in external_rows),
        "new_explicit_knowledge_pairs": len(new_pairs), "supported_new_pairs": len(supported_new),
        "new_exported_direct_pairs": len(raw_edges), "new_propagated_graph_pairs": len(new_graph_pairs),
        "new_pairs_not_explicitly_in_knowledge": len(new_graph_pairs - snapshot_pairs),
        "sources": sources, "source_evidence_codes": dict(source_evidence),
        "source_qualifiers": dict(source_qualifiers),
        "GOA_new_pair_qualifiers": {q: len(ps - baseline_pairs) for q, ps in qualifier_pairs.items()
                                   if q != "unspecified"},
        "GOA_new_upstream_pairs_union": len(set().union(*[
            ps for q, ps in qualifier_pairs.items() if q.startswith("acts_upstream")]) - baseline_pairs),
        "GOA_new_signed_pairs_union": len(set().union(*[
            ps for q, ps in qualifier_pairs.items() if "effect" in q]) - baseline_pairs),
        "invalid_projected_statements": semantic_errors,
        "duplicate_gene_set_groups": len(duplicate_groups),
        "nodes_in_duplicate_gene_set_groups": sum(len(g) for g in duplicate_groups),
        "new_nodes_in_duplicate_gene_set_groups": sum(r["same_gene_set_nodes"] > 1 for r in new_rows),
        "new_nodes_matching_a_baseline_gene_set": sum(r["same_as_baseline_gene_set"] for r in new_rows),
        "new_nodes_with_zero_parent_child_gene_difference": sum(
            r["min_parent_minus_child_genes"] == 0 for r in new_rows),
        "new_nodes_with_parent_child_difference_below30": sum(
            isinstance(r["min_parent_minus_child_genes"], int)
            and r["min_parent_minus_child_genes"] < 30 for r in new_rows),
        "root_children_baseline": len(baseline["children"][root]),
        "root_children_augmented": len(augmented["children"][root]),
        "root_external_children": len({t for t in augmented["children"][root] if not t.startswith("GO:")}),
        "root_linear_inputs_baseline": len(baseline["direct"][root]) + 6 * len(baseline["children"][root]),
        "root_linear_inputs_augmented": len(augmented["direct"][root]) + 6 * len(augmented["children"][root]),
        "literature": {"statements": len(literature), "relations": dict(Counter(r["relation"] for r in literature)),
                       "papers": len({s for r in literature for s in r["study_ids"]}),
                       "projected_statements": sum(r["projection_eligible"] for r in literature),
                       "projected_unique_pairs": len(lit_pairs), "novel_pairs_vs_baseline": len(lit_novel),
                       "novel_pairs_exclusive_to_literature": sum(pair_sources[p] == {"PubMed/PMC"} for p in lit_novel),
                       "projected_contexts_collapsed_pairs": sum(len(pair_contexts[p]) > 1 for p in lit_pairs)},
        "thematic_categories": categories,
        "inputs": {str(path.relative_to(experiment)): ontology.sha256(path) for path in [
            snapshot / "freeze_manifest.json", snapshot / "statements.jsonl",
            snapshot / "gene_attributes.jsonl", experiment / "baseline/drugcell_ont.txt",
            experiment / "augmentation/drugcell_ont.txt"]},
    }
    source_verification = verify_sources(snapshot, baseline_pairs)
    (out / "source_verification.json").write_text(json.dumps(source_verification, indent=2, sort_keys=True) + "\n")
    summary["source_verification"] = source_verification
    assert summary["supported_new_pairs"] == summary["new_explicit_knowledge_pairs"]
    manifest = json.loads((experiment / "augmentation/projection_manifest.json").read_text())
    assert len(new_terms) == manifest["projection_counts"]["added_terms"]
    assert len(new_graph_pairs) == manifest["projection_counts"]["new_propagated_memberships"]
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"source_evidence_codes", "source_qualifiers",
                                                                "thematic_categories", "inputs", "source_verification"}}, indent=2))


if __name__ == "__main__":
    main()

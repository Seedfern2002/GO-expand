"""Find identity, lexical and projected-feature redundancy candidates in frozen GO overlays."""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import itertools
import json
from pathlib import Path
import re
import unicodedata


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize(label):
    label = unicodedata.normalize("NFKC", label).casefold()
    label = label.replace("b(0)at1", "b0at1")
    for char, word in [("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"), ("ε", "epsilon")]:
        label = label.replace(char, word)
    return " ".join(re.findall(r"[a-z0-9]+", label))


def write_table(path, rows, fields):
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_obo(path):
    terms, current = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("["):
            current = None
        elif line.startswith("id: GO:"):
            current = {"id": line[4:], "aliases": [], "alt_ids": [], "replaced_by": []}
            terms[current["id"]] = current
        elif current is not None:
            for key in ("name", "namespace", "def", "is_obsolete"):
                if line.startswith(key + ": "):
                    current[key] = line[len(key) + 2:]
            for key in ("alt_id", "replaced_by"):
                if line.startswith(key + ": "):
                    current["alt_ids" if key == "alt_id" else key].append(line[len(key) + 2:])
            match = re.match(r'synonym: "(.*)" EXACT ', line)
            if match:
                current["aliases"].append(match.group(1))
    return terms


def main(workspace, output):
    if output.exists():
        raise FileExistsError("Use a fresh audit directory")
    knowledge = workspace / "knowledge"
    manifest = json.loads((knowledge / "freeze_manifest.json").read_text())
    for item in manifest["files"]:
        assert digest(knowledge / item["path"]) == item["sha256"]
    baseline = {g: set(a) for g, a in json.loads((workspace / "inputs/annotations.json").read_text()).items()}
    carriers, additions = defaultdict(set), defaultdict(set)
    for row in map(json.loads, (knowledge / "gene_attributes.jsonl").open()):
        for attribute in row["attributes"]:
            carriers[attribute].add(row["gene"])
            if attribute not in baseline[row["gene"]]:
                additions[attribute].add(row["gene"])
    terms = read_obo(workspace / "inputs/go.obo")
    labels, context = defaultdict(set), defaultdict(set)
    local, sources = set(), defaultdict(set)
    for row in map(json.loads, (knowledge / "statements.jsonl").open()):
        attribute = row["object_id"] if row["object_id"].startswith("GO:") else "EXTERNAL:" + row["object_id"]
        if attribute not in carriers:
            continue
        labels[attribute].update(row["object_labels"])
        sources[attribute].update(e["source_name"] for e in row["evidence"])
        if "literature_extracted" in row["evidence_classes"]:
            if not attribute.startswith("GO:"):
                local.add(attribute)
            context[attribute].add(json.dumps(row["context"], sort_keys=True, ensure_ascii=False))
    aliases = defaultdict(list)
    for attribute in carriers:
        if attribute in terms:
            term = terms[attribute]
            labels[attribute].add(term.get("name", attribute))
            aliases[attribute] += [(name, "GO_exact_synonym") for name in term["aliases"]]
    cp_rows = {}
    with (workspace / "acquisition/sources/complexportal_9606.tsv").open() as stream:
        for number, row in enumerate(csv.DictReader(stream, delimiter="\t"), 2):
            attribute = "EXTERNAL:ComplexPortal:" + row["#Complex ac"]
            if attribute in carriers:
                cp_rows[attribute] = row
                aliases[attribute] += [(name, "ComplexPortal_alias") for name in row["Aliases for complex"].split("|") if name != "-"]
    candidates = defaultdict(set)

    def add(a, b, reason):
        if a != b:
            candidates[tuple(sorted((a, b)))].add(reason)

    names = defaultdict(set)
    for attribute in carriers:
        for label in labels[attribute]:
            names[normalize(label)].add(attribute)
    for group in names.values():
        for a, b in itertools.combinations(sorted(group), 2):
            add(a, b, "normalized_label_match")
    for attribute, values in aliases.items():
        for label, reason in values:
            for match in names.get(normalize(label), ()):
                add(attribute, match, reason)
    all_names = defaultdict(set, {key: set(value) for key, value in names.items()})
    for attribute, values in aliases.items():
        for label, _ in values:
            all_names[normalize(label)].add(attribute)
    # Scope words are removed for candidate discovery only; review retains their meaning.
    for attribute in local:
        for label in labels[attribute]:
            simplified = re.sub(r"\b(?:human|reconstituted|canonical|structural)\b", "", label, flags=re.I)
            for match in all_names.get(normalize(simplified), ()):
                add(attribute, match, "local_scope_normalized_alias_candidate")
    for canonical, term in terms.items():
        if canonical in carriers:
            for alternate in term["alt_ids"]:
                if alternate in carriers:
                    add(canonical, alternate, "official_GO_alt_id")
        if canonical in carriers and term.get("is_obsolete") == "true":
            for replacement in term["replaced_by"]:
                if replacement in carriers:
                    add(canonical, replacement, "official_GO_replacement")
    # Token retrieval is a discovery aid for local study concepts with extra qualifiers.
    stop = {"human", "complex", "regulation", "of", "the", "a", "and", "in", "cell", "protein", "activity", "reconstituted"}
    token_index = defaultdict(set)
    tokens = {}
    for attribute in carriers:
        tokens[attribute] = set(normalize(" ".join(labels[attribute])).split()) - stop
        for token in tokens[attribute]:
            token_index[token].add(attribute)
    for attribute in local:
        pool = set().union(*(token_index[t] for t in tokens[attribute])) if tokens[attribute] else set()
        for other in pool:
            shared = tokens[attribute] & tokens[other]
            score = len(shared) / max(1, len(tokens[attribute] | tokens[other]))
            if len(shared) >= 2 and score >= 0.45:
                add(attribute, other, "local_concept_token_overlap")
    rows = []
    for (a, b), reasons in sorted(candidates.items()):
        shared = carriers[a] & carriers[b]
        rows.append({"attribute_a": a, "label_a": " | ".join(sorted(labels[a])),
                     "attribute_b": b, "label_b": " | ".join(sorted(labels[b])),
                     "candidate_reasons": ";".join(sorted(reasons)),
                     "genes_a": len(carriers[a]), "genes_b": len(carriers[b]), "shared_genes": len(shared),
                     "gene_set_jaccard": len(shared) / len(carriers[a] | carriers[b]),
                     "new_gene_links_a": len(additions[a]), "new_gene_links_b": len(additions[b]),
                     "shared_gene_names": ";".join(sorted(shared)),
                     "review_status": "candidate_requires_semantic_review"})
    groups = defaultdict(list)
    for attribute, genes in carriers.items():
        groups[tuple(sorted(genes))].append(attribute)
    duplicate_sets = []
    for genes, attributes in groups.items():
        if len(attributes) > 1 and any(additions[a] for a in attributes):
            duplicate_sets.append({"gene_count": len(genes), "attribute_count": len(attributes),
                                   "genes": ";".join(genes), "attribute_ids": ";".join(sorted(attributes))})
    duplicate_sets.sort(key=lambda row: (-row["gene_count"], -row["attribute_count"], row["genes"]))
    output.mkdir(parents=True)
    write_table(output / "name_candidates.tsv", rows, list(rows[0]) if rows else ["attribute_a", "attribute_b"])
    write_table(output / "identical_gene_set_groups.tsv", duplicate_sets,
                ["gene_count", "attribute_count", "genes", "attribute_ids"])
    inventory = [{"attribute_id": a, "labels": " | ".join(sorted(labels[a])),
                  "gene_count": len(carriers[a]), "new_gene_links": len(additions[a]),
                  "genes": ";".join(sorted(carriers[a])), "source_names": ";".join(sorted(sources[a]))}
                 for a in sorted(carriers)]
    write_table(output / "attribute_inventory.tsv", inventory, list(inventory[0]))
    summary = {"attributes": len(carriers), "attributes_with_added_gene_links": sum(bool(v) for v in additions.values()),
               "local_literature_attribute_ids": len(local), "lexical_or_identifier_candidate_pairs": len(rows),
               "candidate_reason_counts": dict(Counter(reason for v in candidates.values() for reason in v)),
               "identical_gene_set_groups_touching_additions": len(duplicate_sets),
               "identical_gene_set_groups_with_at_least_two_genes": sum(g["gene_count"] >= 2 for g in duplicate_sets),
               "projection_duplicate_scope": "Identical membership vectors in this gene universe; biological equivalence requires separate evidence.",
               "inputs": [{"path": str(p), "sha256": digest(p)} for p in
                          [knowledge / "freeze_manifest.json", workspace / "inputs/go.obo",
                           workspace / "acquisition/sources/complexportal_9606.tsv", Path(__file__).resolve()]]}
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.workspace.resolve(), args.output.resolve())

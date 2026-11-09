"""Summarize gene frequencies of literature-supported additions in frozen knowledge."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "outputs/.matplotlib"))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_table(path, rows):
    with path.open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def histogram(values):
    return {str(k): v for k, v in sorted(Counter(values).items())}


def analyze(workspace, output):
    knowledge = workspace / "knowledge"
    manifest = json.loads((knowledge / "freeze_manifest.json").read_text())
    for item in manifest["files"]:
        if sha256(knowledge / item["path"]) != item["sha256"]:
            raise ValueError("Frozen knowledge hash mismatch: " + item["path"])
    baseline_path = workspace / "inputs/annotations.json"
    frozen_baseline = next(item for item in manifest["inputs"] if item["path"] == "/workspace/inputs/annotations.json")
    if sha256(baseline_path) != frozen_baseline["sha256"]:
        raise ValueError("Original annotation hash mismatch")
    base = {g: set(a) for g, a in json.loads(baseline_path.read_text()).items()}
    final = {row["gene"]: set(row["attributes"]) for row in
             map(json.loads, (knowledge / "gene_attributes.jsonl").open())}
    if set(base) != set(final) or any(not base[g] <= final[g] for g in base):
        raise ValueError("Expected the fixed universe and preserved original annotations")
    vocabulary = set().union(*base.values())
    policy = manifest["knowledge_contract"]["projection"]
    if policy["context_policy"] != "preserve" or policy["singleton_policy"] != "retain":
        raise ValueError("This analysis supports the preserve-context, retain-singletons projection")
    conflicting = {sid for row in map(json.loads, (knowledge / "conflicts.jsonl").open()) for sid in row["statement_ids"]}
    reconstructed = {g: set(a) for g, a in base.items()}
    literature, database = set(), set()
    labels, studies, relations, statements = (defaultdict(set) for _ in range(4))
    for line in (knowledge / "statements.jsonl").open():
        row = json.loads(line)
        if (row["id"] in conflicting or not row["projection_eligible"] or
            row["relation"] not in policy["membership_relations"] or
            row["polarity"] not in {"positive", "not_applicable"}):
            continue
        term = row["object_id"]
        attribute = term if term.startswith("GO:") else "EXTERNAL:" + term
        pair = row["subject_label"], attribute
        reconstructed[pair[0]].add(attribute)
        if set(row["evidence_classes"]) - {"literature_extracted"}:
            database.add(pair)
        if "literature_extracted" in row["evidence_classes"]:
            literature.add(pair)
            labels[attribute].update(row["object_labels"])
            studies[pair].update(e["study_id"] for e in row["evidence"] if e["assertion_type"] != "database_record")
            relations[attribute].add(row["relation"])
            statements[pair].add(row["id"])
    if reconstructed != final:
        raise ValueError("Reconstructed projection differs from the frozen gene attributes")
    all_new = {(g, a) for g, terms in final.items() for a in terms - base[g]}
    added = literature & all_new
    new_by_attribute = defaultdict(set)
    for gene, attribute in added:
        new_by_attribute[attribute].add(gene)
    if not added:
        raise ValueError("No literature-supported additions to analyze")
    base_carriers, final_carriers = defaultdict(set), defaultdict(set)
    for target, data in [(base_carriers, base), (final_carriers, final)]:
        for gene, terms in data.items():
            for term in terms:
                target[term].add(gene)
    rows = []
    for attribute, genes in new_by_attribute.items():
        paper_ids = set().union(*(studies[(g, attribute)] for g in genes))
        rows.append({
            "attribute_id": attribute, "label": " | ".join(sorted(labels[attribute])),
            "attribute_type": "GO" if attribute.startswith("GO:") else "external",
            "absent_from_original_annotation_vocabulary": attribute not in vocabulary,
            "literature_added_gene_count": len(genes),
            "literature_exclusive_added_gene_count": sum((g, attribute) not in database for g in genes),
            "also_database_supported_added_gene_count": sum((g, attribute) in database for g in genes),
            "original_total_gene_count": len(base_carriers[attribute]),
            "final_total_gene_count": len(final_carriers[attribute]),
            "literature_added_genes": ";".join(sorted(genes)),
            "final_all_genes": ";".join(sorted(final_carriers[attribute])),
            "supporting_study_id_count": len(paper_ids), "supporting_study_ids": ";".join(sorted(paper_ids)),
            "relations": ";".join(sorted(relations[attribute])),
        })
    rows.sort(key=lambda row: (-row["literature_added_gene_count"], row["attribute_id"]))
    novel = [row for row in rows if row["absent_from_original_annotation_vocabulary"]]
    knowledge_summary = json.loads((knowledge / "summary.json").read_text())
    if len(all_new) != knowledge_summary["added_memberships"]:
        raise ValueError("Overall added-membership count mismatch")
    review_path = workspace / "review/summary.json"
    if review_path.exists():
        review = json.loads(review_path.read_text())
        if review.get("literature_additional_memberships", len(added)) != len(added):
            raise ValueError("Literature additions differ from independent review")
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Final approved literature-supported membership/function projection across the complete fixed gene universe",
        "definitions": {
            "literature_added_gene_count": "Unique genes newly linked to this attribute by literature relative to original GEARS annotations; repeated papers/contexts count once per gene and attribute.",
            "final_total_gene_count": "All genes carrying the attribute in the frozen final product, including original GO and database-supported associations.",
            "absent_from_original_annotation_vocabulary": "Attribute ID occurs in none of the original gene annotations; existing GO ontology IDs can satisfy this criterion.",
            "source_overlap": "Literature-supported additions include pairs also supported by databases; their overlap and exclusive counts are reported separately.",
            "identifier_policy": "Use the frozen exact attribute IDs; preserve source-specific and context-qualified concepts and their reviewed equivalences.",
        },
        "gene_universe": len(base), "literature_projected_memberships": len(literature),
        "literature_baseline_overlap_memberships": len(literature) - len(added),
        "literature_added_memberships": len(added), "genes_with_literature_additions": len({g for g, a in added}),
        "attributes_with_literature_additions": len(rows),
        "single_gene_attributes_by_literature_added_count": sum(row["literature_added_gene_count"] == 1 for row in rows),
        "multiple_gene_attributes_by_literature_added_count": sum(row["literature_added_gene_count"] > 1 for row in rows),
        "existing_attribute_ids_with_new_gene_links": len(rows) - len(novel),
        "attribute_ids_absent_from_original_annotations": len(novel),
        "novel_ids_by_type": dict(Counter(row["attribute_type"] for row in novel)),
        "literature_database_overlap_added_memberships": len(added & database),
        "literature_exclusive_added_memberships": len(added - database),
        "histograms": {
            "literature_added_genes_per_attribute": histogram(row["literature_added_gene_count"] for row in rows),
            "final_total_genes_per_literature_added_attribute": histogram(row["final_total_gene_count"] for row in rows),
            "literature_added_genes_per_novel_attribute_id": histogram(row["literature_added_gene_count"] for row in novel),
            "final_total_genes_per_novel_attribute_id": histogram(row["final_total_gene_count"] for row in novel),
        },
        "inputs": [{"path": str(path), "sha256": sha256(path)} for path in
                   [knowledge / "freeze_manifest.json", baseline_path, Path(__file__).resolve()]],
    }
    output.mkdir(parents=True)
    write_table(output / "attribute_gene_counts.tsv", rows)
    write_table(output / "new_attribute_ids.tsv", novel)
    write_table(output / "top_attributes.tsv", rows[:12])
    distribution_rows = []
    for name, counts in summary["histograms"].items():
        denominator = sum(counts.values())
        for count, frequency in counts.items():
            distribution_rows.append({"distribution": name, "genes_per_attribute": int(count),
                                      "attribute_count": frequency, "percent_of_attributes": 100 * frequency / denominator})
    write_table(output / "distributions.tsv", distribution_rows)
    write_table(output / "literature_added_pairs.tsv", [
        {"gene": g, "attribute_id": a, "also_database_supported": (g, a) in database,
         "supporting_study_ids": ";".join(sorted(studies[(g, a)])),
         "canonical_statement_ids": ";".join(sorted(statements[(g, a)]))} for g, a in sorted(added)
    ])
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return rows, summary


def plot(rows, summary, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 12,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "svg.fonttype": "none"})
    blue, orange = "#4477AA", "#EE9955"

    def save(figure, name):
        for suffix in ("png", "pdf", "svg"):
            figure.savefig(output / f"{name}.{suffix}", dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(figure)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.1), layout="constrained")
    xs = sorted({row["literature_added_gene_count"] for row in rows})
    old = Counter(row["literature_added_gene_count"] for row in rows if not row["absent_from_original_annotation_vocabulary"])
    new = Counter(row["literature_added_gene_count"] for row in rows if row["absent_from_original_annotation_vocabulary"])
    positions = list(range(len(xs)))
    axes[0].bar(positions, [old[x] for x in xs], color=blue, label="ID present in original annotations")
    axes[0].bar(positions, [new[x] for x in xs], bottom=[old[x] for x in xs], color=orange,
                label="ID absent from original annotations")
    for i, x in enumerate(xs):
        axes[0].text(i, old[x] + new[x] + 0.8, str(old[x] + new[x]), ha="center")
    axes[0].set_xticks(positions, [str(x) for x in xs])
    axes[0].set_xlabel("Genes newly linked by literature per attribute")
    axes[0].set_title(f"A  All {len(rows)} attributes with literature additions", loc="left", pad=14)
    axes[0].set_ylim(0, max(old[x] + new[x] for x in xs) * 1.2)
    axes[0].legend(frameon=False, fontsize=9, loc="upper right")
    counts = summary["histograms"]["final_total_genes_per_novel_attribute_id"]
    xs2 = [int(x) for x in counts]
    bars = axes[1].bar(range(len(xs2)), list(counts.values()), color=orange, width=0.65)
    axes[1].bar_label(bars, padding=5)
    axes[1].set_xticks(range(len(xs2)), [str(x) for x in xs2])
    axes[1].set_xlabel("All carriers per attribute in the final overlay")
    axes[1].set_title(f"B  Only {sum(counts.values())} IDs absent from original annotations", loc="left", pad=14)
    axes[1].set_ylim(0, max(counts.values()) * 1.2)
    for ax in axes:
        ax.set_ylabel("Number of attributes")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(axis="y", alpha=0.16)
        ax.set_axisbelow(True)
    fig.suptitle("Gene frequencies of literature-supported attributes", fontsize=16, fontweight="bold")
    fig.supxlabel(f"{summary['gene_universe']:,} genes | {summary['literature_added_memberships']} new literature-supported gene–attribute pairs\n"
                  "A counts literature additions. B includes all original, database and literature carriers of new attribute IDs.", fontsize=9)
    save(fig, "literature_attribute_frequency")

    top = rows[:12]
    fig, ax = plt.subplots(figsize=(11.5, 9), layout="constrained")
    names = [textwrap.fill(row["label"], 53) + "\n" + row["attribute_id"] for row in top]
    ax.barh(range(len(top)), [row["literature_added_gene_count"] for row in top],
            color=[orange if row["absent_from_original_annotation_vocabulary"] else blue for row in top], height=0.7)
    ax.set_yticks(range(len(top)), names, fontsize=9)
    ax.invert_yaxis()
    maximum = max(row["literature_added_gene_count"] for row in top)
    for i, row in enumerate(top):
        ax.text(row["literature_added_gene_count"] + maximum * 0.02, i,
                str(row["literature_added_gene_count"]), va="center")
    ax.set_xlim(0, maximum * 1.13)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Unique genes newly linked by literature")
    ax.set_title("Attributes with the most literature-supported additions", loc="left", pad=15)
    ax.grid(axis="x", alpha=0.16)
    ax.set_axisbelow(True)
    save(fig, "top_literature_attributes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh analysis directory")
    rows, summary = analyze(args.workspace.resolve(), args.output.resolve())
    plot(rows, summary, args.output.resolve())
    print(json.dumps({key: summary[key] for key in ["literature_added_memberships", "genes_with_literature_additions",
          "attributes_with_literature_additions", "attribute_ids_absent_from_original_annotations", "histograms"]}, indent=2))

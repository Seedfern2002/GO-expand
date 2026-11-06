#!/usr/bin/env python3
"""Plot the exact external attributes used in the GEARS neighborhood comparison."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "outputs/.matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import pandas as pd


COLORS = {"Reactome": "#3478B8", "hu.MAP": "#189C83"}


def save_figure(figure, output, name):
    for extension in ("png", "pdf", "svg"):
        figure.savefig(output / f"{name}.{extension}", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-dir", type=Path, default=ROOT / "outputs/analysis/norman_topk_neighbors_001")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("output directory exists; choose a new figure directory")
    output.mkdir(parents=True)
    comparison = json.loads((args.comparison_dir / "summary.json").read_text())
    attributes = {}
    family_genes = defaultdict(set)
    all_records = 0
    for item in comparison["inputs"]["approved_sources"]:
        path = Path(item["path"])
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        selected = 0
        for line in raw.decode().splitlines():
            record = json.loads(line)
            if not record["projection_eligible"]:
                continue
            assert record["relation"] in ("member_of_pathway", "predicted_member_of_complex")
            family = "Reactome" if record["relation"] == "member_of_pathway" else "hu.MAP"
            key = "EXTERNAL:" + record["object_id"]
            if key not in attributes:
                attributes[key] = {"attribute_id": record["object_id"], "label": record["object_label"],
                                   "family": family, "genes": set(), "confidence_class": record["source_confidence"]["class"] if family == "hu.MAP" else None}
            attribute = attributes[key]
            assert attribute["family"] == family and attribute["label"] == record["object_label"]
            assert record["subject_label"] not in attribute["genes"], "duplicate membership"
            attribute["genes"].add(record["subject_label"])
            family_genes[family].add(record["subject_label"])
            selected += 1
        assert selected == item["projection_eligible_records"]
        all_records += selected
    rows = []
    for item in attributes.values():
        genes = sorted(item["genes"])
        rows.append({**item, "genes": ";".join(genes), "gene_count": len(genes)})
    table = pd.DataFrame(rows).sort_values(["family", "gene_count", "attribute_id"], ascending=[True, False, True])
    table.to_csv(output / "attribute_gene_counts.tsv", sep="\t", index=False)
    order = ["Reactome", "hu.MAP"]
    summary = []
    for family in order:
        subset = table[table.family == family]
        summary.append({"family": family, "distinct_attributes": len(subset), "gene_attribute_memberships": int(subset.gene_count.sum()),
                        "genes_annotated": len(family_genes[family]), "single_gene_attributes": int((subset.gene_count == 1).sum()),
                        "attributes_shared_by_multiple_genes": int((subset.gene_count >= 2).sum()),
                        "maximum_genes_per_attribute": int(subset.gene_count.max())})
    totals = {"distinct_attributes": len(table), "gene_attribute_memberships": int(table.gene_count.sum()),
              "genes_annotated": len(set().union(*family_genes.values()))}
    assert totals["gene_attribute_memberships"] == comparison["added_memberships"] == all_records
    assert totals["genes_annotated"] == comparison["genes_with_added_attributes"]
    data = {"scope": "Exact approved primary attributes used in the top-k comparison: all Reactome memberships and hu.MAP classes 1–3.",
            "definition": "One distinct namespaced pathway/complex ID is one attribute; its count is the number of graph genes carrying that attribute.",
            "families": summary, "total": totals, "source_comparison": str(args.comparison_dir / "summary.json")}
    (output / "summary.json").write_text(json.dumps(data, indent=2) + "\n")

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.titlesize": 13,
                         "axes.labelsize": 11, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42, "svg.fonttype": "none"})
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.6), layout="constrained")
    for ax, key, title, label in zip(axes, ("distinct_attributes", "gene_attribute_memberships"),
                                    ("A  Distinct added attributes", "B  Gene-attribute memberships"),
                                    ("Number of distinct pathway / complex IDs", "Number of unique gene-attribute pairs")):
        values = [item[key] for item in summary]
        bars = ax.bar(order, values, color=[COLORS[name] for name in order], width=0.56)
        ax.bar_label(bars, labels=[f"{value:,}" for value in values], padding=6, fontsize=13, fontweight="bold")
        ax.set_title(title, loc="left", pad=14)
        ax.set_ylabel(label)
        ax.set_ylim(0, max(values) * 1.21)
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        ax.grid(axis="y", alpha=0.17)
        ax.set_axisbelow(True)
    figure.suptitle("Attributes added in the GEARS top-20 comparison", fontsize=16, fontweight="bold")
    figure.supxlabel(f"{totals['distinct_attributes']:,} distinct attributes  |  {totals['gene_attribute_memberships']:,} memberships  |  {totals['genes_annotated']:,} genes\nReactome primary memberships; hu.MAP confidence classes 1–3", fontsize=10)
    save_figure(figure, output, "added_attributes_overview")

    figure, axes = plt.subplots(2, 1, figsize=(12, 11.5), layout="constrained")
    top_tables = []
    for ax, family in zip(axes, order):
        top = table[table.family == family].head(12).copy()
        top_tables.append(top)
        labels = []
        for row in top.itertuples(index=False):
            if family == "Reactome":
                label = textwrap.fill(row.label, width=49)
            else:
                members = row.genes.split(";")
                label = row.attribute_id.replace("hu.MAP3:", "") + "  [" + ", ".join(members[:4]) + (", ..." if len(members) > 4 else "") + "]"
                label = textwrap.fill(label, width=59)
            labels.append(label)
        positions = list(range(len(top)))
        ax.barh(positions, top.gene_count, color=COLORS[family], height=0.68)
        ax.set_yticks(positions, labels, fontsize=9)
        ax.invert_yaxis()
        for position, count in zip(positions, top.gene_count):
            ax.text(count + max(top.gene_count) * 0.015, position, str(count), va="center", fontsize=10)
        ax.set_xlim(0, max(top.gene_count) * 1.13)
        ax.set_xlabel("Number of graph genes carrying the attribute")
        ax.set_title(f"{family}: 12 attributes with the most gene memberships", loc="left", pad=12)
        ax.grid(axis="x", alpha=0.17)
        ax.set_axisbelow(True)
    figure.suptitle("Most frequent added pathway and complex attributes", fontsize=16, fontweight="bold")
    figure.supxlabel("Counts use the 3,127-gene GEARS universe. Complex labels show source IDs and up to four member genes.", fontsize=9)
    save_figure(figure, output, "top_added_attributes")
    pd.concat(top_tables).to_csv(output / "top_attributes.tsv", sep="\t", index=False)
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()

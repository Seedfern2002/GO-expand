"""Render the three frozen DrugCell GO stages as aligned interactive graphs.

All graph statistics come from the exact ontology files used by the experiment.
The self-contained HTML works offline. The PDF/SVG/PNG overview is suitable for
export; node and edge tables retain identifiers and relationship provenance.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path

import drugcell_ontology as ontology


COLORS = {
    "Original GO": "#5279a6",
    "Added GO": "#9270bd",
    "Reactome": "#128f83",
    "ComplexPortal": "#d69b35",
    "Literature / other": "#c45c8c",
}


def json_rows(path):
    with path.open() as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def go_names(path):
    names, term = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("["):
            term = None
        elif line.startswith("id: GO:"):
            term = line[4:]
        elif term and line.startswith("name: "):
            names[term] = line[6:]
    return names


def term_metadata(snapshot, aliases):
    """Join normalized evidence concepts to the exported model identifiers."""
    result = defaultdict(lambda: {"labels": set(), "sources": set(),
                                 "relations": set(), "evidence_classes": set(),
                                 "studies": set()})
    for row in json_rows(snapshot / "statements.jsonl"):
        obj = row["object_id"]
        attribute = obj if obj.startswith("GO:") else "EXTERNAL:" + obj
        identifier = aliases.get(attribute, attribute)
        info = result[identifier]
        info["labels"].update(row.get("object_labels", []))
        info["relations"].add(row["relation"])
        info["evidence_classes"].update(row.get("evidence_classes", []))
        info["studies"].update(s for s in row.get("study_ids", [])
                               if not s.startswith("UNRESOLVED:"))
        for evidence in row.get("evidence", []):
            if evidence.get("source_name"):
                info["sources"].add(evidence["source_name"])
    return {key: {field: sorted(values) for field, values in info.items()}
            for key, info in result.items()}


def source_group(identifier, original, baseline_terms):
    if identifier in baseline_terms:
        return "Original GO"
    if identifier.startswith("GO:"):
        return "Added GO"
    if "R-HSA-" in original:
        return "Reactome"
    if "ComplexPortal:" in original or "CPX-" in original:
        return "ComplexPortal"
    return "Literature / other"


def aligned_layout(graph, groups):
    """A common topological depth and deterministic grid within depth bands.

    Original/added GO occupies the left region. External modules occupy the
    right region. Positions are calculated once on the pre-pruning union so a
    surviving node stays in exactly the same position in all three panels.
    """
    parents = defaultdict(set)
    for parent, child in graph["edges"]:
        parents[child].add(parent)
    depths, branch = {}, {}
    for term in graph["order"]:
        depths[term] = max((depths[p] + 1 for p in parents[term]), default=0)
        branch[term] = (min((branch[p] for p in parents[term]
                            if p != graph["root"]), default=term))
    max_depth = max(depths.values())
    positions = {graph["root"]: [0.50, 0.085]}
    for depth in range(1, max_depth + 1):
        for external, (left, right, columns) in [
            (False, (0.065, 0.55, 60)), (True, (0.60, 0.965, 80))
        ]:
            terms = [term for term in graph["terms"] if depths[term] == depth
                     and (groups[term] not in {"Original GO", "Added GO"}) == external]
            terms.sort(key=lambda term: (list(COLORS).index(groups[term]), branch[term], term))
            width = min(columns, len(terms))
            rows = math.ceil(len(terms) / columns) if terms else 0
            for index, term in enumerate(terms):
                row, col = divmod(index, columns)
                x = (left + right) / 2 if width == 1 else left + (right - left) * col / (width - 1)
                band_offset = 0 if rows == 1 else (row / (rows - 1) - 0.5) * 0.48
                y = 0.085 + (depth + band_offset) * 0.80 / max_depth
                positions[term] = [round(x, 7), round(y, 7)]
    return positions, depths, max_depth


def build_data(experiment):
    snapshot = experiment / "unpruned/knowledge_snapshot"
    inputs = experiment / "unpruned/projection_inputs"
    projection = json.loads((experiment / "unpruned/augmentation/projection_manifest.json").read_text())
    obo = Path(projection["sources"]["obo"]["path"])
    paths = {
        "gene_map": experiment / "source_inputs/gene2ind.txt",
        "baseline": experiment / "baseline/drugcell_ont.txt",
        "augmented": experiment / "unpruned/augmentation/drugcell_ont.txt",
        "pruned": experiment / "augmentation/drugcell_ont.txt",
        "obo_labels": obo,
        "statements": snapshot / "statements.jsonl",
        "identifier_map": inputs / "external_identifier_map.json",
        "edge_provenance": experiment / "unpruned/augmentation/edge_provenance.jsonl",
        "removed_nodes": experiment / "augmentation/removed_nodes.jsonl",
        "pruning_manifest": experiment / "augmentation/pruning_manifest.json",
    }
    hashes = {key: ontology.sha256(path) for key, path in paths.items()}
    genes = ontology.read_gene_map(paths["gene_map"])
    gene_index = {gene: index for index, gene in enumerate(genes)}
    graphs = {key: ontology.read_ontology(paths[key], genes)
              for key in ("baseline", "augmented", "pruned")}
    baseline, augmented, pruned = (graphs[key] for key in ("baseline", "augmented", "pruned"))
    if not baseline["terms"] <= augmented["terms"] or not pruned["terms"] <= augmented["terms"]:
        raise ValueError("Expected additive augmentation followed by pruning")
    aliases = json.loads(paths["identifier_map"].read_text())
    originals = {encoded: original for original, encoded in aliases.items()}
    info = term_metadata(snapshot, aliases)
    names = go_names(obo)
    groups = {term: source_group(term, originals.get(term, term), baseline["terms"])
              for term in augmented["terms"]}
    positions, depths, max_depth = aligned_layout(augmented, groups)
    removed = {row["term"]: row["reason"] for row in json_rows(paths["removed_nodes"])}
    edge_info = {(row["parent"], row["child"]): row["semantics"]
                 for row in json_rows(paths["edge_provenance"])}
    data = {
        "experiment": experiment.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "genes": genes, "colors": COLORS, "root": baseline["root"],
        "max_depth": max_depth,
        "scope": "Exact DrugCell model hierarchy; baseline is the released pruned GO.",
        "layout": "Aligned depth bands; longest parent-to-child depth in the augmented input; GO and external modules have separate horizontal regions.",
        "edge_direction": "parent to child; external aggregation edges retain their model-aggregation semantics",
        "stages": [],
    }
    titles = {"baseline": "Released GO", "augmented": "Augmented GO", "pruned": "Augmented + pruned"}
    for key, graph in graphs.items():
        nodes = []
        for term in sorted(graph["terms"]):
            evidence = info.get(term, {})
            old_direct = baseline["direct"].get(term, set())
            old_coverage = baseline["propagated"].get(term, set())
            labels = evidence.get("labels", [])
            original = originals.get(term, term)
            nodes.append({
                "id": term, "original_id": original,
                "label": names.get(term, labels[0] if labels else original),
                "source": groups[term], "baseline": term in baseline["terms"],
                "removed": term not in pruned["terms"],
                "removal_reason": removed.get(term, ""),
                "x": positions[term][0], "y": positions[term][1], "depth": depths[term],
                "direct": sorted(gene_index[g] for g in graph["direct"][term]),
                "coverage": sorted(gene_index[g] for g in graph["propagated"][term]),
                "added_direct": len(graph["direct"][term] - old_direct),
                "removed_direct": len(old_direct - graph["direct"][term]),
                "added_coverage": len(graph["propagated"][term] - old_coverage),
                "removed_coverage": len(old_coverage - graph["propagated"][term]),
                "evidence": evidence,
            })
        indices = {node["id"]: index for index, node in enumerate(nodes)}
        edges = []
        for edge in sorted(graph["edges"]):
            semantics = ("released_hierarchy" if edge in baseline["edges"] else
                         edge_info.get(edge, "contracted_ancestry"))
            edges.append([indices[edge[0]], indices[edge[1]], semantics])
        stage = {"id": key, "title": titles[key], "stats": graph["stats"],
                 "nodes": nodes, "edges": edges,
                 "source_counts": dict(Counter(groups[t] for t in graph["terms"])),
                 "root_children": len(graph["children"][graph["root"]]),
                 "external_root_children": sum(groups[t] not in {"Original GO", "Added GO"}
                                               for t in graph["children"][graph["root"]]),
                 "edge_semantics": dict(Counter(edge[2] for edge in edges))}
        data["stages"].append(stage)
    provenance = {key: {"path": str(paths[key]), "sha256": value} for key, value in hashes.items()}
    return data, provenance


def write_tables(data, output):
    fields = ["stage", "id", "original_id", "label", "source", "baseline", "removed", "removal_reason",
              "depth", "direct_genes", "propagated_genes", "added_direct", "removed_direct",
              "added_coverage", "removed_coverage"]
    with (output / "nodes.tsv").open("w") as stream:
        writer = csv.DictWriter(stream, fields, delimiter="\t")
        writer.writeheader()
        for stage in data["stages"]:
            for node in stage["nodes"]:
                row = {key: node[key] for key in fields if key in node}
                row.update(stage=stage["id"], direct_genes=len(node["direct"]), propagated_genes=len(node["coverage"]))
                writer.writerow(row)
    with (output / "edges.tsv").open("w") as stream:
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["stage", "parent", "child", "semantics"])
        for stage in data["stages"]:
            for parent, child, semantics in stage["edges"]:
                writer.writerow([stage["id"], stage["nodes"][parent]["id"], stage["nodes"][child]["id"], semantics])


def plot_overview(data, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D
    import numpy as np

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"})
    fig = plt.figure(figsize=(18, 10), facecolor="#fbfaf7")
    grid = fig.add_gridspec(2, 3, height_ratios=[2.2, 1], hspace=0.40, wspace=0.28,
                          left=0.055, right=0.975, bottom=0.09, top=0.81)
    labels = [stage["title"] for stage in data["stages"]]
    for index, stage in enumerate(data["stages"]):
        ax = fig.add_subplot(grid[0, index])
        nodes = stage["nodes"]
        for aggregation in (False, True):
            segments = [((nodes[a]["x"], nodes[a]["y"]), (nodes[b]["x"], nodes[b]["y"]))
                        for a, b, semantics in stage["edges"]
                        if (semantics == "explicit_model_aggregation") == aggregation]
            ax.add_collection(LineCollection(segments, colors="#9babb3" if aggregation else "#7e8b9b",
                                            linewidths=0.25, alpha=0.06 if aggregation else 0.18,
                                            rasterized=False))
        for source, color in COLORS.items():
            selected = [node for node in nodes if node["source"] == source]
            if selected:
                ax.scatter([n["x"] for n in selected], [n["y"] for n in selected],
                           s=3.5, c=color, linewidths=0, zorder=3, alpha=0.80)
        root = next(n for n in nodes if n["id"] == data["root"])
        ax.scatter(root["x"], root["y"], s=45, marker="D", c="#24394b", zorder=5)
        ticks = [0.085 + depth * 0.80 / data["max_depth"] for depth in range(data["max_depth"] + 1)]
        ax.set(ylim=(0.99, 0.01), xlim=(0.01, 1), xticks=[], yticks=ticks,
               yticklabels=[str(i) for i in range(len(ticks))], ylabel="Depth in augmented hierarchy")
        ax.axvline(0.575, color="#d7dce1", lw=0.7, ls="--")
        ax.text(0.29, 0.975, "GO terms", transform=ax.transAxes, ha="center", color="#536374")
        ax.text(0.79, 0.975, "External modules", transform=ax.transAxes, ha="center", color="#536374")
        ax.set_title(f"{stage['title']}\n{len(nodes):,} terms · {len(stage['edges']):,} hierarchy edges", loc="left", pad=16)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(length=0, labelsize=8)
        ax.set_facecolor("#ffffff")
    ax = fig.add_subplot(grid[1, 0])
    bottom = np.zeros(3)
    for source, color in COLORS.items():
        values = [stage["source_counts"].get(source, 0) for stage in data["stages"]]
        ax.bar(range(3), values, bottom=bottom, color=color, width=0.58)
        bottom += values
    ax.set(xticks=range(3), xticklabels=["Released", "Augmented", "+ pruned"], ylabel="Terms")
    ax.set_title("Term composition", loc="left")
    for index, value in enumerate(bottom):
        ax.text(index, value + 100, f"{int(value):,}", ha="center", fontsize=9)
    ax.set_ylim(0, max(bottom) * 1.18)
    ax = fig.add_subplot(grid[1, 1])
    for index, field in enumerate(["direct_memberships", "propagated_memberships"]):
        values = [stage["stats"][field] / 1000 for stage in data["stages"]]
        bars = ax.bar(np.arange(3) + (index - 0.5) * 0.34, values, width=0.32,
                      color=["#5279a6", "#84b8b0"][index], label=["Direct", "After propagation"][index])
        ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8)
    ax.set(xticks=range(3), xticklabels=["Released", "Augmented", "+ pruned"], ylabel="Gene–term links (thousands)")
    ax.set_title("Gene membership", loc="left")
    ax.set_ylim(0, 240)
    ax.legend(frameon=False, fontsize=8)
    ax = fig.add_subplot(grid[1, 2])
    for index, stage in enumerate(data["stages"]):
        ax.bar(index, stage["root_children"], color="#d4dce5", width=0.58)
        ax.bar(index, stage["external_root_children"], color=COLORS["Reactome"], width=0.58)
        ax.text(index, stage["root_children"] + 60, f"{stage['root_children']:,}", ha="center", fontsize=9)
    ax.set(xticks=range(3), xticklabels=["Released", "Augmented", "+ pruned"], ylabel="Direct children of root")
    ax.set_title("Root connectivity", loc="left")
    ax.set_ylim(0, max(stage["root_children"] for stage in data["stages"]) * 1.22)
    ax.legend(handles=[Line2D([], [], color="#d4dce5", lw=7, label="GO children"),
                       Line2D([], [], color=COLORS["Reactome"], lw=7, label="External children")], frameon=False, fontsize=8)
    for ax in fig.axes[3:]:
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_facecolor("#fbfaf7")
        ax.grid(axis="y", alpha=0.13)
        ax.set_axisbelow(True)
    fig.suptitle("DrugCell · GO structure before and after augmentation", x=0.055, ha="left", y=0.985,
                 fontsize=20, weight="bold", color="#24394b")
    fig.text(0.055, 0.937, "Latest adaptive augmentation · fixed 3,008-gene input · aligned positions across stages", fontsize=11, color="#536374")
    fig.legend(handles=[Line2D([], [], marker="o", lw=0, color=color, label=source, markersize=6)
                        for source, color in COLORS.items()], loc="upper left", bbox_to_anchor=(0.05, 0.916),
               ncol=5, frameon=False)
    fig.text(0.055, 0.025, "Baseline: released, already-pruned DrugCell GO. Nodes: terms/modules; gene memberships are summarized below.\n"
             "Edges: exported model hierarchy. External-module edges describe model aggregation. Depth coordinates remain fixed after pruning.",
             fontsize=9, color="#536374")
    for extension in ("png", "svg", "pdf"):
        fig.savefig(output / f"overview.{extension}", dpi=190, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    experiment = args.experiment.resolve()
    data, provenance = build_data(experiment)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_tables(data, output)
    (output / "graph_data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    template_path = Path(__file__).with_name("drugcell_go_viewer.html")
    template = template_path.read_text()
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    (output / "index.html").write_text(template.replace("__GRAPH_DATA__", encoded))
    plot_overview(data, output)
    summary = {"experiment": data["experiment"], "genes": len(data["genes"]),
               "stages": [{key: stage[key] for key in ("id", "title", "stats", "source_counts", "root_children", "external_root_children", "edge_semantics")}
                          for stage in data["stages"]]}
    ontology.write_json(output / "summary.json", summary)
    readme = ["# DrugCell GO structure comparison", "", data["scope"], "",
              "Open `index.html` in a browser. It embeds all data and works offline.", "",
              "- Compare three aligned stages: released GO, augmented GO before pruning, and augmented GO after pruning.",
              "- Search a GO identifier, module name, original external identifier, or gene symbol.",
              "- Click a node to inspect parents, children, gene memberships, evidence classes and pruning status.",
              "- Choose a neighborhood, ancestor, descendant or gene view; pan and zoom are synchronized.",
              "- Gene views add the selected input gene and its direct membership edges.",
              "- `overview.png`, `.svg` and `.pdf` provide a static export; `nodes.tsv` and `edges.tsv` expose the plotted data.", "",
              "The original GO is the released DrugCell pruned hierarchy. Full pre-pruning GO reconstruction is a separate graph input.",
              "Node positions use the augmented graph's longest parent-to-child depth, with compact grids within each depth band. Surviving nodes retain those coordinates after pruning.",
              "External aggregation edges retain their computational relationship label. Released rows encode hierarchy edges without distinguishing is_a from part_of.",
              "Evidence metadata describes frozen knowledge records, including context retained upstream. The plotted membership graph is the structure consumed by DrugCell.", "",
              "| Stage | Terms | Hierarchy edges | Direct gene links | Propagated gene links | Root children |", "|---|---:|---:|---:|---:|---:|"]
    for stage in data["stages"]:
        stat = stage["stats"]
        readme.append(f"| {stage['title']} | {stat['terms']:,} | {stat['hierarchy_edges']:,} | {stat['direct_memberships']:,} | {stat['propagated_memberships']:,} | {stage['root_children']:,} |")
    (output / "README.md").write_text("\n".join(readme) + "\n")
    for record in provenance.values():
        if ontology.sha256(record["path"]) != record["sha256"]:
            raise RuntimeError("A source artifact changed while rendering")
    ontology.write_json(output / "manifest.json", {
        "created_at_utc": data["created_at_utc"], "experiment": str(experiment),
        "sources": provenance, "script_sha256": ontology.sha256(__file__),
        "template_sha256": ontology.sha256(template_path),
        "source_files_unchanged": True,
        "artifacts": {path.name: ontology.sha256(path) for path in sorted(output.iterdir())},
    })
    print(json.dumps({"output": str(output), **summary}, indent=2))


if __name__ == "__main__":
    main()

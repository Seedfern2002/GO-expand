"""Compare the three final DrugCell hierarchies using shared graph coordinates."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from textwrap import fill, shorten

import networkx as nx

import drugcell_ontology as ontology
from visualize_drugcell_go import go_names


COLORS = {
    "GO in both rebuilt graphs": "#4f7faa",
    "GO kept only in rebuilt control": "#cc6977",
    "GO kept only after augmentation": "#9170bb",
    "GO present only in official release": "#b1bac4",
    "Reactome module": "#15988b",
    "Complex Portal module": "#d59c39",
}
SOURCE_COLORS = {"GO": "#4f7faa", "Reactome": "#15988b", "ComplexPortal": "#d59c39"}


def depths(graph):
    result = {}
    for term in nx.lexicographical_topological_sort(graph):
        result[term] = max((result[p] + 1 for p in graph.predecessors(term)), default=0)
    return result


def shared_layout(union, groups):
    """The union DAG supplies display bands; each stage keeps its real depth."""
    bands = depths(union)
    maximum = max(bands.values())
    branches = {}
    root = "GO:0008150"
    for term in nx.lexicographical_topological_sort(union):
        branches[term] = min((branches[p] for p in union.predecessors(term) if p != root), default=term)
    positions = {root: (0.5, 0.085)}
    for depth in range(1, maximum + 1):
        for external, left, right, columns in [(False, 0.055, 0.55, 45), (True, 0.61, 0.97, 30)]:
            terms = sorted((t for t in union if bands[t] == depth and t.startswith("EXTERNAL:") == external),
                           key=lambda t: (branches[t], list(COLORS).index(groups[t]), t))
            width = min(columns, len(terms))
            rows = math.ceil(len(terms) / columns)
            for i, term in enumerate(terms):
                row, col = divmod(i, columns)
                x = (left + right) / 2 if width == 1 else left + (right - left) * col / (width - 1)
                offset = 0 if rows == 1 else (row / (rows - 1) - 0.5) * 0.53
                positions[term] = (x, 0.085 + (depth + offset) * 0.80 / maximum)
    return positions, bands, maximum


def compare_sets(a, b):
    return {"shared": len(a & b), "added": len(b - a), "removed": len(a - b),
            "jaccard": len(a & b) / len(a | b)}


def build_data(root, experiment):
    paths = {
        "released": root / "third_party/DrugCell/data/drugcell_ont.txt",
        "control": experiment / "control_pruning/drugcell_ont.txt",
        "augmented": experiment / "augmentation/drugcell_ont.txt",
        "gene_map": root / "third_party/DrugCell/data/gene2ind.txt",
        "frozen_graph": experiment / "knowledge_snapshot/provenance/knowledge_graph/graph.json",
        "identifier_map": experiment / "source_augmentation/identifier_map.json",
        "obo_labels": root / "data/raw/go/2026-07-26/go-basic.obo",
        "control_pruning": experiment / "control_pruning/pruning_manifest.json",
        "augmented_pruning": experiment / "augmentation/pruning_manifest.json",
    }
    genes = ontology.read_gene_map(paths["gene_map"])
    gene_index = {g: i for i, g in enumerate(genes)}
    graphs = {key: ontology.read_ontology(paths[key], genes) for key in ("released", "control", "augmented")}
    union = nx.DiGraph()
    for graph in graphs.values():
        union.add_edges_from(sorted(graph["edges"]))
    if not nx.is_directed_acyclic_graph(union):
        raise ValueError("A shared topological layout requires an acyclic union")
    frozen = json.loads(paths["frozen_graph"].read_text())
    aliases = json.loads(paths["identifier_map"].read_text())
    originals = {v: k for k, v in aliases.items()}
    names = go_names(paths["obo_labels"])
    groups, origins, labels = {}, {}, {}
    control, augmented = graphs["control"], graphs["augmented"]
    for term in union:
        info = frozen["nodes"].get(originals.get(term, term), {})
        origins[term] = "GO" if term.startswith("GO:") else info.get("origin", "Reactome")
        labels[term] = names.get(term, info.get("label", originals.get(term, term)))
        if term.startswith("EXTERNAL:"):
            groups[term] = "Complex Portal module" if origins[term] == "ComplexPortal" else "Reactome module"
        elif term in control["terms"] and term in augmented["terms"]:
            groups[term] = "GO in both rebuilt graphs"
        elif term in control["terms"]:
            groups[term] = "GO kept only in rebuilt control"
        elif term in augmented["terms"]:
            groups[term] = "GO kept only after augmentation"
        else:
            groups[term] = "GO present only in official release"
    positions, bands, maximum = shared_layout(union, groups)
    data = {
        "experiment": experiment.name, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "comparison_mode": "independent_final_graphs", "genes": genes,
        "root": graphs["released"]["root"], "colors": SOURCE_COLORS,
        "comparison_colors": {k: v for k, v in COLORS.items() if k in set(groups.values())},
        "max_depth": maximum,
        "scope": "Three exact, final model hierarchies: the official released DrugCell GO; complete GO-BP pruned by the project reconstruction; and complete GO-BP augmented with reviewed database modules before the same pruning.",
        "layout": "Shared coordinates use the topological depth of the union of all three graphs, with GO and external modules in separate horizontal regions. Union depth is a display coordinate; each individual graph has six hierarchy levels. Identical identifiers keep identical positions.",
        "edge_direction": "parent to child", "stages": [], "comparisons": {},
    }
    titles = {"released": ("A  Official released GO", "Official"),
              "control": ("B  Complete GO → pruned", "Rebuilt control"),
              "augmented": ("C  Augmented GO → pruned", "Augmented")}
    for key, graph in graphs.items():
        nxgraph = nx.DiGraph(sorted(graph["edges"]))
        stage_depth = depths(nxgraph)
        nodes = []
        for term in sorted(graph["terms"]):
            original = originals.get(term, term)
            direct_before = control["direct"].get(term, set())
            covered_before = control["propagated"].get(term, set())
            nodes.append({"id": term, "original_id": original, "label": labels[term],
                          "source": origins[term], "comparison_group": groups[term],
                          "baseline": term in control["terms"], "removed": term not in augmented["terms"],
                          "removal_reason": "", "x": positions[term][0], "y": positions[term][1],
                          "depth": bands[term], "stage_depth": stage_depth[term],
                          "direct": sorted(gene_index[g] for g in graph["direct"][term]),
                          "coverage": sorted(gene_index[g] for g in graph["propagated"][term]),
                          "added_direct": len(graph["direct"][term] - direct_before),
                          "removed_direct": len(direct_before - graph["direct"][term]),
                          "added_coverage": len(graph["propagated"][term] - covered_before),
                          "removed_coverage": len(covered_before - graph["propagated"][term]),
                          "evidence": {"sources": [origins[term]], "labels": [labels[term]]}})
        index = {node["id"]: i for i, node in enumerate(nodes)}
        edges = [[index[a], index[b], "exported_model_hierarchy"] for a, b in sorted(graph["edges"])]
        data["stages"].append({"id": key, "title": titles[key][0], "short_title": titles[key][1],
                               "stats": graph["stats"], "nodes": nodes, "edges": edges,
                               "source_counts": dict(Counter(origins[t] for t in graph["terms"])),
                               "comparison_counts": dict(Counter(groups[t] for t in graph["terms"])),
                               "root_children": len(graph["children"][graph["root"]]),
                               "external_root_children": sum(t.startswith("EXTERNAL:") for t in graph["children"][graph["root"]])})
    for a, b in [("released", "control"), ("control", "augmented"), ("released", "augmented")]:
        data["comparisons"][a + "_to_" + b] = {field: compare_sets(graphs[a][field], graphs[b][field])
                                                for field in ("terms", "edges", "memberships")}
    return data, {k: {"path": str(v.resolve()), "sha256": ontology.sha256(v)} for k, v in paths.items()}


def plotting():
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "drugcell-three-graphs-mpl"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.fonttype": "none"})
    return plt


def save_figure(fig, output, name):
    for extension in ("png", "svg", "pdf"):
        fig.savefig(output / f"{name}.{extension}", dpi=170, facecolor=fig.get_facecolor())


def plot_overview(data, output):
    plt = plotting()
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D
    import numpy as np
    fig = plt.figure(figsize=(18, 11.6), facecolor="#fbfaf7")
    grid = fig.add_gridspec(2, 3, height_ratios=[2.7, 1], left=.055, right=.98,
                          bottom=.11, top=.82, hspace=.38, wspace=.24)
    for i, stage in enumerate(data["stages"]):
        ax = fig.add_subplot(grid[0, i]); nodes = stage["nodes"]
        segments = [[(nodes[a]["x"], nodes[a]["y"]), (nodes[b]["x"], nodes[b]["y"])] for a, b, _ in stage["edges"]]
        ax.add_collection(LineCollection(segments, colors="#7e8b9b", linewidths=.30, alpha=.12))
        for group, color in data["comparison_colors"].items():
            selected = [n for n in nodes if n["comparison_group"] == group]
            ax.scatter([n["x"] for n in selected], [n["y"] for n in selected], s=5.5, color=color, linewidths=0, zorder=3)
        root = next(n for n in nodes if n["id"] == data["root"])
        ax.scatter(root["x"], root["y"], s=42, marker="D", color="#24394b", zorder=5)
        ticks = [.085 + d * .8 / data["max_depth"] for d in range(data["max_depth"] + 1)]
        ax.set(xlim=(.01, 1), ylim=(.97, .01), xticks=[], yticks=ticks,
               yticklabels=range(len(ticks)), ylabel="Aligned union band")
        ax.axvline(.58, color="#d7dce1", ls="--", lw=.8)
        ax.text(.29, .98, "GO terms", transform=ax.transAxes, ha="center", color="#687789", fontsize=8)
        ax.text(.79, .98, "External modules", transform=ax.transAxes, ha="center", color="#687789", fontsize=8)
        stats = stage["stats"]
        ax.set_title(stage["title"] + f"\n{stats['terms']:,} nodes · {stats['hierarchy_edges']:,} edges · {stats['annotated_genes']:,} genes",
                     loc="left", fontsize=11, pad=17)
        ax.spines[:].set_visible(False); ax.tick_params(length=0, labelsize=8)
    ax = fig.add_subplot(grid[1, 0]); bottom = np.zeros(3)
    for group, color in data["comparison_colors"].items():
        values = [s["comparison_counts"].get(group, 0) for s in data["stages"]]
        ax.bar(range(3), values, bottom=bottom, color=color, width=.60); bottom += values
    ax.set_title("Node composition", loc="left")
    ax.set(ylabel="Terms / modules", ylim=(0, max(bottom)*1.2))
    for i, n in enumerate(bottom):ax.text(i, n+40, f"{int(n):,}", ha="center")
    ax = fig.add_subplot(grid[1, 1])
    for i, field in enumerate(["direct_memberships", "propagated_memberships"]):
        bars=ax.bar(np.arange(3)+(i-.5)*.34, [s["stats"][field]/1000 for s in data["stages"]], width=.32,
                    color=["#4f7faa", "#8cbdb5"][i], label=["Direct", "After propagation"][i])
        ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=8)
    ax.set_title("Gene–module associations", loc="left"); ax.set(ylabel="Associations (thousands)", ylim=(0, 190))
    ax.legend(frameon=False, fontsize=8)
    ax = fig.add_subplot(grid[1, 2])
    bars=ax.bar(range(3), [s["root_children"] for s in data["stages"]], color="#9dabbc", width=.60)
    ax.bar(range(3), [s["external_root_children"] for s in data["stages"]], color="#15988b", width=.60)
    ax.bar_label(bars,padding=4,fontsize=9)
    ax.set_title("Direct children of root after pruning", loc="left"); ax.set(ylabel="Children", ylim=(0, 1050))
    ax.legend(handles=[Line2D([],[],lw=7,color="#9dabbc",label="GO"),Line2D([],[],lw=7,color="#15988b",label="External")],frameon=False,fontsize=8)
    for ax in fig.axes[3:]:
        ax.set(xticks=range(3),xticklabels=["A  Official", "B  Control", "C  Augmented"])
        ax.spines[["top", "right"]].set_visible(False);ax.set_facecolor("#fbfaf7")
        ax.grid(axis="y",alpha=.12);ax.set_axisbelow(True)
    fig.suptitle("DrugCell | Three final GO hierarchies", x=.055, y=.975, ha="left", fontsize=22, weight="bold", color="#24394b")
    fig.text(.055,.934,"Official release · reconstructed complete-GO control · database augmentation before pruning",fontsize=11,color="#536374")
    fig.legend(handles=[Line2D([],[],marker="o",lw=0,color=c,label=g,markersize=6) for g,c in data["comparison_colors"].items()],
               loc="upper left",bbox_to_anchor=(.05,.918),ncol=3,frameon=False,fontsize=9)
    fig.text(.055,.035,"Same identifier = same position in all panels. Colors distinguish retention in B/C and external module origins.\n"
             f"Alignment uses the union DAG ({data['max_depth']+1} display bands); each individual model has 6 hierarchy levels. Dots represent modules; gene links are summarized below.\n"
             "B/C use GO 2026-07-26. Model-connected genes: A 3,008; B 2,984; C 2,997. Root connections shown here are measured after pruning.",fontsize=9,color="#536374",linespacing=1.6)
    save_figure(fig, output, "overview");plt.close(fig)


def plot_neighborhood(data, output, identifier="GO:0006281", name="dna_repair"):
    plt = plotting()
    from matplotlib.lines import Line2D
    graphs, maps, chosen = {}, {}, {identifier}
    for stage in data["stages"]:
        maps[stage["id"]] = {n["id"]: n for n in stage["nodes"]}
        g=nx.DiGraph();g.add_nodes_from(maps[stage["id"]])
        g.add_edges_from((stage["nodes"][a]["id"],stage["nodes"][b]["id"]) for a,b,_ in stage["edges"])
        graphs[stage["id"]]=g
        if identifier in g:chosen.update(g.predecessors(identifier));chosen.update(g.successors(identifier))
    if all(identifier not in g for g in graphs.values()):raise KeyError(identifier)
    union=nx.DiGraph();union.add_nodes_from(sorted(chosen))
    for g in graphs.values():union.add_edges_from(g.subgraph(chosen).edges)
    bands=depths(union);positions={}
    for d in sorted(set(bands.values())):
        terms=sorted(t for t in chosen if bands[t]==d)
        for i,t in enumerate(terms):
            row,col=divmod(i,3);width=min(3,len(terms))
            positions[t]=((col-(width-1)/2)*1.45,-d*2.2-row*.85)
    all_nodes={n['id']:n for s in data['stages'] for n in s['nodes']}
    ymin=min(y for x,y in positions.values());ymax=max(y for x,y in positions.values())
    fig,axes=plt.subplots(1,3,figsize=(18,9),facecolor="#fbfaf7")
    for ax,stage in zip(axes,data["stages"]):
        g=graphs[stage['id']].subgraph(chosen);nodes=sorted(g.nodes)
        nx.draw_networkx_edges(g,positions,ax=ax,arrows=True,arrowsize=12,width=.85,edge_color="#a5b0ba",alpha=.8,node_size=180)
        nx.draw_networkx_nodes(g,positions,ax=ax,nodelist=nodes,node_size=[230 if t==identifier else 95 for t in nodes],
                               node_color=[data['comparison_colors'][all_nodes[t]['comparison_group']] for t in nodes],linewidths=1,edgecolors="white")
        absent=chosen-set(g)
        if absent:ax.scatter([positions[t][0] for t in absent],[positions[t][1] for t in absent],s=48,facecolors="none",edgecolors="#dce1e6",linewidths=.8)
        for t in nodes:
            label=fill(shorten(all_nodes[t]['label'],width=53,placeholder="…"),width=24)
            ax.text(positions[t][0],positions[t][1]-.19,label,ha="center",va="top",fontsize=7.5,
                    color="#24394b",weight="bold" if t==identifier else "normal",
                    bbox={"facecolor":"white","edgecolor":"none","alpha":.85,"pad":1})
        ax.set_title(stage['title'],loc="left",fontsize=12,pad=15)
        ax.set(xlim=(-2.2,2.2),ylim=(ymin-1.1,ymax+.8));ax.axis('off')
        node=maps[stage['id']].get(identifier)
        ax.text(.01,.015,(f"{len(node['coverage']):,} propagated genes · {g.in_degree(identifier)} parents · {g.out_degree(identifier)} children" if node else "Selected module absent"),transform=ax.transAxes,color="#687789",fontsize=9)
    fig.suptitle(f"{all_nodes[identifier]['label']} | {identifier}",x=.04,y=.965,ha="left",fontsize=20,weight="bold",color="#24394b")
    fig.text(.04,.915,"Exact one-hop parents and children in any of the three graphs · shared local positions",fontsize=11,color="#536374")
    fig.legend(handles=[Line2D([],[],marker='o',lw=0,color=c,label=g,markersize=6) for g,c in data['comparison_colors'].items()],
               loc='lower left',bbox_to_anchor=(.035,.015),ncol=3,frameon=False,fontsize=9)
    fig.subplots_adjust(top=.84,bottom=.15,left=.035,right=.99,wspace=.12)
    save_figure(fig,output,name);plt.close(fig)


def write_tables(data, output):
    fields=['stage','id','label','source','comparison_group','stage_depth','depth','direct_genes','propagated_genes']
    with (output/'nodes.tsv').open('w') as stream:
        writer=csv.DictWriter(stream,fields,delimiter='\t');writer.writeheader()
        for stage in data['stages']:
            for n in stage['nodes']:
                writer.writerow({**{k:n[k] for k in fields if k in n},'stage':stage['id'],'direct_genes':len(n['direct']),'propagated_genes':len(n['coverage'])})
    with (output/'edges.tsv').open('w') as stream:
        writer=csv.writer(stream,delimiter='\t');writer.writerow(['stage','parent','child'])
        for s in data['stages']:
            for a,b,_ in s['edges']:writer.writerow([s['id'],s['nodes'][a]['id'],s['nodes'][b]['id']])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    data,sources=build_data(root,args.experiment.resolve())
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'graph_data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n')
    template=Path(__file__).with_name('drugcell_go_viewer.html').read_text()
    encoded=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (output/'index.html').write_text(template.replace('__GRAPH_DATA__',encoded))
    write_tables(data,output);plot_overview(data,output);plot_neighborhood(data,output)
    summary={**{k:data[k] for k in ['experiment','scope','layout','comparisons']},
             'stages':[{k:s[k] for k in ['id','title','stats','source_counts','comparison_counts','root_children','external_root_children']} for s in data['stages']]}
    ontology.write_json(output/'summary.json',summary)
    ontology.write_json(output/'manifest.json',{'sources':sources,'created_at_utc':data['created_at_utc'],
                        'generator':{'path':str(Path(__file__).resolve()),'sha256':ontology.sha256(Path(__file__))},
                        'viewer_template_sha256':ontology.sha256(Path(__file__).with_name('drugcell_go_viewer.html')),
                        'artifacts':{p.name:ontology.sha256(p) for p in output.iterdir() if p.is_file()}})
    print(json.dumps({'output':str(output),'nodes':[s['stats']['terms'] for s in data['stages']],
                      'sources':[s['source_counts'] for s in data['stages']]},indent=2))


if __name__=='__main__':main()

"""Evidence-bound, append-only module edits on one task-wide functional graph."""

from collections import Counter, defaultdict, deque
from copy import deepcopy
import hashlib
import json
import re


RELATIONS = {"source_pathway_parent", "is_a", "part_of", "participates_in",
             "model_aggregation", "related_to", "regulates"}
HIERARCHY = {"source_pathway_parent", "is_a", "part_of"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def topology(graph):
    nodes = graph["nodes"]
    children = {n: set() for n in nodes}
    incoming = Counter({n: 0 for n in nodes})
    seen = set()
    for edge in graph["edges"]:
        a, b = edge["parent"], edge["child"]
        if a not in nodes or b not in nodes or a == b:
            raise ValueError("An edge requires two distinct declared nodes")
        if edge["model_edge"]:
            if (a, b) in seen:
                raise ValueError("Duplicate model edge")
            seen.add((a, b)); children[a].add(b); incoming[b] += 1
    queue = deque(sorted(n for n in nodes if not incoming[n])); order = []
    roots = list(queue)
    while queue:
        parent = queue.popleft(); order.append(parent)
        for child in sorted(children[parent]):
            incoming[child] -= 1
            if not incoming[child]:
                queue.append(child)
    if len(order) != len(nodes):
        raise ValueError("Model hierarchy contains a cycle")
    if roots != [graph["root"]]:
        raise ValueError("Model hierarchy must be connected under its declared root")
    return order, children


def validate_graph(graph):
    genes = graph["genes"]
    if len(genes) != len(set(genes)) or not genes:
        raise ValueError("A unique fixed gene universe is required")
    universe = set(genes)
    for key, node in graph["nodes"].items():
        if node["id"] != key or len(node["direct_genes"]) != len(set(node["direct_genes"])):
            raise ValueError("Invalid node identity or duplicate membership")
        if not set(node["direct_genes"]) <= universe:
            raise ValueError("Membership outside the fixed gene universe")
    topology(graph)
    if set().union(*(set(n["direct_genes"]) for n in graph["nodes"].values())) != universe:
        raise ValueError("The shared graph must preserve all input genes")


def coverage(graph):
    order, children = topology(graph)
    result = {key: set(node["direct_genes"]) for key, node in graph["nodes"].items()}
    for node in reversed(order):
        for child in children[node]:
            result[node].update(result[child])
    return result


def summary(graph):
    order, children = topology(graph)
    depth = {n: 0 for n in order}
    for parent in order:
        for child in children[parent]:
            depth[child] = max(depth[child], depth[parent] + 1)
    propagated = coverage(graph)
    added = [key for key, n in graph["nodes"].items() if n["origin"] != "baseline"]
    return {"revision": graph["revision"], "genes": len(graph["genes"]),
            "nodes": len(graph["nodes"]), "model_edges": sum(e["model_edge"] for e in graph["edges"]),
            "typed_edges": len(graph["edges"]), "added_nodes": len(added),
            "added_nodes_by_depth": dict(sorted(Counter(str(depth[n]) for n in added).items())),
            "added_nodes_attached_to_root": sum(n in children[graph["root"]] for n in added),
            "direct_memberships": sum(len(n["direct_genes"]) for n in graph["nodes"].values()),
            "propagated_model_memberships": sum(map(len, propagated.values())),
            "source_aliases": len(graph.get("aliases", {})), "maximum_model_depth": max(depth.values())}


class GraphContext:
    def __init__(self, graph, catalog, facts):
        validate_graph(graph)
        self.graph, self.catalog, self.facts = graph, catalog, facts
        self.members = coverage(graph)
        self.parents, self.children = defaultdict(list), defaultdict(list)
        for edge in graph["edges"]:
            self.parents[edge["child"]].append(edge)
            self.children[edge["parent"]].append(edge)

    def node(self, identifier, neighbors=8, offset=0):
        node = self.graph["nodes"].get(identifier)
        if not node:
            return None
        def adjacent(edges, field):
            return [{"id": e[field], "label": self.graph["nodes"][e[field]]["label"],
                     "relation": e["relation"], "model_edge": e["model_edge"]}
                    for e in edges[offset:offset + neighbors]]
        return {"id": identifier, "label": node["label"], "definition": node["definition"],
                "kind": node["kind"], "origin": node["origin"],
                "direct_genes": len(node["direct_genes"]), "propagated_genes": len(self.members[identifier]),
                "parents": adjacent(self.parents[identifier], "parent"),
                "children": adjacent(self.children[identifier], "child"),
                "total_parents": len(self.parents[identifier]), "total_children": len(self.children[identifier])}

    def search(self, label, limit=8, offset=0):
        matches = sorted(key for key, node in self.graph["nodes"].items()
                         if label.casefold() in node["label"].casefold())
        return {"query": label, "total_matches": len(matches), "offset": offset, "limit": limit,
                "nodes": [self.node(key, 3) for key in matches[offset:offset + limit]]}

    def module(self, identifier, limit=6):
        module = self.catalog[identifier]
        genes = set(module["genes"])
        tokens = set(re.findall(r"[a-z0-9]+", module["label"].lower())) - {"of", "the", "and", "in", "pathway", "complex"}
        annotations = set(module.get("go_annotations", []))
        ranked = []
        for term, node in self.graph["nodes"].items():
            if term == self.graph["root"]:
                continue
            overlap = len(genes & self.members[term]); union = len(genes | self.members[term])
            other = set(re.findall(r"[a-z0-9]+", node["label"].lower()))
            lexical = len(tokens & other) / max(1, len(tokens | other))
            jaccard = overlap / max(1, union)
            score = (2 if term in annotations else 0) + lexical * 1.5 + jaccard * .5
            if score:
                ranked.append((score, term, overlap, round(jaccard, 4), round(lexical, 4)))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        suggestions = [{**self.node(term), "shared_genes": overlap, "gene_jaccard": jaccard,
                        "name_similarity": lexical, "source_GO_annotation": term in annotations}
                       for _, term, overlap, jaccard, lexical in ranked[:limit]]
        evidence = []
        for key in module["evidence_ids"]:
            item = dict(self.facts[key])
            if item.get("description") == module["definition"]:
                item.pop("description")
                item["description_reference"] = "module.definition"
            evidence.append(item)
        return {key: module[key] for key in ("id", "label", "definition", "kind", "source", "go_annotations")} | {
            "member_gene_count": len(genes), "member_gene_sample": sorted(genes)[:8],
            "existing_alias": self.graph.get("aliases", {}).get(identifier),
            "candidate_locations": suggestions, "evidence": evidence,
            "source_relatives": [{"id": key, "label": self.catalog[key]["label"],
                                  "already_in_graph": key in self.graph["nodes"],
                                  "existing_alias": self.graph.get("aliases", {}).get(key)}
                                 for key in module.get("source_relatives", []) if key in self.catalog],
            "candidate_scope": "Retrieval candidates; biological identity and placement are agent-reviewed."}


def apply_patch(graph, catalog, facts, patch, allowed_modules):
    """Validate the complete transaction before returning a new graph revision."""
    if patch["graph_revision"] != graph["revision"]:
        raise ValueError("Stale graph revision")
    decisions = patch["decisions"]
    ids = [d["module_id"] for d in decisions]
    if len(ids) != len(set(ids)) or set(ids) != set(allowed_modules):
        raise ValueError("One decision is required for every module in the batch")
    result = deepcopy(graph)
    result.setdefault("aliases", {})
    planned = {d["target_id"] for d in decisions if d["action"] == "add"}
    for decision in decisions:
        module_id, target, action = decision["module_id"], decision["target_id"], decision["action"]
        if module_id not in catalog or action not in {"add", "reuse", "defer"}:
            raise ValueError("Unknown module or action")
        if len(decision["rationale"].strip()) < 25:
            raise ValueError("Supply a biological rationale")
        if not set(decision["evidence_ids"]) <= facts.keys():
            raise ValueError("Unknown decision evidence")
        if action == "defer":
            if decision["edges"] or target:
                raise ValueError("Deferred modules retain a reason and empty edits")
            continue
        if not decision["evidence_ids"] or not decision["inspected_concepts"]:
            raise ValueError("Placement requires source evidence and inspected graph concepts")
        if not set(decision["inspected_concepts"]) <= graph["nodes"].keys() | planned:
            raise ValueError("An inspected concept must be in the current graph or this batch")
        module = catalog[module_id]
        if action == "add":
            if target != module_id or target in result["nodes"]:
                raise ValueError("A new node retains its source identifier")
            result["nodes"][target] = {"id": target, "label": module["label"],
                "definition": module["definition"], "kind": module["kind"], "origin": module["source"],
                "direct_genes": list(module["genes"])}
        elif target not in graph["nodes"] or target == graph["root"]:
            raise ValueError("Reuse targets an existing non-root concept")
        else:
            node = result["nodes"][target]
            node["direct_genes"] = sorted(set(node["direct_genes"]) | set(module["genes"]))
        result["aliases"][module_id] = target
    all_targets = {**graph.get("aliases", {}), **result["aliases"]}
    def resolved(identifier):
        return all_targets.get(identifier, identifier)
    pairs = {(e["parent"], e["child"]) for e in result["edges"] if e["model_edge"]}
    typed = {(e["parent"], e["child"], e["relation"]) for e in result["edges"]}
    for decision in decisions:
        if decision["action"] == "defer":
            continue
        target = decision["target_id"]
        for supplied in decision["edges"]:
            edge = dict(supplied)
            edge["parent"], edge["child"] = resolved(edge["parent"]), resolved(edge["child"])
            parent, child, relation = edge["parent"], edge["child"], edge["relation"]
            if target not in {parent, child} or relation not in RELATIONS:
                raise ValueError("An edit must touch its module and declare its relation")
            if not edge["evidence_ids"] or not set(edge["evidence_ids"]) <= facts.keys():
                raise ValueError("Every edge needs declared evidence")
            if len(edge["rationale"].strip()) < 25:
                raise ValueError("Every edge needs a scoped biological explanation")
            if relation in {"related_to", "regulates"} and edge["model_edge"]:
                raise ValueError("Associative/regulatory links remain outside the model hierarchy")
            if relation in HIERARCHY:
                support = [facts[key] for key in edge["evidence_ids"]]
                if not any(f.get("relation") == relation and resolved(f.get("parent")) == parent
                           and resolved(f.get("child")) == child for f in support):
                    raise ValueError("Hierarchy assertion must match the pinned source relationship")
            if edge["model_edge"] and (parent, child) in pairs:
                raise ValueError("Repeated model edge would duplicate message flow")
            if (parent, child, relation) in typed:
                raise ValueError("Repeated typed edge")
            edge["placement_batch"] = patch["batch_id"]
            edge["module_id"] = decision["module_id"]
            result["edges"].append(edge)
            typed.add((parent, child, relation))
            if edge["model_edge"]:
                pairs.add((parent, child))
    result["revision"] += 1
    result["applied_batches"] = [*graph.get("applied_batches", []), patch["batch_id"]]
    validate_graph(result)
    return result


def filter_review(patch, review):
    """Retain independently accepted modules, deferring unmet dependencies."""
    result = deepcopy(patch)
    verdicts = {d["module_id"]: d for d in review["decisions"]}
    if len(verdicts) != len(review["decisions"]) or set(verdicts) != {d["module_id"] for d in patch["decisions"]}:
        raise ValueError("Review must decide every module exactly once")
    deferred = set()
    for decision in result["decisions"]:
        verdict = verdicts[decision["module_id"]]
        if verdict["verdict"] == "defer" or decision["action"] == "defer":
            deferred.add(decision["module_id"])
    changed = True
    while changed:
        changed = False
        for decision in result["decisions"]:
            if decision["module_id"] not in deferred and any(
                    {e["parent"], e["child"]} & deferred for e in decision["edges"]):
                deferred.add(decision["module_id"]); changed = True
    for decision in result["decisions"]:
        if decision["module_id"] in deferred:
            decision.update(action="defer", target_id="", edges=[],
                            rationale="Deferred after independent evidence review or an unmet module dependency: "
                                      + verdicts[decision["module_id"]]["reason"])
    return result

"""Compile agent-selected module groups into evidence-bound graph transactions."""

from copy import deepcopy

from engine.module_graph import GraphContext, RELATIONS, apply_patch


def compile_recipe(graph, catalog, facts, recipe, allowed_modules):
    """Expand explicit group scopes; preserve every source membership and decision."""
    if recipe["graph_revision"] != graph["revision"]:
        raise ValueError("Stale recipe revision")
    groups = recipe["groups"]
    group_ids = [g["group_id"] for g in groups]
    members = [m for g in groups for m in g["modules"]]
    if len(group_ids) != len(set(group_ids)) or not all(group_ids):
        raise ValueError("Recipe group identities must be unique and nonempty")
    if len(members) != len(set(members)) or set(members) != set(allowed_modules):
        raise ValueError("Groups must partition every supplied module exactly once")
    decisions, owners = {}, {}
    for group in groups:
        scope = set(group["modules"])
        if not scope or len(group["rationale"].strip()) < 25:
            raise ValueError("Each group needs a scope and biological rationale")
        reuse = {r["module_id"]: r for r in group["reuse"]}
        deferred = {d["module_id"]: d for d in group["defer"]}
        if len(reuse) != len(group["reuse"]) or len(deferred) != len(group["defer"]):
            raise ValueError("Repeated identity exception")
        if not (reuse.keys() | deferred.keys()) <= scope or reuse.keys() & deferred.keys():
            raise ValueError("Identity exceptions must be disjoint within their group")
        for module in group["modules"]:
            owners[module] = group["group_id"]
            action, target, rationale = "add", module, group["rationale"]
            if module in reuse:
                action, target, rationale = "reuse", reuse[module]["target_id"], reuse[module]["rationale"]
            elif module in deferred:
                action, target, rationale = "defer", "", deferred[module]["reason"]
            decisions[module] = {"module_id": module, "action": action, "target_id": target,
                "rationale": rationale, "inspected_concepts": list(group["inspected_concepts"]),
                "evidence_ids": list(catalog[module]["evidence_ids"]), "edges": []}
    aliases = {**graph.get("aliases", {}), **{m: d["target_id"] for m, d in decisions.items() if d["action"] != "defer"}}
    def resolved(identifier):
        return aliases.get(identifier, identifier)
    model_pairs = {(e["parent"], e["child"]) for e in graph["edges"] if e["model_edge"]}
    typed = {(e["parent"], e["child"], e["relation"]) for e in graph["edges"]}
    receipt = {"groups": [], "expanded_edges": [], "preserved_existing_edges": []}

    def attach(edge, group, native=False):
        parent, child = resolved(edge["parent"]), resolved(edge["child"])
        owner = next((m for m in (edge["child"], edge["parent"]) if m in group["modules"]
                      and decisions[m]["action"] != "defer"), None)
        if owner is None:
            # Explicit edges may use a reuse target instead of its source alias.
            owner = next((m for m in group["modules"] if decisions[m]["action"] != "defer"
                          and decisions[m]["target_id"] in {parent, child}), None)
        if owner is None:
            raise ValueError("A recipe edge must touch an active module in its own group")
        pair, triple = (parent, child), (parent, child, edge["relation"])
        if native and (parent == child or pair in model_pairs):
            receipt["preserved_existing_edges"].append({"parent": parent, "child": child,
                "evidence_ids": edge["evidence_ids"], "group_id": group["group_id"],
                "reason": "resolved_identity" if parent == child else "existing_model_connection"})
            return
        if triple in typed or (edge["model_edge"] and pair in model_pairs):
            raise ValueError("Recipe introduces a duplicate connection")
        decisions[owner]["edges"].append(edge)
        typed.add(triple)
        if edge["model_edge"]:
            model_pairs.add(pair)
        receipt["expanded_edges"].append({**deepcopy(edge), "resolved_parent": parent,
            "resolved_child": child, "group_id": group["group_id"], "module_id": owner})

    for group in groups:
        active = {m for m in group["modules"] if decisions[m]["action"] != "defer"}
        native_count = 0
        if group["native_hierarchy"]:
            available = active | graph.get("aliases", {}).keys()
            for identifier, fact in sorted(facts.items()):
                if (fact.get("relation") == "source_pathway_parent"
                        and {fact.get("parent"), fact.get("child")} <= available
                        and {fact["parent"], fact["child"]} & active):
                    native_count += 1
                    attach({"parent": fact["parent"], "child": fact["child"],
                        "relation": "source_pathway_parent", "model_edge": True,
                        "evidence_ids": [identifier],
                        "rationale": "Expand the agent-approved source hierarchy within this group: " + group["rationale"]}, group, True)
        for anchor in group["anchors"]:
            if not anchor["modules"] or len(anchor["modules"]) != len(set(anchor["modules"])) or not set(anchor["modules"]) <= active:
                raise ValueError("An anchor must select active modules within its group")
            if anchor["relation"] not in RELATIONS:
                raise ValueError("Unknown anchor relation")
            for module in anchor["modules"]:
                attach({"parent": anchor["parent"], "child": module,
                    "relation": anchor["relation"], "model_edge": anchor["model_edge"],
                    "evidence_ids": list(catalog[module]["evidence_ids"]),
                    "rationale": anchor["rationale"]}, group)
        for edge in group["extra_edges"]:
            attach(deepcopy(edge), group)
        receipt["groups"].append({"group_id": group["group_id"], "modules": group["modules"],
            "source_hierarchy_facts_expanded": native_count,
            "actions": {m: decisions[m]["action"] for m in group["modules"]},
            "member_counts": {m: len(catalog[m]["genes"]) for m in group["modules"]}})
    patch = {"batch_id": recipe["batch_id"], "graph_revision": graph["revision"],
             "decisions": [decisions[m] for m in allowed_modules]}
    apply_patch(graph, catalog, facts, patch, allowed_modules)
    return patch, receipt


def expand_group_review(recipe, review, patch):
    """Translate group verdicts and explicit module exceptions without sampling."""
    if any(review[k] != recipe[k] for k in ("batch_id", "graph_revision")):
        raise ValueError("Review refers to a different recipe revision")
    verdicts = {v["group_id"]: v for v in review["groups"]}
    if len(verdicts) != len(review["groups"]) or set(verdicts) != {g["group_id"] for g in recipe["groups"]}:
        raise ValueError("Review must cover every group exactly once")
    evidence = {d["module_id"]: d["evidence_ids"] for d in patch["decisions"]}
    decisions = []
    for group in recipe["groups"]:
        v = verdicts[group["group_id"]]
        overrides = {x["module_id"]: x for x in v["exceptions"]}
        if len(overrides) != len(v["exceptions"]) or not overrides.keys() <= set(group["modules"]):
            raise ValueError("Review exceptions must be unique modules in their group")
        for module in group["modules"]:
            item = overrides.get(module, v)
            if item["verdict"] not in {"accept", "defer"} or not item["reason"].strip():
                raise ValueError("Each review requires a verdict and evidence-specific reason")
            decisions.append({"module_id": module, "verdict": item["verdict"],
                              "reason": item["reason"], "evidence_ids": evidence[module]})
    return {"batch_id": recipe["batch_id"], "graph_revision": recipe["graph_revision"], "decisions": decisions}


def recipe_context(graph, catalog, facts, batch):
    """Deduplicate definitions and expose exact annotations, with open graph queries."""
    context = GraphContext(graph, catalog, facts)
    selected = set(batch["modules"])
    fact_ids = sorted({e for m in selected for e in catalog[m]["evidence_ids"]})
    annotations = sorted({go for m in selected for go in catalog[m]["go_annotations"]})
    nodes = {go: context.node(go, 4) for go in annotations if go in graph["nodes"]}
    compact_facts = {}
    for identifier in fact_ids:
        fact = facts[identifier]
        compact_facts[identifier] = {k: v for k, v in fact.items()
            if k in {"id", "type", "module", "path", "locator", "go_id", "go_name", "go_namespace", "relation", "parent", "child"}}
    modules = []
    for identifier in batch["modules"]:
        module = catalog[identifier]
        modules.append({k: module[k] for k in ("id", "label", "definition", "kind", "source", "go_annotations", "evidence_ids")} | {
            "member_gene_count": len(module["genes"]), "existing_alias": graph.get("aliases", {}).get(identifier),
            "source_relatives_in_batch": [m for m in module["source_relatives"] if m in selected],
            "source_relatives_outside_batch_count": sum(m not in selected for m in module["source_relatives"])})
    return {"batch_id": batch["id"], "graph_revision": graph["revision"], "modules": modules,
        "annotated_graph_concepts": nodes, "source_facts": compact_facts,
        "graph_path": "graph/current.json", "full_catalog_path": "inputs/modules.json",
        "full_evidence_path": "inputs/placement_evidence.json",
        "context_scope": "All supplied modules and their evidence identifiers; exact source-annotated concepts are shown when present. Additional graph locations are available through paginated label and multi-concept queries."}

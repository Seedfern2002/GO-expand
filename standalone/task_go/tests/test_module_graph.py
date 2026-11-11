"""Test scientific graph edits across modules and independent review boundaries."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.module_graph import GraphContext, apply_patch, coverage, filter_review, summary


def edge(parent, child, relation="model_aggregation", evidence="E1", model=True):
    return {"parent": parent, "child": child, "relation": relation, "model_edge": model,
            "evidence_ids": [evidence], "rationale": "Source definition supports this scoped biological connection."}


class ModuleGraphTests(unittest.TestCase):
    def setUp(self):
        def node(key, genes):
            return {"id": key, "label": key, "definition": "Original process", "kind": "biological_process",
                    "origin": "baseline", "direct_genes": genes}
        self.graph = {"revision": 0, "genes": ["A", "B"], "root": "GO:ROOT", "aliases": {}, "applied_batches": [],
                      "nodes": {"GO:ROOT": node("GO:ROOT", []), "GO:REPAIR": node("GO:REPAIR", ["A", "B"])},
                      "edges": [edge("GO:ROOT", "GO:REPAIR")]}
        self.catalog = {key: {"id": key, "label": "Repair submodule", "definition": "A source-defined repair submodule",
                             "kind": "pathway", "source": "Source", "genes": [gene],
                             "go_annotations": ["GO:REPAIR"], "evidence_ids": ["E1"], "source_relatives": []}
                        for key, gene in [("EXT:P", "A"), ("EXT:C", "B")]}
        self.facts = {"E1": {"id": "E1", "description": "Source passage"},
                      "E2": {"id": "E2", "relation": "source_pathway_parent", "parent": "EXT:P", "child": "EXT:C"}}

    def decision(self, key, parent="GO:REPAIR"):
        return {"module_id": key, "action": "add", "target_id": key,
                "rationale": "A distinct source-defined submodule of the existing repair process.",
                "inspected_concepts": [parent], "evidence_ids": ["E1"], "edges": [edge(parent, key)]}

    def patch(self, decisions):
        return {"batch_id": "batch_1", "graph_revision": 0, "decisions": decisions}

    def test_same_batch_native_hierarchy_and_original_graph_remain_intact(self):
        parent = self.decision("EXT:P")
        child = self.decision("EXT:C", "EXT:P")
        child["edges"] = [edge("EXT:P", "EXT:C", "source_pathway_parent", "E2")]
        original = deepcopy(self.graph)
        result = apply_patch(self.graph, self.catalog, self.facts, self.patch([parent, child]), self.catalog)
        self.assertEqual(self.graph, original)
        self.assertEqual(result["edges"][:1], original["edges"])
        self.assertEqual(coverage(result)["GO:ROOT"], {"A", "B"})
        self.assertEqual(summary(result)["added_nodes_by_depth"], {"2": 1, "3": 1})
        self.assertEqual(summary(result)["added_nodes_attached_to_root"], 0)

    def test_cycle_from_cross_module_edit_rejects_entire_transaction(self):
        d = self.decision("EXT:P")
        d["edges"].append(edge("EXT:P", "GO:REPAIR"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            apply_patch(self.graph, self.catalog, self.facts, self.patch([d]), ["EXT:P"])
        self.assertNotIn("EXT:P", self.graph["nodes"])

    def test_duplicate_message_flow_is_rejected_even_with_different_labels(self):
        d = self.decision("EXT:P")
        d["edges"].append(edge("GO:REPAIR", "EXT:P", "participates_in"))
        with self.assertRaisesRegex(ValueError, "Repeated model edge"):
            apply_patch(self.graph, self.catalog, self.facts, self.patch([d]), ["EXT:P"])

    def test_native_hierarchy_claim_needs_matching_source_endpoints(self):
        d = self.decision("EXT:P")
        d["edges"] = [edge("GO:REPAIR", "EXT:P", "source_pathway_parent", "E2")]
        with self.assertRaisesRegex(ValueError, "pinned source"):
            apply_patch(self.graph, self.catalog, self.facts, self.patch([d]), ["EXT:P"])

    def test_reuse_retains_source_identity_and_joins_membership(self):
        self.graph["nodes"]["GO:REPAIR"]["direct_genes"] = ["A"]
        self.graph["nodes"]["GO:ROOT"]["direct_genes"] = ["B"]
        d = self.decision("EXT:C")
        d.update(action="reuse", target_id="GO:REPAIR", edges=[])
        result = apply_patch(self.graph, self.catalog, self.facts, self.patch([d]), ["EXT:C"])
        self.assertEqual(result["aliases"]["EXT:C"], "GO:REPAIR")
        self.assertEqual(result["nodes"]["GO:REPAIR"]["direct_genes"], ["A", "B"])
        self.assertEqual(len(result["nodes"]), 2)

    def test_regulatory_link_keeps_semantics_without_creating_model_cycle(self):
        d = self.decision("EXT:P")
        d["edges"].append(edge("EXT:P", "GO:REPAIR", "regulates", model=False))
        result = apply_patch(self.graph, self.catalog, self.facts, self.patch([d]), ["EXT:P"])
        self.assertEqual(summary(result)["model_edges"], 2)
        self.assertEqual(summary(result)["typed_edges"], 3)

    def test_review_defers_a_module_depending_on_a_deferred_parent(self):
        patch = self.patch([self.decision("EXT:P"), self.decision("EXT:C", "EXT:P")])
        review = {"decisions": [{"module_id": "EXT:P", "verdict": "defer", "reason": "Missing source support"},
                                {"module_id": "EXT:C", "verdict": "accept", "reason": "Supported subpathway"}]}
        result = filter_review(patch, review)
        self.assertEqual([d["action"] for d in result["decisions"]], ["defer", "defer"])
        graph = apply_patch(self.graph, self.catalog, self.facts, result, self.catalog)
        self.assertEqual(len(graph["nodes"]), 2)

    def test_later_batch_queries_the_committed_graph(self):
        result = apply_patch(self.graph, self.catalog, self.facts, self.patch([self.decision("EXT:P")]), ["EXT:P"])
        result_context = GraphContext(result, self.catalog, self.facts)
        self.assertEqual(result_context.node("GO:REPAIR")["total_children"], 1)
        self.assertEqual(result_context.module("EXT:P")["existing_alias"], "EXT:P")

    def test_compact_context_retains_evidence_ids_and_one_complete_definition(self):
        self.facts["E1"]["description"] = self.catalog["EXT:P"]["definition"]
        packet = GraphContext(self.graph, self.catalog, self.facts).module("EXT:P")
        self.assertEqual(packet["definition"], self.catalog["EXT:P"]["definition"])
        self.assertEqual(packet["evidence"][0]["id"], "E1")
        self.assertEqual(packet["evidence"][0]["description_reference"], "module.definition")
        self.assertEqual(self.facts["E1"]["description"], packet["definition"])

    def test_stale_revision_and_unseen_evidence_are_rejected(self):
        patch = self.patch([self.decision("EXT:P")]);patch["graph_revision"] = 2
        with self.assertRaisesRegex(ValueError, "Stale"):
            apply_patch(self.graph, self.catalog, self.facts, patch, ["EXT:P"])
        patch["graph_revision"] = 0;patch["decisions"][0]["edges"][0]["evidence_ids"] = ["MISSING"]
        with self.assertRaisesRegex(ValueError, "declared evidence"):
            apply_patch(self.graph, self.catalog, self.facts, patch, ["EXT:P"])


if __name__ == "__main__":
    unittest.main()

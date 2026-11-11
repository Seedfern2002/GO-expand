"""Exercise whole-group expansion and scientific exception boundaries."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.module_graph import GraphContext, apply_patch, filter_review
from engine.module_recipes import compile_recipe, expand_group_review, recipe_context
import test_module_graph as fixtures


class ModuleRecipeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ModuleGraphTests(); fixture.setUp()
        self.graph, self.catalog, self.facts = fixture.graph, fixture.catalog, fixture.facts
        self.catalog["EXT:P"]["evidence_ids"].append("E2")
        self.catalog["EXT:C"]["evidence_ids"].append("E2")
        self.recipe = {"batch_id": "batch_1", "graph_revision": 0, "groups": [{
            "group_id": "repair", "modules": ["EXT:P", "EXT:C"],
            "rationale": "These repair submodules preserve a common source pathway hierarchy.",
            "inspected_concepts": ["GO:REPAIR"], "native_hierarchy": True,
            "reuse": [{"module_id": "EXT:P", "target_id": "GO:REPAIR",
                       "rationale": "The source repair parent has equivalent scope to the existing process."}],
            "defer": [], "anchors": [], "extra_edges": []}]}

    def compile(self):
        return compile_recipe(self.graph, self.catalog, self.facts, self.recipe, list(self.catalog))

    def review(self, verdict="accept", exceptions=None):
        return {"batch_id": "batch_1", "graph_revision": 0, "groups": [{"group_id": "repair", "verdict": verdict,
            "reason": "The full source scope and placement agree with the repair definition.", "exceptions": exceptions or []}]}

    def test_native_expansion_resolves_reuse_and_keeps_complete_members(self):
        original = deepcopy(self.graph)
        patch, receipt = self.compile()
        updated = apply_patch(self.graph, self.catalog, self.facts, patch, list(self.catalog))
        self.assertEqual(original, self.graph)
        self.assertEqual(updated["edges"][-1]["parent"], "GO:REPAIR")
        self.assertEqual(updated["edges"][-1]["evidence_ids"], ["E2"])
        self.assertEqual(updated["nodes"]["EXT:C"]["direct_genes"], ["B"])
        self.assertEqual(receipt["groups"][0]["source_hierarchy_facts_expanded"], 1)

    def test_existing_native_connections_are_preserved_once_with_receipt(self):
        self.recipe["groups"][0]["reuse"] = []
        self.recipe["groups"][0]["anchors"] = [{"parent": "GO:REPAIR", "modules": ["EXT:P"],
            "relation": "model_aggregation", "model_edge": True,
            "rationale": "The source-defined repair parent is a distinct functional module."}]
        patch, _ = self.compile()
        graph = apply_patch(self.graph, self.catalog, self.facts, patch, list(self.catalog))
        next_recipe = deepcopy(self.recipe); next_recipe["graph_revision"] = 1
        next_recipe["groups"][0]["reuse"] = [
            {"module_id": m, "target_id": m, "rationale": "Reuse the source-defined module already in the shared graph."} for m in self.catalog]
        next_recipe["groups"][0]["anchors"] = []
        _, receipt = compile_recipe(graph, self.catalog, self.facts, next_recipe, list(self.catalog))
        self.assertEqual(len(receipt["preserved_existing_edges"]), 1)
        self.assertEqual(receipt["expanded_edges"], [])

    def test_shared_anchor_expands_each_member_and_source_evidence(self):
        group = self.recipe["groups"][0]
        group.update(reuse=[], native_hierarchy=False, anchors=[{"parent": "GO:REPAIR", "modules": list(self.catalog),
            "relation": "participates_in", "model_edge": True,
            "rationale": "Both source assemblies participate in the existing repair process."}])
        patch, receipt = self.compile()
        self.assertEqual(len(receipt["expanded_edges"]), 2)
        self.assertEqual(patch["decisions"][1]["edges"][0]["evidence_ids"], ["E1", "E2"])

    def test_exception_review_covers_every_member_and_holds_dependencies(self):
        patch, _ = self.compile()
        review = expand_group_review(self.recipe, self.review(exceptions=[{
            "module_id": "EXT:P", "verdict": "defer", "reason": "The parent scope needs more evidence."}]), patch)
        filtered = filter_review(patch, review)
        self.assertEqual([d["action"] for d in filtered["decisions"]], ["defer", "defer"])

    def test_group_defer_can_retain_a_supported_module_exception(self):
        patch, _ = self.compile()
        review = expand_group_review(self.recipe, self.review("defer", [{
            "module_id": "EXT:P", "verdict": "accept", "reason": "The parent identity is independently supported."}]), patch)
        self.assertEqual([d["action"] for d in filter_review(patch, review)["decisions"]], ["reuse", "defer"])

    def test_missing_or_duplicate_modules_are_rejected_before_execution(self):
        self.recipe["groups"][0]["modules"].append("EXT:C")
        with self.assertRaisesRegex(ValueError, "partition"):
            self.compile()

    def test_group_anchor_cannot_select_an_outside_or_deferred_module(self):
        self.recipe["groups"][0]["anchors"] = [{"parent": "GO:REPAIR", "modules": ["OUTSIDE"],
            "relation": "model_aggregation", "model_edge": True, "rationale": "A purported module outside the approved scope."}]
        with self.assertRaisesRegex(ValueError, "active modules"):
            self.compile()

    def test_cross_source_scope_and_cycles_remain_checked_after_expansion(self):
        group = self.recipe["groups"][0]
        group["extra_edges"] = [{"parent": "EXT:C", "child": "GO:REPAIR", "relation": "model_aggregation",
            "model_edge": True, "evidence_ids": ["E1"], "rationale": "This purported extra connection creates a hierarchy cycle."}]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.compile()

    def test_review_cannot_hide_missing_groups_or_unknown_exceptions(self):
        patch, _ = self.compile()
        review = self.review(); review["groups"] = []
        with self.assertRaisesRegex(ValueError, "every group"):
            expand_group_review(self.recipe, review, patch)
        with self.assertRaisesRegex(ValueError, "unique modules"):
            expand_group_review(self.recipe, self.review(exceptions=[{
                "module_id": "OUTSIDE", "verdict": "accept", "reason": "outside"}]), patch)

    def test_context_has_complete_module_scope_and_paginated_open_queries(self):
        packet = recipe_context(self.graph, self.catalog, self.facts, {"id": "b", "modules": list(self.catalog)})
        self.assertEqual({m["id"] for m in packet["modules"]}, set(self.catalog))
        self.assertEqual(set(packet["source_facts"]), {"E1", "E2"})
        context = GraphContext(self.graph, self.catalog, self.facts)
        page = context.search("GO:", limit=1, offset=1)
        self.assertEqual(page["total_matches"], 2)
        self.assertEqual([n["id"] for n in page["nodes"]], ["GO:ROOT"])


if __name__ == "__main__":
    unittest.main()

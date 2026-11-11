"""Verify that reviewed edges survive export into the actual model hierarchy."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import drugcell_ontology as ontology
from export_drugcell_module_graph import export
import run_drugcell_comparison_optimized as comparison


class GraphExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.product = self.root / "knowledge_graph";self.product.mkdir()
        (self.root / "task.json").write_text('{"task_id":"example"}')
        self.genes = self.root / "genes.tsv";self.genes.write_text("0\tA\n1\tB\n")
        self.baseline = self.root / "baseline.txt"
        self.baseline.write_text("GO:ROOT\tGO:REPAIR\tdefault\nGO:REPAIR\tA\tgene\nGO:REPAIR\tB\tgene\n")
        self.graph = {"genes": ["A", "B"], "root": "GO:ROOT", "aliases": {}, "nodes": {
            "GO:ROOT": {"direct_genes": []}, "GO:REPAIR": {"direct_genes": ["A", "B"]},
            "EXT:P": {"direct_genes": ["A"]}, "EXT:C": {"direct_genes": ["A"]}}, "edges": [
                {"parent": "GO:ROOT", "child": "GO:REPAIR", "relation": "released_hierarchy", "model_edge": True},
                {"parent": "GO:REPAIR", "child": "EXT:P", "relation": "model_aggregation", "model_edge": True},
                {"parent": "EXT:P", "child": "EXT:C", "relation": "source_pathway_parent", "model_edge": True},
                {"parent": "EXT:C", "child": "GO:REPAIR", "relation": "regulates", "model_edge": False}]}

    def freeze(self):
        ontology.write_json(self.product / "graph.json", self.graph)
        ontology.write_json(self.product / "validation.json", {"passed": True})
        ontology.write_json(self.product / "freeze_manifest.json", {
            "files": [{"path": p.name, "sha256": ontology.sha256(p)} for p in sorted(self.product.iterdir()) if p.name != "freeze_manifest.json"],
            "inputs": {"files": [], "task_sha256": ontology.sha256(self.root / "task.json")}, "batch_receipts": []})

    def test_native_and_specific_GO_edges_reach_model_without_root_fallback(self):
        self.freeze();out = self.root / "export"
        report = export(self.product, self.baseline, self.genes, out)
        result = ontology.read_ontology(out / "drugcell_ont.txt", ["A", "B"])
        self.assertIn(("GO:REPAIR", "EXT:P"), result["edges"])
        self.assertIn(("EXT:P", "EXT:C"), result["edges"])
        self.assertNotIn(("GO:ROOT", "EXT:P"), result["edges"])
        self.assertNotIn(("EXT:C", "GO:REPAIR"), result["edges"])
        self.assertTrue(report["baseline_bytes_preserved"])
        self.assertNotIn(("EXT:P", "A"), result["memberships"])
        self.assertEqual(result["propagated"]["EXT:P"], {"A"})
        provenance = [json.loads(line) for line in (out / "edge_provenance.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["relation"] == "regulates" and not e["model_edge"] for e in provenance))

    def test_changed_graph_and_task_are_rejected(self):
        self.freeze();(self.product / "graph.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            export(self.product, self.baseline, self.genes, self.root / "out1")
        self.freeze();(self.root / "task.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "task changed"):
            export(self.product, self.baseline, self.genes, self.root / "out2")

    def test_changed_recipe_expansion_is_rejected_by_consumer(self):
        self.freeze()
        batch = self.root / "batches/b1"; (batch / "reviewer").mkdir(parents=True)
        for filename in ("accepted_patch.json", "reviewer/result.json", "recipe.json", "expansion_receipt.json"):
            (batch / filename).write_text('{}\n')
        path = self.product / "freeze_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["batch_receipts"] = [{"batch_id": "b1", **{key: ontology.sha256(batch / filename)
            for key, filename in [("patch_sha256", "accepted_patch.json"), ("review_sha256", "reviewer/result.json"),
                                  ("recipe_sha256", "recipe.json"), ("expansion_sha256", "expansion_receipt.json")]}}]
        ontology.write_json(path, manifest)
        (batch / "expansion_receipt.json").write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, "recipe expansion receipt changed"):
            export(self.product, self.baseline, self.genes, self.root / "out")

    def test_duplicate_graph_edges_and_changed_gene_order_are_rejected(self):
        self.graph["edges"].append(self.graph["edges"][1]);self.freeze()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            export(self.product, self.baseline, self.genes, self.root / "out1")
        self.graph["edges"].pop();self.graph["genes"].reverse();self.freeze()
        with self.assertRaisesRegex(ValueError, "gene order"):
            export(self.product, self.baseline, self.genes, self.root / "out2")

    def test_training_preparation_selects_reviewed_graph_and_pins_its_freeze(self):
        self.freeze()
        experiment = self.root / "experiment"
        (experiment / "source_inputs").mkdir(parents=True)
        (experiment / "source_inputs/gene2ind.txt").write_bytes(self.genes.read_bytes())
        def snapshot(workspace, destination):
            destination.mkdir()
            (destination / "task.json").write_bytes((self.root / "task.json").read_bytes())
        config = {"knowledge": {"augmentation_workspace": str(self.root), "baseline_ontology": str(self.baseline),
                  "module_graph_product": str(self.product), "module_graph_freeze_sha256": ontology.sha256(self.product / "freeze_manifest.json")}}
        with patch.object(comparison, "snapshot_knowledge", side_effect=snapshot):
            report = comparison.prepare_augmentation(experiment, config)
        graph = ontology.read_ontology(experiment / "augmentation/drugcell_ont.txt", ["A", "B"])
        self.assertIn(("GO:REPAIR", "EXT:P"), graph["edges"])
        self.assertNotIn(("GO:ROOT", "EXT:P"), graph["edges"])
        self.assertIn("agent-reviewed", report["hierarchy_policy"])
        (self.product / "freeze_manifest.json").write_text('{}')
        other = self.root / "other"
        with patch.object(comparison, "snapshot_knowledge", side_effect=snapshot):
            with self.assertRaisesRegex(ValueError, "freeze changed"):
                other.mkdir()
                comparison.prepare_augmentation(other, config)


if __name__ == "__main__":
    unittest.main()

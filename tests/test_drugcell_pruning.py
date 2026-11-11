"""Exercise pruning thresholds, DAG contraction and frozen-derivation checks."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import drugcell_ontology as ontology
import prune_drugcell_ontology as pruning
import run_drugcell_optimized as training
import run_drugcell_comparison_optimized as comparison
import prepare_drugcell_pruned_experiment as preparation


class PruningTests(unittest.TestCase):
    def test_small_leaf_contraction_recovers_its_genes_and_keeps_existing_inputs(self):
        genes = [f"G{i}" for i in range(1, 8)]
        graph = ontology.analyze({("GO:R", "GO:A"), ("GO:A", "GO:T"), ("GO:R", "GO:B")},
            {("GO:T", "G1"), ("GO:A", "G2"), ("GO:A", "G3"), ("GO:A", "G4"),
             ("GO:B", "G5"), ("GO:B", "G6"), ("GO:B", "G7"), ("GO:R", "G1")}, genes)
        final, audit = pruning.prune_graph(graph, genes, 3, 2, 5)
        self.assertEqual(final["terms"], {"GO:R", "GO:A", "GO:B"})
        self.assertEqual(final["direct"]["GO:A"], {"G1", "G2", "G3", "G4"})
        self.assertIn(("GO:R", "G1"), final["memberships"])
        self.assertIn(("GO:A", "G1"), audit["recovered_direct_memberships"])

    def test_parent_child_difference_uses_thirty_inclusive_boundary(self):
        for size, retained in [(40, True), (39, False)]:
            genes = [f"G{i}" for i in range(size)]
            memberships = {("GO:B", g) for g in genes[:10]} | {("GO:A", g) for g in genes[10:]}
            graph = ontology.analyze({("GO:R", "GO:A"), ("GO:A", "GO:B")}, memberships, genes)
            final, _ = pruning.prune_graph(graph, genes)
            self.assertEqual("GO:A" in final["terms"], retained)
            self.assertEqual(final["propagated"]["GO:R"], set(genes))
            self.assertEqual(final["propagated"]["GO:B"], set(genes[:10]))

    def test_multi_parent_contraction_preserves_each_retained_parent_coverage(self):
        genes = ["G1", "G2", "G3"]
        graph = ontology.analyze({("GO:R", "GO:A"), ("GO:R", "GO:B"),
                                  ("GO:A", "GO:T"), ("GO:B", "GO:T")},
                                 {("GO:T", "G1"), ("GO:A", "G2"), ("GO:B", "G3")}, genes)
        final, _ = pruning.prune_graph(graph, genes, 2, 0, 5)
        self.assertEqual(final["direct"]["GO:A"], {"G1", "G2"})
        self.assertEqual(final["direct"]["GO:B"], {"G1", "G3"})

    def test_depth_cap_contracts_upper_nodes_and_preserves_root_gene_coverage(self):
        genes = ["G1", "G2", "G3", "G4", "G5"]
        names = ["GO:R", "GO:A", "GO:B", "GO:C", "GO:D"]
        graph = ontology.analyze(set(zip(names, names[1:])), set(zip(names, genes)), genes)
        final, audit = pruning.prune_graph(graph, genes, 1, 0, 2)
        self.assertEqual(final["terms"], {"GO:R", "GO:C", "GO:D"})
        self.assertEqual(final["stats"]["hierarchy_levels"], 3)
        self.assertEqual(final["propagated"]["GO:R"], set(genes))
        self.assertEqual(audit["removed_by_reason"]["exceeds_depth_cap_below_common_root"], 2)

    def test_export_is_deterministic_and_preserves_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, genes = root / "source.txt", root / "gene2ind.txt"
            source.write_text("GO:R\tGO:A\tdefault\nGO:A\tG1\tgene\nGO:A\tG2\tgene\n")
            genes.write_text("0\tG1\n1\tG2\n")
            original = source.read_bytes()
            first = pruning.prune(source, genes, root / "one", 2, 0)
            pruning.prune(source, genes, root / "two", 2, 0)
            self.assertEqual((root / "one/drugcell_ont.txt").read_bytes(), (root / "two/drugcell_ont.txt").read_bytes())
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(first["retained_gene_coverage_exact"])


class FrozenPruningContractTests(unittest.TestCase):
    def test_new_knowledge_requires_the_same_gene_universe_and_baseline_annotations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "knowledge").mkdir()
            (root / "inputs").mkdir()
            gene_map, baseline = root / "gene2ind.txt", root / "baseline.txt"
            gene_map.write_text("0\tG1\n1\tG2\n")
            baseline.write_text("GO:R\tGO:A\tdefault\nGO:A\tG1\tgene\nGO:R\tG2\tgene\n")
            (root / "knowledge/task.json").write_text(json.dumps({
                "scope": {"gene_universe_path": "inputs/genes.json", "gene_field": "genes"},
                "compilation": {"baseline_annotations_path": "inputs/annotations.json"}}))
            genes, annotations = root / "inputs/genes.json", root / "inputs/annotations.json"
            genes.write_text('{"genes":["G1","G2"]}')
            annotations.write_text('{"G1":["GO:R","GO:A"],"G2":["GO:R"]}')
            preparation.validate_knowledge_inputs(root, gene_map, baseline)
            genes.write_text('{"genes":["G2","G1"]}')
            with self.assertRaisesRegex(ValueError, "gene universe"):
                preparation.validate_knowledge_inputs(root, gene_map, baseline)
            genes.write_text('{"genes":["G1","G2"]}')
            annotations.write_text('{"G1":["GO:R"],"G2":["GO:R"]}')
            with self.assertRaisesRegex(ValueError, "baseline functional annotations"):
                preparation.validate_knowledge_inputs(root, gene_map, baseline)

    def test_training_rejects_undeclared_or_changed_pruned_ontology(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, parent, pruned, manifest = [root / n for n in ("baseline", "parent", "pruned", "manifest")]
            baseline.write_text("original\n"); parent.write_text("original\naugmented\n"); pruned.write_text("contracted\n")
            manifest.write_text(json.dumps({"status": "pruned", "artifacts": {"drugcell_ont.txt": training.sha256(pruned)},
                                            "sources": {"ontology": {"sha256": training.sha256(parent)}}}))
            config = {"knowledge": {}}
            def record(name, path, expected):
                if training.sha256(path) != expected:
                    raise ValueError("checksum mismatch")
                return Path(path)
            with self.assertRaisesRegex(ValueError, "declare"):
                training.verify_ontology_origin(pruned, baseline, config, root, record)
            config["knowledge"]["ontology_derivation"] = {
                "operation": "drugcell_prune", "manifest": str(manifest), "manifest_sha256": training.sha256(manifest),
                "parent_ontology": str(parent), "parent_ontology_sha256": training.sha256(parent)}
            training.verify_ontology_origin(pruned, baseline, config, root, record)
            pruned.write_text("changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                training.verify_ontology_origin(pruned, baseline, config, root, record)

    def test_completed_baseline_reference_is_read_only_and_checksum_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics.json"
            metrics.write_text('{"status":"complete"}')
            original = metrics.read_bytes()
            config = {"completed_run_references": {"baseline_0": {
                "path": str(root), "files": {"metrics.json": ontology.sha256(metrics)}}}}
            jobs = {"baseline_0": {"arm": "baseline", "output": "new"}}
            comparison.apply_completed_references(jobs, config)
            self.assertTrue(jobs["baseline_0"]["reused_completed_run"])
            self.assertEqual(metrics.read_bytes(), original)
            metrics.write_text('{"status":"running"}')
            with self.assertRaisesRegex(ValueError, "changed"):
                comparison.apply_completed_references(jobs, config)


if __name__ == "__main__":
    unittest.main()

"""Validate additive DrugCell exports against hierarchy and membership semantics."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/drugcell_ontology.py"
spec = importlib.util.spec_from_file_location("drugcell_ontology", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DrugCellOntologyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mapping = self.root / "gene2ind.txt"
        self.mapping.write_text("0\tG1\n1\tG2\n2\tG3\n")
        self.ontology = self.root / "ontology.txt"
        self.ontology.write_text(
            "GO:0008150\tGO:0000001\tdefault\n"
            "GO:0008150\tGO:0000002\tdefault\n"
            "GO:0000001\tG1\tgene\n"
            "GO:0000002\tG2\tgene\n"
        )
        self.obo = self.root / "go.obo"
        self.obo.write_text(
            "format-version: 1.2\n"
            "\n[Term]\nid: GO:0008150\nnamespace: biological_process\n"
            "\n[Term]\nid: GO:0000001\nnamespace: biological_process\nis_a: GO:0008150\n"
            "\n[Term]\nid: GO:0000002\nnamespace: biological_process\nis_a: GO:0008150\n"
            "\n[Term]\nid: GO:0000003\nnamespace: biological_process\nis_a: GO:0000001\n"
            "\n[Term]\nid: GO:0000004\nnamespace: biological_process\nis_a: GO:0000003\n"
            "\n[Term]\nid: GO:0000005\nnamespace: molecular_function\n"
            "\n[Term]\nid: GO:0000006\nnamespace: biological_process\nis_obsolete: true\n"
        )
        self.attributes = self.root / "gene_attributes.jsonl"

    def write_attributes(self, rows):
        self.attributes.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def export(self, parents=None):
        return module.augment(self.ontology, self.mapping, self.attributes,
                              self.root / "augmented", self.obo, parents)

    def test_preparation_keeps_direct_and_inherited_annotations_separate(self):
        output = self.root / "prepared"
        report = module.prepare(self.ontology, self.mapping, output)
        direct = json.loads((output / "annotations.json").read_text())
        propagated = json.loads((output / "propagated_annotations.json").read_text())
        self.assertEqual(direct["G1"], ["GO:0000001"])
        self.assertEqual(propagated["G1"], ["GO:0000001", "GO:0008150"])
        self.assertEqual(direct["G3"], [])
        self.assertEqual(report["statistics"]["direct_memberships"], 2)
        self.assertEqual(report["statistics"]["propagated_memberships"], 4)
        self.assertEqual((output / "drugcell_ont.txt").read_bytes(), self.ontology.read_bytes())
        with self.assertRaises(FileExistsError):
            module.prepare(self.ontology, self.mapping, output)

    def test_selected_GO_hierarchy_and_closure_reduction_preserve_original_rows(self):
        self.write_attributes([
            {"gene": "G1", "attributes": ["GO:0008150", "GO:0000001", "GO:0000002", "GO:0000003", "GO:0000004"]},
            {"gene": "G3", "attributes": ["GO:0000001", "GO:0000003", "GO:0000004", "GO:0000004"]},
        ])
        report = self.export()
        result = self.root / "augmented/drugcell_ont.txt"
        final = module.read_ontology(result, module.read_gene_map(self.mapping))
        self.assertTrue(result.read_bytes().startswith(self.ontology.read_bytes()))
        self.assertIn(("GO:0000001", "GO:0000003"), final["edges"])
        self.assertIn(("GO:0000003", "GO:0000004"), final["edges"])
        self.assertIn(("GO:0000001", "G1"), final["memberships"])
        self.assertIn(("GO:0000004", "G3"), final["memberships"])
        self.assertNotIn(("GO:0000003", "G3"), final["memberships"])
        self.assertNotIn(("GO:0000001", "G3"), final["memberships"])
        self.assertIn(("GO:0000002", "G1"), final["memberships"])
        self.assertEqual(report["projection_counts"]["added_terms"], 2)
        self.assertEqual(report["projection_counts"]["added_direct_memberships"], 3)
        self.assertEqual(report["projection_counts"]["implied_by_child_memberships"], 3)
        self.assertEqual(report["projection_counts"]["duplicate_input_memberships"], 1)

    def test_inherited_only_input_is_a_byte_identical_noop(self):
        self.ontology.write_bytes(self.ontology.read_bytes().rstrip(b"\n"))
        self.write_attributes([{"gene": "G1", "attributes": ["GO:0008150", "GO:0000001"]}])
        report = self.export()
        self.assertEqual((self.root / "augmented/drugcell_ont.txt").read_bytes(), self.ontology.read_bytes())
        self.assertEqual(report["projection_counts"]["added_direct_memberships"], 0)
        self.assertEqual(report["projection_counts"]["already_implied_by_baseline"], 2)

    def test_external_modules_need_explicit_placement_and_semantic_lineage(self):
        self.write_attributes([
            {"gene": "G1", "attributes": ["COMPLEX:1", "PATHWAY:unplaced", "GO:0000005", "GO:0000006", "LOCAL:has_underscore"]},
            {"gene": "OUTSIDE", "attributes": ["GO:0000001"]},
        ])
        parents = self.root / "parents.json"
        parents.write_text(json.dumps({"COMPLEX:1": ["GO:0008150"]}))
        report = self.export(parents)
        reasons = report["exclusion_reasons"]
        self.assertEqual(reasons["outside_gene_universe"], 1)
        self.assertEqual(reasons["unsupported_model_identifier"], 1)
        self.assertEqual(reasons["external_term_requires_explicit_parent_mapping"], 1)
        self.assertEqual(reasons["new_term_requires_active_canonical_GO_BP"], 2)
        edges = [json.loads(line) for line in (self.root / "augmented/edge_provenance.jsonl").read_text().splitlines()]
        self.assertEqual(edges[0]["semantics"], "explicit_model_aggregation")
        self.assertEqual(edges[0]["mapping_file_sha256"], module.sha256(parents))

    def test_cyclic_placement_is_rejected_before_writing_product(self):
        self.write_attributes([{"gene": "G1", "attributes": ["MODULE:1", "MODULE:2"]}])
        parents = self.root / "parents.json"
        parents.write_text(json.dumps({"MODULE:1": ["MODULE:2"], "MODULE:2": ["MODULE:1"]}))
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.export(parents)
        self.assertFalse((self.root / "augmented").exists())

    def test_baseline_duplicates_unknown_genes_and_index_errors_are_rejected(self):
        self.ontology.write_text(self.ontology.read_text() + "GO:0000001\tG1\tgene\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            module.read_ontology(self.ontology, ["G1", "G2", "G3"])
        with self.assertRaisesRegex(ValueError, "fixed-universe"):
            module.analyze({("GO:1", "GO:2")}, {("GO:2", "OTHER")}, ["G1"])
        self.mapping.write_text("1\tG1\n2\tG2\n")
        with self.assertRaisesRegex(ValueError, "contiguous"):
            module.read_gene_map(self.mapping)


if __name__ == "__main__":
    unittest.main()

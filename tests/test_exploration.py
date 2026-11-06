import gzip
import tempfile
import unittest
from pathlib import Path

from go_enrichment.annotations import read_gaf
from go_enrichment.ontology import Ontology, jaccard

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "toy.obo"


class OntologySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.ontology = Ontology.read(FIXTURE)

    def test_regulation_is_preserved_but_not_positive_membership(self):
        term = self.ontology.resolve("DEMO:0002")
        self.assertIn(("regulates", "DEMO:0001"), term.edges)
        self.assertEqual(self.ontology.ancestors(term.id), {"DEMO:0000"})

    def test_multiple_relation_paths_and_self_exclusion(self):
        self.assertEqual(
            self.ontology.ancestors("DEMO:0003"),
            {"DEMO:0000", "DEMO:0001", "DEMO:0004"},
        )

    def test_alt_id_resolves_before_closure(self):
        self.assertEqual(
            self.ontology.closure({"DEMO:0009"}),
            {"DEMO:0000", "DEMO:0001", "DEMO:0003", "DEMO:0004"},
        )

    def test_obsolete_requires_review_instead_of_auto_replacement(self):
        self.assertEqual(self.ontology.resolve("DEMO:0005").replaced_by, ["DEMO:0001"])
        with self.assertRaisesRegex(ValueError, "Obsolete"):
            self.ontology.closure({"DEMO:0005"})

    def test_missing_term_does_not_silently_disappear(self):
        with self.assertRaises(KeyError):
            self.ontology.closure({"DEMO:unknown"})

    def test_two_empty_annotations_are_undefined_similarity(self):
        self.assertIsNone(jaccard(set(), set()))
        self.assertEqual(jaccard(set(), {"DEMO:0001"}), 0.0)

    def test_shared_annotation_overlay_changes_projection(self):
        a = self.ontology.closure({"DEMO:0001"}, exclude={"DEMO:0000"})
        b = self.ontology.closure({"DEMO:0002"}, exclude={"DEMO:0000"})
        augmented = self.ontology.closure({"DEMO:0001", "DEMO:0002"}, exclude={"DEMO:0000"})
        self.assertEqual(jaccard(a, b), 0.0)
        self.assertEqual(jaccard(a, augmented), 0.5)

    def test_compressed_obo_retains_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "toy.obo.gz"
            with gzip.open(path, "wt") as handle:
                handle.write(FIXTURE.read_text())
            loaded = Ontology.read(path)
        self.assertEqual(loaded.metadata["data-version"], self.ontology.metadata["data-version"])


class GAFSemanticsTests(unittest.TestCase):
    @staticmethod
    def row(relation="involved_in", database="TEST", extension="", form=""):
        return "\t".join([
            database, "item1", "SAME_SYMBOL", relation, "DEMO:0001", "LOCAL:source1",
            "IDA", "", "P", "", "", "protein", "taxon:9606", "20261105", "TEST",
            extension, form,
        ]) + "\n"

    def read(self, contents, compressed=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ("input.gaf.gz" if compressed else "input.gaf")
            if compressed:
                with gzip.open(path, "wt") as handle:
                    handle.write(contents)
            else:
                path.write_text(contents)
            return list(read_gaf(path))

    def test_negation_context_and_form_are_not_lost(self):
        record, = self.read(
            "!gaf-version: 2.2\n" + self.row("NOT|involved_in", extension="part_of(CL:example)", form="TEST:form1"),
            compressed=True,
        )
        self.assertTrue(record.negated)
        self.assertEqual(record.relation, "involved_in")
        self.assertEqual(record.extension, "part_of(CL:example)")
        self.assertEqual(record.product_form_id, "TEST:form1")
        self.assertEqual(record.reference, "LOCAL:source1")

    def test_same_symbol_from_different_databases_keeps_distinct_ids(self):
        first, second = self.read("!gaf-version: 2.2\n" + self.row() + self.row(database="OTHER"))
        self.assertEqual(first.symbol, second.symbol)
        self.assertNotEqual(first.object_id, second.object_id)

    def test_old_version_and_missing_header_are_explicit(self):
        for contents in ["!gaf-version: 2.1\n" + self.row(), self.row(), ""]:
            with self.subTest(contents=contents):
                with self.assertRaises(ValueError):
                    self.read(contents)

    def test_invalid_column_count_and_relation_are_rejected(self):
        for row in ["too\tfew\tcolumns\n", self.row("NOT"), self.row("enables|involved_in")]:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    self.read("!gaf-version: 2.2\n" + row)


if __name__ == "__main__":
    unittest.main()

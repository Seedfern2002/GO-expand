"""Check grouped DrugCell response splitting and input validation."""

from collections import Counter
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_drugcell_data.py"
spec = importlib.util.spec_from_file_location("prepare_drugcell_data", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DrugCellDataTests(unittest.TestCase):
    def make_inputs(self, root):
        source = root / "source"
        data = source / "data"
        data.mkdir(parents=True)
        (data / "gene2ind.txt").write_text("0\tG1\n1\tG2\n")
        (data / "cell2ind.txt").write_text("0\tC1\n1\tC2\n2\tC3\n")
        (data / "drug2ind.txt").write_text("0\tD1\n1\tD2\n2\tD3\n")
        (data / "cell2mutation.txt").write_text("0,1\n1,0\n1,1\n")
        (data / "drug2fingerprint.txt").write_text((",".join(["0"] * 2048) + "\n") * 3)
        (data / "drugcell_ont.txt").write_text(
            "GO:ROOT\tGO:CHILD\tdefault\nGO:ROOT\tG1\tgene\nGO:CHILD\tG2\tgene\n"
        )
        rows = [f"C{cell}\tD{drug}\t0.{cell}{drug}\n"
                for cell in range(1, 4) for drug in range(1, 4)]
        rows.append("C1\tD1\t0.99\n")
        responses = root / "responses.tsv"
        responses.write_text("".join(rows))
        return source, responses

    def test_grouped_folds_retain_measurements_and_have_disjoint_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, responses = self.make_inputs(root)
            output = root / "output"
            manifest = module.prepare(source, responses, output, folds=3, validation_pairs=1, seed=0)
            self.assertEqual(manifest["responses"]["rows"], 10)
            self.assertEqual(manifest["responses"]["unique_cell_drug_pairs"], 9)
            self.assertEqual(manifest["responses"]["additional_measurements_of_existing_pairs"], 1)
            original = Counter(responses.read_text().splitlines())
            tested = Counter()
            for fold in range(3):
                all_rows = Counter()
                pairs = {}
                for part in module.PARTITIONS:
                    rows = (output / "splits" / f"fold_{fold}" / f"{part}.tsv").read_text().splitlines()
                    all_rows.update(rows)
                    pairs[part] = {tuple(row.split("\t")[:2]) for row in rows}
                    self.assertIn(sum(row.startswith("C1\tD1\t") for row in rows), (0, 2))
                    if part == "test":
                        tested.update(rows)
                self.assertEqual(all_rows, original)
                self.assertEqual(len(pairs["validation"]), 1)
                self.assertFalse(pairs["train"] & pairs["test"])
                self.assertFalse(pairs["train"] & pairs["validation"])
                self.assertFalse(pairs["validation"] & pairs["test"])
            self.assertEqual(tested, original)
            split = json.loads((output / "split_manifest.json").read_text())
            self.assertEqual(split["protocol"]["seed_provenance"], "project replication seed")
            with self.assertRaises(FileExistsError):
                module.prepare(source, responses, output, folds=3, validation_pairs=1)

    def test_seed_reproduces_and_changes_assignment(self):
        first = module.assign_groups(100, folds=5, validation_pairs=5, seed=0)
        self.assertEqual(first, module.assign_groups(100, folds=5, validation_pairs=5, seed=0))
        self.assertNotEqual(first, module.assign_groups(100, folds=5, validation_pairs=5, seed=1))
        self.assertEqual(Counter(first[0]), {0: 20, 1: 20, 2: 20, 3: 20, 4: 20})

    def test_unknown_identifiers_and_nonfinite_labels_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, responses = self.make_inputs(root)
            cells = module.load_mapping(source / "data/cell2ind.txt")
            drugs = module.load_mapping(source / "data/drug2ind.txt")
            for text in ("UNKNOWN\tD1\t0.5\n", "C1\tUNKNOWN\t0.5\n", "C1\tD1\tnan\n", "C1\tD1\tinf\n"):
                with self.subTest(text=text):
                    responses.write_text(text)
                    with self.assertRaises(ValueError):
                        module.scan_responses(responses, cells, drugs)

    def test_nonbinary_features_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "features.csv"
            path.write_text("0,2\n")
            with self.assertRaises(ValueError):
                module.validate_binary_matrix(path, 1, 2)


if __name__ == "__main__":
    unittest.main()

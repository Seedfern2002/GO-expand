import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.knowledge import sha256, write_json
from engine.knowledge_context import KnowledgeContext


class KnowledgeContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "inputs").mkdir()
        write_json(self.root / "inputs/genes.json", {"genes": ["G1", "G2"]})
        write_json(self.root / "inputs/annotations.json", {"G1": ["GO:0000001"], "G2": []})
        (self.root / "inputs/go.obo").write_text('''format-version: 1.2

[Term]
id: GO:0000001
name: alpha process
namespace: biological_process
def: "A defined process." []
synonym: "process alpha" EXACT []
is_a: GO:0000002

[Term]
id: GO:0000002
name: C complex
namespace: cellular_component

[Term]
id: GO:0000003
name: C* complex
namespace: cellular_component
''')
        self.task = {"task_id": "context", "scope": {"gene_universe_path": "inputs/genes.json", "gene_field": "genes"},
                     "compilation": {"baseline_annotations_path": "inputs/annotations.json", "ontology_path": "inputs/go.obo",
                                     "allowed_relations": ["annotated_to", "binds", "negatively_regulates"],
                                     "allowed_evidence_classes": ["literature_extracted"]}}
        write_json(self.root / "task.json", self.task)
        self.text = "A primary experimental passage reports a functional effect in human cells."
        (self.root / "inputs/paper.txt").write_text(self.text)
        self.index = self.root / "context.sqlite"
        self.ctx = KnowledgeContext.build(self.root, self.index)
        self.addCleanup(self.ctx.close)

    def record(self, **updates):
        r = {"id": "LIT:1", "subject_id": "HGNC:1", "subject_label": "G1", "object_id": "GO:0000001",
             "object_label": "alpha process", "relation": "annotated_to", "polarity": "positive", "context": {},
             "evidence_class": "literature_extracted", "projection_eligible": True,
             "evidence": [{"source_name": "Primary study", "source_version": "test", "source_uri": "https://example.org/paper",
                           "study_id": "PMID:1", "locator": "Results paragraph1", "snapshot_path": "inputs/paper.txt",
                           "snapshot_sha256": sha256(self.root / "inputs/paper.txt"), "quote": self.text,
                           "assertion_type": "experimental_result"}]}
        return {**r, **updates}

    def propose(self, records, name, **kwargs):
        file = self.root / (name + ".jsonl")
        file.write_text("".join(json.dumps(r) + "\n" for r in records))
        return self.ctx.propose(self.root, file, self.root / name, **kwargs)

    def test_baseline_definitions_synonyms_edges_and_review_states(self):
        q = self.ctx.query(["G1"], label="process alpha")
        self.assertEqual(q["genes"]["G1"]["assertions"][0]["status"], "baseline")
        self.assertEqual(q["concepts"][0]["id"], "GO:0000001")
        self.assertEqual(q["concepts"][0]["ontology_edges"], [{"relation": "is_a", "target": "GO:0000002"}])
        self.assertEqual(self.ctx.query(label="C complex")["concepts"][0]["id"], "GO:0000002")
        self.assertEqual(self.ctx.query(label="C* complex")["concepts"][0]["id"], "GO:0000003")

    def test_duplicate_assertions_append_support_then_skip_identical_evidence(self):
        before = (self.root / "inputs/annotations.json").read_bytes()
        a = self.propose([self.record(), self.record(id="LIT:2")], "first")
        self.assertEqual(a["records_emitted"], 1)
        self.assertEqual([r["action"] for r in a["actions"]], ["append_evidence", "already_supported"])
        b = self.propose([self.record()], "second")
        self.assertEqual(b["records_emitted"], 0)
        self.assertEqual((self.root / "inputs/annotations.json").read_bytes(), before)

    def test_context_and_polarity_preserved(self):
        a = self.propose([self.record(context={"cell_type": "K562"}),
                          self.record(id="LIT:2", polarity="negative", context={"cell_type": "K562"})], "states")
        self.assertEqual(a["records_emitted"], 2)
        rows = [json.loads(l) for l in (self.root / a["records_path"]).read_text().splitlines()]
        self.assertEqual({r["polarity"] for r in rows}, {"positive", "negative"})

    def test_pending_relations_visible_in_both_directions(self):
        self.propose([self.record(object_id="GENE:G2", object_label="G2", relation="negatively_regulates", projection_eligible=False)], "links",
                     concepts=[{"id": "GENE:G2", "definition": "The supplied G2 gene.", "kind": "gene"}])
        rows = self.ctx.query(["G2"])["genes"]["G2"]["assertions"]
        self.assertEqual(rows[0]["gene"], "G1")
        self.assertEqual(rows[0]["status"], "candidate")
        self.assertEqual(rows[0]["relation"], "negatively_regulates")

    def test_new_concepts_require_definition_and_collision_review(self):
        r = self.record(object_id="LOCAL:alpha")
        with self.assertRaisesRegex(ValueError, "definition"):
            self.propose([r], "missing")
        with self.assertRaisesRegex(ValueError, "matching existing"):
            self.propose([r], "collision", concepts=[{"id": "LOCAL:alpha", "definition": "A narrower context.", "kind": "process"}])
        a = self.propose([r], "qualified", concepts=[{"id": "LOCAL:alpha", "definition": "A narrower context.", "kind": "process",
                         "distinct_from": [{"concept_id": "GO:0000001", "reason": "The source fixes a distinct substrate."}]}])
        self.assertEqual(a["records_emitted"], 1)
        self.assertEqual(self.propose([r], "repeat")["records_emitted"], 0)

    def test_explicit_equivalence_reuses_canonical_id_and_preserves_origin(self):
        r = self.record(object_id="STUDY:alpha")
        a = self.propose([r], "resolved", equivalences=[{"alias_id": "STUDY:alpha", "canonical_id": "GO:0000001",
                         "relationship": "equivalent", "evidence": "Matching source definition and scope."}])
        record = json.loads((self.root / a["records_path"]).read_text())
        self.assertEqual(record["object_id"], "GO:0000001")
        self.assertEqual(record["evidence"][0]["concept_resolution"]["original_object_id"], "STUDY:alpha")
        with self.assertRaisesRegex(ValueError, "concept-level"):
            self.propose([r], "scoped", equivalences=[{"alias_id": "STUDY:alpha", "canonical_id": "GO:0000001",
                         "relationship": "equivalent", "scope": "task_projection", "evidence": "Feature similarity."}])

    def test_failure_rolls_back_candidate_index(self):
        r = self.record(object_id="LOCAL:new", object_label="New process")
        with self.assertRaises(ValueError):
            self.propose([r, self.record(id="LIT:2", object_id="LOCAL:missing")], "rollback",
                         concepts=[{"id": "LOCAL:new", "definition": "Source-specific process.", "kind": "process"}])
        self.assertEqual(self.ctx.query(concept_id="LOCAL:new")["concepts"], [])

    def test_cli_build_query_and_workspace_boundary(self):
        script = Path(__file__).resolve().parents[1] / "knowledge_ops.py"
        for command in [["build", "--index", "cli.sqlite"], ["query", "--index", "cli.sqlite", "--genes", "G1"]]:
            r = subprocess.run([sys.executable, str(script), "--workspace", str(self.root), *command], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        with self.assertRaisesRegex(ValueError, "inside"):
            KnowledgeContext.build(self.root, self.root.parent / "escape.sqlite")


if __name__ == "__main__":
    unittest.main()

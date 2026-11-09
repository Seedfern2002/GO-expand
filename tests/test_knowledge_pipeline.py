"""Exercise evidence integrity, assembly semantics and frozen task projections."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from go_enrichment.knowledge import (
    assemble, compile_knowledge, project_attributes, read_json, read_records, sha256,
    validate_batches, validate_contract, validate_knowledge_review, write_json, write_rows,
)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write_json(self.root / "genes.json", {"genes": ["A", "B", "C"]})
        write_json(self.root / "base.json", {"A": ["GO:1"], "B": ["GO:1"], "C": ["GO:2"]})
        (self.root / "source.tsv").write_text("A\tP1\nB\tP1\n")
        self.policy = {"baseline_annotations_path": "base.json", "allowed_relations": ["annotated_to", "member_of_pathway", "binds"],
                       "allowed_evidence_classes": ["database_derived", "literature_extracted"],
                       "projection": {"adapter": "gene_attributes", "membership_relations": ["annotated_to", "member_of_pathway"],
                                      "singleton_policy": "retain", "context_policy": "preserve", "k": 1, "threshold": 0.1}}
        self.task = {"task_id": "test", "scope": {"gene_universe_path": "genes.json", "gene_field": "genes"},
                     "organism": {"taxon_id": "NCBITaxon:9606"}, "biological_context": {"cell_type": "K562"},
                     "retrieval_budget": {"max_candidate_records": 5, "max_papers": 2}, "compilation": self.policy}
        self.plan = {"knowledge_contract": copy.deepcopy(self.policy)}
        self.record = {"id": "r1", "subject_id": "HGNC:1", "subject_label": "A", "object_id": "DB:P1", "object_label": "Process one",
                       "relation": "member_of_pathway", "polarity": "positive", "context": {"cell_type": "unknown"},
                       "evidence_class": "database_derived", "projection_eligible": True,
                       "evidence": [{"source_name": "DB", "source_version": "1", "source_uri": "urn:db",
                                     "study_id": "PMID:1", "locator": "line:1", "snapshot_path": "source.tsv",
                                     "snapshot_sha256": sha256(self.root / "source.tsv"), "assertion_type": "database_record"}]}

    def rows(self, *records):
        p = self.root / "records.jsonl"
        write_rows(p, records or [self.record])
        return p

    def batch(self):
        path = self.rows()
        write_json(self.root / "coverage.json", {"universe_size": 3, "genes_screened": 3, "genes_annotated": 1, "record_count": 1})
        write_json(self.root / "validation.json", {"validated_rows": 1, "failed_rows": 0})
        write_json(self.root / "provenance.json", {"source": "synthetic fixture"})
        return {"id": "B1", "records_path": str(path), "records_sha256": sha256(path),
                "coverage_report_path": "coverage.json", "validation_report_path": "validation.json", "provenance_path": "provenance.json"}

    def test_duplicate_claims_merge_evidence_without_multiplying_studies(self):
        other = copy.deepcopy(self.record)
        other["id"] = "r2"
        other["evidence"][0]["source_uri"] = "urn:second-index-of-same-study"
        result = assemble([self.record, other])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["evidence"]), 2)
        self.assertEqual(result[0]["identified_study_count"], 1)

    def test_context_and_polarity_are_not_collapsed(self):
        other = copy.deepcopy(self.record)
        other.update(id="r2", polarity="negative", context={"cell_type": "A375"})
        self.assertEqual(len(assemble([self.record, other])), 2)

    def test_overlap_is_not_an_equivalence(self):
        other = copy.deepcopy(self.record)
        other.update(id="r2", object_id="DB:P2")
        self.assertEqual(len(assemble([self.record, other])), 2)
        mapping = [{"alias_id": "DB:P2", "canonical_id": "DB:P1", "relationship": "equivalent", "evidence": ["reviewed mapping"]}]
        self.assertEqual(len(assemble([self.record, other], mapping)), 1)
        mapping[0]["relationship"] = "related"
        with self.assertRaisesRegex(ValueError, "equivalence evidence"):
            assemble([self.record, other], mapping)

    def test_equivalence_cycles_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            assemble([], [{"alias_id": "DB:1", "canonical_id": "DB:2", "relationship": "equivalent", "evidence": ["x"]},
                          {"alias_id": "DB:2", "canonical_id": "DB:1", "relationship": "equivalent", "evidence": ["x"]}])

    def test_changed_evidence_snapshot_is_rejected(self):
        path = self.rows()
        (self.root / "source.tsv").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "snapshot checksum"):
            read_records(path, self.task, self.root)

    def test_invalid_line_locator_is_rejected(self):
        self.record["evidence"][0]["locator"] = "line:999"
        with self.assertRaisesRegex(ValueError, "source line"):
            read_records(self.rows(), self.task, self.root)

    def test_go_grounding_checks_active_canonical_ids(self):
        (self.root / "go.obo").write_text("format-version: 1.2\n\n[Term]\nid: GO:0000001\nname: process\nalt_id: GO:0000002\n")
        self.policy["ontology_path"] = "go.obo"
        self.record["object_id"] = "GO:0000001"
        self.assertEqual(len(read_records(self.rows(), self.task, self.root)), 1)
        self.record["object_id"] = "GO:0000002"
        with self.assertRaisesRegex(ValueError, "canonical GO"):
            read_records(self.rows(), self.task, self.root)
        self.record["object_id"] = "GO:9999999"
        with self.assertRaisesRegex(ValueError, "Unknown GO"):
            read_records(self.rows(), self.task, self.root)

    def test_reactome_stable_id_is_preserved(self):
        self.record["object_id"] = "R-HSA-12345"
        self.assertEqual(read_records(self.rows(), self.task, self.root)[0]["object_id"], "R-HSA-12345")

    def test_unsupported_literature_quote_is_rejected(self):
        self.record["evidence_class"] = "literature_extracted"
        self.record["evidence"][0]["quote"] = "A fabricated mechanistic statement never written in the source."
        with self.assertRaisesRegex(ValueError, "verbatim passage"):
            read_records(self.rows(), self.task, self.root)

    def test_paper_bundle_materializes_supported_claim(self):
        spec = importlib.util.spec_from_file_location("batch_import_test", ROOT / "scripts/import_knowledge_batch.py")
        importer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(importer)
        quote = "Gene A participates in process one in this experimental system."
        (self.root / "paper.txt").write_text(quote)
        papers = [{"paper_id": "PMID:1", "source_name": "PMC", "source_version": "1", "source_uri": "urn:paper:1",
                   "study_id": "PMID:1", "text_path": "paper.txt", "text_sha256": sha256(self.root / "paper.txt")}]
        write_json(self.root / "papers.json", papers)
        claim = copy.deepcopy(self.record)
        claim.pop("evidence")
        claim["paper_evidence"] = [{"paper_id": "PMID:1", "locator": "Results", "quote": quote, "assertion_type": "experimental_result"}]
        batch = importer.import_batch(self.task, self.rows(claim), self.root / "imported", "B1", "P1", root=self.root, paper_manifest="papers.json")
        report = validate_batches(self.task, [batch], self.root)["B1"]
        self.assertEqual((report["genes_screened"], report["genes_annotated"]), (3, 1))

    def test_forged_report_count_is_rejected(self):
        batch = self.batch()
        coverage = read_json(self.root / "coverage.json")
        coverage["record_count"] = 2
        write_json(self.root / "coverage.json", coverage)
        with self.assertRaisesRegex(ValueError, "independently counted"):
            validate_batches(self.task, [batch], self.root)

    def test_contract_cannot_change_after_task_definition(self):
        self.plan["knowledge_contract"]["projection"]["k"] = 10
        with self.assertRaisesRegex(ValueError, "predeclared"):
            validate_contract(self.task, self.plan)

    def test_explicit_negation_conflict_stays_in_knowledge_and_out_of_projection(self):
        other = copy.deepcopy(self.record)
        other.update(id="r2", polarity="negative")
        statements = assemble([self.record, other])
        attrs, reasons = project_attributes(statements, ["A", "B", "C"], {}, self.policy["projection"], {})
        self.assertEqual(attrs["A"], set())
        self.assertEqual(reasons["conflicting_assertions"], 2)
        self.assertEqual(len(statements), 2)

    def test_hypothesis_and_binding_do_not_become_membership_attributes(self):
        self.record["evidence"][0]["assertion_type"] = "hypothesis"
        attrs, _ = project_attributes(assemble([self.record]), ["A"], {}, self.policy["projection"], {})
        self.assertFalse(attrs["A"])
        self.record["evidence"][0]["assertion_type"] = "experimental_result"
        self.record["relation"] = "binds"
        attrs, _ = project_attributes(assemble([self.record]), ["A"], {}, self.policy["projection"], {})
        self.assertFalse(attrs["A"])

    def test_context_filter_preserves_general_human_evidence(self):
        projection = {**self.policy["projection"], "context_policy": "compatible"}
        self.record["context"] = {"cell_type": "A375"}
        attrs, _ = project_attributes(assemble([self.record]), ["A"], {}, projection, {"cell_type": "K562"})
        self.assertFalse(attrs["A"])
        self.record["context"]["source_scope"] = "general_human"
        attrs, _ = project_attributes(assemble([self.record]), ["A"], {}, projection, {"cell_type": "K562"})
        self.assertTrue(attrs["A"])

    def test_singleton_rule_does_not_remove_original_attributes(self):
        projection = {**self.policy["projection"], "singleton_policy": "exclude_new"}
        attrs, _ = project_attributes(assemble([self.record]), ["A"], {"A": ["GO:1"]}, projection, {})
        self.assertEqual(attrs["A"], {"GO:1"})

    def test_freeze_hashes_all_outputs_and_refuses_overwrite(self):
        path = self.rows()
        output = self.root / "compiled"
        summary = compile_knowledge(self.task, self.plan, [path], self.root, output)
        self.assertEqual(summary["added_memberships"], 1)
        self.assertEqual(summary["genes"], 3)
        manifest = read_json(output / "freeze_manifest.json")
        self.assertTrue(all(sha256(output / f["path"]) == f["sha256"] for f in manifest["files"]))
        self.assertIn("external", manifest["leakage_audit"])
        with self.assertRaises(FileExistsError):
            compile_knowledge(self.task, self.plan, [path], self.root, output)

    def test_reviewer_cannot_introduce_claims(self):
        batch = self.batch()
        other = copy.deepcopy(self.record)
        other["object_id"] = "DB:invented"
        write_rows(self.root / "approved.jsonl", [other])
        write_json(self.root / "audit.json", {})
        decision = {"batch_id": "B1", "verdict": "accept", "approved_records_path": "approved.jsonl",
                    "approved_records_sha256": sha256(self.root / "approved.jsonl"), "audit_report_path": "audit.json"}
        with self.assertRaisesRegex(ValueError, "new or edited claims"):
            validate_knowledge_review(self.task, {"batches": [batch]}, {"batch_decisions": [decision]}, self.root)

    def test_completed_stage_chain_compiles_and_rejects_modified_handoff(self):
        spec = importlib.util.spec_from_file_location("compile_run_test", ROOT / "scripts/compile_agent_knowledge.py")
        compiler = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compiler)
        batch = self.batch()
        candidates = {"batches": [batch]}
        write_json(self.root / "audit.json", {"review_method": "source_policy_and_sample"})
        review = {"batch_decisions": [{"batch_id": "B1", "verdict": "accept", "approved_records_path": batch["records_path"],
                   "approved_records_sha256": batch["records_sha256"], "audit_report_path": "audit.json"}],
                  "equivalences_path": None, "equivalences_sha256": None}
        run = self.root / "run"
        for stage, result in [("planner", self.plan), ("retriever", candidates), ("reviewer", review)]:
            d = run / stage
            d.mkdir(parents=True)
            write_json(d / "result.json", result)
            write_json(d / "schema.json", {"type": "object"})
            inputs = {"task": self.task}
            if stage != "planner":
                inputs["plan"] = self.plan
            if stage == "reviewer":
                inputs["candidates"] = candidates
            for name, value in inputs.items():
                write_json(d / f"{name}.input.json", value)
            write_json(d / "manifest.json", {"workflow": "task_knowledge", "inputs": {
                name: {"sha256": sha256(d / f"{name}.input.json")} for name in inputs}})
            write_json(d / "execution.json", {"status": "completed", "result_sha256": sha256(d / "result.json"),
                                              "schema_sha256": sha256(d / "schema.json")})
        summary = compiler.compile_run(run, self.root / "product", root=self.root)
        self.assertEqual(summary["added_memberships"], 1)
        write_json(run / "reviewer/plan.input.json", {})
        with self.assertRaisesRegex(ValueError, "input changed"):
            compiler.compile_run(run, self.root / "bad_product", root=self.root)

    def test_v3_preparation_preserves_historical_default_and_uses_new_schema(self):
        subprocess.run([sys.executable, str(ROOT / "scripts/prepare_agent_stage.py"), "--stage", "planner",
                        "--task", str(ROOT / "configs/agent_tasks/gears_norman_v3.json"), "--run-dir", str(self.root / "run")],
                       check=True, capture_output=True)
        stage = self.root / "run/planner"
        self.assertEqual(read_json(stage / "manifest.json")["workflow"], "task_knowledge")
        self.assertEqual(read_json(stage / "schema.json")["properties"]["schema_version"]["enum"], ["3.0"])
        self.assertFalse(any('\u4e00' <= c <= '\u9fff' for c in (stage / "prompt.md").read_text()))
        self.assertEqual(read_json(ROOT / "configs/agent_tasks/gears_norman.json")["execution"]["workflow"], "task_batch")


if __name__ == "__main__":
    unittest.main()

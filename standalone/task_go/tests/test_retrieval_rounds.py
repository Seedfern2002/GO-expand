"""Exercise target-driven continuation and evidence-backed reading counters."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))
import run as runtime
from engine.knowledge import sha256, write_json
from engine.rounds import identities, merge_candidates, next_action, paper_counts, read_inspections


class RetrievalRoundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "inputs").mkdir()
        (self.root / "stages/planner").mkdir(parents=True)
        write_json(self.root / "inputs/genes.json", {"genes": ["GENE1"]})
        self.task = {"task_id": "reading", "scope": {"gene_universe_path": "inputs/genes.json", "gene_field": "genes"},
                     "compilation": {"baseline_annotations_path": "inputs/annotations.json", "allowed_relations": ["annotated_to"], "allowed_evidence_classes": ["literature_extracted"],
                                     "ontology_path": None},
                     "retrieval_budget": {"target_papers_inspected": 2, "target_full_text_papers_inspected": 1,
                       "max_search_queries": 100, "max_sources_opened": 100, "max_papers": 10,
                       "max_candidate_records": 20, "max_download_bytes": 100000}}
        write_json(self.root / "task.json", self.task)
        write_json(self.root / "inputs/annotations.json", {"GENE1": []})
        write_json(self.root / "stages/planner/result.json", {"augmentations": [{"id": "functions"}]})
        self.abstract = "A complete abstract passage describing a gene function in human cells."
        self.body = "The functional experiments measured the reported phenotype using two controls."
        self.snapshot = self.root / "inputs/paper.txt"
        self.snapshot.write_text("Abstract\n" + self.abstract + "\nResults\n" + self.body)

    def observation(self, pmid, level="abstract"):
        passages = [{"section": "Abstract", "locator": "abstract", "quote": self.abstract}]
        if level == "full_text":
            passages.append({"section": "Results", "locator": "results paragraph 1", "quote": self.body})
        return {"paper_id": "PMID:" + pmid, "pmid": pmid, "pmcid": None, "doi": None,
                "is_primary": True, "inspection_level": level, "snapshot_path": "inputs/paper.txt",
                "snapshot_sha256": sha256(self.snapshot), "decision": "defer", "reason": "Further gene-specific extraction pending",
                "passages": passages}

    def saved_observations(self, row, visible=True):
        directory = self.root / "test_round"
        directory.mkdir(exist_ok=True)
        ledger = directory / "papers.jsonl"
        ledger.write_text(json.dumps(row) + "\n")
        output = self.abstract + "\n" + self.body if visible else "Downloaded one source"
        (directory / "events.jsonl").write_text(json.dumps({"type": "item.completed", "item": {
            "type": "command_execution", "aggregated_output": output}}) + "\n")
        return ledger, directory / "events.jsonl"

    def test_downloaded_text_without_tool_visible_reading_is_rejected(self):
        ledger, events = self.saved_observations(self.observation("1"), visible=False)
        with self.assertRaisesRegex(ValueError, "not exposed"):
            read_inspections(ledger, self.root, events)

    def test_abstract_cannot_satisfy_full_text_inspection(self):
        row = self.observation("1")
        row["inspection_level"] = "full_text"
        ledger, events = self.saved_observations(row)
        with self.assertRaisesRegex(ValueError, "body passage"):
            read_inspections(ledger, self.root, events)

    def test_full_text_passages_are_validated_against_snapshots(self):
        ledger, events = self.saved_observations(self.observation("1", "full_text"))
        self.assertEqual(len(read_inspections(ledger, self.root, events)), 1)
        self.snapshot.write_text("Changed source text")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            read_inspections(ledger, self.root, events)

    def test_pmid_doi_aliases_and_full_text_upgrades_count_once(self):
        first = {**self.observation("1"), "doi": "10.1234/example"}
        upgrade = {**self.observation("1", "full_text"), "pmid": None, "doi": "https://doi.org/10.1234/EXAMPLE"}
        counts = paper_counts([first, upgrade])
        self.assertEqual(counts, {"unique_inspected_papers": 1, "inspected_primary": 1, "full_text_inspected_primary": 1})

    def test_pending_reading_targets_continue_after_partial_return(self):
        progress = {"inspected_primary": 1, "full_text_inspected_primary": 0}
        self.assertEqual(next_action(self.task, progress, 1, 10, 0, 3), "continue")
        progress["inspected_primary"] = 2
        self.assertEqual(next_action(self.task, progress, 2, 10, 0, 3), "continue")
        progress["full_text_inspected_primary"] = 1
        self.assertEqual(next_action(self.task, progress, 3, 10, 0, 3), "targets_met")

    def test_resource_and_stall_limits_produce_explicit_gap_reasons(self):
        self.assertEqual(next_action(self.task, {"search_queries": 100}, 1, 10, 0, 3), "resource_limit:search_queries")
        self.assertEqual(next_action(self.task, {}, 3, 10, 3, 3), "stalled_reading")
        self.assertEqual(next_action(self.task, {}, 10, 10, 0, 3), "round_limit")

    def test_rounds_append_batches_and_require_explicit_revisions(self):
        previous = {"batches": [{"id": "old", "records_sha256": "old_hash"}]}
        result = {"task_id": "reading", "batches": [{"id": "new"}], "coverage": [], "open_questions": []}
        self.assertEqual([b["id"] for b in merge_candidates(previous, result)["batches"]], ["old", "new"])
        result["batches"] = [{"id": "old", "records_sha256": "changed_hash"}]
        with self.assertRaisesRegex(ValueError, "new batch ID"):
            merge_candidates(previous, result)
        result.update(batches=[{"id": "new"}], supersedes_batch_ids=["old"])
        self.assertEqual(merge_candidates(previous, result)["batches"], [{"id": "new"}])

    def test_controller_reinvokes_acquisition_and_accumulates_both_rounds(self):
        self.controller_rounds()

    def test_adaptive_controller_uses_fresh_batches_and_finishes_with_abstracts(self):
        self.task["retrieval_budget"].update(reading_mode="planner_adaptive", max_full_text_papers=3)
        plan = {"augmentations": [{"id": "functions"}], "reading_plan": {
            "initial_papers": 2, "batch_size": 1, "max_full_text_papers": 2,
            "topic_questions": ["Which functions are supported?"], "stop_criteria": ["Topic coverage resolved"]}}
        write_json(self.root / "stages/planner/result.json", plan)
        write_json(self.root / "task.json", self.task)
        self.controller_rounds(adaptive=True)

    def controller_rounds(self, adaptive=False):
        seen = []

        def agent(stage, task, settings, root, directory, round_input):
            directory.mkdir(parents=True)
            number = round_input["number"]
            seen.append(number)
            if adaptive:
                self.assertEqual(round_input["new_papers_target"], 1)
                self.assertEqual(round_input["full_text_inspections_target"], 0)
                self.assertTrue((root / round_input["knowledge_context_index"]).is_file())
            row = self.observation(str(number), "full_text" if number == 2 and not adaptive else "abstract")
            (directory / "papers.jsonl").write_text(json.dumps(row) + "\n")
            (directory / "events.jsonl").write_text(json.dumps({"type": "item.completed", "item": {
                "type": "command_execution", "aggregated_output": self.abstract + "\n" + self.body}}) + "\n")
            write_json(directory / "usage.json", {"search_queries": 0, "sources_opened": number,
                       "paper_identities_opened": number, "literature_candidate_statements": number})
            record = {"id": f"LIT:{number}", "subject_id": "HGNC:1", "subject_label": "GENE1",
                      "object_id": "LOCAL:function", "object_label": "Supported function", "relation": "annotated_to",
                      "polarity": "positive", "context": {}, "evidence_class": "literature_extracted", "projection_eligible": True,
                      "evidence": [{"source_name": "Primary paper", "source_version": "test snapshot",
                                    "source_uri": f"https://example.org/paper/{number}", "study_id": f"PMID:{number}",
                                    "locator": "Abstract", "snapshot_path": "inputs/paper.txt",
                                    "snapshot_sha256": sha256(self.snapshot), "quote": self.abstract,
                                    "assertion_type": "experimental_result"}]}
            records = directory / "records.jsonl"
            records.write_text(json.dumps(record) + "\n")
            write_json(directory / "coverage.json", {"universe_size": 1, "genes_screened": 1,
                       "genes_annotated": 1, "record_count": 1})
            write_json(directory / "validation.json", {"validated_rows": 1, "failed_rows": 0})
            write_json(directory / "provenance.json", {"source": "Primary paper"})
            batch = {"id": f"round{number}", "plan_item_id": "functions", "source_name": "Primary paper",
                     "source_version": "test", "source_uri": f"https://example.org/paper/{number}",
                     "records_path": str(records.relative_to(root)), "records_sha256": sha256(records),
                     "coverage_report_path": str((directory / "coverage.json").relative_to(root)),
                     "validation_report_path": str((directory / "validation.json").relative_to(root)),
                     "provenance_path": str((directory / "provenance.json").relative_to(root))}
            result = {"task_id": task["task_id"], "batches": [batch], "coverage": [{"plan_item_id": "functions",
                    "status": "covered", "notes": "Round complete"}], "open_questions": [],
                    "paper_inspections_path": str((directory / "papers.jsonl").relative_to(root)),
                    "usage_path": str((directory / "usage.json").relative_to(root)), "supersedes_batch_ids": []}
            if adaptive:
                result["reading_decision"] = {"decision": "stop" if number == 2 else "continue",
                    "reason": "All planned topic questions resolved" if number == 2 else "Continue the remaining topic",
                    "stop_code": "coverage_sufficient" if number == 2 else "continue",
                    "next_batch_size": 0 if number == 2 else 1, "unresolved_questions": []}
            return result

        with patch.object(runtime, "run_stage", side_effect=agent):
            result = runtime.run_retrieval_rounds(self.task, {"retrieval_rounds": 5}, self.root,
                                                  lambda *args, **kwargs: None)
        self.assertEqual(seen, [1, 2])
        self.assertEqual(result, "coverage_sufficient" if adaptive else "targets_met")
        progress = json.loads((self.root / "rounds/progress.json").read_text())
        self.assertEqual(progress["progress"]["inspected_primary"], 2)
        self.assertEqual(progress["progress"]["full_text_inspected_primary"], 0 if adaptive else 1)
        self.assertEqual(progress["progress"]["active_records"], 2)
        self.assertEqual(progress["progress"]["active_batches"], 2)


if __name__ == "__main__":
    unittest.main()

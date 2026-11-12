"""Verify role-specific skill loading and review before each graph commit."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.knowledge import sha256
from engine.module_prompts import build_module_prompt, instruction_manifest, instruction_receipts
from engine.module_progress import load_progress
from place_module_recipes import schemas, worker
from place_modules import agent, write
import test_module_graph as fixtures


class ModuleSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"; self.root.mkdir()
        shutil.copytree(Path(__file__).resolve().parents[1], self.root / "pipeline",
                        ignore=shutil.ignore_patterns("tests", "__pycache__"))
        write(self.root / "task.json", {"task_id": "scientific_task", "task_description": "Human repair knowledge"})

    def invoke(self, role, directory, result):
        def backend(command, **kwargs):
            write(Path(command[command.index("--output-last-message") + 1]), result)
            return SimpleNamespace(wait=lambda **_kwargs: 0)
        schema = schemas()[0 if role == "recipe_editor" else 1]
        with patch("place_modules.assert_external_boundary"), patch("place_modules.subprocess.Popen", side_effect=backend):
            return agent(role, self.root, self.root / directory,
                         {"model": "fixture", "reasoning_effort": "medium", "stage_timeout_seconds": 1},
                         {"batch_id": "b", "graph_revision": 0}, schema)

    def test_roles_load_distinct_skills_and_only_the_active_interface(self):
        editor = instruction_manifest(self.root, "recipe_editor")
        reviewer = instruction_manifest(self.root, "recipe_reviewer")
        self.assertEqual(editor["skill"], "place-functional-modules")
        self.assertEqual(reviewer["skill"], "review-functional-modules")
        self.assertEqual(editor["interface"], "group_recipe")
        paths = {x["path"] for x in reviewer["resources"]}
        self.assertIn("pipeline/skills/review-functional-modules/references/group-reviews.md", paths)
        self.assertNotIn("pipeline/skills/place-functional-modules/SKILL.md", paths)
        self.assertNotIn("pipeline/skills/review-functional-modules/references/transactions.md", paths)
        shared = lambda value: next(x for x in value["resources"] if x["kind"] == "shared_semantics")
        self.assertEqual(shared(editor), shared(reviewer))
        legacy = instruction_manifest(self.root, "reviewer")
        self.assertEqual(legacy["interface"], "transaction")
        self.assertTrue(legacy["resources"][-1]["path"].endswith("references/transactions.md"))

    def test_prompt_is_self_contained_and_uses_declared_workspace_resources(self):
        (Path(self.tmp.name) / "previous_result.txt").write_text("OUTSIDE_EXPERIMENT_MARKER")
        prompt, manifest = build_module_prompt(self.root, "recipe_editor", {"batch_id": "b", "graph_revision": 3})
        for resource in manifest["resources"]:
            self.assertIn((self.root / resource["path"]).read_text(), prompt)
            self.assertEqual(resource["sha256"], sha256(self.root / resource["path"]))
            self.assertFalse(Path(resource["path"]).is_absolute())
        self.assertNotIn("OUTSIDE_EXPERIMENT_MARKER", prompt)
        self.assertIn('"graph_revision":3', prompt)

    def test_executed_prompt_and_skill_versions_are_bound_in_receipts(self):
        result = {"batch_id": "b", "graph_revision": 0, "groups": []}
        self.invoke("recipe_reviewer", "batches/b/reviewer", result)
        receipt = instruction_receipts(self.root)["invocations"][0]
        self.assertEqual(receipt["skill"], "review-functional-modules")
        self.assertEqual(receipt["prompt_sha256"], sha256(self.root / "batches/b/reviewer/prompt.md"))

    def test_changed_skill_or_prompt_blocks_freeze_provenance(self):
        self.invoke("recipe_reviewer", "batches/b/reviewer", {"batch_id": "b", "graph_revision": 0, "groups": []})
        skill = self.root / "pipeline/skills/review-functional-modules/SKILL.md"
        original = skill.read_text(); skill.write_text(original + "\nChanged scope.\n")
        with self.assertRaisesRegex(ValueError, "instruction resources changed"):
            instruction_receipts(self.root)
        skill.write_text(original)
        with (self.root / "batches/b/reviewer/prompt.md").open("a") as stream:
            stream.write("\nChanged prompt.\n")
        with self.assertRaisesRegex(ValueError, "executed prompt"):
            instruction_receipts(self.root)

    def test_unknown_role_and_instruction_escape_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown module agent role"):
            instruction_manifest(self.root, "../../outside")
        outside = Path(self.tmp.name) / "outside.md"; outside.write_text("Outside instructions")
        path = self.root / "pipeline/references/knowledge_semantics.md"
        path.unlink(); path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "task pipeline"):
            instruction_manifest(self.root, "recipe_editor")

    def test_two_batches_each_review_then_commit_and_freeze_all_skill_receipts(self):
        fixture = fixtures.ModuleGraphTests(); fixture.setUp()
        for m in fixture.catalog.values():
            m["evidence_ids"].append("E2")
        inputs = {"baseline_graph.json": fixture.graph, "modules.json": fixture.catalog,
                  "placement_evidence.json": fixture.facts,
                  "module_batches.json": [{"id": "b1", "modules": ["EXT:P"]}, {"id": "b2", "modules": ["EXT:C"]}]}
        for name, value in inputs.items():
            write(self.root / "inputs" / name, value)
        write(self.root / "inputs/manifest.json", {"task_sha256": sha256(self.root / "task.json"),
            "files": [{"path": "inputs/" + name, "sha256": sha256(self.root / "inputs" / name)} for name in inputs]})
        write(self.root / "runtime.json", {"model": "fixture", "reasoning_effort": "medium", "stage_timeout_seconds": 1,
                                          "publish_memberships": True})
        observed = []
        def backend(command, **kwargs):
            result_path = Path(command[command.index("--output-last-message") + 1])
            batch = result_path.parent.parent.name; editor = result_path.parent.name.startswith("editor")
            current = json.loads((self.root / "graph/current.json").read_text())
            observed.append((batch, "editor" if editor else "reviewer", current["revision"], set(current["nodes"])))
            module = "EXT:P" if batch == "b1" else "EXT:C"
            if editor:
                group = {"group_id": "repair", "modules": [module],
                    "rationale": "The source-defined repair submodule supports the complete task.",
                    "inspected_concepts": ["GO:REPAIR"], "native_hierarchy": batch == "b2", "reuse": [], "defer": [],
                    "anchors": [], "extra_edges": []}
                if batch == "b1":
                    group["anchors"] = [{"parent": "GO:REPAIR", "modules": [module], "relation": "model_aggregation",
                        "model_edge": True, "rationale": "The parent module groups this source-defined repair process."}]
                result = {"batch_id": batch, "graph_revision": current["revision"], "groups": [group]}
            else:
                result = {"batch_id": batch, "graph_revision": current["revision"], "groups": [{"group_id": "repair",
                    "verdict": "accept", "reason": "The source definition and native relationship support this placement.", "exceptions": []}]}
            write(result_path, result)
            kwargs["stdout"].write('{"type":"turn.completed","usage":{}}\n')
            return SimpleNamespace(wait=lambda **_kwargs: 0)
        old_cwd = Path.cwd()
        try:
            with patch("place_modules.assert_external_boundary"), patch("place_modules.subprocess.Popen", side_effect=backend), contextlib.redirect_stdout(io.StringIO()):
                code = worker(self.root)
        finally:
            os.chdir(old_cwd)
        self.assertEqual(code, 0)
        self.assertEqual([(b, role, rev) for b, role, rev, _ in observed],
                         [("b1", "editor", 0), ("b1", "reviewer", 0), ("b2", "editor", 1), ("b2", "reviewer", 1)])
        self.assertNotIn("EXT:P", observed[1][3])
        self.assertIn("EXT:P", observed[2][3])
        graph = json.loads((self.root / "knowledge_graph/graph.json").read_text())
        self.assertEqual(graph["revision"], 2)
        self.assertTrue(any(e["parent"] == "EXT:P" and e["child"] == "EXT:C" for e in graph["edges"]))
        manifest = json.loads((self.root / "knowledge_graph/freeze_manifest.json").read_text())
        self.assertIn("instructions.json", {r["path"] for r in manifest["files"]})
        receipts = json.loads((self.root / "knowledge_graph/instructions.json").read_text())
        self.assertEqual(len(receipts["invocations"]), 4)
        self.assertEqual([x["skill"] for x in receipts["invocations"]],
                         ["place-functional-modules", "review-functional-modules"] * 2)
        self.assertEqual(json.loads((self.root / "efficiency.json").read_text())["agent_invocations"], 4)
        loaded, timings = load_progress(self.root, fixture.graph, fixture.catalog, fixture.facts, inputs["module_batches.json"])
        self.assertEqual(loaded, graph)
        self.assertEqual(len(timings), 2)
        membership_freeze = json.loads((self.root / "knowledge/freeze_manifest.json").read_text())
        self.assertIn("task.json", {r["path"] for r in membership_freeze["files"]})
        self.assertTrue(any(r["path"] == "knowledge_graph/freeze_manifest.json" for r in membership_freeze["inputs"]))
        graph["revision"] = 99
        write(self.root / "graph/current.json", graph)
        with self.assertRaisesRegex(ValueError, "replayed accepted batches"):
            load_progress(self.root, fixture.graph, fixture.catalog, fixture.facts, inputs["module_batches.json"])


if __name__ == "__main__":
    unittest.main()

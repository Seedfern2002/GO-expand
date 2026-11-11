import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.reading import validate_reading_plan, round_reading_input, validate_reading_decision
from engine.rounds import next_action


class AdaptiveReadingTests(unittest.TestCase):
    def setUp(self):
        self.task = {"retrieval_budget": {"reading_mode": "planner_adaptive", "max_papers": 100,
                     "max_papers_per_round": 20, "max_full_text_papers": 10}}
        self.plan = {"reading_plan": {"initial_papers": 20, "batch_size": 10, "max_full_text_papers": 5,
                     "topic_questions": ["Which complexes support the task?"], "stop_criteria": ["Resolve planned questions."]}}
        self.progress = {"inspected_primary": 20, "full_text_inspected_primary": 0}
        self.stop = {"decision": "stop", "reason": "Planned questions have supporting source evidence.",
                     "stop_code": "coverage_sufficient", "next_batch_size": 0, "unresolved_questions": []}

    def test_planner_chooses_initial_volume_within_resource_ceilings(self):
        validate_reading_plan(self.task, self.plan)
        self.plan["reading_plan"]["initial_papers"] = 101
        with self.assertRaisesRegex(ValueError, "ceiling"):
            validate_reading_plan(self.task, self.plan)

    def test_no_body_reading_quota_and_smaller_next_bundle(self):
        r = round_reading_input(self.task, self.plan, {}, self.progress, {"next_batch_size": 3})
        self.assertEqual(r["new_papers_target"], 3)
        self.assertEqual(r["full_text_inspections_target"], 0)
        self.assertEqual(r["full_text_budget_remaining"], 5)

    def test_controller_continues_without_default_zero_targets(self):
        self.assertEqual(next_action(self.task, self.progress, 1, 10, 0, 3), "continue")
        self.assertEqual(next_action(self.task, self.progress, 1, 10, 0, 3, self.stop), "coverage_sufficient")

    def test_can_finish_from_abstracts_with_resolved_questions(self):
        d = validate_reading_decision(self.task, self.plan, {"reading_decision": self.stop}, [], self.progress)
        self.assertEqual(d["decision"], "stop")
        self.stop["unresolved_questions"] = ["Missing component list"]
        with self.assertRaisesRegex(ValueError, "resolved"):
            validate_reading_decision(self.task, self.plan, {"reading_decision": self.stop}, [], self.progress)

    def test_body_inspection_needs_a_concrete_abstract_first_question(self):
        observation = {"inspection_level": "full_text"}
        with self.assertRaisesRegex(ValueError, "information need"):
            validate_reading_decision(self.task, self.plan, {"reading_decision": self.stop}, [observation], self.progress)
        observation["body_reading_request"] = {"reason_code": "large_scale_screen", "abstract_assessment": "A source reports a complete functional screen.",
                                              "question": "Which in-universe genes appear in the validated supplement?"}
        validate_reading_decision(self.task, self.plan, {"reading_decision": self.stop}, [observation], self.progress)

    def test_body_budget_is_an_enforced_upper_bound(self):
        self.progress["full_text_inspected_primary"] = 6
        with self.assertRaisesRegex(ValueError, "ceiling"):
            validate_reading_decision(self.task, self.plan, {"reading_decision": self.stop}, [], self.progress)

    def test_resource_limits_override_planner_coverage_stop(self):
        self.progress["paper_identities_opened"] = 100
        self.assertEqual(next_action(self.task, self.progress, 1, 10, 0, 3, self.stop), "resource_limit:paper_identities_opened")


if __name__ == "__main__":
    unittest.main()

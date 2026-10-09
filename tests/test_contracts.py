import copy
import unittest

from harness_fusion import contracts as c


def valid_plan():
    return {"summary": "Calculator", "tasks": [{"id": "T1", "title": "Add",
            "depends_on": [], "touch": ["calculator.py", "tests/**"], "acceptance": ["2+3=5"]}]}


def valid_review():
    return {"token": "fresh", "task_id": "T1", "verdict": "PASS", "spec_score": 3,
            "test_score": 3, "criteria": [{"criterion": "2+3=5", "passed": True,
            "evidence": "test_add verifies actual result"}], "issues": []}


class ContractsTests(unittest.TestCase):
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(c.ContractError):
            c.object_from('{"verdict":"FAIL","verdict":"PASS"}')

    def test_plain_pass_is_not_a_review(self):
        with self.assertRaises(c.ContractError):
            c.object_from("PASS")

    def test_object_after_progress_prose_is_accepted(self):
        text = 'I have launched `npm run lint`.\nWaiting for the task to finish.\n{\n  "summary": "done {ok}"\n}\n'
        self.assertEqual(c.object_from(text), {"summary": "done {ok}"})

    def test_fenced_object_after_prose_is_accepted(self):
        self.assertEqual(c.object_from('Result:\n```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_after_object_is_rejected(self):
        with self.assertRaises(c.ContractError):
            c.object_from('{"verdict": "PASS"}\nActually it failed.')

    def test_duplicate_keys_after_prose_rejected(self):
        with self.assertRaises(c.ContractError) as caught:
            c.object_from('Done.\n{"verdict":"FAIL","verdict":"PASS"}')
        self.assertIn("Duplicate", str(caught.exception))

    def test_prose_without_object_rejected(self):
        with self.assertRaises(c.ContractError):
            c.object_from("Waiting for the task {to finish}")

    def test_no_checks_cannot_pass(self):
        self.assertFalse(c.gate([], valid_review()))

    def test_failed_check_overrides_model_pass(self):
        self.assertFalse(c.gate([{"returncode": 1}], valid_review()))

    def test_low_scores_and_unresolved_issues_block(self):
        for key, value in [("spec_score", 1), ("test_score", 1), ("issues", ["Missing edge cases"]), ("verdict", "BLOCKED")]:
            with self.subTest(key=key):
                review = valid_review()
                review[key] = value
                self.assertFalse(c.gate([{"returncode": 0}], review))

    def test_false_criterion_blocks(self):
        review = valid_review()
        review["criteria"][0]["passed"] = False
        self.assertFalse(c.gate([{"returncode": 0}], review))

    def test_stale_review_rejected(self):
        with self.assertRaises(c.ContractError):
            c.review(valid_review(), "new-token", "T1", ["2+3=5"])

    def test_exact_criteria_required(self):
        review = valid_review()
        review["criteria"][0]["criterion"] = "Some other test"
        with self.assertRaises(c.ContractError):
            c.review(review, "fresh", "T1", ["2+3=5"])

    def test_boolean_score_rejected(self):
        review = valid_review()
        review["spec_score"] = True
        with self.assertRaises(c.ContractError):
            c.review(review, "fresh", "T1", ["2+3=5"])

    def test_plan_requires_tasks(self):
        with self.assertRaises(c.ContractError):
            c.plan({"summary": "done", "tasks": []})

    def test_dependency_cycle_rejected(self):
        plan = valid_plan()
        plan["tasks"][0]["depends_on"] = ["T1"]
        with self.assertRaises(c.ContractError):
            c.plan(plan)

    def test_duplicate_task_rejected(self):
        plan = valid_plan()
        plan["tasks"].append(copy.deepcopy(plan["tasks"][0]))
        with self.assertRaises(c.ContractError):
            c.plan(plan)

    def test_unsafe_touch_rejected(self):
        for path in ("../secret", "/tmp/data", "C:/data", "**/*", ".fusion/state.json", "a\\b"):
            with self.subTest(path=path), self.assertRaises(c.ContractError):
                c.path_rule(path)

    def test_valid_contracts(self):
        self.assertEqual(c.plan(valid_plan()), valid_plan())
        assessment = c.review(valid_review(), "fresh", "T1", ["2+3=5"])
        self.assertTrue(c.gate([{"returncode": 0}], assessment))

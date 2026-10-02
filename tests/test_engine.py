import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion.config import initialize, load
from harness_fusion.engine import Engine, Halt
from test_contracts import valid_plan


class FakeAgent:
    def __init__(self, broken_first=False, bad_review=False, violation=False, fail_final=False, always_broken=False):
        self.calls = []
        self.generated = 0
        self.broken_first = broken_first
        self.bad_review = bad_review
        self.violation = violation
        self.fail_final = fail_final
        self.always_broken = always_broken

    def __call__(self, cfg, role, prompt, root, timeout):
        self.calls.append(role)
        request = json.loads(prompt[prompt.index("\n") + 1:])
        if role == "planner":
            result = valid_plan()
        elif role == "generator":
            self.generated += 1
            broken = self.always_broken or self.broken_first and self.generated == 1
            (root / "calculator.py").write_text("def add(a,b): return " + ("0" if broken else "a+b") + "\n")
            (root / "tests").mkdir(exist_ok=True)
            (root / "tests/test_calc.py").write_text(
                "import unittest\nfrom calculator import add\nclass Tests(unittest.TestCase):\n"
                " def test_add(self): self.assertEqual(add(2,3),5)\n")
            result = {"summary": "Calculator with executable acceptance test"}
        else:
            if self.bad_review:
                return {"response": "PASS", "seconds": 0}
            if self.violation:
                (root / "calculator.py").write_text("# evaluator edited existing file\n")
            failed = self.fail_final and request["task_id"] == "FINAL"
            result = {"token": request["token"], "task_id": request["task_id"],
                      "verdict": "FAIL" if failed else "PASS", "spec_score": 3, "test_score": 3,
                      "criteria": [{"criterion": x, "passed": not failed, "evidence": "tests/test_calc.py"}
                                   for x in request["task"]["acceptance"]],
                      "issues": ["Final integration issue"] if failed else []}
        return {"response": json.dumps(result), "seconds": 0}


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(self.root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다.")

    def run_engine(self, agent, resume=False):
        with redirect_stdout(io.StringIO()):
            return Engine(self.root, invoke=agent).run(resume)

    def state(self):
        return json.loads((self.root / ".fusion/state.json").read_text(encoding="utf-8"))

    def test_end_to_end_requires_final_review(self):
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 0)
        self.assertEqual(self.state()["status"], "DONE")
        self.assertEqual(agent.calls, ["planner", "generator", "evaluator", "evaluator"])

    def test_failed_tests_override_lying_reviewer_then_retry(self):
        agent = FakeAgent(broken_first=True)
        self.assertEqual(self.run_engine(agent), 0)
        self.assertEqual(agent.generated, 2)
        self.assertEqual(self.state()["attempts"]["T1"], 2)

    def test_bad_review_format_halts(self):
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        self.assertEqual(self.state()["status"], "HALTED")
        self.assertEqual(self.state()["completed"], [])

    def test_evaluator_edit_halts_even_preexisting_file(self):
        (self.root / "calculator.py").write_text("# existing dirty work")
        self.assertEqual(self.run_engine(FakeAgent(violation=True)), 2)
        self.assertIn("forbidden paths", self.state()["reason"])

    def test_repeated_failure_has_nonzero_exit(self):
        agent = FakeAgent(always_broken=True)
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.generated, 3)
        self.assertIn("retry budget", self.state()["reason"])

    def test_final_failure_is_not_done(self):
        self.assertEqual(self.run_engine(FakeAgent(fail_final=True)), 2)
        self.assertEqual(self.state()["last_failure"]["task"], "FINAL")

    def test_final_failure_resume_reopens_tasks(self):
        self.run_engine(FakeAgent(fail_final=True))
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent, resume=True), 0)
        self.assertEqual(agent.generated, 1)
        self.assertNotIn("planner", agent.calls)

    def test_resume_after_protocol_error(self):
        self.run_engine(FakeAgent(bad_review=True))
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent, resume=True), 0)
        self.assertNotIn("planner", agent.calls)

    def test_changed_requirements_block_resume(self):
        self.run_engine(FakeAgent())
        (self.root / "docs/PRD.md").write_text("New requirement")
        with self.assertRaises(Halt):
            self.run_engine(FakeAgent(), resume=True)

    def test_changed_done_code_blocks_stale_completion(self):
        self.run_engine(FakeAgent())
        (self.root / "calculator.py").write_text("# changed after verification")
        with self.assertRaises(Halt):
            self.run_engine(FakeAgent(), resume=True)

    def test_no_checks_is_config_error(self):
        path = self.root / "harness.toml"
        path.write_text(path.read_text().split("[[checks]]")[0])
        with self.assertRaises(ValueError):
            load(self.root)

    def test_init_never_overwrites_instructions(self):
        old = (self.root / "AGENTS.md").read_bytes()
        with self.assertRaises(ValueError):
            initialize(self.root)
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), old)

    def test_total_timeout_blocks_completion(self):
        engine = Engine(self.root, invoke=FakeAgent())
        engine.deadline = 0
        with self.assertRaises(Halt):
            engine.time_left(10)

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion.config import initialize, load
from harness_fusion.engine import Engine, Halt, render_plan
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

    def test_templates_pin_default_models_per_backend(self):
        with tempfile.TemporaryDirectory() as name:
            codex = Path(name) / "codex"
            claude = Path(name) / "claude"
            initialize(codex, backend="codex", goal="정수 두 개를 더하는 add 함수를 작성한다.")
            initialize(claude, backend="claude", goal="정수 두 개를 더하는 add 함수를 작성한다.")
            for role, agent in load(codex)["agents"].items():
                expected = "claude-sonnet-5-5" if role == "planner" else "gpt-6.1-sol"
                self.assertEqual(agent["model"], expected, role)
            for role, agent in load(claude)["agents"].items():
                self.assertEqual(agent["model"], "claude-sonnet-5-5", role)

    def test_total_timeout_blocks_completion(self):
        engine = Engine(self.root, invoke=FakeAgent())
        engine.deadline = 0
        with self.assertRaises(Halt):
            engine.time_left(10)


@unittest.skipUnless(shutil.which("git"), "git is required")
class GitPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        initialize(self.root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다.")

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.root, check=True,
                              capture_output=True, text=True).stdout

    def run_engine(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = Engine(self.root, invoke=FakeAgent()).run()
        return code, out.getvalue()

    def test_passed_tasks_are_committed_without_controls_and_pushed(self):
        bare = Path(self.temp.name) / "remote.git"
        self.git("init", "-q", "--bare", str(bare), cwd=self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("remote", "add", "origin", str(bare))
        (self.root / ".env").write_text("SECRET=1\n")
        (self.root / "node_modules/pkg").mkdir(parents=True)
        (self.root / "node_modules/pkg/index.js").write_text("x\n")
        code, out = self.run_engine()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.git("log", "--format=%s").split("\n")[:2],
                         ["FINAL: Whole-project acceptance", "T1: Add"])
        tracked = self.git("ls-files").split()
        self.assertIn("calculator.py", tracked)
        self.assertIn("tests/test_calc.py", tracked)
        for never in ("harness.toml", "agents.toml", "AGENTS.md", ".env", "node_modules/pkg/index.js"):
            self.assertNotIn(never, tracked)
        self.assertFalse([p for p in tracked if p.startswith(".fusion/")])
        self.assertIn("T1: Add", self.git("--git-dir", str(bare), "log", "--format=%s", "HEAD"))
        self.assertIn("[T1] PASS: verdict PASS, spec 3/3, test 3/3, criteria 1/1, checks acceptance-tests=ok", out)
        self.assertIn("pushed to origin", out)

    def test_missing_repository_is_reported_not_fatal(self):
        code, out = self.run_engine()
        self.assertEqual(code, 0, out)
        self.assertIn("[T1] git: skipped: not a git repository", out)

    def test_failed_task_is_reported_with_reasons(self):
        out = io.StringIO()
        with redirect_stdout(out):
            Engine(self.root, invoke=FakeAgent(always_broken=True)).run()
        self.assertIn("[T1] FAIL", out.getvalue())
        self.assertIn("checks acceptance-tests=1", out.getvalue())

    def test_git_settings_validated(self):
        path = self.root / "harness.toml"
        base = path.read_text().split("[git]")[0]
        self.assertEqual(load(self.root)["git"], {"commit": True, "push": True})
        path.write_text(base)
        self.assertEqual(load(self.root)["git"], {"commit": False, "push": False})
        for bad in ("[git]\npush = true\n", "[git]\ncommit = \"yes\"\n", "[git]\nbranch = \"main\"\n"):
            path.write_text(base + bad)
            with self.assertRaises(ValueError):
                load(self.root)


class RenderPlanTests(unittest.TestCase):
    def test_summary_sentences_become_bullets_and_tasks_a_table(self):
        plan = {"summary": "첫 문장입니다. 둘째는 a|b를 씁니다.",
                "tasks": [{"id": "T1", "title": "A|B", "depends_on": [], "touch": ["src/**"], "acceptance": ["x"]},
                          {"id": "T2", "title": "C", "depends_on": ["T1"], "touch": ["a", "b"], "acceptance": ["y"]}]}
        text = render_plan(plan, ["T1"])
        self.assertIn("- 첫 문장입니다.\n- 둘째는 a|b를 씁니다.\n", text)
        self.assertIn("| T1 | A\|B | - | src/** | 완료 |", text)
        self.assertIn("| T2 | C | T1 | a, b | 대기 |", text)

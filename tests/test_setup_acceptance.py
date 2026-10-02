import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import filesystem as fs
from harness_fusion.config import initialize, load
from harness_fusion.contracts import ContractError
from harness_fusion.engine import Engine, Halt
from test_engine import FakeAgent

ACCEPTANCE_TEST = (
    "import unittest\nfrom calculator import add\n"
    "class AcceptanceTests(unittest.TestCase):\n"
    " def test_add(self):\n"
    "  self.assertEqual(add(1, 1), 2)\n"
    "  self.assertEqual(add(1, 2), add(2, 1))\n")


def add_toml(root, text):
    path = root / "harness.toml"
    path.write_text(path.read_text(encoding="utf-8") + "\n" + text, encoding="utf-8")


class Base(unittest.TestCase):
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

    def events(self):
        lines = (self.root / ".fusion/events.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]


class SetupTests(Base):
    def log_setup(self, name="prepare"):
        add_toml(self.root, f'[[setup]]\nname = "{name}"\n'
                            "command = [\"{python}\", \"-c\", 'open(\"setup.log\", \"a\").write(\"x\\\\n\")']\n")

    def test_setup_runs_before_planning(self):
        self.log_setup()

        class Agent(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                if role == "planner":
                    assert (root / "setup.log").is_file(), "setup must precede the planner"
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(Agent()), 0)
        self.assertEqual(self.state()["status"], "DONE")
        self.assertIn("setup", [e["kind"] for e in self.events()])

    def test_setup_is_not_repeated_on_resume(self):
        self.log_setup()
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        self.assertEqual((self.root / "setup.log").read_text().count("x"), 1)
        self.assertEqual(self.run_engine(FakeAgent(), resume=True), 0)
        self.assertEqual((self.root / "setup.log").read_text().count("x"), 1)

    def test_failed_setup_halts_before_any_agent(self):
        add_toml(self.root, '[[setup]]\nname = "install"\ncommand = ["{python}", "-c", "import sys; sys.exit(3)"]\n')
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.calls, [])
        self.assertEqual(self.state()["status"], "HALTED")
        self.assertIn("Setup 'install' failed", self.state()["reason"])
        self.assertFalse(self.state().get("setup_done"))

    def test_failed_setup_is_retried_on_resume_until_it_succeeds(self):
        add_toml(self.root, '[[setup]]\nname = "needs-ready"\n'
                            "command = [\"{python}\", \"-c\", 'import pathlib,sys; "
                            "sys.exit(0 if pathlib.Path(\"ready\").exists() else 3)']\n")
        self.assertEqual(self.run_engine(FakeAgent()), 2)
        (self.root / "ready").write_text("ok")
        self.assertEqual(self.run_engine(FakeAgent(), resume=True), 0)
        self.assertTrue(self.state()["setup_done"])

    def test_setup_timeout_halts(self):
        add_toml(self.root, '[[setup]]\nname = "slow"\ntimeout = 1\n'
                            'command = ["{python}", "-c", "import time; time.sleep(30)"]\n')
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.calls, [])
        self.assertIn("Setup 'slow' failed", self.state()["reason"])

    def test_setup_may_populate_excluded_dependency_folders(self):
        add_toml(self.root, '[[setup]]\nname = "deps"\ncommand = ["{python}", "-c", '
                            "'import pathlib; d=pathlib.Path(\"node_modules\"); d.mkdir(); (d/\"pkg.txt\").write_text(\"x\")']\n")
        self.assertEqual(self.run_engine(FakeAgent()), 0)

    def test_changed_setup_blocks_resume(self):
        self.log_setup()
        self.run_engine(FakeAgent(bad_review=True))
        self.log_setup("another")
        with self.assertRaises(Halt):
            self.run_engine(FakeAgent(), resume=True)

    def test_setup_requires_argument_array(self):
        add_toml(self.root, '[[setup]]\nname = "bad"\ncommand = "pip install -r requirements.txt"\n')
        with self.assertRaises(ContractError):
            load(self.root)

    def test_setup_rejects_unknown_keys_and_bad_timeout(self):
        add_toml(self.root, '[[setup]]\nname = "bad"\ncommand = ["x"]\nshell = true\n')
        with self.assertRaises(ContractError):
            load(self.root)
        initialize_dir = tempfile.TemporaryDirectory()
        self.addCleanup(initialize_dir.cleanup)
        other = Path(initialize_dir.name)
        initialize(other, goal="정수 두 개를 더하는 add 함수를 작성한다.")
        add_toml(other, '[[setup]]\nname = "bad"\ncommand = ["x"]\ntimeout = 0\n')
        with self.assertRaises(ContractError):
            load(other)


class AcceptanceTests(Base):
    def enable(self, with_test=True):
        add_toml(self.root, '[acceptance]\npath = "acceptance"\n')
        folder = self.root / "acceptance"
        folder.mkdir()
        (folder / "README.md").write_text("human-owned\n", encoding="utf-8")
        if with_test:
            (folder / "test_add.py").write_text(ACCEPTANCE_TEST, encoding="utf-8")

    def test_acceptance_check_is_added_automatically(self):
        self.enable()
        names = [c["name"] for c in load(self.root)["checks"]]
        self.assertIn("acceptance", names)
        self.assertEqual(load(self.root)["acceptance"], "acceptance")

    def test_unsafe_acceptance_paths_rejected(self):
        for bad in ("../outside", "/abs", ".fusion/x", ".git/hooks", ".", "a\\\\b"):
            with self.subTest(path=bad):
                path = self.root / "harness.toml"
                original = path.read_text(encoding="utf-8")
                add_toml(self.root, f"[acceptance]\npath = '{bad}'\n")
                with self.assertRaises(ContractError):
                    load(self.root)
                path.write_text(original, encoding="utf-8")

    def test_acceptance_passes_end_to_end(self):
        self.enable()
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 0)
        self.assertEqual(self.state()["status"], "DONE")
        self.assertIn("acceptance_digest", self.state())

    def test_missing_acceptance_folder_halts_before_agents(self):
        add_toml(self.root, '[acceptance]\npath = "acceptance"\n')
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.calls, [])
        self.assertIn("acceptance", self.state()["reason"].lower())

    def test_acceptance_folder_with_only_readme_halts(self):
        self.enable(with_test=False)
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.calls, [])

    def test_generator_cannot_weaken_acceptance_tests(self):
        self.enable()

        class Weakening(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                if role == "generator":
                    (root / "acceptance/test_add.py").write_text(
                        "import unittest\nclass T(unittest.TestCase):\n def test_x(self): pass\n")
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(Weakening()), 2)
        self.assertEqual(self.state()["status"], "HALTED")
        self.assertIn("acceptance/test_add.py", self.state()["reason"])
        self.assertEqual(self.state()["completed"], [])

    def test_plan_touch_cannot_unlock_acceptance_folder(self):
        self.enable()

        class Greedy(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                if role == "planner":
                    plan = {"summary": "Calculator", "tasks": [{"id": "T1", "title": "Add", "depends_on": [],
                            "touch": ["calculator.py", "tests/**", "acceptance/**"], "acceptance": ["2+3=5"]}]}
                    return {"response": json.dumps(plan), "seconds": 0}
                if role == "generator":
                    (root / "acceptance/test_add.py").write_text(
                        "import unittest\nclass T(unittest.TestCase):\n def test_x(self): pass\n")
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(Greedy()), 2)
        self.assertIn("forbidden paths: acceptance/test_add.py", self.state()["reason"])

    def test_generator_cannot_add_or_delete_acceptance_files(self):
        self.enable()

        class Tampering(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                if role == "generator":
                    (root / "acceptance/test_extra.py").write_text("x = 1\n")
                    (root / "acceptance/README.md").unlink()
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(Tampering()), 2)
        self.assertIn("acceptance/", self.state()["reason"])

    def test_edit_between_runs_blocks_resume(self):
        self.enable()
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        (self.root / "acceptance/test_add.py").write_text(
            ACCEPTANCE_TEST.replace("add(1, 1), 2", "add(1, 1), 3"), encoding="utf-8")
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent, resume=True), 2)
        self.assertEqual(agent.calls, [])
        self.assertIn("Acceptance tests changed", self.state()["reason"])

    def test_failing_acceptance_test_overrides_passing_review(self):
        self.enable()
        (self.root / "acceptance/test_add.py").write_text(
            ACCEPTANCE_TEST.replace("add(1, 1), 2", "add(1, 1), 3"), encoding="utf-8")
        agent = FakeAgent()
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(agent.generated, 3)
        self.assertEqual(self.state()["completed"], [])

    def test_all_skipped_acceptance_tests_cannot_pass(self):
        self.enable()
        (self.root / "acceptance/test_add.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n @unittest.skip('x')\n def test_x(self): pass\n",
            encoding="utf-8")
        self.assertEqual(self.run_engine(FakeAgent()), 2)
        self.assertEqual(self.state()["completed"], [])

    def test_prompt_tells_agents_the_folder_is_read_only(self):
        self.enable()
        seen = []

        class Spy(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                seen.append(prompt)
                return super().__call__(cfg, role, prompt, root, timeout)

        self.run_engine(Spy())
        self.assertTrue(all('"acceptance_path": "acceptance"' in p for p in seen))

    def test_init_creates_acceptance_folder_without_overwriting(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        root = Path(other.name) / "project"
        initialize(root, goal="정수 두 개를 더하는 add 함수를 작성한다.", acceptance=True)
        self.assertTrue((root / "acceptance/README.md").is_file())
        self.assertEqual(load(root)["acceptance"], "acceptance")
        engine_agent = FakeAgent()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Engine(root, invoke=engine_agent).run(False), 2)
        self.assertEqual(engine_agent.calls, [])
        occupied = Path(other.name) / "occupied"
        (occupied / "acceptance").mkdir(parents=True)
        (occupied / "acceptance/mine.py").write_text("keep", encoding="utf-8")
        with self.assertRaises(ContractError):
            initialize(occupied, goal="정수 두 개를 더하는 add 함수를 작성한다.", acceptance=True)
        self.assertEqual((occupied / "acceptance/mine.py").read_text(), "keep")


class LockedPathTests(unittest.TestCase):
    def test_violations_include_locked_prefix_even_inside_touch(self):
        changed = ["acceptance/test_a.py", "src/a.py"]
        self.assertEqual(fs.violations(changed, "generator", ["**/*.py", "src/**", "acceptance/**"],
                                       locked=("acceptance/",)), ["acceptance/test_a.py"])

    def test_tree_files_and_digest_follow_content(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "acceptance").mkdir()
            (root / "acceptance/test_a.py").write_text("a")
            (root / "other.txt").write_text("x")
            before = fs.digest(fs.tree_files(root, "acceptance"))
            self.assertEqual(list(fs.tree_files(root, "acceptance")), ["acceptance/test_a.py"])
            (root / "other.txt").write_text("y")
            self.assertEqual(before, fs.digest(fs.tree_files(root, "acceptance")))
            (root / "acceptance/test_a.py").write_text("b")
            self.assertNotEqual(before, fs.digest(fs.tree_files(root, "acceptance")))


if __name__ == "__main__":
    unittest.main()

import io
import json
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import filesystem as fs
from harness_fusion.config import agents_template, initialize, load, watch_settings
from harness_fusion.contracts import ContractError
from harness_fusion.engine import Engine
from test_engine import FakeAgent


def set_watch(root, ignore):
    """Replace the [watch] table written by init."""
    text = (root / "harness.toml").read_text(encoding="utf-8")
    start = text.index("[watch]")
    end = text.index("\n\n", start)
    entries = ", ".join(f'"{x}"' for x in ignore)
    (root / "harness.toml").write_text(text[:start] + f"[watch]\nignore = [{entries}]" + text[end:], encoding="utf-8")


class WatchSettingsTests(unittest.TestCase):
    def test_missing_section_ignores_nothing(self):
        self.assertEqual(watch_settings(None), {"ignore": []})

    def test_hidden_tool_folders_allowed(self):
        self.assertEqual(watch_settings({"ignore": [".omc/", ".expo/cache/"]})["ignore"], [".omc/", ".expo/cache/"])

    def test_sources_controls_and_skills_rejected(self):
        for entry in ["src/", "docs/", ".claude/", ".agents/skills/", ".git/", ".fusion/", ".env/", ".omc", ".x/*/", "../.omc/"]:
            with self.subTest(entry=entry), self.assertRaises(ContractError):
                watch_settings({"ignore": [entry]})

    def test_acceptance_folder_cannot_be_ignored(self):
        with self.assertRaises(ContractError):
            watch_settings({"ignore": [".acceptance/"]}, acceptance=".acceptance/tests")

    def test_unknown_keys_rejected(self):
        with self.assertRaises(ContractError):
            watch_settings({"ignore": [], "extra": 1})


class SnapshotIgnoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_ignored_folder_changes_are_invisible(self):
        (self.root / ".omc").mkdir()
        (self.root / "app.py").write_text("x")
        before = fs.snapshot(self.root, (".omc/",))
        (self.root / ".omc/state.json").write_text("hook wrote this")
        self.assertEqual(fs.changes(before, fs.snapshot(self.root, (".omc/",))), [])
        (self.root / "app.py").write_text("y")
        self.assertEqual(fs.changes(before, fs.snapshot(self.root, (".omc/",))), ["app.py"])

    def test_prefix_does_not_match_similar_names(self):
        (self.root / ".omc-real").mkdir()
        (self.root / ".omc-real/file").write_text("x")
        self.assertIn(".omc-real/file", fs.snapshot(self.root, (".omc/",)))


class InitTemplateTests(unittest.TestCase):
    def test_new_project_lists_every_backend_and_watches_tool_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            initialize(root, backend="agy", goal="add 함수를 만들고 2+3=5를 테스트한다. 완료 기준: 테스트 통과")
            agents = (root / "agents.toml").read_text(encoding="utf-8")
            for backend in ('"agy"', '"claude"', '"codex"'):
                self.assertIn(f"backend = {backend}", agents)
            self.assertEqual(load(root)["watch"]["ignore"], [".omc/", ".expo/"])

    def test_menu_is_comments_only(self):
        parsed = tomllib.loads(agents_template("claude"))
        self.assertEqual(parsed["planner"]["backend"], "claude")
        self.assertEqual(set(parsed), {"planner", "generator", "evaluator", "bootstrap"})


class EngineWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(self.root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다.")

    def run_engine(self, agent):
        with redirect_stdout(io.StringIO()):
            return Engine(self.root, invoke=agent).run(False)

    def test_tool_state_written_by_every_role_does_not_halt(self):
        class HookNoise(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                (root / ".omc").mkdir(exist_ok=True)
                (root / ".omc/idle-notif-cooldown.json").write_text(json.dumps({"role": role, "n": len(self.calls)}))
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(HookNoise()), 0)
        state = json.loads((self.root / ".fusion/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "DONE")

    def test_without_watch_the_same_noise_halts(self):
        set_watch(self.root, [])

        class HookNoise(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                (root / ".omc").mkdir(exist_ok=True)
                (root / ".omc/noise.json").write_text(str(len(self.calls)))
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(HookNoise()), 2)

    def test_source_edits_by_evaluator_still_halt(self):
        self.assertEqual(self.run_engine(FakeAgent(violation=True)), 2)


if __name__ == "__main__":
    unittest.main()

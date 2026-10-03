import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import cli, filesystem as fs
from harness_fusion import config
from harness_fusion.config import default_agents, initialize, load
from harness_fusion.contracts import ContractError
from harness_fusion.engine import Engine, Halt
from harness_fusion.providers import command_for
from test_engine import FakeAgent

GOAL = "정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다."

THREE_MODELS = '''[planner]
backend = "codex"
model = "plan-model"
effort = "high"

[generator]
backend = "claude"
model = "gen-model"
effort = "low"

[evaluator]
backend = "codex"
model = "eval-model"
effort = "max"
'''

LEGACY_AGENTS = '''
[agents.planner]
backend = "codex"
model = "legacy-plan"

[agents.generator]
backend = "claude"

[agents.evaluator]
backend = "codex"
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(self.root, goal=GOAL)

    def run_engine(self, agent, resume=False):
        with redirect_stdout(io.StringIO()):
            return Engine(self.root, invoke=agent).run(resume)


class FileLayoutTests(Base):
    def test_init_writes_agents_file_and_keeps_agents_out_of_harness_toml(self):
        self.assertTrue((self.root / "agents.toml").is_file())
        self.assertNotIn("[agents", (self.root / "harness.toml").read_text(encoding="utf-8"))
        text = (self.root / "agents.toml").read_text(encoding="utf-8")
        for role in ("planner", "generator", "evaluator"):
            self.assertIn(f"[{role}]", text)

    def test_template_values_load(self):
        expected = default_agents("codex")
        self.assertEqual(load(self.root)["agents"], {r: expected[r] for r in ("planner", "generator", "evaluator")})
        self.assertEqual(load(self.root)["bootstrap"], expected["bootstrap"])

    def test_uniform_template_uses_one_backend_for_every_role(self):
        other = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(other.cleanup)
        initialize(Path(other.name) / "p", backend="codex", goal=GOAL, uniform=True)
        generator = default_agents("codex")["generator"]
        for role, agent in load(Path(other.name) / "p")["agents"].items():
            self.assertEqual(agent, generator, role)

    def test_defaults_file_is_the_single_source_for_new_projects(self):
        other = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(other.cleanup)
        custom = Path(other.name) / "defaults.toml"
        custom.write_text('[models]\ncodex = "c-model"\nclaude = "k-model"\n'
                          '[planner]\nbackend = "init"\neffort = "low"\n'
                          '[generator]\nbackend = "claude"\nmodel = "pinned"\n'
                          '[evaluator]\nbackend = "init"\neffort = "max"\n'
                          '[bootstrap]\nbackend = "claude"\n', encoding="utf-8")
        original = config.DEFAULT_AGENTS
        config.DEFAULT_AGENTS = custom
        self.addCleanup(setattr, config, "DEFAULT_AGENTS", original)
        initialize(Path(other.name) / "p", backend="codex", goal=GOAL)
        loaded = load(Path(other.name) / "p")
        self.assertEqual(loaded["agents"], {"planner": {"backend": "codex", "model": "c-model", "effort": "low"},
                                            "generator": {"backend": "claude", "model": "pinned"},
                                            "evaluator": {"backend": "codex", "model": "c-model", "effort": "max"}})
        self.assertEqual(loaded["bootstrap"], {"backend": "claude", "model": "k-model"})

    def test_each_agent_can_use_its_own_backend_model_and_effort(self):
        (self.root / "agents.toml").write_text(THREE_MODELS, encoding="utf-8")
        agents = load(self.root)["agents"]
        self.assertEqual([agents[r]["model"] for r in ("planner", "generator", "evaluator")],
                         ["plan-model", "gen-model", "eval-model"])
        self.assertEqual([agents[r]["effort"] for r in ("planner", "generator", "evaluator")],
                         ["high", "low", "max"])
        self.assertEqual(command_for(agents["generator"], "generator")[command_for(agents["generator"], "generator").index("--model") + 1],
                         "gen-model")

    def test_legacy_harness_toml_agents_still_work(self):
        (self.root / "agents.toml").unlink()
        path = self.root / "harness.toml"
        path.write_text(path.read_text(encoding="utf-8") + LEGACY_AGENTS, encoding="utf-8")
        agents = load(self.root)["agents"]
        self.assertEqual(agents["planner"]["model"], "legacy-plan")
        self.assertEqual(agents["generator"]["backend"], "claude")

    def test_defining_agents_in_both_places_is_rejected(self):
        path = self.root / "harness.toml"
        path.write_text(path.read_text(encoding="utf-8") + LEGACY_AGENTS, encoding="utf-8")
        with self.assertRaises(ContractError) as caught:
            load(self.root)
        self.assertIn("agents.toml", str(caught.exception))

    def test_missing_role_unknown_role_and_unknown_key_are_rejected(self):
        bad = {
            "missing evaluator": '[planner]\nbackend = "codex"\n[generator]\nbackend = "codex"\n',
            "unknown role": THREE_MODELS + '\n[reviewer]\nbackend = "codex"\n',
            "unknown key": THREE_MODELS.replace('effort = "high"', 'temperature = 1'),
            "unknown backend": THREE_MODELS.replace('backend = "claude"', 'backend = "gemini"'),
        }
        for name, text in bad.items():
            with self.subTest(name):
                (self.root / "agents.toml").write_text(text, encoding="utf-8")
                with self.assertRaises(ContractError):
                    load(self.root)

    def test_effort_rules_apply_in_agents_file(self):
        (self.root / "agents.toml").write_text(THREE_MODELS.replace('"max"', '"ultra"'), encoding="utf-8")
        with self.assertRaises(ContractError):
            load(self.root)

    def test_init_does_not_overwrite_an_existing_agents_file(self):
        other = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(other.cleanup)
        root = Path(other.name)
        (root / "agents.toml").write_text("# mine\n", encoding="utf-8")
        with self.assertRaises(ContractError):
            initialize(root, goal=GOAL)
        self.assertEqual((root / "agents.toml").read_text(encoding="utf-8"), "# mine\n")


class ProtectionAndResumeTests(Base):
    def test_agents_file_is_protected_from_every_role(self):
        self.assertEqual(fs.violations(["agents.toml"], "generator", ["*.toml", "**"]), ["agents.toml"])
        self.assertEqual(fs.violations(["agents.toml"], "evaluator", []), ["agents.toml"])

    def test_generator_cannot_swap_models(self):
        class Tampering(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                if role == "generator":
                    (root / "agents.toml").write_text(THREE_MODELS, encoding="utf-8")
                return super().__call__(cfg, role, prompt, root, timeout)

        self.assertEqual(self.run_engine(Tampering()), 2)
        state = json.loads((self.root / ".fusion/state.json").read_text(encoding="utf-8"))
        self.assertIn("agents.toml", state["reason"])

    def test_changing_agents_file_blocks_resume(self):
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        (self.root / "agents.toml").write_text(THREE_MODELS, encoding="utf-8")
        with self.assertRaises(Halt):
            self.run_engine(FakeAgent(), resume=True)

    def test_unchanged_agents_file_allows_resume(self):
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        self.assertEqual(self.run_engine(FakeAgent(), resume=True), 0)

    def test_events_record_each_agents_model_and_effort(self):
        (self.root / "agents.toml").write_text(THREE_MODELS, encoding="utf-8")
        self.assertEqual(self.run_engine(FakeAgent()), 0)
        lines = (self.root / ".fusion/events.jsonl").read_text(encoding="utf-8").splitlines()
        seen = {(e["role"], e["model"], e["effort"]) for e in map(json.loads, lines) if e["kind"] == "agent"}
        self.assertEqual(seen, {("planner", "plan-model", "high"), ("generator", "gen-model", "low"),
                                ("evaluator", "eval-model", "max")})

    def test_doctor_says_where_agents_are_defined(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.doctor(self.root)
        self.assertIn("agents.toml", out.getvalue())


if __name__ == "__main__":
    unittest.main()

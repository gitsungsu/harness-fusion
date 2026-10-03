import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import cli, config
from harness_fusion.config import default_agents, initialize, load, prd_warnings
from harness_fusion.contracts import ContractError
from harness_fusion.engine import Engine
from harness_fusion.providers import command_for
from test_engine import FakeAgent

GOAL = "정수 두 개를 더하는 add 함수를 작성한다."


def set_effort(root, role, value, backend=None):
    path = root / "agents.toml"
    text = path.read_text(encoding="utf-8")
    header = f"[{role}]\n"
    start = text.index(header) + len(header)
    end = text.index("\n[", start) if "\n[" in text[start:] else len(text)
    block = [line for line in text[start:end].splitlines() if not line.startswith("effort")]
    if backend:
        block = [f'backend = "{backend}"'] + [x for x in block if not x.startswith("backend")]
    block.append(f'effort = "{value}"' if value is not None else "")
    path.write_text(text[:start] + "\n".join(block) + "\n" + text[end:], encoding="utf-8")


class EffortConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_template_efforts_per_role(self):
        for backend in ("codex", "claude"):
            with self.subTest(backend=backend):
                root = self.root / backend
                initialize(root, backend=backend, goal=GOAL)
                efforts = {role: agent["effort"] for role, agent in load(root)["agents"].items()}
                defaults = default_agents(backend)
                self.assertEqual(efforts, {role: defaults[role]["effort"] for role in efforts})

    def test_accepts_documented_values(self):
        initialize(self.root / "p", backend="codex", goal=GOAL)
        for value in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(value=value):
                set_effort(self.root / "p", "planner", value)
                self.assertEqual(load(self.root / "p")["agents"]["planner"]["effort"], value)

    def test_rejects_unknown_non_string_and_delegating_values(self):
        initialize(self.root / "p", backend="codex", goal=GOAL)
        for bad in ("turbo", "ultra", "Medium", ""):
            with self.subTest(value=bad):
                set_effort(self.root / "p", "planner", bad)
                with self.assertRaises(ContractError):
                    load(self.root / "p")
        path = self.root / "p/agents.toml"
        path.write_text(path.read_text(encoding="utf-8").replace('effort = "', "effort = 3 # ", 1), encoding="utf-8")
        with self.assertRaises(ContractError):
            load(self.root / "p")

    def test_ultra_is_rejected_because_it_delegates_to_subagents(self):
        initialize(self.root / "p", backend="codex", goal=GOAL)
        set_effort(self.root / "p", "planner", "ultra")
        with self.assertRaises(ContractError) as caught:
            load(self.root / "p")
        self.assertIn("subagent", str(caught.exception).lower())

    def test_effort_is_not_valid_for_command_backend(self):
        initialize(self.root / "p", backend="codex", goal=GOAL)
        path = self.root / "p/agents.toml"
        text = path.read_text(encoding="utf-8")
        start = text.index("[planner]")
        end = text.index("[generator]")
        path.write_text(text[:start] + '[planner]\nbackend = "command"\ncommand = ["x"]\neffort = "low"\n\n'
                        + text[end:], encoding="utf-8")
        with self.assertRaises(ContractError):
            load(self.root / "p")


class EffortCommandTests(unittest.TestCase):
    def test_codex_passes_effort_as_config_override_before_stdin_marker(self):
        command = command_for({"backend": "codex", "model": "gpt-6.1-sol", "effort": "high"}, "planner", "/tmp/out")
        self.assertIn("model_reasoning_effort=\"high\"", command)
        self.assertEqual(command[command.index("model_reasoning_effort=\"high\"") - 1], "-c")
        self.assertEqual(command[-1], "-")
        self.assertIn("--model", command)

    def test_claude_passes_effort_flag(self):
        command = command_for({"backend": "claude", "effort": "xhigh"}, "generator")
        self.assertEqual(command[command.index("--effort") + 1], "xhigh")

    def test_no_effort_means_no_flag(self):
        self.assertNotIn("--effort", command_for({"backend": "claude"}, "planner"))
        self.assertFalse(any("reasoning_effort" in x for x in command_for({"backend": "codex"}, "planner", "/tmp/o")))

    def test_permission_flags_unchanged(self):
        command = command_for({"backend": "codex", "effort": "low"}, "generator", "/tmp/o")
        self.assertIn("workspace-write", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)


class EffortEventTests(unittest.TestCase):
    def test_events_record_effort(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name)
            initialize(root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다.")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(Engine(root, invoke=FakeAgent()).run(False), 0)
            lines = (root / ".fusion/events.jsonl").read_text(encoding="utf-8").splitlines()
            agents = [json.loads(x) for x in lines if '"kind": "agent"' in x]
            self.assertTrue(agents)
            defaults = default_agents("codex")
            self.assertEqual({(e["role"], e["effort"]) for e in agents},
                             {(role, defaults[role]["effort"]) for role in ("planner", "generator", "evaluator")})


class PrdTests(unittest.TestCase):
    def test_template_has_required_sections_and_still_blocks_a_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name)
            initialize(root)
            prd = (root / "docs/PRD.md").read_text(encoding="utf-8")
            for heading in ("목표", "입력과 출력", "완료 기준", "테스트 방법"):
                self.assertIn(heading, prd)
            agent = FakeAgent()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(Engine(root, invoke=agent).run(False), 2)
            self.assertEqual(agent.calls, [])

    def test_complete_prd_has_no_warnings(self):
        text = "# 요구사항\n\n## 완료 기준\n- add(2,3)==5\n\n## 테스트 방법\n- unittest\n"
        self.assertEqual(prd_warnings(text), [])

    def test_missing_sections_are_reported(self):
        self.assertEqual(len(prd_warnings("add 함수를 만든다. 충분히 긴 문장입니다.")), 2)
        self.assertEqual(len(prd_warnings("완료 기준: 2+3=5")), 1)
        self.assertEqual(len(prd_warnings("테스트는 unittest. add 함수를 만든다.")), 1)

    def test_unfilled_template_is_reported_by_doctor(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name)
            initialize(root, backend="codex")
            self.assertTrue(any("TODO" in w for w in prd_warnings((root / "docs/PRD.md").read_text(encoding="utf-8"))))
            out = io.StringIO()
            with redirect_stdout(out):
                cli.doctor(root)
            self.assertIn("prd: WARNING", out.getvalue())
            self.assertIn("TODO", out.getvalue())

    def test_english_wording_is_recognized(self):
        self.assertEqual(prd_warnings("Acceptance criteria: add(2,3)==5. Tests use unittest."), [])

    def test_warning_does_not_block_a_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name)
            initialize(root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 확인한다.")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(Engine(root, invoke=FakeAgent()).run(False), 0)
            self.assertIn("WARNING", out.getvalue())
            self.assertIn("PRD", out.getvalue())

    def test_doctor_reports_prd_warnings_without_failing(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name)
            initialize(root, backend="codex", goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 확인한다.")
            out = io.StringIO()
            with redirect_stdout(out):
                cli.doctor(root)
            self.assertIn("prd:", out.getvalue())


if __name__ == "__main__":
    unittest.main()

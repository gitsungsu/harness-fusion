import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import bootstrap, cli
from harness_fusion.config import initialize, load
from harness_fusion.contracts import ContractError

GOAL = "정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 확인한다."
COMPLETE_PRD = ("# 요구사항\n\n## 목표\nadd 함수를 만든다.\n\n## 입력과 출력\nadd(2,3)==5\n\n"
                "## 완료 기준\n- add(2,3)==5\n\n## 테스트 방법\n- unittest로 확인\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(self.root)  # unfilled PRD template, as a new user would have

    def run_bootstrap(self, runner):
        out = io.StringIO()
        with redirect_stdout(out):
            code = bootstrap.run(self.root, runner=runner)
        self.output = out.getvalue()
        return code


class ConfigTests(Base):
    def test_template_defines_bootstrap_as_claude_opus_high(self):
        self.assertEqual(load(self.root)["bootstrap"],
                         {"backend": "claude", "model": "claude-opus-5-5", "effort": "high"})

    def test_bootstrap_is_not_one_of_the_engine_roles(self):
        self.assertEqual(sorted(load(self.root)["agents"]), ["evaluator", "generator", "planner"])

    def test_projects_without_bootstrap_load_with_none(self):
        text = (self.root / "agents.toml").read_text(encoding="utf-8")
        (self.root / "agents.toml").write_text(text[:text.index("[bootstrap]")], encoding="utf-8")
        self.assertIsNone(load(self.root)["bootstrap"])

    def test_invalid_bootstrap_settings_are_rejected(self):
        original = (self.root / "agents.toml").read_text(encoding="utf-8")
        bad = {
            "codex cannot run an interactive interview": ('backend = "claude"', 'backend = "codex"'),
            "command backend": ('backend = "claude"', 'backend = "command"'),
            "ultra effort": ('effort = "high"\n', 'effort = "ultra"\n'),
            "unknown effort": ('effort = "high"\n', 'effort = "turbo"\n'),
            "unknown key": ('effort = "high"\n', 'effort = "high"\ncommand = ["x"]\n'),
        }
        for name, (old, new) in bad.items():
            with self.subTest(name):
                head, tail = original.split("[bootstrap]")
                (self.root / "agents.toml").write_text(head + "[bootstrap]" + tail.replace(old, new, 1),
                                                       encoding="utf-8")
                with self.assertRaises(ContractError):
                    load(self.root)


class CommandTests(Base):
    def command(self, **overrides):
        cfg = dict(load(self.root)["bootstrap"], **overrides)
        return bootstrap.command_for(cfg, "시작합니다")

    def test_uses_configured_model_and_effort(self):
        command = self.command()
        self.assertEqual(command[0], "claude")
        self.assertEqual(command[command.index("--model") + 1], "claude-opus-5-5")
        self.assertEqual(command[command.index("--effort") + 1], "high")

    def test_is_interactive_and_never_bypasses_permissions(self):
        command = self.command()
        for flag in ("-p", "--print", "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"):
            self.assertNotIn(flag, command)
        self.assertFalse(any("bypass" in part.lower() for part in command))

    def test_tools_are_limited_to_reading_and_writing_the_prd_only(self):
        command = self.command()
        tools = command[command.index("--tools") + 1].split(",")
        self.assertEqual(sorted(tools), ["Edit", "Glob", "Grep", "Read", "Write"])
        allowed = command[command.index("--allowedTools") + 1].split(",")
        self.assertIn("Write(docs/PRD.md)", allowed)
        self.assertIn("Edit(docs/PRD.md)", allowed)
        self.assertNotIn("Write", allowed)
        self.assertNotIn("Edit", allowed)
        self.assertFalse(any(t.startswith("Bash") for t in tools + allowed))

    def test_initial_prompt_is_the_first_argument_after_the_program(self):
        # --allowedTools takes a list; a trailing prompt would be swallowed as a tool name.
        self.assertEqual(self.command()[1], "시작합니다")

    def test_interview_instructions_cover_the_prd_sections_and_limits(self):
        command = self.command()
        prompt = command[command.index("--append-system-prompt") + 1]
        for word in ("목표", "입력과 출력", "완료 기준", "테스트 방법", "docs/PRD.md", "한 번에 하나", "TODO"):
            self.assertIn(word, prompt)


class RunTests(Base):
    def writer(self, text=COMPLETE_PRD, extra=None, returncode=0):
        calls = []

        def runner(argv, cwd):
            calls.append((argv, Path(cwd)))
            if text is not None:
                (Path(cwd) / "docs/PRD.md").write_text(text, encoding="utf-8")
            for name, content in (extra or {}).items():
                (Path(cwd) / name).write_text(content, encoding="utf-8")
            return returncode

        runner.calls = calls
        return runner

    def test_success_writes_only_the_prd(self):
        runner = self.writer()
        self.assertEqual(self.run_bootstrap(runner), 0)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][1], self.root.resolve())
        self.assertIn("doctor", self.output)
        self.assertEqual((self.root / "docs/PRD.md").read_text(encoding="utf-8"), COMPLETE_PRD)

    def test_runs_from_the_project_root_with_configured_model(self):
        runner = self.writer()
        self.run_bootstrap(runner)
        argv = runner.calls[0][0]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5-5")

    def test_other_changed_files_fail_the_run(self):
        runner = self.writer(extra={"calculator.py": "print('hi')\n"})
        self.assertEqual(self.run_bootstrap(runner), 2)
        self.assertIn("calculator.py", self.output)

    def test_changed_agents_file_fails_the_run(self):
        before = (self.root / "agents.toml").read_text(encoding="utf-8")
        runner = self.writer(extra={"agents.toml": before.replace("high", "low")})
        self.assertEqual(self.run_bootstrap(runner), 2)
        self.assertIn("agents.toml", self.output)

    def test_unchanged_prd_fails(self):
        self.assertEqual(self.run_bootstrap(self.writer(text=None)), 2)
        self.assertIn("not written", self.output.lower())

    def test_prd_with_todo_placeholders_fails(self):
        template = (self.root / "docs/PRD.md").read_text(encoding="utf-8")
        self.assertEqual(self.run_bootstrap(self.writer(text=template + "\n추가 메모\n")), 2)
        self.assertIn("TODO", self.output)

    def test_nonzero_exit_of_claude_fails_even_if_prd_was_written(self):
        self.assertEqual(self.run_bootstrap(self.writer(returncode=1)), 2)

    def test_prd_quality_warnings_are_shown_but_do_not_fail(self):
        self.assertEqual(self.run_bootstrap(self.writer(text="add 함수를 만든다. 입력은 정수 두 개다.\n")), 0)
        self.assertIn("WARNING", self.output)

    def test_refuses_once_a_run_has_started(self):
        (self.root / ".fusion").mkdir()
        (self.root / ".fusion/state.json").write_text("{}", encoding="utf-8")
        runner = self.writer()
        self.assertEqual(self.run_bootstrap(runner), 2)
        self.assertEqual(runner.calls, [])
        self.assertIn("new project folder", self.output)

    def test_requires_a_bootstrap_section(self):
        text = (self.root / "agents.toml").read_text(encoding="utf-8")
        (self.root / "agents.toml").write_text(text[:text.index("[bootstrap]")], encoding="utf-8")
        runner = self.writer()
        self.assertEqual(self.run_bootstrap(runner), 2)
        self.assertEqual(runner.calls, [])
        self.assertIn("[bootstrap]", self.output)

    def test_missing_claude_executable_is_reported(self):
        def runner(argv, cwd):
            raise FileNotFoundError("claude")

        self.assertEqual(self.run_bootstrap(runner), 2)
        self.assertIn("claude", self.output)

    def test_prd_file_can_be_refined_when_it_already_has_content(self):
        (self.root / "docs/PRD.md").write_text("# 요구사항\n\n초안입니다. 완료 기준 없음.\n", encoding="utf-8")
        self.assertEqual(self.run_bootstrap(self.writer()), 0)


class CliTests(Base):
    def test_doctor_shows_the_bootstrap_agent_without_failing_when_claude_is_absent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            cli.doctor(self.root)
        self.assertIn("bootstrap: claude", out.getvalue())
        self.assertIn("claude-opus-5-5", out.getvalue())

    def test_prd_command_needs_an_interactive_terminal(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["prd", str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("interactive", out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()

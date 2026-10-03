import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness_fusion import cli, providers
from harness_fusion.config import default_agents, initialize, load
from harness_fusion.contracts import ContractError
from harness_fusion.providers import UsageLimitError, command_for, invoke

GOAL = "정수 두 개를 더하는 add 함수를 작성한다."


def envelope(**fields):
    base = {"conversation_id": "c", "status": "SUCCESS", "response": '{"ok": true}\n',
            "usage": {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 3, "total_tokens": 18}}
    base.update(fields)
    return json.dumps(base)


class CommandTests(unittest.TestCase):
    def test_roles_map_to_modes_and_never_bypass_permissions(self):
        for role, mode in (("planner", "plan"), ("evaluator", "plan"), ("generator", "accept-edits")):
            with self.subTest(role=role):
                command = command_for({"backend": "agy"}, role, prompt_file="/tmp/x/prompt.txt")
                self.assertEqual(command[command.index("--mode") + 1], mode)
                self.assertNotIn("--dangerously-skip-permissions", command)
                self.assertEqual(command[command.index("--output-format") + 1], "json")

    def test_model_and_effort_flags_are_optional(self):
        plain = command_for({"backend": "agy"}, "planner", prompt_file="/tmp/x/prompt.txt")
        self.assertNotIn("--model", plain)
        self.assertNotIn("--effort", plain)
        full = command_for({"backend": "agy", "model": "gemini-3.1-pro-high", "effort": "low"}, "planner",
                           prompt_file="/tmp/x/prompt.txt")
        self.assertEqual(full[full.index("--model") + 1], "gemini-3.1-pro-high")
        self.assertEqual(full[full.index("--effort") + 1], "low")

    def test_prompt_is_a_short_instruction_pointing_at_the_file(self):
        prompt_file = Path("/tmp/x/prompt.txt")
        command = command_for({"backend": "agy"}, "planner", prompt_file=prompt_file)
        flag = next(x for x in command if x.startswith("-p="))
        self.assertIn(str(prompt_file), flag)
        self.assertLess(len(flag), 400)
        self.assertEqual(command[command.index("--add-dir") + 1], str(prompt_file.parent))

    def test_executable_falls_back_to_gemini_bin_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as home:
            bin_dir = Path(home) / ".gemini" / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "agy.exe").write_text("", encoding="utf-8")
            (bin_dir / "agy").write_text("", encoding="utf-8")
            with patch.object(providers.shutil, "which", return_value=None), \
                    patch.object(providers.Path, "home", return_value=Path(home)):
                self.assertEqual(Path(providers.agy_executable()).parent, bin_dir)
            with patch.object(providers.shutil, "which", return_value="C:/tools/agy.exe"):
                self.assertEqual(providers.agy_executable(), "C:/tools/agy.exe")

    def test_missing_executable_keeps_a_reportable_name(self):
        with tempfile.TemporaryDirectory() as home, patch.object(providers.shutil, "which", return_value=None), \
                patch.object(providers.Path, "home", return_value=Path(home)):
            self.assertEqual(providers.agy_executable(), "agy")


class InvokeTests(unittest.TestCase):
    def run_invoke(self, stdout, returncode=0, stderr="", role="planner", cfg=None):
        seen = {}

        def fake(command, root, timeout, prompt, env):
            seen.update(command=command, prompt=prompt, env=env)
            flag = next(x for x in command if x.startswith("-p="))
            path = flag[len("-p=Read the file "):].split(" in full")[0]
            seen["file_text"] = Path(path).read_text(encoding="utf-8")
            return {"returncode": returncode, "stdout": stdout, "stderr": stderr, "seconds": 1}

        with tempfile.TemporaryDirectory() as root, patch.object(providers, "execute", side_effect=fake):
            result = invoke(cfg or {"backend": "agy"}, role, "BIG PROMPT 한글", Path(root), 10)
        return result, seen

    def test_prompt_travels_by_file_not_stdin(self):
        result, seen = self.run_invoke(envelope())
        self.assertEqual(seen["file_text"], "BIG PROMPT 한글")
        self.assertEqual(seen["prompt"], "")
        self.assertEqual(seen["env"]["HARNESS_ROLE"], "planner")
        self.assertEqual(result["response"], '{"ok": true}\n')

    def test_usage_is_reduced_to_harness_keys(self):
        result, _ = self.run_invoke(envelope())
        self.assertEqual(result["usage"], {"input_tokens": 10, "output_tokens": 5})

    def test_empty_response_with_denied_actions_is_a_contract_error(self):
        denied = envelope(response="", denied_actions=[{"action": "command", "display_name": "RunCommand"}])
        with self.assertRaises(ContractError) as caught:
            self.run_invoke(denied)
        self.assertIn("RunCommand", str(caught.exception))

    def test_non_success_status_is_a_contract_error(self):
        with self.assertRaises(ContractError):
            self.run_invoke(envelope(status="ERROR", response="boom"))

    def test_non_json_stdout_is_a_contract_error(self):
        with self.assertRaises(ContractError):
            self.run_invoke("plain text, not json")

    def test_limit_text_in_envelope_raises_usage_limit(self):
        with self.assertRaises(UsageLimitError):
            self.run_invoke(envelope(status="ERROR", response="Quota exceeded. Resets 5pm"))

    def test_nonzero_exit_with_limit_in_stdout_raises_usage_limit(self):
        with self.assertRaises(UsageLimitError) as caught:
            self.run_invoke("You've hit your usage limit, try again at 5pm", returncode=1)
        self.assertEqual(caught.exception.hint, "5pm")

    def test_other_nonzero_exit_is_a_plain_runtime_error(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_invoke("", returncode=3, stderr="crashed")
        self.assertNotIsInstance(caught.exception, UsageLimitError)
        self.assertIn("crashed", str(caught.exception))


class ConfigTests(unittest.TestCase):
    def test_agy_backend_initializes_and_loads(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name) / "p"
            initialize(root, backend="agy", goal=GOAL, uniform=True)
            agents = load(root)["agents"]
            defaults = default_agents("agy", uniform=True)
            for role in ("planner", "generator", "evaluator"):
                self.assertEqual(agents[role]["backend"], "agy")
                self.assertEqual(agents[role]["model"], defaults[role]["model"])
            self.assertTrue(agents["generator"]["model"])

    def test_agy_backend_initializes_all_roles_as_agy_without_uniform(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name) / "p"
            initialize(root, backend="agy", goal=GOAL, uniform=False)
            agents = load(root)["agents"]
            defaults = default_agents("agy", uniform=False)
            for role in ("planner", "generator", "evaluator"):
                self.assertEqual(agents[role]["backend"], "agy")
                self.assertEqual(agents[role]["model"], "gemini-3.8-flash")
                self.assertEqual(agents[role]["model"], defaults[role]["model"])

    def test_agy_backend_initializes_all_roles_as_agy_without_uniform(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name) / "p"
            initialize(root, backend="agy", goal=GOAL, uniform=False)
            agents = load(root)["agents"]
            defaults = default_agents("agy", uniform=False)
            for role in ("planner", "generator", "evaluator"):
                self.assertEqual(agents[role]["backend"], "agy")
                self.assertEqual(agents[role]["model"], "gemini-3.8-flash")
                self.assertEqual(agents[role]["model"], defaults[role]["model"])

    def test_bootstrap_still_requires_claude(self):
        from harness_fusion.config import bootstrap_settings
        with self.assertRaises(ContractError):
            bootstrap_settings({"backend": "agy"})


class CliTests(unittest.TestCase):
    def test_doctor_resolves_agy_executable(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as name:
            root = Path(name) / "p"
            initialize(root, backend="agy", goal=GOAL, uniform=True)
            out = io.StringIO()
            with patch.object(cli, "agy_executable", return_value="fake-agy"), \
                    patch.object(cli, "resolve_command", side_effect=lambda cmd: ["C:/bin/fake-agy.exe"]):
                with redirect_stdout(out):
                    result = cli.doctor(root)
            self.assertEqual(result, 0)
            output = out.getvalue()
            self.assertIn("planner: fake-agy -> C:/bin/fake-agy.exe", output)

    def test_bench_cli_accepts_agy_backend(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "runs"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(cli.main(["bench", "--backend", "agy", "--out", str(out)]), 0)
            text = buffer.getvalue()
            self.assertIn("slugify", text)


if __name__ == "__main__":
    unittest.main()

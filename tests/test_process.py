import os
import sys
import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_fusion.process import execute, resolve_command
from harness_fusion.providers import command_for, invoke


class ProcessTests(unittest.TestCase):
    def setUp(self):
        # A just-killed process can hold its cwd for a moment on Windows; that must not fail the test.
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_timeout_fails(self):
        result = execute([sys.executable, "-c", "import time; time.sleep(10)"], self.root, 0.1)
        self.assertEqual(result["returncode"], 124)

    def test_timeout_stops_descendant_process(self):
        heartbeat = self.root / "heartbeat"
        child = "import time\nfrom pathlib import Path\nwhile True:\n Path('heartbeat').write_text(str(time.time_ns()))\n time.sleep(.05)\n"
        parent = "import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', " + repr(child) + "]); time.sleep(30)"
        result = execute([sys.executable, "-c", parent], self.root, 2)
        self.assertEqual(result["returncode"], 124)
        self.assertTrue(heartbeat.is_file(), "Child must start before timeout")
        before = heartbeat.read_bytes()
        time.sleep(.3)
        self.assertEqual(heartbeat.read_bytes(), before, "Descendant survived cancellation")

    def test_missing_executable_fails(self):
        result = execute(["fusion-nonexistent-program-2099"], self.root, 1)
        self.assertEqual(result["returncode"], 127)

    def test_unicode_prompt_through_stdin(self):
        result = execute([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"], self.root, 5, "한국어 입력")
        self.assertEqual(result["stdout"], "한국어 입력")

    def test_zero_tests_fail_default_runner(self):
        (self.root / "tests").mkdir()
        result = execute([sys.executable, "-m", "harness_fusion.verification", "tests"], self.root, 5)
        self.assertNotEqual(result["returncode"], 0)
        self.assertIn("No tests discovered", result["stderr"])

    def test_all_skipped_tests_fail(self):
        (self.root / "tests").mkdir()
        (self.root / "tests/test_skipped.py").write_text(
            "import unittest\nclass Tests(unittest.TestCase):\n @unittest.skip('disabled')\n def test_skip(self): pass\n")
        result = execute([sys.executable, "-m", "harness_fusion.verification", "tests"], self.root, 5)
        self.assertNotEqual(result["returncode"], 0)

    def test_role_specific_provider_permissions(self):
        for role in ("planner", "evaluator"):
            command = command_for({"backend": "codex"}, role, "/tmp/result")
            self.assertIn("read-only", command)
            self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
            command = command_for({"backend": "claude"}, role)
            self.assertNotIn("Write", command[command.index("--tools") + 1])

    def test_failure_message_surfaces_error_lines_not_prompt_echo(self):
        code = ("import sys\n"
                "sys.stderr.write('prompt echo line\\n' * 400)\n"
                "sys.stderr.write('ERROR: usage limit reached\\n')\n"
                "sys.stderr.write('ERROR: usage limit reached\\n')\n"
                "sys.exit(1)\n")
        cfg = {"backend": "command", "command": [sys.executable, "-c", code]}
        with self.assertRaises(RuntimeError) as caught:
            invoke(cfg, "planner", "", self.root, 10)
        message = str(caught.exception)
        self.assertIn("ERROR: usage limit reached", message)
        self.assertEqual(message.count("usage limit reached"), 1)
        self.assertNotIn("prompt echo line", message)

    def test_output_limit_fails(self):
        result = execute([sys.executable, "-c", "print('x' * 1100000)"], self.root, 5)
        self.assertEqual(result["returncode"], 125)

    @unittest.skipUnless(os.name == "nt", "Windows npm shim resolution")
    def test_npm_shims_use_node_and_preserve_literal_arguments(self):
        for name, entry in (("codex", "@openai/codex/bin/codex.js"),
                            ("npm", "npm/bin/npm-cli.js")):
            shim = self.root / (name + ".cmd")
            shim.write_text("@echo must never run")
            script = self.root / "node_modules" / entry
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text("// entrypoint")
            node = self.root / "node.exe"
            node.touch()
            args = [name, "space argument", "&", "%PATH%", 'a"b']
            with patch("harness_fusion.process.shutil.which", return_value=str(shim)):
                self.assertEqual(resolve_command(args), [str(node), str(script), *args[1:]])

    @unittest.skipUnless(os.name == "nt", "Windows shell wrapper rejection")
    def test_unknown_batch_file_is_never_launched(self):
        shim = self.root / "custom.cmd"
        shim.write_text("@echo should not run")
        with patch("harness_fusion.process.subprocess.Popen") as popen:
            result = execute([str(shim)], self.root, 5)
        self.assertEqual(result["returncode"], 127)
        self.assertIn("shell wrapper", result["stderr"])
        popen.assert_not_called()

    def test_scripted_demo_and_resume(self):
        project = self.root / "demo"
        result = execute([sys.executable, "-m", "harness_fusion", "demo", str(project)], self.root, 30)
        self.assertEqual(result["returncode"], 0, result)
        state = json.loads((project / ".fusion/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["attempts"], {"T1": 2})
        self.assertEqual(state["status"], "DONE")
        events = [json.loads(line) for line in (project / ".fusion/events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([e["returncode"] for e in events if e["kind"] == "check"], [1, 0, 0])
        result = execute([sys.executable, "-m", "harness_fusion", "run", str(project), "--resume"], self.root, 30)
        self.assertEqual(result["returncode"], 0, result)

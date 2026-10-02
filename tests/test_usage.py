import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from harness_fusion import cli, providers
from harness_fusion.config import initialize
from harness_fusion.engine import Engine
from harness_fusion.providers import UsageLimitError, invoke, usage_limit_hint
from test_engine import FakeAgent

CODEX_LIMIT = ("ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
               "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 11:33 PM.")


class HintTests(unittest.TestCase):
    def test_detects_limit_and_release_time(self):
        self.assertEqual(usage_limit_hint(CODEX_LIMIT), "11:33 PM")

    def test_detects_limit_without_time(self):
        self.assertEqual(usage_limit_hint("Error: Usage limit reached for this plan"), "")

    def test_detects_claude_style_message(self):
        self.assertEqual(usage_limit_hint("You've hit your limit · resets 5pm"), "5pm")

    def test_unrelated_errors_are_not_limits(self):
        for text in ("", "SyntaxError: invalid syntax", "ERROR: model not found", "timeout after 900s"):
            with self.subTest(text=text):
                self.assertIsNone(usage_limit_hint(text))


class InvokeTests(unittest.TestCase):
    def test_nonzero_exit_with_limit_text_raises_usage_limit(self):
        code = f"import sys; sys.stderr.write({CODEX_LIMIT!r} + chr(10)); sys.exit(1)"
        cfg = {"backend": "command", "command": [sys.executable, "-c", code]}
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(UsageLimitError) as caught:
                invoke(cfg, "planner", "", Path(root), 10)
        self.assertEqual(caught.exception.hint, "11:33 PM")
        self.assertIn("planner", str(caught.exception))

    def test_other_failures_stay_plain_runtime_errors(self):
        cfg = {"backend": "command", "command": [sys.executable, "-c", "import sys; sys.exit(3)"]}
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError) as caught:
                invoke(cfg, "planner", "", Path(root), 10)
        self.assertNotIsInstance(caught.exception, UsageLimitError)

    def test_claude_error_envelope_with_limit_text(self):
        envelope = json.dumps({"is_error": True, "result": "Claude usage limit reached. Resets 5pm"})
        fake = {"returncode": 0, "stdout": envelope, "stderr": "", "seconds": 1}
        cfg = {"backend": "claude"}
        with tempfile.TemporaryDirectory() as root, patch.object(providers, "execute", return_value=fake):
            with self.assertRaises(UsageLimitError):
                invoke(cfg, "generator", "", Path(root), 10)

    def test_claude_nonzero_exit_limit_in_stdout(self):
        envelope = json.dumps({"is_error": True, "result": "You've hit your limit · resets 5pm"})
        fake = {"returncode": 1, "stdout": envelope, "stderr": "", "seconds": 1}
        with tempfile.TemporaryDirectory() as root, patch.object(providers, "execute", return_value=fake):
            with self.assertRaises(UsageLimitError) as caught:
                invoke({"backend": "claude"}, "generator", "", Path(root), 10)
        self.assertEqual(caught.exception.hint, "5pm")


class LimitAgent(FakeAgent):
    """Raises a usage limit on the first call of one role, then behaves normally."""

    def __init__(self, limited_role, **kwargs):
        super().__init__(**kwargs)
        self.limited_role = limited_role
        self.limit_hits = 1

    def __call__(self, cfg, role, prompt, root, timeout):
        if role == self.limited_role and self.limit_hits > 0:
            self.limit_hits -= 1
            self.calls.append(role)
            raise UsageLimitError(f"{role} hit the AI usage limit: {CODEX_LIMIT}", "11:33 PM")
        return super().__call__(cfg, role, prompt, root, timeout)


class UsageEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        initialize(self.root, goal="정수 두 개를 더하는 add 함수를 작성하고 2+3=5를 검사한다.")

    def run_engine(self, agent, resume=False):
        out = io.StringIO()
        with redirect_stdout(out):
            code = Engine(self.root, invoke=agent).run(resume)
        self.output = out.getvalue()
        return code

    def state(self):
        return json.loads((self.root / ".fusion/state.json").read_text(encoding="utf-8"))

    def test_limit_in_planner_halts_with_guidance_and_resumes(self):
        agent = LimitAgent("planner")
        self.assertEqual(self.run_engine(agent), 2)
        state = self.state()
        self.assertEqual(state["status"], "HALTED")
        self.assertEqual(state["halt_kind"], "usage_limit")
        self.assertEqual(state["retry_hint"], "11:33 PM")
        self.assertIn("USAGE_LIMIT", state["reason"])
        self.assertIn("11:33 PM", state["reason"])
        self.assertIn("--resume", state["reason"])
        self.assertIn("--resume", self.output)
        self.assertEqual(self.run_engine(agent, resume=True), 0)
        self.assertEqual(self.state()["status"], "DONE")
        self.assertIsNone(self.state().get("halt_kind"))

    def test_limit_does_not_consume_retry_budget(self):
        agent = LimitAgent("generator")
        for _ in range(5):
            agent.limit_hits = 1
            self.assertEqual(self.run_engine(agent, resume=bool(agent.calls and self.state())), 2)
            self.assertEqual(self.state()["attempts"]["T1"], 0)
            self.assertEqual(self.state()["halt_kind"], "usage_limit")
        self.assertEqual(self.run_engine(agent, resume=True), 0)
        self.assertEqual(self.state()["attempts"]["T1"], 1)
        self.assertNotIn("planner", agent.calls[1:])

    def test_limit_in_evaluator_is_resumable_and_not_success(self):
        agent = LimitAgent("evaluator")
        self.assertEqual(self.run_engine(agent), 2)
        self.assertEqual(self.state()["completed"], [])
        self.assertEqual(self.state()["attempts"]["T1"], 0)
        self.assertEqual(self.run_engine(agent, resume=True), 0)

    def test_ordinary_failure_is_not_marked_usage_limit(self):
        self.assertEqual(self.run_engine(FakeAgent(bad_review=True)), 2)
        self.assertNotEqual(self.state().get("halt_kind"), "usage_limit")
        self.assertNotIn("USAGE_LIMIT", self.state()["reason"])

    def test_status_summarizes_usage_per_role(self):
        class Metered(FakeAgent):
            def __call__(self, cfg, role, prompt, root, timeout):
                result = super().__call__(cfg, role, prompt, root, timeout)
                result["seconds"] = 2.5
                if role == "generator":
                    result["usage"] = {"input_tokens": 10, "output_tokens": 5}
                    result["cost_usd"] = 0.25
                return result

        self.assertEqual(self.run_engine(Metered()), 0)
        out = io.StringIO()
        with redirect_stdout(out):
            cli.status(self.root)
        usage = json.loads(out.getvalue())["usage"]
        self.assertEqual(usage["planner"]["calls"], 1)
        self.assertEqual(usage["evaluator"]["calls"], 2)
        self.assertEqual(usage["evaluator"]["seconds"], 5.0)
        self.assertEqual(usage["generator"]["input_tokens"], 10)
        self.assertEqual(usage["generator"]["output_tokens"], 5)
        self.assertEqual(usage["generator"]["cost_usd"], 0.25)
        self.assertNotIn("cost_usd", usage["planner"])

    def test_status_shows_limit_state(self):
        self.run_engine(LimitAgent("planner"))
        out = io.StringIO()
        with redirect_stdout(out):
            cli.status(self.root)
        data = json.loads(out.getvalue())
        self.assertEqual(data["halt_kind"], "usage_limit")
        self.assertEqual(data["retry_hint"], "11:33 PM")
        self.assertEqual(data["usage"]["planner"]["calls"], 1)


if __name__ == "__main__":
    unittest.main()

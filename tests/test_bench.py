import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness_fusion import bench, cli
from harness_fusion.config import default_agents
from test_engine import FakeAgent

REFERENCE = {
    "slugify": '''import re
import sys


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    result = slugify(sys.argv[1])
    if not result:
        print("empty slug", file=sys.stderr)
        sys.exit(1)
    print(result)
''',
    "wordcount": '''import collections
import re
import sys


def main(argv):
    if not argv:
        return 2
    top = 3
    if "--top" in argv:
        i = argv.index("--top")
        top = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    try:
        with open(argv[0], encoding="utf-8") as stream:
            text = stream.read()
    except OSError as exc:
        print(f"cannot read: {exc}", file=sys.stderr)
        return 2
    counts = collections.Counter(re.findall(r"[a-z0-9']+", text.lower()))
    for word, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:top]:
        print(word, count)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
''',
    "rpn": '''import sys


def evaluate(expression):
    stack = []
    for token in expression.split():
        if token in "+-*/" and len(token) == 1:
            if len(stack) < 2:
                raise ValueError("not enough operands")
            b, a = stack.pop(), stack.pop()
            stack.append({"+": a + b, "-": a - b, "*": a * b, "/": None}[token] if token != "/" else a / b)
        else:
            try:
                stack.append(float(token))
            except ValueError:
                raise ValueError(f"unknown token {token}") from None
    if len(stack) != 1:
        raise ValueError("expected exactly one value")
    return stack[0]


def main(argv):
    if not argv:
        return 2
    try:
        value = evaluate(argv[0])
    except (ValueError, ZeroDivisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(int(value) if value == int(value) else value)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
''',
}


class BenchAgent(FakeAgent):
    """Scripted agent that writes a chosen module for the benchmark case, plus a trivial passing test."""

    def __init__(self, case, source):
        super().__init__()
        self.case = case
        self.source = source

    def __call__(self, cfg, role, prompt, root, timeout):
        if role == "generator":
            (root / f"{self.case}.py").write_text(self.source, encoding="utf-8")
            (root / "tests").mkdir(exist_ok=True)
            (root / "tests/test_smoke.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8")
            return {"response": json.dumps({"summary": "scripted"}), "seconds": 0}
        return super().__call__(cfg, role, prompt, root, timeout)


def plan_for(case):
    return {"summary": case, "tasks": [{"id": "T1", "title": case, "depends_on": [],
            "touch": [f"{case}.py", "tests/**"], "acceptance": [f"{case} works"]}]}


class ScriptedBench(BenchAgent):
    def __call__(self, cfg, role, prompt, root, timeout):
        if role == "planner":
            return {"response": json.dumps(plan_for(self.case)), "seconds": 0}
        return super().__call__(cfg, role, prompt, root, timeout)


class CaseTests(unittest.TestCase):
    def test_three_cases_match_v2_names(self):
        self.assertEqual(sorted(bench.CASES), ["rpn", "slugify", "wordcount"])
        for name, case in bench.CASES.items():
            self.assertIn("python -m " + name, case["prd"])
            self.assertNotIn("uv run", case["prd"])
            self.assertIn("PROJECT_DIR", case["hidden"])

    def test_reference_solutions_pass_their_hidden_tests(self):
        for name, source in REFERENCE.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                project = Path(tmp)
                (project / f"{name}.py").write_text(source, encoding="utf-8")
                result = bench.grade(project, name)
                self.assertTrue(result["passed"], result["output"])

    def test_wrong_or_missing_solutions_fail_hidden_tests(self):
        for name in bench.CASES:
            with self.subTest(case=name), tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                project = Path(tmp)
                self.assertFalse(bench.grade(project, name)["passed"])
                (project / f"{name}.py").write_text("print('wrong')\n", encoding="utf-8")
                self.assertFalse(bench.grade(project, name)["passed"])


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / "runs"

    def records(self):
        lines = (self.out / "results.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def test_good_agent_is_done_and_graded_pass(self):
        with redirect_stdout(io.StringIO()):
            record = bench.run_case("slugify", self.out, backend="codex",
                                    invoke=ScriptedBench("slugify", REFERENCE["slugify"]))
        self.assertEqual(record["status"], "DONE")
        self.assertTrue(record["hidden_passed"])
        saved = self.records()[0]
        for key in ("case", "status", "exit_code", "cycles", "attempts", "seconds", "hidden_passed",
                    "agents", "prd_sha256", "project", "time", "usage"):
            self.assertIn(key, saved)
        self.assertEqual(saved["agents"]["planner"]["backend"], "codex")
        expected = default_agents("codex", uniform=True)["planner"]
        self.assertEqual(saved["agents"]["planner"]["model"], expected["model"])

    def test_false_pass_is_visible(self):
        with redirect_stdout(io.StringIO()):
            record = bench.run_case("rpn", self.out, backend="codex",
                                    invoke=ScriptedBench("rpn", "print('weak implementation')\n"))
        self.assertEqual(record["status"], "DONE")
        self.assertFalse(record["hidden_passed"])
        self.assertFalse(record["verified"])

    def test_halted_run_is_recorded_not_verified(self):
        agent = ScriptedBench("wordcount", REFERENCE["wordcount"])
        agent.bad_review = True
        with redirect_stdout(io.StringIO()):
            record = bench.run_case("wordcount", self.out, invoke=agent)
        self.assertEqual(record["status"], "HALTED")
        self.assertEqual(record["exit_code"], 2)
        self.assertFalse(record["verified"])

    def test_results_are_appended(self):
        with redirect_stdout(io.StringIO()):
            bench.run_case("slugify", self.out, invoke=ScriptedBench("slugify", REFERENCE["slugify"]))
            bench.run_case("slugify", self.out, invoke=ScriptedBench("slugify", REFERENCE["slugify"]))
        self.assertEqual(len(self.records()), 2)

    def test_unknown_case_rejected(self):
        with self.assertRaises(ValueError):
            bench.run_case("nope", self.out)


class CliTests(unittest.TestCase):
    def test_list_does_not_run_or_create_anything(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            out = Path(tmp) / "runs"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(cli.main(["bench", "--out", str(out)]), 0)
            text = buffer.getvalue()
            for name in bench.CASES:
                self.assertIn(name, text)
            self.assertIn("--run", text)
            self.assertFalse(out.exists())

    def test_unencodable_characters_never_crash_console_output(self):
        # Korean Windows consoles are cp949; model-written titles may contain characters it cannot encode.
        raw = io.BytesIO()
        console = io.TextIOWrapper(raw, encoding="cp949", errors="strict")
        original = sys.stdout
        sys.stdout = console
        try:
            self.assertEqual(cli.main(["bench"]), 0)
            print("T1 — plan → done \U0001F600", flush=True)
        finally:
            sys.stdout = original
        self.assertEqual(console.errors, "replace")
        self.assertIn(b"slugify", raw.getvalue())

    def test_run_requires_known_case_names(self):
        with self.assertRaises(SystemExit):
            cli.main(["bench", "--run", "--only", "nope"])


if __name__ == "__main__":
    unittest.main()

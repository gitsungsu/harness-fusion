"""Small fixed benchmark. Each case has a PRD and a hidden grading test the Generator never sees.

PRD behavior and grading assertions come from harness-v2's evals/ (slugify, wordcount, rpn).
Only the execution style changed: `uv run <entry>` -> `python -m <module>` and pytest -> unittest,
because Harness Fusion agents cannot install packages. Results are not interchangeable with v2 runs.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config
from .engine import Engine, usage_summary
from .process import execute

HEADER = '''import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


def run(*args):
    return subprocess.run([sys.executable, "-m", "MODULE", *args], cwd=os.environ["PROJECT_DIR"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)

'''

STACK = '''## 2. 기술 스택

- Python 3.11 이상, 표준 라이브러리만 사용한다 (외부 의존성 없음). 테스트는 unittest.
- 프로젝트 루트의 `MODULE.py`(또는 `MODULE/` 패키지의 `__main__.py`)로 구현하고, 프로젝트 루트에서 `python -m MODULE ...`으로 실행한다.
'''

SLUGIFY_PRD = '''# slugify — PRD

## 1. 개요

문장을 URL에 쓰는 슬러그로 바꾸는 명령줄 도구.

''' + STACK + '''
## 3. 요구사항

- 명령: `python -m slugify "<문장>"`. 결과를 한 줄로 표준 출력에 낸다.
- 규칙: 소문자로 바꾼다 → 영문 소문자·숫자가 아닌 문자 덩어리는 `-` 하나로 바꾼다 → 앞뒤의 `-`를 지운다.
  - `"Hello, World!"` → `hello-world`
  - `"  a  b  "` → `a-b`
  - `"C++ & Rust"` → `c-rust`
- 결과가 빈 문자열이면(예: `"!!!"`) 아무것도 출력하지 않고 표준 오류에 한 줄 이상 메시지를 낸 뒤 종료 코드 1로 끝난다.
- 인자가 없으면 종료 코드 2.

## 4. 범위 밖

- 유니코드 음역(한글 → 로마자), 길이 제한, 파일 입력.
'''

SLUGIFY_HIDDEN = HEADER + '''
class Hidden(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(run("Hello, World!").stdout.strip(), "hello-world")
        self.assertEqual(run("  a  b  ").stdout.strip(), "a-b")
        self.assertEqual(run("C++ & Rust").stdout.strip(), "c-rust")

    def test_empty_result_exits_1_with_message(self):
        r = run("!!!")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout.strip(), "")
        self.assertTrue(r.stderr.strip())

    def test_no_args_exits_2(self):
        self.assertEqual(run().returncode, 2)
'''

WORDCOUNT_PRD = '''# wordcount — PRD

## 1. 개요

텍스트 파일에서 가장 많이 나온 단어를 세어 보여 주는 명령줄 도구.

''' + STACK + '''
## 3. 요구사항

- 명령: `python -m wordcount <파일> [--top N]`. `--top` 기본값은 3.
- 단어: 소문자로 바꾼 뒤 정규식 `[a-z0-9']+`에 일치하는 덩어리.
- 출력: 많이 나온 순서, 횟수가 같으면 단어의 알파벳 순서로 상위 N개를 한 줄에 `단어 횟수`(공백 하나)로 출력한다.
  - 파일 내용 `the cat the dog The end`, `--top 3` → `the 3`, `cat 1`, `dog 1` (세 줄)
- 파일이 없으면 표준 오류에 메시지를 내고 종료 코드 2.
- 단어가 하나도 없는 파일은 아무것도 출력하지 않고 종료 코드 0.

## 4. 범위 밖

- 여러 파일, 불용어 제거, 한글 단어.
'''

WORDCOUNT_HIDDEN = HEADER + '''
def lines(result):
    return result.stdout.strip().splitlines()


class Hidden(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def test_top_default_and_tie_order(self):
        f = self.dir / "a.txt"
        f.write_text("the cat the dog The end", encoding="utf-8")
        self.assertEqual(lines(run(str(f))), ["the 3", "cat 1", "dog 1"])

    def test_top_option_and_apostrophe(self):
        f = self.dir / "b.txt"
        f.write_text("don't stop, don't go. go go", encoding="utf-8")
        self.assertEqual(lines(run(str(f), "--top", "2")), ["go 3", "don't 2"])

    def test_missing_file_exits_2(self):
        r = run(str(self.dir / "none.txt"))
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.strip())

    def test_empty_file_prints_nothing(self):
        f = self.dir / "c.txt"
        f.write_text("  !!! ", encoding="utf-8")
        r = run(str(f))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")
'''

RPN_PRD = '''# rpn — PRD

## 1. 개요

역폴란드 표기법(RPN) 수식을 계산하는 명령줄 도구.

''' + STACK + '''
## 3. 요구사항

- 명령: `python -m rpn "<수식>"`. 토큰은 공백으로 구분한다.
- 지원: 숫자(정수·소수)와 연산자 `+ - * /`.
- 결과가 정수값이면 소수점 없이(`14`), 아니면 소수로(`2.5`) 한 줄에 출력한다.
  - `"3 4 + 2 *"` → `14`
  - `"10 4 /"` → `2.5`
  - `"8 2 /"` → `4`
- 오류(0으로 나눔, 피연산자 부족, 알 수 없는 토큰, 계산 후 값이 하나가 아님)는 표준 오류에 메시지를 내고 종료 코드 1. 표준 출력에는 아무것도 내지 않는다.
- 인자가 없으면 종료 코드 2.

## 4. 범위 밖

- 변수, 괄호, 거듭제곱, 대화형 모드.
'''

RPN_HIDDEN = HEADER + '''
class Hidden(unittest.TestCase):
    def test_results(self):
        for expr, out in [("3 4 + 2 *", "14"), ("10 4 /", "2.5"), ("8 2 /", "4"), ("5 1 2 + 4 * + 3 -", "14")]:
            with self.subTest(expr=expr):
                r = run(expr)
                self.assertEqual(r.returncode, 0)
                self.assertEqual(r.stdout.strip(), out)

    def test_errors_exit_1_without_stdout(self):
        for expr in ["1 0 /", "1 +", "2 x *", "1 2", ""]:
            with self.subTest(expr=expr):
                r = run(expr)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(r.stdout.strip(), "")
                self.assertTrue(r.stderr.strip())

    def test_no_args_exits_2(self):
        self.assertEqual(run().returncode, 2)
'''


def _case(prd, hidden, name):
    return {"prd": prd.replace("MODULE", name), "hidden": hidden.replace("MODULE", name)}


CASES = {
    "slugify": _case(SLUGIFY_PRD, SLUGIFY_HIDDEN, "slugify"),
    "wordcount": _case(WORDCOUNT_PRD, WORDCOUNT_HIDDEN, "wordcount"),
    "rpn": _case(RPN_PRD, RPN_HIDDEN, "rpn"),
}


def grade(project, name, timeout=300):
    """Run the hidden tests against the project. They live outside the project folder."""
    project = Path(project)
    with tempfile.TemporaryDirectory(prefix="fusion-grade-", ignore_cleanup_errors=True) as tmp:
        (Path(tmp) / "test_hidden.py").write_text(CASES[name]["hidden"], encoding="utf-8")
        env = dict(os.environ, PROJECT_DIR=str(project))
        result = execute([sys.executable, "-m", "harness_fusion.verification", tmp], project, timeout, "", env)
    return {"passed": result["returncode"] == 0, "returncode": result["returncode"],
            "output": (result["stderr"] or result["stdout"])[-1500:]}


def run_case(name, out_dir, backend="codex", invoke=None):
    """Create a fresh project from the case PRD, run the engine, grade, and append one JSONL record."""
    if name not in CASES:
        raise ValueError(f"Unknown benchmark case: {name}")
    out_dir = Path(out_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project = (out_dir / f"{name}-{stamp}").resolve()
    prd = CASES[name]["prd"]
    config.initialize(project, backend=backend, goal=prd, uniform=True)
    started = time.monotonic()
    exit_code = Engine(project, invoke=invoke).run(False)
    seconds = round(time.monotonic() - started, 1)
    state = json.loads((project / ".fusion/state.json").read_text(encoding="utf-8"))
    graded = grade(project, name)
    cfg = config.load(project)
    record = {
        "time": datetime.now(timezone.utc).isoformat(), "case": name, "harness_version": __version__,
        "agents": {role: {"backend": agent["backend"], "model": agent.get("model", "CLI default")}
                   for role, agent in cfg["agents"].items()},
        "status": state["status"], "exit_code": exit_code, "cycles": state["cycles"],
        "attempts": state["attempts"], "seconds": seconds, "reason": state.get("reason"),
        "hidden_passed": graded["passed"], "hidden_returncode": graded["returncode"],
        # verified = the engine said DONE and the hidden tests agree. DONE alone can be a false pass.
        "verified": state["status"] == "DONE" and graded["passed"],
        "prd_sha256": hashlib.sha256(prd.encode("utf-8")).hexdigest(),
        "project": str(project), "usage": usage_summary(project),
    }
    if not graded["passed"]:
        record["hidden_output"] = graded["output"]
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record

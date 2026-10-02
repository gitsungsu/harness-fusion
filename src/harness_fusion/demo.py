"""Deterministic transport demo; no model calls or model-quality claims."""
import json
import sys
from pathlib import Path

from .config import AGENTS_FILE, ROLES, initialize
from .engine import Engine

SOURCE = '''import sqlite3
from contextlib import closing

def add_task(database, title):
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        cursor = connection.execute("INSERT INTO tasks(title) VALUES (?)", (title,))
        return cursor.lastrowid

def list_tasks(database):
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")
        return connection.execute("SELECT id, title FROM tasks ORDER BY id").fetchall()
'''

TESTS = '''import tempfile
import unittest
from pathlib import Path
from tracker import add_task, list_tasks

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / "tasks.db"

    def test_persistence_and_order(self):
        first = add_task(self.database, "first")
        second = add_task(self.database, "second")
        self.assertEqual(list_tasks(self.database), [(first, "first"), (second, "second")])

    def test_rejects_blank(self):
        with self.assertRaises(ValueError):
            add_task(self.database, "  ")

    def test_quotes_and_unicode(self):
        text = "회의'); DROP TABLE tasks; -- 한글"
        key = add_task(self.database, text)
        self.assertEqual(list_tasks(self.database), [(key, text)])

    def test_empty_database(self):
        self.assertEqual(list_tasks(self.database), [])
'''


def run_demo(root):
    initialize(root, goal="SQLite 작업 목록: 제목을 저장하고 삽입 순서로 조회한다. 빈 제목을 거부하고 한글·따옴표를 보존한다.")
    # The scripted command backend has no model or effort, so replace the real-agent template.
    (root / AGENTS_FILE).write_text("\n".join(
        f'[{role}]\nbackend = "command"\ncommand = ["{{python}}", "-m", "harness_fusion.demo", "--agent"]\n'
        for role in ROLES), encoding="utf-8")
    print("Scripted demo: first implementation intentionally fails a real test; second attempt repairs it.")
    return Engine(root).run()


def agent():
    raw = sys.stdin.buffer.read().decode("utf-8")
    request = json.loads(raw[raw.index("\n") + 1:])
    role = request["role"]
    if role == "planner":
        response = {"summary": "SQLite module with persistence, validation and behavioral tests.", "tasks": [{
            "id": "T1", "title": "Implement SQLite task store", "depends_on": [],
            "touch": ["tracker.py", "tests/**"],
            "acceptance": ["삽입한 작업을 순서대로 영속 저장한다", "빈 제목은 거부하고 한글·따옴표를 보존한다"]}]}
    elif role == "generator":
        source = SOURCE
        if request["last_failure"] is None:
            source = source.replace('raise ValueError("title must not be empty")', 'return -1')
        Path("tracker.py").write_text(source, encoding="utf-8")
        Path("tests").mkdir(exist_ok=True)
        Path("tests/test_tracker.py").write_text(TESTS, encoding="utf-8")
        response = {"summary": "SQLite 저장 모듈과 영속성·빈 입력·한글·SQL 문자열 테스트 4개를 작성했습니다."}
    else:
        passed = bool(request["checks"]) and all(x["returncode"] == 0 for x in request["checks"])
        response = {"token": request["token"], "task_id": request["task_id"],
                    "verdict": "PASS" if passed else "FAIL", "spec_score": 3 if passed else 1,
                    "test_score": 3, "criteria": [
                        {"criterion": x, "passed": passed, "evidence": "tests/test_tracker.py + engine check results (scripted reviewer)"}
                        for x in request["task"]["acceptance"]],
                    "issues": [] if passed else ["Blank-title rejection test failed; raise ValueError."]}
    sys.stdout.buffer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


if __name__ == "__main__":
    if sys.argv[1:] != ["--agent"]:
        raise SystemExit("Use harness-fusion demo PROJECT")
    agent()

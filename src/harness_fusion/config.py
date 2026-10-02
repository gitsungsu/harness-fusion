import sys
import tomllib
from pathlib import Path

from .contracts import ContractError, keys, string

ROLES = ("planner", "generator", "evaluator")


def load(root):
    data = tomllib.loads((root / "harness.toml").read_text(encoding="utf-8"))
    keys(data, ("version", "limits", "agents", "checks"))
    if type(data["version"]) is not int or data["version"] != 1:
        raise ContractError("Unsupported config version")
    keys(data["limits"], ("max_cycles", "max_attempts", "agent_timeout", "check_timeout", "total_seconds", "context_chars"))
    for name, value in data["limits"].items():
        if type(value) is not int or value < 1:
            raise ContractError(f"limits.{name} must be a positive integer")
    if data["limits"]["context_chars"] < 8000:
        raise ContractError("context_chars must be at least 8000")
    keys(data["agents"], ROLES)
    for role in ROLES:
        cfg = data["agents"][role]
        if not isinstance(cfg, dict) or set(cfg) - {"backend", "model", "command"}:
            raise ContractError(f"Unknown agent settings: {role}")
        backend = cfg.get("backend")
        if backend not in ("codex", "claude", "command"):
            raise ContractError(f"Unknown backend: {backend}")
        if "model" in cfg:
            string(cfg["model"])
        if backend == "command":
            argv(cfg.get("command"))
        elif "command" in cfg:
            raise ContractError("command is only valid for backend=command")
    if not isinstance(data["checks"], list) or not data["checks"]:
        raise ContractError("At least one explicit check is required; no checks means no completion")
    names = set()
    for check in data["checks"]:
        keys(check, ("name", "command"))
        string(check["name"])
        if check["name"] in names:
            raise ContractError("Duplicate check name")
        names.add(check["name"])
        argv(check["command"])
    return data


def argv(value):
    if not isinstance(value, list) or not value:
        raise ContractError("Command must be a nonempty argument array, not a shell string")
    for item in value:
        string(item)
    return [sys.executable if item == "{python}" else item for item in value]


def initialize(root, backend="codex", profile="python", goal=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    from .filesystem import snapshot
    snapshot(root)
    targets = ["harness.toml", "AGENTS.md", "docs/PRD.md"]
    if any((root / p).exists() for p in targets) or (root / ".fusion").exists():
        raise ContractError("Initialization would overwrite existing instructions; use a new project folder")
    (root / "docs").mkdir(exist_ok=True)
    check = ('["{python}", "-m", "harness_fusion.verification", "tests"]' if profile == "python"
             else '["npm", "test", "--", "--run"]')
    config = '''version = 1

[limits]
max_cycles = 8
max_attempts = 3
agent_timeout = 900
check_timeout = 180
total_seconds = 7200
context_chars = 48000
'''
    for role in ROLES:
        config += f'\n[agents.{role}]\nbackend = "{backend}"\n# model = "your-available-model-id"\n'
    config += f'\n[[checks]]\nname = "acceptance-tests"\ncommand = {check}\n'
    if profile == "node":
        config += '\n[[checks]]\nname = "build"\ncommand = ["npm", "run", "build"]\n'
    (root / "harness.toml").write_text(config, encoding="utf-8")
    (root / "AGENTS.md").write_text('''# Project instructions

- Read docs/PRD.md before implementation. Explain results in Korean.
- Work only on the active task and its touch paths. No deployment or git push.
- Do not edit harness.toml, AGENTS.md, CLAUDE.md, docs/PRD.md or .fusion/.
- Do not edit harness-owned PLAN/TASKS/MEMORY/IMPLEMENT/REVIEW documents.
- Add behavioral tests for acceptance criteria. Do not weaken tests to get green.
- Planner/Evaluator inspect only; Generator implements. No spawned subagents.
- Return the requested JSON object as your final answer; do not write report files.
''', encoding="utf-8")
    prd = goal or "TODO: 만들 프로그램, 입력·출력 예시, 오류 처리, 완료 기준을 구체적으로 작성하세요."
    (root / "docs/PRD.md").write_text("# 요구사항\n\n" + prd + "\n", encoding="utf-8")
    for name, content in {
        "ARCHITECTURE.md": "# 구조\n\n모듈별 책임·데이터 흐름·외부 의존성을 기록합니다.\n",
        "DECISIONS.md": "# 결정 기록\n\n날짜 / 문제 / 선택 / 이유 / 대안 순서로 기록합니다.\n",
        "HARNESS_CHECKLIST.md": "# 완료 점검\n\n- [ ] 요구사항별 테스트\n- [ ] 오류·경계값 테스트\n- [ ] 모든 검사 통과\n- [ ] 평가 근거 확인\n- [ ] 사용 안내와 한계 기록\n",
    }.items():
        path = root / "docs" / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    return root

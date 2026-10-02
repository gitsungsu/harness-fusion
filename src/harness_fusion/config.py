import re
import sys
import tomllib
from pathlib import Path

from .contracts import ContractError, keys, path_rule, string

ROLES = ("planner", "generator", "evaluator")
AGENTS_FILE = "agents.toml"
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CRITERIA_WORDS = re.compile(r"완료\s*기준|인수\s*기준|수용\s*기준|acceptance|completion criteria|done when", re.I)
TEST_WORDS = re.compile(r"테스트|test", re.I)
OPTIONAL_SECTIONS = ("setup", "acceptance")
DEFAULT_SETUP_TIMEOUT = 600


def load(root):
    data = tomllib.loads((root / "harness.toml").read_text(encoding="utf-8"))
    agents_file = root / AGENTS_FILE
    if agents_file.is_file():
        if "agents" in data:
            raise ContractError(f"Define agents in {AGENTS_FILE} or in harness.toml [agents], not both")
        data["agents"] = tomllib.loads(agents_file.read_text(encoding="utf-8"))
        bootstrap_raw = data["agents"].pop("bootstrap", None)  # not an engine role; used by `harness-fusion prd`
    else:
        bootstrap_raw = None
    optional = {name: data.pop(name) for name in OPTIONAL_SECTIONS if name in data}
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
        if not isinstance(cfg, dict) or set(cfg) - {"backend", "model", "effort", "command"}:
            raise ContractError(f"Unknown agent settings: {role}")
        backend = cfg.get("backend")
        if backend not in ("codex", "claude", "command"):
            raise ContractError(f"Unknown backend: {backend}")
        if "model" in cfg:
            string(cfg["model"])
        if "effort" in cfg:
            if backend == "command":
                raise ContractError("effort is not valid for backend=command")
            if cfg["effort"] == "ultra":
                raise ContractError("effort 'ultra' delegates work to subagents, which this harness forbids")
            if cfg["effort"] not in EFFORTS:
                raise ContractError(f"effort must be one of {', '.join(EFFORTS)}: {role}")
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
    data["bootstrap"] = bootstrap_settings(bootstrap_raw)
    data["setup"] = setup_steps(optional.get("setup", []))
    data["acceptance"] = acceptance_path(optional.get("acceptance"))
    if data["acceptance"]:
        if "acceptance" in names:
            raise ContractError("Check name 'acceptance' is reserved when [acceptance] is configured")
        data["checks"].append({"name": "acceptance",
                               "command": ["{python}", "-m", "harness_fusion.verification", data["acceptance"]]})
    return data


def bootstrap_settings(value):
    """The interactive PRD interview agent. It needs a live conversation, so only the claude CLI qualifies."""
    if value is None:
        return None
    if not isinstance(value, dict) or not {"backend"} <= set(value) <= {"backend", "model", "effort"}:
        raise ContractError("[bootstrap] needs backend and may set model and effort")
    if value["backend"] != "claude":
        raise ContractError("[bootstrap] backend must be claude (the PRD interview is an interactive claude session)")
    if "model" in value:
        string(value["model"])
    if "effort" in value:
        if value["effort"] == "ultra":
            raise ContractError("effort 'ultra' delegates work to subagents, which this harness forbids")
        if value["effort"] not in EFFORTS:
            raise ContractError(f"effort must be one of {', '.join(EFFORTS)}: bootstrap")
    return value


def setup_steps(value):
    """Human-declared preparation commands; agents are never allowed to install anything."""
    if not isinstance(value, list):
        raise ContractError("setup must be an array of [[setup]] tables")
    names = set()
    for step in value:
        if not isinstance(step, dict) or not {"name", "command"} <= set(step) <= {"name", "command", "timeout"}:
            raise ContractError("Each [[setup]] needs name and command, and may set timeout")
        string(step["name"])
        if step["name"] in names:
            raise ContractError("Duplicate setup name")
        names.add(step["name"])
        argv(step["command"])
        if "timeout" in step and (type(step["timeout"]) is not int or step["timeout"] < 1):
            raise ContractError("setup timeout must be a positive integer")
    return value


def acceptance_path(value):
    """Folder of human-written tests that no agent may modify."""
    if value is None:
        return None
    keys(value, ("path",))
    path = path_rule(value["path"]).rstrip("/")
    if path in ("", ".", "docs", "src", "tests"):
        raise ContractError(f"acceptance.path is too broad or reserved: {value['path']}")
    return path


def prd_warnings(text):
    """Advisory only: free-form PRDs stay valid, but missing completion criteria or test method is flagged."""
    warnings = []
    if "TODO:" in text:
        warnings.append("PRD still has TODO placeholders; a run will refuse to start until they are replaced")
    if not CRITERIA_WORDS.search(text):
        warnings.append("PRD names no completion criteria (add a '완료 기준' section) so reviews may be loose")
    if not TEST_WORDS.search(text):
        warnings.append("PRD does not say how to test it (add a '테스트 방법' section)")
    return warnings


def argv(value):
    if not isinstance(value, list) or not value:
        raise ContractError("Command must be a nonempty argument array, not a shell string")
    for item in value:
        string(item)
    return [sys.executable if item == "{python}" else item for item in value]


MODEL_LINES = {
    "codex": 'model = "gpt-6.1-sol"  # needs a Codex CLI whose model list includes it; change if unavailable',
    "claude": 'model = "claude-sonnet-5-5"  # pinned model ID; change if your account cannot use it',
}


def agents_template(backend, uniform=False):
    """agents.toml for a new project. The planner defaults to claude sonnet high unless uniform."""
    lines = [
        "# Backend, model and effort for each agent. One section per role.",
        "# backend: codex | claude | command   effort: low | medium | high | xhigh | max",
        "# Agents are defined only here (not in harness.toml). Changing this file starts a new run.",
        "# init --backend sets generator and evaluator; the planner defaults to claude.",
    ]
    for role in ROLES:
        if role == "planner" and not uniform:
            lines += ["", "[planner]", 'backend = "claude"', MODEL_LINES["claude"], 'effort = "high"']
        else:
            lines += ["", f"[{role}]", f'backend = "{backend}"', MODEL_LINES[backend], 'effort = "medium"']
    lines += [
        "",
        "# Interview agent for `harness-fusion prd` (interactive, so claude only; not part of a run).",
        "[bootstrap]",
        'backend = "claude"',
        'model = "claude-opus-5-5"',
        'effort = "high"',
    ]
    return "\n".join(lines) + "\n"


def initialize(root, backend="codex", profile="python", goal=None, acceptance=False, uniform=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    from .filesystem import snapshot
    snapshot(root)
    targets = ["harness.toml", AGENTS_FILE, "AGENTS.md", "docs/PRD.md"] + (["acceptance"] if acceptance else [])
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
    agents = agents_template(backend, uniform)
    (root / AGENTS_FILE).write_text(agents, encoding="utf-8")
    config += f'\n[[checks]]\nname = "acceptance-tests"\ncommand = {check}\n'
    if profile == "node":
        config += '\n[[checks]]\nname = "build"\ncommand = ["npm", "run", "build"]\n'
    config += ('\n# Optional preparation run once before planning (argument array, no shell).\n'
               '# Agents cannot install dependencies; declare what the project needs here.\n'
               '# [[setup]]\n# name = "install"\n'
               '# command = ["{python}", "-m", "pip", "install", "-r", "requirements.txt"]\n'
               '# timeout = 600\n')
    if acceptance:
        config += '\n[acceptance]\npath = "acceptance"\n'
    (root / "harness.toml").write_text(config, encoding="utf-8")
    (root / "AGENTS.md").write_text('''# Project instructions

- Read docs/PRD.md before implementation. Explain results in Korean.
- Work only on the active task and its touch paths. No deployment or git push.
- Do not edit harness.toml, agents.toml, AGENTS.md, CLAUDE.md, docs/PRD.md or .fusion/.
- Do not edit harness-owned PLAN/TASKS/MEMORY/IMPLEMENT/REVIEW documents.
- Do not edit the human-owned acceptance test folder if harness.toml defines [acceptance].
- Add behavioral tests for acceptance criteria. Do not weaken tests to get green.
- Planner/Evaluator inspect only; Generator implements. No spawned subagents.
- Return the requested JSON object as your final answer; do not write report files.
''', encoding="utf-8")
    prd = goal or ("## 목표\nTODO: 만들 프로그램을 한 문장으로 설명하세요.\n\n"
                   "## 입력과 출력\nTODO: 입력·출력 예시와 오류 처리를 구체적으로 적으세요.\n\n"
                   "## 완료 기준\nTODO: 끝났다고 볼 수 있는 조건을 확인 가능한 문장으로 적으세요.\n\n"
                   "## 테스트 방법\nTODO: 어떤 자동 테스트로 확인할지 적으세요.")
    (root / "docs/PRD.md").write_text("# 요구사항\n\n" + prd + "\n", encoding="utf-8")
    if acceptance:
        (root / "acceptance").mkdir()
        (root / "acceptance/README.md").write_text(
            "# 수용 테스트\n\n사람이 직접 작성하는 테스트 폴더입니다. 에이전트는 이 폴더를 수정할 수 없고,\n"
            "실행 시작 후 내용이 바뀌면 하네스가 중단합니다. test*.py 파일을 추가한 뒤 실행하세요.\n",
            encoding="utf-8")
    for name, content in {
        "ARCHITECTURE.md": "# 구조\n\n모듈별 책임·데이터 흐름·외부 의존성을 기록합니다.\n",
        "DECISIONS.md": "# 결정 기록\n\n날짜 / 문제 / 선택 / 이유 / 대안 순서로 기록합니다.\n",
        "HARNESS_CHECKLIST.md": "# 완료 점검\n\n- [ ] 요구사항별 테스트\n- [ ] 오류·경계값 테스트\n- [ ] 모든 검사 통과\n- [ ] 평가 근거 확인\n- [ ] 사용 안내와 한계 기록\n",
    }.items():
        path = root / "docs" / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    return root

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
OPTIONAL_SECTIONS = ("setup", "acceptance", "git", "watch")
# Hidden folders that stay watched even if listed in [watch] ignore (skills and harness controls).
UNIGNORABLE = (".claude/", ".agents/")
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
        if backend not in ("codex", "claude", "agy", "command"):
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
    data["git"] = git_settings(optional.get("git"))
    data["watch"] = watch_settings(optional.get("watch"), data["acceptance"])
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


def git_settings(value):
    """Commit each passed task, optionally pushing it. Off unless declared."""
    if value is None:
        return {"commit": False, "push": False}
    if not isinstance(value, dict) or set(value) - {"commit", "push"} or any(type(v) is not bool for v in value.values()):
        raise ContractError("[git] may only set commit and push to true or false")
    settings = {"commit": value.get("commit", False), "push": value.get("push", False)}
    if settings["push"] and not settings["commit"]:
        raise ContractError("[git] push = true requires commit = true")
    return settings


def watch_settings(value, acceptance=None):
    """Tool-state folders (e.g. .omc/, .expo/) written by editors, hooks or CLIs outside the agent's control.
    The harness neither watches nor commits them, so their churn cannot halt a run.
    Only hidden top-level-style folders qualify; source, docs, skills and controls stay watched."""
    if value is None:
        return {"ignore": []}
    if not isinstance(value, dict) or set(value) - {"ignore"}:
        raise ContractError("[watch] may only set ignore")
    ignore = value.get("ignore", [])
    if not isinstance(ignore, list):
        raise ContractError("[watch] ignore must be an array of folder paths ending with '/'")
    for entry in ignore:
        path_rule(entry)
        if not entry.endswith("/") or "*" in entry:
            raise ContractError(f"[watch] ignore entries are folders ending with '/', without wildcards: {entry}")
        if not entry.startswith(".") or entry.startswith(UNIGNORABLE):
            raise ContractError(f"[watch] may only ignore hidden tool-state folders, not sources or controls: {entry}")
        if acceptance and (acceptance + "/").startswith(entry):
            raise ContractError(f"[watch] cannot ignore the acceptance folder: {entry}")
    return {"ignore": ignore}


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


DEFAULT_AGENTS = Path(__file__).with_name("default_agents.toml")


def default_agents(backend, uniform=False):
    """Resolved defaults for init from default_agents.toml, the single place model defaults live.
    uniform gives every run role the generator's settings, so all of them use `backend`."""
    data = tomllib.loads(DEFAULT_AGENTS.read_text(encoding="utf-8"))
    models = data.pop("models")
    resolved = {}
    for role in ROLES + ("bootstrap",):
        cfg = dict(data["generator"] if uniform and role in ROLES else data[role])
        if cfg["backend"] == "init":
            cfg["backend"] = backend
        if "model" not in cfg and cfg["backend"] in models:
            cfg["model"] = models[cfg["backend"]]
        resolved[role] = {key: cfg[key] for key in ("backend", "model", "effort") if key in cfg}
    return resolved


def backend_menu():
    """Comment block listing every backend with its default model, so each project can mix them per role."""
    models = tomllib.loads(DEFAULT_AGENTS.read_text(encoding="utf-8"))["models"]
    return [
        "# 역할(planner / generator / evaluator)마다 backend·model·effort를 따로 고를 수 있습니다.",
        "# 예: 계획·구현은 agy, 평가는 claude처럼 섞어 써도 됩니다.",
        "#",
        f'#   backend = "agy"     Google Antigravity CLI   기본 model: {models.get("agy", "-")}  (목록: `agy models`)',
        f'#   backend = "claude"  Claude Code CLI          기본 model: {models.get("claude", "-")}'
        "  (예: claude-opus-5-5, claude-fable-5-1)",
        f'#   backend = "codex"   Codex CLI                기본 model: {models.get("codex", "-")}',
        '#   backend = "command" 직접 만든 명령 (command = ["..."], model·effort 없음)',
        "#",
        "# effort: low | medium | high | xhigh | max  (agy는 모델마다 지원 effort가 다릅니다)",
        "# model 줄을 지우면 각 CLI의 기본 모델을 씁니다.",
        "# 이 파일을 바꾸면 이전 run을 이어갈 수 없고 새 run으로 시작합니다.",
    ]


def agents_template(backend, uniform=False):
    """agents.toml for a new project, rendered from default_agents.toml."""
    lines = backend_menu()
    for role, cfg in default_agents(backend, uniform).items():
        if role == "bootstrap":
            lines += ["", "# Interview agent for `harness-fusion prd` (interactive, so claude only; not part of a run)."]
        else:
            lines.append("")
        lines.append(f"[{role}]")
        lines += [f'{key} = "{value}"' for key, value in cfg.items()]
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
agent_timeout = 1800
check_timeout = 300
total_seconds = 14400
context_chars = 48000

# Tool-state folders that editors, hooks or CLIs write on their own (not agent work).
# The harness neither watches nor commits them, so they cannot halt a run.
# Only hidden folders ending with '/' are allowed; .claude/ and .agents/ stay protected.
[watch]
ignore = [".omc/", ".expo/"]
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
               '# timeout = 600\n'
               '\n# Commit each passed task and push it when a remote exists (needs a git repository).\n'
               '# harness.toml, agents.toml, AGENTS.md, .fusion/ and .env* are never committed.\n'
               '[git]\ncommit = true\npush = true\n')
    if acceptance:
        config += '\n[acceptance]\npath = "acceptance"\n'
    (root / "harness.toml").write_text(config, encoding="utf-8")
    (root / "AGENTS.md").write_text('''# Project instructions

- Read docs/PRD.md before implementation. Explain results in Korean.
- Work only on the active task and its touch paths. No deployment or git push.
- Do not edit harness.toml, agents.toml, AGENTS.md, CLAUDE.md, docs/PRD.md or .fusion/.
- Do not edit project skills (.claude/skills/, .agents/skills/, skills-lock.json); read them when relevant.
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

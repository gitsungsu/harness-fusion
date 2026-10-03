"""Interactive PRD interview: a live claude session that writes docs/PRD.md, then offers project skills.

The conversation needs a real terminal, so only the claude CLI qualifies (see [bootstrap] in agents.toml).
The harness auto-approves only reading the project, editing the PRD and searching for skills; installing a
skill (`npx skills add`) always needs the user's approval at claude's permission prompt. Afterwards it checks
that nothing changed except the PRD and the project skill folders.
"""
import subprocess

from . import config, filesystem as fs
from .process import resolve_command

PRD = "docs/PRD.md"
TOOLS = "Read,Glob,Grep,Write,Edit,Skill,Bash"
ALLOWED = f"Read,Glob,Grep,Edit({PRD}),Skill(find-skills),Bash(npx skills find:*)"
# Where `npx skills add -a claude-code -a codex --copy` writes, plus claude's own "don't ask again" file.
SKILL_PATHS = (".claude/skills/", ".agents/skills/")
SKILL_FILES = ("skills-lock.json", ".claude/settings.local.json")

OPENING = ("PRD 작성 인터뷰를 시작해 주세요. 먼저 프로젝트 폴더에 이미 있는 코드와 문서를 읽어 보고, "
           "그다음 저에게 질문을 한 번에 하나씩 해 주세요.")

INSTRUCTIONS = """You are the PRD interviewer for Harness Fusion. You write docs/PRD.md, then help the user install project skills.

How to work:
- Speak Korean. The user may not be a developer; avoid jargon and explain briefly when you must use it.
- First read the existing project (Read, Glob, Grep) so you do not ask what the files already answer.
- Ask exactly one question at a time (한 번에 하나). Wait for the answer. Offer 2-3 concrete options when helpful.
- Cover, in this order: 목표 (what to build, in one sentence), 입력과 출력 (examples, including error cases),
  완료 기준 (conditions that can be checked mechanically), 테스트 방법 (which automated tests will prove it),
  and what is out of scope.
- Do not invent requirements. If the user is unsure, record it as an explicit open question instead of guessing.
- Before writing, read the answers back as a short summary and get the user's confirmation.

What you may do:
- Write or edit docs/PRD.md only, using the sections: 목표, 입력과 출력, 완료 기준, 테스트 방법
  (add 범위 밖 if needed). Write concrete, testable sentences.
- The finished file must contain no TODO placeholders.
- Do not write code, tests, or any other file. Other files are read-only for you.

After the PRD is saved — install project skills:
- Use the find-skills skill if it is available; otherwise follow these steps directly.
- From the PRD, pick 1-3 search terms (language, framework, test tool) and run `npx skills find <term>`.
- Prefer well-known sources and skills with many installs; skip anything under 100 installs or from unknown authors.
- Show the user at most 5 candidates (name, what it does, source, installs) and ask which to install, one question.
  Installing nothing is a fine answer.
- Install only what the user chose, into this project, for both agents, as real copies:
  `npx skills add <owner/repo> -s <skill> -a claude-code -a codex --copy -y`
  Never use -g (global) and never omit --copy (symlinks break the harness).
- Run no other commands. Do not change the PRD in this step.

Finally, tell the user to run `harness-fusion doctor` and then `harness-fusion run` for this project.
"""


def command_for(cfg, prompt=OPENING):
    # The opening prompt goes first: --allowedTools takes a list and would swallow a trailing positional.
    command = ["claude", prompt, "--tools", TOOLS, "--allowedTools", ALLOWED, "--append-system-prompt", INSTRUCTIONS]
    if cfg.get("model"):
        command += ["--model", cfg["model"]]
    if cfg.get("effort"):
        command += ["--effort", cfg["effort"]]
    return command


def default_runner(argv, cwd):
    return subprocess.run(resolve_command(argv), cwd=cwd).returncode


def run(root, runner=None):
    root = root.resolve()
    try:
        cfg = config.load(root)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 2
    settings = cfg["bootstrap"]
    if settings is None:
        print("ERROR: add a [bootstrap] section to agents.toml (backend = \"claude\") to use the PRD interview")
        return 2
    if (root / ".fusion/state.json").exists():
        print("ERROR: a run already exists for this project; PRD changes need a new project folder")
        return 2
    runner = runner or default_runner
    try:
        before = fs.snapshot(root)
        print(f"Starting the PRD interview with claude ({settings.get('model', 'CLI default')}, "
              f"effort {settings.get('effort', 'CLI default')}). Finish the conversation to save docs/PRD.md.", flush=True)
        try:
            code = runner(command_for(settings), root)
        except KeyboardInterrupt:
            code = 130
        changed = fs.changes(before, fs.snapshot(root))
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not run the interview: {exc}")
        return 2
    skills = [p for p in changed if p.startswith(SKILL_PATHS) or p in SKILL_FILES]
    others = [p for p in changed if p != PRD and p not in skills]
    if others:
        print("ERROR: the interview changed files other than docs/PRD.md and project skills: " + ", ".join(others)
              + ". Nothing was reverted; inspect them before continuing.")
        return 2
    if code != 0:
        print(f"ERROR: claude exited with code {code}; the PRD may be incomplete")
        return 2
    if PRD not in changed:
        print("ERROR: docs/PRD.md was not written. Run the command again and finish the interview.")
        return 2
    text = (root / PRD).read_text(encoding="utf-8")
    if "TODO:" in text:
        print("ERROR: docs/PRD.md still has TODO placeholders; a run will refuse to start until they are replaced")
        return 2
    for warning in config.prd_warnings(text):
        print("WARNING: " + warning)
    installed = sorted({p.split("/")[2] for p in skills if p.startswith(SKILL_PATHS) and p.count("/") >= 3})
    print("Project skills: " + (", ".join(installed) if installed else "none installed"))
    print("PRD saved to docs/PRD.md. Next: harness-fusion doctor <project>, then harness-fusion run <project>.")
    return 0

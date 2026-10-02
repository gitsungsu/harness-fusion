"""Interactive PRD interview: a live claude session that may write docs/PRD.md and nothing else.

The conversation needs a real terminal, so only the claude CLI qualifies (see [bootstrap] in agents.toml).
The harness never auto-approves anything beyond reading the project and editing the PRD, and it checks
afterwards that no other file changed.
"""
import subprocess

from . import config, filesystem as fs
from .process import resolve_command

PRD = "docs/PRD.md"
TOOLS = "Read,Glob,Grep,Write,Edit"
ALLOWED = f"Read,Glob,Grep,Write({PRD}),Edit({PRD})"

OPENING = ("PRD 작성 인터뷰를 시작해 주세요. 먼저 프로젝트 폴더에 이미 있는 코드와 문서를 읽어 보고, "
           "그다음 저에게 질문을 한 번에 하나씩 해 주세요.")

INSTRUCTIONS = """You are the PRD interviewer for Harness Fusion. Your only deliverable is docs/PRD.md.

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
- Do not write code, tests, or any other file, and do not run commands. Other files are read-only for you.

When the PRD is saved, tell the user to run `harness-fusion doctor` and then `harness-fusion run` for this project.
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
    others = [p for p in changed if p != PRD]
    if others:
        print("ERROR: the interview changed files other than docs/PRD.md: " + ", ".join(others)
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
    print("PRD saved to docs/PRD.md. Next: harness-fusion doctor <project>, then harness-fusion run <project>.")
    return 0

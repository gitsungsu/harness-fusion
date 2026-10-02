import argparse
import json
import sys
from pathlib import Path

from . import __version__, bench, bootstrap, config
from .engine import Engine, usage_summary
from .filesystem import code_digest, snapshot
from .process import resolve_command


def doctor(root):
    cfg = config.load(root)
    snapshot(root)
    okay = True
    def available(program):
        try:
            return " ".join(resolve_command([program]))
        except OSError as exc:
            return None
    where = config.AGENTS_FILE if (root / config.AGENTS_FILE).is_file() else "harness.toml [agents]"
    print(f"agents defined in: {where}")
    for role, agent in cfg["agents"].items():
        program = config.argv(agent["command"])[0] if agent["backend"] == "command" else agent["backend"]
        found = available(program)
        print(f"{role}: {program} -> {found or 'NOT FOUND'}")
        okay &= found is not None
    if cfg["bootstrap"]:  # informational: only `harness-fusion prd` needs it, never a run
        found = available("claude")
        print(f"bootstrap: claude ({cfg['bootstrap'].get('model', 'CLI default')}, "
              f"effort {cfg['bootstrap'].get('effort', 'CLI default')}) -> {found or 'NOT FOUND'}")
    for check in cfg["checks"]:
        program = config.argv(check["command"])[0]
        found = available(program)
        print(f"check/{check['name']}: {program} -> {found or 'NOT FOUND'}")
        okay &= found is not None
    prd = root / "docs/PRD.md"
    if prd.is_file():
        notes = config.prd_warnings(prd.read_text(encoding="utf-8"))
        print("prd: " + ("ok" if not notes else "WARNING: " + "; ".join(notes)))
    for step in cfg["setup"]:
        program = config.argv(step["command"])[0]
        found = available(program)
        print(f"setup/{step['name']}: {program} -> {found or 'NOT FOUND'}")
        okay &= found is not None
    if cfg["acceptance"]:
        folder = root / cfg["acceptance"]
        found = folder.is_dir() and any(p.is_file() and p.name.lower() != "readme.md" for p in folder.rglob("*"))
        print(f"acceptance: {cfg['acceptance']}/ -> {'tests found' if found else 'NO TESTS (add human-written tests)'}")
        okay &= found
    print("Command availability only; authentication, model access and test quality require a real run.")
    return 0 if okay else 2


def status(root):
    path = root / ".fusion/state.json"
    if not path.exists():
        print("No execution yet.")
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    output = {k: state.get(k) for k in ("status", "active", "completed", "attempts", "cycles", "reason")}
    if state.get("halt_kind"):
        output["halt_kind"] = state["halt_kind"]
        output["retry_hint"] = state.get("retry_hint")
    output["usage"] = usage_summary(root)
    if state.get("status") == "DONE":
        output["current_files_match_verified_result"] = state.get("digest") == code_digest(root)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def run_bench(args):
    names = args.only or sorted(bench.CASES)
    if not args.run:
        for name in sorted(bench.CASES):
            lines = bench.CASES[name]["prd"].splitlines()
            print(f"{name}: {lines[lines.index('## 1. 개요') + 2]}")
        print("Listing only; nothing was run. Use --run to execute with real AI CLIs (this consumes usage quota).")
        return 0
    try:
        records = [bench.run_case(name, args.out, backend=args.backend) for name in names]
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for record in records:
        print(f"{record['case']}: engine={record['status']} hidden={'PASS' if record['hidden_passed'] else 'FAIL'} "
              f"cycles={record['cycles']} seconds={record['seconds']}")
    print(f"Results appended to {args.out / 'results.jsonl'}")
    return 0 if all(r["verified"] for r in records) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness-fusion", description="Verified AI coding workflow")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create project instructions and harness.toml")
    init.add_argument("project", type=Path)
    init.add_argument("--backend", choices=("codex", "claude"), default="codex")
    init.add_argument("--profile", choices=("python", "node"), default="python")
    init.add_argument("--goal", help="Concrete requirements; otherwise edit docs/PRD.md")
    init.add_argument("--acceptance", action="store_true",
                      help="Create a human-owned, agent-read-only acceptance/ test folder")
    run = sub.add_parser("run", help="Run configured agents and checks")
    run.add_argument("project", type=Path)
    run.add_argument("--resume", action="store_true")
    bench_parser = sub.add_parser("bench", help="List the fixed benchmark cases; --run executes them with real agents")
    bench_parser.add_argument("--run", action="store_true", help="Run cases with real AI CLIs (consumes usage quota)")
    bench_parser.add_argument("--only", nargs="+", choices=sorted(bench.CASES), metavar="CASE")
    bench_parser.add_argument("--backend", choices=("codex", "claude"), default="codex")
    bench_parser.add_argument("--out", type=Path, default=Path("bench-runs"))
    prd = sub.add_parser("prd", help="Interview you in an interactive claude session and write docs/PRD.md")
    prd.add_argument("project", type=Path)
    for name in ("doctor", "status", "demo"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Titles and messages come from models; a console encoding like cp949 must never crash a run.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if args.action == "bench":
        return run_bench(args)
    root = args.project.resolve()
    if args.action == "prd":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("ERROR: harness-fusion prd needs an interactive terminal (stdin and stdout must be a console)")
            return 2
        return bootstrap.run(root)
    try:
        if args.action == "init":
            config.initialize(root, args.backend, args.profile, args.goal, args.acceptance)
            print(f"Initialized {root}. Edit docs/PRD.md and review harness.toml; then run doctor.")
            return 0
        if args.action == "run":
            return Engine(root).run(args.resume)
        if args.action == "doctor":
            return doctor(root)
        if args.action == "status":
            return status(root)
        from .demo import run_demo
        return run_demo(root)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

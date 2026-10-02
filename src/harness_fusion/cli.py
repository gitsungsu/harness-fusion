import argparse
import json
import sys
from pathlib import Path

from . import __version__, config
from .engine import Engine
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
    for role, agent in cfg["agents"].items():
        program = config.argv(agent["command"])[0] if agent["backend"] == "command" else agent["backend"]
        found = available(program)
        print(f"{role}: {program} -> {found or 'NOT FOUND'}")
        okay &= found is not None
    for check in cfg["checks"]:
        program = config.argv(check["command"])[0]
        found = available(program)
        print(f"check/{check['name']}: {program} -> {found or 'NOT FOUND'}")
        okay &= found is not None
    print("Command availability only; authentication, model access and test quality require a real run.")
    return 0 if okay else 2


def status(root):
    path = root / ".fusion/state.json"
    if not path.exists():
        print("No execution yet.")
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    output = {k: state.get(k) for k in ("status", "active", "completed", "attempts", "cycles", "reason")}
    if state.get("status") == "DONE":
        output["current_files_match_verified_result"] = state.get("digest") == code_digest(root)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="harness-fusion", description="Verified AI coding workflow")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create project instructions and harness.toml")
    init.add_argument("project", type=Path)
    init.add_argument("--backend", choices=("codex", "claude"), default="codex")
    init.add_argument("--profile", choices=("python", "node"), default="python")
    init.add_argument("--goal", help="Concrete requirements; otherwise edit docs/PRD.md")
    run = sub.add_parser("run", help="Run configured agents and checks")
    run.add_argument("project", type=Path)
    run.add_argument("--resume", action="store_true")
    for name in ("doctor", "status", "demo"):
        command = sub.add_parser(name)
        command.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    root = args.project.resolve()
    try:
        if args.action == "init":
            config.initialize(root, args.backend, args.profile, args.goal)
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

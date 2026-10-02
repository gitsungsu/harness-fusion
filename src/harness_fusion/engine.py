"""State machine owns completion; models supply proposals and evidence."""
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config, context, contracts, filesystem as fs, providers
from .process import execute


# Never committed: run controls, harness state and secrets.
GIT_NEVER = (":(exclude)harness.toml", f":(exclude){config.AGENTS_FILE}", ":(exclude)AGENTS.md",
             ":(exclude).fusion", ":(exclude,glob)**/.env*")


def render_plan(plan, completed):
    """Readable PLAN.md: one bullet per summary sentence, then a task overview table."""
    def cell(text):
        return text.replace("|", "\\|")
    lines = ["# Plan", "", "## 요약", ""]
    lines += [f"- {s}" for s in re.split(r"(?<=[.!?])\s+", plan["summary"].strip()) if s]
    lines += ["", "## 작업 순서", "", "| ID | 작업 | 선행 | 수정 범위 | 상태 |", "|---|---|---|---|---|"]
    for task in plan["tasks"]:
        lines.append(f"| {task['id']} | {cell(task['title'])} | {', '.join(task['depends_on']) or '-'} | "
                     f"{cell(', '.join(task['touch']))} | {'완료' if task['id'] in completed else '대기'} |")
    lines += ["", "작업별 완료 기준은 docs/TASKS.md에 있습니다."]
    return "\n".join(lines) + "\n"


class Halt(RuntimeError):
    pass


class Engine:
    def __init__(self, root, invoke=None):
        self.root = root.resolve()
        fs.snapshot(self.root)  # Reject symlinked control directories before writing any state.
        self.cfg = config.load(self.root)
        self.invoke = invoke or providers.invoke
        self.meta = self.root / ".fusion"
        self.state_path = self.meta / "state.json"
        self.deadline = None
        self.state = {}

    def time_left(self, limit):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise Halt("Total wall-time budget exhausted")
        return min(limit, remaining)

    def event(self, kind, **fields):
        item = {"time": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
        with (self.meta / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    def save(self):
        fs.atomic_json(self.state_path, self.state)
        docs = self.root / "docs"
        plan = self.state.get("plan")
        if plan:
            (docs / "PLAN.md").write_text(render_plan(plan, self.state["completed"]), encoding="utf-8")
            rows = ["# Tasks", ""]
            for task in plan["tasks"]:
                done = task["id"] in self.state["completed"]
                rows += [f"- [{'x' if done else ' '}] {task['id']}: {task['title']}",
                         f"  - touch: {', '.join(task['touch'])}",
                         *[f"  - acceptance: {a}" for a in task["acceptance"]]]
            (docs / "TASKS.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (docs / "MEMORY.md").write_text("# Recent working memory\n\n" + "\n\n".join(
            self.state.get("memory", [])[-5:]) + "\n", encoding="utf-8")

    def load_state(self, resume):
        tracked = ["harness.toml", "AGENTS.md", "docs/PRD.md"]
        if (self.root / config.AGENTS_FILE).is_file():  # absent for legacy projects: keeps old fingerprints valid
            tracked.append(config.AGENTS_FILE)
        fingerprint = hashlib.sha256(b"\0".join((self.root / p).read_bytes() for p in tracked)).hexdigest()
        if self.state_path.exists():
            if not resume:
                raise Halt("Existing run found. Use --resume to continue")
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state.get("fingerprint") != fingerprint:
                raise Halt("Config/instructions/PRD changed since the run. Preserve the old run and initialize a new project")
            if self.state.get("status") == "DONE" and self.state.get("digest") != fs.code_digest(self.root):
                raise Halt("Files changed after DONE; old completion is invalid. Initialize a new run in a copy")
        else:
            if resume:
                raise Halt("No run to resume")
            self.state = {"version": 1, "fingerprint": fingerprint, "status": "NEW", "plan": None,
                          "completed": [], "attempts": {}, "memory": [], "last_failure": None, "cycles": 0}
        self.save()

    def agent(self, role, task=None, evidence=None):
        token = uuid.uuid4().hex
        folder = self.meta / "runs" / token
        folder.mkdir(parents=True)
        prompt = context.build(self.root, role, self.state, token, task, evidence,
                               self.cfg["limits"]["context_chars"], self.cfg["acceptance"])
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        before = fs.snapshot(self.root)
        result = None
        failure = None
        try:
            result = self.invoke(self.cfg["agents"][role], role, prompt, self.root,
                                 self.time_left(self.cfg["limits"]["agent_timeout"]))
        except Exception as exc:
            failure = exc
        finally:
            after = fs.snapshot(self.root)
            changed = fs.changes(before, after)
            illegal = fs.violations(changed, role, task["touch"] if task else [],
                                    [self.cfg["acceptance"]] if self.cfg["acceptance"] else [])
            fs.atomic_json(folder / "changes.json", {"changed": changed, "violations": illegal,
                                                     "before": before, "after": after})
            self.event("agent", role=role, token=token, backend=self.cfg["agents"][role]["backend"],
                       model=self.cfg["agents"][role].get("model", "CLI default"),
                       effort=self.cfg["agents"][role].get("effort", "CLI default"),
                       prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                       seconds=result.get("seconds") if result else None,
                       usage=result.get("usage") if result else None,
                       cost_usd=result.get("cost_usd") if result else None,
                       changed=changed, error=str(failure) if failure else None)
        if illegal:
            raise Halt(f"{role} modified forbidden paths: {', '.join(illegal)}. Changes retained for inspection")
        self.guard_acceptance()
        if failure:
            raise failure
        fs.atomic_json(folder / "result.json", result)
        data = contracts.object_from(result["response"])
        if role == "planner":
            return contracts.plan(data)
        if role == "generator":
            contracts.keys(data, ("summary",))
            contracts.string(data["summary"])
            if len(data["summary"]) > 4000:
                raise contracts.ContractError("Implementation summary exceeds 4000 characters")
            self.state["memory"] = (self.state["memory"] + [task["id"] + ": " + data["summary"]])[-5:]
            with (self.root / "docs/IMPLEMENT.md").open("a", encoding="utf-8") as stream:
                stream.write(f"\n## {task['id']} / {token}\n\n{data['summary']}\n")
            return data
        return contracts.review(data, token, task["id"], task["acceptance"])

    def acceptance_digest(self):
        files = fs.tree_files(self.root, self.cfg["acceptance"])
        if not any(Path(p).name.lower() != "readme.md" for p in files):
            raise Halt(f"Acceptance folder '{self.cfg['acceptance']}' must contain human-written tests (not only README.md)")
        return fs.digest(files)

    def guard_acceptance(self):
        """Human-owned tests are pinned by content hash for the whole run, across resumes."""
        if not self.cfg["acceptance"]:
            return
        recorded = self.state.get("acceptance_digest")
        if recorded is None:
            self.state["acceptance_digest"] = self.acceptance_digest()
        elif self.acceptance_digest() != recorded:
            raise Halt(f"Acceptance tests changed since the run started: {self.cfg['acceptance']}/. "
                       "Restore them or start a new project folder")

    def run_setup(self):
        """Run human-declared preparation once; failure stops before any agent is called."""
        for step in self.cfg["setup"]:
            result = execute(config.argv(step["command"]), self.root,
                             self.time_left(step.get("timeout", config.DEFAULT_SETUP_TIMEOUT)))
            token = uuid.uuid4().hex
            result.update(name=step["name"], command=step["command"])
            fs.atomic_json(self.meta / "setup" / f"{token}.json", result)
            self.event("setup", token=token, name=step["name"], returncode=result["returncode"],
                       seconds=result["seconds"])
            if result["returncode"] != 0:
                detail = (result["stderr"] or result["stdout"]).strip()[-1000:]
                raise Halt(f"Setup '{step['name']}' failed ({result['returncode']}): {detail}")

    def prepare(self):
        self.guard_acceptance()
        if self.cfg["setup"] and not self.state.get("setup_done"):
            self.run_setup()
            self.state["setup_done"] = True
        self.save()

    def checks(self):
        results = []
        for check in self.cfg["checks"]:
            before = fs.snapshot(self.root)
            result = execute(config.argv(check["command"]), self.root,
                             self.time_left(self.cfg["limits"]["check_timeout"]))
            changed = fs.changes(before, fs.snapshot(self.root))
            illegal = [p for p in changed if not p.startswith(fs.BUILD_OUTPUTS)]
            result.update(name=check["name"], command=check["command"])
            token = uuid.uuid4().hex
            fs.atomic_json(self.meta / "checks" / f"{token}.json", result)
            self.event("check", token=token, name=check["name"], returncode=result["returncode"], seconds=result["seconds"])
            if illegal:
                raise Halt("Check changed project sources or controls: " + ", ".join(illegal))
            # Prompts carry tails; full bounded process output remains in the check artifact.
            self.guard_acceptance()
            results.append({**result, "stdout": result["stdout"][-6000:], "stderr": result["stderr"][-6000:]})
        fs.atomic_json(self.meta / "latest-checks.json", results)
        return results

    def assess(self, task):
        evidence = self.checks()
        review = self.agent("evaluator", task, evidence)
        fs.atomic_json(self.meta / "latest-review.json", review)
        (self.root / "docs/REVIEW.md").write_text(
            "# Review\n\n```json\n" + json.dumps(review, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")
        # Evaluator is read-only and source hashes were checked after its process returned.
        passed = contracts.gate(evidence, review)
        self.event("gate", task=task["id"], passed=passed)
        self.report(task, evidence, review, passed)
        if not passed:
            self.state["last_failure"] = {"task": task["id"], "review": review, "checks": evidence}
        return passed

    @staticmethod
    def report(task, evidence, review, passed):
        ok = sum(c["passed"] for c in review["criteria"])
        checks = ", ".join(f"{c['name']}={'ok' if c['returncode'] == 0 else c['returncode']}" for c in evidence)
        print(f"[{task['id']}] {'PASS' if passed else 'FAIL'}: verdict {review['verdict']}, "
              f"spec {review['spec_score']}/3, test {review['test_score']}/3, "
              f"criteria {ok}/{len(review['criteria'])}, checks {checks}", flush=True)
        for c in review["criteria"]:
            if not c["passed"]:
                print(f"  - failed: {c['criterion'][:200]}", flush=True)
        for issue in review["issues"]:
            print(f"  - issue: {issue[:200]}", flush=True)

    def publish(self, task):
        """Commit (and push) a passed task. Best effort: the gate already decided the outcome."""
        if not self.cfg["git"]["commit"]:
            return
        def git(*args):
            return execute(["git", *args], self.root, 120)
        def tail(result):
            return (result["stderr"] or result["stdout"]).strip()[-300:]
        excludes = [f":(exclude,glob)**/{name}/**" for name in fs.EXCLUDED]
        excludes += [f":(exclude){prefix.rstrip('/')}" for prefix in fs.BUILD_OUTPUTS]
        if git("rev-parse", "--is-inside-work-tree")["returncode"] != 0:
            note = "skipped: not a git repository"
        elif (added := git("add", "-A", "--", ".", *GIT_NEVER, *excludes))["returncode"] != 0:
            note = "add failed: " + tail(added)
        elif git("diff", "--cached", "--quiet")["returncode"] == 0:
            note = "nothing to commit"
        elif (committed := git("commit", "-m", f"{task['id']}: {task['title']}"))["returncode"] != 0:
            note = "commit failed: " + tail(committed)
        else:
            note = "committed " + git("rev-parse", "--short", "HEAD")["stdout"].strip()
            if self.cfg["git"]["push"]:
                remotes = git("remote")["stdout"].split()
                if not remotes:
                    note += "; push skipped: no remote"
                else:
                    remote = "origin" if "origin" in remotes else remotes[0]
                    pushed = git("push", "-u", remote, "HEAD")
                    note += f"; pushed to {remote}" if pushed["returncode"] == 0 else "; push failed: " + tail(pushed)
        self.event("git", task=task["id"], note=note)
        print(f"[{task['id']}] git: {note}", flush=True)

    def run(self, resume=False):
        self.deadline = time.monotonic() + self.cfg["limits"]["total_seconds"]
        with fs.project_lock(self.root):
            self.load_state(resume)
            self.state.pop("halt_kind", None)
            self.state.pop("retry_hint", None)
            try:
                prd = (self.root / "docs/PRD.md").read_text(encoding="utf-8")
                if "TODO:" in prd or len(prd.strip()) < 20:
                    raise Halt("Write concrete requirements in docs/PRD.md first")
                for warning in config.prd_warnings(prd):
                    print("WARNING: " + warning, flush=True)
                self.prepare()
                if not self.state["plan"]:
                    self.state["status"] = "PLANNING"
                    self.save()
                    self.state["plan"] = self.agent("planner")
                    self.save()
                if (self.state.get("last_failure") or {}).get("task") == "FINAL":
                    # A final integration failure reopens the whole plan on explicit resume.
                    self.state["completed"] = []
                cycles = 0
                for task in self.state["plan"]["tasks"]:
                    if task["id"] in self.state["completed"]:
                        continue
                    if not set(task["depends_on"]).issubset(self.state["completed"]):
                        raise Halt("Unsatisfied task dependencies")
                    while self.state["attempts"].get(task["id"], 0) < self.cfg["limits"]["max_attempts"]:
                        if cycles >= self.cfg["limits"]["max_cycles"]:
                            raise Halt("Per-invocation cycle limit reached; --resume continues pending work")
                        cycles += 1
                        self.state["cycles"] += 1
                        self.state["attempts"][task["id"]] = self.state["attempts"].get(task["id"], 0) + 1
                        self.state["status"] = "IMPLEMENTING"
                        self.state["active"] = task["id"]
                        self.save()
                        print(f"[{task['id']}] attempt {self.state['attempts'][task['id']]}: {task['title']}", flush=True)
                        try:
                            self.agent("generator", task)
                            self.state["status"] = "VERIFYING"
                            self.save()
                            passed = self.assess(task)
                        except providers.UsageLimitError:
                            # A usage limit is not a failed attempt; do not spend the retry budget on it.
                            self.state["attempts"][task["id"]] -= 1
                            self.state["cycles"] -= 1
                            raise
                        if passed:
                            self.state["completed"].append(task["id"])
                            self.state["last_failure"] = None
                            self.save()
                            self.publish(task)
                            break
                        self.save()
                    if task["id"] not in self.state["completed"]:
                        raise Halt(f"{task['id']}: retry budget exhausted; inspect review and preserve this run")
                final = {"id": "FINAL", "title": "Whole-project acceptance", "touch": [],
                         "acceptance": [f"{t['id']}: {a}" for t in self.state["plan"]["tasks"] for a in t["acceptance"]]}
                self.state["status"] = "FINAL_CHECK"
                self.save()
                if not self.assess(final):
                    raise Halt("Final integration review failed; --resume reopens tasks within remaining retry budgets")
                self.state["status"] = "DONE"
                self.state["last_failure"] = None
                self.state["digest"] = fs.code_digest(self.root)
                self.save()
                self.event("done", digest=self.state["digest"])
                print("DONE: tests + task reviews + final integration review passed.", flush=True)
                self.publish(final)
                return 0
            except (Exception, KeyboardInterrupt) as exc:
                self.state["status"] = "HALTED"
                self.state["reason"] = "Interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc)
                if isinstance(exc, providers.UsageLimitError):
                    self.state["halt_kind"] = "usage_limit"
                    self.state["retry_hint"] = exc.hint
                    when = f" Retry after {exc.hint}." if exc.hint else ""
                    self.state["reason"] = (f"USAGE_LIMIT: {exc}.{when} Progress is saved; "
                                            "run again with --resume after the limit resets.")
                self.save()
                self.event("halt", reason=self.state["reason"])
                print("HALTED: " + self.state["reason"], flush=True)
                return 130 if isinstance(exc, KeyboardInterrupt) else 2


def usage_summary(root):
    """Per-role calls, seconds and (when the CLI reports them) Claude tokens/cost, from events.jsonl."""
    path = root / ".fusion" / "events.jsonl"
    summary = {}
    if not path.is_file():
        return summary
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("kind") != "agent":
            continue
        item = summary.setdefault(event["role"], {"calls": 0, "seconds": 0.0})
        item["calls"] += 1
        item["seconds"] = round(item["seconds"] + (event.get("seconds") or 0), 3)
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = (event.get("usage") or {}).get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                item[key] = item.get(key, 0) + value
        if isinstance(event.get("cost_usd"), (int, float)):
            item["cost_usd"] = round(item.get("cost_usd", 0) + event["cost_usd"], 6)
    return summary

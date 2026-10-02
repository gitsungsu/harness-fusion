"""State machine owns completion; models supply proposals and evidence."""
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from . import config, context, contracts, filesystem as fs, providers
from .process import execute


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
            (docs / "PLAN.md").write_text("# Plan\n\n" + plan["summary"] + "\n", encoding="utf-8")
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
        fingerprint = hashlib.sha256(b"\0".join((self.root / p).read_bytes()
            for p in ("harness.toml", "AGENTS.md", "docs/PRD.md"))).hexdigest()
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
                               self.cfg["limits"]["context_chars"])
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
            illegal = fs.violations(changed, role, task["touch"] if task else [])
            fs.atomic_json(folder / "changes.json", {"changed": changed, "violations": illegal,
                                                     "before": before, "after": after})
            self.event("agent", role=role, token=token, backend=self.cfg["agents"][role]["backend"],
                       model=self.cfg["agents"][role].get("model", "CLI default"),
                       prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                       seconds=result.get("seconds") if result else None,
                       usage=result.get("usage") if result else None,
                       cost_usd=result.get("cost_usd") if result else None,
                       changed=changed, error=str(failure) if failure else None)
        if illegal:
            raise Halt(f"{role} modified forbidden paths: {', '.join(illegal)}. Changes retained for inspection")
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

    def checks(self):
        results = []
        for check in self.cfg["checks"]:
            before = fs.snapshot(self.root)
            result = execute(config.argv(check["command"]), self.root,
                             self.time_left(self.cfg["limits"]["check_timeout"]))
            changed = fs.changes(before, fs.snapshot(self.root))
            illegal = [p for p in changed if not p.startswith(("dist/", "build/", ".next/", "coverage/"))]
            result.update(name=check["name"], command=check["command"])
            token = uuid.uuid4().hex
            fs.atomic_json(self.meta / "checks" / f"{token}.json", result)
            self.event("check", token=token, name=check["name"], returncode=result["returncode"], seconds=result["seconds"])
            if illegal:
                raise Halt("Check changed project sources or controls: " + ", ".join(illegal))
            # Prompts carry tails; full bounded process output remains in the check artifact.
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
        if not passed:
            self.state["last_failure"] = {"task": task["id"], "review": review, "checks": evidence}
        return passed

    def run(self, resume=False):
        self.deadline = time.monotonic() + self.cfg["limits"]["total_seconds"]
        with fs.project_lock(self.root):
            self.load_state(resume)
            try:
                prd = (self.root / "docs/PRD.md").read_text(encoding="utf-8")
                if "TODO:" in prd or len(prd.strip()) < 20:
                    raise Halt("Write concrete requirements in docs/PRD.md first")
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
                        self.agent("generator", task)
                        self.state["status"] = "VERIFYING"
                        self.save()
                        if self.assess(task):
                            self.state["completed"].append(task["id"])
                            self.state["last_failure"] = None
                            self.save()
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
                return 0
            except (Exception, KeyboardInterrupt) as exc:
                self.state["status"] = "HALTED"
                self.state["reason"] = "Interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc)
                self.save()
                self.event("halt", reason=self.state["reason"])
                print("HALTED: " + self.state["reason"], flush=True)
                return 130 if isinstance(exc, KeyboardInterrupt) else 2

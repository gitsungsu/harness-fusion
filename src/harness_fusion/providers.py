"""Use existing logged-in CLIs; never add permission-bypass flags."""
import os
import tempfile
from pathlib import Path

from .config import argv
from .contracts import ContractError, object_from
from .process import execute


def command_for(cfg, role, output=None):
    if cfg["backend"] == "command":
        return argv(cfg["command"])
    if cfg["backend"] == "codex":
        cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox",
               "workspace-write" if role == "generator" else "read-only",
               "--output-last-message", str(output)]
        if cfg.get("model"):
            cmd += ["--model", cfg["model"]]
        return cmd + ["-"]
    available = "Read,Glob,Grep,Edit,Write" if role == "generator" else "Read,Glob,Grep"
    cmd = ["claude", "-p", "--output-format", "json", "--tools", available,
           "--allowedTools", available]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    return cmd


def failure_detail(stderr):
    """Codex echoes the whole prompt to stderr; surface its ERROR lines instead of the tail."""
    errors = list(dict.fromkeys(line.strip() for line in stderr.splitlines()
                                if line.strip().startswith("ERROR")))
    return "\n".join(errors)[-2000:] if errors else stderr[-2000:]


def invoke(cfg, role, prompt, root, timeout):
    with tempfile.TemporaryDirectory(prefix="fusion-agent-") as tmp:
        output = Path(tmp) / "result.json"
        env = dict(os.environ, HARNESS_ROLE=role)
        result = execute(command_for(cfg, role, output), root, timeout, prompt, env)
        if result["returncode"] != 0:
            raise RuntimeError(f"{role} process failed ({result['returncode']}): {failure_detail(result['stderr'])}")
        if cfg["backend"] == "codex":
            if not output.is_file() or output.stat().st_size > 1024 * 1024:
                raise ContractError("Missing or oversized Codex final response")
            result["response"] = output.read_text(encoding="utf-8")
        elif cfg["backend"] == "claude":
            envelope = object_from(result["stdout"])
            if envelope.get("is_error") or not isinstance(envelope.get("result"), str):
                raise ContractError("Claude returned an error or no final result")
            result["response"] = envelope["result"]
            result["usage"] = envelope.get("usage")
            result["cost_usd"] = envelope.get("total_cost_usd")
        else:
            result["response"] = result["stdout"]
        return result

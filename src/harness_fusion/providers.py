"""Use existing logged-in CLIs; never add permission-bypass flags."""
import os
import re
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
        if cfg.get("effort"):
            cmd += ["-c", f'model_reasoning_effort="{cfg["effort"]}"']
        return cmd + ["-"]
    available = "Read,Glob,Grep,Edit,Write" if role == "generator" else "Read,Glob,Grep"
    cmd = ["claude", "-p", "--output-format", "json", "--tools", available,
           "--allowedTools", available]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    if cfg.get("effort"):
        cmd += ["--effort", cfg["effort"]]
    return cmd


def failure_detail(stderr):
    """Codex echoes the whole prompt to stderr; surface its ERROR lines instead of the tail."""
    errors = list(dict.fromkeys(line.strip() for line in stderr.splitlines()
                                if line.strip().startswith("ERROR")))
    return "\n".join(errors)[-2000:] if errors else stderr[-2000:]


class UsageLimitError(RuntimeError):
    """The CLI account hit its usage limit; progress is safe and the run can be resumed later."""

    def __init__(self, message, hint=""):
        super().__init__(message)
        self.hint = hint


# Best-effort: CLI wording can change between versions. Unrecognized failures stay ordinary failures.
LIMIT_PATTERN = re.compile(r"usage limit|hit your (?:usage )?limit|quota (?:exceeded|exhausted)", re.I)
RELEASE_PATTERN = re.compile(r"(?:try again at|resets?(?: at)?)\s+(\d{1,2}(?::\d{2})?\s*(?:[ap]m)?)", re.I)


def usage_limit_hint(text):
    """None if the text is not a usage-limit error, else the announced release time ('' if none)."""
    if not LIMIT_PATTERN.search(text):
        return None
    release = RELEASE_PATTERN.search(text)
    return release.group(1).strip() if release else ""


def limit_error(role, text):
    hint = usage_limit_hint(text)
    if hint is None:
        return None
    line = next((x.strip() for x in text.splitlines() if LIMIT_PATTERN.search(x)), text.strip())
    return UsageLimitError(f"{role} hit the AI usage limit: {line[:300]}", hint)


def invoke(cfg, role, prompt, root, timeout):
    with tempfile.TemporaryDirectory(prefix="fusion-agent-") as tmp:
        output = Path(tmp) / "result.json"
        env = dict(os.environ, HARNESS_ROLE=role)
        result = execute(command_for(cfg, role, output), root, timeout, prompt, env)
        if result["returncode"] != 0:
            detail = failure_detail(result["stderr"])
            if cfg["backend"] == "claude":
                try:
                    detail += "\n" + str(object_from(result["stdout"]).get("result", ""))
                except ContractError:
                    pass
            limit = limit_error(role, detail)
            if limit:
                raise limit
            raise RuntimeError(f"{role} process failed ({result['returncode']}): {failure_detail(result['stderr'])}")
        if cfg["backend"] == "codex":
            if not output.is_file() or output.stat().st_size > 1024 * 1024:
                raise ContractError("Missing or oversized Codex final response")
            result["response"] = output.read_text(encoding="utf-8")
        elif cfg["backend"] == "claude":
            envelope = object_from(result["stdout"])
            if envelope.get("is_error") or not isinstance(envelope.get("result"), str):
                limit = limit_error(role, str(envelope.get("result", "")))
                if limit:
                    raise limit
                raise ContractError("Claude returned an error or no final result")
            result["response"] = envelope["result"]
            result["usage"] = envelope.get("usage")
            result["cost_usd"] = envelope.get("total_cost_usd")
        else:
            result["response"] = result["stdout"]
        return result

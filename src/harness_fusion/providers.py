"""Use existing logged-in CLIs; never add permission-bypass flags."""
import os
import re
import shutil
import tempfile
from pathlib import Path

from .config import argv
from .contracts import ContractError, object_from
from .process import execute

AGY_INSTRUCTION = ("Read the file {path} in full and follow the instructions inside it exactly. "
                   "Your final answer must be only what that file asks for, with no extra prose.")


def agy_executable():
    """agy is often not on PATH; its installer puts it in ~/.gemini/bin."""
    found = shutil.which("agy")
    if found:
        return found
    home = Path.home() / ".gemini" / "bin"
    for name in ("agy.exe", "agy"):
        if (home / name).is_file():
            return str(home / name)
    return "agy"  # not found; resolve_command reports "Executable not found: agy"


def command_for(cfg, role, output=None, prompt_file=None):
    if cfg["backend"] == "command":
        return argv(cfg["command"])
    if cfg["backend"] == "agy":
        # --mode plan blocks edits and commands in headless mode (verified); accept-edits allows file edits only.
        # -p takes the prompt as its value and cannot read stdin, so the prompt lives in a file agy may read.
        cmd = [agy_executable(), "--output-format", "json",
               "--mode", "accept-edits" if role == "generator" else "plan"]
        if cfg.get("model"):
            cmd += ["--model", cfg["model"]]
        if cfg.get("effort"):
            cmd += ["--effort", cfg["effort"]]
        if prompt_file is not None:
            path = Path(prompt_file)
            cmd += ["--add-dir", str(path.parent), "-p=" + AGY_INSTRUCTION.format(path=path)]
        return cmd
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
        if cfg["backend"] == "agy":
            prompt_file = Path(tmp) / "prompt.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            result = execute(command_for(cfg, role, prompt_file=prompt_file), root, timeout, "", env)
        else:
            result = execute(command_for(cfg, role, output), root, timeout, prompt, env)
        if result["returncode"] != 0:
            detail = failure_detail(result["stderr"])
            if cfg["backend"] == "claude":
                try:
                    detail += "\n" + str(object_from(result["stdout"]).get("result", ""))
                except ContractError:
                    pass
            elif cfg["backend"] == "agy":
                detail += "\n" + result["stdout"][-2000:]
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
        elif cfg["backend"] == "agy":
            envelope = object_from(result["stdout"])
            response = envelope.get("response")
            if envelope.get("status") != "SUCCESS" or not isinstance(response, str) or not response.strip():
                limit = limit_error(role, f"{response or ''}\n{result['stderr']}")
                if limit:
                    raise limit
                denied = ", ".join(str(x.get("display_name") or x.get("action"))
                                   for x in envelope.get("denied_actions") or [] if isinstance(x, dict))
                reason = f"; headless mode auto-denied: {denied}" if denied else ""
                raise ContractError(f"agy returned status {envelope.get('status')!r} with no final result{reason}")
            result["response"] = response
            usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
            result["usage"] = {key: usage[key] for key in ("input_tokens", "output_tokens") if key in usage}
        else:
            result["response"] = result["stdout"]
        return result

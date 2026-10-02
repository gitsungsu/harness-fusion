"""Argument-array execution with bounded reads and process-tree cancellation."""
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path


def resolve_command(command):
    """Resolve supported npm shims to Node entrypoints, never a command shell."""
    command = list(command)
    program = shutil.which(command[0])
    if program is None:
        raise FileNotFoundError(f"Executable not found: {command[0]}")
    path = Path(program)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        entries = {"codex": "@openai/codex/bin/codex.js",
                   "npm": "npm/bin/npm-cli.js", "npx": "npm/bin/npx-cli.js"}
        entry = entries.get(path.stem.lower())
        script = path.parent / "node_modules" / entry if entry else None
        local_node = path.parent / "node.exe"
        node = str(local_node) if local_node.is_file() else shutil.which("node")
        if script is None or not script.is_file() or not node:
            raise OSError(f"Cannot execute shell wrapper safely: {path}. Configure a native executable or Node entrypoint")
        return [node, str(script), *command[1:]]
    return [program, *command[1:]]


def stop(process, job=None):
    if os.name == "nt":
        if job is not None:
            job.terminate()
        else:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def execute(command, root, timeout, prompt="", env=None):
    started = time.monotonic()
    job = None
    process = None
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            command = resolve_command(command)
            if os.name == "nt":
                from .windows_job import Job
                job = Job()
            process = subprocess.Popen(command, cwd=root, stdin=subprocess.PIPE,
                                       stdout=stdout, stderr=stderr, env=env,
                                       start_new_session=os.name != "nt",
                                       creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | 0x4) if os.name == "nt" else 0)
            if job is not None:
                job.attach_and_resume(process)
        except OSError as exc:
            if process is not None:
                process.kill()
                process.wait()
                process.stdin.close()
            if job is not None:
                job.close()
            return {"returncode": 127, "stdout": "", "stderr": str(exc), "seconds": 0}
        try:
            process.communicate(prompt.encode("utf-8"), timeout=max(0.01, timeout))
            code = process.returncode
        except subprocess.TimeoutExpired:
            stop(process, job)
            code = 124
        except BaseException:
            stop(process, job)
            raise
        finally:
            if job is not None:
                job.close()
        stdout.seek(0, 2)
        size = stdout.tell()
        stdout.seek(0)
        out = stdout.read(1024 * 1024).decode("utf-8", errors="replace")
        if size > 1024 * 1024:
            code = 125
        stderr.seek(0, 2)
        stderr.seek(max(0, stderr.tell() - 32000))
        err = stderr.read().decode("utf-8", errors="replace")
    if code == 124:
        err += "\nProcess timeout"
    if code == 125:
        err += "\nOutput exceeded 1 MiB protocol limit"
    return {"returncode": code, "stdout": out, "stderr": err,
            "seconds": round(time.monotonic() - started, 3)}

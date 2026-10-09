"""Validate untrusted model output. Missing evidence never implies success."""
import json
import re
from pathlib import PurePosixPath


class ContractError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _trailing_object(text):
    """A JSON object that ends the text after progress prose (agents sometimes narrate before answering)."""
    if text.endswith("```"):
        text = text[:-3].rstrip()
    decoder = json.JSONDecoder(object_pairs_hook=_unique)
    for match in re.finditer(r"\{", text):
        try:
            result, end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict) and not text[end:].strip():
            return result
    return None


def object_from(text):
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    try:
        result = json.loads(text, object_pairs_hook=_unique)
    except ContractError:
        raise
    except (ValueError, TypeError) as exc:
        result = _trailing_object(text) if isinstance(text, str) else None
        if result is None:
            raise ContractError(f"Expected one JSON object: {exc}") from exc
    if not isinstance(result, dict):
        raise ContractError("Expected JSON object")
    return result


def keys(data, expected):
    if not isinstance(data, dict) or set(data) != set(expected):
        raise ContractError(f"Required exact keys: {', '.join(expected)}")


def string(value):
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Nonempty string required")
    return value


def strings(value):
    if not isinstance(value, list) or not value:
        raise ContractError("Nonempty string list required")
    for item in value:
        string(item)
    if len(set(value)) != len(value):
        raise ContractError("Duplicate list entries")
    return value


def path_rule(value):
    string(value)
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or "\\" in value
            or ":" in value or value in (".", "*", "**", "**/*")
            or value.startswith((".git", ".fusion", ".env"))):
        raise ContractError(f"Unsafe or overly broad path: {value}")
    return value


def plan(data):
    keys(data, ("summary", "tasks"))
    string(data["summary"])
    if not isinstance(data["tasks"], list) or not 1 <= len(data["tasks"]) <= 30:
        raise ContractError("Plan must have 1–30 tasks")
    seen = set()
    for task in data["tasks"]:
        keys(task, ("id", "title", "depends_on", "touch", "acceptance"))
        if not isinstance(task["id"], str) or not re.fullmatch(r"T[1-9][0-9]*", task["id"]):
            raise ContractError("Task id must be T1, T2, ...")
        if task["id"] in seen:
            raise ContractError("Duplicate task id")
        string(task["title"])
        deps = task["depends_on"]
        if not isinstance(deps, list) or any(not isinstance(x, str) or x not in seen for x in deps):
            raise ContractError("Dependencies must refer to earlier tasks")
        for rule in strings(task["touch"]):
            path_rule(rule)
        strings(task["acceptance"])
        seen.add(task["id"])
    return data


def review(data, token, task_id, acceptance):
    keys(data, ("token", "task_id", "verdict", "spec_score", "test_score", "criteria", "issues"))
    if data["token"] != token or data["task_id"] != task_id:
        raise ContractError("Stale or mismatched review")
    if data["verdict"] not in ("PASS", "FAIL", "BLOCKED"):
        raise ContractError("Invalid verdict")
    for score in ("spec_score", "test_score"):
        if type(data[score]) is not int or not 0 <= data[score] <= 3:
            raise ContractError("Scores must be integers 0–3")
    if not isinstance(data["issues"], list):
        raise ContractError("issues must be a list")
    for issue in data["issues"]:
        string(issue)
    criteria = data["criteria"]
    if not isinstance(criteria, list) or len(criteria) != len(acceptance):
        raise ContractError("Every acceptance criterion must be reviewed")
    for item, criterion in zip(criteria, acceptance):
        keys(item, ("criterion", "passed", "evidence"))
        if item["criterion"] != criterion or type(item["passed"]) is not bool:
            raise ContractError("Criterion mismatch or non-boolean result")
        string(item["evidence"])
    return data


def gate(checks, assessment):
    return bool(checks) and all(x["returncode"] == 0 for x in checks) and (
        assessment["verdict"] == "PASS" and assessment["spec_score"] >= 2
        and assessment["test_score"] >= 2 and not assessment["issues"]
        and all(x["passed"] for x in assessment["criteria"]))

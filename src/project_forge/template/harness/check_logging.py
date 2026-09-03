from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "backend/src/app"
EVENT_PATTERN = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)+$")
OUTCOMES = frozenset({"success", "failed", "rejected", "retry", "skipped", "unknown"})
SENSITIVE_FIELD = re.compile(
    r"(?:authorization|body|cookie|credential|database_url|headers|parameters|"
    r"password|payload|private_key|query|secret|session|sql|token)",
    re.IGNORECASE,
)
DIRECT_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "error", "exception", "critical", "log"}
)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_static_message(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _event_is_static(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return EVENT_PATTERN.fullmatch(node.value) is not None
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LogEvent"
    ) or (
        isinstance(node, ast.IfExp)
        and _event_is_static(node.body)
        and _event_is_static(node.orelse)
    )


def _outcome_is_static(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in OUTCOMES
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LogOutcome"
    ) or (
        isinstance(node, ast.IfExp)
        and _outcome_is_static(node.body)
        and _outcome_is_static(node.orelse)
    )


def scan(path: Path) -> list[str]:
    relative = path.relative_to(APP_ROOT)
    if relative.parts[0] == "observability":
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        return [f"{path}:{error.lineno}: cannot validate logging in invalid Python"]
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if isinstance(node.func, ast.Attribute) and name in DIRECT_LOG_METHODS:
            problems.append(
                f"{path}:{node.lineno}: use log_event/log_exception instead of direct logger calls"
            )
            continue
        if name not in {"log_event", "log_exception"}:
            continue
        message_index = 2 if name == "log_event" else 1
        message = node.args[message_index] if len(node.args) > message_index else None
        if not _is_static_message(message):
            problems.append(f"{path}:{node.lineno}: log message must be a static string")
        keywords = {item.arg: item.value for item in node.keywords if item.arg is not None}
        if any(item.arg is None for item in node.keywords):
            problems.append(
                f"{path}:{node.lineno}: structured log fields must be explicit keywords"
            )
        if not _event_is_static(keywords.get("event")):
            problems.append(
                f"{path}:{node.lineno}: event must be a LogEvent member or static dotted name"
            )
        if not _outcome_is_static(keywords.get("outcome")):
            problems.append(
                f"{path}:{node.lineno}: outcome must be a LogOutcome member or supported literal"
            )
        for field in keywords:
            if field not in {"error", "event", "outcome"} and SENSITIVE_FIELD.search(field):
                problems.append(
                    f"{path}:{node.lineno}: sensitive structured log field is forbidden: {field}"
                )
    return problems


def main() -> int:
    if not APP_ROOT.exists():
        return 0
    problems: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        problems.extend(scan(path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

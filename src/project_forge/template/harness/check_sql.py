from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_WORDS = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.IGNORECASE)
FORBIDDEN_TEXT = ("async" + "pg", "$1", "$2")


def scan(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = [f"{path}: forbidden token {token!r}" for token in FORBIDDEN_TEXT if token in text]
    if "/db/migrations/" in path.as_posix():
        return problems
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if SQL_WORDS.search(literal):
                problems.append(f"{path}:{node.lineno}: SQL f-string is forbidden")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "execute" and node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str) and SQL_WORDS.search(value):
                    problems.append(f"{path}:{node.lineno}: wrap executable SQL with psycopg.sql.SQL")
    return problems


def main() -> int:
    backend = ROOT / "backend/src"
    if not backend.exists():
        return 0
    problems: list[str] = []
    for path in backend.rglob("*.py"):
        problems.extend(scan(path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

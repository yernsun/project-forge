from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
STATIC_TRANSLATION = re.compile(
    r"(?<![A-Za-z0-9_$.])(?:\$t|t)\s*\(\s*['\"]([^'\"]+)['\"]"
)


def flatten(value: dict[str, object], prefix: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten(child, path))  # type: ignore[arg-type]
        else:
            if not isinstance(child, str):
                raise TypeError(f"translation leaf must be a string: {path}")
            result[path] = child
    return result


def load(path: Path) -> dict[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"locale root must be an object: {path}")
    return flatten(value)


def main() -> int:
    locales = ROOT / "frontend/src/shared/i18n/locales"
    if not locales.exists():
        return 0
    try:
        zh = load(locales / "zh-CN.json")
        en = load(locales / "en-US.json")
    except (OSError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    problems: list[str] = []
    if zh.keys() != en.keys():
        problems.append(f"missing in zh-CN: {sorted(en.keys() - zh.keys())}")
        problems.append(f"missing in en-US: {sorted(zh.keys() - en.keys())}")
    for key in sorted(zh.keys() & en.keys()):
        if not zh[key].strip() or not en[key].strip():
            problems.append(f"empty translation: {key}")
        if set(PLACEHOLDER.findall(zh[key])) != set(PLACEHOLDER.findall(en[key])):
            problems.append(f"placeholder mismatch: {key}")

    used: set[str] = set()
    source = ROOT / "frontend/src"
    for suffix in ("*.ts", "*.vue"):
        for path in source.rglob(suffix):
            used.update(STATIC_TRANSLATION.findall(path.read_text(encoding="utf-8")))
    missing = used - zh.keys()
    if missing:
        problems.append(f"static translation keys missing from locales: {sorted(missing)}")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

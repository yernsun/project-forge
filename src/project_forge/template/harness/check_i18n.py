from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def flatten(value: dict[str, Any], prefix: str = "") -> set[str]:
    result: set[str] = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            result.update(flatten(child, path))
        else:
            result.add(path)
    return result


def main() -> int:
    locales = ROOT / "frontend/src/shared/i18n/locales"
    if not locales.exists():
        return 0
    zh = flatten(json.loads((locales / "zh-CN.json").read_text(encoding="utf-8")))
    en = flatten(json.loads((locales / "en-US.json").read_text(encoding="utf-8")))
    if zh != en:
        print(f"missing in zh-CN: {sorted(en - zh)}", file=sys.stderr)
        print(f"missing in en-US: {sorted(zh - en)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

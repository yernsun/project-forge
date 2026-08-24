from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import app


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: export_openapi.py OUTPUT", file=sys.stderr)
        return 2
    output = Path(sys.argv[1])
    output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

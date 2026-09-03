from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

CURRENT_STATE_SCHEMA_VERSION = 3
TEMPLATE_DIGEST_PREFIX = "sha256:"


@lru_cache
def current_template_digest() -> str:
    """Return a deterministic identity for the packaged template payload."""

    template = Path(__file__).resolve().parent / "template"
    digest = hashlib.sha256()
    for path in sorted(template.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(template).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"{TEMPLATE_DIGEST_PREFIX}{digest.hexdigest()}"

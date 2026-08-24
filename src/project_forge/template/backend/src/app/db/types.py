from __future__ import annotations

from typing import Any, TypeAlias

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

DbRow: TypeAlias = dict[str, Any]
DbConnection: TypeAlias = AsyncConnection[DbRow]
DbPool: TypeAlias = AsyncConnectionPool[DbConnection]

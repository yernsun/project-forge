from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

type DbRow = dict[str, Any]
type DbConnection = AsyncConnection[DbRow]
type DbPool = AsyncConnectionPool[DbConnection]

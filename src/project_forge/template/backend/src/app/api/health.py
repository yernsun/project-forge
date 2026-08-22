from __future__ import annotations

from fastapi import APIRouter, Request
from psycopg import sql
from pydantic import Field

from app.api.models import StrictApiModel

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(StrictApiModel):
    status: str = Field(description="Current health state")


@router.get("/live")
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready")
async def readiness(request: Request) -> HealthResponse:
    pool = request.app.state.database_pool
    async with pool.connection() as connection, connection.cursor() as cursor:
        await cursor.execute(sql.SQL("SELECT 1"))
    return HealthResponse(status="ready")

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request, Response

from app.uow.factory import UnitOfWorkFactory


def get_unit_of_work_factory(request: Request) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, request.app.state.unit_of_work_factory)


def prevent_auth_caching(response: Response) -> None:
    """Keep authenticated and authentication-related responses out of caches."""

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


UnitOfWorkFactoryDep = Annotated[UnitOfWorkFactory, Depends(get_unit_of_work_factory)]

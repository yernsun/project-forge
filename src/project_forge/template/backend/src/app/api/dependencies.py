from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.uow.factory import UnitOfWorkFactory


def get_unit_of_work_factory(request: Request) -> UnitOfWorkFactory:
    return cast(UnitOfWorkFactory, request.app.state.unit_of_work_factory)


UnitOfWorkFactoryDep = Annotated[UnitOfWorkFactory, Depends(get_unit_of_work_factory)]

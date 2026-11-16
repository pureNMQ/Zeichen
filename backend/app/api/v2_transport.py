"""Shared error and transaction behavior for v2 Web adapters."""

from collections.abc import Callable

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from ..errors import invalid_request


class V2Route(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handle(request)
            except RequestValidationError as error:
                fields = {
                    str(issue["loc"][-1])[:64] for issue in error.errors()[:8] if issue.get("loc")
                }
                raise invalid_request(f"参数无效：{', '.join(sorted(fields))}") from error

        return validated


def commit_command(db: Session, command: Callable[[], dict]) -> dict:
    try:
        receipt = command()
        db.commit()
        return receipt
    except Exception:
        db.rollback()
        raise

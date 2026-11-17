"""Web adapter for project-scoped modular search."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import invalid_request
from ..models import User
from ..services.pagination import DEFAULT_PAGE_SIZE
from ..v2.resource_refs import parse_uuid
from ..v2.search import SearchDomain, SearchResult, search_project
from .deps import current_user


class SearchRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handle(request)
            except RequestValidationError as error:
                fields = {str(issue["loc"][-1])[:64] for issue in error.errors()[:8] if issue.get("loc")}
                raise invalid_request(f"检索参数无效：{', '.join(sorted(fields))}") from error

        return validated


router = APIRouter(prefix="/api/v2/projects", tags=["project search"], route_class=SearchRoute)


@router.get("/{project_id}/search")
def search(
    project_id: str, q: str, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
    domains: Annotated[list[SearchDomain] | None, Query(alias="domain")] = None,
    cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
) -> SearchResult:
    return search_project(db, actor, parse_uuid(project_id, "project_id"), query=q, domains=domains, cursor=cursor, limit=limit)

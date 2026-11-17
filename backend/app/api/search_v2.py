"""Web adapter for project-scoped modular search."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services.pagination import DEFAULT_PAGE_SIZE
from ..v2.resource_refs import parse_uuid
from ..v2.search import SearchDomain, SearchResult, search_project
from ..v2.search_filters import SearchFilters
from .deps import current_user
from .v2_transport import V2Route


class SearchParameters(SearchFilters):
    q: str = ""
    domain: list[SearchDomain] | None = None
    include_project: list[str] | None = None
    cursor: str | None = None
    limit: int = DEFAULT_PAGE_SIZE


router = APIRouter(prefix="/api/v2/projects", tags=["project search"], route_class=V2Route)


@router.get("/{project_id}/search")
def search(
    project_id: str, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
    params: Annotated[SearchParameters, Query()],
) -> SearchResult:
    filters = SearchFilters.model_validate(params.model_dump(include=set(SearchFilters.model_fields)))
    return search_project(
        db, actor, parse_uuid(project_id, "project_id"), query=params.q, domains=params.domain,
        cursor=params.cursor, limit=params.limit, filters=filters,
        additional_project_ids=[parse_uuid(selected, "include_project") for selected in params.include_project or []],
    )

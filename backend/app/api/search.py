"""全局搜索 API(规格书 §4.2 search.query 的 HTTP 面,与 MCP 同一后端)。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import invalid_request
from ..models import User
from ..services import search as service
from .deps import current_user

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(min_length=1, max_length=200),
    domain: list[str] | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
    cursor: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    valid = {"requirement", "task", "document"}
    if domain and any(d not in valid for d in domain):
        raise invalid_request(f"不支持的搜索域,可选:{', '.join(sorted(valid))}")
    domains = list(domain) if domain else None
    return service.search(db, user, q, domains, cursor=cursor, limit=limit)

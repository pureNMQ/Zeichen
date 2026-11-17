"""Search the v2 project read models without changing the legacy all-project tool."""

from mcp.types import ToolAnnotations
from pydantic import StrictInt

from ..services.pagination import DEFAULT_PAGE_SIZE
from ..v2.resource_refs import parse_uuid
from ..v2.search import SearchDomain, SearchResult, search_project
from ..v2.search_filters import SearchFilters
from .tools import dbc, sessioned


def register_search_tools(mcp) -> None:
    @mcp.tool(name="search.project", annotations=ToolAnnotations(
        readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=False,
    ))
    @sessioned
    def search(project_id: str, query: str = "", domains: list[SearchDomain] | None = None,
               cursor: str | None = None, limit: StrictInt = DEFAULT_PAGE_SIZE,
               additional_project_ids: list[str] | None = None, filters: SearchFilters | None = None) -> SearchResult:
        """检索需求、当前有效时间轴、Wiki 和文件。默认仅检索 project_id，可显式选择有权访问的其他项目。
        query 与 filters 至少提供一项，from_at 含边界、to_at 不含边界。每域独立分页，续页时保留范围和筛选、
        选一个域并传其 next_cursor。
        """
        db, actor = dbc()
        return search_project(
            db, actor, parse_uuid(project_id, "project_id"), query=query, domains=domains, cursor=cursor,
            limit=limit, filters=filters, additional_project_ids=[
                parse_uuid(selected, "additional_project_ids") for selected in additional_project_ids or []
            ],
        )

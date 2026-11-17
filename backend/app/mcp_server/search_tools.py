"""Search the v2 project read models without changing the legacy all-project tool."""

from mcp.types import ToolAnnotations
from pydantic import StrictInt

from ..services.pagination import DEFAULT_PAGE_SIZE
from ..v2.resource_refs import parse_uuid
from ..v2.search import SearchDomain, SearchResult, search_project
from .tools import dbc, sessioned


def register_search_tools(mcp) -> None:
    @mcp.tool(name="search.project", annotations=ToolAnnotations(
        readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=False,
    ))
    @sessioned
    def search(project_id: str, query: str, domains: list[SearchDomain] | None = None,
               cursor: str | None = None, limit: StrictInt = DEFAULT_PAGE_SIZE) -> SearchResult:
        """按项目检索需求、当前有效时间轴、Wiki 和文件。每域分页独立，续页时选一个域并传其 next_cursor。"""
        db, actor = dbc()
        return search_project(db, actor, parse_uuid(project_id, "project_id"), query=query, domains=domains, cursor=cursor, limit=limit)

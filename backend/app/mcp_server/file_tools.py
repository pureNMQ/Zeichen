"""v2 file capability tools backed by the same service as the HTTP routes."""

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.types import ToolAnnotations

from ..errors import unauthorized
from ..v2.files import issue_read_grant, issue_upload_grant
from ..v2.resource_refs import parse_uuid
from .tools import dbc, sessioned


def _api_key_id():
    auth = auth_context_var.get()
    if auth is None:
        raise unauthorized("缺少有效 API key")
    return parse_uuid(auth.access_token.client_id, "api_key_id")


def register_file_tools(mcp) -> None:
    @mcp.tool(name="files.authorize_read", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
    ))
    @sessioned
    def authorize_read(project_id: str, file_id: str, inline: bool = False) -> dict:
        """签发单文件限时读取链接。可用 GET、HEAD、Range；返回到期时间和文件摘要，不返回文件字节。"""
        db, actor = dbc()
        result = issue_read_grant(
            db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"),
            api_key_id=_api_key_id(), inline=inline,
        )
        db.commit()
        return result

    @mcp.tool(name="files.prepare_upload", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
    ))
    @sessioned
    def prepare_upload(project_id: str, name: str, size: int) -> dict:
        """申请限时单文件上传地址。文件发送器以 PUT 发送 size 个原始字节，无需 Cookie、长期 Key 或 Base64。"""
        db, actor = dbc()
        result = issue_upload_grant(
            db, actor.id, parse_uuid(project_id, "project_id"), api_key_id=_api_key_id(), name=name, size=size,
        )
        db.commit()
        return result

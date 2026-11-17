"""v2 file capability tools backed by the same service as the HTTP routes."""

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.types import ToolAnnotations
from pydantic import StrictInt

from ..errors import unauthorized
from ..v2 import file_usage, files
from ..v2.files import issue_read_grant, issue_upload_grant
from ..v2.resource_refs import parse_uuid
from .tools import dbc, sessioned


def _api_key_id():
    auth = auth_context_var.get()
    if auth is None:
        raise unauthorized("缺少有效 API key")
    return parse_uuid(auth.access_token.client_id, "api_key_id")


def register_file_tools(mcp) -> None:
    @mcp.tool(name="files.list", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @sessioned
    def list_library(project_id: str, query: str = "", cursor: str | None = None,
                     limit: StrictInt = 20, media_type: str | None = None) -> dict:
        """发现项目内有效文件及稳定引用地址。用 authorize_read 获取临时字节通道。"""
        db, actor = dbc()
        return files.list_files(db, actor.id, parse_uuid(project_id, "project_id"), query=query,
                                cursor=cursor, limit=limit, media_type=media_type)

    @mcp.tool(name="files.get", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @sessioned
    def get_metadata(project_id: str, file_id: str) -> dict:
        """查看有效文件的元数据，不返回二进制内容。"""
        db, actor = dbc()
        row = files.get_file(db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"))
        return files.file_summary(row, detail=True)

    @mcp.tool(name="files.delete", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False,
    ))
    @sessioned
    def delete_file(project_id: str, file_id: str) -> dict:
        """将文件放入回收站，保留原始字节和引用并停用已有下载授权。可先查看 files.usages。"""
        db, actor = dbc()
        files.delete_file(db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"))
        db.commit()
        return {"id": file_id, "project_id": project_id, "deleted": True}

    @mcp.tool(name="files.trash_list", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
    ))
    @sessioned
    def trash_list(project_id: str, query: str = "", cursor: str | None = None, limit: StrictInt = 20) -> dict:
        """分页查找本项目已删除文件。需要项目编辑权限，不返回文件内容或访问凭据。"""
        db, actor = dbc()
        return files.list_files(db, actor.id, parse_uuid(project_id, "project_id"), query=query,
                                cursor=cursor, limit=limit, state=files.FileState.DELETED)

    @mcp.tool(name="files.trash_get", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
    ))
    @sessioned
    def trash_get(project_id: str, file_id: str) -> dict:
        """查看一条文件回收站记录的详情。不签发下载授权。"""
        db, actor = dbc()
        row = files.get_deleted_file(db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"))
        return files.file_summary(row, detail=True)

    @mcp.tool(name="files.restore", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False,
    ))
    @sessioned
    def restore(project_id: str, file_id: str) -> dict:
        """恢复已删除文件的原始标识与引用。缺少原始字节时报告冲突。"""
        db, actor = dbc()
        row = files.restore_file(db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"))
        result = files.file_summary(row)
        db.commit()
        return result

    @mcp.tool(name="files.usages", annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False,
    ))
    @sessioned
    def list_usage(project_id: str, file_id: str, include_history: bool = False,
                   cursor: str | None = None, limit: StrictInt = 20) -> file_usage.UsagePage:
        """查看可见的文件使用位置。include_history=true 同时显示引用该文件的历史 Wiki 版本。"""
        db, actor = dbc()
        return file_usage.list_usage(db, actor.id, parse_uuid(project_id, "project_id"), parse_uuid(file_id, "file_id"),
                                     include_history=include_history, cursor=cursor, limit=limit)

    @mcp.tool(name="files.link", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False,
    ))
    @sessioned
    def link(project_id: str, file_id: str, target_kind: file_usage.TargetKind, target_id: str) -> file_usage.AssociationReceipt:
        """将文件显式关联到同项目的需求、任务、Wiki 或项目；正文链接由 Markdown 单独维护。"""
        db, actor = dbc()
        receipt = file_usage.set_association(db, actor.id, parse_uuid(project_id, "project_id"),
                                             parse_uuid(file_id, "file_id"), kind=target_kind, target_id=target_id, linked=True)
        db.commit()
        return receipt

    @mcp.tool(name="files.unlink", annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False,
    ))
    @sessioned
    def unlink(project_id: str, file_id: str, target_kind: file_usage.TargetKind, target_id: str) -> file_usage.AssociationReceipt:
        """解除同项目中的一条显式关联。操作保留文件和正文中的 Markdown 引用。"""
        db, actor = dbc()
        receipt = file_usage.set_association(db, actor.id, parse_uuid(project_id, "project_id"),
                                             parse_uuid(file_id, "file_id"), kind=target_kind, target_id=target_id, linked=False)
        db.commit()
        return receipt

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

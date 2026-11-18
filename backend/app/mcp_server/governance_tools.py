"""Agent entry points for workspace governance and personal requirement views."""

from base64 import b64encode
from typing import Annotated, Literal

from mcp.types import ImageContent, ToolAnnotations
from pydantic import Field

from ..errors import permission_denied
from ..schemas import FilterViewUpdate, ProjectMemberAdd
from ..services import filter_views, members, projects, user_profiles
from ..services.permissions import effective_user_id, get_workspace_member, require_workspace_admin
from ..v2.resource_refs import parse_uuid
from .tools import dbc, sessioned

ProjectRole = Literal["editor", "viewer"]
WorkspaceRole = Literal["member", "admin"]
ProjectName = Annotated[str, Field(min_length=1, max_length=128)]
Description = Annotated[str, Field(max_length=1000)]
Username = Annotated[str, Field(min_length=1, max_length=64)]
ViewName = Annotated[str, Field(min_length=1, max_length=50)]
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(destructiveHint=False, openWorldHint=False)
CHANGE = ToolAnnotations(destructiveHint=True, openWorldHint=False)


def register_governance_tools(mcp) -> None:
    @mcp.tool(name="project.create", annotations=WRITE)
    @sessioned
    def project_create(name: ProjectName, description: Description = "", members: list[ProjectMemberAdd] | None = None) -> dict:
        """工作区管理员创建项目。主人登记为项目负责人，操作由当前 Agent 署名。"""
        db, actor = dbc()
        project = projects.create_project(db, actor, name, [m.model_dump() for m in members or []], description)
        return {"id": str(project.id), "name": project.name, "description": project.description, "my_role": "owner"}

    @mcp.tool(name="project.update", annotations=WRITE)
    @sessioned
    def project_update(project_id: str, name: ProjectName | None = None, description: Description | None = None) -> dict:
        """负责人修改名称或简介，省略字段保留原值，空字符串清空简介。"""
        db, actor = dbc()
        project = projects.update_project(db, actor, parse_uuid(project_id, "project_id"), name, description)
        return {"id": str(project.id), "name": project.name, "description": project.description}

    @mcp.tool(name="project.delete_impact", annotations=READ)
    @sessioned
    def project_delete_impact(project_id: str) -> dict:
        """查看删除项目影响的资源数量。"""
        db, actor = dbc()
        return projects.project_delete_impact(db, actor, parse_uuid(project_id, "project_id"))

    @mcp.tool(name="project.delete", annotations=CHANGE)
    @sessioned
    def project_delete(project_id: str) -> dict:
        """负责人将项目移入回收站。可用 trash.projects_restore 恢复。"""
        db, actor = dbc()
        projects.soft_delete_project(db, actor, parse_uuid(project_id, "project_id"))
        return {"id": project_id, "deleted": True}

    @mcp.tool(name="project.members", annotations=READ)
    @sessioned
    def project_members(project_id: str) -> dict:
        """列出项目人类成员及其工作区、项目角色。"""
        db, actor = dbc()
        return {"items": projects.roster(db, actor, parse_uuid(project_id, "project_id"))}

    @mcp.tool(name="project.member_candidates", annotations=READ)
    @sessioned
    def project_member_candidates(project_id: str) -> dict:
        """负责人查看可加入项目的有效工作区人类成员。"""
        db, actor = dbc()
        return {"items": projects.eligible_people(db, actor, parse_uuid(project_id, "project_id"))}

    @mcp.tool(name="project.add_member", annotations=WRITE)
    @sessioned
    def project_add_member(project_id: str, user_id: str, role: ProjectRole) -> dict:
        """授予人类成员项目角色；其附属 Agent 动态继承。"""
        db, actor = dbc()
        projects.add_project_member(db, actor, parse_uuid(project_id, "project_id"), parse_uuid(user_id, "user_id"), role)
        return {"user_id": user_id, "role": role}

    @mcp.tool(name="project.set_member_role", annotations=CHANGE)
    @sessioned
    def project_set_member_role(project_id: str, user_id: str, role: ProjectRole) -> dict:
        """修改普通成员的项目角色，负责人转让需本人在 Web 验证。"""
        db, actor = dbc()
        projects.update_project_member_role(db, actor, parse_uuid(project_id, "project_id"), parse_uuid(user_id, "user_id"), role)
        return {"user_id": user_id, "role": role}

    @mcp.tool(name="project.remove_member", annotations=CHANGE)
    @sessioned
    def project_remove_member(project_id: str, user_id: str) -> dict:
        """解除项目成员关系。"""
        db, actor = dbc()
        projects.remove_project_member(db, actor, parse_uuid(project_id, "project_id"), parse_uuid(user_id, "user_id"))
        return {"user_id": user_id, "removed": True}

    @mcp.tool(name="workspace.members", annotations=READ)
    @sessioned
    def workspace_members() -> dict:
        """列出工作区人类成员、角色和附属 Agent。"""
        db, actor = dbc()
        return {"items": members.workspace_roster(db, actor)}

    @mcp.tool(name="workspace.member_avatar", annotations=READ)
    @sessioned
    def workspace_member_avatar(user_id: str) -> ImageContent:
        """查看成员或其附属 Agent 的头像图片。使用工作区名册中的用户 ID。"""
        db, actor = dbc()
        if get_workspace_member(db, actor.id) is None:
            raise permission_denied("仅工作区成员可查看名册")
        content, mime = user_profiles.read_avatar(db, parse_uuid(user_id, "user_id"))
        return ImageContent(type="image", data=b64encode(content).decode("ascii"), mimeType=mime)

    @mcp.tool(name="workspace.inactive_members", annotations=READ)
    @sessioned
    def workspace_inactive_members() -> dict:
        """管理员查看已停用的人类成员。"""
        db, actor = dbc()
        return {"items": members.inactive_roster(db, actor)}

    @mcp.tool(name="workspace.create_member", annotations=WRITE)
    @sessioned
    def workspace_create_member(username: Username, role: WorkspaceRole = "member") -> dict:
        """管理员建立人类成员。设置密码的链接由人类管理员在 Web 签发。"""
        db, actor = dbc()
        user, _ = members.create_member(db, actor, username, role)
        return {**members.member_summary(user), "role": role}

    @mcp.tool(name="workspace.set_member_role", annotations=CHANGE)
    @sessioned
    def workspace_set_member_role(user_id: str, role: WorkspaceRole) -> dict:
        """管理员调整工作区人类成员角色。"""
        db, actor = dbc()
        user = members.update_role(db, actor, parse_uuid(user_id, "user_id"), role)
        return {"id": str(user.id), "role": role}

    @mcp.tool(name="workspace.deactivate_member", annotations=CHANGE)
    @sessioned
    def workspace_deactivate_member(user_id: str) -> dict:
        """停用人类成员，同时停用其附属 Agent 及密钥。"""
        db, actor = dbc()
        members.remove_member(db, actor, parse_uuid(user_id, "user_id"))
        return {"id": user_id, "deactivated": True}

    @mcp.tool(name="workspace.reactivate_member", annotations=WRITE)
    @sessioned
    def workspace_reactivate_member(user_id: str) -> dict:
        """以普通成员身份重新启用，项目授权和已吊销密钥仍需重新处理。"""
        db, actor = dbc()
        user, _ = members.reactivate_member(db, actor, parse_uuid(user_id, "user_id"))
        return {**members.member_summary(user), "role": "member"}

    def managed_profile(user_id: str):
        db, actor = dbc()
        require_workspace_admin(db, actor.id)
        target = user_profiles.get_user(db, parse_uuid(user_id, "user_id"))
        if target.is_agent or target.id == effective_user_id(db, actor.id):
            raise permission_denied("本人和附属 Agent 的身份资料请由主人在网页维护")
        if get_workspace_member(db, target.id) is None:
            raise permission_denied("只能管理工作区人类成员的资料")
        return db, actor, target.id

    @mcp.tool(name="workspace.set_member_nickname", annotations=WRITE)
    @sessioned
    def workspace_set_member_nickname(user_id: str, nickname: Annotated[str, Field(max_length=64)]) -> dict:
        """管理员编辑其他人类成员的昵称，空字符串恢复显示账号名。"""
        db, actor, target_id = managed_profile(user_id)
        return user_profiles.payload(user_profiles.update_profile(db, actor, target_id, nickname))

    @mcp.tool(name="workspace.set_member_avatar", annotations=WRITE)
    @sessioned
    def workspace_set_member_avatar(user_id: str, content_type: Literal["image/jpeg", "image/png", "image/gif", "image/webp"], data_base64: str) -> dict:
        """管理员设置其他人类成员的头像。传标准 Base64 图片，大小上限与 Web 相同。"""
        db, actor, target_id = managed_profile(user_id)
        return user_profiles.payload(user_profiles.set_encoded_avatar(db, actor, target_id, content_type, data_base64))

    @mcp.tool(name="workspace.remove_member_avatar", annotations=CHANGE)
    @sessioned
    def workspace_remove_member_avatar(user_id: str) -> dict:
        """管理员移除其他人类成员的头像。"""
        db, actor, target_id = managed_profile(user_id)
        return user_profiles.payload(user_profiles.remove_avatar(db, actor, target_id))

    @mcp.tool(name="views.list", annotations=READ)
    @sessioned
    def views_list(project_id: str) -> dict:
        """列出当前主人在该项目保存的个人需求筛选视图。"""
        db, actor = dbc()
        return filter_views.list_filter_views(db, actor, parse_uuid(project_id, "project_id"), "requirement")

    @mcp.tool(name="views.create", annotations=WRITE)
    @sessioned
    def views_create(project_id: str, name: ViewName, criteria: dict) -> dict:
        """保存个人需求视图。criteria 支持 statuses、updated_within_days、keyword、participated_by_me、view_mode。"""
        db, actor = dbc()
        view = filter_views.create_filter_view(db, actor, parse_uuid(project_id, "project_id"), "requirement", name, criteria)
        return filter_views.view_summary(view)

    @mcp.tool(name="views.get", annotations=READ)
    @sessioned
    def views_get(id: str) -> dict:
        """读取个人视图及筛选条件。"""
        db, actor = dbc()
        return filter_views.view_summary(filter_views.get_filter_view(db, actor, parse_uuid(id, "id")))

    @mcp.tool(name="views.update", annotations=WRITE)
    @sessioned
    def views_update(id: str, patch: FilterViewUpdate) -> dict:
        """修改视图名称或条件。省略字段保留原值，criteria={} 清除筛选条件。"""
        db, actor = dbc()
        return filter_views.view_summary(filter_views.update_filter_view(
            db, actor, parse_uuid(id, "id"), patch.name, patch.criteria,
            name_set="name" in patch.model_fields_set, criteria_set="criteria" in patch.model_fields_set,
        ))

    @mcp.tool(name="views.delete", annotations=CHANGE)
    @sessioned
    def views_delete(id: str) -> dict:
        """删除个人筛选视图。"""
        db, actor = dbc()
        filter_views.delete_filter_view(db, actor, parse_uuid(id, "id"))
        return {"id": id, "deleted": True}

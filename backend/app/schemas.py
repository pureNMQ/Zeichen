"""HTTP API 与 Web 共用的请求/响应结构(pydantic)。"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

PasswordField = Field(min_length=8, max_length=128)


class UsernamePassword(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = PasswordField


class SetPassword(BaseModel):
    password: str = PasswordField


class SetPasswordWithToken(SetPassword):
    token: str = Field(min_length=32, max_length=256)


class ChangePassword(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = PasswordField


class UserProfileUpdate(BaseModel):
    nickname: str | None = Field(max_length=64)


class MemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal["admin", "member"] = "member"


class MemberUpdate(BaseModel):
    role: Literal["admin", "member"]


class MyAgentCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class AgentProfileUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)


class KeyIssue(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class KeyReveal(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ProjectMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: Literal["editor", "viewer"]


class ProjectMemberUpdate(BaseModel):
    role: Literal["editor", "viewer"]


class ProjectOwnerTransfer(BaseModel):
    user_id: uuid.UUID
    password: str = Field(min_length=1, max_length=128)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    members: list[ProjectMemberAdd] = []


class ProjectUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None


class StatusBody(BaseModel):
    status: str = Field(min_length=1, max_length=16)


class RequirementDeleteBody(BaseModel):
    confirm_task_count: int | None = Field(default=None, ge=0)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    # 必填由服务层强制(缺失 → invalid_request,而非 422;ADR 0003);值为需求短码 REQ-n(ADR 0002)
    requirement_id: str | None = None
    assignee_id: uuid.UUID | None = None
    blocked_by: list[str] | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    requirement_id: str | None = None
    blocked_by: list[str] | None = None


class TaskAssignBody(BaseModel):
    assignee_id: uuid.UUID


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    doc_type: Literal["wiki", "glossary"]
    content: str | None = None
    metadata: dict = {}
    parent_id: str | None = None
    directory_id: str | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = None
    metadata: dict | None = None


class FilterViewCreate(BaseModel):
    """字段类型宽松,校验放 service(保证 400 而非 422)。"""

    entity_type: str | None = None
    name: str | None = None
    criteria: dict | None = None


class FilterViewUpdate(BaseModel):
    """PATCH:name/criteria 可只传其一;model_fields_set 区分未传与传 null。"""

    name: str | None = None
    criteria: dict | None = None


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    vcs_type: Literal["git", "svn", "other"]
    other_vcs_type: str | None = Field(default=None, max_length=64)
    url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=1000)
    default_branch: str | None = Field(default=None, max_length=256)


class RepositoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    vcs_type: Literal["git", "svn", "other"] | None = None
    other_vcs_type: str | None = Field(default=None, max_length=64)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=1000)
    default_branch: str | None = Field(default=None, max_length=256)


class DocumentMove(BaseModel):
    parent_id: str | None = None
    directory_id: str | None = None


class DirectoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None


class DirectoryRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class DirectoryMove(BaseModel):
    parent_id: str | None = None


class RollbackBody(BaseModel):
    version_no: int = Field(ge=1)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReferenceCreate(BaseModel):
    # 五类实体端点传短码(REQ/TASK/DOC/TERM/DIR-n);repository/project 端点传 UUID(ADR 0002)
    from_type: Literal["requirement", "task", "document", "repository", "project"]
    from_id: str
    to_type: Literal["requirement", "task", "document", "repository", "project"]
    to_id: str
    type: Literal["derives", "documents", "implements", "mentions"]


class NotificationPreferencesUpdate(BaseModel):
    domains: dict[str, bool] = {}
    actions: dict[str, bool] = {}

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


class MemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal["admin", "member"] = "member"


class MemberUpdate(BaseModel):
    role: Literal["admin", "member"]


class ProjectGrant(BaseModel):
    project_id: uuid.UUID
    role: Literal["owner", "editor", "viewer"]


class AgentCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    project_grants: list[ProjectGrant] = []


class AgentUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    project_grants: list[ProjectGrant] | None = None


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
    requirement_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    requirement_id: uuid.UUID | None = None


class TaskAssignBody(BaseModel):
    assignee_id: uuid.UUID


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReferenceCreate(BaseModel):
    from_type: Literal["requirement", "task", "document", "project"]
    from_id: uuid.UUID
    to_type: Literal["requirement", "task", "document", "project"]
    to_id: uuid.UUID
    type: Literal["derives", "documents", "implements", "mentions"]

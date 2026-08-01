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
    role: Literal["owner", "editor", "viewer"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    members: list[ProjectMemberAdd] = []

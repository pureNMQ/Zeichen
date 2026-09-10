"""HTTP API 与 Web 共用的请求/响应结构(pydantic)。"""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .errors import invalid_request

PasswordField = Field(min_length=8, max_length=128)

# cognee 受管配置 llm_model 的 provider/model 限定格式契约(REQ bc36ae8b):
# 含且仅含一个 /,两侧非空、无空白。cognee 1.4.1 经 litellm 以 model 串推断
# provider,未限定串会让全部 LLM 调用失败(LLM Provider NOT provided),蒸馏永久
# 失败。schema 层与 services.cognee_configuration.update 共用此规则。
LLM_MODEL_PATTERN = re.compile(r"^[^/\s]+/[^/\s]+$")


def validate_llm_model(value: str) -> str:
    """返回去除首尾空白的限定 model 串;未限定时抛 invalid_request(HTTP 400)。"""
    normalized = str(value).strip()
    if not LLM_MODEL_PATTERN.fullmatch(normalized):
        raise invalid_request(
            "llm_model 必须为 provider/model 限定格式(如 deepseek/deepseek-v4-flash),"
            "未限定格式会导致 LiteLLM 无法路由并阻断蒸馏"
        )
    return normalized


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


class ProjectDelete(BaseModel):
    confirm_memory_cleanup: bool = False


class MemoryRemember(BaseModel):
    session_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=20000)
    anchor: dict | None = None


class MemoryRecall(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=256)


class MemoryImprove(BaseModel):
    agent_id: uuid.UUID
    session_id: str = Field(min_length=1, max_length=256)


class CogneeConfigurationUpdate(BaseModel):
    llm_provider: str = Field(min_length=1, max_length=64)
    llm_model: str = Field(min_length=1, max_length=256)
    llm_endpoint: str | None = Field(default=None, max_length=2048)
    # Omit the key to retain the stored value; an empty value explicitly clears it.
    llm_api_key: str | None = Field(default=None, max_length=4096)
    embedding_provider: str = Field(min_length=1, max_length=64)
    embedding_model: str = Field(min_length=1, max_length=256)
    embedding_dimensions: int | None = Field(default=None, ge=1, le=65536)

    @field_validator("llm_model")
    @classmethod
    def _require_provider_qualified_llm_model(cls, value: str) -> str:
        # 抛 AppError 而非 ValueError:由统一错误 handler 转 400 invalid_request,
        # 与服务层契约一致,避免 pydantic 默认的 422。
        return validate_llm_model(value)


class CogneeRestartRequest(BaseModel):
    confirmed: bool = False


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
    blocked_by: list[uuid.UUID] | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    requirement_id: uuid.UUID | None = None
    blocked_by: list[uuid.UUID] | None = None


class TaskAssignBody(BaseModel):
    assignee_id: uuid.UUID


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    doc_type: Literal["wiki", "glossary"]
    content: str | None = None
    metadata: dict = {}
    parent_id: uuid.UUID | None = None
    directory_id: uuid.UUID | None = None


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
    parent_id: uuid.UUID | None = None
    directory_id: uuid.UUID | None = None


class DirectoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: uuid.UUID | None = None


class DirectoryRename(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class DirectoryMove(BaseModel):
    parent_id: uuid.UUID | None = None


class RollbackBody(BaseModel):
    version_no: int = Field(ge=1)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class ReferenceCreate(BaseModel):
    from_type: Literal["requirement", "task", "document", "repository", "project"]
    from_id: uuid.UUID
    to_type: Literal["requirement", "task", "document", "repository", "project"]
    to_id: uuid.UUID
    type: Literal["derives", "documents", "implements", "mentions"]

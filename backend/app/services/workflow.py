"""状态机:需求六态、任务四态,完全自由流转。

- 需求六态:pending / backlog / in_progress / verifying / done / cancelled(verifying 为普通状态,
  验收语义上移需求,ADR 0003)
- 任务四态:backlog / in_progress / done / cancelled(verifying 已删)
- 完全自由流转:任意状态互转(含直达终态),**无任何前置校验**(需求带未决任务也可直达 done);
  唯一约束是同态再转 → conflict
- 状态完全手动:任务状态变化不影响需求状态(自动流转已删除),需求状态仅由操作者显式控制
- 验收语义:置 done/verifying 不留说明;activity 只记 status action + 旧态 → 新态摘要
- 所有权规则(已指派任务仅本人/工作区 admin/项目 owner)在 services/tasks.py,不在此层
"""

from ..errors import conflict, invalid_request

REQUIREMENT_STATUSES = (
    "pending",
    "backlog",
    "in_progress",
    "verifying",
    "done",
    "cancelled",
)
TASK_STATUSES = ("backlog", "in_progress", "done", "cancelled")
TERMINAL = ("done", "cancelled")


def _statuses(what: str) -> tuple[str, ...]:
    if what == "需求":
        return REQUIREMENT_STATUSES
    return TASK_STATUSES


def assert_status_valid(current: str, target: str, what: str = "任务") -> None:
    """状态值校验:目标态非法 → invalid_request;同态再转 → conflict。"""
    if target not in _statuses(what):
        raise invalid_request(f"非法的{what}状态: {target}")
    if target == current:
        raise conflict(f"{what}当前已是 {target}")

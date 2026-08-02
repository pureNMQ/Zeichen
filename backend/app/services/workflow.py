"""状态机(ticket 09:需求四态、任务五态,完全自由流转)。

- 需求四态:backlog / in_progress / done / cancelled(删 verifying)
- 任务五态:backlog / in_progress / verifying / done / cancelled(verifying 为普通状态)
- 完全自由流转:任意状态互转(含直达终态),**无任何前置校验**(需求带未决任务也可直达 done);
  唯一约束是同态再转 → conflict
- 状态完全手动:任务状态变化不影响需求状态(自动流转已删除),需求状态仅由操作者显式控制
- 验收语义删除:置 done 不再留说明;activity 只记 status action + 旧态 → 新态摘要
- 所有权规则(已指派任务仅本人/工作区 admin/项目 owner)在 services/tasks.py,不在此层
"""

from ..errors import conflict, invalid_request

REQUIREMENT_STATUSES = ("backlog", "in_progress", "done", "cancelled")
TASK_STATUSES = ("backlog", "in_progress", "verifying", "done", "cancelled")
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

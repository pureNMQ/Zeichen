"""展示层中文标签:活动 summary 落库用(REQ 877727e8)。

历史活动已按英文枚举落库,展示层(前端)对旧记录做兼容映射;新记录直接写中文。
"""

STATUS_CN = {
    "pending": "待确认",
    "backlog": "待办",
    "in_progress": "实现中",
    "verifying": "验收中",
    "done": "已完成",
    "cancelled": "已取消",
}

TARGET_TYPE_CN = {
    "requirement": "需求",
    "task": "任务",
    "document": "文档",
    "repository": "代码仓库",
    "project": "项目",
}

"""API 路由汇总。"""

from fastapi import APIRouter

from . import agents, attachments, auth, code_reference, documents, members, memory, notifications, polymorphic, projects, requirements, search, tasks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(agents.router)
api_router.include_router(projects.router)
api_router.include_router(memory.router)
api_router.include_router(notifications.router)
api_router.include_router(search.router)
api_router.include_router(attachments.router)
api_router.include_router(requirements.router)
api_router.include_router(tasks.router)
api_router.include_router(documents.router)
api_router.include_router(code_reference.router)
api_router.include_router(polymorphic.router)

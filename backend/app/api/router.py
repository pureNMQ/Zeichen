"""API 路由汇总。"""

from fastapi import APIRouter

from . import agents, auth, documents, members, polymorphic, projects, requirements, tasks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(agents.router)
api_router.include_router(projects.router)
api_router.include_router(requirements.router)
api_router.include_router(tasks.router)
api_router.include_router(documents.router)
api_router.include_router(polymorphic.router)

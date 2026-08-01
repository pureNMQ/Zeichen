"""API 路由汇总。"""

from fastapi import APIRouter

from . import agents, auth, members, projects

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(agents.router)
api_router.include_router(projects.router)

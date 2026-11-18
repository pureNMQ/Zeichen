"""API 路由汇总。"""

from fastapi import APIRouter

from . import work_content

from . import agents, attachments, auth, documents, files_v2, filter_views, members, notifications, polymorphic, projects, repositories, requirements, search, tasks, users
from . import notifications_v2, project_completion, search_v2, timeline, wiki_v2, work_trash

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(agents.router)
api_router.include_router(projects.router)
api_router.include_router(project_completion.router)
api_router.include_router(notifications.router)
api_router.include_router(notifications_v2.router)
api_router.include_router(notifications.prefs_router)
api_router.include_router(search.router)
api_router.include_router(search_v2.router)
api_router.include_router(attachments.router)
api_router.include_router(files_v2.router)
api_router.include_router(requirements.router)
api_router.include_router(timeline.router)
api_router.include_router(work_trash.router)
api_router.include_router(tasks.router)
api_router.include_router(documents.router)
api_router.include_router(wiki_v2.router)
api_router.include_router(repositories.router)
api_router.include_router(polymorphic.router)
api_router.include_router(users.router)
api_router.include_router(filter_views.router)

api_router.include_router(work_content.router)

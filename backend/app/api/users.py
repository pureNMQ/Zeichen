import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import UserProfileUpdate
from ..services import user_profiles
from .deps import current_user

router = APIRouter(prefix="/api/users", tags=["users"])


def _target_id(user_id: uuid.UUID | None, user: User) -> uuid.UUID:
    return user_id or user.id


@router.get("/me")
def get_me(user: User = Depends(current_user)) -> dict:
    return user_profiles.payload(user)


@router.patch("/me")
def update_me(body: UserProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(user_profiles.update_profile(db, user, user.id, body.nickname))


@router.patch("/{user_id}")
def update_user(user_id: uuid.UUID, body: UserProfileUpdate, admin: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(user_profiles.update_profile(db, admin, user_id, body.nickname))


@router.post("/me/avatar")
async def upload_my_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(await user_profiles.set_avatar(db, user, user.id, file))


@router.post("/{user_id}/avatar")
async def upload_user_avatar(user_id: uuid.UUID, file: UploadFile = File(...), admin: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(await user_profiles.set_avatar(db, admin, user_id, file))


@router.delete("/me/avatar")
def delete_my_avatar(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(user_profiles.remove_avatar(db, user, user.id))


@router.delete("/{user_id}/avatar")
def delete_user_avatar(user_id: uuid.UUID, admin: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return user_profiles.payload(user_profiles.remove_avatar(db, admin, user_id))


@router.get("/{user_id}/avatar")
def get_avatar(user_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    data = user_profiles.read_avatar(db, user_id)
    content, content_type = data
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=300"})

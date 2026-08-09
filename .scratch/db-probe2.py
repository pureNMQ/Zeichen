import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as c:
    print("users:")
    for r in c.execute(text('select username, length(password_hash), is_bootstrap, deleted_at from "user"')).fetchall():
        print(" ", r)
    print("api_keys:")
    for r in c.execute(text('select u.username, ak.note, ak.revoked_at from api_key ak join "user" u on u.id = ak.user_id')).fetchall():
        print(" ", r)
    print("project_members:")
    for r in c.execute(text('select u.username, pm.role from project_member pm join "user" u on u.id = pm.user_id')).fetchall():
        print(" ", r)

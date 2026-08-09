import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as c:
    print("users:", c.execute(text('select username, is_agent from "user"')).fetchall())
    print("projects:", c.execute(text("select id, name from project where deleted_at is null")).fetchall())
    print("teams:", c.execute(text("select count(*) from team")).scalar())
    print("notifications:", c.execute(text("select count(*) from notification")).scalar())
    print("attachments:", c.execute(text("select count(*) from attachment")).scalar())

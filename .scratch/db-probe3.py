import os
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as c:
    print("agents:")
    for r in c.execute(text('select username from "user" where is_agent = true')).fetchall():
        print(" ", r[0])
    print("requirements:")
    for r in c.execute(text("select title from requirement where deleted_at is null")).fetchall():
        print(" ", r[0])

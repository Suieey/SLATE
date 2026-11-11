"""Snapshot persistence through SQLAlchemy. Works with the Postgres DATABASE_URL from PR #4 or SQLite.

Deliberately simple: the whole service state is stored as one JSON document and rewritten after each
change. Fine for a demo and one process; NOT safe for concurrent writers or large data. Replace with
real tables once the data model settles. Tested on SQLite only; Postgres was not run here.
"""
import json
from sqlalchemy import create_engine, text

class SqlSnapshot:
    def __init__(self, url: str):
        self.engine = create_engine(url, future=True)
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS slate_state (id INTEGER PRIMARY KEY, doc TEXT NOT NULL)"))

    def load(self):
        with self.engine.begin() as c:
            row = c.execute(text("SELECT doc FROM slate_state WHERE id = 1")).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, state: dict):
        doc = json.dumps(state)
        with self.engine.begin() as c:
            c.execute(text("DELETE FROM slate_state WHERE id = 1"))
            c.execute(text("INSERT INTO slate_state (id, doc) VALUES (1, :d)"), {"d": doc})

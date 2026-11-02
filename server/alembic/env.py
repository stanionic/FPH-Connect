import os
import sys

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import models  # noqa: F401,E402
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_online():
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata,
                          render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()

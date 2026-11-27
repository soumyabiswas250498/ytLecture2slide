from alembic import context

from app.core.config import Settings
from app.infrastructure import models as _models  # noqa: F401
from app.infrastructure.database import Base, create_database_engine
from app.infrastructure.storage import Storage

settings = Settings()
assert settings.database_path is not None
target_metadata = Base.metadata

if context.is_offline_mode():
    from sqlalchemy import URL

    context.configure(
        url=URL.create("sqlite", database=str(settings.database_path)),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    Storage.from_settings(settings).initialize()
    engine = create_database_engine(settings.database_path)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()

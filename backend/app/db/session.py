from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "field_results" in tables and "rank" in {
            column["name"] for column in inspector.get_columns("field_results")
        }:
            connection.execute(text("ALTER TABLE field_results DROP COLUMN rank"))
        if "resolved_fields" in tables and "final_rank" in {
            column["name"] for column in inspector.get_columns("resolved_fields")
        }:
            connection.execute(text("ALTER TABLE resolved_fields DROP COLUMN final_rank"))
        if "page_micro_memories" in tables and "field_states" not in {
            column["name"] for column in inspector.get_columns("page_micro_memories")
        }:
            connection.execute(
                text(
                    "ALTER TABLE page_micro_memories "
                    "ADD COLUMN field_states JSON NOT NULL DEFAULT '{}'"
                )
            )

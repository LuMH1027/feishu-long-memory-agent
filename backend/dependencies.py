from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_database_schema():
    """Create tables and add lightweight SQLite-compatible columns when needed."""
    from db.relational.models import Memory, DecisionMemory  # noqa: F401

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if "memories" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("memories")}
    migrations = {
        "description": "ALTER TABLE memories ADD COLUMN description TEXT",
        "memory_metadata": "ALTER TABLE memories ADD COLUMN memory_metadata TEXT",
    }
    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

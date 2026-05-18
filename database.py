import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# On Vercel the project root is read-only; /tmp is the only writable dir.
# For persistence, set DATABASE_URL to a PostgreSQL connection string (e.g. Neon free tier).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/mytodo.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import Goal, StrategicState, DailyTask, ExecutionLog  # noqa
    Base.metadata.create_all(bind=engine)

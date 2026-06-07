import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Vercel serverless: DATABASE_URL must be a PostgreSQL connection string.
# Recommended: Neon free tier — set DATABASE_URL in Vercel project settings.
# Fallback: SQLite in /tmp (non-persistent across invocations, dev/testing only).
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/mytodo.db")

# Neon and most Postgres hosts use `postgresql://` — SQLAlchemy 2.x requires
# `postgresql+psycopg2://` for psycopg2. Normalise the scheme here.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping keeps connections alive across serverless cold starts.
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import Initiative, Task, RevenueRecord, DistributionAction, Reflection, DailyBrief, ChatMessage  # noqa
    Base.metadata.create_all(bind=engine)

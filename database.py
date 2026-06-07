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
    from models import (  # noqa — all models must be imported for create_all
        WorkspaceUser, WorkspaceInvite,
        Initiative, Task, RevenueRecord, DistributionAction, Reflection,
        DailyBrief, ChatMessage,
    )
    Base.metadata.create_all(bind=engine)


def bootstrap_founder() -> None:
    """
    Auto-create the founder WorkspaceUser on first startup.

    If workspace_users is empty:
      - Creates founder row using MYTODO_OWNER_EMAIL + MYTODO_OWNER_NAME
      - Hashes MYTODO_ACCESS_CODE as the initial password
      - Assigns id=1 (all existing gateway_user_id=1 data is attributed here)

    Safe to call on every startup — exits immediately if a founder exists.
    """
    import os
    from models import WorkspaceUser
    from workspace_auth import hash_password

    db = SessionLocal()
    try:
        existing = db.query(WorkspaceUser).first()
        if existing:
            return  # already bootstrapped

        email     = os.getenv("MYTODO_OWNER_EMAIL", "faturotijude@gmail.com").strip()
        name      = os.getenv("MYTODO_OWNER_NAME", "Boluwatife").strip()
        password  = os.getenv("MYTODO_ACCESS_CODE", "humble").strip()

        founder = WorkspaceUser(
            email=email,
            full_name=name,
            role="founder",
            status="approved",
            password_hash=hash_password(password),
        )
        db.add(founder)
        db.commit()
        import logging
        logging.getLogger("mytodo").info(
            "Founder workspace user bootstrapped: %s (id=%d)", email, founder.id
        )
    except Exception as e:
        import logging
        logging.getLogger("mytodo").error("bootstrap_founder failed: %s", e)
        db.rollback()
    finally:
        db.close()

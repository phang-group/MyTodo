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
    # PHANT cognition tables — optional. If phant package is absent, only PHANT
    # tables are skipped; all product tables are still created.
    try:
        from phant.models import ALL_MODELS as _phant_models  # noqa: F401 — side-effect import
    except Exception:
        pass  # phant absent — product tables unaffected
    Base.metadata.create_all(bind=engine)
    _run_schema_migrations()
    # PHANT-specific migrations (pgvector + embedding column). Non-fatal.
    try:
        from phant import migrations as phant_migrations
        phant_migrations.run()
    except Exception as _e:
        import logging
        logging.getLogger("mytodo.db").warning("PHANT migrations skipped: %s", _e)


# ── Schema migrations ─────────────────────────────────────────────────────────
# create_all() only creates new tables — it never alters existing ones.
# These migrations add Phase 2 columns to tables that were created in Phase 1.
# Each ALTER is idempotent: safe on every cold start regardless of DB state.
#
# Columns added:
#   initiatives.visibility        VARCHAR(20) DEFAULT 'private'
#   tasks.visibility              VARCHAR(20) DEFAULT 'team'
#   tasks.assigned_to_user_id     INTEGER (nullable FK to workspace_users.id)
#   revenue_records.visibility    VARCHAR(20) DEFAULT 'private'
#   distribution_actions.visibility VARCHAR(20) DEFAULT 'team'

_MIGRATIONS = [
    # (table, column, column_definition)
    ("initiatives",        "visibility",             "VARCHAR(20) NOT NULL DEFAULT 'private'"),
    ("tasks",              "visibility",             "VARCHAR(20) NOT NULL DEFAULT 'team'"),
    ("tasks",              "assigned_to_user_id",    "INTEGER"),
    ("revenue_records",    "visibility",             "VARCHAR(20) NOT NULL DEFAULT 'private'"),
    ("distribution_actions", "visibility",           "VARCHAR(20) NOT NULL DEFAULT 'team'"),
    # ── tasks table reconciliation (old CUA schema → Founder OS schema) ───────
    # Production tasks table was created from the CUA era. The current model
    # references columns that don't exist in the old schema. Adding them here
    # so SELECT * on the tasks table no longer fails.
    ("tasks",              "initiative_id",          "INTEGER"),
    ("tasks",              "category",               "VARCHAR(50) DEFAULT 'build'"),
    ("tasks",              "for_date",               "DATE"),
]


def _run_schema_migrations() -> None:
    """
    Idempotently apply Phase 2 column additions to existing tables.

    Strategy per dialect:
      PostgreSQL — ALTER TABLE … ADD COLUMN IF NOT EXISTS (native, no-op if present)
      SQLite     — ALTER TABLE … ADD COLUMN wrapped in try/except
                   (SQLite raises OperationalError if column exists)

    No destructive operations. Existing rows receive the column default value.
    """
    import logging
    log = logging.getLogger("mytodo.db")
    dialect = engine.dialect.name  # "postgresql" or "sqlite"

    from sqlalchemy import text

    with engine.begin() as conn:
        for table, column, col_def in _MIGRATIONS:
            try:
                if dialect == "postgresql":
                    conn.execute(
                        text(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN IF NOT EXISTS {column} {col_def}"
                        )
                    )
                else:
                    # SQLite: no IF NOT EXISTS for ALTER TABLE
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
                    )
                log.debug("schema migration OK: %s.%s", table, column)
            except Exception as exc:
                # "column already exists" is expected on warm restarts; log at DEBUG only
                msg = str(exc).lower()
                if "already exists" in msg or "duplicate column" in msg:
                    log.debug("schema migration skip (exists): %s.%s", table, column)
                else:
                    # Unexpected error — log at WARNING so it appears in Vercel logs
                    log.warning(
                        "schema migration WARNING: %s.%s — %s", table, column, exc
                    )



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

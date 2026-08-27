import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")

def _is_postgres(url: str) -> bool:
    # Covers postgresql://, postgres://, postgresql+psycopg2://, postgresql+psycopg:// (Neon/Render)
    return url.startswith(("postgresql://", "postgres://", "postgresql+"))

connect_args = {}
if _is_sqlite(settings.DATABASE_URL):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from app.models import models
    Base.metadata.create_all(bind=engine)
    # Harden SQLite against corruption (WAL + NORMAL, 32k busy timeout) — critical for 200k+ row datasets on Windows
    if _is_sqlite(settings.DATABASE_URL):
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA synchronous=NORMAL;"))
                conn.execute(text("PRAGMA busy_timeout=30000;"))
                conn.execute(text("PRAGMA cache_size=-64000;"))
                conn.execute(text("PRAGMA temp_store=MEMORY;"))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite pragma setup failed: {e}")

    # Lightweight migration for new Monitor and Report columns — dialect-agnostic
    # Uses SQLAlchemy inspect(engine) so it works on both SQLite (local) and PostgreSQL (Neon/Render prod).
    # Fallback to information_schema.columns on Postgres if inspect fails.
    try:
        inspector = inspect(engine)
        is_pg = _is_postgres(settings.DATABASE_URL) or engine.dialect.name == "postgresql"

        # Map generic SQLite types to PostgreSQL-native types for ALTER TABLE
        _PG_TYPE_MAP = {
            "DATETIME": "TIMESTAMP",
            "VARCHAR": "VARCHAR",
            "INTEGER": "INTEGER",
            "BOOLEAN": "BOOLEAN",
            "JSON": "JSON",
        }

        def _effective_type(generic_type: str) -> str:
            if is_pg:
                return _PG_TYPE_MAP.get(generic_type, generic_type)
            return generic_type

        def _get_existing_columns(table_name: str) -> list:
            """Dialect-agnostic column listing via SQLAlchemy inspect, with fallback."""
            try:
                if not inspector.has_table(table_name):
                    return []
                return [col["name"] for col in inspector.get_columns(table_name)]
            except Exception as e:
                logger.warning(f"inspect.get_columns failed for {table_name}: {e}, trying fallback")
                # Fallback: ANSI information_schema for Postgres, PRAGMA for SQLite
                try:
                    with engine.connect() as conn:
                        if is_pg or engine.dialect.name == "postgresql":
                            # ANSI SQL — works on PostgreSQL (Neon)
                            res = conn.execute(
                                text("SELECT column_name FROM information_schema.columns WHERE table_name = :table"),
                                {"table": table_name},
                            )
                            return [row[0] for row in res.fetchall()]
                        else:
                            res = conn.execute(text(f"PRAGMA table_info({table_name})"))
                            return [row[1] for row in res.fetchall()]
                except Exception as fe:
                    logger.warning(f"Fallback column check failed for {table_name}: {fe}")
                    return []

        with engine.connect() as conn:
            # Monitor columns
            cols = _get_existing_columns("monitors")
            needed_mon = {
                "period_start": "DATETIME",
                "period_end": "DATETIME",
                "previous_period_start": "DATETIME",
                "previous_period_end": "DATETIME",
                "time_column": "VARCHAR",
                "dataset_version": "VARCHAR",
                "check_interval_hours": "INTEGER",
                "last_status": "VARCHAR",
                "alert_sent_at": "DATETIME",
                "alert_count": "INTEGER",
                "notify_email": "VARCHAR",
                "notify_slack_webhook": "VARCHAR",
                "notify_on_recovery": "BOOLEAN"
            }
            for col, typ in needed_mon.items():
                if col not in cols:
                    eff_typ = _effective_type(typ)
                    try:
                        conn.execute(text(f"ALTER TABLE monitors ADD COLUMN {col} {eff_typ}"))
                        conn.commit()
                    except Exception as e:
                        # Column may already exist concurrently or type mismatch — log and continue
                        logger.warning(f"Migration monitors add {col} failed: {e}")
                        try:
                            conn.rollback()
                        except Exception:
                            pass

            # Report columns for reporting workspace
            # Re-inspect after monitors migration in case inspector cache is stale
            try:
                inspector.clear_cache()  # SQLAlchemy 2.0
            except Exception:
                pass
            # Re-create inspector to refresh cache for reports check
            # (inspector caches table info; fresh inspect avoids stale read on Postgres)
            cols = _get_existing_columns("reports")
            needed_rep = {
                "dataset_version": "VARCHAR",
                "dataset_version_number": "INTEGER",
                "session_id": "VARCHAR",
                "analysis_type": "VARCHAR",
                "report_type": "VARCHAR",
                "source_report_ids": "JSON"
            }
            for col, typ in needed_rep.items():
                if col not in cols:
                    eff_typ = _effective_type(typ)
                    # JSON needs special handling on Postgres: JSON is valid, JSONB also works; keep JSON for cross-dialect
                    try:
                        conn.execute(text(f"ALTER TABLE reports ADD COLUMN {col} {eff_typ}"))
                        conn.commit()
                    except Exception as e:
                        logger.warning(f"Migration reports add {col} failed: {e}")
                        try:
                            conn.rollback()
                        except Exception:
                            pass
    except Exception as e:
        logger.warning(f"Migration check failed: {e}")

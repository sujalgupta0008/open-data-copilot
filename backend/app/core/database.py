import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
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
    if settings.DATABASE_URL.startswith("sqlite"):
        try:
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA synchronous=NORMAL;"))
                conn.execute(text("PRAGMA busy_timeout=30000;"))
                conn.execute(text("PRAGMA cache_size=-64000;"))
                conn.execute(text("PRAGMA temp_store=MEMORY;"))
                conn.commit()
        except Exception as e:
            logger.warning(f"SQLite pragma setup failed: {e}")
    # Lightweight migration for new Monitor and Report columns (SQLite)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Monitor columns
            res = conn.execute(text("PRAGMA table_info(monitors)"))
            cols = [row[1] for row in res.fetchall()]
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
                    try:
                        conn.execute(text(f"ALTER TABLE monitors ADD COLUMN {col} {typ}"))
                        conn.commit()
                    except Exception as e:
                        logger.warning(f"Migration monitors add {col} failed: {e}")
            # Report columns for reporting workspace
            res = conn.execute(text("PRAGMA table_info(reports)"))
            cols = [row[1] for row in res.fetchall()]
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
                    try:
                        conn.execute(text(f"ALTER TABLE reports ADD COLUMN {col} {typ}"))
                        conn.commit()
                    except Exception as e:
                        logger.warning(f"Migration reports add {col} failed: {e}")
    except Exception as e:
        logger.warning(f"Migration check failed: {e}")

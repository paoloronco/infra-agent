"""Database setup via SQLAlchemy + Alembic migrations."""
import logging
from datetime import datetime, timedelta
from utils import utcnow
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "app.db"
DATABASE_URL = settings.database_url.strip() or f"sqlite:///{DB_PATH}"

if DATABASE_URL.startswith("sqlite"):
    DB_PATH.parent.mkdir(exist_ok=True)
    _connect_args = {"check_same_thread": False}
else:
    _connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize the database:
    1. create_all() — creates any brand-new tables (idempotent)
    2. alembic upgrade head — applies tracked column/index migrations
    3. _recover_stuck_messages() — reset pending/streaming from prior crash
    4. _cleanup_old_logs() — delete app_logs older than 30 days
    """
    from models_db import (  # noqa — all models must be imported before create_all
        Chat, Message, ModelConfig, UsageLog, CronJob,
        AuthSetting, UserAccount, System, AppLog, AgentMemory, Attachment, AgentRun,
        ActionApproval,
    )
    Base.metadata.create_all(bind=engine)

    _ensure_chat_target_host_id_column()
    _run_alembic_migrations()
    _recover_stuck_messages()
    _cleanup_old_logs(days=settings.log_retention_days)
    _migrate_plaintext_api_keys()


def _ensure_chat_target_host_id_column() -> None:
    """Hotfix guard for upgrades from schemas older than migration 006."""
    try:
        insp = inspect(engine)
        if "chats" not in insp.get_table_names():
            return
        columns = {col["name"] for col in insp.get_columns("chats")}
        if "target_host_id" in columns:
            return

        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chats ADD COLUMN target_host_id VARCHAR"))
            conn.execute(text(
                """
                UPDATE chats
                SET target_host_id = (
                    SELECT systems.id
                    FROM systems
                    WHERE systems.name = chats.target_host
                    LIMIT 1
                )
                WHERE target_host_id IS NULL
                  AND target_host IS NOT NULL
                  AND target_host != ''
                """
            ))
        logger.info("Added chats.target_host_id compatibility column")
    except Exception as e:
        logger.warning("Could not ensure chats.target_host_id column: %s", e)


def _run_alembic_migrations() -> None:
    """Run Alembic upgrade head — replaces the hand-written _ensure_* functions."""
    try:
        from alembic.config import Config
        from alembic import command
        from pathlib import Path as _Path

        alembic_cfg = Config(str(_Path(__file__).parent / "alembic.ini"))
        # Override sqlalchemy.url so Alembic uses the same engine URL
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(alembic_cfg, "head")
        logger.info("Alembic migrations applied")
    except Exception as e:
        # Non-fatal: tables were already created by create_all above.
        # Log the issue so it is visible but don't crash startup.
        logger.warning("Alembic migration warning (non-fatal): %s", e)


def _recover_stuck_messages() -> None:
    """Reset messages stuck in pending/streaming from a previous crashed process."""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE messages "
                    "SET status='failed', content='[Processing was interrupted — please resend]' "
                    "WHERE status IN ('pending', 'streaming') "
                    "AND (content IS NULL OR content='')"
                )
            )
            if result.rowcount:
                logger.info("Recovered %d stuck message(s)", result.rowcount)
            runs = conn.execute(
                text(
                    "UPDATE agent_runs "
                    "SET status='failed', error='Processing was interrupted by restart', "
                    "finished_at=:finished_at "
                    "WHERE status IN ('pending', 'running')"
                ),
                {"finished_at": utcnow()},
            )
            if runs.rowcount:
                logger.info("Recovered %d stuck agent run(s)", runs.rowcount)
    except Exception as e:
        logger.warning("Could not recover stuck messages: %s", e)


def _migrate_plaintext_api_keys() -> None:
    """Store API keys encrypted exactly once, including old double-encrypted rows."""
    try:
        from crypto import encrypt_secret, decrypt_secret, decrypt_secret_deep, is_encrypted
        db = SessionLocal()
        try:
            from models_db import ModelConfig
            updated = 0
            for cfg in db.query(ModelConfig).all():
                if cfg.api_key:
                    decrypted_once = decrypt_secret(cfg.api_key)
                    if is_encrypted(cfg.api_key) and decrypted_once == cfg.api_key:
                        cfg.api_key = ""
                        updated += 1
                        continue
                    needs_normalize = (not is_encrypted(cfg.api_key)) or is_encrypted(decrypted_once)
                    if needs_normalize:
                        cfg.api_key = encrypt_secret(decrypt_secret_deep(cfg.api_key))
                        updated += 1
                elif cfg.api_key is None:
                    cfg.api_key = ""
                    updated += 1
            if updated:
                db.commit()
                logger.info("Normalized %d API key value(s) in model_configs", updated)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not migrate plaintext API keys: %s", e)


def _cleanup_old_logs(days: int = 30) -> None:
    """Delete app_logs entries older than `days` days to keep the table manageable."""
    try:
        with engine.begin() as conn:
            cutoff = utcnow() - timedelta(days=days)
            result = conn.execute(text("DELETE FROM app_logs WHERE created_at < :cutoff"), {"cutoff": cutoff})
            if result.rowcount:
                logger.info("Purged %d app_log entries older than %d days", result.rowcount, days)
    except Exception as e:
        logger.warning("Could not clean up old logs: %s", e)

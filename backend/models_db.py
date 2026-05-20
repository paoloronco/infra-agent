"""SQLAlchemy ORM models."""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Float, Index, text
from sqlalchemy.orm import relationship
from datetime import datetime
from utils import utcnow
from db import Base


class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, default="New Chat")
    model = Column(String, default="")
    target_host_id = Column(String, ForeignKey("systems.id", ondelete="SET NULL"), nullable=True)
    target_host = Column(String, nullable=True)  # Persistent host context for this chat
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")
    agent_runs = relationship("AgentRun", back_populates="chat", cascade="all, delete-orphan")
    action_approvals = relationship("ActionApproval", back_populates="chat", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    role = Column(String, nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False, default="")
    # pending: placeholder created, AI not started
    # streaming: AI is generating tokens
    # complete: saved successfully
    # failed: processing error
    status = Column(String, nullable=False, default="complete")
    created_at = Column(DateTime, default=utcnow)
    chat = relationship("Chat", back_populates="messages")


class ModelConfig(Base):
    __tablename__ = "model_configs"
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, unique=True)  # groq, openai, ollama, etc.
    api_key = Column(String)
    model_name = Column(String)
    auth_mode = Column(String, default="api_key")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class UsageLog(Base):
    __tablename__ = "usage_logs"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=True)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)


class AgentRun(Base):
    """Durable metadata for one AI processing run."""
    __tablename__ = "agent_runs"
    id = Column(String, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    assistant_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    model = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index(
            "ux_agent_runs_one_active_chat",
            "chat_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    chat = relationship("Chat", back_populates="agent_runs")


class ActionApproval(Base):
    """User approval state for one sensitive agent action."""
    __tablename__ = "action_approvals"
    id = Column(String, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    assistant_message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    run_id = Column(String, ForeignKey("agent_runs.id"), nullable=True, index=True)
    action_type = Column(String, nullable=False, default="ssh_command", index=True)
    system_name = Column(String, nullable=True)
    command = Column(Text, nullable=False)
    risk_level = Column(String, nullable=False, default="high")
    reason = Column(Text, nullable=False, default="")
    status = Column(String, nullable=False, default="pending", index=True)
    user_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ux_action_approvals_one_pending_chat",
            "chat_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    chat = relationship("Chat", back_populates="action_approvals")


class CronJob(Base):
    __tablename__ = "cron_jobs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    model = Column(String, nullable=False)
    schedule = Column(String, nullable=False)  # cron expression
    enabled = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class AuthSetting(Base):
    __tablename__ = "auth_settings"
    id = Column(Integer, primary_key=True, default=1)  # Singleton table
    enabled = Column(Boolean, default=False)
    session_timeout = Column(Integer, default=3600)
    max_failed_attempts = Column(Integer, default=5)
    lockout_duration = Column(Integer, default=900)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    last_login = Column(DateTime, nullable=True)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)


class System(Base):
    __tablename__ = "systems"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    host = Column(String, nullable=False)
    port = Column(Integer, default=22)
    username = Column(String, nullable=False)
    ssh_key_path = Column(String, nullable=True)
    tags = Column(Text)  # JSON-serialized list
    description = Column(Text, default="")  # multi-line markdown notes for AI
    connection_id = Column(String, nullable=True)
    parent_id = Column(String, ForeignKey("systems.id"), nullable=True)  # Hierarchical structure
    order = Column(Integer, default=0)  # Display order within parent
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    # Self-referential relationship for hierarchy
    children = relationship("System", backref="parent", remote_side=[id], cascade="all")


class AppLog(Base):
    __tablename__ = "app_logs"
    id = Column(Integer, primary_key=True, index=True)
    level = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    username = Column(String, nullable=True, index=True)
    host = Column(String, nullable=True, index=True)
    chat_id = Column(Integer, nullable=True, index=True)
    model = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow, index=True)


class AgentMemory(Base):
    """Cross-session persistent memory for the agent."""
    __tablename__ = "agent_memory"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)            # JSON-encoded value
    category = Column(String, nullable=False, default="general", index=True)
    chat_id = Column(Integer, nullable=True, index=True)
    access_count = Column(Integer, default=0)
    last_accessed = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)    # NULL = never expires
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Attachment(Base):
    """File attachments uploaded alongside chat messages."""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, index=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    filename = Column(String, nullable=False)        # UUID-based stored filename
    original_name = Column(String, nullable=False)  # user-facing filename
    mime_type = Column(String, nullable=False, default="application/octet-stream")
    size_bytes = Column(Integer, default=0)
    is_image = Column(Boolean, default=False)
    text_content = Column(Text, nullable=True)       # extracted text (txt/json/md/pdf)
    created_at = Column(DateTime, default=utcnow)

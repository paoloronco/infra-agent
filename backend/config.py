from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # LLM Configuration (legacy — keys are now managed via the Models page in the DB)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.3

    # SSH Configuration
    default_ssh_timeout: int = 30
    max_concurrent_ssh_connections: int = 5

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    api_title: str = "SSH Troubleshooting AI Agent"
    api_version: str = "1.0.0"
    public_base_url: str = ""
    enable_api_docs: bool = False

    # CORS Configuration
    cors_origins: list = ["http://localhost:3000", "http://localhost:5173"]

    # Logging
    log_level: str = "INFO"
    log_retention_days: int = 30

    # Database. Defaults to local SQLite; set DATABASE_URL for Postgres/MySQL/etc.
    database_url: str = ""

    # Security
    auth_enabled_by_default: bool = False
    enable_command_validation: bool = True
    strict_ssh_host_key_checking: bool = False
    dangerous_commands_blacklist: list = [
        "rm -rf",
        "dd if=/dev/zero",
        ":(){:|:&};:",
        "mkfs",
        "fdisk",
    ]

    class Config:
        env_file = ".env"
        case_sensitive = False


# Load settings
settings = Settings()

"""Model provider configuration endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app_logging import log_event
from crypto import encrypt_secret, decrypt_secret_deep, is_encrypted
from db import get_db
from models_db import ModelConfig
from models_registry import PROVIDERS

router = APIRouter(prefix="/api/models", tags=["models"])
logger = logging.getLogger(__name__)


class ProviderUpdate(BaseModel):
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    auth_mode: Optional[str] = None
    enabled: Optional[bool] = None


OPENAI_AUTH_MODE_API_KEY = "api_key"
_INVALID_API_KEY_VALUES = {
    "",
    "your_api_key_here",
    "your_groq_api_key_here",
    "your_openai_api_key_here",
    "your_anthropic_api_key_here",
    "your_google_api_key_here",
}


def _is_usable_api_key(value: Optional[str]) -> bool:
    if not value:
        return False
    cleaned = value.strip()
    if not cleaned:
        return False
    if is_encrypted(cleaned):
        return False
    lowered = cleaned.lower()
    return lowered not in _INVALID_API_KEY_VALUES and not lowered.startswith("your_")


def _preview_api_key(value: Optional[str]) -> Optional[str]:
    if not _is_usable_api_key(value):
        return None
    return value[:8] + "..."


def _ensure_auth_mode_column(db: Session) -> None:
    """Keep the providers endpoint usable even if an old DB missed Alembic."""
    bind = db.get_bind()
    inspector = inspect(bind)
    if any(col["name"] == "auth_mode" for col in inspector.get_columns("model_configs")):
        return
    db.execute(text("ALTER TABLE model_configs ADD COLUMN auth_mode VARCHAR DEFAULT 'api_key'"))
    db.commit()


def _openai_auth_metadata(api_key_set: bool) -> dict:
    return {
        "auth_mode": OPENAI_AUTH_MODE_API_KEY,
        "modes": [
            {
                "id": OPENAI_AUTH_MODE_API_KEY,
                "label": "Use API key",
                "available": True,
                "configured": api_key_set,
                "billing": "OpenAI Platform API billing",
                "description": "Server-side OpenAI API access using a project API key.",
            },
        ],
    }


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    _ensure_auth_mode_column(db)
    configs = {c.provider: c for c in db.query(ModelConfig).all()}
    result = []
    for pid, pinfo in PROVIDERS.items():
        cfg = configs.get(pid)
        raw_key = decrypt_secret_deep(cfg.api_key) if cfg and cfg.api_key else None
        if not raw_key and pid == "groq":
            from config import settings
            raw_key = settings.groq_api_key or None
        key_is_set = _is_usable_api_key(raw_key)
        auth_mode = OPENAI_AUTH_MODE_API_KEY
        if pid == "openai" and cfg and cfg.auth_mode != OPENAI_AUTH_MODE_API_KEY:
            cfg.auth_mode = OPENAI_AUTH_MODE_API_KEY
            db.commit()
        auth_metadata = _openai_auth_metadata(key_is_set) if pid == "openai" else None
        result.append({
            "id": pid,
            "name": pinfo["name"],
            "models": pinfo["models"],
            "docs_url": pinfo["docs_url"],
            "api_key_set": key_is_set,
            "api_key_preview": _preview_api_key(raw_key),
            "model_name": cfg.model_name if cfg else (pinfo["models"][0] if pinfo["models"] else None),
            "auth_mode": auth_mode,
            "auth": auth_metadata,
            "enabled": cfg.enabled if cfg else False,
        })
    return result


@router.put("/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdate, db: Session = Depends(get_db)):
    if provider_id not in PROVIDERS:
        raise HTTPException(404, "Provider not found")

    _ensure_auth_mode_column(db)
    cfg = db.query(ModelConfig).filter(ModelConfig.provider == provider_id).first()
    if not cfg:
        cfg = ModelConfig(provider=provider_id)
        db.add(cfg)

    if body.auth_mode is not None:
        if provider_id != "openai":
            raise HTTPException(400, "Authentication mode is only configurable for OpenAI")
        if body.auth_mode == OPENAI_AUTH_MODE_API_KEY:
            cfg.auth_mode = OPENAI_AUTH_MODE_API_KEY
        else:
            raise HTTPException(400, "Only OpenAI API key mode is supported")

    if body.api_key is not None:
        # Encrypt non-empty keys; store empty string as-is (clearing the key)
        cfg.api_key = encrypt_secret(decrypt_secret_deep(body.api_key)) if body.api_key else ""
    if body.model_name is not None:
        cfg.model_name = body.model_name
    if body.enabled is not None:
        cfg.enabled = body.enabled

    db.commit()
    log_event(
        level="INFO",
        category="model",
        event_type="provider_updated",
        message=f"Model provider updated: {provider_id}",
        source="routers.models_config",
        model=cfg.model_name,
        details={
            "provider": provider_id,
            "enabled": cfg.enabled,
            "has_api_key": bool(cfg.api_key),
            "auth_mode": cfg.auth_mode or OPENAI_AUTH_MODE_API_KEY,
        },
    )
    return {"success": True}


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, db: Session = Depends(get_db)):
    _ensure_auth_mode_column(db)
    cfg = db.query(ModelConfig).filter(ModelConfig.provider == provider_id).first()
    if cfg and cfg.api_key:
        key = decrypt_secret_deep(cfg.api_key)
    elif provider_id == "groq":
        from config import settings
        key = settings.groq_api_key or None
    else:
        key = None

    if not _is_usable_api_key(key) and provider_id != "ollama":
        return {"success": False, "message": "No API key configured"}

    try:
        if provider_id == "groq":
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage
            llm = ChatGroq(model="llama-3.1-8b-instant", api_key=key, max_tokens=5)
            llm.invoke([HumanMessage(content="hi")])
            log_event(level="INFO", category="model", event_type="provider_test_success",
                      message=f"Provider test succeeded: {provider_id}", source="routers.models_config",
                      model="llama-3.1-8b-instant")
            return {"success": True, "message": "Connection successful"}

        elif provider_id == "openai":
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage
            ChatOpenAI(api_key=key, model="gpt-4o-mini", max_tokens=5).invoke([HumanMessage(content="hi")])
            log_event(level="INFO", category="model", event_type="provider_test_success",
                      message=f"Provider test succeeded: {provider_id}", source="routers.models_config",
                      model="gpt-4o-mini")
            return {"success": True, "message": "Connection successful"}

        elif provider_id == "anthropic":
            from langchain_anthropic import ChatAnthropic
            from langchain_core.messages import HumanMessage
            ChatAnthropic(model="claude-3-5-haiku-20241022", api_key=key, max_tokens=5).invoke([HumanMessage(content="hi")])
            log_event(level="INFO", category="model", event_type="provider_test_success",
                      message=f"Provider test succeeded: {provider_id}", source="routers.models_config",
                      model="claude-3-5-haiku-20241022")
            return {"success": True, "message": "Connection successful"}

        elif provider_id == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.messages import HumanMessage
            ChatGoogleGenerativeAI(model="gemini-1.5-flash", google_api_key=key, max_tokens=5).invoke([HumanMessage(content="hi")])
            log_event(level="INFO", category="model", event_type="provider_test_success",
                      message=f"Provider test succeeded: {provider_id}", source="routers.models_config",
                      model="gemini-1.5-flash")
            return {"success": True, "message": "Connection successful"}

        elif provider_id == "ollama":
            import requests as req
            ollama_url = (cfg.model_name if cfg and cfg.model_name and cfg.model_name.startswith("http")
                          else "http://localhost:11434")
            resp = req.get(f"{ollama_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                return {"success": True, "message": "Ollama server connected successfully"}
            return {"success": False, "message": "Cannot connect to Ollama server"}

        elif provider_id in ("deepseek", "mistral_ai", "xai", "perplexity", "nvidia",
                              "openrouter", "zhipu", "huggingface"):
            _TEST_MODELS = {
                "deepseek":    "deepseek-chat",
                "mistral_ai":  "mistral-small-latest",
                "xai":         "grok-3-fast",
                "perplexity":  "sonar",
                "nvidia":      "meta/llama-3.3-70b-instruct",
                "openrouter":  "meta-llama/llama-3.3-70b-instruct:free",
                "zhipu":       "glm-4-flash",
                "huggingface": "Qwen/Qwen2.5-72B-Instruct",
            }
            _BASE_URLS = {
                "deepseek":    "https://api.deepseek.com/v1",
                "mistral_ai":  "https://api.mistral.ai/v1",
                "xai":         "https://api.x.ai/v1",
                "perplexity":  "https://api.perplexity.ai",
                "nvidia":      "https://integrate.api.nvidia.com/v1",
                "openrouter":  "https://openrouter.ai/api/v1",
                "zhipu":       "https://open.bigmodel.cn/api/paas/v4/",
                "huggingface": "https://api-inference.huggingface.co/v1/",
            }
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage as HM
            kw = dict(
                model=_TEST_MODELS[provider_id],
                api_key=key,
                base_url=_BASE_URLS[provider_id],
                max_tokens=5,
            )
            if provider_id == "openrouter":
                kw["default_headers"] = {"HTTP-Referer": "ai-agent-ssh-troubleshooter"}
            if provider_id != "perplexity":
                kw["temperature"] = 0.0
            ChatOpenAI(**kw).invoke([HM(content="hi")])
            return {"success": True, "message": "Connection successful"}

        else:
            return {"success": True, "message": "Key saved (test not implemented for this provider yet)"}

    except Exception as e:
        logger.error("Provider test failed for %s: %s", provider_id, e)
        log_event(
            level="ERROR", category="model", event_type="provider_test_failed",
            message=f"Provider test failed: {provider_id}", source="routers.models_config",
            model=cfg.model_name if cfg else None,
            details={"error": str(e)},
        )
        return {"success": False, "message": str(e)}

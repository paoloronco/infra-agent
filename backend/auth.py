"""
Authentication system for SSH Agent.
Supports username/password with JWT tokens.
"""
import base64
import hashlib
import hmac
import os
import secrets
import logging
from pathlib import Path
from typing import Optional, Dict, List
from pydantic import BaseModel
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from utils import utcnow
import jwt
from app_logging import log_event

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
except Exception:  # pragma: no cover - dependency fallback for local/dev envs
    PasswordHasher = None
    InvalidHashError = VerificationError = VerifyMismatchError = Exception

logger = logging.getLogger(__name__)
_PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4) if PasswordHasher else None
_PBKDF2_ITERATIONS = 600_000

# ── JWT helpers ───────────────────────────────────────────────────────────────

_SECRET_KEY: Optional[str] = None

def _get_secret_key() -> str:
    global _SECRET_KEY
    if _SECRET_KEY:
        return _SECRET_KEY
    key_file = Path(__file__).resolve().parent / "data" / "secret_key.txt"
    key_file.parent.mkdir(exist_ok=True)
    if key_file.exists():
        _SECRET_KEY = key_file.read_text().strip()
    else:
        _SECRET_KEY = secrets.token_hex(32)
        key_file.write_text(_SECRET_KEY)
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
    return _SECRET_KEY

def _get_session_timeout_hours() -> int:
    """Read session_timeout (seconds) from DB AuthSetting, convert to hours. Default 24h."""
    try:
        from db import SessionLocal
        from models_db import AuthSetting
        db = SessionLocal()
        try:
            setting = db.query(AuthSetting).filter(AuthSetting.id == 1).first()
            if setting and setting.session_timeout:
                return max(1, setting.session_timeout // 3600)
        finally:
            db.close()
    except Exception:
        pass
    return 24


def create_access_token(username: str, hours: Optional[int] = None) -> str:
    token_hours = hours if hours is not None else _get_session_timeout_hours()
    payload = {
        "sub": username,
        "exp": utcnow() + timedelta(hours=token_hours),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm="HS256")

def verify_token(token: str) -> Optional[str]:
    """Returns username if token is valid, else None."""
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None

# Pydantic models
class AuthConfig(BaseModel):
    enabled: bool = False
    session_timeout: int = 3600  # 1 hour
    max_failed_attempts: int = 5
    lockout_duration: int = 900  # 15 minutes

class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False

class UserUpdate(BaseModel):
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    username: str
    is_admin: bool
    is_active: bool
    created_at: str
    last_login: Optional[str] = None
    failed_attempts: int
    is_locked: bool

# Auth state management (DB-backed)
def _auth_enabled_by_default() -> bool:
    """Read first-boot auth default from env; persisted DB state wins afterwards."""
    return os.getenv("AUTH_ENABLED_BY_DEFAULT", "false").strip().lower() in {"1", "true", "yes", "on"}


def get_auth_enabled() -> bool:
    """Load auth_enabled state from database."""
    from db import SessionLocal
    from models_db import AuthSetting
    db = SessionLocal()
    try:
        setting = db.query(AuthSetting).filter(AuthSetting.id == 1).first()
        if not setting:
            setting = AuthSetting(id=1, enabled=_auth_enabled_by_default())
            db.add(setting)
            db.commit()
        return setting.enabled
    finally:
        db.close()

def set_auth_enabled(enabled: bool):
    """Persist auth_enabled state to database."""
    from db import SessionLocal
    from models_db import AuthSetting
    db = SessionLocal()
    try:
        setting = db.query(AuthSetting).filter(AuthSetting.id == 1).first()
        if not setting:
            setting = AuthSetting(id=1, enabled=enabled)
            db.add(setting)
        else:
            setting.enabled = enabled
        db.commit()
        logger.info("Auth enabled set to: %s", enabled)
        log_event(
            level="WARNING" if enabled else "INFO",
            category="auth",
            event_type="auth_toggled",
            message=f"Authentication {'enabled' if enabled else 'disabled'}",
            source="auth",
            details={"enabled": enabled},
        )
    finally:
        db.close()

# Password utilities
def hash_password(password: str) -> str:
    """Hash password using Argon2id, with PBKDF2 fallback if argon2 is unavailable."""
    if _PASSWORD_HASHER:
        return "argon2id$" + _PASSWORD_HASHER.hash(password)

    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )

def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash."""
    if not stored_hash:
        return False

    try:
        if stored_hash.startswith("argon2id$") and _PASSWORD_HASHER:
            _PASSWORD_HASHER.verify(stored_hash.removeprefix("argon2id$"), password)
            return True

        if stored_hash.startswith("pbkdf2_sha256$"):
            _, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(digest_b64.encode("ascii"))
            computed = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                int(iterations),
            )
            return hmac.compare_digest(computed, expected)

        # Legacy format kept only for transparent migration on next successful login.
        salt, password_hash = stored_hash.split(':')
        computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return hmac.compare_digest(computed_hash, password_hash)
    except (ValueError, InvalidHashError, VerificationError, VerifyMismatchError):
        return False

def password_needs_rehash(stored_hash: str) -> bool:
    """Return True for legacy or weaker hashes so login can migrate them."""
    if not stored_hash:
        return True
    if stored_hash.startswith("argon2id$") and _PASSWORD_HASHER:
        try:
            return _PASSWORD_HASHER.check_needs_rehash(stored_hash.removeprefix("argon2id$"))
        except (InvalidHashError, VerificationError):
            return True
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, _, _ = stored_hash.split("$", 3)
            return int(iterations) < _PBKDF2_ITERATIONS or _PASSWORD_HASHER is not None
        except ValueError:
            return True
    return True

def init_default_admin():
    """Initialize default admin user if no users exist."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        admin = db.query(UserAccount).filter(UserAccount.username == "admin").first()
        if not admin:
            password_file = Path(__file__).resolve().parent / "data" / "bootstrap_admin_password.txt"
            configured_password = os.getenv("AI_AGENT_ADMIN_PASSWORD", "").strip()
            initial_password = configured_password or secrets.token_urlsafe(18)
            admin = UserAccount(
                username="admin",
                password_hash=hash_password(initial_password),
                is_admin=True,
                is_active=True
            )
            db.add(admin)
            db.commit()
            if not configured_password:
                password_file.write_text(initial_password + "\n", encoding="utf-8")
                try:
                    os.chmod(password_file, 0o600)
                except Exception:
                    pass
            logger.warning(
                "Initial admin user created. Username: admin. %s",
                "Password loaded from AI_AGENT_ADMIN_PASSWORD."
                if configured_password
                else f"Initial password written to {password_file}",
            )
            log_event(
                level="WARNING",
                category="auth",
                event_type="default_admin_created",
                message="Default admin user created",
                source="auth",
                username="admin",
                details={
                    "password_source": "env" if configured_password else "bootstrap_file",
                    "bootstrap_password_file": str(password_file) if not configured_password else None,
                },
            )
    finally:
        db.close()

def is_account_locked(username: str) -> bool:
    """Check if account is locked due to failed attempts."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if not user:
            return False
        
        if user.locked_until and utcnow() < user.locked_until:
            return True
        
        # Reset lockout if time has passed
        if user.locked_until and utcnow() >= user.locked_until:
            user.failed_attempts = 0
            user.locked_until = None
            db.commit()
            return False
        
        return False
    finally:
        db.close()

def record_failed_attempt(username: str, max_attempts: int, lockout_duration: int):
    """Record failed login attempt and lock account if needed."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if not user:
            return
        
        user.failed_attempts += 1
        
        if user.failed_attempts >= max_attempts:
            user.locked_until = utcnow() + timedelta(seconds=lockout_duration)
            logger.warning("Account %s locked due to too many failed attempts", username)
            log_event(
                level="WARNING",
                category="auth",
                event_type="account_locked",
                message=f"Account locked due to failed attempts: {username}",
                source="auth",
                username=username,
                details={"failed_attempts": user.failed_attempts, "lockout_duration": lockout_duration},
            )
        
        db.commit()
    finally:
        db.close()

def verify_user(username: str, password: str, max_attempts: int = 5, lockout_duration: int = 900) -> bool:
    """Verify user credentials."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()

        if not user or not user.is_active:
            return False

        # Inline lockout check — avoids opening a second DB session inside verify_user
        now = utcnow()
        if user.locked_until:
            if now < user.locked_until:
                return False
            # Reset expired lockout within the same session
            user.failed_attempts = 0
            user.locked_until = None
            db.commit()

        if verify_password(password, user.password_hash):
            # Reset failed attempts on successful login
            if password_needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            user.failed_attempts = 0
            user.last_login = utcnow()
            db.commit()
            log_event(
                level="INFO",
                category="auth",
                event_type="login_success",
                message=f"User authenticated: {username}",
                source="auth",
                username=username,
            )
            return True
        else:
            record_failed_attempt(username, max_attempts, lockout_duration)
            log_event(
                level="WARNING",
                category="auth",
                event_type="login_failed",
                message=f"Invalid credentials for user: {username}",
                source="auth",
                username=username,
            )
            return False
    finally:
        db.close()

def create_user(username: str, password: str, is_admin: bool = False) -> bool:
    """Create a new user."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        existing = db.query(UserAccount).filter(UserAccount.username == username).first()
        if existing:
            return False
        
        user = UserAccount(
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
            is_active=True
        )
        db.add(user)
        db.commit()
        logger.info("User %s created (admin: %s)", username, is_admin)
        log_event(
            level="INFO",
            category="auth",
            event_type="user_created",
            message=f"User created: {username}",
            source="auth",
            username=username,
            details={"is_admin": is_admin},
        )
        return True
    finally:
        db.close()

def update_user(username: str, updates: Dict) -> bool:
    """Update user information."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if not user:
            return False
        
        if "password" in updates:
            user.password_hash = hash_password(updates["password"])
        
        if "is_admin" in updates:
            user.is_admin = updates["is_admin"]
        
        if "is_active" in updates:
            user.is_active = updates["is_active"]
        
        db.commit()
        logger.info("User %s updated", username)
        log_event(
            level="INFO",
            category="auth",
            event_type="user_updated",
            message=f"User updated: {username}",
            source="auth",
            username=username,
            details={key: value for key, value in updates.items() if key != "password"},
        )
        return True
    finally:
        db.close()

def delete_user(username: str) -> bool:
    """Delete a user."""
    if username == "admin":
        return False  # Cannot delete admin
    
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if user:
            db.delete(user)
            db.commit()
            logger.info("User %s deleted", username)
            log_event(
                level="WARNING",
                category="auth",
                event_type="user_deleted",
                message=f"User deleted: {username}",
                source="auth",
                username=username,
            )
            return True
        return False
    finally:
        db.close()

def list_users() -> List[Dict]:
    """List all users (excluding password hashes)."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        now = utcnow()
        users = db.query(UserAccount).all()
        return [
            {
                "username": u.username,
                "is_admin": u.is_admin,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "failed_attempts": u.failed_attempts,
                # Inline check — avoids N+1 DB sessions (one per user)
                "is_locked": bool(u.locked_until and now < u.locked_until),
            }
            for u in users
        ]
    finally:
        db.close()

def get_user(username: str) -> Optional[Dict]:
    """Get user details (excluding password hash)."""
    from db import SessionLocal
    from models_db import UserAccount
    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if not user:
            return None
        
        return {
            "username": user.username,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "failed_attempts": user.failed_attempts,
            "is_locked": is_account_locked(username)
        }
    finally:
        db.close()

# FastAPI dependency for authentication
_bearer = HTTPBearer(auto_error=False)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Dict:
    auth_enabled = get_auth_enabled()
    if not auth_enabled:
        return {"username": "admin", "is_admin": True, "is_active": True}

    token = credentials.credentials if credentials else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})

    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})

    user = get_user(username)
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="Account inactive")

    return user

def require_admin(current_user: Dict = Depends(get_current_user)) -> Dict:
    if not current_user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

def change_password(username: str, old_password: str, new_password: str) -> bool:
    """Change password after verifying the old one. Returns False if old password wrong."""
    if not verify_user(username, old_password):
        return False
    return update_user(username, {"password": new_password})


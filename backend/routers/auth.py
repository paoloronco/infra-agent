"""Authentication management endpoints."""
import logging
import secrets
import string
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from auth import (
    get_auth_enabled, set_auth_enabled, AuthConfig, UserCreate, UserUpdate, UserResponse,
    create_user, update_user, delete_user, list_users, get_user,
    require_admin, get_current_user, verify_user, create_access_token, change_password,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["authentication"])

limiter = Limiter(key_func=get_remote_address)


def _generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
@limiter.limit("5/minute")
def login(body: LoginRequest, request: Request):
    """Authenticate and return a JWT token."""
    if not verify_user(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials or account locked")
    token = create_access_token(body.username)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/change-password")
def change_my_password(body: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    """Change the current user's password (requires old password)."""
    if not change_password(current_user["username"], body.old_password, body.new_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return {"success": True, "message": "Password changed successfully"}

# ── Authentication Configuration ───────────────────────────────────────

@router.get("/config")
def get_auth_config():
    """Get current authentication configuration."""
    auth_enabled = get_auth_enabled()
    return {
        "enabled": auth_enabled,
        "message": "Authentication is enabled" if auth_enabled else "Authentication is disabled",
    }

@router.put("/config")
def update_auth_config(config: AuthConfig, current_user: dict = Depends(require_admin)):
    """Update authentication configuration."""
    auth_enabled = get_auth_enabled()
    
    if config.enabled and not auth_enabled:
        # Enable authentication
        set_auth_enabled(True)
        logger.info("Authentication enabled (persisted to DB)")
        return {
            "enabled": True,
            "message": "Authentication enabled. Use the configured admin account or the generated bootstrap password from backend/data/bootstrap_admin_password.txt."
        }
    elif not config.enabled and auth_enabled:
        # Disable authentication
        set_auth_enabled(False)
        logger.info("Authentication disabled (persisted to DB)")
        return {
            "enabled": False,
            "message": "Authentication disabled"
        }
    
    return {
        "enabled": get_auth_enabled(),
        "message": f"Authentication is {'enabled' if get_auth_enabled() else 'disabled'}"
    }

# ── User Management ─────────────────────────────────────────────────────

@router.get("/users", response_model=List[UserResponse])
def list_all_users(current_user: dict = Depends(require_admin)):
    """List all users (admin only)."""
    return list_users()

@router.post("/users")
def create_new_user(user: UserCreate, current_user: dict = Depends(require_admin)):
    """Create a new user (admin only)."""
    auth_enabled = get_auth_enabled()
    if not auth_enabled:
        raise HTTPException(400, "Authentication must be enabled first")
    
    if create_user(user.username, user.password, user.is_admin):
        return {"success": True, "message": f"User {user.username} created"}
    else:
        raise HTTPException(400, f"User {user.username} already exists")

@router.put("/users/{username}")
def update_existing_user(username: str, updates: UserUpdate, current_user: dict = Depends(require_admin)):
    """Update a user (admin only)."""
    auth_enabled = get_auth_enabled()
    if not auth_enabled:
        raise HTTPException(400, "Authentication must be enabled first")
    
    if username == "admin" and updates.is_admin is not None and not updates.is_admin:
        raise HTTPException(400, "Cannot remove admin privileges from admin user")
    
    update_data = {}
    if updates.password:
        update_data["password"] = updates.password
    if updates.is_admin is not None:
        update_data["is_admin"] = updates.is_admin
    if updates.is_active is not None:
        update_data["is_active"] = updates.is_active
    
    if update_user(username, update_data):
        return {"success": True, "message": f"User {username} updated"}
    else:
        raise HTTPException(404, f"User {username} not found")

@router.delete("/users/{username}")
def delete_existing_user(username: str, current_user: dict = Depends(require_admin)):
    """Delete a user (admin only)."""
    auth_enabled = get_auth_enabled()
    if not auth_enabled:
        raise HTTPException(400, "Authentication must be enabled first")
    
    if username == "admin":
        raise HTTPException(400, "Cannot delete admin user")
    
    if delete_user(username):
        return {"success": True, "message": f"User {username} deleted"}
    else:
        raise HTTPException(404, f"User {username} not found")

@router.get("/users/{username}", response_model=UserResponse)
def get_user_details(username: str, current_user: dict = Depends(require_admin)):
    """Get user details (admin only)."""
    user = get_user(username)
    if not user:
        raise HTTPException(404, f"User {username} not found")
    return user

# ── Password Reset ─────────────────────────────────────────────────────

@router.post("/reset-password/{username}")
def reset_user_password(username: str, current_user: dict = Depends(require_admin)):
    """Reset user password to a random temporary password (admin only)."""
    auth_enabled = get_auth_enabled()
    if not auth_enabled:
        raise HTTPException(400, "Authentication must be enabled first")

    new_password = _generate_temp_password()

    if update_user(username, {"password": new_password}):
        logger.info("Password reset for user %s by admin %s", username, current_user['username'])
        return {
            "success": True,
            "message": f"Password for {username} has been reset",
            "new_password": new_password,
        }
    else:
        raise HTTPException(404, f"User {username} not found")

@router.get("/me")
def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information."""
    return current_user

# ── Status and Health ───────────────────────────────────────────────────

@router.get("/status")
def get_auth_status():
    """Get authentication system status."""
    auth_enabled = get_auth_enabled()
    users = list_users()
    return {
        "enabled": auth_enabled,
        "user_count": len(users),
        "admin_users": [u["username"] for u in users if u["is_admin"]],
        "active_users": [u["username"] for u in users if u["is_active"]]
    }

"""
Fernet-based encryption for sensitive values (API keys, secrets).

Key derivation: uses the JWT secret key (already persisted in data/secret_key.txt)
as the entropy source, deriving a 32-byte Fernet-compatible key via SHA-256 + base64.

Migration path: values that cannot be decrypted are returned as-is (unencrypted
plain text). This allows upgrading existing DBs transparently on the first save.
"""
import base64
import hashlib
import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_SECRET_KEY_FILE = Path(__file__).parent / "data" / "secret_key.txt"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    # Read the JWT secret (created on first startup by auth.py)
    if not _SECRET_KEY_FILE.exists():
        # Fallback: derive from a fixed string — will be replaced once auth.py writes the real key
        raw = b"ai-agent-ssh-fallback-encryption-key-v1"
    else:
        raw = _SECRET_KEY_FILE.read_bytes().strip()

    # Derive a 32-byte key and base64url-encode it to satisfy Fernet
    digest = hashlib.sha256(raw).digest()
    key = base64.urlsafe_b64encode(digest)
    _fernet = Fernet(key)
    return _fernet


def encrypt_secret(value: str) -> str:
    """Encrypt a plaintext secret. Returns a Fernet token string."""
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """
    Decrypt a Fernet token.
    If the value is not a valid token (e.g. plain text from before encryption was added),
    returns it as-is so existing unencrypted values continue to work.
    """
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeDecodeError):
        # Not encrypted — return as plain text (migration path)
        return value


def is_encrypted(value: str) -> bool:
    """Return True if value looks like a Fernet token (starts with 'gAAAA')."""
    return bool(value and value.startswith("gAAAA"))


def decrypt_secret_deep(value: str, *, max_depth: int = 3) -> str:
    """
    Decrypt a secret repeatedly.

    This keeps old plaintext values working and also recovers API keys restored by
    older backup code that accidentally encrypted an already encrypted DB token.
    """
    if not value:
        return value
    current = value
    for _ in range(max_depth):
        if not is_encrypted(current):
            return current
        decrypted = decrypt_secret(current)
        if decrypted == current:
            return decrypted
        current = decrypted
    return current

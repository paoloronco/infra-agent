"""Regression tests for AIB backup encryption headers."""
import io
import json
import zipfile

from routers.backup import (
    BACKUP_FORMAT_VERSION,
    _backup_encryption_version,
    _decrypt_zip,
    _encrypt_zip,
    _is_encrypted_backup,
)


def _sample_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "data.json",
            json.dumps({
                "_meta": {
                    "format_version": BACKUP_FORMAT_VERSION,
                    "includes": [],
                    "record_counts": {},
                }
            }),
        )
    return buf.getvalue()


def test_aibenc2_backup_round_trip_decrypts():
    encrypted = _encrypt_zip(_sample_zip(), "correct horse battery staple")

    assert encrypted.startswith(b"AIBENC2")
    assert _is_encrypted_backup(encrypted)
    assert _backup_encryption_version(encrypted) == "AIBENC2"

    decrypted = _decrypt_zip(encrypted, "correct horse battery staple")
    with zipfile.ZipFile(io.BytesIO(decrypted)) as zf:
        manifest = json.loads(zf.read("data.json"))

    assert manifest["_meta"]["format_version"] == BACKUP_FORMAT_VERSION


if __name__ == "__main__":
    test_aibenc2_backup_round_trip_decrypts()
    print("backup_encryption_ok")

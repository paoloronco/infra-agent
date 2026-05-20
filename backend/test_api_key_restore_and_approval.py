"""Regression checks for API key restore and risky-action approval creation."""

import json

from agent_loader import _approval_from_tool_output, _approval_required_payload
from crypto import decrypt_secret_deep, encrypt_secret
from routers.backup import _deobfuscate, _obfuscate
from routers.chat import _approval_from_textual_risky_response
from routers.models_config import _is_usable_api_key


def test_decrypt_secret_deep_recovers_double_encrypted_api_key():
    raw_key = "sk-test-openai-key"
    encrypted_once = encrypt_secret(raw_key)
    encrypted_twice = encrypt_secret(encrypted_once)

    assert decrypt_secret_deep(encrypted_once) == raw_key
    assert decrypt_secret_deep(encrypted_twice) == raw_key


def test_legacy_backup_obfuscated_encrypted_key_restores_plain_key():
    raw_key = "sk-test-openai-key"
    legacy_backup_value = _obfuscate(encrypt_secret(raw_key))

    restored_plain = decrypt_secret_deep(_deobfuscate(legacy_backup_value))
    restored_db_value = encrypt_secret(restored_plain)

    assert restored_plain == raw_key
    assert decrypt_secret_deep(restored_db_value) == raw_key


def test_unrestorable_encrypted_token_is_not_treated_as_api_key():
    assert not _is_usable_api_key("gAAAA_unrestorable_ciphertext")


def test_approval_marker_is_detected_when_wrapped_by_runtime_messages():
    payload = _approval_required_payload(
        system_name="web-prod",
        command="rm /root/test1.txt",
        risk_level="high",
        reason="deletes files or data",
    )

    direct = _approval_from_tool_output(payload)
    assert direct.command == "rm /root/test1.txt"

    wrapped = _approval_from_tool_output({"content": payload})
    assert wrapped.system_name == "web-prod"

    mixed = _approval_from_tool_output(f"tool output follows:\n{payload}\nwaiting")
    assert mixed.reason == "deletes files or data"

    list_wrapped = _approval_from_tool_output([{"type": "text", "text": payload}])
    assert list_wrapped.risk_level == "high"

    parsed_dict = _approval_from_tool_output(json.loads(payload))
    assert parsed_dict.command == "rm /root/test1.txt"


def test_textual_risky_command_response_becomes_runtime_approval():
    response = (
        "To delete the file I need to use this command and wait for approval:\n\n"
        "```bash\nrm /root/test1.txt\n```"
    )
    approval = _approval_from_textual_risky_response(
        text=response,
        query="delete /root/test1.txt",
        current_host="web-prod",
    )

    assert approval is not None
    assert approval.system_name == "web-prod"
    assert approval.command == "rm /root/test1.txt"
    assert approval.risk_level == "high"


def test_read_only_text_response_does_not_become_approval():
    response = "I checked the service status: nginx is active."
    approval = _approval_from_textual_risky_response(
        text=response,
        query="check nginx status",
        current_host="web-prod",
    )

    assert approval is None


if __name__ == "__main__":
    test_decrypt_secret_deep_recovers_double_encrypted_api_key()
    test_legacy_backup_obfuscated_encrypted_key_restores_plain_key()
    test_unrestorable_encrypted_token_is_not_treated_as_api_key()
    test_approval_marker_is_detected_when_wrapped_by_runtime_messages()
    test_textual_risky_command_response_becomes_runtime_approval()
    test_read_only_text_response_does_not_become_approval()
    print("api_key_restore_and_approval_ok")

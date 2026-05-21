"""Regression checks for Groq agent compatibility."""

from langchain_core.messages import AIMessage

from agent_loader import _message_text
from models_registry import canonical_model_id, get_provider


def test_legacy_llama4_groq_ids_are_canonicalized():
    assert canonical_model_id("llama-4-scout-17b-16e-instruct") == (
        "meta-llama/llama-4-scout-17b-16e-instruct"
    )
    assert canonical_model_id("llama-4-maverick-17b-128e-instruct") == (
        "meta-llama/llama-4-maverick-17b-128e-instruct"
    )
    assert get_provider("llama-4-scout-17b-16e-instruct") == "groq"


def test_message_text_preserves_non_streamed_text_blocks():
    message = AIMessage(content=[{"type": "text", "text": "Groq"}, " response"])

    assert _message_text(message) == "Groq response"

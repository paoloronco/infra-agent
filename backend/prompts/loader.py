"""
Versioned, layered prompt loading and composition.

Prompts are assembled from ordered .md layer files in prompts/layers/.
Each layer addresses a distinct concern (identity, rules, tools, safety, etc.).
Layers are versioned — the assembled prompt carries a version string for tracing.
"""
import os
import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROMPT_VERSION = "3.1.0"
LAYERS_DIR = os.path.join(os.path.dirname(__file__), "layers")

LAYER_ORDER: List[str] = [
    "00_core_identity.md",
    "01_operational_rules.md",
    "02_tool_policies.md",
    "03_safety_policies.md",
    "04_output_format.md",
    "05_recovery_behaviors.md",
    "06_failure_handling.md",
    "07_attachment_handling.md",
]

_layer_cache: Dict[str, str] = {}


def _load_layer(filename: str, bypass_cache: bool = False) -> str:
    if not bypass_cache and filename in _layer_cache:
        return _layer_cache[filename]

    path = os.path.join(LAYERS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        _layer_cache[filename] = content
        return content
    except FileNotFoundError:
        logger.warning("Prompt layer not found: %s", filename)
        return ""
    except OSError as e:
        logger.error("Error loading prompt layer %s: %s", filename, e)
        return ""


def _substitute_vars(content: str, context_vars: Dict[str, str]) -> str:
    """Replace {VAR_NAME} placeholders. Leaves unmatched placeholders intact."""
    for key, val in context_vars.items():
        content = content.replace(f"{{{key}}}", val)
    return content


def build_system_prompt(
    include_layers: Optional[List[str]] = None,
    exclude_layers: Optional[List[str]] = None,
    context_vars: Optional[Dict[str, str]] = None,
    extra_context: Optional[str] = None,
    bypass_cache: bool = False,
) -> str:
    """
    Assemble the system prompt from ordered layers.

    Args:
        include_layers:  Override the default layer list.
        exclude_layers:  Skip specific layers by filename.
        context_vars:    Dict of {PLACEHOLDER: value} substitutions in layer content.
        extra_context:   Additional runtime context appended after all layers.
        bypass_cache:    Force reload from disk (useful after prompt edits).

    Returns:
        Fully assembled system prompt string with version header.
    """
    layers = list(include_layers or LAYER_ORDER)
    if exclude_layers:
        layers = [l for l in layers if l not in exclude_layers]

    parts: List[str] = [f"<!-- SSHAgent System Prompt v{PROMPT_VERSION} -->"]

    for layer in layers:
        content = _load_layer(layer, bypass_cache=bypass_cache)
        if not content:
            continue
        if context_vars:
            content = _substitute_vars(content, context_vars)
        parts.append(content)

    if extra_context:
        parts.append(extra_context)

    return "\n\n---\n\n".join(parts)


def invalidate_cache() -> None:
    """Clear the layer cache so next build_system_prompt reloads from disk."""
    _layer_cache.clear()


def get_prompt_metadata() -> Dict:
    return {
        "version": PROMPT_VERSION,
        "layers": LAYER_ORDER,
        "layers_dir": LAYERS_DIR,
        "cached_layers": list(_layer_cache.keys()),
    }

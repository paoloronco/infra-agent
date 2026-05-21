"""
Single source of truth for all LLM model/provider definitions.

All other modules import from here — never duplicate these lists.
"""
from typing import Dict, List, Optional

# ── Model catalogue ───────────────────────────────────────────────────────────

AVAILABLE_MODELS: List[Dict] = [
    # Groq
    {"id": "llama-3.3-70b-versatile",                         "name": "Llama 3.3 70B",           "provider": "groq"},
    {"id": "openai/gpt-oss-120b",                             "name": "GPT-OSS 120B",            "provider": "groq"},
    {"id": "openai/gpt-oss-20b",                              "name": "GPT-OSS 20B",             "provider": "groq"},
    {"id": "qwen/qwen3-32b",                                  "name": "Qwen 3 32B",              "provider": "groq"},
    {"id": "meta-llama/llama-4-scout-17b-16e-instruct",       "name": "Llama 4 Scout",           "provider": "groq"},
    {"id": "meta-llama/llama-4-maverick-17b-128e-instruct",   "name": "Llama 4 Maverick",        "provider": "groq"},
    {"id": "llama-3.1-8b-instant",                             "name": "Llama 3.1 8B",            "provider": "groq"},
    {"id": "gemma2-9b-it",                                     "name": "Gemma 2 9B",              "provider": "groq"},
    # OpenAI
    {"id": "gpt-5.5",                                    "name": "GPT-5.5",                 "provider": "openai"},
    {"id": "gpt-5.4",                                    "name": "GPT-5.4",                 "provider": "openai"},
    {"id": "gpt-5.4-mini",                               "name": "GPT-5.4 Mini",            "provider": "openai"},
    {"id": "gpt-5.4-nano",                               "name": "GPT-5.4 Nano",            "provider": "openai"},
    {"id": "gpt-5.2",                                    "name": "GPT-5.2",                 "provider": "openai"},
    {"id": "gpt-5.1",                                    "name": "GPT-5.1",                 "provider": "openai"},
    {"id": "gpt-5.1-chat-latest",                        "name": "GPT-5.1 Chat",            "provider": "openai"},
    {"id": "gpt-5",                                      "name": "GPT-5",                   "provider": "openai"},
    {"id": "gpt-5-mini",                                 "name": "GPT-5 Mini",              "provider": "openai"},
    {"id": "gpt-5-nano",                                 "name": "GPT-5 Nano",              "provider": "openai"},
    {"id": "gpt-4.1",                                    "name": "GPT-4.1",                 "provider": "openai"},
    {"id": "gpt-4.1-mini",                               "name": "GPT-4.1 Mini",            "provider": "openai"},
    {"id": "gpt-4.1-nano",                               "name": "GPT-4.1 Nano",            "provider": "openai"},
    {"id": "gpt-4o",                                     "name": "GPT-4o",                  "provider": "openai"},
    {"id": "gpt-4o-mini",                                "name": "GPT-4o Mini",             "provider": "openai"},
    {"id": "o3",                                         "name": "o3",                      "provider": "openai"},
    {"id": "o4-mini",                                    "name": "o4-mini",                 "provider": "openai"},
    # Anthropic
    {"id": "claude-opus-4-7",                            "name": "Claude Opus 4.7",         "provider": "anthropic"},
    {"id": "claude-sonnet-4-6",                          "name": "Claude Sonnet 4.6",       "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001",                  "name": "Claude Haiku 4.5",        "provider": "anthropic"},
    {"id": "claude-3-5-sonnet-20241022",                 "name": "Claude 3.5 Sonnet",       "provider": "anthropic"},
    {"id": "claude-3-5-haiku-20241022",                  "name": "Claude 3.5 Haiku",        "provider": "anthropic"},
    # Gemini
    {"id": "gemini-2.5-pro",                             "name": "Gemini 2.5 Pro",          "provider": "gemini"},
    {"id": "gemini-2.5-flash",                           "name": "Gemini 2.5 Flash",        "provider": "gemini"},
    {"id": "gemini-2.0-flash",                           "name": "Gemini 2.0 Flash",        "provider": "gemini"},
    {"id": "gemini-1.5-pro",                             "name": "Gemini 1.5 Pro",          "provider": "gemini"},
    {"id": "gemini-1.5-flash",                           "name": "Gemini 1.5 Flash",        "provider": "gemini"},
    # DeepSeek
    {"id": "deepseek-chat",                              "name": "DeepSeek V3",             "provider": "deepseek"},
    {"id": "deepseek-reasoner",                          "name": "DeepSeek R1",             "provider": "deepseek"},
    # Mistral AI
    {"id": "mistral-large-latest",                       "name": "Mistral Large",           "provider": "mistral_ai"},
    {"id": "mistral-small-latest",                       "name": "Mistral Small",           "provider": "mistral_ai"},
    {"id": "codestral-latest",                           "name": "Codestral",               "provider": "mistral_ai"},
    # xAI
    {"id": "grok-3",                                     "name": "Grok 3",                  "provider": "xai"},
    {"id": "grok-3-fast",                                "name": "Grok 3 Fast",             "provider": "xai"},
    {"id": "grok-2-vision-1212",                         "name": "Grok 2 Vision",           "provider": "xai"},
    # Perplexity
    {"id": "sonar",                                      "name": "Sonar",                   "provider": "perplexity"},
    {"id": "sonar-pro",                                  "name": "Sonar Pro",               "provider": "perplexity"},
    {"id": "sonar-reasoning",                            "name": "Sonar Reasoning",         "provider": "perplexity"},
    # NVIDIA
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1",     "name": "Nemotron 49B",            "provider": "nvidia"},
    {"id": "meta/llama-3.3-70b-instruct",                "name": "Llama 3.3 70B (NVIDIA)",  "provider": "nvidia"},
    # OpenRouter
    {"id": "google/gemini-2.5-pro-preview-05-06",        "name": "Gemini 2.5 Pro",          "provider": "openrouter"},
    {"id": "openai/gpt-4.1",                             "name": "GPT-4.1",                 "provider": "openrouter"},
    {"id": "anthropic/claude-opus-4-5",                  "name": "Claude Opus 4",           "provider": "openrouter"},
    {"id": "meta-llama/llama-3.3-70b-instruct:free",     "name": "Llama 3.3 70B (free)",    "provider": "openrouter"},
    {"id": "deepseek/deepseek-r1:free",                  "name": "DeepSeek R1 (free)",      "provider": "openrouter"},
    # Z.AI / Zhipu
    {"id": "glm-4-plus",                                 "name": "GLM-4 Plus",              "provider": "zhipu"},
    {"id": "glm-4v-plus",                                "name": "GLM-4V Plus",             "provider": "zhipu"},
    {"id": "glm-4-flash",                                "name": "GLM-4 Flash",             "provider": "zhipu"},
    # Hugging Face
    {"id": "meta-llama/Llama-3.3-70B-Instruct",          "name": "Llama 3.3 70B",           "provider": "huggingface"},
    {"id": "Qwen/Qwen2.5-72B-Instruct",                  "name": "Qwen 2.5 72B",            "provider": "huggingface"},
    {"id": "mistralai/Mixtral-8x7B-Instruct-v0.1",       "name": "Mixtral 8x7B",            "provider": "huggingface"},
    # Ollama (local)
    {"id": "llama3.2",                                   "name": "Llama 3.2",               "provider": "ollama"},
    {"id": "llama3.1",                                   "name": "Llama 3.1",               "provider": "ollama"},
    {"id": "qwen2.5",                                    "name": "Qwen 2.5",                "provider": "ollama"},
    {"id": "qwen2.5-coder",                              "name": "Qwen 2.5 Coder",          "provider": "ollama"},
    {"id": "mistral",                                    "name": "Mistral",                 "provider": "ollama"},
    {"id": "codellama",                                  "name": "CodeLlama",               "provider": "ollama"},
    {"id": "phi3",                                       "name": "Phi-3",                   "provider": "ollama"},
    {"id": "phi4",                                       "name": "Phi-4",                   "provider": "ollama"},
    {"id": "gemma2",                                     "name": "Gemma 2",                 "provider": "ollama"},
    {"id": "deepseek-coder",                             "name": "DeepSeek Coder",          "provider": "ollama"},
    {"id": "deepseek-r1",                                "name": "DeepSeek R1",             "provider": "ollama"},
]

# ── Derived lookups (computed once at import time) ────────────────────────────

GROQ_MODEL_ALIASES: Dict[str, str] = {
    # Older UI entries missed Groq's required meta-llama namespace.
    "llama-4-scout-17b-16e-instruct": "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-4-maverick-17b-128e-instruct": "meta-llama/llama-4-maverick-17b-128e-instruct",
}


def canonical_model_id(model_id: str) -> str:
    """Return the provider model ID accepted by the upstream API."""
    return GROQ_MODEL_ALIASES.get(model_id, model_id)


MODEL_PROVIDER_MAP: Dict[str, str] = {m["id"]: m["provider"] for m in AVAILABLE_MODELS}
MODEL_PROVIDER_MAP.update({legacy_id: "groq" for legacy_id in GROQ_MODEL_ALIASES})

MODEL_IDS = {m["id"] for m in AVAILABLE_MODELS}


def get_provider(model_id: str) -> str:
    return MODEL_PROVIDER_MAP.get(canonical_model_id(model_id), "groq")


# ── Provider metadata (for the Models config page) ───────────────────────────

PROVIDERS: Dict[str, Dict] = {
    "groq": {
        "name": "Groq",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "groq"],
        "docs_url": "https://console.groq.com",
    },
    "openai": {
        "name": "OpenAI",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "openai"],
        "docs_url": "https://platform.openai.com",
    },
    "anthropic": {
        "name": "Anthropic",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "anthropic"],
        "docs_url": "https://console.anthropic.com",
    },
    "gemini": {
        "name": "Google Gemini",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "gemini"],
        "docs_url": "https://aistudio.google.com",
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "deepseek"],
        "docs_url": "https://platform.deepseek.com",
    },
    "mistral_ai": {
        "name": "Mistral AI",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "mistral_ai"],
        "docs_url": "https://console.mistral.ai",
    },
    "xai": {
        "name": "xAI (Grok)",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "xai"],
        "docs_url": "https://console.x.ai",
    },
    "perplexity": {
        "name": "Perplexity",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "perplexity"],
        "docs_url": "https://www.perplexity.ai/settings/api",
    },
    "nvidia": {
        "name": "NVIDIA",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "nvidia"],
        "docs_url": "https://build.nvidia.com",
    },
    "openrouter": {
        "name": "OpenRouter",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "openrouter"],
        "docs_url": "https://openrouter.ai/keys",
    },
    "zhipu": {
        "name": "Z.AI (Zhipu GLM)",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "zhipu"],
        "docs_url": "https://open.bigmodel.cn",
    },
    "huggingface": {
        "name": "Hugging Face",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "huggingface"],
        "docs_url": "https://huggingface.co/settings/tokens",
    },
    "ollama": {
        "name": "Ollama (local)",
        "models": [m["id"] for m in AVAILABLE_MODELS if m["provider"] == "ollama"],
        "docs_url": "https://ollama.com",
    },
}

# ── Cost table (USD per 1,000 tokens, approximate as of 2025-05) ─────────────
# Format: model_id → (input_cost_per_1k, output_cost_per_1k)

_COST_TABLE: Dict[str, tuple] = {
    # Groq
    "llama-3.3-70b-versatile":                  (0.00059, 0.00079),
    "meta-llama/llama-4-scout-17b-16e-instruct":            (0.00011, 0.00034),
    "meta-llama/llama-4-maverick-17b-128e-instruct":        (0.00020, 0.00060),
    "llama-3.1-8b-instant":                      (0.00005, 0.00008),
    "gemma2-9b-it":                              (0.00020, 0.00020),
    # OpenAI
    "gpt-5.5":                                   (0.00500, 0.03000),
    "gpt-5.4":                                   (0.00250, 0.01500),
    "gpt-5.4-mini":                              (0.00075, 0.00450),
    "gpt-5.4-nano":                              (0.00020, 0.00125),
    "gpt-5.2":                                   (0.00175, 0.01400),
    "gpt-5.1":                                   (0.00125, 0.01000),
    "gpt-5.1-chat-latest":                       (0.00125, 0.01000),
    "gpt-5":                                     (0.00125, 0.01000),
    "gpt-5-mini":                                (0.00025, 0.00200),
    "gpt-5-nano":                                (0.00005, 0.00040),
    "gpt-4.1":                                   (0.00200, 0.00800),
    "gpt-4.1-mini":                              (0.00040, 0.00160),
    "gpt-4.1-nano":                              (0.00010, 0.00040),
    "gpt-4o":                                    (0.00250, 0.01000),
    "gpt-4o-mini":                               (0.00015, 0.00060),
    "o3":                                        (0.01000, 0.04000),
    "o4-mini":                                   (0.00110, 0.00440),
    # Anthropic
    "claude-opus-4-7":                           (0.01500, 0.07500),
    "claude-sonnet-4-6":                         (0.00300, 0.01500),
    "claude-haiku-4-5-20251001":                 (0.00080, 0.00400),
    "claude-3-5-sonnet-20241022":                (0.00300, 0.01500),
    "claude-3-5-haiku-20241022":                 (0.00080, 0.00400),
    # Gemini
    "gemini-2.5-pro":                            (0.00125, 0.01000),
    "gemini-2.5-flash":                          (0.00015, 0.00060),
    "gemini-2.0-flash":                          (0.00010, 0.00040),
    "gemini-1.5-pro":                            (0.00125, 0.00500),
    "gemini-1.5-flash":                          (0.000075, 0.00030),
    # DeepSeek
    "deepseek-chat":                             (0.00027, 0.00110),
    "deepseek-reasoner":                         (0.00055, 0.00219),
    # Mistral
    "mistral-large-latest":                      (0.00200, 0.00600),
    "mistral-small-latest":                      (0.00010, 0.00030),
    "codestral-latest":                          (0.00100, 0.00300),
    # xAI
    "grok-3":                                    (0.00300, 0.01500),
    "grok-3-fast":                               (0.00050, 0.00250),
    # Perplexity
    "sonar":                                     (0.00100, 0.00100),
    "sonar-pro":                                 (0.00300, 0.01500),
}


def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for a model call. Returns 0.0 for unknown models."""
    costs = _COST_TABLE.get(canonical_model_id(model_id))
    if not costs:
        return 0.0
    return round(input_tokens * costs[0] / 1000 + output_tokens * costs[1] / 1000, 6)


def estimate_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per token (better than word-split)."""
    return max(1, len(text) // 4)

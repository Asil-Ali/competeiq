"""
config.py v5 — Secure Configuration
All API keys from environment variables ONLY
Supports: OpenRouter (main) + Groq (evaluator) + Supabase (memory/rate-limit)
"""

import os, re

# ── PATTERNS ──────────────────────────────────────────────────
_OR_PATTERN   = r"^sk-or-v1-[a-zA-Z0-9]{20,}$"
_ANT_PATTERN  = r"^sk-ant-[a-zA-Z0-9\-_]{20,}$"
_GROQ_PATTERN = r"^gsk_[a-zA-Z0-9]{20,}$"

DEFAULT_MAIN_MODEL     = "meta-llama/llama-3.1-8b-instruct:free"
DEFAULT_FALLBACK_MODEL = "meta-llama/llama-3.1-8b-instruct:free"
DEFAULT_EVALUATOR_MODEL = "llama-3.3-70b-versatile"   # Groq model


def get_ai_config() -> dict:
    """Main agent AI config (OpenRouter preferred, Anthropic fallback)."""
    or_key  = os.environ.get("OPENROUTER_API_KEY", "").strip()
    ant_key = os.environ.get("ANTHROPIC_API_KEY",  "").strip()
    model   = os.environ.get("AI_MODEL", "").strip()

    if or_key and re.match(_OR_PATTERN, or_key):
        return {
            "provider":        "openrouter",
            "api_key":         or_key,
            "model":           model or DEFAULT_MAIN_MODEL,
            "fallback_model":  DEFAULT_FALLBACK_MODEL,
            "valid":           True,
        }
    if ant_key and re.match(_ANT_PATTERN, ant_key):
        return {
            "provider":        "anthropic",
            "api_key":         ant_key,
            "model":           model or "claude-haiku-20240307",
            "fallback_model":  None,
            "valid":           True,
        }
    return {"valid": False, "error": "No valid API key in environment"}


def get_groq_config() -> dict:
    """Evaluator config — ALWAYS Groq (independent from main agent)."""
    key   = os.environ.get("GROQ_API_KEY", "").strip()
    model = os.environ.get("GROQ_MODEL", DEFAULT_EVALUATOR_MODEL).strip()
    if key and re.match(_GROQ_PATTERN, key):
        return {"api_key": key, "model": model, "valid": True}
    # Fallback: use OpenRouter with different model if Groq not available
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if or_key:
        return {
            "api_key":  or_key,
            "model":    "mistralai/mistral-7b-instruct:free",
            "valid":    True,
            "fallback": True,  # signal that this is not ideal
        }
    return {"valid": False}


def get_telegram_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    return token


def get_admin_ids() -> list:
    raw = os.environ.get("ADMIN_IDS", "").strip()
    if not raw:
        return []
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except Exception:
        return []


def get_brave_api_key() -> str:
    return os.environ.get("BRAVE_API_KEY", "").strip()


def validate_skill(content: str, name: str) -> dict:
    required = ["## SKILL:", "## PURPOSE", "## INSTRUCTIONS", "## OUTPUT FORMAT"]
    missing  = [s for s in required if s not in content]
    return {"valid": len(missing) == 0, "missing": missing, "skill_name": name}


def load_file(path: str) -> str:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


# Legacy helpers kept for compatibility
def get_price() -> str:
    return os.environ.get("SERVICE_PRICE", "Free").strip()

def get_spacer_remit_info() -> str:
    name   = os.environ.get("SPACER_REMIT_NAME", "").strip()
    number = os.environ.get("SPACER_REMIT_NUMBER", "").strip()
    return f"Name: {name}\nNumber: {number}" if name else ""

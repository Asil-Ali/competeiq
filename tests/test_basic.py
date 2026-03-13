"""
tests/test_basic.py — Unit Tests
Run: python -m pytest tests/ -v
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── INPUT VALIDATION ─────────────────────────────────────────

def test_sanitize_valid():
    from bot import _sanitize
    cleaned, err = _sanitize("My Business Name")
    assert err is None
    assert cleaned == "My Business Name"

def test_sanitize_too_long():
    from bot import _sanitize, MAX_FIELD_LEN
    cleaned, err = _sanitize("x" * (MAX_FIELD_LEN + 1))
    assert err is not None

def test_sanitize_bad_chars():
    from bot import _sanitize
    cleaned, err = _sanitize("<script>alert(1)</script>")
    assert err is not None

def test_sanitize_empty():
    from bot import _sanitize
    cleaned, err = _sanitize("   ")
    assert err is not None


# ── TOOLS ────────────────────────────────────────────────────

def test_web_search_returns_dict():
    from tools import web_search
    result = web_search("test query", max_results=2)
    assert isinstance(result, dict)
    assert "success" in result

def test_save_and_load_data():
    import tools
    tools.set_current_user(99999)
    tools.ensure_dirs()
    r = tools.save_data("test_unit_99", {"hello": "world"})
    assert r["success"] is True
    r2 = tools.load_data("test_unit_99")
    assert r2.get("data", {}).get("hello") == "world"

def test_filter_metadata_keeps_recent():
    from tools import _filter_by_metadata
    results = [
        {"title": "Old",  "snippet": "x", "age": "2021"},
        {"title": "New",  "snippet": "x", "age": "2024"},
        {"title": "None", "snippet": "x", "age": ""},
    ]
    filtered = _filter_by_metadata(results)
    titles   = [r["title"] for r in filtered]
    assert "New"  in titles
    assert "None" in titles   # no age = keep

def test_rerank_by_relevance():
    from tools import _rerank_results
    results = [
        {"title": "Other stuff",      "snippet": "something else"},
        {"title": "Notion pricing",   "snippet": "notion pricing plans $10"},
    ]
    ranked = _rerank_results("notion pricing", results)
    assert ranked[0]["title"] == "Notion pricing"


# ── STATE ─────────────────────────────────────────────────────

def test_state_set_get():
    import state as S
    S.set_val(11111, "x", "hello")
    assert S.get_val(11111, "x") == "hello"

def test_state_reset():
    import state as S
    S.set_val(22222, "x", "y")
    S.reset_session(22222)
    assert S.get_val(22222, "x") is None


# ── CONFIG ────────────────────────────────────────────────────

def test_config_no_key_invalid():
    import config
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY",  None)
    cfg = config.get_ai_config()
    assert cfg["valid"] is False

def test_groq_config_no_key():
    import config
    os.environ.pop("GROQ_API_KEY", None)
    cfg = config.get_groq_config()
    # Should either be invalid or fallback to OpenRouter
    assert "valid" in cfg

def test_validate_skill_ok():
    import config
    c = "## SKILL: test\n## PURPOSE\nx\n## INSTRUCTIONS\nx\n## OUTPUT FORMAT\nx"
    r = config.validate_skill(c, "test")
    assert r["valid"] is True

def test_validate_skill_missing():
    import config
    c = "## SKILL: test\n## PURPOSE\nx"
    r = config.validate_skill(c, "test")
    assert r["valid"] is False


# ── RATE LIMITER ──────────────────────────────────────────────

def test_rate_allows_new_user():
    from rate_limiter import can_analyze
    allowed, _ = can_analyze(999001)
    assert allowed is True

def test_rate_blocks_running():
    from rate_limiter import can_analyze, start_analysis, end_analysis
    uid = 999002
    start_analysis(uid)
    allowed, reason = can_analyze(uid)
    assert allowed is False
    assert "running" in reason.lower()
    end_analysis(uid)


# ── EVALUATOR ────────────────────────────────────────────────

def test_evaluator_default_pass_no_config():
    from evaluator import evaluate_analysis
    result = evaluate_analysis(
        business    = {"name": "Test", "industry": "SaaS"},
        competitors = [],
        insights    = {},
        ai_config   = {"valid": False},
        groq_config = {"valid": False},
    )
    assert result["pass"] is True

def test_reflection_prompt_content():
    from evaluator import build_reflection_prompt
    ev = {
        "overall": 5.0,
        "gaps":    ["Missing pricing data for Notion"],
        "hallucination_risks": ["Invented 10M users claim"],
        "improvement_queries": ["Notion pricing 2025"],
        "evaluator_notes": "Weak evidence",
    }
    prompt = build_reflection_prompt(ev, {"name": "MyApp", "industry": "SaaS"})
    assert "QUALITY GATE FAILED" in prompt
    assert "Missing pricing data" in prompt
    assert "MyApp" in prompt


# ── MEMORY ────────────────────────────────────────────────────

def test_memory_stats_no_supabase():
    """Memory should not crash if Supabase not configured."""
    os.environ.pop("SUPABASE_URL", None)
    os.environ.pop("SUPABASE_ANON_KEY", None)
    from memory_manager import get_stats
    stats = get_stats()
    assert "total_analyses" in stats

def test_memory_context_empty_no_supabase():
    os.environ.pop("SUPABASE_URL", None)
    os.environ.pop("SUPABASE_ANON_KEY", None)
    from memory_manager import get_context_for_agent
    ctx = get_context_for_agent("SaaS")
    assert isinstance(ctx, str)


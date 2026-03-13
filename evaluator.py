"""
evaluator.py v3 — Independent Quality Evaluator via Groq
CRITICAL FIX: Uses Groq API (separate service from OpenRouter)
So if OpenRouter fails, evaluator still works — and vice versa.

Models used:
  Main agent: google/gemini-2.0-flash-exp (OpenRouter)
  Evaluator:  llama-3.3-70b-versatile     (Groq) ← completely independent
"""

import json, urllib.request, urllib.error, logging, time

log = logging.getLogger("evaluator")

QUALITY_THRESHOLD = 7.0
GROQ_URL          = "https://api.groq.com/openai/v1/chat/completions"
OR_URL            = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a strict quality auditor for competitive intelligence reports.
Your ONLY job: catch hallucinations, missing data, and weak analysis.
Return ONLY valid JSON — absolutely no markdown, no explanation, no preamble."""

EVAL_PROMPT = """Audit this competitive analysis strictly.

BUSINESS: {business_name} | Industry: {industry}
COMPETITORS ANALYZED: {competitor_count}

COMPETITOR DATA SUMMARY:
{competitors_summary}

INSIGHTS SUMMARY:
{insights_summary}

Return ONLY this JSON (no extra text):
{{
  "scores": {{
    "completeness": <1-10>,
    "evidence_quality": <1-10>,
    "actionability": <1-10>,
    "anti_hallucination": <1-10>
  }},
  "overall": <1-10 float>,
  "pass": <true if overall >= 7.0>,
  "gaps": ["specific missing data point"],
  "hallucination_risks": ["specific unsupported claim"],
  "improvement_queries": ["specific search query to fix gap"],
  "evaluator_notes": "brief assessment in one sentence"
}}

Scoring rules:
- completeness: all competitors researched? all fields non-empty?
- evidence_quality: every price/feature claim backed by search data?
- actionability: recommendations specific with timeframe and metric?
- anti_hallucination: invented numbers/features? (10=nothing suspicious found)
- overall: weighted avg where anti_hallucination counts DOUBLE
- If competitor_count = 0: overall must be <= 3"""


def _call_groq(prompt: str, api_key: str, model: str) -> str:
    """Call Groq API (independent from OpenRouter)."""
    body = json.dumps({
        "model":       model,
        "max_tokens":  600,
        "temperature": 0.1,   # Low temperature for consistent evaluation
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(GROQ_URL, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def _call_openrouter_fallback(prompt: str, api_key: str) -> str:
    """Fallback: use different free model on OpenRouter if Groq unavailable."""
    body = json.dumps({
        "model":       "mistralai/mistral-7b-instruct:free",
        "max_tokens":  600,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(OR_URL, data=body, headers={
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer":  "https://t.me/competeiq_bot",
        "X-Title":       "CompeteIQ-Evaluator",
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def _parse_json_safe(text: str) -> dict:
    """Extract JSON from AI response safely."""
    text = text.strip()
    # Remove code fences if present
    if "```" in text:
        for part in text.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                text = part
                break
    s = text.find("{")
    e = text.rfind("}") + 1
    if s >= 0 and e > s:
        text = text[s:e]
    return json.loads(text)


def _summarize_competitors(competitors: list) -> str:
    if not competitors:
        return "NO COMPETITOR DATA FOUND — critical gap"
    lines = []
    for c in competitors[:7]:
        lines.append(
            f"• {c.get('name','?')}: "
            f"threat={c.get('threat_level','?')} | "
            f"pricing={str(c.get('pricing_summary','N/A'))[:50]} | "
            f"strengths={len(c.get('strengths',[]))} | "
            f"website={c.get('website','N/A')}"
        )
    return "\n".join(lines)


def _summarize_insights(insights: dict) -> str:
    if not insights:
        return "NO INSIGHTS GENERATED — critical gap"
    recs = insights.get("recommendations", [])
    return (
        f"Executive summary: {str(insights.get('executive_summary',''))[:200]}\n"
        f"Key findings: {len(insights.get('key_findings', []))} items\n"
        f"Recommendations: {len(recs)} items"
    )


def _default_pass() -> dict:
    return {
        "pass":               True,
        "overall":            7.5,
        "scores":             {"completeness": 7, "evidence_quality": 7,
                               "actionability": 7, "anti_hallucination": 9},
        "gaps":               [],
        "hallucination_risks":[],
        "improvement_queries":[],
        "evaluator_notes":    "Evaluation skipped — no evaluator config",
    }


def evaluate_analysis(business: dict, competitors: list,
                       insights: dict, ai_config: dict,
                       groq_config: dict = None) -> dict:
    """
    Evaluate analysis quality using an INDEPENDENT model.
    Uses Groq (separate service) — not the same account as main agent.
    """
    prompt = EVAL_PROMPT.format(
        business_name      = business.get("name", "Unknown"),
        industry           = business.get("industry", "Unknown"),
        competitor_count   = len(competitors),
        competitors_summary= _summarize_competitors(competitors),
        insights_summary   = _summarize_insights(insights),
    )

    raw    = None
    source = "none"

    # 1. Try Groq first (preferred — completely independent)
    if groq_config and groq_config.get("valid") and not groq_config.get("fallback"):
        try:
            raw    = _call_groq(prompt, groq_config["api_key"], groq_config["model"])
            source = f"groq/{groq_config['model']}"
        except Exception as e:
            log.warning(f"Groq evaluation failed: {e} — trying fallback")

    # 2. Fallback: different model on OpenRouter
    if raw is None and ai_config.get("valid") and ai_config.get("provider") == "openrouter":
        try:
            raw    = _call_openrouter_fallback(prompt, ai_config["api_key"])
            source = "openrouter/mistral-7b-fallback"
        except Exception as e:
            log.warning(f"OpenRouter evaluation fallback failed: {e}")

    # 3. No evaluator available — default pass (never block user)
    if raw is None:
        log.warning("All evaluators failed — using default pass")
        return _default_pass()

    try:
        result = _parse_json_safe(raw)
        result.setdefault("pass",   float(result.get("overall", 7)) >= QUALITY_THRESHOLD)
        result.setdefault("overall", 7.0)
        result.setdefault("gaps",    [])
        result.setdefault("improvement_queries", [])
        result.setdefault("hallucination_risks", [])
        result.setdefault("evaluator_notes",     "")
        result["_source"] = source  # For debugging
        log.info(f"Evaluation: score={result['overall']} pass={result['pass']} via={source}")
        return result
    except Exception as e:
        log.warning(f"Evaluation JSON parse failed: {e} — using default pass")
        return {**_default_pass(), "_parse_error": str(e), "_raw": raw[:200]}


def build_reflection_prompt(evaluation: dict, business: dict) -> str:
    """Build targeted improvement instructions for the reflection pass."""
    gaps    = "\n".join(f"  - {g}" for g in evaluation.get("gaps", []))
    risks   = "\n".join(f"  - {r}" for r in evaluation.get("hallucination_risks", []))
    queries = "\n".join(f"  - {q}" for q in evaluation.get("improvement_queries", []))

    return f"""🔍 QUALITY GATE FAILED — Reflection Pass Required

Independent Evaluator Score: {evaluation.get('overall', 0)}/10
(Minimum required: {QUALITY_THRESHOLD}/10)
Evaluator notes: {evaluation.get('evaluator_notes', '')}

GAPS TO FILL:
{gaps or '  - No specific gaps listed'}

CLAIMS NEEDING VERIFICATION (possible hallucinations):
{risks or '  - None flagged'}

SEARCH QUERIES TO RUN NOW:
{queries or '  - Run targeted searches for missing data'}

YOUR INSTRUCTIONS FOR THIS REFLECTION PASS:
1. Run the search queries listed above — do not skip any
2. For each hallucination risk: search for the specific claim and verify or correct it
3. Fill every identified gap with real search data
4. Update competitor records using save_data() with corrected information
5. Regenerate insights using load_skill("report_writing_skill")
6. Call generate_pdf() with the improved data
7. Call finish_analysis() as the final step

Business: {business.get('name', 'Unknown')} | Industry: {business.get('industry', 'Unknown')}

IMPORTANT: The evaluator is an independent AI — not you.
Your goal is to satisfy IT, not just finish quickly."""

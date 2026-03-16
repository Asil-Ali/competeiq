"""
agent.py v6 — Production-Grade Agentic Loop
Fixes: Groq evaluator, fallback model, Supabase memory, retry logic
"""

import json, urllib.request, urllib.error, logging, time
import state as S
from tools import TOOL_DEFINITIONS, execute_tool, set_current_user, load_data
from config import load_file, get_groq_config
from evaluator import evaluate_analysis, build_reflection_prompt
from memory_manager import get_context_for_agent, record_analysis
from logger import AnalysisLogger

log             = logging.getLogger("agent")
MAX_ITERATIONS  = 40
MAX_REFLECTIONS = 2
MAX_RETRIES     = 3
RETRY_DELAYS    = [2, 5, 12]


def build_system_prompt(industry="", competitors=None):
    parts = [
        load_file("CLAUDE.md"),
        get_context_for_agent(industry, competitors),
        "---\n## WORKFLOW SOP\n" + load_file("workflows/competitor_analysis.md"),
        "---\n## AVAILABLE SKILLS\n" + load_file("skills/SKILLS_INDEX.md"),
        """---
## ANTI-HALLUCINATION RULES (NON-NEGOTIABLE)
1. Every pricing claim MUST come from a real search — NEVER invent
2. Every feature claim MUST be verified — NEVER assume
3. Data not found → write "Not publicly available" — NEVER guess
4. Search any fact you are unsure about from 2 different angles
5. threat_level MUST have a 1-sentence evidence justification
6. avg_price = real number from search, or 0 if genuinely unknown

## QUALITY GATE
An INDEPENDENT AI (not you) will evaluate your output.
It scores on: completeness, evidence, actionability, anti-hallucination.
Minimum to pass: 7/10. Aim for 9/10. You will get a second chance if you fail."""
    ]
    return "\n\n".join(p for p in parts if p.strip())


# ── API CALLS ─────────────────────────────────────────────────

def _call_anthropic(messages, system, api_key, model):
    body = json.dumps({
        "model": model, "max_tokens": 4096,
        "system": system, "tools": TOOL_DEFINITIONS, "messages": messages,
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def _to_openai_messages(messages, system):
    """Convert Anthropic message format to OpenAI format."""
    om = [{"role": "system", "content": system}]
    for msg in messages:
        role, content = msg["role"], msg["content"]
        if isinstance(content, str):
            om.append({"role": role, "content": content})
        elif isinstance(content, list):
            texts, tcs, trs = [], [], []
            for b in content:
                bt = b.get("type")
                if bt == "text":
                    texts.append(b.get("text", ""))
                elif bt == "tool_use":
                    tcs.append({"id": b["id"], "type": "function",
                        "function": {"name": b["name"],
                                     "arguments": json.dumps(b.get("input", {}))}})
                elif bt == "tool_result":
                    trs.append({"role": "tool",
                                "tool_call_id": b["tool_use_id"],
                                "content": str(b.get("content", ""))})
            if trs:
                om.extend(trs)
            elif tcs:
                om.append({"role": "assistant",
                           "content": "\n".join(texts) or None,
                           "tool_calls": tcs})
            elif texts:
                om.append({"role": role, "content": "\n".join(texts)})
    return om


def _call_openrouter(messages, system, api_key, model):
    ot = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": t["input_schema"]}} for t in TOOL_DEFINITIONS]

    body = json.dumps({
        "model": model, "max_tokens": 4096, "tools": ot,
        "messages": _to_openai_messages(messages, system),
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}",
                 "HTTP-Referer": "https://t.me/competeiq_bot",
                 "X-Title": "CompeteIQ"})
    with urllib.request.urlopen(req, timeout=90) as r:
        resp = json.loads(r.read().decode())

    choice = resp["choices"][0]
    msg    = choice["message"]
    blocks = []
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for tc in (msg.get("tool_calls") or []):
        try:   inp = json.loads(tc["function"]["arguments"])
        except: inp = {}
        blocks.append({"type": "tool_use", "id": tc["id"],
                        "name": tc["function"]["name"], "input": inp})
    stop = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"
    return {"stop_reason": stop, "content": blocks}



def _call_groq(messages, system, api_key, model):
    """Call Groq API (OpenAI-compatible format)."""
    ot = [{"type": "function", "function": {
        "name": t["name"], "description": t["description"],
        "parameters": t["input_schema"]}} for t in TOOL_DEFINITIONS]

    body = json.dumps({
        "model": model, "max_tokens": 4096, "tools": ot,
        "tool_choice": "auto",
        "messages": _to_openai_messages(messages, system),
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=90) as r:
        resp = json.loads(r.read().decode())

    choice = resp["choices"][0]
    msg    = choice["message"]
    blocks = []
    if msg.get("content"):
        blocks.append({"type": "text", "text": msg["content"]})
    for tc in (msg.get("tool_calls") or []):
        try:   inp = json.loads(tc["function"]["arguments"])
        except: inp = {}
        blocks.append({"type": "tool_use", "id": tc["id"],
                        "name": tc["function"]["name"], "input": inp})
    stop = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"
    return {"stop_reason": stop, "content": blocks}


def _call_ai_with_retry(messages, system, ai_config, use_fallback=False):
    """Call AI with exponential backoff. Tries fallback model on repeated failure."""
    provider = ai_config["provider"]
    api_key  = ai_config["api_key"]
    model    = ai_config.get("fallback_model") if use_fallback else ai_config["model"]
    if not model:
        model = ai_config["model"]

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            if provider == "groq":
                return _call_groq(messages, system, api_key, model)
            if provider == "openrouter":
                return _call_openrouter(messages, system, api_key, model)
            return _call_anthropic(messages, system, api_key, model)
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:200]
            if e.code in (401, 403):
                raise RuntimeError(f"Auth error {e.code}: {body}") from e
            if e.code == 429:
                wait = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)-1)] * 2
                log.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                last_err = e
            elif e.code >= 500:
                wait = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)-1)]
                log.warning(f"Server error {e.code}, retry {attempt+1} in {wait}s")
                time.sleep(wait)
                last_err = e
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            wait = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)-1)]
            log.warning(f"Network error, retry {attempt+1} in {wait}s: {e}")
            time.sleep(wait)
            last_err = e

    raise last_err or RuntimeError("Max retries exceeded")


# ── AGENTIC LOOP ──────────────────────────────────────────────

def _run_loop(user_id, messages, system, ai_config,
              message_callback, tool_callback,
              alog=None, max_iter=MAX_ITERATIONS,
              use_fallback=False):
    for _ in range(max_iter):
        try:
            response = _call_ai_with_retry(messages, system, ai_config, use_fallback)
        except RuntimeError as e:
            # Try fallback model if main fails and fallback available
            if not use_fallback and ai_config.get("fallback_model"):
                log.warning(f"Main model failed, switching to fallback: {e}")
                message_callback("⚠️ Switching to backup model...")
                try:
                    response = _call_ai_with_retry(messages, system, ai_config, use_fallback=True)
                except Exception as e2:
                    message_callback(f"❌ All models failed: {str(e2)[:150]}")
                    if alog: alog.error("All models failed", e2)
                    break
            else:
                message_callback(f"❌ API error: {str(e)[:150]}")
                if alog: alog.error(str(e))
                break
        except Exception as e:
            message_callback(f"❌ Unexpected error: {str(e)[:150]}")
            if alog: alog.error(str(e), e)
            break

        stop    = response.get("stop_reason", "end_turn")
        content = response.get("content", [])
        messages.append({"role": "assistant", "content": content})

        tool_calls = []
        for block in content:
            if block.get("type") == "text":
                t = block.get("text", "").strip()
                if t: message_callback(t)
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        if stop == "end_turn" and not tool_calls:
            break

        if tool_calls:
            results = []
            for tc in tool_calls:
                name, inp, tid = tc["name"], tc.get("input", {}), tc["id"]
                tool_callback(name, inp)
                if alog: alog.tool_called(name, inp.get("query", ""))
                r_str = execute_tool(name, inp)
                # Add error hint for agent to recover
                try:
                    r_obj = json.loads(r_str)
                    if not r_obj.get("success", True) and "error" in r_obj:
                        r_str = json.dumps({
                            **r_obj,
                            "agent_note": f"Tool failed: {r_obj['error']}. Adjust your approach."
                        })
                except Exception:
                    pass
                results.append({"type": "tool_result", "tool_use_id": tid, "content": r_str})
            messages.append({"role": "user", "content": results})

        if S.get_val(user_id, "analysis_complete"):
            break
    return messages


def _extract_queries(messages):
    queries = []
    for msg in messages:
        content = msg.get("content", [])
        if not isinstance(content, list): continue
        for b in content:
            if b.get("type") == "tool_use" and b.get("name") in ("brave_search", "web_search"):
                q = b.get("input", {}).get("query", "")
                if q and q not in queries: queries.append(q)
    return queries[:15]


# ── MAIN ENTRY ────────────────────────────────────────────────

def run_agent(user_id, user_message, ai_config, message_callback,
              tool_callback, business=None, competitors_list=None):
    """
    Full production agent:
    WAT loop → Groq quality gate → Reflection → Supabase memory
    """
    set_current_user(user_id)
    industry    = (business or {}).get("industry", "")
    groq_config = get_groq_config()
    system      = build_system_prompt(industry, competitors_list)
    alog        = AnalysisLogger(user_id, (business or {}).get("name", "unknown"))
    alog.event("start", industry=industry, competitors=competitors_list or [])

    # ── Pass 1: Initial Analysis ──
    S.set_val(user_id, "analysis_complete", False)
    messages = [{"role": "user", "content": user_message}]
    message_callback("🧠 Starting analysis...")
    messages = _run_loop(user_id, messages, system, ai_config,
                          message_callback, tool_callback, alog)
    S.set_val(user_id, "agent_messages", messages)

    # ── Quality Gate (independent Groq evaluator) ──
    set_current_user(user_id)
    competitors = load_data("all_competitors").get("data") or []
    insights    = load_data("insights").get("data") or {}

    message_callback("🔍 Running independent quality check...")
    evaluation = evaluate_analysis(
        business or {}, competitors, insights,
        ai_config, groq_config
    )
    score  = evaluation.get("overall", 0)
    passed = evaluation.get("pass", True)
    src    = evaluation.get("_source", "unknown")

    if passed:
        message_callback(f"✅ Quality passed — {score}/10 (via {src})")
    else:
        message_callback(f"⚠️ Score {score}/10 — improving...")

    # ── Reflection Passes ──
    reflection_count = 0
    while not passed and reflection_count < MAX_REFLECTIONS:
        reflection_count += 1
        message_callback(f"🔁 Reflection {reflection_count}/{MAX_REFLECTIONS}...")
        S.set_val(user_id, "analysis_complete", False)

        messages = S.get_val(user_id, "agent_messages", [])
        messages.append({"role": "user",
                         "content": build_reflection_prompt(evaluation, business or {})})
        messages = _run_loop(user_id, messages, system, ai_config,
                              message_callback, tool_callback, alog, max_iter=20)
        S.set_val(user_id, "agent_messages", messages)

        set_current_user(user_id)
        competitors = load_data("all_competitors").get("data") or []
        insights    = load_data("insights").get("data") or {}
        evaluation  = evaluate_analysis(
            business or {}, competitors, insights, ai_config, groq_config
        )
        score  = evaluation.get("overall", 0)
        passed = evaluation.get("pass", True)

        if passed:
            message_callback(f"✅ Improved: {score}/10")
        elif reflection_count >= MAX_REFLECTIONS:
            message_callback(f"⚠️ Best output — {score}/10")

    alog.quality_result(score, passed, reflection_count)

    # ── Record to Supabase Memory ──
    try:
        record_analysis(
            industry           = industry,
            business_name      = (business or {}).get("name", ""),
            competitors        = competitors,
            quality_score      = score,
            successful_queries = _extract_queries(messages),
            reflection_count   = reflection_count,
            learnings          = ([evaluation["evaluator_notes"]]
                                  if evaluation.get("evaluator_notes") else []),
        )
    except Exception as e:
        log.warning(f"Memory save failed (non-fatal): {e}")

    alog.done(score)
    S.set_val(user_id, "quality_score", score)
    S.set_val(user_id, "reflection_count", reflection_count)

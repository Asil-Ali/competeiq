"""
bot.py v5 — CompeteIQ Telegram Bot
Fixes: input validation, PDF timeout, delivery retry, broken cmd_users
"""

import logging, threading, io, re
from telegram import Update
from telegram.ext import (Application, CommandHandler, MessageHandler,
                            ContextTypes, filters)
from telegram.constants import ParseMode

import state as S
from config import get_ai_config, get_telegram_token, get_admin_ids
from agent import run_agent
from tools import load_data, set_current_user
from rate_limiter import can_analyze, start_analysis, end_analysis
from logger import setup_logging, get_logger

setup_logging()
log = get_logger("bot")

AI_CONFIG = get_ai_config()
ADMIN_IDS = get_admin_ids()

# ── INPUT VALIDATION ──────────────────────────────────────────
MAX_FIELD_LEN     = 100   # max chars per business field
MAX_COMP_NAME_LEN = 60    # max chars per competitor name
MIN_COMPETITORS   = 2
MAX_COMPETITORS   = 7
# Characters not allowed in inputs (prevent injection / weird behaviour)
_BAD_CHARS = re.compile(r"[<>{}\[\]|\\^`~]")


def _sanitize(text: str, max_len: int = MAX_FIELD_LEN) -> tuple:
    """
    Sanitize user input.
    Returns (cleaned: str, error: str|None)
    """
    text = text.strip()
    if not text:
        return "", "Input cannot be empty."
    if len(text) > max_len:
        return "", f"Too long (max {max_len} characters)."
    if _BAD_CHARS.search(text):
        return "", "Input contains invalid characters."
    # Collapse multiple spaces/newlines
    text = re.sub(r"\s+", " ", text)
    return text, None


STEPS = [
    ("name",           "🏢 *Business Name*\nWhat's your business called?"),
    ("industry",       "🏭 *Industry / Niche*\nExamples: SaaS, E-commerce, AI Automation"),
    ("target_market",  "🎯 *Target Market*\nWho do you sell to? Examples: Freelancers, SMBs"),
    ("pricing_model",  "💳 *Pricing Model*\nExamples: Subscription, One-time, Freemium"),
    ("price_range",    "💰 *Your Price Range*\nExamples: $99-299/month, Free"),
    ("differentiator", "⭐ *Key Differentiator*\nWhat makes you different from competitors?"),
]

COMPETITOR_PROMPT = """✅ *Business info saved!*

Now send your *competitor names* — one per line.
Send between 2 and 7 competitors.

Example:
```
Notion
Trello
Asana
Monday
```"""


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _build_start_msg() -> str:
    if not AI_CONFIG.get("valid"):
        return "⚠️ Bot not configured yet. Contact admin."
    return (
        "⚔️ *Welcome to CompeteIQ*\n\n"
        "AI-powered competitor intelligence — professional PDF reports in minutes.\n\n"
        f"*Model:* `{AI_CONFIG.get('model','?')}`\n"
        "*Framework:* WAT + Reflexion + Memory\n"
        "*Search:* Brave Search API\n\n"
        "✅ *Free to use — type /analyze to start!*"
    )


def _tool_emoji(name: str) -> str:
    return {
        "brave_search":    "🔵",
        "web_search":      "🔍",
        "load_skill":      "📚",
        "save_data":       "💾",
        "load_data":       "📂",
        "generate_pdf":    "📄",
        "finish_analysis": "✅",
    }.get(name, "🔧")


# ── SAFE SEND HELPERS ─────────────────────────────────────────

async def _send_safe(bot, chat_id: int, text: str,
                      parse_mode=ParseMode.MARKDOWN) -> bool:
    """Send message safely — try markdown then plain text."""
    if len(text) > 4000:
        text = text[:3997] + "..."
    for pm in [parse_mode, None]:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=pm)
            return True
        except Exception as e:
            if pm is None:
                log.error(f"Send failed for {chat_id}: {e}")
                return False
    return False


def _send_sync(bot, chat_id: int, text: str,
                parse_mode=ParseMode.MARKDOWN) -> bool:
    """Synchronous wrapper for sending from threads."""
    import asyncio
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            _send_safe(bot, chat_id, text, parse_mode)
        )
        loop.close()
        return result
    except Exception as e:
        log.error(f"_send_sync error: {e}")
        return False


def _send_doc_sync(bot, chat_id: int, data: bytes,
                    filename: str, caption: str) -> bool:
    """Send document from thread with retry."""
    import asyncio
    for attempt in range(3):
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(bot.send_document(
                chat_id   = chat_id,
                document  = io.BytesIO(data),
                filename  = filename,
                caption   = caption,
                parse_mode= ParseMode.MARKDOWN,
            ))
            loop.close()
            return True
        except Exception as e:
            log.warning(f"Doc send attempt {attempt+1} failed: {e}")
            if attempt < 2:
                import time; time.sleep(3)
    return False


# ── COMMANDS ─────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    S.reset_session(update.effective_user.id)
    await update.message.reply_text(_build_start_msg(), parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *CompeteIQ Help*\n\n"
        "*Commands:*\n"
        "/start — Welcome\n"
        "/analyze — Start new analysis\n"
        "/status — Check session status\n"
        "/cancel — Cancel analysis\n\n"
        "*How it works:*\n"
        "1️⃣ /analyze\n"
        "2️⃣ Answer 6 questions\n"
        "3️⃣ Send competitor names\n"
        "4️⃣ Wait 2-4 minutes\n"
        "5️⃣ Receive PDF report",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not AI_CONFIG.get("valid"):
        await update.message.reply_text("⚠️ Service not configured. Contact admin.")
        return

    # Rate limiting (admins bypass)
    if not is_admin(uid):
        allowed, reason = can_analyze(uid)
        if not allowed:
            await update.message.reply_text(reason)
            return

    S.set_val(uid, "screen",       "collecting")
    S.set_val(uid, "collect_step", 0)
    S.set_val(uid, "business",     {})

    await update.message.reply_text(
        f"🚀 *Let's start your analysis!*\n\n{STEPS[0][1]}",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    sess = S.get_session(uid)
    screen = sess.get("screen", "setup")
    status_map = {
        "setup":               "⏳ Not started — use /analyze",
        "collecting":          f"📝 Collecting info — step {sess.get('collect_step',0)+1}/{len(STEPS)}",
        "waiting_competitors": "📝 Waiting for competitor names",
        "running":             "🤖 Analysis running...",
        "done":                "✅ Analysis complete",
    }
    await update.message.reply_text(
        f"📊 *Status*\n"
        f"State: {status_map.get(screen, screen)}\n"
        f"Business: {sess.get('business',{}).get('name','—')}\n"
        f"Competitors: {len(sess.get('competitors',[]))}",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    end_analysis(uid)  # release rate limiter
    S.reset_session(uid)
    await update.message.reply_text(
        "❌ *Cancelled.* Use /analyze to start fresh.",
        parse_mode=ParseMode.MARKDOWN)


# ── ADMIN COMMANDS ────────────────────────────────────────────

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    from memory_manager import get_stats
    s = get_stats()
    await update.message.reply_text(
        f"🧠 *Agent Memory Stats*\n\n"
        f"📊 Analyses: *{s['total_analyses']}*\n"
        f"⭐ Avg score: *{s['avg_quality_score']}/10*\n"
        f"🏭 Industries: *{s['industries_known']}*\n"
        f"🔍 Queries: *{s['queries_stored']}*\n"
        f"💡 Learnings: *{s['learnings_stored']}*\n"
        f"🤝 Competitors known: *{s['competitors_known']}*\n"
        f"🕐 Last updated: {s['last_updated']}",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    sessions = S.get_all_sessions()
    if not sessions:
        await update.message.reply_text("No active users.")
        return
    lines = ["👥 *Active Users:*\n"]
    for uid, sess in list(sessions.items())[:20]:
        biz    = sess.get("business", {}).get("name", "—")
        screen = sess.get("screen", "?")
        lines.append(f"• `{uid}` — {biz} — {screen}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── MESSAGE HANDLER ───────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid    = update.effective_user.id
    text   = (update.message.text or "").strip()
    sess   = S.get_session(uid)
    screen = sess.get("screen", "setup")

    # Collecting business info
    if screen == "collecting":
        step = sess.get("collect_step", 0)
        biz  = sess.get("business", {})

        if step < len(STEPS):
            field_key, _ = STEPS[step]
            cleaned, err = _sanitize(text, MAX_FIELD_LEN)
            if err:
                await update.message.reply_text(f"❌ {err} Please try again.")
                return

            biz[field_key] = cleaned
            S.set_val(uid, "business", biz)
            S.set_val(uid, "collect_step", step + 1)
            next_step = step + 1

            if next_step < len(STEPS):
                _, question = STEPS[next_step]
                await update.message.reply_text(
                    f"_{next_step}/{len(STEPS)}_\n\n{question}",
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    COMPETITOR_PROMPT, parse_mode=ParseMode.MARKDOWN)
                S.set_val(uid, "screen", "waiting_competitors")
        return

    # Waiting for competitor names
    if screen == "waiting_competitors":
        raw_names = [n.strip() for n in text.split("\n") if n.strip()]

        # Validate count
        if len(raw_names) < MIN_COMPETITORS:
            await update.message.reply_text(
                f"❌ Please enter at least {MIN_COMPETITORS} competitors, one per line.")
            return
        if len(raw_names) > MAX_COMPETITORS:
            await update.message.reply_text(
                f"❌ Maximum {MAX_COMPETITORS} competitors. Please remove some.")
            return

        # Validate each name
        clean_names = []
        for raw in raw_names:
            cleaned, err = _sanitize(raw, MAX_COMP_NAME_LEN)
            if err:
                await update.message.reply_text(
                    f"❌ Competitor name issue: '{raw[:30]}' — {err}")
                return
            clean_names.append(cleaned)

        S.set_val(uid, "competitors", clean_names)
        S.set_val(uid, "screen",      "running")
        S.set_val(uid, "analysis_complete", False)

        biz       = sess.get("business", {})
        comp_list = "\n".join(f"  • {n}" for n in clean_names)

        await update.message.reply_text(
            f"🤖 *Starting Analysis...*\n\n"
            f"Business: *{biz.get('name','')}*\n"
            f"Competitors:\n{comp_list}\n\n"
            f"⏳ This takes 2-4 minutes. I'll update you as I work...",
            parse_mode=ParseMode.MARKDOWN)

        threading.Thread(
            target  = _run_agent_thread,
            args    = (uid, context, biz, clean_names),
            daemon  = True,
        ).start()
        return

    # Other states
    if screen == "running":
        await update.message.reply_text("⏳ Analysis is running... please wait.")
    elif screen == "done":
        await update.message.reply_text("✅ Done! Use /analyze to start a new one.")
    else:
        await update.message.reply_text("👋 Use /analyze to start, or /help for info.")


# ── AGENT THREAD ──────────────────────────────────────────────

def _run_agent_thread(user_id: int, context, biz: dict, competitors: list):
    """Run agent in background thread — handles PDF timeout + delivery retry."""

    bot        = context.bot
    tool_count = [0]

    user_msg = (
        "Run the full competitor analysis workflow.\n\n"
        f"MY BUSINESS:\n"
        f"- Name: {biz.get('name','')}\n"
        f"- Industry: {biz.get('industry','')}\n"
        f"- Target Market: {biz.get('target_market','N/A')}\n"
        f"- Pricing Model: {biz.get('pricing_model','N/A')}\n"
        f"- Price Range: {biz.get('price_range','N/A')}\n"
        f"- Key Differentiator: {biz.get('differentiator','N/A')}\n\n"
        "COMPETITORS TO ANALYZE:\n"
        + "\n".join(f"- {c}" for c in competitors)
        + "\n\nStart now. Follow the 6-phase SOP."
    )

    def on_message(text: str):
        keywords = ["error","failed","complete","✅","❌","pdf",
                    "quality","reflection","improved","warning"]
        if any(kw in text.lower() for kw in keywords):
            _send_sync(bot, user_id, f"🤖 {text[:400]}")

    def on_tool(name: str, inp: dict):
        tool_count[0] += 1
        if name == "load_skill":
            skill = inp.get("skill_name","").replace("_skill","").replace("_"," ").title()
            msg   = f"📚 Loading skill: *{skill}*"
        elif name in ("brave_search", "web_search"):
            icon  = "🔵 Brave" if name == "brave_search" else "🔍"
            msg   = f"{icon} Searching: _{inp.get('query','')[:60]}_"
        elif name == "save_data":
            msg   = f"💾 Saved: `{inp.get('key','')}`"
        elif name == "generate_pdf":
            # Send BEFORE calling — fixes Telegram timeout issue
            _send_sync(bot, user_id,
                "📄 *Generating PDF report...*\n⏳ This may take 30-60 seconds...")
            return
        elif name == "finish_analysis":
            msg   = "✅ *Analysis complete!*"
        else:
            msg   = f"{_tool_emoji(name)} `{name}`"

        # Only send every 3rd tool call to avoid spam (except key milestones)
        if name in ("load_skill", "finish_analysis") or tool_count[0] % 3 == 0:
            _send_sync(bot, user_id, msg)

    # ── Run agent ──
    start_analysis(user_id)
    error_occurred = False
    try:
        run_agent(
            user_id, user_msg, AI_CONFIG, on_message, on_tool,
            business=biz, competitors_list=competitors
        )
    except Exception as e:
        log.error(f"Agent error for {user_id}: {e}", exc_info=True)
        _send_sync(bot, user_id, f"❌ Agent error: {str(e)[:200]}")
        S.set_val(user_id, "screen", "setup")
        error_occurred = True
    finally:
        end_analysis(user_id)

    if error_occurred:
        return

    # ── Deliver results ──
    set_current_user(user_id)
    summary    = S.get_val(user_id, "analysis_summary", {})
    pdf_bytes  = S.get_val(user_id, "pdf_bytes")
    comps_data = load_data("all_competitors").get("data", [])
    high_count = sum(1 for c in comps_data
                     if str(c.get("threat_level","")).lower() == "high")
    score      = S.get_val(user_id, "quality_score", 0)

    # Summary message
    _send_sync(
        bot, user_id,
        f"✅ *Analysis Complete!*\n\n"
        f"📊 Competitors analyzed: *{len(comps_data)}*\n"
        f"⚠️ High threat: *{high_count}*\n"
        f"⭐ Quality score: *{score}/10*\n\n"
        f"🎯 *Top Recommendation:*\n"
        f"{summary.get('recommended_first_action','See PDF report')}\n\n"
        f"🏆 *Biggest Opportunity:*\n"
        f"{summary.get('biggest_opportunity','See PDF report')}"
    )

    # PDF delivery with retry
    if pdf_bytes:
        biz_name = re.sub(r"[^\w]", "_", biz.get("name","Report"))[:30]
        filename = f"CompeteIQ_{biz_name}.pdf"
        delivered = _send_doc_sync(
            bot, user_id, pdf_bytes, filename,
            "📄 *Your Competitive Intelligence Report*\nGenerated by CompeteIQ · WAT Framework"
        )
        if not delivered:
            _send_sync(bot, user_id,
                "⚠️ PDF delivery failed after 3 attempts. Contact admin.")
            log.error(f"PDF delivery failed for user {user_id}")
        else:
            log.info(f"PDF delivered to user {user_id} — score={score}")
    else:
        _send_sync(bot, user_id,
            "⚠️ PDF generation failed. Please try /analyze again.")

    S.set_val(user_id, "screen", "done")
    _send_sync(bot, user_id,
        "🔄 Use /analyze anytime to run another analysis.")


# ── MAIN ─────────────────────────────────────────────────────

def main():
    if not AI_CONFIG.get("valid"):
        log.error(f"AI config invalid: {AI_CONFIG.get('error')}")
        return

    token = get_telegram_token()
    log.info(f"Starting CompeteIQ — {AI_CONFIG['provider']} — {AI_CONFIG['model']}")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(CommandHandler("memory",  cmd_memory))
    app.add_handler(CommandHandler("users",   cmd_users))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import threading, http.server
    def health():
        server = http.server.HTTPServer(("0.0.0.0", 10000), http.server.BaseHTTPRequestHandler)
        server.serve_forever()
    threading.Thread(target=health, daemon=True).start()
    main()

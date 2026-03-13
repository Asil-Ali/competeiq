"""
rate_limiter.py v2 — Supabase-Backed Rate Limiter
CRITICAL FIX: No longer uses RAM dict — persists across Koyeb restarts
Falls back to RAM if Supabase not configured (safe degradation)
"""

import threading, time, logging
from collections import defaultdict

log   = logging.getLogger("rate_limiter")
_lock = threading.Lock()
_ram  = defaultdict(list)   # fallback if Supabase not set
_running = {}               # always in RAM (per-process, intentional)

MAX_PER_HOUR  = 3
MAX_PER_DAY   = 10
COOLDOWN_SECS = 60


def _use_supabase() -> bool:
    try:
        from db import DB
        return DB.is_configured()
    except Exception:
        return False


def _get_timestamps_supabase(user_id: int) -> list:
    """Get request timestamps from Supabase."""
    from db import DB
    now_ts = int(time.time())
    cutoff = now_ts - 86400  # last 24h

    # Supabase stores timestamps as ISO strings — we use bigint created_at
    rows = DB.select(
        "rate_limits",
        {"user_id": f"eq.{user_id}"},
        order="created_at.desc",
        limit=MAX_PER_DAY + 5,
    )
    timestamps = []
    for r in rows:
        # Parse ISO timestamp to unix
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            ts = dt.timestamp()
            if ts > cutoff:
                timestamps.append(ts)
        except Exception:
            pass
    return timestamps


def _record_supabase(user_id: int):
    """Record a new analysis request in Supabase."""
    from db import DB
    DB.insert("rate_limits", {"user_id": user_id})
    # Cleanup old records (best effort)
    try:
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        DB.delete("rate_limits", {
            "user_id":    f"eq.{user_id}",
            "created_at": f"lt.{cutoff}",
        })
    except Exception:
        pass


def can_analyze(user_id: int) -> tuple:
    """
    Returns (allowed: bool, reason: str).
    Checks Supabase if configured, falls back to RAM.
    """
    now = time.time()

    with _lock:
        # Always check in-process running flag first
        if _running.get(user_id):
            return False, "⏳ Analysis already running — please wait."

        if _use_supabase():
            try:
                timestamps = _get_timestamps_supabase(user_id)
            except Exception as e:
                log.warning(f"Supabase rate check failed, falling back to RAM: {e}")
                timestamps = [t for t in _ram[user_id] if now - t < 86400]
        else:
            timestamps = [t for t in _ram[user_id] if now - t < 86400]

        # Daily limit
        if len(timestamps) >= MAX_PER_DAY:
            return False, (
                f"⚠️ Daily limit reached ({MAX_PER_DAY} analyses/day). "
                "Try again tomorrow."
            )

        # Hourly limit
        hour_ts = [t for t in timestamps if now - t < 3600]
        if len(hour_ts) >= MAX_PER_HOUR:
            wait = int((3600 - (now - hour_ts[0])) / 60) + 1
            return False, (
                f"⚠️ Hourly limit reached ({MAX_PER_HOUR}/hour). "
                f"Try again in ~{wait} min."
            )

        # Cooldown
        if timestamps:
            elapsed = now - timestamps[-1]
            if elapsed < COOLDOWN_SECS:
                wait = int(COOLDOWN_SECS - elapsed) + 1
                return False, f"⏳ Please wait {wait} seconds before starting again."

        return True, ""


def start_analysis(user_id: int):
    """Record analysis start in Supabase + RAM."""
    now = time.time()
    with _lock:
        _running[user_id] = True
        _ram[user_id].append(now)

    if _use_supabase():
        try:
            _record_supabase(user_id)
        except Exception as e:
            log.warning(f"Supabase rate record failed: {e}")


def end_analysis(user_id: int):
    """Mark analysis complete."""
    with _lock:
        _running[user_id] = False


def is_running(user_id: int) -> bool:
    with _lock:
        return _running.get(user_id, False)


def get_user_stats(user_id: int) -> dict:
    now = time.time()
    if _use_supabase():
        try:
            timestamps = _get_timestamps_supabase(user_id)
        except Exception:
            timestamps = [t for t in _ram[user_id] if now - t < 86400]
    else:
        timestamps = [t for t in _ram[user_id] if now - t < 86400]

    hour_ts = [t for t in timestamps if now - t < 3600]
    return {
        "today":           len(timestamps),
        "this_hour":       len(hour_ts),
        "running":         is_running(user_id),
        "remaining_today": max(0, MAX_PER_DAY - len(timestamps)),
        "remaining_hour":  max(0, MAX_PER_HOUR - len(hour_ts)),
    }

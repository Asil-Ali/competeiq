"""
state.py — Per-user session state (in-memory)
"""
import threading

_lock     = threading.Lock()
_sessions = {}

def get_session(user_id: int) -> dict:
    with _lock:
        if user_id not in _sessions:
            _sessions[user_id] = {}
        return dict(_sessions[user_id])

def set_val(user_id: int, key: str, value):
    with _lock:
        if user_id not in _sessions:
            _sessions[user_id] = {}
        _sessions[user_id][key] = value

def get_val(user_id: int, key: str, default=None):
    with _lock:
        return _sessions.get(user_id, {}).get(key, default)

def reset_session(user_id: int):
    with _lock:
        _sessions[user_id] = {}

def get_all_sessions() -> dict:
    with _lock:
        return dict(_sessions)

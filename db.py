"""
db.py — Supabase REST API Wrapper
Uses urllib only — no extra dependencies
Free Supabase tier: 500MB PostgreSQL, persistent across deployments

Usage:
    from db import DB
    DB.insert("analyses", {"business_name": "Test", "quality_score": 8.5})
    rows = DB.select("known_competitors", {"industry": "eq.saas"}, limit=10)
"""

import urllib.request, urllib.parse, urllib.error
import json, os, logging

log = logging.getLogger("db")

# Supabase filter operators (PostgREST syntax)
# eq=equals, gt=greater than, lt=less than, gte>=, lte<=, like=LIKE
# Usage: {"industry": "eq.saas", "quality_score": "gte.7"}


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL or SUPABASE_ANON_KEY not set")
    return url, key


def _request(method: str, path: str, data=None, extra_headers=None) -> list | dict:
    url, key = _cfg()
    endpoint = f"{url}/rest/v1/{path}"
    headers  = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    body = json.dumps(data).encode("utf-8") if data is not None else None
    req  = urllib.request.Request(endpoint, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else []
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")[:200]
        log.error(f"Supabase {method} /{path} → {e.code}: {err}")
        raise
    except Exception as e:
        log.error(f"Supabase request failed: {e}")
        raise


class DB:
    """Static Supabase REST client."""

    @staticmethod
    def select(table: str, filters: dict = None, order: str = None,
               limit: int = None, columns: str = "*") -> list:
        """
        SELECT from table.
        filters: PostgREST format {"col": "eq.value", "col2": "gte.5"}
        order:   "created_at.desc"
        """
        params = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)

        qs   = urllib.parse.urlencode(params)
        path = f"{table}?{qs}"
        result = _request("GET", path)
        return result if isinstance(result, list) else []

    @staticmethod
    def insert(table: str, data: dict, upsert_on: str = None) -> list:
        """
        INSERT row. If upsert_on given, INSERT OR UPDATE on that column conflict.
        Returns list of inserted rows.
        """
        headers = {"Prefer": "return=representation"}
        if upsert_on:
            headers["Prefer"] += f",resolution=merge-duplicates"
            headers["x-upsert"] = "true"  # Supabase upsert header

        return _request("POST", table, data=data, extra_headers=headers) or []

    @staticmethod
    def upsert(table: str, data: dict) -> list:
        """INSERT OR UPDATE — table must have unique constraint."""
        headers = {
            "Prefer":   "return=representation,resolution=merge-duplicates",
            "x-upsert": "true",
        }
        return _request("POST", table, data=data, extra_headers=headers) or []

    @staticmethod
    def update(table: str, data: dict, filters: dict) -> list:
        """UPDATE rows matching filters."""
        qs   = urllib.parse.urlencode(filters)
        path = f"{table}?{qs}"
        return _request("PATCH", path, data=data,
                         extra_headers={"Prefer": "return=representation"}) or []

    @staticmethod
    def delete(table: str, filters: dict) -> None:
        """DELETE rows matching filters."""
        qs   = urllib.parse.urlencode(filters)
        path = f"{table}?{qs}"
        _request("DELETE", path)

    @staticmethod
    def count(table: str, filters: dict = None) -> int:
        """COUNT rows matching filters."""
        params = {"select": "id"}
        if filters:
            params.update(filters)
        qs     = urllib.parse.urlencode(params)
        path   = f"{table}?{qs}"
        result = _request("GET", path, extra_headers={"Prefer": "count=exact"})
        if isinstance(result, list):
            return len(result)
        return 0

    @staticmethod
    def is_configured() -> bool:
        """Check if Supabase env vars are set."""
        return bool(
            os.environ.get("SUPABASE_URL", "").strip() and
            os.environ.get("SUPABASE_ANON_KEY", "").strip()
        )

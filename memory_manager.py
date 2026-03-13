"""
memory_manager.py v3 — Supabase-Backed Persistent Memory
Solves: SQLite lost on Koyeb restart — Supabase persists forever
Free Supabase tier: 500MB, persistent, no card needed
"""

import logging
from datetime import datetime
from db import DB

log = logging.getLogger("memory")


def record_analysis(industry, business_name, competitors, quality_score,
                    successful_queries, reflection_count=0, learnings=None):
    """Record completed analysis to Supabase."""
    if not DB.is_configured():
        log.warning("Supabase not configured — memory not saved")
        return
    try:
        ind = (industry or "general").lower().strip()

        # 1. Record analysis
        DB.insert("analyses", {
            "business_name":    business_name,
            "industry":         ind,
            "quality_score":    quality_score,
            "competitor_count": len(competitors),
            "reflection_count": reflection_count,
        })

        # 2. Upsert successful queries (increment use_count if exists)
        for q in (successful_queries or [])[:10]:
            q = q.strip()
            if not q:
                continue
            # Try upsert — if query exists, increment count
            existing = DB.select("search_queries", {"query": f"eq.{q}"}, limit=1)
            if existing:
                DB.update("search_queries",
                          {"use_count": existing[0]["use_count"] + 1},
                          {"query": f"eq.{q}"})
            else:
                DB.insert("search_queries", {"query": q, "industry": ind})

        # 3. Insert learnings
        for l in (learnings or []):
            l = l.strip()
            if l and len(l) >= 10:
                try:
                    DB.insert("learnings", {"learning": l, "industry": ind})
                except Exception:
                    pass  # Ignore duplicate

        # 4. Upsert known competitors
        for c in competitors:
            name = c.get("name", "").strip()
            if not name:
                continue
            existing = DB.select("known_competitors", {"name": f"eq.{name}"}, limit=1)
            if existing:
                DB.update("known_competitors", {
                    "seen_count":   existing[0]["seen_count"] + 1,
                    "last_pricing": c.get("pricing_summary", ""),
                    "last_threat":  c.get("threat_level", ""),
                    "updated_at":   datetime.now().isoformat(),
                }, {"name": f"eq.{name}"})
            else:
                DB.insert("known_competitors", {
                    "name":         name,
                    "industry":     ind,
                    "last_pricing": c.get("pricing_summary", ""),
                    "last_threat":  c.get("threat_level", ""),
                })

        log.info(f"Memory saved: industry={ind} score={quality_score}")
    except Exception as e:
        log.warning(f"record_analysis failed (non-fatal): {e}")


def get_context_for_agent(industry="", competitors=None):
    """Build memory context to inject into agent system prompt."""
    if not DB.is_configured():
        return ""
    try:
        stats = get_stats()
        if stats["total_analyses"] == 0:
            return ""

        ind   = (industry or "general").lower().strip()
        lines = [
            "",
            "═══════════════════════════════════════",
            f"## AGENT MEMORY  ({stats['total_analyses']} analyses | avg quality {stats['avg_quality_score']}/10)",
            "═══════════════════════════════════════",
        ]

        # Industry stats
        ind_rows = DB.select("analyses", {"industry": f"eq.{ind}"}, limit=100)
        if ind_rows:
            scores    = [r["quality_score"] for r in ind_rows if r.get("quality_score")]
            avg_score = round(sum(scores)/len(scores), 1) if scores else 0
            lines.append(f"\nIndustry '{industry}': {len(ind_rows)} analyses, avg {avg_score}/10")

        # Known competitors in this industry
        known = DB.select("known_competitors",
                          {"industry": f"eq.{ind}"},
                          order="seen_count.desc", limit=8)
        if known:
            lines.append("\nKnown competitors in this space:")
            for k in known:
                pricing = (k.get("last_pricing") or "unknown")[:40]
                lines.append(
                    f"  ✓ {k['name']} | pricing: {pricing} | "
                    f"threat: {k.get('last_threat') or '?'} | seen {k['seen_count']}x"
                )

        # Check requested competitors against known
        if competitors:
            for comp in competitors:
                name = (comp if isinstance(comp, str) else comp.get("name", "")).strip()
                if not name:
                    continue
                rows = DB.select("known_competitors", {"name": f"eq.{name}"}, limit=1)
                if rows:
                    r = rows[0]
                    pricing = (r.get("last_pricing") or "unknown")[:50]
                    lines.append(
                        f"\n⚡ Known: {r['name']} — {r.get('last_threat','?')} threat | {pricing}"
                    )

        # Top proven queries
        queries = DB.select("search_queries",
                            {"industry": f"eq.{ind}"},
                            order="use_count.desc", limit=10)
        if queries:
            lines.append("\nProven search patterns:")
            for q in queries:
                lines.append(f"  ✓ {q['query']}")

        # Recent learnings
        lrns = DB.select("learnings",
                         {"industry": f"eq.{ind}"},
                         order="id.desc", limit=5)
        if lrns:
            lines.append("\nLessons learned:")
            for l in lrns:
                lines.append(f"  → {l['learning']}")

        lines.append("═══════════════════════════════════════\n")
        return "\n".join(lines)

    except Exception as e:
        log.warning(f"get_context failed (non-fatal): {e}")
        return ""


def add_learning(learning, industry="general"):
    if not learning or len(learning.strip()) < 10:
        return
    if not DB.is_configured():
        return
    try:
        DB.insert("learnings", {
            "learning": learning.strip(),
            "industry": (industry or "general").lower(),
        })
    except Exception:
        pass


def get_stats():
    if not DB.is_configured():
        return {"total_analyses": 0, "avg_quality_score": 0,
                "industries_known": 0, "queries_stored": 0,
                "learnings_stored": 0, "competitors_known": 0,
                "last_updated": "Supabase not configured"}
    try:
        analyses   = DB.select("analyses", limit=1000)
        industries = set(r.get("industry","") for r in analyses)
        scores     = [r["quality_score"] for r in analyses if r.get("quality_score")]
        avg        = round(sum(scores)/len(scores), 2) if scores else 0
        queries    = DB.select("search_queries", limit=1)
        learnings  = DB.select("learnings", limit=1)
        comps      = DB.select("known_competitors", limit=1)
        last       = DB.select("analyses", order="id.desc", limit=1)
        return {
            "total_analyses":    len(analyses),
            "avg_quality_score": avg,
            "industries_known":  len(industries),
            "queries_stored":    len(DB.select("search_queries", limit=500)),
            "learnings_stored":  len(DB.select("learnings", limit=500)),
            "competitors_known": len(DB.select("known_competitors", limit=500)),
            "last_updated":      last[0]["created_at"] if last else "never",
        }
    except Exception as e:
        log.warning(f"get_stats failed: {e}")
        return {"total_analyses": 0, "avg_quality_score": 0,
                "industries_known": 0, "queries_stored": 0,
                "learnings_stored": 0, "competitors_known": 0,
                "last_updated": "error"}

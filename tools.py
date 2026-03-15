"""
tools.py v4 — All Agent Tools
Same as v3 — uses state.py instead of st.session_state
"""

import json, os, urllib.request, urllib.parse
from datetime import datetime
import state as S

DATA_DIR       = "data"
COMPETITOR_DIR = f"{DATA_DIR}/competitors"
HISTORY_DIR    = f"{DATA_DIR}/analysis_history"
SKILLS_DIR     = "skills"

# Current user context (set before each agent run)
_current_user_id: int = 0

def set_current_user(user_id: int):
    global _current_user_id
    _current_user_id = user_id

def _uid() -> int:
    return _current_user_id


def ensure_dirs():
    for d in [DATA_DIR, COMPETITOR_DIR, HISTORY_DIR, "outputs"]:
        os.makedirs(d, exist_ok=True)


# ════════════════════════════════════════════
# TOOL 1: WEB SEARCH
# ════════════════════════════════════════════
def web_search(query: str, max_results: int = 5) -> dict:
    try:
        enc = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={enc}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "CompeteIQ-Bot/4.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        results = []
        if data.get("Abstract"):
            results.append({"title": data.get("Heading",""), "snippet": data.get("Abstract",""), "url": data.get("AbstractURL","")})
        for t in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(t, dict) and t.get("Text"):
                results.append({"title": t.get("Text","")[:80], "snippet": t.get("Text",""), "url": t.get("FirstURL","")})
        return {"success": True, "query": query, "results": results[:max_results], "source": "duckduckgo"}
    except Exception as e:
        return {"success": False, "query": query, "error": str(e), "results": []}


# ════════════════════════════════════════════
# HELPERS: METADATA FILTERING + RE-RANKING
# ════════════════════════════════════════════

def _filter_by_metadata(results: list) -> list:
    """
    Metadata Filtering:
    Remove results that are clearly outdated (before 2023).
    If all results get filtered, return the original list as fallback.
    """
    RECENT_YEARS = {"2024", "2025", "2026"}
    filtered = []
    for r in results:
        age = str(r.get("age", ""))
        # Keep if: no age info, or age contains a recent year
        if not age or any(y in age for y in RECENT_YEARS):
            filtered.append(r)
    return filtered if filtered else results  # fallback: return all


def _rerank_results(query: str, results: list) -> list:
    """
    Re-ranking:
    Score each result by how many query words appear in its title + snippet.
    Higher score = more relevant = comes first.
    """
    query_words = set(query.lower().split())
    # Remove common stop words that add noise
    stop_words = {"the", "a", "an", "and", "or", "in", "of", "for", "to", "is", "are", "was"}
    query_words -= stop_words

    def score(result: dict) -> int:
        text = (result.get("title", "") + " " + result.get("snippet", "")).lower()
        return sum(1 for word in query_words if word in text)

    return sorted(results, key=score, reverse=True)


# ════════════════════════════════════════════
# TOOL 2: BRAVE SEARCH (replaces MCP)
# ════════════════════════════════════════════
def brave_search(query: str, max_results: int = 5) -> dict:
    """
    Search via Tavily API (replaces Brave Search).
    Falls back to DuckDuckGo if TAVILY_API_KEY not set.
    """
    import os
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()

    if not api_key:
        result = web_search(query, max_results)
        result["source"] = "duckduckgo_fallback"
        return result

    try:
        payload = json.dumps({
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic"
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title":   item.get("title", ""),
                "snippet": item.get("content", ""),
                "url":     item.get("url", ""),
                "age":     ""
            })
        results = _rerank_results(query, results)
        return {"success": True, "query": query, "results": results, "source": "tavily"}
    except Exception as e:
        result = web_search(query, max_results)
        result["source"] = "duckduckgo_fallback"
        result["tavily_error"] = str(e)
        return result


# ════════════════════════════════════════════
# TOOL 4: LOAD SKILL
# ════════════════════════════════════════════
def load_skill(skill_name: str) -> dict:
    if not skill_name.endswith("_skill"):
        skill_name = skill_name + "_skill"
    skill_file = f"{SKILLS_DIR}/{skill_name}.md"
    if not os.path.exists(skill_file):
        alt = f"{SKILLS_DIR}/{skill_name.replace('_skill','')}.md"
        if os.path.exists(alt):
            skill_file = alt
        else:
            skills = [f.replace(".md","") for f in os.listdir(SKILLS_DIR) if f.endswith(".md") and "INDEX" not in f] if os.path.exists(SKILLS_DIR) else []
            return {"success": False, "error": f"Skill not found: {skill_name}", "available": skills}
    with open(skill_file, encoding="utf-8") as f:
        content = f.read()
    from config import validate_skill
    v = validate_skill(content, skill_name)
    if not v["valid"]:
        return {"success": False, "error": f"Skill invalid — missing: {v['missing']}"}
    return {"success": True, "skill_name": skill_name, "content": content,
            "message": f"Skill '{skill_name}' loaded. Follow its INSTRUCTIONS and OUTPUT FORMAT."}


# ════════════════════════════════════════════
# TOOL 5: SAVE DATA
# ════════════════════════════════════════════
def save_data(key: str, data: dict) -> dict:
    ensure_dirs()
    uid = _uid()
    try:
        if key == "business_profile":
            path = f"{DATA_DIR}/business_profile_{uid}.json"
        elif key.startswith("competitor_"):
            name = key.replace("competitor_","").lower().replace(" ","_").replace("/","-")
            path = f"{COMPETITOR_DIR}/{uid}_{name}.json"
        elif key in ("insights", "pricing_analysis"):
            path = f"{DATA_DIR}/{key}_{uid}.json"
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{HISTORY_DIR}/{key}_{uid}_{ts}.json"

        data["_saved_at"] = datetime.now().isoformat()
        data["_key"] = key
        data["_user_id"] = uid

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Also in memory
        S.set_memory(uid, key, data)
        return {"success": True, "key": key, "path": path}
    except Exception as e:
        return {"success": False, "key": key, "error": str(e)}


# ════════════════════════════════════════════
# TOOL 6: LOAD DATA
# ════════════════════════════════════════════
def load_data(key: str) -> dict:
    ensure_dirs()
    uid = _uid()
    try:
        # Check memory first
        mem = S.get_memory(uid)
        if key in mem:
            return {"success": True, "key": key, "data": mem[key], "source": "memory"}

        if key == "all_competitors":
            comps = []
            if os.path.exists(COMPETITOR_DIR):
                for fn in os.listdir(COMPETITOR_DIR):
                    if fn.startswith(f"{uid}_") and fn.endswith(".json"):
                        with open(f"{COMPETITOR_DIR}/{fn}", encoding="utf-8") as f:
                            comps.append(json.load(f))
            return {"success": True, "key": key, "data": comps, "count": len(comps)}

        if key == "business_profile":
            path = f"{DATA_DIR}/business_profile_{uid}.json"
        elif key in ("insights", "pricing_analysis"):
            path = f"{DATA_DIR}/{key}_{uid}.json"
        else:
            path = f"{DATA_DIR}/{key}_{uid}.json"

        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            return {"success": True, "key": key, "data": d, "source": "file"}
        return {"success": False, "key": key, "error": "Not found", "data": None}
    except Exception as e:
        return {"success": False, "key": key, "error": str(e), "data": None}


# ════════════════════════════════════════════
# TOOL 7: GENERATE PDF
# ════════════════════════════════════════════
def generate_pdf(report_data: dict) -> dict:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, PageBreak, HRFlowable, Image)
        from reportlab.lib.enums import TA_CENTER
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io as _io

        buf = _io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

        C = {
            "dark":   colors.HexColor("#0a0a0f"),
            "purple": colors.HexColor("#7c3aed"),
            "light":  colors.HexColor("#f8f7ff"),
            "muted":  colors.HexColor("#6b7280"),
            "text":   colors.HexColor("#1f2937"),
            "green":  colors.HexColor("#10b981"),
            "amber":  colors.HexColor("#f59e0b"),
            "red":    colors.HexColor("#ef4444"),
        }
        def S_(n, **kw): return ParagraphStyle(n, **kw)
        styles = {
            "title": S_("t",  fontName="Helvetica-Bold", fontSize=26, textColor=colors.white, alignment=TA_CENTER, spaceAfter=6),
            "sub":   S_("sb", fontName="Helvetica",      fontSize=11, textColor=colors.HexColor("#a78bfa"), alignment=TA_CENTER),
            "h1":    S_("h1", fontName="Helvetica-Bold", fontSize=18, textColor=C["dark"],   spaceBefore=14, spaceAfter=8),
            "h2":    S_("h2", fontName="Helvetica-Bold", fontSize=13, textColor=C["purple"], spaceBefore=10, spaceAfter=5),
            "body":  S_("bd", fontName="Helvetica",      fontSize=10, textColor=C["text"],   leading=15, spaceAfter=5),
            "small": S_("sm", fontName="Helvetica",      fontSize=8,  textColor=C["muted"],  alignment=TA_CENTER),
        }

        business    = report_data.get("business_profile", {})
        competitors = report_data.get("competitors", [])
        insights    = report_data.get("insights", {})
        pricing     = report_data.get("pricing_analysis", {})
        story = []

        # Cover
        story.append(Spacer(1, 1.5*cm))
        ct = Table([[Paragraph(business.get("name","Your Business"), styles["title"])]], colWidths=[17*cm])
        ct.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C["dark"]),("TOPPADDING",(0,0),(-1,-1),28),("BOTTOMPADDING",(0,0),(-1,-1),28)]))
        story.append(ct); story.append(Spacer(1,.4*cm))
        story.append(Paragraph("COMPETITIVE INTELLIGENCE REPORT", styles["sub"]))
        story.append(Paragraph(f"Generated by CompeteIQ · {datetime.now().strftime('%B %d, %Y')}", styles["small"]))
        story.append(Spacer(1,.8*cm))

        high = sum(1 for c in competitors if str(c.get("threat_level","")).lower()=="high")
        sd = [[
            Paragraph(f"<b>{len(competitors)}</b><br/><font size='8'>Analyzed</font>",  styles["body"]),
            Paragraph(f"<b>{high}</b><br/><font size='8'>High Threat</font>",            styles["body"]),
            Paragraph(f"<b>{len(insights.get('recommendations',[]))}</b><br/><font size='8'>Recommendations</font>", styles["body"]),
            Paragraph(f"<b>WAT</b><br/><font size='8'>Framework</font>",                styles["body"]),
        ]]
        st2 = Table(sd, colWidths=[4.25*cm]*4)
        st2.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C["light"]),("ALIGN",(0,0),(-1,-1),"CENTER"),
                                   ("TOPPADDING",(0,0),(-1,-1),13),("BOTTOMPADDING",(0,0),(-1,-1),13),
                                   ("GRID",(0,0),(-1,-1),1,colors.white)]))
        story.append(st2); story.append(PageBreak())

        # Executive Summary
        story.append(Paragraph("Executive Summary", styles["h1"]))
        story.append(HRFlowable(width="100%", thickness=2, color=C["purple"]))
        story.append(Spacer(1,.3*cm))
        story.append(Paragraph(insights.get("executive_summary","Analysis complete."), styles["body"]))
        story.append(Spacer(1,.4*cm))
        story.append(Paragraph("Key Findings", styles["h2"]))
        for f in insights.get("key_findings",[]):
            story.append(Paragraph(f"→  {f}", styles["body"]))
        if insights.get("market_position_summary"):
            story.append(Spacer(1,.3*cm))
            story.append(Paragraph("Market Position", styles["h2"]))
            story.append(Paragraph(insights["market_position_summary"], styles["body"]))
        story.append(PageBreak())

        # Business Profile
        story.append(Paragraph("Your Business Profile", styles["h1"]))
        story.append(HRFlowable(width="100%", thickness=2, color=C["purple"]))
        rows = [["Business Name", business.get("name","N/A")],["Industry", business.get("industry","N/A")],
                ["Target Market", business.get("target_market","N/A")],["Pricing Model", business.get("pricing_model","N/A")],
                ["Price Range", business.get("price_range","N/A")],["Differentiator", business.get("differentiator","N/A")]]
        pt = Table(rows, colWidths=[5*cm,12*cm])
        pt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),C["purple"]),("TEXTCOLOR",(0,0),(0,-1),colors.white),
                                  ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),10),
                                  ("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9),
                                  ("LEFTPADDING",(0,0),(-1,-1),12),("ROWBACKGROUNDS",(1,0),(1,-1),[colors.white,C["light"]]),
                                  ("GRID",(0,0),(-1,-1),.4,colors.HexColor("#e5e7eb"))]))
        story.append(Spacer(1,.3*cm)); story.append(pt); story.append(PageBreak())

        # Competitor Profiles
        story.append(Paragraph("Competitor Profiles", styles["h1"]))
        story.append(HRFlowable(width="100%", thickness=2, color=C["purple"]))
        story.append(Spacer(1,.3*cm))
        sorted_c = sorted(competitors, key=lambda c: {"high":0,"medium":1,"low":2}.get(str(c.get("threat_level","")).lower(),1))
        for comp in sorted_c:
            threat = str(comp.get("threat_level","Medium")).upper()
            tc = {"HIGH":C["red"],"MEDIUM":C["amber"],"LOW":C["green"]}.get(threat, C["amber"])
            ch = Table([[Paragraph(f"<b>{comp.get('name','?')}</b>", styles["h2"]),
                          Paragraph(f"<b>{threat}</b>", ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9, textColor=tc, alignment=1))]],
                        colWidths=[13*cm,4*cm])
            ch.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C["light"]),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                      ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                                      ("LEFTPADDING",(0,0),(0,0),12),("ALIGN",(1,0),(1,0),"RIGHT"),
                                      ("LINEBELOW",(0,0),(-1,-1),2,tc)]))
            story.append(ch); story.append(Spacer(1,.1*cm))
            def _list(v): return " • ".join(v) if isinstance(v,list) else str(v or "N/A")
            drows = [["Website", comp.get("website","N/A")],["Pricing", comp.get("pricing_summary","N/A")],
                      ["Target Market", comp.get("target_market","N/A")],["Strengths", _list(comp.get("strengths",[]))],
                      ["Weaknesses", _list(comp.get("weaknesses",[]))],
                      ["Your Advantage", comp.get("your_advantage_over_them",comp.get("your_advantage","N/A"))],
                      ["Sentiment", comp.get("sentiment_score","N/A")],
                      ["Threat Reason", comp.get("threat_justification",comp.get("threat_reason","N/A"))]]
            dt = Table(drows, colWidths=[4*cm,13*cm])
            dt.setStyle(TableStyle([("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("TEXTCOLOR",(0,0),(0,-1),C["purple"]),
                                      ("FONTSIZE",(0,0),(-1,-1),9),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
                                      ("LEFTPADDING",(0,0),(-1,-1),8),("ROWBACKGROUNDS",(0,0),(-1,-1),[colors.white,C["light"]]),
                                      ("GRID",(0,0),(-1,-1),.3,colors.HexColor("#e5e7eb"))]))
            story.append(dt); story.append(Spacer(1,.6*cm))
        story.append(PageBreak())

        # Pricing Chart
        story.append(Paragraph("Pricing Analysis", styles["h1"]))
        story.append(HRFlowable(width="100%", thickness=2, color=C["purple"]))
        story.append(Spacer(1,.3*cm))
        if pricing.get("client_position"):
            cp = pricing["client_position"]
            story.append(Paragraph(f"Your position: <b>{cp.get('zone','?').upper()}</b> — {cp.get('pricing_verdict','?').replace('_',' ').title()}", styles["body"]))
            story.append(Paragraph(cp.get("reasoning",""), styles["body"]))
        try:
            names  = [str(c.get("name","?"))[:14] for c in competitors]
            prices = [float(c.get("avg_price",0) or 0) for c in competitors]
            bcols  = [{"high":"#ef4444","medium":"#f59e0b","low":"#10b981"}.get(str(c.get("threat_level","medium")).lower(),"#7c3aed") for c in competitors]
            fig, ax = plt.subplots(figsize=(10,4.5)); fig.patch.set_facecolor("#f8f7ff"); ax.set_facecolor("#f8f7ff")
            bars = ax.bar(names, prices, color=bcols, alpha=0.85, width=0.55, zorder=3)
            ax.set_title("Competitor Pricing Comparison", fontsize=13, fontweight="bold", pad=12, color="#0a0a0f")
            ax.set_ylabel("Avg Monthly Price ($)", fontsize=9); ax.grid(axis="y", alpha=0.25, zorder=0)
            ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
            for bar, p in zip(bars, prices):
                if p: ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1, f"${int(p)}", ha="center", va="bottom", fontsize=8, fontweight="bold")
            plt.xticks(rotation=15, ha="right", fontsize=9); plt.tight_layout()
            ibuf = _io.BytesIO(); plt.savefig(ibuf, format="png", dpi=150, bbox_inches="tight"); ibuf.seek(0); plt.close()
            story.append(Image(ibuf, width=15*cm, height=6.75*cm))
        except: pass
        story.append(PageBreak())

        # Recommendations
        story.append(Paragraph("Strategic Recommendations", styles["h1"]))
        story.append(HRFlowable(width="100%", thickness=2, color=C["purple"]))
        story.append(Spacer(1,.3*cm))
        rcols = [C["green"], C["amber"], C["purple"]]
        rlbls = ["🚀 Quick Win", "📈 Medium Term", "🏆 Long Term"]
        for i, rec in enumerate(insights.get("recommendations",[])[:3]):
            rc = rcols[i] if i<3 else C["purple"]
            lbl = f"{rlbls[i]} ({rec.get('timeframe','')})" if i<3 else f"Recommendation {i+1}"
            rh = Table([[Paragraph(f"<b>{lbl}</b>", styles["body"])]], colWidths=[17*cm])
            rh.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),rc),("TEXTCOLOR",(0,0),(-1,-1),colors.white),
                                      ("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9),("LEFTPADDING",(0,0),(-1,-1),14)]))
            story.append(rh)
            for lk, lv in [("what","What"),("why","Why"),("impact","Impact"),("metric","Success Metric")]:
                if rec.get(lk): story.append(Paragraph(f"<b>{lv}:</b>  {rec[lk]}", styles["body"]))
            story.append(Spacer(1,.5*cm))

        doc.build(story)
        pdf_bytes = buf.getvalue()
        # Save to user session
        S.set_val(_uid(), "pdf_bytes", pdf_bytes)
        return {"success": True, "message": "PDF generated", "size_kb": len(pdf_bytes)//1024}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════
# TOOL 8: FINISH ANALYSIS
# ════════════════════════════════════════════
def finish_analysis(summary: dict) -> dict:
    uid = _uid()
    S.set_val(uid, "analysis_complete", True)
    S.set_val(uid, "analysis_summary", summary)
    return {"success": True, "message": "Analysis complete!", "summary": summary}


# ════════════════════════════════════════════
# TOOL REGISTRY
# ════════════════════════════════════════════
TOOLS = {
    "brave_search":    brave_search,
    "web_search":      web_search,
    "load_skill":      load_skill,
    "save_data":       save_data,
    "load_data":       load_data,
    "generate_pdf":    generate_pdf,
    "finish_analysis": finish_analysis,
}

TOOL_DEFINITIONS = [
    {
        "name": "brave_search",
        "description": "Search the web via Brave Search API (preferred — more accurate and up-to-date). Falls back to DuckDuckGo automatically if key not configured. Use this for ALL web searches.",
        "input_schema": {"type":"object","properties":{"query":{"type":"string","description":"Specific search query. Include company name and what you're looking for."},"max_results":{"type":"integer","default":5}},"required":["query"]}
    },
    {
        "name": "web_search",
        "description": "Search the web via DuckDuckGo. Use brave_search instead unless it fails.",
        "input_schema": {"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","default":5}},"required":["query"]}
    },
    {
        "name": "load_skill",
        "description": "Load a trusted skill file before each task phase. Available: research_skill, pricing_skill, sentiment_skill, report_writing_skill.",
        "input_schema": {"type":"object","properties":{"skill_name":{"type":"string"}},"required":["skill_name"]}
    },
    {
        "name": "save_data",
        "description": "Save data persistently. Keys: 'business_profile', 'competitor_{name}', 'insights', 'pricing_analysis'.",
        "input_schema": {"type":"object","properties":{"key":{"type":"string"},"data":{"type":"object"}},"required":["key","data"]}
    },
    {
        "name": "load_data",
        "description": "Load saved data. Use 'all_competitors' to load all competitor profiles at once.",
        "input_schema": {"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}
    },
    {
        "name": "generate_pdf",
        "description": "Generate the final PDF report. Call only after all research and analysis is complete and saved.",
        "input_schema": {"type":"object","properties":{"report_data":{"type":"object"}},"required":["report_data"]}
    },
    {
        "name": "finish_analysis",
        "description": "Mark analysis as complete. Call this as the absolute LAST step after PDF is generated.",
        "input_schema": {"type":"object","properties":{"summary":{"type":"object"}},"required":["summary"]}
    },
]


def execute_tool(name: str, inp: dict) -> str:
    if name not in TOOLS:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return json.dumps(TOOLS[name](**inp), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name})

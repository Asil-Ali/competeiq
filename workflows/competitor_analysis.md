# Competitor Analysis — Master SOP v5
# Standard Operating Procedure for production-grade competitive intelligence

## PHASE 0: INITIALIZATION
1. Load `research_skill`
2. Save business profile:
   save_data("business_profile", {name, industry, target_market, pricing_model, price_range, differentiator})
3. Confirm: "✅ Business profile saved. Starting competitor research..."

---

## PHASE 1: COMPETITOR RESEARCH
For EACH competitor (repeat this block):

### Step 1.1 — Basic Research
- brave_search: "{competitor} official website pricing"
- brave_search: "{competitor} features overview 2025"
- brave_search: "{competitor} target market customers"

### Step 1.2 — Pricing Deep Dive
- brave_search: "{competitor} pricing plans cost per month"
- brave_search: "{competitor} enterprise pricing"
- Extract: pricing tiers, free plan?, avg monthly cost

### Step 1.3 — Sentiment Analysis
- Load `sentiment_skill`
- brave_search: "{competitor} reviews complaints Reddit 2025"
- brave_search: "{competitor} G2 Capterra reviews"
- Extract: top praise, top complaints, churn reasons

### Step 1.4 — Save Immediately
save_data("competitor_{name}", {
  name, website, pricing_summary, avg_price,
  target_market, strengths, weaknesses,
  sentiment_score, top_praise, top_complaints,
  your_advantage_over_them, threat_level, threat_justification
})

---

## PHASE 2: PRICING ANALYSIS
1. Load `pricing_skill`
2. load_data("all_competitors")
3. brave_search: "{industry} SaaS pricing benchmarks 2025"
4. Analyze: market range, tiers, client position
5. save_data("pricing_analysis", {...})

---

## PHASE 3: STRATEGIC INSIGHTS
1. Load `report_writing_skill`
2. load_data("all_competitors") + load_data("business_profile") + load_data("pricing_analysis")
3. Generate:
   - executive_summary (4-5 sentences, specific to THIS business)
   - key_findings (4-6 items, specific and data-backed)
   - market_position_summary
   - recommendations (3 items: quick win / medium / long-term)
     Each needs: what, why, impact, timeframe, metric
4. save_data("insights", {...})

---

## PHASE 4: QUALITY GATE (MANDATORY)
1. Load `quality_check_skill`
2. Verify all competitor data fields are complete and sourced
3. Verify insights are specific (not generic)
4. Fix any gaps found — do targeted searches
5. Re-save corrected data

---

## PHASE 5: PDF GENERATION
1. load_data("all_competitors")
2. load_data("business_profile")
3. load_data("insights")
4. load_data("pricing_analysis")
5. generate_pdf({business_profile, competitors, insights, pricing_analysis})
6. Confirm PDF generated successfully

---

## PHASE 6: FINISH
1. finish_analysis({
     recommended_first_action: "specific action with timeline",
     biggest_opportunity: "specific gap in market",
     top_threat: "specific competitor + reason"
   })

---

## QUALITY STANDARDS
- Minimum 3 brave_search calls per competitor
- No field should contain invented data
- Recommendations must be implementable within 90 days (for quick wins)
- Every threat_level assignment needs a 1-sentence justification


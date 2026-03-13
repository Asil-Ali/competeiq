## SKILL: quality_check_skill
## PURPOSE
Guide the agent through a self-audit before generating the final PDF.
Use this skill to catch gaps, hallucinations, and weak analysis before delivery.

## INSTRUCTIONS
1. Load all competitor data using load_data("all_competitors")
2. For each competitor, verify:
   - website: is it a real URL? (not N/A)
   - pricing_summary: is it based on a search result?
   - avg_price: is it 0 or a real number? (not invented)
   - strengths: are they specific? (not generic like "good product")
   - weaknesses: are they specific? (not generic)
   - threat_level: is it justified by evidence?
3. Check insights:
   - executive_summary: is it specific to THIS business? (not generic)
   - recommendations: do they have what/why/impact/timeframe/metric?
4. For any field that fails → do a targeted search to fill it properly
5. Only proceed to generate_pdf after all checks pass

## OUTPUT FORMAT
After completing quality check, output a brief audit summary:
- Fields verified: X/Y
- Issues fixed: list
- Confidence level: High/Medium/Low
Then proceed to generate_pdf.

## HALLUCINATION CHECKLIST
Before generating PDF, confirm:
- [ ] No invented pricing numbers
- [ ] No assumed features (all verified by search)
- [ ] No fabricated user counts or revenue
- [ ] threat_level backed by specific evidence
- [ ] recommendations are realistic for the client's situation


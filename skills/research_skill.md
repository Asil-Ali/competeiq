## SKILL: research_skill
## PURPOSE
Guide thorough competitor research using web search to gather accurate, current data.

## INSTRUCTIONS
1. Search for the competitor's official website and pricing page
2. Search for recent news (last 12 months) about the competitor
3. Search for user reviews on G2, Capterra, Trustpilot, Reddit
4. Identify: target market, pricing model, key features, positioning
5. Note any recent product launches or pivots
6. Mark any data you cannot verify as "Not publicly available"

## OUTPUT FORMAT
Return a structured dict with:
- name: string
- website: string
- pricing_summary: string
- avg_price: number (monthly USD estimate, 0 if unknown)
- target_market: string
- strengths: list of strings
- weaknesses: list of strings
- your_advantage_over_them: string
- threat_level: "high" | "medium" | "low"
- threat_justification: string


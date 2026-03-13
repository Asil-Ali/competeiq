## SKILL: pricing_skill
## PURPOSE
Analyze the competitive pricing landscape and determine the client's optimal pricing position.

## INSTRUCTIONS
1. Compare all competitor price points
2. Calculate market average and range
3. Identify pricing tiers in the market (budget / mid / premium)
4. Determine where the client sits relative to competitors
5. Assess if client is under-priced, well-positioned, or over-priced
6. Recommend pricing adjustments if needed

## OUTPUT FORMAT
Return pricing_analysis dict with:
- market_avg_price: number
- price_range: {min: number, max: number}
- pricing_tiers: {budget: string, mid: string, premium: string}
- client_position: {zone: string, pricing_verdict: string, reasoning: string}
- recommendations: list of strings


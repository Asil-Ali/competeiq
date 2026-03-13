## SKILL: sentiment_skill
## PURPOSE
Analyze customer sentiment toward a competitor from reviews and social media.

## INSTRUCTIONS
1. Search for reviews on G2, Capterra, Reddit, Twitter/X
2. Identify recurring praise themes (what users love)
3. Identify recurring complaint themes (what users hate)
4. Look for patterns in churn reasons
5. Assess overall sentiment: positive / mixed / negative

## OUTPUT FORMAT
Return sentiment data as part of competitor dict:
- sentiment_score: "Positive" | "Mixed" | "Negative"
- top_praise: list of strings (max 3)
- top_complaints: list of strings (max 3)
- churn_risk_factors: list of strings


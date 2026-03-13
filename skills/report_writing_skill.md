## SKILL: report_writing_skill
## PURPOSE
Transform research data into clear, actionable insights for the PDF report.

## INSTRUCTIONS
1. Write an executive summary (3-4 sentences, business-level language)
2. Extract 3-5 key findings from the research
3. Write a market position summary
4. Create 3 specific recommendations (quick win / medium term / long term)
5. Each recommendation must have: what, why, impact, timeframe, metric

## OUTPUT FORMAT
Return insights dict with:
- executive_summary: string
- key_findings: list of strings (3-5 items)
- market_position_summary: string
- recommendations: list of dicts, each with:
  - what: string
  - why: string
  - impact: string
  - timeframe: string
  - metric: string


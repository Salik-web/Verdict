You are an impartial judge extracting brand mentions from an AI engine's answer.

The user asked an AI assistant a product-research question. Given the answer
below, extract structured data about how brands are mentioned. You are analyzing
visibility for this company:

Target brand: {brand}
Aliases for the target brand: {aliases}
Known competitors: {competitors}

CRITICAL: Extract ONLY brands that literally appear in the answer text below. The
"Known competitors" line is context to help you recognize names — it is NOT a list
to copy. Never output a brand (target or competitor) that does not actually appear
in the answer. A known competitor that is not mentioned must be omitted, not listed.
Do not put the target brand in the competitors array.

From the answer, determine:

- Whether the TARGET brand is mentioned (any alias counts; only if it appears).
- Its rank position (1 = the first brand named in the answer; null if not mentioned).
- Sentiment toward it: positive | neutral | negative (null if not mentioned).
- A sentiment score in [-1, 1] (null if not mentioned).
- The URLs cited anywhere in the answer.
- Every OTHER brand that ACTUALLY appears in the answer, with its rank position
  (order of first appearance) and sentiment.

Return ONLY JSON of this exact shape:
{{
  "brand": "{brand}",
  "mentioned": true,
  "position": 1,
  "sentiment": "neutral",
  "sentiment_score": 0.0,
  "cited_urls": ["https://..."],
  "competitors": [
    {{"brand": "Name", "position": 1, "sentiment": "positive"}}
]
}}

## Answer to analyze:

{answer}

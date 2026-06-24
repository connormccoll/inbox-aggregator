"""Canonical extraction prompt — seed + fallback for the versioned prompt store."""

BASE_EXTRACTION_PROMPT = """You are a financial email analyst. Analyse the following email and extract all stock trading information.

Return ONLY a valid JSON object with this exact structure (no markdown, no explanation):
{{
  "recommendations": [
    {{
      "ticker": "AAPL",
      "action": "BUY",
      "sentiment": "brief quote or rationale from the email",
      "confidence": "HIGH",
      "price_target": null,
      "stop_loss_price": null,
      "instrument_type": "STOCK",
      "option_symbol": null,
      "option_type": null,
      "strike_price": null,
      "expiration_date": null,
      "percent_closed": null,
      "closed_by": null,
      "url": null
    }}
  ],
    "source_name": "TradeSmith",
    "analyst": "Zach Scheidt"
}}

Rules:

ACTION SELECTION — use the first matching rule:
1. CLOSE: percent_closed = 100, or text says "Percent Closed: 100%", or position described as fully closed. CRITICAL override — takes priority over any other action word in the text. "Buy MSTR $110 Put" in a close alert is a position label, NOT a new recommendation.
2. STOP_LOSS: stop-loss trigger or stop-loss alert from any source.
3. SELL: explicit instruction to sell.
4. BUY: explicit instruction to buy (including options contracts).
5. HOLD: explicit hold recommendation.
6. POSITIVE: the email is BULLISH on a specific named stock — earnings beats, raised guidance, "further upside", "strong momentum", "accelerating growth", analyst upgrades, bullish analysis focused on a named ticker. Use this for newsletter/research emails that analyse a stock favourably even without saying "buy".
7. NEGATIVE: the email is BEARISH on a specific named stock — misses, warnings, downgrade language, "downside risk", bearish analysis focused on a named ticker.

IMPORTANT — what counts as a recommendation:
- Any email that analyses a specific stock and draws a bullish or bearish conclusion produces a POSITIVE or NEGATIVE recommendation for that ticker. You do NOT need an explicit "buy" or "sell" command.
- Research newsletters, earnings analysis emails, and market commentary focused on a named stock ALWAYS produce at least a POSITIVE or NEGATIVE recommendation.
- If the email is not related to stocks or investing (health, politics, advertising, lifestyle, retail promotions, etc.), return an empty recommendations array and do not attempt to extract anything.
- Do NOT extract tickers from marketing or promotional emails that merely mention a company name in passing (e.g. "buy at Staples", "available on Apple devices"). A valid recommendation requires the email's PRIMARY purpose to be financial analysis or stock advice about that ticker.
- Do NOT extract tickers from advertisement blocks, sponsored content, or unsubscribe footers embedded in otherwise relevant emails.

OTHER RULES:
- confidence: HIGH (explicit rec or very strong language), MEDIUM (implied or analytical), LOW (brief mention)
- sentiment: the most informative bullish/bearish quote or data point from the email (e.g. "EPS beat by 790%, FCF of $4.8B exceeds full-year 2025")
- price_target: numeric if stated, else null
- stop_loss_price: numeric if stated, else null
- instrument_type: STOCK or OPTION
- option_symbol: full OCC option symbol if present (e.g. MSTR260515P00110000), else null
- option_type: PUT or CALL if an option, else null
- strike_price: numeric strike price if an option, else null
- expiration_date: YYYY-MM-DD expiration if an option, else null
- percent_closed: numeric percentage if stated (e.g. 100), else null
- closed_by: if the email says "Was closed in Newsletters: X" or similar, extract X; else null
- ticker: always the underlying stock symbol, not the option symbol
- source_name: the newsletter or publication name (e.g. "Banyan Hill", "Motley Fool"), NOT the forwarding sender
- analyst: the PERSON who wrote the email or made the call (newsletter author/editor/analyst), e.g. "Zach Scheidt", "Keith Kaplan". This is an individual's name, distinct from source_name (the publication). null if no person is identifiable.
- url: the single most relevant link in the email for THIS recommendation (the "read more"/article/trade-alert link). Prefer the primary content link; ignore unsubscribe, manage-preferences, and advertisement links. Must start with http:// or https://. null if none.
- ticker must be explicitly present in the email text as a stock symbol (e.g. AAPL, TSLA, NVDA, or NASDAQ:AAPL / NYSE:GEV). Do not infer ticker symbols from company names alone (e.g. Apple, Staples).

Email subject: {subject}
Email from: {sender}
Email date: {email_date}

Email body:
{body}"""

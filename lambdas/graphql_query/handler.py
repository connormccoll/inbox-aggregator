"""
graphql_query/handler.py

Lightweight GraphQL-style read endpoint for recommendation lookups.
Supported operations:
- chatQuery(prompt: String!)
- recommendations(ticker: String!, limit: Int)
- closeEvents(ticker: String!, source: String)

This is intentionally narrow and read-only.
"""

import json
import logging
import os
import re
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)

RECOMMENDATIONS_TABLE = os.environ["RECOMMENDATIONS_TABLE"]
OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _to_jsonable(value):
    if isinstance(value, Decimal):
        # Keep integer-like values as int for cleaner JSON.
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


def _extract_ticker(text: str) -> str | None:
    if not text:
        return None

    # Explicit symbol pattern first.
    m = re.search(r"\b(?:NASDAQ|NYSE)?\s*:?[\s-]*([A-Z]{1,5})\b", text.upper())
    if m:
        candidate = m.group(1)
        if candidate not in {"BUY", "SELL", "CLOSE", "OPEN", "STOP", "LOSS", "WITH", "FROM", "WHEN", "WHAT"}:
            return candidate

    # Fallback: all-caps token in user prompt.
    for token in re.findall(r"\b[A-Z]{1,5}\b", text.upper()):
        if token not in {"BUY", "SELL", "CLOSE", "OPEN", "STOP", "LOSS", "WITH", "FROM", "WHEN", "WHAT"}:
            return token
    return None


def _extract_source(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\bby\s+([A-Za-z0-9:&' .\-]{2,80})", text, flags=re.IGNORECASE)
    if not m:
        return None
    source = m.group(1).strip().strip("?.!,")
    return source or None


def _query_recommendations(ticker: str, limit: int = 20) -> list[dict]:
    table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"),
        ScanIndexForward=False,
        Limit=max(1, min(limit, 100)),
    )
    return resp.get("Items", [])


def _query_close_events(ticker: str, source_filter: str | None = None) -> list[dict]:
    table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    resp = table.query(KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"))

    rows = []
    for item in resp.get("Items", []):
        if item.get("open_status") != "CLOSED":
            continue
        if source_filter and source_filter.lower() not in str(item.get("source", "")).lower():
            continue
        rows.append(item)

    rows.sort(key=lambda x: str(x.get("close_date", "")), reverse=True)
    return rows


def _run_chat_query(prompt: str) -> dict:
    ticker = _extract_ticker(prompt)
    if not ticker:
        return {
            "summary": "I could not find a stock ticker in your question. Try: 'recommendations for TSLA' or 'when did TradeSmith close MSTR'.",
            "rows": [],
            "intent": "unknown",
        }

    source = _extract_source(prompt)
    lower = prompt.lower()
    is_close = any(word in lower for word in ["close", "closed", "stop_loss", "stop loss", "exit", "sold"]) 

    if is_close:
        rows = _query_close_events(ticker, source)
        summary = f"Found {len(rows)} close event(s) for {ticker}."
        return {"summary": summary, "rows": rows, "intent": "closeEvents"}

    rows = _query_recommendations(ticker, limit=25)
    summary = f"Found {len(rows)} recommendation(s) for {ticker}."
    return {"summary": summary, "rows": rows, "intent": "recommendations"}


def lambda_handler(event: dict, _context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    if event.get("httpMethod") != "POST":
        return _response(405, {"errors": [{"message": "Method not allowed"}]})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"errors": [{"message": "Invalid JSON body"}]})

    query = body.get("query", "")
    variables = body.get("variables") or {}

    try:
        if "chatQuery" in query:
            prompt = str(variables.get("prompt") or "")
            result = _run_chat_query(prompt)
            return _response(200, {"data": {"chatQuery": _to_jsonable(result)}})

        if "recommendations" in query:
            ticker = _extract_ticker(str(variables.get("ticker") or ""))
            if not ticker:
                return _response(400, {"errors": [{"message": "ticker is required"}]})
            limit = int(variables.get("limit") or 20)
            rows = _query_recommendations(ticker, limit)
            return _response(200, {"data": {"recommendations": _to_jsonable(rows)}})

        if "closeEvents" in query:
            ticker = _extract_ticker(str(variables.get("ticker") or ""))
            if not ticker:
                return _response(400, {"errors": [{"message": "ticker is required"}]})
            source = variables.get("source")
            rows = _query_close_events(ticker, source)
            return _response(200, {"data": {"closeEvents": _to_jsonable(rows)}})

        return _response(400, {"errors": [{"message": "Unsupported query"}]})

    except (ClientError, ValueError, TypeError, KeyError) as exc:
        logger.exception("GraphQL query failed: %s", exc)
        return _response(500, {"errors": [{"message": "Internal server error"}]})

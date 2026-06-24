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
from datetime import datetime, timedelta, timezone
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
FEEDBACK_TABLE = os.environ.get("FEEDBACK_TABLE", "")

RANGE_DAYS = {"today": 1, "week": 7, "month": 30}
CLOSE_ACTIONS = {"CLOSE", "SELL", "STOP_LOSS", "NEGATIVE"}

TICKER_STOPWORDS = {
    "A",
    "ALSO",
    "AND",
    "ARE",
    "ASK",
    "BUY",
    "CAN",
    "CLOSE",
    "CLOSED",
    "DID",
    "DO",
    "EVENT",
    "EVENTS",
    "FOR",
    "FROM",
    "GET",
    "GIVE",
    "HOW",
    "IN",
    "INFORMATION",
    "IS",
    "IT",
    "LOSS",
    "ME",
    "MORE",
    "OF",
    "ON",
    "OPEN",
    "OR",
    "QUESTION",
    "RECOMMENDATION",
    "RECOMMENDATIONS",
    "RESULT",
    "RETURN",
    "SELL",
    "SHOW",
    "STOP",
    "THE",
    "TO",
    "WHAT",
    "WHEN",
    "WHICH",
    "WITH",
    "YOU",
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
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

    candidates = []

    # Prefer explicit symbol mentions like $MSTR, NASDAQ:MSTR, NYSE:GEV.
    for m in re.finditer(r"\$([A-Z]{1,5})\b", text.upper()):
        candidates.append(m.group(1))
    for m in re.finditer(r"\b(?:NASDAQ|NYSE)\s*:?\s*([A-Z]{1,5})\b", text.upper()):
        candidates.append(m.group(1))

    # Then scan generic tokens but require DB evidence.
    for token in re.findall(r"\b[A-Z]{1,5}\b", text.upper()):
        if token in TICKER_STOPWORDS:
            continue
        candidates.append(token)

    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _ticker_exists(candidate):
            return candidate

    return None


def _ticker_exists(ticker: str) -> bool:
    rec_table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    rec_resp = rec_table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"),
        Limit=1,
    )
    if rec_resp.get("Items"):
        return True

    open_table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    open_resp = open_table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"),
        Limit=1,
    )
    return bool(open_resp.get("Items"))


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
    rec_table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    rec_resp = rec_table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"),
        ScanIndexForward=False,
        Limit=100,
    )

    open_table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    open_resp = open_table.query(KeyConditionExpression=Key("PK").eq(f"TICKER#{ticker}"))
    open_by_source = {
        str(item.get("source", "")): item
        for item in open_resp.get("Items", [])
    }

    rows = []
    for rec in rec_resp.get("Items", []):
        action = str(rec.get("action", "")).upper()
        if action not in CLOSE_ACTIONS:
            continue

        source = str(rec.get("source", ""))
        if source_filter and source_filter.lower() not in source.lower():
            continue

        open_row = open_by_source.get(source, {})
        rows.append({
            "ticker": rec.get("ticker"),
            "source": source,
            "close_action": action,
            "close_date": rec.get("email_date"),
            "first_rec_date": open_row.get("first_rec_date"),
            "latest_rec_date": open_row.get("latest_rec_date") or rec.get("email_date"),
            "confidence": rec.get("confidence") or open_row.get("confidence"),
            "open_status": open_row.get("open_status") or "CLOSED",
            "rec_count": open_row.get("rec_count"),
            "sentiment": rec.get("sentiment"),
            "email_subject": rec.get("email_subject"),
        })

    rows.sort(key=lambda x: str(x.get("close_date", "")), reverse=True)
    return rows


def _format_recommendation_row(item: dict) -> dict:
    return {
        "ticker": item.get("ticker"),
        "action": item.get("action"),
        "source": item.get("source"),
        "email_date": item.get("email_date"),
        "email_subject": item.get("email_subject"),
        "confidence": item.get("confidence"),
        "sentiment": item.get("sentiment"),
        "price_target": item.get("price_target"),
        "stop_loss_price": item.get("stop_loss_price"),
        "instrument_type": item.get("instrument_type"),
        "option_symbol": item.get("option_symbol"),
    }


def _format_close_row(item: dict) -> dict:
    return {
        "ticker": item.get("ticker"),
        "source": item.get("source"),
        "close_action": item.get("close_action") or item.get("action"),
        "close_date": item.get("close_date"),
        "first_rec_date": item.get("first_rec_date"),
        "latest_rec_date": item.get("latest_rec_date"),
        "confidence": item.get("confidence"),
        "open_status": item.get("open_status"),
        "rec_count": item.get("rec_count"),
        "sentiment": item.get("sentiment"),
        "email_subject": item.get("email_subject"),
    }


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
        raw_rows = _query_close_events(ticker, source)
        rows = [_format_close_row(r) for r in raw_rows]
        summary = f"Found {len(rows)} close event(s) for {ticker}."
        if rows:
            latest = rows[0]
            summary += f" Latest close: {latest.get('close_date', '?')} by {latest.get('source', '?')} ({latest.get('close_action', '?')})."
        return {"summary": summary, "rows": rows, "intent": "closeEvents"}

    raw_rows = _query_recommendations(ticker, limit=25)
    rows = [_format_recommendation_row(r) for r in raw_rows]
    summary = f"Found {len(rows)} recommendation(s) for {ticker}."
    if rows:
        latest = rows[0]
        summary += f" Latest: {latest.get('action', '?')} on {latest.get('email_date', '?')} by {latest.get('source', '?')}."
    return {"summary": summary, "rows": rows, "intent": "recommendations"}


def _format_feed_row(item: dict) -> dict:
    sk = str(item.get("SK", ""))
    message_id = sk.split("#", 1)[1] if "#" in sk else sk
    return {
        "id": sk,
        "message_id": message_id,
        "ticker": item.get("ticker"),
        "action": item.get("action"),
        "source": item.get("source"),
        "email_date": item.get("email_date"),
        "created_at": item.get("created_at"),
        "sentiment": item.get("sentiment"),
        "confidence": item.get("confidence"),
        "email_subject": item.get("email_subject"),
        "price_target": item.get("price_target"),
        "stop_loss_price": item.get("stop_loss_price"),
        "instrument_type": item.get("instrument_type"),
        "option_symbol": item.get("option_symbol"),
    }


def _query_recent(range_key: str, limit: int = 300) -> list[dict]:
    """Recommendations across a rolling window via the DateIndex GSI."""
    days = RANGE_DAYS.get(range_key, 1)
    table = dynamodb.Table(RECOMMENDATIONS_TABLE)
    today = datetime.now(timezone.utc).date()
    rows: list[dict] = []
    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        kwargs = {"IndexName": "DateIndex",
                  "KeyConditionExpression": Key("date_pk").eq(f"DATE#{date_str}")}
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
            rows.extend(resp.get("Items", []))
    rows.sort(key=lambda r: (str(r.get("email_date", "")), str(r.get("created_at", ""))), reverse=True)
    return [_format_feed_row(r) for r in rows[:limit]]


def _submit_feedback(sub: str | None, variables: dict) -> dict:
    if not FEEDBACK_TABLE:
        return {"ok": False, "error": "Feedback storage is not configured."}
    message_id = str(variables.get("messageId") or "").strip()
    ticker = str(variables.get("ticker") or "").upper().strip()
    if not message_id or not ticker:
        return {"ok": False, "error": "messageId and ticker are required."}
    now = datetime.now(timezone.utc).isoformat()
    dynamodb.Table(FEEDBACK_TABLE).put_item(Item={
        "PK": "FEEDBACK",
        "SK": f"{now}#{message_id}#{ticker}",
        "message_id": message_id,
        "ticker": ticker,
        "reason": str(variables.get("reason") or "").strip(),
        "note": str(variables.get("note") or "").strip(),
        "model_action": str(variables.get("modelAction") or "").strip(),
        "source": str(variables.get("source") or "").strip(),
        "email_subject": str(variables.get("emailSubject") or "").strip(),
        "status": "NEW",
        "sub": sub or "",
        "created_at": now,
    })
    return {"ok": True, "message": "Thanks - feedback recorded."}


def _in_active_group(event: dict) -> bool:
    """True if the caller's Cognito token carries the 'active' group claim."""
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("claims", {})
    ) or {}
    raw = claims.get("cognito:groups", "")
    groups = raw if isinstance(raw, list) else str(raw).strip("[]").replace(",", " ").split()
    return "active" in groups


def lambda_handler(event: dict, _context) -> dict:
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    if not _in_active_group(event):
        return _response(403, {"errors": [{"message": "Account not activated"}]})

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

        if "recentRecommendations" in query:
            range_key = str(variables.get("range") or "today").lower()
            rows = _query_recent(range_key)
            return _response(200, {"data": {"recentRecommendations": _to_jsonable(rows)}})

        if "submitFeedback" in query:
            sub = (event.get("requestContext", {}).get("authorizer", {})
                   .get("claims", {}).get("sub"))
            result = _submit_feedback(sub, variables)
            return _response(200, {"data": {"submitFeedback": _to_jsonable(result)}})

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

"""
weekly_digest/handler.py

EventBridge-triggered Lambda. Runs weekly (default: Sundays 7 PM UTC).
Scans the OpenPositions table to build a comprehensive weekly summary:
  - All currently OPEN recommendations grouped by ticker, showing every
    source with confidence level and first recommendation date.
  - Recently CLOSED positions (within last 7 days) flagged as "CLOSE ALERT"
    to remind subscribers that a source exited or stopped out. CLOSED rows
    auto-purge via DynamoDB TTL after 7 days.

Holdings are cross-referenced so owned tickers are marked with a star (*).
"""

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]
HOLDINGS_TABLE = os.environ["HOLDINGS_TABLE"]
SUBSCRIBERS_TABLE = os.environ["SUBSCRIBERS_TABLE"]

# Max SMS length per segment × 2 segments; split digest into chunks if needed
SMS_CHUNK_SIZE = 320


def _scan_open_positions() -> list[dict]:
    """Full table scan — OpenPositions stays small (one row per ticker+source)."""
    table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    # Handle pagination
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _get_owned_tickers() -> set[str]:
    """Scan Holdings table and return all tickers currently tracked."""
    table = dynamodb.Table(HOLDINGS_TABLE)
    owned = set()
    resp = table.scan(ProjectionExpression="SK")
    for item in resp.get("Items", []):
        sk = item.get("SK", "")
        if sk.startswith("TICKER#"):
            owned.add(sk.removeprefix("TICKER#"))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            ProjectionExpression="SK",
        )
        for item in resp.get("Items", []):
            sk = item.get("SK", "")
            if sk.startswith("TICKER#"):
                owned.add(sk.removeprefix("TICKER#"))
    return owned


def _get_active_subscribers() -> list[dict]:
    table = dynamodb.Table(SUBSCRIBERS_TABLE)
    resp = table.query(
        IndexName="StatusIndex",
        KeyConditionExpression=Key("status").eq("ACTIVE"),
    )
    return resp.get("Items", [])


def _build_weekly_digest(positions: list[dict], owned_tickers: set[str], week_str: str) -> str:
    """
    Build the weekly digest text.

    OPEN section: group by ticker, sorted with owned tickers first then alpha.
    CLOSE ALERTS section: positions that went CLOSED this week, owned tickers only.
    """
    open_by_ticker: dict[str, list[dict]] = defaultdict(list)
    close_alerts: dict[str, list[dict]] = defaultdict(list)

    for pos in positions:
        ticker = pos.get("ticker", "?").upper()
        status = pos.get("open_status", "OPEN")
        if status == "OPEN":
            open_by_ticker[ticker].append(pos)
        elif status == "CLOSED":
            close_alerts[ticker].append(pos)

    lines = [f"[INBOX] Weekly Summary — {week_str}"]

    # ── Open positions ──────────────────────────────────────────────────────
    if open_by_ticker:
        lines.append("")
        lines.append("OPEN RECOMMENDATIONS:")

        # Owned tickers first, then the rest alphabetically
        sorted_tickers = sorted(
            open_by_ticker.keys(),
            key=lambda t: (0 if t in owned_tickers else 1, t),
        )

        for ticker in sorted_tickers:
            recs = open_by_ticker[ticker]
            owned_marker = "*" if ticker in owned_tickers else " "

            # Build per-source summary: "Source (confidence, since YYYY-MM-DD)"
            source_parts = []
            for r in sorted(recs, key=lambda x: x.get("first_rec_date", "")):
                source = r.get("source", "?")
                confidence = r.get("confidence", "MED")[:3].upper()
                first_date = r.get("first_rec_date", "?")
                action = r.get("action", "BUY")
                source_parts.append(f"{source}/{action}/{confidence} since {first_date}")

            sources_str = " | ".join(source_parts)
            lines.append(f"{owned_marker}{ticker}: {sources_str}")
    else:
        lines.append("No open recommendations this week.")

    # ── Close alerts (owned positions only) ────────────────────────────────
    owned_close_alerts = {t: recs for t, recs in close_alerts.items() if t in owned_tickers}
    if owned_close_alerts:
        lines.append("")
        lines.append("CLOSE ALERTS (owned positions):")
        for ticker in sorted(owned_close_alerts.keys()):
            for r in owned_close_alerts[ticker]:
                source = r.get("source", "?")
                close_action = r.get("close_action", r.get("action", "?"))
                close_date = r.get("close_date", "?")
                first_date = r.get("first_rec_date", "?")
                lines.append(
                    f"*{ticker} {close_action} by {source} on {close_date} (rec'd since {first_date})"
                )

    # ── Footer ──────────────────────────────────────────────────────────────
    total_open = sum(len(v) for v in open_by_ticker.values())
    total_tickers = len(open_by_ticker)
    lines.append("")
    lines.append(f"Total: {total_open} open recs across {total_tickers} tickers. * = owned position.")

    return "\n".join(lines)


def _chunk_message(message: str, chunk_size: int = SMS_CHUNK_SIZE) -> list[str]:
    """Split a long message into SMS-friendly chunks, breaking on newlines where possible."""
    if len(message) <= chunk_size:
        return [message]

    chunks = []
    remaining = message
    part = 1

    while remaining:
        header = f"[{part}] "
        available = chunk_size - len(header)

        if len(remaining) <= available:
            chunks.append(header + remaining)
            break

        # Try to break on a newline within the available window
        split_at = remaining[:available].rfind("\n")
        if split_at <= 0:
            split_at = available

        chunks.append(header + remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
        part += 1

    return chunks


def _send_sms(phone_number: str, message: str) -> None:
    sns.publish(
        PhoneNumber=phone_number,
        Message=message,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {
                "DataType": "String",
                "StringValue": "Transactional",
            }
        },
    )


def lambda_handler(event: dict, context) -> None:
    week_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("Running weekly digest for week of %s", week_str)

    positions = _scan_open_positions()
    logger.info("Found %d open-position rows", len(positions))

    owned_tickers = _get_owned_tickers()
    logger.info("Owned tickers: %s", owned_tickers)

    subscribers = _get_active_subscribers()
    if not subscribers:
        logger.info("No active subscribers — weekly digest not sent.")
        return

    digest = _build_weekly_digest(positions, owned_tickers, week_str)
    chunks = _chunk_message(digest)
    logger.info("Weekly digest: %d chunks, %d chars total", len(chunks), len(digest))

    for subscriber in subscribers:
        phone = subscriber["PK"].removeprefix("SUBSCRIBER#")
        try:
            for chunk in chunks:
                _send_sms(phone, chunk)
            logger.info("Weekly digest sent to %s (%d chunks)", phone, len(chunks))
        except Exception as exc:
            logger.error("Failed to send weekly digest to %s: %s", phone, exc)

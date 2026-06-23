"""
weekly_digest/handler.py

EventBridge-triggered Lambda. Runs weekly (default: Sundays 7 PM UTC).
Scans the OpenPositions table to build a comprehensive weekly summary:
  - All currently OPEN recommendations grouped by ticker, showing every
    source with confidence level and first recommendation date.
  - Recently CLOSED positions (within last 7 days) flagged as "CLOSE ALERT".

Sends to every active delivery channel (Users table ActiveChannels GSI). The
long digest is chunked for SMS; Pushover receives it whole.
"""

import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3

import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

region = os.environ["AWS_REGION_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=region)
sns = boto3.client("sns", region_name=region)

OPEN_POSITIONS_TABLE = os.environ["OPEN_POSITIONS_TABLE"]
USERS_TABLE = os.environ["USERS_TABLE"]
ORIGINATION_NUMBER = os.environ.get("ORIGINATION_NUMBER", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

# Max SMS length per segment × 2 segments; split digest into chunks if needed
SMS_CHUNK_SIZE = 320


def _scan_open_positions() -> list[dict]:
    """Full table scan — OpenPositions stays small (one row per ticker+source)."""
    table = dynamodb.Table(OPEN_POSITIONS_TABLE)
    items = []
    resp = table.scan()
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"])
        items.extend(resp.get("Items", []))
    return items


def _build_weekly_digest(positions: list[dict], week_str: str) -> str:
    """
    Build the weekly digest text.

    OPEN section: group by ticker alphabetically.
    CLOSE ALERTS section: all positions that went CLOSED this week.
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

        sorted_tickers = sorted(open_by_ticker.keys())

        for ticker in sorted_tickers:
            recs = open_by_ticker[ticker]
            # Build per-source summary: "Source (confidence, since YYYY-MM-DD)"
            source_parts = []
            for r in sorted(recs, key=lambda x: x.get("first_rec_date", "")):
                source = r.get("source", "?")
                confidence = r.get("confidence", "MED")[:3].upper()
                first_date = r.get("first_rec_date", "?")
                action = r.get("action", "BUY")
                source_parts.append(f"{source}/{action}/{confidence} since {first_date}")

            sources_str = " | ".join(source_parts)
            lines.append(f"{ticker}: {sources_str}")
    else:
        lines.append("No open recommendations this week.")

    # ── Close alerts ───────────────────────────────────────────────────────
    if close_alerts:
        lines.append("")
        lines.append("CLOSE ALERTS:")
        for ticker in sorted(close_alerts.keys()):
            for r in close_alerts[ticker]:
                source = r.get("source", "?")
                close_action = r.get("close_action", r.get("action", "?"))
                close_date = r.get("close_date", "?")
                first_date = r.get("first_rec_date", "?")
                lines.append(
                    f"{ticker} {close_action} by {source} on {close_date} (rec'd since {first_date})"
                )

    # ── Footer ──────────────────────────────────────────────────────────────
    total_open = sum(len(v) for v in open_by_ticker.values())
    total_tickers = len(open_by_ticker)
    lines.append("")
    lines.append(f"Total: {total_open} open recs across {total_tickers} tickers.")

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


def lambda_handler(event: dict, context) -> None:
    week_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logger.info("Running weekly digest for week of %s", week_str)

    positions = _scan_open_positions()
    logger.info("Found %d open-position rows", len(positions))

    channels = notify.get_active_channels(dynamodb.Table(USERS_TABLE))
    if not channels:
        logger.info("No active channels — weekly digest not sent.")
        return

    digest = _build_weekly_digest(positions, week_str)
    chunks = _chunk_message(digest)
    title = f"[INBOX] Weekly Summary — {week_str}"
    logger.info("Weekly digest: %d chunks, %d chars total", len(chunks), len(digest))

    for ch in channels:
        ctype = ch.get("channel_type", "")
        value = ch.get("value", "")
        if not value:
            continue
        try:
            if ctype == "SMS":
                for chunk in chunks:
                    notify.send_sms(sns, value, chunk, ORIGINATION_NUMBER)
            elif ctype == "PUSHOVER" and PUSHOVER_API_TOKEN:
                notify.send_pushover(PUSHOVER_API_TOKEN, value, title, digest)
        except Exception as exc:
            logger.error("Weekly delivery failed type=%s value=%s: %s", ctype, value, exc)

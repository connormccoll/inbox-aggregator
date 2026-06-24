"""
promptadmin.py

Prompt-tuning operations for the extraction prompt, backed by the prompts
DynamoDB table (versioned, human-approved). Used by the graphql Lambda.

Table layout (PK = "PROMPT#extraction"):
  SK = CURRENT          -> {version, body}            (read by email_processor)
  SK = V#000001 ...     -> {version, body, reasoning, note, created_at}  (history)
  SK = PENDING          -> a drafted suggestion awaiting approval
"""

import difflib
import json
import logging
import re
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from prompt_base import BASE_EXTRACTION_PROMPT

logger = logging.getLogger()

PK = "PROMPT#extraction"
REQUIRED = ("{subject}", "{sender}", "{email_date}", "{body}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid(template: str) -> bool:
    if not template or not all(p in template for p in REQUIRED):
        return False
    try:
        template.format(subject="x", sender="x", email_date="x", body="x")
        return True
    except (KeyError, IndexError, ValueError):
        return False


def _current(table) -> tuple[int, str]:
    item = table.get_item(Key={"PK": PK, "SK": "CURRENT"}).get("Item")
    if item and int(item.get("version", 0) or 0) >= 1 and item.get("body"):
        return int(item["version"]), item["body"]
    # Version 0 tracks the code base prompt — no DB row needed until a human
    # approves a customized version (which writes version >= 1).
    return 0, BASE_EXTRACTION_PROMPT


def _parse_json(text: str) -> dict:
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
    return json.loads(text)


def get_state(dynamodb, prompts_table: str) -> dict:
    table = dynamodb.Table(prompts_table)
    version, body = _current(table)
    pend = table.get_item(Key={"PK": PK, "SK": "PENDING"}).get("Item")
    pending = None
    if pend:
        pending = {
            "body": pend.get("body"),
            "reasoning": pend.get("reasoning"),
            "changes": pend.get("changes", []),
            "diff": pend.get("diff"),
            "based_on": int(pend.get("based_on", 0)),
            "created_at": pend.get("created_at"),
        }
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(PK) & Key("SK").begins_with("V#"),
        ScanIndexForward=False, Limit=20,
    )
    history = [{
        "version": int(i.get("version", 0)),
        "note": i.get("note", ""),
        "reasoning": i.get("reasoning", ""),
        "created_at": i.get("created_at"),
    } for i in resp.get("Items", [])]
    return {"current_version": version, "current_body": body, "pending": pending, "history": history}


def _new_feedback(dynamodb, feedback_table: str, limit: int = 40) -> list[dict]:
    table = dynamodb.Table(feedback_table)
    resp = table.query(
        IndexName="FeedbackStatus",
        KeyConditionExpression=Key("status").eq("NEW"),
        ScanIndexForward=False, Limit=limit,
    )
    return resp.get("Items", [])


def _meta_prompt(current: str, examples: list[dict]) -> str:
    lines = []
    for i, e in enumerate(examples, 1):
        lines.append(
            f"{i}. ticker={e.get('ticker')} model_action={e.get('model_action')} "
            f"reason={e.get('reason')} note={e.get('note')!r} "
            f"source={e.get('source')} subject={e.get('email_subject')!r}"
        )
    feedback_block = "\n".join(lines)
    return (
        "You maintain a prompt that instructs an LLM to extract stock recommendations "
        "from financial newsletter emails as JSON. A user flagged the extractions below "
        "as wrong. Propose a MINIMAL revision of the prompt that fixes these cases without "
        "regressing other behavior.\n\n"
        "HARD CONSTRAINTS — the revised prompt MUST:\n"
        "- keep the placeholders {subject}, {sender}, {email_date}, {body} exactly once each\n"
        "- keep all literal JSON braces escaped as {{ and }} (doubled)\n"
        "- keep the same JSON output schema\n"
        "- change as little as possible; prefer adding/clarifying a rule over rewriting\n\n"
        "Return ONLY a JSON object (no markdown) with keys:\n"
        '  "revised_prompt": the full revised prompt string,\n'
        '  "reasoning": 1-3 sentences on what you changed and why,\n'
        '  "changes": array of short bullet strings.\n\n'
        f"=== CURRENT PROMPT ===\n{current}\n\n"
        f"=== FLAGGED EXTRACTIONS ===\n{feedback_block}\n"
    )


def suggest(dynamodb, bedrock, model_id: str, prompts_table: str, feedback_table: str) -> dict:
    table = dynamodb.Table(prompts_table)
    _version, current = _current(table)
    feedback = _new_feedback(dynamodb, feedback_table)
    if not feedback:
        return {"ok": False, "error": "No new feedback to learn from yet."}

    examples = [{
        "ticker": f.get("ticker"), "model_action": f.get("model_action"),
        "reason": f.get("reason"), "note": f.get("note"),
        "email_subject": f.get("email_subject"), "source": f.get("source"),
    } for f in feedback]

    try:
        resp = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": _meta_prompt(current, examples)}]}],
            inferenceConfig={"maxTokens": 4096},
        )
        text = resp["output"]["message"]["content"][0]["text"].strip()
        data = _parse_json(text)
    except Exception as exc:
        logger.exception("suggest failed: %s", exc)
        return {"ok": False, "error": "Could not draft a suggestion. Try again."}

    revised = data.get("revised_prompt", "")
    if not _valid(revised):
        return {"ok": False, "error": "Drafted prompt was invalid (placeholders/braces broken) — discarded."}

    diff = "\n".join(difflib.unified_diff(
        current.splitlines(), revised.splitlines(),
        fromfile="current", tofile="proposed", lineterm="",
    ))
    table.put_item(Item={
        "PK": PK, "SK": "PENDING", "body": revised,
        "reasoning": str(data.get("reasoning", ""))[:2000],
        "changes": [str(c)[:300] for c in (data.get("changes") or [])][:20],
        "diff": diff[:12000], "based_on": len(feedback),
        "feedback_keys": [f["SK"] for f in feedback], "created_at": _now(),
    })
    return {"ok": True, "pending": {
        "body": revised, "reasoning": data.get("reasoning", ""),
        "changes": data.get("changes", []), "diff": diff, "based_on": len(feedback),
    }}


def approve(dynamodb, prompts_table: str, feedback_table: str) -> dict:
    table = dynamodb.Table(prompts_table)
    pend = table.get_item(Key={"PK": PK, "SK": "PENDING"}).get("Item")
    if not pend:
        return {"ok": False, "error": "No pending suggestion to approve."}
    if not _valid(pend.get("body", "")):
        return {"ok": False, "error": "Pending prompt is invalid — discard it."}
    version, _ = _current(table)
    nv = version + 1
    table.put_item(Item={
        "PK": PK, "SK": f"V#{nv:06d}", "version": nv, "body": pend["body"],
        "reasoning": pend.get("reasoning", ""), "note": "approved from feedback", "created_at": _now(),
    })
    table.put_item(Item={"PK": PK, "SK": "CURRENT", "version": nv, "body": pend["body"], "updated_at": _now()})
    ft = dynamodb.Table(feedback_table)
    for sk in pend.get("feedback_keys", []):
        try:
            ft.update_item(
                Key={"PK": "FEEDBACK", "SK": sk},
                UpdateExpression="SET #s = :r",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":r": "REVIEWED"},
            )
        except Exception:
            pass
    table.delete_item(Key={"PK": PK, "SK": "PENDING"})
    return {"ok": True, "current_version": nv}


def discard(dynamodb, prompts_table: str) -> dict:
    dynamodb.Table(prompts_table).delete_item(Key={"PK": PK, "SK": "PENDING"})
    return {"ok": True}


def rollback(dynamodb, prompts_table: str, version: int) -> dict:
    table = dynamodb.Table(prompts_table)
    item = table.get_item(Key={"PK": PK, "SK": f"V#{int(version):06d}"}).get("Item")
    if not item or not item.get("body"):
        return {"ok": False, "error": f"Version {version} not found."}
    table.put_item(Item={"PK": PK, "SK": "CURRENT", "version": int(version),
                         "body": item["body"], "updated_at": _now()})
    return {"ok": True, "current_version": int(version)}

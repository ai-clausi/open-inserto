from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    logger.info("Received eBay account deletion request: method=%s", method)

    if method == "GET":
        return _handle_challenge(event)

    if method == "POST":
        logger.info("Received account deletion notification: %s", _redact_body(event.get("body")))
        return _json_response(200, {"status": "ok"})

    return _json_response(405, {"error": "method_not_allowed"})


def _handle_challenge(event: dict[str, Any]) -> dict[str, Any]:
    challenge_code = str((event.get("queryStringParameters") or {}).get("challenge_code") or "").strip()
    verification_token = os.environ["VERIFICATION_TOKEN"]
    endpoint_url = _endpoint_url_from_event(event)

    if not challenge_code:
        return _json_response(400, {"error": "missing_challenge_code"})

    challenge_response = hashlib.sha256(
        f"{challenge_code}{verification_token}{endpoint_url}".encode("utf-8")
    ).hexdigest()
    return _json_response(200, {"challengeResponse": challenge_response})


def _endpoint_url_from_event(event: dict[str, Any]) -> str:
    headers = {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}
    host = headers.get("host") or str(event.get("requestContext", {}).get("domainName") or "")
    raw_path = str(event.get("rawPath") or "/")

    if not host:
        raise RuntimeError("Unable to determine endpoint host from Lambda Function URL event")
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    return f"https://{host}{raw_path}"


def _json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _redact_body(body: object) -> str:
    if not isinstance(body, str) or not body:
        return ""
    return body[:4000]

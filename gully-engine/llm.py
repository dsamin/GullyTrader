"""Thin OpenRouter chat-completions client.

Mirrors the KalshiTrader engine's LLM access pattern: per-agent provider/model
config from env, JSON-mode requests for structured outputs, and a write to the
`agent_logs` table for every call so we have a full audit trail.

Stays defensive: network errors, non-2xx responses, and malformed JSON all log
and return a fallback rather than raising into the orchestrator loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import requests

import database
from settings import settings


log = logging.getLogger(__name__)


@dataclass
class LlmResponse:
    content: str
    parsed_json: object | None
    model: str
    latency_ms: int
    raw: dict


def chat_json(
    *,
    agent: str,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    log_ticker: str | None = None,
) -> LlmResponse | None:
    """Call OpenRouter chat-completions with JSON mode; persist to agent_logs.

    Returns None on any failure that would break the caller. The orchestrator
    loops must keep running through transient LLM blips.
    """
    if not settings.openrouter_api_key:
        log.warning("llm.chat_json[%s]: OPENROUTER_API_KEY missing — skipping call", agent)
        return None

    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/dsamin/GullyTrader",
        "X-Title": "GullyTrader",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=body, timeout=45)
    except requests.RequestException as e:
        log.error("llm.chat_json[%s] request failed: %s", agent, e)
        return None
    latency_ms = int((time.time() - t0) * 1000)

    if not r.ok:
        log.error("llm.chat_json[%s] %s: %s", agent, r.status_code, r.text[:200])
        return None

    try:
        payload = r.json()
    except ValueError:
        log.error("llm.chat_json[%s]: non-JSON response", agent)
        return None

    try:
        content = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        log.error("llm.chat_json[%s]: unexpected payload shape %s", agent, payload)
        return None

    parsed: object | None = None
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        log.warning("llm.chat_json[%s]: response not valid JSON, content=%s", agent, content[:200])

    _persist_agent_log(
        agent=agent, ticker=log_ticker, decision=_decision_summary(parsed),
        confidence=_confidence(parsed), reasoning=content[:4000],
        model=model, latency_ms=latency_ms,
    )

    return LlmResponse(content=content, parsed_json=parsed,
                       model=model, latency_ms=latency_ms, raw=payload)


def _persist_agent_log(*, agent, ticker, decision, confidence, reasoning, model, latency_ms) -> None:
    try:
        with database.write_conn() as conn:
            conn.execute(
                """INSERT INTO agent_logs
                   (agent, ticker, decision, confidence, reasoning, model, latency_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent, ticker, decision, confidence, reasoning, model, latency_ms, int(time.time())),
            )
    except Exception:  # noqa: BLE001 — DB write failure must not crash the agent
        log.exception("llm: failed to write agent_log for %s", agent)


def _decision_summary(parsed) -> str | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("decision", "action", "verdict"):
        if key in parsed:
            return str(parsed[key])[:200]
    return None


def _confidence(parsed) -> float | None:
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get("confidence")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None

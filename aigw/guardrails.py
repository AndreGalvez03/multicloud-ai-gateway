"""Small, explicit guardrails.

This is not a substitute for a dedicated safety model. It is the platform
control we can explain and test: redact common PII before a prompt leaves the
process, and refuse a short list of blocked topics per team.

Raw prompts are never written to logs. Callers log the redaction count only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
PHONE = re.compile(r"\b(?:\+\d{1,3}[\s.-])?(?:\(\d{3}\)|\d{3})[\s.-]\d{3}[\s.-]\d{4}\b")


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact_text(text: str) -> Redaction:
    counts = {"email": 0, "phone": 0, "ssn": 0, "card": 0}

    def sub(pattern: re.Pattern[str], label: str, value: str) -> str:
        def repl(_match: re.Match[str]) -> str:
            counts[label] += 1
            return f"[REDACTED_{label.upper()}]"

        return pattern.sub(repl, value)

    # Cards first so a card number is not partially eaten by the phone pattern.
    cleaned = sub(CARD, "card", text)
    cleaned = sub(SSN, "ssn", cleaned)
    cleaned = sub(EMAIL, "email", cleaned)
    cleaned = sub(PHONE, "phone", cleaned)
    return Redaction(cleaned, counts)


def redact_messages(messages: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    redacted: list[dict[str, str]] = []
    total = 0
    for message in messages:
        result = redact_text(message.get("content", ""))
        total += result.total
        redacted.append({"role": message.get("role", "user"), "content": result.text})
    return redacted, total


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def find_blocked_topic(messages: list[dict[str, str]], topics: list[str]) -> str | None:
    """Match a topic as a whole phrase, not as a substring of another word."""
    if not topics:
        return None
    haystack = f" {_normalize(chr(10).join(message.get('content', '') for message in messages))} "
    for topic in topics:
        needle = _normalize(topic)
        if needle and f" {needle} " in haystack:
            return topic
    return None


def check_output(text: str, topics: list[str]) -> tuple[str, str | None]:
    """Redact model output and refuse a blocked topic.

    Replace this function to call Bedrock ApplyGuardrail or Azure Content
    Safety. The platform only depends on the (text, topics) -> (text, topic) shape.
    """
    redacted = redact_text(text)
    blocked = find_blocked_topic([{"role": "assistant", "content": text}], topics)
    return redacted.text, blocked

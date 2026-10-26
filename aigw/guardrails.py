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


def find_blocked_topic(messages: list[dict[str, str]], topics: list[str]) -> str | None:
    if not topics:
        return None
    haystack = "\n".join(message.get("content", "") for message in messages).lower()
    for topic in topics:
        needle = topic.strip().lower()
        if needle and needle in haystack:
            return topic
    return None

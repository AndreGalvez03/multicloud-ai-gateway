"""Rough token estimates used only before the provider returns usage."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def parse_usage(body: dict[str, object], prompt_text: str, completion_text: str) -> tuple[int, int, int]:
    usage = body.get("usage")
    usage_dict = usage if isinstance(usage, dict) else {}
    prompt_tokens = usage_dict.get("prompt_tokens")
    completion_tokens = usage_dict.get("completion_tokens")
    input_tokens = int(prompt_tokens) if isinstance(prompt_tokens, int) else estimate_tokens(prompt_text)
    output_tokens = (
        int(completion_tokens) if isinstance(completion_tokens, int) else estimate_tokens(completion_text)
    )
    details = usage_dict.get("prompt_tokens_details")
    cached = 0
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int):
        cached = int(details["cached_tokens"])
    cached = max(0, min(cached, input_tokens))
    return input_tokens, output_tokens, cached


def completion_text(body: dict[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return str(message["content"])
    return ""

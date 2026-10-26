from aigw.guardrails import find_blocked_topic, redact_text


def test_redacts_common_pii_and_leaves_ordinary_numbers() -> None:
    text = (
        "mail ada@example.com, call +1 415 555 0134, "
        "ssn 123-45-6789, card 4242 4242 4242 4242. "
        "the year 2026 and budget 12000 stay."
    )
    result = redact_text(text)
    assert "ada@example.com" not in result.text
    assert "415" not in result.text
    assert "123-45-6789" not in result.text
    assert "4242" not in result.text
    assert "[REDACTED_EMAIL]" in result.text
    assert "[REDACTED_PHONE]" in result.text
    assert "[REDACTED_SSN]" in result.text
    assert "[REDACTED_CARD]" in result.text
    assert "2026" in result.text
    assert "12000" in result.text
    assert result.total == 4


def test_blocked_topic_is_case_insensitive() -> None:
    messages = [{"role": "user", "content": "What is Project-Northstar?"}]
    assert find_blocked_topic(messages, ["project-northstar"]) == "project-northstar"
    assert find_blocked_topic(messages, ["other"]) is None
    assert find_blocked_topic(messages, []) is None

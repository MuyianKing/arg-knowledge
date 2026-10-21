from __future__ import annotations

import re

# Order matters: ID (18 chars) before bank card (16-19 digits).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[ID]"),
    (re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "[BANK_CARD]"),
]


def redact_text(text: str) -> str:
    """Mask phone numbers, Chinese ID numbers, and bank card numbers.

    Used before sending content to a third-party LLM API and before logging.
    """

    redacted = text
    for pattern, replacement in _PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

"""JSON logs for CloudWatch metric filters and local debugging.

Prompt bodies are not log fields. Do not add them.
"""

from __future__ import annotations

import json
import logging
from typing import Any

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _CONFIGURED = True


def log_event(event: str, **fields: Any) -> None:
    configure_logging()
    payload = {"event": event, **fields}
    logging.getLogger("aigw").info(json.dumps(payload, default=str, separators=(",", ":")))

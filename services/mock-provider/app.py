"""OpenAI-compatible mock used when no cloud account is available.

Keep hash_embedding identical to aigw.rag.hash_embedding so local RAG retrieves
the same neighbors the platform tests do.

POST /_admin/mode {"match": "bedrock", "mode": "ok"|"error"|"throttle"|"slow"}
lets a runbook simulate a provider failure without touching a real API.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIM = 64
TOKEN = re.compile(r"[a-z0-9]+")
MODES = {"ok", "error", "throttle", "slow"}


def hash_embedding(text: str, dim: int = DIM) -> list[float]:
    if dim <= 0:
        raise ValueError("dimension must be positive")
    vector = [0.0] * dim
    tokens = TOKEN.findall(text.lower()) or ["empty"]
    for token in tokens:
        digest = hashlib.sha256(token.encode()).digest()
        bucket = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.modes: dict[str, str] = {}
        self.last: dict[str, object] | None = None

    def mode_for(self, model: str) -> str:
        with self.lock:
            for key, mode in self.modes.items():
                if key and key in model:
                    return mode
        return "ok"

    def set_mode(self, match: str, mode: str) -> None:
        with self.lock:
            if mode == "ok":
                self.modes.pop(match, None)
            else:
                self.modes[match] = mode

    def remember(self, payload: dict[str, object]) -> None:
        with self.lock:
            self.last = payload


STATE = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "aigw-mock/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"mock {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/healthz", "/health"}:
            self._send(200, {"status": "ok"})
            return
        if self.path == "/_debug/last":
            self._send(200, STATE.last or {})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "invalid json"}})
            return
        if self.path == "/_admin/mode":
            match = str(body.get("match", ""))
            mode = str(body.get("mode", "ok"))
            if not match or mode not in MODES:
                self._send(400, {"error": {"message": "match and mode are required"}})
                return
            STATE.set_mode(match, mode)
            self._send(200, {"match": match, "mode": mode})
            return
        if self.path == "/v1/chat/completions":
            self._chat(body)
            return
        if self.path == "/v1/embeddings":
            self._embed(body)
            return
        self._send(404, {"error": {"message": "not found"}})

    def _chat(self, body: dict[str, object]) -> None:
        model = str(body.get("model", "mock"))
        STATE.remember({"path": "/v1/chat/completions", "model": model, "body": body})
        mode = STATE.mode_for(model)
        if mode == "throttle":
            self._send(
                429,
                {"error": {"message": f"{model} is throttling", "type": "rate_limit"}},
                {"retry-after": "2"},
            )
            return
        if mode == "error":
            self._send(503, {"error": {"message": f"{model} is unavailable", "type": "upstream"}})
            return
        if mode == "slow":
            import time

            time.sleep(2)
        messages = body.get("messages")
        user = ""
        if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
            user = str(messages[-1].get("content", ""))
        reply = f"[{model}] {user[:400]}"
        prompt_tokens = max(1, len(user) // 4)
        completion_tokens = max(1, len(reply) // 4)
        system = ""
        if isinstance(messages, list):
            system = "\n".join(
                str(item.get("content", ""))
                for item in messages
                if isinstance(item, dict) and item.get("role") == "system"
            )
        cached = prompt_tokens // 2 if len(system) > 200 else 0
        self._send(
            200,
            {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "prompt_tokens_details": {"cached_tokens": cached},
                },
            },
        )

    def _embed(self, body: dict[str, object]) -> None:
        model = str(body.get("model", "embed"))
        raw_input = body.get("input", "")
        texts = raw_input if isinstance(raw_input, list) else [str(raw_input)]
        STATE.remember({"path": "/v1/embeddings", "model": model, "count": len(texts)})
        data = [
            {"object": "embedding", "index": index, "embedding": hash_embedding(str(text))}
            for index, text in enumerate(texts)
        ]
        prompt_tokens = sum(max(1, len(str(text)) // 4) for text in texts)
        self._send(
            200,
            {
                "object": "list",
                "model": model,
                "data": data,
                "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
            },
        )

    def _send(self, status: int, payload: dict[str, object], headers: dict[str, str] | None = None) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("mock provider listening on :8080")
    server.serve_forever()


if __name__ == "__main__":
    main()

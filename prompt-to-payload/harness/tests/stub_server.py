"""Minimal OpenAI-compatible server with no model behind it.

Scripted /v1/chat/completions and /v1/embeddings. Lets the egress test exercise
the real HTTP path, and lets you check your install before weights finish
downloading.

Loopback only. Test fixture, not a service.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# Scripted so a run is deterministic: first a tool call, then a conclusion.
SCRIPT = [
    {
        "content": "",
        "tool_calls": [{
            "id": "call_0",
            "type": "function",
            "function": {"name": "binary_overview",
                         "arguments": json.dumps({"path": "PLACEHOLDER"})},
        }],
    },
    {
        "content": "Stub model: observed the tool output and stopped.",
        "tool_calls": [],
    },
]


class Handler(BaseHTTPRequestHandler):
    turn = 0

    def log_message(self, *args):  # keep test output clean
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")

        if self.path.endswith("/chat/completions"):
            # Pull the target path out of the conversation the way a real
            # model would, not from a field the harness has no
            # reason to send.
            binary = ""
            for message in reversed(request.get("messages") or []):
                if message.get("role") != "user":
                    continue
                match = re.search(r"(/[^\s]+/[^\s]+)", message.get("content") or "")
                if match:
                    binary = match.group(1).rstrip(".,")
                    break
            index = min(Handler.turn, len(SCRIPT) - 1)
            message = json.loads(json.dumps(SCRIPT[index]))
            Handler.turn += 1

            for call in message.get("tool_calls") or []:
                call["function"]["arguments"] = call["function"][
                    "arguments"].replace("PLACEHOLDER", binary)

            self._json({
                "id": "stub",
                "object": "chat.completion",
                "model": request.get("model", "stub"),
                "choices": [{"index": 0, "message": message,
                             "finish_reason": "stop"}],
            })
            return

        if self.path.endswith("/embeddings"):
            texts = request.get("input") or []
            if isinstance(texts, str):
                texts = [texts]
            # Deterministic pseudo-embeddings: same text always same vector,
            # so retrieval ordering is reproducible across runs.
            data = []
            for index, text in enumerate(texts):
                digest = hashlib.sha256(text.encode()).digest()
                vector = [((b / 255.0) - 0.5) for b in digest[:32]]
                data.append({"object": "embedding", "index": index,
                             "embedding": vector})
            self._json({"object": "list", "data": data,
                        "model": request.get("model", "stub-embed")})
            return

        self._json({"error": f"unhandled path {self.path}"}, status=404)


def serve(port: int = 11455) -> None:
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"stub model server on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 11455)

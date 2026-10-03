"""Append-only record of what the harness did.

One JSON object per line: every model turn, tool call and approval decision.
An engagement needs an auditable record of what touched the target, and you
need to be able to see where the model went wrong afterwards.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


class Transcript:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex[:12]
        self._write("run_start", {"run_id": self.run_id, "version": _version()})

    def _write(self, kind: str, data: dict[str, Any]) -> None:
        record = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "run": self.run_id,
            "kind": kind,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def model_call(self, role: str, model: str, messages: list[dict]) -> None:
        self._write("model_call", {
            "role": role,
            "model": model,
            "messages": len(messages),
        })

    def model_reply(self, role: str, content: str, tool_calls: list) -> None:
        self._write("model_reply", {
            "role": role,
            "content": content,
            "tool_calls": [c.get("name") for c in tool_calls],
        })

    def tool_call(self, name: str, args: dict, risk: str) -> None:
        self._write("tool_call", {"tool": name, "args": args, "risk": risk})

    def tool_result(self, name: str, ok: bool, output: str) -> None:
        self._write("tool_result", {
            "tool": name,
            "ok": ok,
            # Truncated in the record; full output stays in the tool's own
            # artifact directory so transcripts remain readable.
            "output": output[:4000],
            "truncated": len(output) > 4000,
        })

    def approval(self, name: str, granted: bool, reason: str = "") -> None:
        self._write("approval", {"tool": name, "granted": granted, "reason": reason})

    def note(self, message: str, **extra: Any) -> None:
        self._write("note", {"message": message, **extra})


def _version() -> str:
    from payload import __version__
    return __version__

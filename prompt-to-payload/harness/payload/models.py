"""Model client and role router.

Speaks the OpenAI-compatible chat and embeddings API, which Ollama,
llama.cpp's server, LM Studio and mlx_lm.server all expose. Switching runtime
is a config change.

urllib instead of a real HTTP client, so there is nothing to install on an
air-gapped box.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from payload import egress
from payload.config import Config, RoleConfig


class ModelError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    content: str
    tool_calls: list[ToolCall]
    raw: dict[str, Any]


def _post(url: str, payload: dict, timeout: int) -> dict:
    egress.check(url)

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            # Some local servers reject a missing auth header even though they
            # ignore the value. Harmless, and never leaves this machine.
            "Authorization": "Bearer local",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise ModelError(f"{url} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ModelError(
            f"cannot reach {url}: {exc.reason}. Is the model server running? "
            f"Check `scripts/doctor.sh`."
        ) from exc


def _parse_tool_calls(message: dict) -> list[ToolCall]:
    """Extract tool calls, tolerating the variations local servers emit.

    Arguments arrive as a JSON string per the OpenAI schema, but several local
    runtimes send an object instead, and a few send malformed JSON when the
    model's output was truncated. A bad call is surfaced to the model as an
    error instead of crashing the run, so it gets a chance to retry.
    """
    calls: list[ToolCall] = []

    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function", {})
        name = function.get("name", "")
        arguments = function.get("arguments", {})

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {"__malformed__": arguments}

        if not isinstance(arguments, dict):
            arguments = {"__malformed__": repr(arguments)}

        calls.append(ToolCall(
            id=raw.get("id") or f"call_{index}",
            name=name,
            arguments=arguments,
        ))

    return calls


class ModelClient:
    def __init__(self, config: Config) -> None:
        self.config = config

    def chat(
        self,
        role: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        retries: int = 2,
    ) -> Reply:
        rc: RoleConfig = self.config.role_or_fallback(role)

        payload: dict[str, Any] = {
            "model": rc.model,
            "messages": messages,
            "temperature": rc.temperature,
            "max_tokens": rc.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = rc.endpoint.rstrip("/") + "/chat/completions"

        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                data = _post(url, payload, rc.timeout)
                break
            except ModelError as exc:
                last = exc
                # A cold model refuses connections while it pages in.
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        else:  # pragma: no cover - loop always breaks or raises
            raise ModelError(str(last))

        choices = data.get("choices") or []
        if not choices:
            raise ModelError(f"no choices in response from {rc.model}: {data}")

        message = choices[0].get("message") or {}
        return Reply(
            content=message.get("content") or "",
            tool_calls=_parse_tool_calls(message),
            raw=data,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        rc = self.config.role_or_fallback("embed")
        url = rc.endpoint.rstrip("/") + "/embeddings"

        data = _post(url, {"model": rc.model, "input": texts}, rc.timeout)
        items = data.get("data") or []
        if len(items) != len(texts):
            raise ModelError(
                f"asked {rc.model} for {len(texts)} embeddings, got {len(items)}"
            )

        # Servers do not reliably return these in request order.
        items.sort(key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in items]

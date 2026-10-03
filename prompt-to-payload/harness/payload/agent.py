"""The agent loop.

prompt -> model -> tool calls -> observations -> repeat, until the model stops
asking for tools or the step budget runs out.

Owns orchestration and nothing else. It does not know what any tool does or
which model is answering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from payload.approval import Approver
from payload.config import Config
from payload.models import ModelClient, ToolCall
from payload.tools.base import Registry, ToolError, validate
from payload.transcript import Transcript


@dataclass
class Step:
    index: int
    content: str
    calls: list[str] = field(default_factory=list)


@dataclass
class Result:
    answer: str
    steps: list[Step]
    stopped_early: bool = False
    # Tools the model asked for and was refused. Worth surfacing: a model that
    # keeps reaching for a blocked capability is telling you its plan.
    denied: list[str] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        config: Config,
        registry: Registry,
        client: ModelClient,
        transcript: Transcript,
        approver: Approver,
        role: str = "plan",
    ) -> None:
        self.config = config
        self.registry = registry
        self.client = client
        self.transcript = transcript
        self.approver = approver
        self.role = role

    def run(self, task: str, system: str) -> Result:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        tools = self.registry.schemas()
        steps: list[Step] = []
        denied: list[str] = []

        for index in range(1, self.config.max_steps + 1):
            self.transcript.model_call(self.role, "-", messages)
            reply = self.client.chat(self.role, messages, tools)
            self.transcript.model_reply(
                self.role, reply.content,
                [{"name": c.name} for c in reply.tool_calls],
            )

            step = Step(index=index, content=reply.content,
                        calls=[c.name for c in reply.tool_calls])
            steps.append(step)

            if not reply.tool_calls:
                return Result(answer=reply.content, steps=steps, denied=denied)

            # Echo the assistant turn back, including the tool calls, or the
            # model loses track of what it asked for.
            messages.append({
                "role": "assistant",
                "content": reply.content or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name,
                                     "arguments": _as_json(call.arguments)},
                    }
                    for call in reply.tool_calls
                ],
            })

            for call in reply.tool_calls:
                observation, was_denied = self._dispatch(call)
                if was_denied:
                    denied.append(call.name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": observation,
                })

        self.transcript.note("step budget exhausted",
                             max_steps=self.config.max_steps)
        return Result(
            answer=steps[-1].content if steps else "",
            steps=steps,
            stopped_early=True,
            denied=denied,
        )

    def _dispatch(self, call: ToolCall) -> tuple[str, bool]:
        """Run one tool call. Returns (observation, was_denied).

        Every failure path returns text instead of raising. The observation
        goes back into the conversation, so a model that called a tool wrongly
        gets told how and can correct itself. Raising would end a run over a
        recoverable mistake.
        """
        try:
            tool = self.registry.get(call.name)
        except ToolError as exc:
            self.transcript.tool_result(call.name, False, str(exc))
            return f"error: {exc}", False

        try:
            args = validate(tool, call.arguments)
        except ToolError as exc:
            self.transcript.tool_call(call.name, call.arguments, tool.risk)
            self.transcript.tool_result(call.name, False, str(exc))
            return f"error: {exc}", False

        granted, reason = self.approver(call.name, args, tool.risk)
        self.transcript.approval(call.name, granted, reason)
        if not granted:
            return (
                f"denied: the operator did not approve {call.name} "
                f"({reason}). Do not retry it. Continue with what you can "
                f"establish without it, or state what you would need.",
                True,
            )

        self.transcript.tool_call(call.name, args, tool.risk)
        try:
            output = tool.handler(**args)
        except ToolError as exc:
            self.transcript.tool_result(call.name, False, str(exc))
            return f"error: {exc}", False
        except Exception as exc:  # unexpected: report, do not kill the run
            self.transcript.tool_result(call.name, False, repr(exc))
            return f"error: {call.name} failed unexpectedly: {exc!r}", False

        self.transcript.tool_result(call.name, True, output)
        return output or "(the tool produced no output)", False


def _as_json(value: dict) -> str:
    import json
    return json.dumps(value)

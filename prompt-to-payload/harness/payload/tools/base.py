"""Tool registry and argument validation.

A tool is a schema, a risk class and a handler. The schema goes to the model
and is also enforced on the way back in, because a local model will invent
parameters that were never in it.

The validator covers the subset of JSON Schema these tools use. A full one
would be a dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from payload.approval import RISK_ORDER


class ToolError(Exception):
    """A tool failed in a way the model should see and may recover from."""


@dataclass
class Tool:
    name: str
    description: str
    risk: str
    handler: Callable[..., str]
    parameters: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.risk not in RISK_ORDER:
            raise ValueError(
                f"tool {self.name!r} has unknown risk class {self.risk!r}; "
                f"expected one of {RISK_ORDER}"
            )

    def schema(self) -> dict[str, Any]:
        """The OpenAI tool-schema representation handed to the model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": list(self.required),
                },
            },
        }


# TODO: no support for nested object/array schemas. None of the tools need it
# yet; if one does, this is where it breaks.
def _type_ok(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        # bool is an int subclass; an integer parameter given `true` is a
        # model error worth reporting, not coercing.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def validate(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """Check `args` against the tool schema, returning the cleaned arguments.

    Raises ToolError with a message aimed at the model, not at a developer:
    it goes back into the conversation as an observation, so it needs to say
    what to do differently.
    """
    if "__malformed__" in args:
        raise ToolError(
            "your tool call arguments were not valid JSON. Re-issue the call "
            "with a single well-formed JSON object."
        )

    missing = [key for key in tool.required if key not in args]
    if missing:
        raise ToolError(
            f"missing required argument(s): {', '.join(missing)}. "
            f"Required: {', '.join(tool.required)}."
        )

    unknown = [key for key in args if key not in tool.parameters]
    if unknown:
        raise ToolError(
            f"unknown argument(s): {', '.join(unknown)}. "
            f"This tool accepts only: {', '.join(tool.parameters) or 'nothing'}."
        )

    cleaned: dict[str, Any] = {}
    for key, value in args.items():
        spec = tool.parameters[key]
        expected = spec.get("type")

        if expected and not _type_ok(value, expected):
            raise ToolError(
                f"argument {key!r} must be of type {expected}, got "
                f"{type(value).__name__}."
            )

        choices = spec.get("enum")
        if choices and value not in choices:
            raise ToolError(
                f"argument {key!r} must be one of {choices}, got {value!r}."
            )

        if expected in ("integer", "number"):
            low, high = spec.get("minimum"), spec.get("maximum")
            if low is not None and value < low:
                raise ToolError(f"argument {key!r} must be >= {low}.")
            if high is not None and value > high:
                raise ToolError(f"argument {key!r} must be <= {high}.")

        cleaned[key] = value

    return cleaned


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolError(
                f"no tool named {name!r}. Available tools: "
                f"{', '.join(sorted(self._tools))}."
            )
        return self._tools[name]

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

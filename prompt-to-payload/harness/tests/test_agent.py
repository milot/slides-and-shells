"""Agent loop tests. Scripted fake model, so no weights and no network."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payload.agent import Agent
from payload.approval import auto_approver
from payload.config import Config, RoleConfig
from payload.models import Reply, ToolCall
from payload.tools.base import Registry, Tool
from payload.transcript import Transcript


class FakeClient:
    """Replays scripted replies, records what it was asked."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, role, messages, tools=None, retries=2) -> Reply:
        self.calls.append(list(messages))
        if not self.replies:
            return Reply(content="(script exhausted)", tool_calls=[], raw={})
        return self.replies.pop(0)


def _tmp_config(**kw) -> Config:
    cfg = Config(**kw)
    cfg.roles["plan"] = RoleConfig(model="fake")
    return cfg


def _agent(replies, registry, approver=None, max_steps=8):
    tmp = Path(tempfile.mkdtemp())
    cfg = _tmp_config(max_steps=max_steps)
    transcript = Transcript(tmp / "t.jsonl")
    agent = Agent(cfg, registry, FakeClient(replies), transcript,
                  approver or auto_approver())
    return agent, transcript


def _call(name, args, cid="c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=args)


# ---------------------------------------------------------------- happy path

def test_plain_answer_returns_immediately():
    registry = Registry()
    agent, _ = _agent([Reply("the answer", [], {})], registry)
    result = agent.run("question", "system")
    assert result.answer == "the answer"
    assert len(result.steps) == 1
    assert not result.stopped_early
    print("  plain answer returns without tool use")


def test_tool_is_dispatched_then_answer_returned():
    seen = {}

    def handler(value: str) -> str:
        seen["value"] = value
        return f"observed {value}"

    registry = Registry()
    registry.add(Tool(name="probe", description="d", risk="read",
                      handler=handler,
                      parameters={"value": {"type": "string"}},
                      required=("value",)))

    agent, transcript = _agent([
        Reply("", [_call("probe", {"value": "x"})], {}),
        Reply("done", [], {}),
    ], registry)

    result = agent.run("task", "system")
    assert seen["value"] == "x", seen
    assert result.answer == "done"
    assert result.steps[0].calls == ["probe"]

    records = [json.loads(l) for l in transcript.path.read_text().splitlines()]
    kinds = [r["kind"] for r in records]
    assert "tool_call" in kinds and "tool_result" in kinds, kinds
    print("  tool dispatched, result fed back, transcript records both")


def test_tool_observation_reaches_the_next_model_call():
    registry = Registry()
    registry.add(Tool(name="probe", description="d", risk="read",
                      handler=lambda: "OBSERVATION-MARKER",
                      parameters={}))

    client_replies = [
        Reply("", [_call("probe", {})], {}),
        Reply("fin", [], {}),
    ]
    agent, _ = _agent(client_replies, registry)
    agent.run("task", "system")

    second_call = agent.client.calls[1]
    tool_messages = [m for m in second_call if m.get("role") == "tool"]
    assert tool_messages, second_call
    assert "OBSERVATION-MARKER" in tool_messages[0]["content"]
    # the assistant turn carrying the tool_calls must be echoed back too,
    # or the model loses track of what it asked for
    assistant = [m for m in second_call if m.get("role") == "assistant"]
    assert assistant and assistant[0].get("tool_calls"), assistant
    print("  observation and assistant tool_calls both reach the next turn")


# ------------------------------------------------------------- failure paths

def test_unknown_tool_is_reported_to_the_model_not_raised():
    registry = Registry()
    registry.add(Tool(name="real", description="d", risk="read",
                      handler=lambda: "ok", parameters={}))
    agent, _ = _agent([
        Reply("", [_call("imaginary", {})], {}),
        Reply("recovered", [], {}),
    ], registry)

    result = agent.run("task", "system")
    assert result.answer == "recovered"
    observation = [m for m in agent.client.calls[1] if m.get("role") == "tool"][0]
    assert "no tool named" in observation["content"]
    print("  hallucinated tool name reported back, run continues")


def test_bad_arguments_are_reported_to_the_model():
    # Order matters: told only that `wrong` is unknown, a local model tends to
    # re-issue the call with the same omission.
    registry = Registry()
    registry.add(Tool(name="probe", description="d", risk="read",
                      handler=lambda value: value,
                      parameters={"value": {"type": "string"}},
                      required=("value",)))
    agent, _ = _agent([
        Reply("", [_call("probe", {"wrong": 1})], {}),
        Reply("recovered", [], {}),
    ], registry)
    agent.run("task", "system")
    observation = [m for m in agent.client.calls[1] if m.get("role") == "tool"][0]
    assert "missing required" in observation["content"], observation["content"]
    assert "value" in observation["content"]
    print("  missing required argument named first, which is what aids recovery")


def test_unknown_argument_alone_is_reported_with_the_accepted_set():
    registry = Registry()
    registry.add(Tool(name="probe", description="d", risk="read",
                      handler=lambda value="v": value,
                      parameters={"value": {"type": "string"}}))
    agent, _ = _agent([
        Reply("", [_call("probe", {"invented": 1})], {}),
        Reply("recovered", [], {}),
    ], registry)
    agent.run("task", "system")
    observation = [m for m in agent.client.calls[1] if m.get("role") == "tool"][0]
    assert "unknown argument" in observation["content"], observation["content"]
    assert "accepts only: value" in observation["content"]
    print("  invented argument reported with the set the tool does accept")


def test_handler_exception_does_not_end_the_run():
    def explode():
        raise RuntimeError("disk on fire")

    registry = Registry()
    registry.add(Tool(name="boom", description="d", risk="read",
                      handler=explode, parameters={}))
    agent, _ = _agent([
        Reply("", [_call("boom", {})], {}),
        Reply("survived", [], {}),
    ], registry)
    result = agent.run("task", "system")
    assert result.answer == "survived"
    observation = [m for m in agent.client.calls[1] if m.get("role") == "tool"][0]
    assert "failed unexpectedly" in observation["content"]
    print("  unexpected handler exception becomes an observation, not a crash")


# -------------------------------------------------------------------- safety

def test_target_touching_tool_is_denied_by_default():
    ran = {"yes": False}

    def toucher(host: str) -> str:
        ran["yes"] = True
        return "scanned"

    registry = Registry()
    registry.add(Tool(name="scan", description="d", risk="touch",
                      handler=toucher,
                      parameters={"host": {"type": "string"}},
                      required=("host",)))

    agent, transcript = _agent([
        Reply("", [_call("scan", {"host": "10.0.0.1"})], {}),
        Reply("stopped", [], {}),
    ], registry, approver=auto_approver())

    result = agent.run("task", "system")
    assert ran["yes"] is False, "a touch-class tool ran without approval"
    assert "scan" in result.denied
    observation = [m for m in agent.client.calls[1] if m.get("role") == "tool"][0]
    assert "denied" in observation["content"]

    records = [json.loads(l) for l in transcript.path.read_text().splitlines()]
    approvals = [r for r in records if r["kind"] == "approval"]
    assert approvals and approvals[0]["granted"] is False
    print("  touch-class tool denied by default and the denial is recorded")


def test_preapproved_tool_runs():
    ran = {"yes": False}

    def toucher(host: str) -> str:
        ran["yes"] = True
        return "scanned"

    registry = Registry()
    registry.add(Tool(name="scan", description="d", risk="touch",
                      handler=toucher,
                      parameters={"host": {"type": "string"}},
                      required=("host",)))
    agent, _ = _agent([
        Reply("", [_call("scan", {"host": "10.0.0.1"})], {}),
        Reply("ok", [], {}),
    ], registry, approver=auto_approver(allow=("scan",)))
    agent.run("task", "system")
    assert ran["yes"] is True
    print("  explicitly pre-approved touch-class tool is allowed to run")


def test_step_budget_is_enforced():
    registry = Registry()
    registry.add(Tool(name="loop", description="d", risk="read",
                      handler=lambda: "again", parameters={}))
    # a model that never stops asking for tools
    agent, _ = _agent([Reply("", [_call("loop", {})], {})] * 50,
                      registry, max_steps=4)
    result = agent.run("task", "system")
    assert result.stopped_early is True
    assert len(result.steps) == 4, len(result.steps)
    print("  runaway loop stopped at the configured step budget")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"agent loop: {len(tests)} tests\n")
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            print(f"  FAIL {test.__name__}: {exc}")
            failed += 1
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

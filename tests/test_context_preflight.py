"""Hard context-budget preflight and recovery trimming."""

from types import SimpleNamespace

import pytest

from personal_agent.agent.context_preflight import (
    looks_like_context_length_error,
    preflight_context_budget,
)
from personal_agent.compression.simple import prune_old_tool_results
from personal_agent.llm.token_counter import count_messages_tokens, truncate_message_to_tokens


def _text(role: str, text: str) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _tool_result(tool_use_id: str, text: str) -> dict:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}],
    }


def _tool_use(tool_id: str, name: str = "read") -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {}}],
    }


def _agent(**kwargs):
    provider = SimpleNamespace(
        model="m",
        context_window=kwargs.pop("context_window", 400),
        max_tokens=kwargs.pop("max_tokens", 80),
    )
    defaults = dict(
        _provider=provider,
        model="m",
        tools=[],
        _cached_system_prompt="system",
        _compressor=None,
        _last_context_recovery={},
        _last_memory_injections="memory",
        _last_skill_summaries="skills",
        _last_skill_injection="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _ctx(**kwargs):
    defaults = dict(
        messages=[_text("user", "hello")],
        skill_summaries="",
        skill_injection=None,
        memory_prefetch_messages=[],
        memory_injections_text="",
        hook_contexts=[],
        trim_actions=[],
        overflow_source="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_looks_like_context_length_error_distinguishes_parse_errors():
    assert looks_like_context_length_error(RuntimeError("maximum context length exceeded"))
    assert looks_like_context_length_error(RuntimeError("prompt is too long"))
    assert looks_like_context_length_error(RuntimeError("This model's context window is 8k"))
    assert not looks_like_context_length_error(RuntimeError("unexpected token"))
    assert not looks_like_context_length_error(RuntimeError("transport boom"))


def test_truncate_message_to_tokens_shortens_tool_result():
    message = _tool_result("t1", "y" * 8000)
    truncated = truncate_message_to_tokens(message, 40, model="m")
    assert count_messages_tokens([truncated], model="m") <= 50
    assert "truncated" in str(truncated["content"]).lower() or len(str(truncated["content"])) < 8000


@pytest.mark.asyncio
async def test_preflight_drops_memory_then_skills_before_failing_closed():
    history = []
    for index in range(8):
        history.append(_tool_use(f"t{index}"))
        history.append(_tool_result(f"t{index}", "tool output " + "z" * 400))
        history.append(_text("user", f"q{index}"))
        history.append(_text("assistant", f"a{index}"))
    history.append(_text("user", "current question"))
    ctx = _ctx(
        messages=history,
        skill_summaries="skill catalog " + "s" * 400,
        memory_prefetch_messages=[_text("user", "[相关记忆] " + "m" * 400)],
        memory_injections_text="[相关记忆] " + "m" * 400,
    )
    agent = _agent(context_window=220, max_tokens=80)

    result = await preflight_context_budget(agent, ctx, tools=[], mode="hard")

    actions = [item.action for item in result.trim_actions]
    assert "prune_tool_results" in actions or "drop_memory" in actions
    assert ctx.memory_injections_text == ""
    assert ctx.memory_prefetch_messages == []
    if "drop_skill_summaries" in actions:
        assert ctx.skill_summaries == ""
    assert "drop_memory" in actions or not ctx.memory_injections_text


@pytest.mark.asyncio
async def test_preflight_truncates_oversized_tool_result():
    ctx = _ctx(messages=[
        _text("user", "start"),
        _tool_use("t1"),
        _tool_result("t1", "w" * 12000),
        _text("user", "what was in the file?"),
    ])
    agent = _agent(context_window=300, max_tokens=60)

    result = await preflight_context_budget(agent, ctx, tools=[], mode="hard")

    actions = [item.action for item in result.trim_actions]
    assert "truncate_messages" in actions or "prune_tool_results" in actions
    longest = max(
        (count_messages_tokens([message], model="m") for message in ctx.messages),
        default=0,
    )
    assert longest < count_messages_tokens([_tool_result("t1", "w" * 12000)], model="m")


@pytest.mark.asyncio
async def test_preflight_fail_closed_when_system_and_tools_are_immovable():
    agent = _agent(
        context_window=120,
        max_tokens=40,
        _cached_system_prompt="S" * 2000,
        tools=[{
            "name": "read",
            "description": "D" * 2000,
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }],
    )
    ctx = _ctx(messages=[_text("user", "hi")])

    result = await preflight_context_budget(agent, ctx, tools=agent.tools, mode="hard")

    assert result.allowed is False
    assert result.immovable_overflow is True
    assert result.budget.over_budget is True


@pytest.mark.asyncio
async def test_preflight_rechecks_after_tool_result_appended():
    agent = _agent(context_window=280, max_tokens=50)
    ctx = _ctx(messages=[_text("user", "hello")])

    first = await preflight_context_budget(agent, ctx, tools=[], mode="hard")
    assert first.allowed is True

    ctx.messages.extend([
        _tool_use("t-new"),
        _tool_result("t-new", "n" * 10000),
    ])
    second = await preflight_context_budget(agent, ctx, tools=[], mode="hard")
    assert second.trim_actions
    assert any(
        action.action in {"prune_tool_results", "truncate_messages"}
        for action in second.trim_actions
    )


def test_prune_old_tool_results_keeps_tail():
    messages = [
        _text("user", "old"),
        _tool_use("t0"),
        _tool_result("t0", "ancient"),
        _text("assistant", "mid"),
        _tool_use("t1"),
        _tool_result("t1", "recent"),
        _text("user", "now"),
    ]
    pruned = prune_old_tool_results(messages, protect_head=1, protect_tail=2)
    contents = str(pruned)
    assert "now" in contents
    assert "ancient" not in contents

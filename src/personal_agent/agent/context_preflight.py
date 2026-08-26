"""Hard context-budget gate and recovery trimming before each LLM call."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from personal_agent.compression.simple import fit_tail_token_budget, prune_old_tool_results
from personal_agent.context_budget import ContextBudget, compose_context_text, estimate_context_budget
from personal_agent.conversation.history_events import repair_native_tool_messages
from personal_agent.llm.token_counter import fit_messages_to_token_budget

logger = logging.getLogger(__name__)

PreflightMode = Literal["hard", "aggressive"]

_CONTEXT_LENGTH_MARKERS = (
    "context length",
    "context_length",
    "maximum context",
    "max context",
    "prompt is too long",
    "prompt too long",
    "too many tokens",
    "token limit exceeded",
    "exceeds the context",
    "exceeded model token limit",
    "context window",
    "input is too long",
    "request too large",
    "prompt exceeds",
    "tokens exceed",
    "context_overflow",
)


@dataclass
class TrimAction:
    action: str
    detail: str = ""
    tokens_before: int = 0
    tokens_after: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "detail": self.detail,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
        }


@dataclass
class PreflightResult:
    allowed: bool
    budget: ContextBudget
    trim_actions: list[TrimAction] = field(default_factory=list)
    overflow_source: str = ""
    immovable_overflow: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "overflow_source": self.overflow_source,
            "trim_actions": [action.as_dict() for action in self.trim_actions],
            "immovable_overflow": self.immovable_overflow,
            "budget": self.budget.as_dict(),
        }


def looks_like_context_length_error(exc: Exception) -> bool:
    """True when a provider error is about input context overflowing."""
    msg = str(exc).lower()
    if "unexpected token" in msg:
        return False
    return any(marker in msg for marker in _CONTEXT_LENGTH_MARKERS)


def format_overflow_message(result: PreflightResult) -> str:
    source = result.overflow_source or result.budget.overflow_source or "mixed"
    actions = [action.action for action in result.trim_actions]
    if result.immovable_overflow:
        return (
            f"本轮上下文超出限制（主要来源: {source}）。"
            "system prompt 与工具 schema 已单独占满可用窗口，无法通过裁剪历史发送请求。"
        )
    if actions:
        return (
            f"本轮上下文超出限制（主要来源: {source}），"
            f"已尝试裁剪（{', '.join(actions)}）后仍无法发送请求。"
        )
    return f"本轮上下文超出限制（主要来源: {source}），未能发送请求。"


def estimate_turn_budget(agent, ctx, *, tools: list[dict] | None = None) -> ContextBudget:
    provider = getattr(agent, "_provider", None)
    model = getattr(provider, "model", "") or getattr(agent, "model", "")
    context_limit = int(getattr(provider, "context_window", 0) or 0)
    reserved_output = max(1, int(getattr(provider, "max_tokens", 1) or 1))
    compressor = getattr(agent, "_compressor", None)
    threshold_ratio = 0.0
    if compressor is not None:
        context_length = int(getattr(compressor, "context_length", 0) or 0)
        threshold_tokens = int(getattr(compressor, "threshold_tokens", 0) or 0)
        if context_length > 0 and threshold_tokens > 0:
            threshold_ratio = threshold_tokens / context_length

    messages = list(getattr(ctx, "messages", []) or [])
    for hook_context in getattr(ctx, "hook_contexts", []) or []:
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": hook_context}],
        })

    skills_summary = compose_context_text(
        getattr(ctx, "skill_summaries", "") or "",
        getattr(ctx, "skill_injection", None) or "",
    )
    return estimate_context_budget(
        messages=messages,
        system_prompt=getattr(agent, "_cached_system_prompt", "") or "",
        tools=list(getattr(agent, "tools", []) if tools is None else tools),
        skills_summary=skills_summary,
        memory_injections=getattr(ctx, "memory_injections_text", "") or "",
        context_limit=context_limit,
        model=model,
        compression_threshold_ratio=threshold_ratio,
        reserved_output=reserved_output,
    )


async def preflight_context_budget(
    agent,
    ctx,
    *,
    tools: list[dict] | None = None,
    mode: PreflightMode = "hard",
) -> PreflightResult:
    """Trim ctx until the request fits, or fail closed without calling the provider."""
    previous: list[TrimAction] = []
    for action in getattr(ctx, "trim_actions", []) or []:
        if isinstance(action, TrimAction):
            previous.append(action)
        elif isinstance(action, dict) and action.get("action"):
            previous.append(TrimAction(
                action=str(action.get("action") or ""),
                detail=str(action.get("detail") or ""),
                tokens_before=int(action.get("tokens_before") or 0),
                tokens_after=int(action.get("tokens_after") or 0),
            ))
    actions = list(previous)
    tools = list(getattr(agent, "tools", []) if tools is None else tools)
    compressor = getattr(agent, "_compressor", None)
    model = getattr(getattr(agent, "_provider", None), "model", "") or getattr(agent, "model", "")

    if mode == "aggressive":
        protect_head = 1
        protect_tail = 2
        tail_budget = int(getattr(compressor, "tail_token_budget", 4000) or 4000)
        tail_budget = max(256, min(tail_budget, 4000))
    else:
        protect_head = int(getattr(compressor, "protect_head", 2) or 2)
        protect_tail = int(getattr(compressor, "protect_tail", 6) or 6)
        tail_budget = int(getattr(compressor, "tail_token_budget", 0) or 0)

    budget = estimate_turn_budget(agent, ctx, tools=tools)
    if budget.can_send and not budget.over_budget:
        return _finish(ctx, agent, True, budget, actions)

    if budget.immovable_overflow:
        logger.warning(
            "Context overflow is immovable: system+tools=%d usable=%d",
            budget.immovable,
            budget.usable_limit,
        )
        return _finish(ctx, agent, False, budget, actions, immovable=True)

    # 1. Old tool outputs
    budget = _maybe_trim(
        agent,
        ctx,
        tools,
        actions,
        "prune_tool_results",
        lambda: _set_messages(
            ctx,
            prune_old_tool_results(
                list(ctx.messages),
                protect_head=protect_head,
                protect_tail=protect_tail,
            ),
        ),
        budget,
    )
    if not budget.over_budget:
        return _finish(ctx, agent, True, budget, actions)

    # 2. Memory injections (request-side only)
    if getattr(ctx, "memory_prefetch_messages", None) or getattr(ctx, "memory_injections_text", ""):
        budget = _maybe_trim(
            agent,
            ctx,
            tools,
            actions,
            "drop_memory",
            lambda: _drop_memory(agent, ctx),
            budget,
        )
        if not budget.over_budget:
            return _finish(ctx, agent, True, budget, actions)

    # 3. Low-priority skill catalog; keep explicit /skill injection unless aggressive
    if getattr(ctx, "skill_summaries", ""):
        budget = _maybe_trim(
            agent,
            ctx,
            tools,
            actions,
            "drop_skill_summaries",
            lambda: _drop_skill_summaries(agent, ctx),
            budget,
        )
        if not budget.over_budget:
            return _finish(ctx, agent, True, budget, actions)

    if mode == "aggressive" and getattr(ctx, "skill_injection", None):
        budget = _maybe_trim(
            agent,
            ctx,
            tools,
            actions,
            "drop_skill_injection",
            lambda: _drop_skill_injection(agent, ctx),
            budget,
        )
        if not budget.over_budget:
            return _finish(ctx, agent, True, budget, actions)

    # 4. History compression / token trim
    history_target = max(32, budget.usable_limit - budget.immovable)
    budget = _maybe_trim(
        agent,
        ctx,
        tools,
        actions,
        "truncate_messages",
        lambda: _trim_history(
            ctx,
            model=model,
            history_target=history_target,
            protect_head=protect_head,
            protect_tail=protect_tail,
            tail_budget=tail_budget,
            aggressive=mode == "aggressive",
        ),
        budget,
    )
    allowed = budget.can_send
    return _finish(ctx, agent, allowed, budget, actions)


def _maybe_trim(
    agent,
    ctx,
    tools: list[dict],
    actions: list[TrimAction],
    action: str,
    mutator,
    budget: ContextBudget,
) -> ContextBudget:
    before = budget.used
    mutator()
    updated = estimate_turn_budget(agent, ctx, tools=tools)
    if updated.used < before:
        actions.append(TrimAction(
            action=action,
            tokens_before=before,
            tokens_after=updated.used,
        ))
    return updated


def _set_messages(ctx, messages: list[dict]) -> None:
    ctx.messages = messages


def _drop_memory(agent, ctx) -> None:
    ctx.memory_prefetch_messages = []
    ctx.memory_injections_text = ""
    if hasattr(agent, "_last_memory_injections"):
        agent._last_memory_injections = ""


def _drop_skill_summaries(agent, ctx) -> None:
    ctx.skill_summaries = ""
    if hasattr(agent, "_last_skill_summaries"):
        agent._last_skill_summaries = ""


def _drop_skill_injection(agent, ctx) -> None:
    ctx.skill_injection = None
    if hasattr(agent, "_last_skill_injection"):
        agent._last_skill_injection = ""


def _trim_history(
    ctx,
    *,
    model: str,
    history_target: int,
    protect_head: int,
    protect_tail: int,
    tail_budget: int,
    aggressive: bool,
) -> None:
    messages = list(ctx.messages)
    if tail_budget > 0:
        messages = fit_tail_token_budget(
            messages,
            model=model,
            tail_token_budget=tail_budget,
            protect_head=protect_head,
            protect_tail=protect_tail,
        )
    per_message_cap = max(64, history_target if aggressive else max(history_target, tail_budget or history_target))
    messages = fit_messages_to_token_budget(
        messages,
        model=model,
        max_tokens=max(32, history_target),
        protect_head=protect_head if not aggressive else 1,
        protect_last=1,
    )
    # Ensure no leftover single oversized tool_result even in the protected tail.
    if per_message_cap > 0:
        from personal_agent.llm.token_counter import truncate_message_to_tokens

        cap = min(per_message_cap, tail_budget) if tail_budget > 0 else per_message_cap
        messages = [
            truncate_message_to_tokens(message, max(64, cap), model)
            for message in messages
        ]
    ctx.messages = repair_native_tool_messages(messages)


def _finish(
    ctx,
    agent,
    allowed: bool,
    budget: ContextBudget,
    actions: list[TrimAction],
    *,
    immovable: bool = False,
) -> PreflightResult:
    payload = PreflightResult(
        allowed=allowed,
        budget=budget,
        trim_actions=actions,
        overflow_source=budget.overflow_source,
        immovable_overflow=immovable or budget.immovable_overflow,
    )
    ctx.trim_actions = [action.as_dict() for action in actions]
    ctx.overflow_source = payload.overflow_source
    if hasattr(agent, "_last_context_recovery"):
        agent._last_context_recovery = payload.as_dict()
    return payload

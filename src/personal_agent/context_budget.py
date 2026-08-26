"""Unified context budget estimation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from personal_agent.llm.token_counter import count_messages_tokens, count_tools_tokens, estimate_tokens

_COMPONENT_KEYS = (
    "system_prompt",
    "history_messages",
    "tools_schema",
    "skills",
    "memory_injections",
    "mcp_tools",
)


def compose_context_text(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


@dataclass
class ContextBudget:
    system_prompt: int
    history_messages: int
    tools_schema: int
    skills: int
    memory_injections: int
    mcp_tools: int
    remaining_context: int
    context_limit: int
    compression_threshold: int = 0
    reserved_output: int = 0
    over_budget: bool = False
    deficit: int = 0
    overflow_source: str = ""

    @property
    def used(self) -> int:
        return (
            self.system_prompt
            + self.history_messages
            + self.tools_schema
            + self.skills
            + self.memory_injections
            + self.mcp_tools
        )

    @property
    def percent(self) -> float:
        return round(self.used / max(self.context_limit, 1) * 100, 1)

    @property
    def immovable(self) -> int:
        return self.system_prompt + self.tools_schema + self.mcp_tools

    @property
    def usable_limit(self) -> int:
        return max(0, self.context_limit - self.reserved_output)

    @property
    def immovable_overflow(self) -> bool:
        return self.immovable >= self.context_limit

    @property
    def can_send(self) -> bool:
        """True when input fits in the window, leaving at least one output token."""
        return self.used < self.context_limit

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_prompt": self.system_prompt,
            "history_messages": self.history_messages,
            "tools_schema": self.tools_schema,
            "skills": self.skills,
            "memory_injections": self.memory_injections,
            "mcp_tools": self.mcp_tools,
            "used": self.used,
            "context_limit": self.context_limit,
            "remaining_context": self.remaining_context,
            "percent": self.percent,
            "compression_threshold": self.compression_threshold,
            "over_compression_threshold": self.over_compression_threshold,
            "reserved_output": self.reserved_output,
            "over_budget": self.over_budget,
            "deficit": self.deficit,
            "overflow_source": self.overflow_source,
            "immovable": self.immovable,
            "usable_limit": self.usable_limit,
            "immovable_overflow": self.immovable_overflow,
            "can_send": self.can_send,
        }

    @property
    def over_compression_threshold(self) -> bool:
        return bool(self.compression_threshold and self.used >= self.compression_threshold)


def resolve_overflow_source(budget: ContextBudget) -> str:
    if not budget.over_budget:
        return ""
    parts = [(key, int(getattr(budget, key) or 0)) for key in _COMPONENT_KEYS]
    max_val = max((value for _, value in parts), default=0)
    if max_val <= 0:
        return "mixed"
    leaders = [key for key, value in parts if value == max_val]
    if len(leaders) != 1:
        return "mixed"
    return leaders[0]


def estimate_context_budget(
    *,
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,
    skills_summary: str = "",
    memory_injections: str = "",
    context_limit: int = 0,
    model: str = "",
    compression_threshold_ratio: float = 0,
    reserved_output: int = 0,
) -> ContextBudget:
    if context_limit <= 0:
        from personal_agent.llm.provider import _detect_context_window

        context_limit = _detect_context_window(model)

    all_tools = tools or []
    mcp_tools = [
        tool for tool in all_tools
        if tool.get("name", "").startswith("mcp__")
        or str(tool.get("description", "")).startswith("[MCP ")
    ]
    normal_tools = [tool for tool in all_tools if tool not in mcp_tools]

    system_tokens = estimate_tokens(system_prompt, model)
    history_tokens = count_messages_tokens(messages, model=model)
    tool_tokens = count_tools_tokens(normal_tools, model=model)
    mcp_tokens = count_tools_tokens(mcp_tools, model=model)
    skills_tokens = estimate_tokens(skills_summary, model)
    memory_tokens = estimate_tokens(memory_injections, model)
    used = system_tokens + history_tokens + tool_tokens + mcp_tokens + skills_tokens + memory_tokens
    reserved = max(0, int(reserved_output or 0))
    deficit = max(0, used + reserved - context_limit)
    compression_threshold = (
        int(context_limit * compression_threshold_ratio)
        if compression_threshold_ratio > 0 else 0
    )

    budget = ContextBudget(
        system_prompt=system_tokens,
        history_messages=history_tokens,
        tools_schema=tool_tokens,
        skills=skills_tokens,
        memory_injections=memory_tokens,
        mcp_tools=mcp_tokens,
        context_limit=context_limit,
        remaining_context=max(0, context_limit - used),
        compression_threshold=compression_threshold,
        reserved_output=reserved,
        over_budget=deficit > 0,
        deficit=deficit,
    )
    budget.overflow_source = resolve_overflow_source(budget)
    return budget


async def build_context_budget(
    *,
    messages: list[dict],
    agent: Any | None = None,
    settings: Any | None = None,
    system_prompt: str = "",
    tools: list[dict] | None = None,
    skills_summary: str | None = None,
    memory_injections: str | None = None,
    current_user_message: str = "",
    context_limit: int = 0,
    model: str = "",
) -> ContextBudget:
    """Build a context budget from either raw inputs or a live Agent."""
    if agent is not None:
        provider = getattr(agent, "_provider", None)
        model = model or getattr(provider, "model", "") or getattr(agent, "model", "")
        if context_limit <= 0:
            context_limit = getattr(provider, "context_window", 0) or 0
        if not system_prompt:
            system_prompt = getattr(agent, "_cached_system_prompt", "") or ""
        if tools is None:
            tools = getattr(agent, "tools", [])

    if tools is None:
        tools = []

    if settings is not None:
        model = model or str(getattr(settings, "llm_model", "") or "")
        if context_limit <= 0:
            context_limit = int(getattr(settings, "llm_context_window", 0) or 0)

    if skills_summary is None:
        skills_summary = _current_skill_summaries()

    if memory_injections is None:
        memory_injections = ""
        if agent is not None and current_user_message:
            memory_injections = await _memory_prefetch_text(agent, current_user_message)

    threshold_ratio = float(getattr(settings, "compression_threshold_ratio", 0) or 0)
    reserved_output = 0
    if agent is not None:
        provider = getattr(agent, "_provider", None)
        reserved_output = int(getattr(provider, "max_tokens", 0) or 0)
    if reserved_output <= 0 and settings is not None:
        reserved_output = int(getattr(settings, "llm_max_tokens", 0) or 0)

    return estimate_context_budget(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        skills_summary=skills_summary or "",
        memory_injections=memory_injections or "",
        context_limit=context_limit,
        model=model,
        compression_threshold_ratio=threshold_ratio,
        reserved_output=reserved_output,
    )


def _current_skill_summaries() -> str:
    try:
        from personal_agent.skills.registry import skill_registry

        return skill_registry.get_summaries()
    except Exception:
        return ""


async def _memory_prefetch_text(agent: Any, user_message: str) -> str:
    memory_manager = getattr(agent, "_memory_manager", None)
    if memory_manager is None:
        return ""
    try:
        prefetched = await memory_manager.prefetch(user_message)
    except Exception:
        return ""
    return "\n".join(message_text(message) for message in prefetched if message)


def message_text(message: dict) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts = []
    for block in content:
        if isinstance(block, dict):
            if "text" in block:
                parts.append(str(block.get("text") or ""))
            elif "content" in block:
                parts.append(str(block.get("content") or ""))
        else:
            parts.append(str(block))
    return "\n".join(part for part in parts if part)


def format_context_budget_report(
    budget: ContextBudget,
    *,
    recovery: dict[str, Any] | None = None,
) -> str:
    """Human-readable context window section used by /usage and CLI."""
    lines = [
        f"已用: {budget.used:,} / {budget.context_limit:,} tokens ({budget.percent}%)",
        f"  system prompt: {budget.system_prompt:,}",
        f"  history messages: {budget.history_messages:,}",
        f"  tools schema: {budget.tools_schema:,}",
        f"  skills: {budget.skills:,}",
        f"  memory injections: {budget.memory_injections:,}",
        f"  MCP tools: {budget.mcp_tools:,}",
        f"预留输出: {budget.reserved_output:,} tokens",
        f"可用上限: {budget.usable_limit:,} tokens",
        f"剩余: {budget.remaining_context:,} tokens",
    ]
    if budget.over_budget:
        source = budget.overflow_source or "mixed"
        lines.append(f"硬性预算: 已超限 (deficit {budget.deficit:,}, 主要来源: {source})")
    else:
        lines.append("硬性预算: 未超限")
    if budget.compression_threshold:
        marker = "，已达到" if budget.over_compression_threshold else ""
        lines.append(f"压缩阈值: {budget.compression_threshold:,} tokens{marker}")
    if recovery:
        source = str(recovery.get("overflow_source") or "").strip()
        actions = recovery.get("trim_actions") or []
        if source:
            lines.append(f"最近超限来源: {source}")
        if actions:
            labels = []
            for action in actions:
                name = action.get("action") if isinstance(action, dict) else str(action)
                if name:
                    labels.append(str(name))
            if labels:
                lines.append(f"最近裁剪动作: {', '.join(labels)}")
    return "\n".join(lines)

"""ContextCompressor — prune old tool_results, then LLM summary with iterative update.

Two-step algorithm (Hermes pattern):
  1. _prune_old_tool_results — regex cleanup, zero LLM cost
  2. _generate_summary — LLM summary (iterative update if previous summary exists)
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from personal_agent.compression.base import ContextEngine
from personal_agent.compression.registry import compression_registry
from personal_agent.conversation.history_events import (
    build_system_summary_api_message,
    repair_native_tool_messages,
)
from personal_agent.llm.provider import ProviderProfile
from personal_agent.llm.token_counter import (
    count_messages_tokens,
    fit_messages_to_token_budget,
    truncate_message_to_tokens,
)

logger = logging.getLogger(__name__)


class ContextCompressor(ContextEngine):
    name = "compressor"

    def __init__(
        self,
        context_length: int = 64000,
        threshold_ratio: float = 0.6,
        tail_token_budget: int = 20000,
        max_summary_tokens: int = 500,
        protect_head: int = 2,
        protect_tail: int = 6,
        compressor_transport: Any = None,  # optional: separate transport for cheap model
        model: str = "",
    ) -> None:
        self.context_length = context_length
        self.threshold_tokens = int(context_length * threshold_ratio)
        self.tail_token_budget = tail_token_budget
        self.max_summary_tokens = max_summary_tokens
        self.protect_head = protect_head
        self.protect_tail = protect_tail
        self._compressor_transport = compressor_transport  # None = use main transport
        self.model = model

        # Per-session state
        self._previous_summary: str | None = None
        self._ineffective_compression_count: int = 0
        self._summary_failure_cooldown_until: float = 0
        self.last_prompt_tokens: int = 0

    # ── ContextEngine interface ───────────────────────

    def should_compress(self, token_count: int, messages: list[dict]) -> bool:
        if token_count < self.threshold_tokens:
            return False
        if self._ineffective_compression_count >= 2:
            logger.info("Compression disabled: 2 ineffective attempts")
            return False
        if time.time() < self._summary_failure_cooldown_until:
            logger.info("Compression in cooldown until %.0f", self._summary_failure_cooldown_until)
            return False
        if len(messages) <= self.protect_head + self.protect_tail + 2:
            return False
        return True

    async def compress(
        self,
        messages: list[dict],
        system_prompt: str,
        transport: Any,
        protect_head: int = 2,
        protect_tail: int = 6,
    ) -> list[dict]:
        """Two-step: prune, then summarize if still needed."""
        self.protect_head = protect_head
        self.protect_tail = protect_tail
        before_tokens = self._estimate_tokens(messages, system_prompt)
        self.last_prompt_tokens = before_tokens

        # Step 1: prune old tool results (zero LLM cost)
        messages = self._prune_old_tool_results(messages)
        messages = self.apply_tail_token_budget(messages)

        # Check if pruning was enough
        token_count = self._estimate_tokens(messages, system_prompt)
        if token_count < self.threshold_tokens:
            logger.info("Pruning sufficient: %d → %d tokens", before_tokens, token_count)
            return messages

        # Step 2: LLM summary
        if len(messages) <= self.protect_head + self.protect_tail + 2:
            return messages

        head = messages[:self.protect_head]
        middle = messages[self.protect_head:-self.protect_tail]
        tail = messages[-self.protect_tail:]

        summary = await self._generate_summary(middle, system_prompt, transport)
        if summary is None:
            self._summary_failure_cooldown_until = time.time() + 120
            self._ineffective_compression_count += 1
            return messages

        # Measure effectiveness
        summary_msg = build_system_summary_api_message(summary)
        compressed = head + [summary_msg] + self.apply_tail_token_budget(tail)
        after_tokens = count_messages_tokens(compressed, model=self.model) + count_messages_tokens([], system_prompt, model=self.model)

        if before_tokens > 0 and (before_tokens - after_tokens) / before_tokens < 0.10:
            logger.info("Compression ineffective: %d → %d tokens (< 10%%)", before_tokens, after_tokens)
            self._ineffective_compression_count += 1
        else:
            self._ineffective_compression_count = 0

        # Store for iterative update next time
        self._previous_summary = summary
        logger.info("Compressed: %d → %d tokens (saved %d%%)",
                     before_tokens, after_tokens,
                     int((1 - after_tokens / (before_tokens or 1)) * 100))
        # Summary insertion can sit between tool_use and tool_result; repair pairing.
        return repair_native_tool_messages(compressed)

    def on_session_start(self) -> None:
        self._previous_summary = None
        self._ineffective_compression_count = 0
        self._summary_failure_cooldown_until = 0

    def on_session_end(self) -> None:
        self.on_session_start()

    # ── Step 1: prune old tool results ─────────────────

    def _prune_old_tool_results(self, messages: list[dict]) -> list[dict]:
        return prune_old_tool_results(
            messages,
            protect_head=self.protect_head,
            protect_tail=self.protect_tail,
        )

    def apply_tail_token_budget(
        self,
        messages: list[dict],
        *,
        protect_head: int | None = None,
        protect_tail: int | None = None,
    ) -> list[dict]:
        """Keep the tail within ``tail_token_budget``, truncating oversized messages."""
        return fit_tail_token_budget(
            messages,
            model=self.model,
            tail_token_budget=self.tail_token_budget,
            protect_head=self.protect_head if protect_head is None else protect_head,
            protect_tail=self.protect_tail if protect_tail is None else protect_tail,
        )

    @staticmethod
    def _clean_orphan_tool_uses(messages: list[dict]) -> list[dict]:
        return _clean_orphan_tool_uses(messages)

    # ── Step 2: LLM summary ────────────────────────────

    async def _generate_summary(
        self,
        middle: list[dict],
        system_prompt: str,
        transport: Any,
    ) -> str | None:
        """Call LLM to summarize middle segment."""
        use_transport = self._compressor_transport or transport
        formatted = _format_messages_for_summary(middle)

        if self._previous_summary:
            prompt = (
                "以下是之前对话的摘要：\n\n"
                f"{self._previous_summary}\n\n"
                "请将以下新的对话内容更新到这个摘要中，保持结构清晰、简洁。"
                "用中文回复，不超过300字。\n\n"
                f"新内容：\n{formatted}"
            )
        else:
            prompt = (
                "请将以下对话历史压缩为一段简洁的摘要，保留关键信息和上下文。"
                "用中文回复，不超过300字。\n\n"
                f"{formatted}"
            )

        try:
            response = await use_transport.call(
                messages=[{
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }],
                system_prompt="你是一个摘要助手。请简洁地总结对话。",
                max_tokens=self.max_summary_tokens,
            )
            summary = response.text.strip()
            if not summary:
                return None
            return summary
        except Exception:
            logger.exception("Compression LLM call failed")
            return None

    def _estimate_tokens(self, messages: list[dict], system_prompt: str) -> int:
        return (
            count_messages_tokens(messages, model=self.model)
            + count_messages_tokens([], system_prompt, model=self.model)
        )


def build_simple_compressor(
    settings: Any,
    provider: ProviderProfile,
    api_mode: str,
) -> ContextCompressor | None:
    """Build the built-in compressor implementation."""
    compressor_transport = None
    if settings.compressor_model:
        comp_provider = ProviderProfile(
            name="compressor",
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.compressor_model,
            max_tokens=512,
        )
        from personal_agent.llm.transport_registry import transport_registry

        compressor_transport = transport_registry.get(api_mode, comp_provider)

    return ContextCompressor(
        context_length=provider.context_window or 64_000,
        threshold_ratio=settings.compression_threshold_ratio,
        tail_token_budget=settings.tail_token_budget,
        max_summary_tokens=settings.compressor_max_tokens,
        compressor_transport=compressor_transport,
        model=provider.model or "",
    )


compression_registry.register("simple", build_simple_compressor, aliases=("compressor",))


def prune_old_tool_results(
    messages: list[dict],
    *,
    protect_head: int = 2,
    protect_tail: int = 6,
) -> list[dict]:
    """Remove tool_result blocks from the middle segment (not head/tail)."""
    if len(messages) <= protect_head + protect_tail:
        return messages

    middle = messages[protect_head:-protect_tail]
    result: list[dict] = list(messages[:protect_head])

    for msg in middle:
        content = msg.get("content")
        if isinstance(content, list):
            kept = [b for b in content if b.get("type") != "tool_result"]
            if kept:
                new_msg = dict(msg)
                new_msg["content"] = kept
                result.append(new_msg)
        else:
            result.append(msg)

    result.extend(messages[-protect_tail:])
    result = _clean_orphan_tool_uses(result)
    return repair_native_tool_messages(result)


def fit_tail_token_budget(
    messages: list[dict],
    *,
    model: str = "",
    tail_token_budget: int = 0,
    protect_head: int = 2,
    protect_tail: int = 6,
) -> list[dict]:
    """Truncate/drop tail messages so the tail stays within ``tail_token_budget``."""
    if tail_token_budget <= 0 or not messages:
        return messages
    if len(messages) <= protect_tail:
        head: list[dict] = []
        tail = list(messages)
    else:
        head = list(messages[:-protect_tail])
        tail = list(messages[-protect_tail:])

    fitted = [truncate_message_to_tokens(message, tail_token_budget, model) for message in tail]
    fitted = fit_messages_to_token_budget(
        fitted,
        model=model,
        max_tokens=tail_token_budget,
        protect_head=0,
        protect_last=1,
    )
    return repair_native_tool_messages(head + fitted)


def _clean_orphan_tool_uses(messages: list[dict]) -> list[dict]:
    """Remove tool_use blocks that no longer have a matching tool_result."""
    has_result: set[str] = set()
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for b in content:
                if b.get("type") == "tool_result":
                    tid = b.get("tool_use_id", "")
                    if tid:
                        has_result.add(tid)

    cleaned: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            kept = []
            for b in content:
                if b.get("type") == "tool_use":
                    if b.get("id", "") in has_result:
                        kept.append(b)
                else:
                    kept.append(b)
            if kept:
                new_msg = dict(msg)
                new_msg["content"] = kept
                cleaned.append(new_msg)
        else:
            cleaned.append(msg)
    return cleaned


def _format_messages_for_summary(messages: list[dict]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = []
            for block in content:
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    texts.append(f"[调用工具: {block.get('name')}]")
                elif block.get("type") == "tool_result":
                    result = str(block.get("content", ""))[:200]
                    texts.append(f"[工具结果: {result}]")
            text = " ".join(texts)
        else:
            text = str(content)
        lines.append(f"{role}: {text[:300]}")
    return "\n".join(lines)

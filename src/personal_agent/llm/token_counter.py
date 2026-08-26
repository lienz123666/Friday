"""Token counting via tiktoken with model-aware encoding selection.

Tries to load tiktoken encoding at module init time. If download fails
(proxy issues, no internet), falls back to char/4 heuristic silently.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tiktoken

logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_LIMIT = 64_000  # DeepSeek
IMAGE_INPUT_TOKEN_ESTIMATE = 1500

# Model prefix → tiktoken encoding name. Longer prefixes checked first.
_MODEL_ENCODING_MAP: list[tuple[str, str]] = [
    ("o1-", "o200k_base"),
    ("o3-", "o200k_base"),
    ("gpt-4o-", "o200k_base"),
    ("gpt-4o", "o200k_base"),
    ("chatgpt-4o", "o200k_base"),
    ("gpt-4-", "cl100k_base"),
    ("gpt-4", "cl100k_base"),
    ("gpt-3.5-turbo-", "cl100k_base"),
    ("gpt-3.5-turbo", "cl100k_base"),
    ("gpt-35-turbo", "cl100k_base"),
    ("deepseek-", "cl100k_base"),
    ("deepseek", "cl100k_base"),
    ("text-davinci-003", "p50k_base"),
    ("text-davinci-002", "p50k_base"),
    ("text-davinci-001", "r50k_base"),
    ("davinci", "r50k_base"),
    ("text-embedding-ada-002", "cl100k_base"),
    ("text-embedding-3-", "cl100k_base"),
    ("gpt-3.5", "cl100k_base"),
    ("gpt35", "cl100k_base"),
    ("claude-", "cl100k_base"),
    ("claude", "cl100k_base"),
]

# Module-level cache — preload tiktoken at import time, fall back on failure
_tiktoken: object = None  # Will be the tiktoken module on success
_encodings: dict[str, object] = {}
_tiktoken_available = False


def _init_tiktoken() -> None:
    """Try to initialise tiktoken. Runs once at module import time."""
    global _tiktoken, _tiktoken_available  # noqa: PLW0603
    try:
        import tiktoken as _mod
        _tiktoken = _mod
        _tiktoken_available = True
        logger.debug("tiktoken loaded successfully")
    except ImportError:
        logger.info("tiktoken not installed, using char/4 heuristic")
    except Exception:
        logger.info("tiktoken init failed (proxy?), using char/4 heuristic")


def _get_encoding(model: str) -> object | None:
    """Get a cached tiktoken Encoding for the given model, or None on failure."""
    global _tiktoken, _tiktoken_available  # noqa: PLW0603
    if not _tiktoken_available:
        return None

    normalized = model.strip().lower()
    enc_name = "cl100k_base"
    for prefix, name in _MODEL_ENCODING_MAP:
        if normalized.startswith(prefix):
            enc_name = name
            break

    # Cache by encoding name — only one download attempt
    if enc_name not in _encodings:
        try:
            enc = _tiktoken.get_encoding(enc_name)  # type: ignore[union-attr]
            _encodings[enc_name] = enc
        except Exception:
            logger.warning("tiktoken encoding '%s' unavailable, using char/4", enc_name)
            _encodings[enc_name] = None  # mark as failed permanently
    result = _encodings[enc_name]
    return result if result is not None else None


# Init once at import
_init_tiktoken()


def estimate_tokens(text: str, model: str = "") -> int:
    """Token count using tiktoken. Falls back to char/4 heuristic on failure.

    When model is empty, uses cl100k_base (DeepSeek / GPT-4 compatible).
    """
    if not text:
        return 0
    enc = _get_encoding(model)
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))  # type: ignore[union-attr]


def tokenizer_status() -> dict:
    """Return tokenizer health for CLI/doctor diagnostics."""
    cached = {
        name: {
            "available": enc is not None,
            "fallback": enc is None,
        }
        for name, enc in sorted(_encodings.items())
    }
    return {
        "tiktoken_available": _tiktoken_available,
        "fallback_active": (not _tiktoken_available) or any(enc is None for enc in _encodings.values()),
        "default_encoding": "cl100k_base",
        "cached_encodings": cached,
    }


def count_messages_tokens(
    messages: list[dict],
    system_prompt: str = "",
    model: str = "",
) -> int:
    """Sum token counts across messages + system prompt."""
    total = estimate_tokens(system_prompt, model)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content, model)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type in {"image_url", "image"}:
                        total += IMAGE_INPUT_TOKEN_ESTIMATE
                        continue
                    total += estimate_tokens(block.get("text", ""), model)
                    if block_type == "tool_use":
                        total += estimate_tokens(str(block.get("input", {})), model)
                    if block_type == "tool_result":
                        total += estimate_tokens(str(block.get("content", "")), model)
    return total


TRUNCATION_MARK = "\n...[truncated]"


def truncate_text_to_tokens(
    text: str,
    max_tokens: int,
    model: str = "",
    *,
    suffix: str = TRUNCATION_MARK,
) -> str:
    """Keep a prefix of ``text`` whose token count fits in ``max_tokens``."""
    if max_tokens <= 0 or not text:
        return ""
    if estimate_tokens(text, model) <= max_tokens:
        return text
    suffix_tokens = estimate_tokens(suffix, model) if suffix else 0
    budget = max(1, max_tokens - suffix_tokens)
    # Bound the search window: char/4 heuristic is ~1 token per 4 chars.
    hi = min(len(text), max(budget * 8, budget))
    lo = 0
    best = ""
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid]
        if estimate_tokens(candidate, model) <= budget:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    trimmed = best.rstrip()
    return trimmed + suffix if suffix else trimmed


def _block_text(block: dict) -> str:
    if block.get("type") == "tool_result":
        return str(block.get("content") or "")
    return str(block.get("text") or "")


def _set_block_text(block: dict, text: str) -> None:
    if block.get("type") == "tool_result":
        block["content"] = text
    else:
        block["text"] = text


def _is_truncatable_block(block: object) -> bool:
    return isinstance(block, dict) and block.get("type") in {"text", "tool_result"}


def truncate_message_to_tokens(message: dict, max_tokens: int, model: str = "") -> dict:
    """Return a copy of ``message`` whose estimated tokens fit in ``max_tokens``."""
    import copy

    if max_tokens <= 0:
        return {"role": message.get("role", "user"), "content": [{"type": "text", "text": ""}]}
    new_msg = copy.deepcopy(message)
    if count_messages_tokens([new_msg], model=model) <= max_tokens:
        return new_msg

    content = new_msg.get("content")
    if isinstance(content, str):
        new_msg["content"] = truncate_text_to_tokens(content, max_tokens, model)
        return new_msg
    if not isinstance(content, list):
        new_msg["content"] = [{"type": "text", "text": truncate_text_to_tokens(str(content), max_tokens, model)}]
        return new_msg

    truncatable = [block for block in content if _is_truncatable_block(block)]
    if not truncatable:
        return new_msg

    # Repeatedly shrink the largest truncatable block until the message fits.
    for _ in range(24):
        current = count_messages_tokens([new_msg], model=model)
        if current <= max_tokens:
            return new_msg
        largest = max(truncatable, key=lambda block: estimate_tokens(_block_text(block), model))
        text = _block_text(largest)
        if not text:
            break
        block_tokens = estimate_tokens(text, model)
        overflow = current - max_tokens
        target = max(8, block_tokens - overflow)
        if target >= block_tokens:
            target = max(8, block_tokens // 2)
        _set_block_text(largest, truncate_text_to_tokens(text, target, model))
        if _block_text(largest) == text:
            break
    return new_msg


def fit_messages_to_token_budget(
    messages: list[dict],
    *,
    model: str = "",
    max_tokens: int,
    protect_head: int = 2,
    protect_last: int = 1,
) -> list[dict]:
    """Drop/truncate messages so the list fits ``max_tokens``.

    Never drops the last ``protect_last`` messages; truncates them instead.
    """
    import copy

    if max_tokens <= 0:
        return []
    result = [copy.deepcopy(message) for message in messages]
    result = [truncate_message_to_tokens(message, max_tokens, model) for message in result]
    if count_messages_tokens(result, model=model) <= max_tokens:
        return result

    head = max(0, int(protect_head or 0))
    tail = max(1, int(protect_last or 1))
    while len(result) > head + tail:
        if count_messages_tokens(result, model=model) <= max_tokens:
            return result
        drop_at = min(head, len(result) - tail - 1)
        if drop_at < 0:
            break
        result.pop(drop_at)

    if count_messages_tokens(result, model=model) <= max_tokens:
        return result
    per_cap = max(32, max_tokens // max(len(result), 1))
    return [truncate_message_to_tokens(message, per_cap, model) for message in result]


def count_tools_tokens(tools: list[dict], model: str = "") -> int:
    """Token estimate for tool definitions."""
    total = 0
    for tool in tools:
        total += estimate_tokens(tool.get("name", ""), model)
        total += estimate_tokens(tool.get("description", ""), model)
        total += estimate_tokens(
            str(tool.get("input_schema", tool.get("parameters", {}))), model
        )
    return total


def context_usage(
    messages: list[dict],
    system_prompt: str = "",
    tools: list[dict] | None = None,
    context_limit: int = 0,
    provider_name: str = "",
    model: str = "",
) -> dict:
    """Estimate context window usage.

    Returns dict with keys: used, limit, percent, system, messages, tools.
    context_limit=0 → auto-detect from model name.
    """
    if context_limit <= 0:
        from personal_agent.llm.provider import _detect_context_window
        context_limit = _detect_context_window(model)

    sys_tok = estimate_tokens(system_prompt, model)
    msg_tok = count_messages_tokens(messages, model=model)
    tool_tok = count_tools_tokens(tools or [], model=model)
    used = sys_tok + msg_tok + tool_tok
    return {
        "used": used,
        "limit": context_limit,
        "remaining": max(0, context_limit - used),
        "percent": round(used / max(context_limit, 1) * 100, 1),
        "system": sys_tok,
        "messages": msg_tok,
        "tools": tool_tok,
    }

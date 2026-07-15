"""Text sanitization for API and persistence boundaries.

`clean_*` only repairs invalid Unicode for live API / embedding paths.

Persistence callers must use the `sanitize_persistence_*` interface so secrets
do not reach SQLite, JSONL audit logs, session exports, or CLI tool-run views.

Field classification for nested JSON:

- ``public`` — kept after Unicode cleanup and content redaction
- ``sensitive`` / ``secret`` — values under secret-like keys become ``[REDACTED]``
- ``debug-opt-in`` — omitted from default persistence (e.g. raw artifact payloads)
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from personal_agent.tools.redact import redact


DEFAULT_PERSISTED_TOOL_OUTPUT_CHARS = 8_000
DEFAULT_PERSISTED_SUMMARY_CHARS = 2_000
DEFAULT_PERSISTED_METADATA_CHARS = 2_000

_SECRET_FIELD_NAMES = frozenset({
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "credential",
    "credentials",
    "cookie",
    "set_cookie",
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "session_token",
    "client_secret",
    "private_key",
    "x_api_key",
})

_SECRET_FIELD_SUFFIXES = (
    "_api_key",
    "_apikey",
    "_token",
    "_secret",
    "_password",
    "_passwd",
    "_cookie",
    "_credential",
    "_credentials",
    "_authorization",
)

# Usage counters like cache_hit_tokens stay public.
_PUBLIC_FIELD_SUFFIXES = (
    "_tokens",
    "_token_count",
    "_token_budget",
)


class PersistenceClass(str, Enum):
    PUBLIC = "public"
    SENSITIVE = "sensitive"
    SECRET = "secret"
    DEBUG_OPT_IN = "debug-opt-in"


def clean_text(value: Any) -> str:
    """Return UTF-8 encodable text, replacing invalid surrogate code points."""
    text = "" if value is None else str(value)
    return text.encode("utf-8", errors="replace").decode("utf-8")


def clean_payload(value: Any) -> Any:
    """Recursively clean strings in JSON-like data structures."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clean_payload(item) for item in value)
    if isinstance(value, dict):
        return {
            clean_text(key) if isinstance(key, str) else key: clean_payload(item)
            for key, item in value.items()
        }
    return value


def classify_persistence_field(key: str) -> PersistenceClass:
    """Classify a JSON object key for persistence policy."""
    normalized = key.strip().lower().replace("-", "_")
    if not normalized:
        return PersistenceClass.PUBLIC
    if normalized in _SECRET_FIELD_NAMES:
        return PersistenceClass.SECRET
    if any(normalized.endswith(suffix) for suffix in _PUBLIC_FIELD_SUFFIXES):
        return PersistenceClass.PUBLIC
    if any(normalized.endswith(suffix) for suffix in _SECRET_FIELD_SUFFIXES):
        return PersistenceClass.SECRET
    if normalized in {"data", "raw", "raw_output", "payload", "body", "content_bytes"}:
        return PersistenceClass.DEBUG_OPT_IN
    return PersistenceClass.PUBLIC


_PERSISTENCE_OMISSION_MARKER = " chars omitted before persistence)"


def sanitize_persistence_text(value: Any, *, max_chars: int | None = None) -> str:
    """Return UTF-8-safe, redacted text suitable for persistent storage."""
    text = redact(clean_text(value))
    if max_chars is None:
        return text
    # Keep a second sanitize pass (DB + service/query) from stacking truncation notes.
    if _PERSISTENCE_OMISSION_MARKER in text and len(text) <= max_chars + 80:
        return text
    if len(text) > max_chars:
        omitted = len(text) - max_chars
        return f"{text[:max_chars]}\n\n...({omitted}{_PERSISTENCE_OMISSION_MARKER}"
    return text


def sanitize_persistence_payload(
    value: Any,
    *,
    max_string_chars: int | None = None,
) -> Any:
    """Recursively sanitize JSON-like data and redact values under secret keys."""
    if isinstance(value, str):
        return sanitize_persistence_text(value, max_chars=max_string_chars)
    if isinstance(value, list):
        return [
            sanitize_persistence_payload(item, max_string_chars=max_string_chars)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            sanitize_persistence_payload(item, max_string_chars=max_string_chars)
            for item in value
        ]
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for raw_key, item in value.items():
            key = clean_text(raw_key) if isinstance(raw_key, str) else raw_key
            if not isinstance(key, str):
                sanitized[key] = sanitize_persistence_payload(
                    item,
                    max_string_chars=max_string_chars,
                )
                continue
            field_class = classify_persistence_field(key)
            if field_class in {PersistenceClass.SECRET, PersistenceClass.SENSITIVE}:
                sanitized[key] = "[REDACTED]"
            elif field_class is PersistenceClass.DEBUG_OPT_IN:
                continue
            else:
                sanitized[key] = sanitize_persistence_payload(
                    item,
                    max_string_chars=max_string_chars,
                )
        return sanitized
    return value


def sanitize_tool_artifacts(value: Any) -> list[dict[str, Any]]:
    """Persist only the stable, non-payload artifact summary fields."""
    allowed = (
        "kind", "name", "mime_type", "encoded_size", "has_data",
        "has_uri", "uri_scheme",
    )
    items = value if isinstance(value, list) else []
    sanitized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        projected: dict[str, Any] = {}
        for key in allowed:
            if key not in item:
                continue
            projected[key] = sanitize_persistence_payload(
                item[key],
                max_string_chars=500,
            )
        if "data" in item and "has_data" not in projected:
            projected["has_data"] = True
        if "uri" in item and "has_uri" not in projected:
            projected["has_uri"] = True
            if "uri_scheme" not in projected:
                uri = str(item.get("uri") or "")
                if ":" in uri:
                    projected["uri_scheme"] = sanitize_persistence_text(
                        uri.split(":", 1)[0],
                        max_chars=32,
                    )
        sanitized.append(projected)
    return sanitized


def sanitize_tool_run_for_persistence(run: dict[str, Any]) -> dict[str, Any]:
    """Return a safe projection of one tool-run record for storage or CLI display."""
    projected = dict(run)
    projected["input_summary"] = sanitize_persistence_text(
        run.get("input_summary") or "",
        max_chars=DEFAULT_PERSISTED_SUMMARY_CHARS,
    )
    projected["output_summary"] = sanitize_persistence_text(
        run.get("output_summary") or "",
        max_chars=DEFAULT_PERSISTED_SUMMARY_CHARS,
    )
    full_output = str(run.get("full_output") or "")
    projected["full_output"] = sanitize_persistence_text(
        full_output,
        max_chars=DEFAULT_PERSISTED_TOOL_OUTPUT_CHARS,
    )
    if len(full_output) > DEFAULT_PERSISTED_TOOL_OUTPUT_CHARS:
        projected["output_truncated"] = True
    else:
        projected["output_truncated"] = bool(run.get("output_truncated", False))
    projected["artifacts"] = sanitize_tool_artifacts(run.get("artifacts") or [])
    projected["result_metadata"] = sanitize_persistence_payload(
        run.get("result_metadata") or {},
        max_string_chars=DEFAULT_PERSISTED_METADATA_CHARS,
    )
    projected["error"] = sanitize_persistence_text(
        run.get("error") or "",
        max_chars=DEFAULT_PERSISTED_SUMMARY_CHARS,
    )
    for key in ("tool_name", "tool_use_id", "session_id", "session_key", "turn_id"):
        if key in projected:
            projected[key] = sanitize_persistence_text(projected.get(key) or "", max_chars=500)
    return projected

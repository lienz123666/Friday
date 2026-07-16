"""Controlled local-file access for tools and future ingest/RAG paths.

All model-supplied paths must go through resolve + Sandbox checks here
before any bytes are read. Providers and memory layers should consume the
returned text (or Path already validated), never a raw user path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from personal_agent.tools.sandbox import get_sandbox

DEFAULT_MAX_READ_CHARS = 50_000


def resolve_readable_path(path: str, *, access: str = "read") -> tuple[Path | None, str | None]:
    """Resolve ``path`` and enforce sandbox roots / blocked patterns / grants.

    Returns ``(resolved_path, None)`` on success, or ``(None, error_message)``.
    """
    text = str(path or "").strip()
    if not text:
        return None, "Error: path is required"

    sandbox = get_sandbox()
    try:
        resolved = sandbox.resolve(text)
    except Exception as exc:
        return None, f"Error: {exc}"

    error = sandbox.check_path(resolved, access=access)
    if error:
        return None, error
    return resolved, None


def file_read_precheck(input_: dict[str, Any]) -> str | None:
    """Hard precheck for tools that accept a filesystem ``path`` argument."""
    path = str(input_.get("path") or "").strip()
    if not path:
        return None
    _resolved, error = resolve_readable_path(path, access="read")
    return error


def read_sandboxed_text(
    path: str,
    *,
    max_chars: int = DEFAULT_MAX_READ_CHARS,
    access: str = "read",
) -> str:
    """Read a local text file only after sandbox validation.

    On denial returns an ``Error: ...`` string (same convention as file tools).
    """
    resolved, error = resolve_readable_path(path, access=access)
    if error:
        return error
    assert resolved is not None

    if not resolved.exists():
        return f"Error: file not found: {path}"
    if resolved.is_dir():
        return f"Error: '{path}' is a directory"

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"Error: {exc}"

    limit = max(1, int(max_chars or DEFAULT_MAX_READ_CHARS))
    if len(content) > limit:
        content = content[:limit] + f"\n\n...(truncated {len(content) - limit} bytes)"
    return content


def extract_sandboxed_document(
    path: str,
    *,
    max_chars: int = 12_000,
    access: str = "read",
) -> tuple[str | None, str | None]:
    """Extract text from a sandboxed path (txt/md/pdf/docx).

    Returns ``(text, None)`` or ``(None, error_message)``. Intended for any
    future memory/RAG ingest so providers never receive a bare user path.
    """
    resolved, error = resolve_readable_path(path, access=access)
    if error:
        return None, error
    assert resolved is not None

    if not resolved.exists() or not resolved.is_file():
        return None, f"Error: file not found: {path}"

    try:
        from personal_agent.attachments.text_extract import (
            AttachmentTextExtractError,
            extract_attachment_text,
        )

        extracted = extract_attachment_text(resolved, max_chars=max_chars)
    except AttachmentTextExtractError as exc:
        detail = exc.detail or exc.reason
        return None, f"Error: cannot extract text ({detail})"
    except Exception as exc:
        return None, f"Error: {exc}"

    return extracted.text, None

"""AD-014: memory ingest must not bypass the unified file sandbox."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_memory_ingest_tool_is_not_registered():
    """Product direction: do not restore memory_ingest; knowledge RAG is separate."""
    import personal_agent.plugins.builtin.tools.builtin.file_read  # noqa: F401
    from personal_agent.memory.tools import memory_buffer_tool_entry, memory_tool_entry
    from personal_agent.tools.registry import tool_registry

    tool_registry.register(memory_tool_entry())
    tool_registry.register(memory_buffer_tool_entry())
    try:
        assert tool_registry.get("memory_ingest") is None
        assert "memory_ingest" not in {item["name"] for item in tool_registry.catalog()}
        memory = tool_registry.get("memory")
        assert memory is not None
        actions = memory.schema["properties"]["action"]["enum"]
        assert "ingest" not in actions
        assert "path" not in memory.schema["properties"]
    finally:
        tool_registry.unregister("memory")
        tool_registry.unregister("memory_buffer")


def test_extract_sandboxed_document_allows_workspace_file(tmp_path: Path):
    from personal_agent.tools.file_access import extract_sandboxed_document
    from personal_agent.tools.sandbox import init_sandbox

    init_sandbox([tmp_path], ["**/.env", "**/.env.*", "**/.ssh/**", "**/.git/**"])
    target = tmp_path / "notes.md"
    target.write_text("workspace note", encoding="utf-8")

    text, error = extract_sandboxed_document(str(target))
    assert error is None
    assert text == "workspace note"


@pytest.mark.parametrize(
    "relative",
    [".env", "project/.env.local", ".ssh/id_rsa", ".git/config"],
)
def test_extract_sandboxed_document_blocks_sensitive_paths(tmp_path: Path, relative: str):
    from personal_agent.tools.file_access import extract_sandboxed_document
    from personal_agent.tools.sandbox import init_sandbox

    init_sandbox([tmp_path], ["**/.env", "**/.env.*", "**/.ssh/**", "**/.git/**"])
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret", encoding="utf-8")

    text, error = extract_sandboxed_document(str(target))
    assert text is None
    assert error is not None
    assert "blocked" in error.lower() or "path" in error.lower()


def test_extract_sandboxed_document_blocks_outside_root(tmp_path: Path):
    from personal_agent.tools.file_access import extract_sandboxed_document
    from personal_agent.tools.sandbox import init_sandbox

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("leaked", encoding="utf-8")
    init_sandbox([workspace], ["**/.env", "**/.ssh/**"])

    text, error = extract_sandboxed_document(str(secret))
    assert text is None
    assert error is not None
    assert "outside" in error.lower() or "sandbox" in error.lower()


def test_extract_sandboxed_document_blocks_symlink_escape(tmp_path: Path):
    from personal_agent.tools.file_access import extract_sandboxed_document
    from personal_agent.tools.sandbox import init_sandbox

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("leaked-via-symlink", encoding="utf-8")
    link = workspace / "notes.txt"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    init_sandbox([workspace], ["**/.env", "**/.ssh/**"])
    text, error = extract_sandboxed_document(str(link))
    assert text is None
    assert error is not None
    assert "outside" in error.lower() or "sandbox" in error.lower() or "granted" in error.lower()


@pytest.mark.asyncio
async def test_read_tool_precheck_rejects_env_before_handler(tmp_path: Path):
    import personal_agent.plugins.builtin.tools.builtin.file_read  # noqa: F401
    from personal_agent.tools.executor import execute_tool_call_result
    from personal_agent.tools.sandbox import init_sandbox

    init_sandbox([tmp_path], ["**/.env", "**/.env.*", "**/.ssh/**"])
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")

    result = await execute_tool_call_result(
        {"id": "r1", "name": "read", "input": {"path": str(tmp_path / ".env")}},
    )
    assert result.status == "denied"
    assert result.category == "precheck"
    assert "blocked" in result.error.lower() or "path" in result.error.lower()


@pytest.mark.asyncio
async def test_legacy_raw_path_ingest_pattern_is_blocked_by_shared_seam(tmp_path: Path):
    """Old memory_ingest handed Path(user_path) to providers; shared seam must refuse."""
    from personal_agent.tools.file_access import extract_sandboxed_document, resolve_readable_path
    from personal_agent.tools.sandbox import init_sandbox

    workspace = tmp_path / "ws"
    workspace.mkdir()
    init_sandbox([workspace], ["**/.env", "**/.ssh/**"])

    outside = tmp_path / ".ssh" / "id_rsa"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("PRIVATE KEY", encoding="utf-8")

    # Raw Path would succeed — that is exactly the AD-014 bypass.
    assert outside.read_text(encoding="utf-8") == "PRIVATE KEY"

    resolved, error = resolve_readable_path(str(outside))
    assert resolved is None
    assert error is not None

    text, extract_error = extract_sandboxed_document(str(outside))
    assert text is None
    assert extract_error is not None

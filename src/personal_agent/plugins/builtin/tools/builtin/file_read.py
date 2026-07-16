"""Read files within sandbox boundaries.

Security is enforced by the unified sandbox (roots + blocked patterns)
via the shared file_access helpers — the same seam future ingest/RAG must use.
"""

from personal_agent.tools.entry import ToolEntry
from personal_agent.tools.file_access import (
    DEFAULT_MAX_READ_CHARS,
    file_read_precheck,
    read_sandboxed_text,
)
from personal_agent.tools.registry import tool_registry

MAX_READ_BYTES = DEFAULT_MAX_READ_CHARS


async def _file_read(path: str) -> str:
    return read_sandboxed_text(path, max_chars=MAX_READ_BYTES)


tool_registry.register(ToolEntry(
    name="read",
    description="Read a file from the agent's allowed directories. Accepts relative or absolute paths.",
    schema={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to file, e.g. 'notes/ideas.txt' or 'C:/Users/.../file.md'"},
        },
        "required": ["path"],
    },
    handler=_file_read,
    toolset="builtin",
    permission_category="read",
    tags=["file", "read"],
    risk_level="low",
    usage_hint="Use to inspect a known file path before editing or summarizing it.",
    precheck=file_read_precheck,
))

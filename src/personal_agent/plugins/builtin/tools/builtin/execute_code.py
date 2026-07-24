"""Python code execution gate (AD-038).

No OS-level code sandbox is shipped yet. The tool stays registered so callers
get an explicit, audited denial instead of an unknown-tool error.
"""

from __future__ import annotations

from personal_agent.tools.code_runner import DEFAULT_TIMEOUT, MAX_TIMEOUT
from personal_agent.tools.entry import ToolEntry
from personal_agent.tools.registry import tool_registry

_UNAVAILABLE_MESSAGE = (
    "Error: execute_code is disabled because this installation has no "
    "OS-level code sandbox. Use bash with project Python only when explicitly "
    "authorized; do not treat this tool as a substitute for file, network, "
    "or shell permissions."
)


async def _execute_code(code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    del code, timeout
    return _UNAVAILABLE_MESSAGE


def _precheck(_: dict) -> str:
    """Hard block before permission prompts or handler dispatch."""
    return _UNAVAILABLE_MESSAGE


tool_registry.register(
    ToolEntry(
        name="execute_code",
        description=(
            "Python code execution is unavailable because this installation "
            "does not provide an OS-level sandbox. Do not use this tool as a "
            "substitute for file, network, shell, or process permissions."
        ),
        schema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code (tool currently disabled).",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout seconds (default {DEFAULT_TIMEOUT}, max {MAX_TIMEOUT}).",
                },
            },
            "required": ["code"],
        },
        handler=_execute_code,
        toolset="builtin",
        permission_category="bash",
        tags=["code", "python", "requires-isolation"],
        risk_level="high",
        usage_hint="Unavailable until an OS-level code sandbox is installed and verified.",
        precheck=_precheck,
        approval_mode="prompt",
        is_parallel_safe=False,
        is_destructive=True,
    )
)

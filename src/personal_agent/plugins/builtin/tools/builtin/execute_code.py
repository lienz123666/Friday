"""High-risk Python execution via an honest subprocess backend (AD-038)."""

from __future__ import annotations

from personal_agent.security.models import ResourceRequirement
from personal_agent.tools.code_runner import DEFAULT_TIMEOUT, MAX_TIMEOUT, get_code_runner
from personal_agent.tools.entry import ToolEntry
from personal_agent.tools.registry import tool_registry
from personal_agent.tools.sandbox import get_sandbox

_AVAILABLE_MODULES_HINT = (
    "Stdlib only in the subprocess interpreter; no agent venv packages."
)


def _execute_code_resources(_inp: dict) -> list[ResourceRequirement]:
    """Require network + workspace write so read-only modes fail closed."""
    sandbox = get_sandbox()
    root = str(sandbox.roots[0]) if sandbox.roots else "."
    return [
        ResourceRequirement("filesystem", root, "write", "execute_code"),
        ResourceRequirement("network", "python-subprocess", "connect", "execute_code"),
    ]


async def _execute_code(code: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    runner = get_code_runner()
    return await runner.run(code, timeout=timeout)


tool_registry.register(
    ToolEntry(
        name="execute_code",
        description=(
            "Run Python in a separate subprocess with a temp working directory and "
            "reduced environment variables. This is high risk: it is NOT OS-level "
            "isolation and code retains the host user's privileges. Requires explicit "
            "approval in default security modes and is blocked in read-only mode."
        ),
        schema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute (stdlib only).",
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
        permission_category="destructive",
        risk_level="high",
        approval_mode="prompt",
        resource_resolver=_execute_code_resources,
        is_parallel_safe=False,
        is_destructive=True,
        usage_hint=_AVAILABLE_MODULES_HINT,
    )
)

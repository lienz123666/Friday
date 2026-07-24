"""Honest Python code execution backend (AD-038 seam)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
import textwrap
from dataclasses import dataclass

from personal_agent.tools.env_filter import filter_env

logger = logging.getLogger(__name__)

MAX_OUTPUT = 8000
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120


@dataclass(frozen=True, slots=True)
class CodeRunnerCapabilities:
    """Truthful snapshot of what the current backend actually provides."""

    backend: str
    os_isolated: bool
    network_isolated: bool
    host_fs_isolated: bool
    uses_temp_workdir: bool
    detail: str = ""


class CodeRunner:
    """Run untrusted Python in a subprocess with minimal, explicit guarantees."""

    def capabilities(self) -> CodeRunnerCapabilities:
        return CodeRunnerCapabilities(
            backend="subprocess",
            os_isolated=False,
            network_isolated=False,
            host_fs_isolated=False,
            uses_temp_workdir=True,
            detail=(
                "Runs as the same OS user in a temp working directory with a reduced "
                "environment. This is not a container or VM sandbox."
            ),
        )

    async def run(self, code: str, *, timeout: int = DEFAULT_TIMEOUT) -> str:
        timeout = min(max(int(timeout or DEFAULT_TIMEOUT), 5), MAX_TIMEOUT)
        code = textwrap.dedent(str(code or "")).strip()
        if not code:
            return "Error: empty code"

        work_dir = tempfile.mkdtemp(prefix="pyexec_")
        try:
            env = filter_env()
            keep = {
                "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TMP", "TEMP", "TMPDIR",
                "PATH", "PATHEXT", "COMSPEC", "USERNAME", "USER", "HOME",
                "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
            }
            env = {k: v for k, v in env.items() if k in keep or k.startswith("PYTHON")}

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-c",
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return f"Error: code execution timed out after {timeout}s"

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            lines: list[str] = []
            if out:
                lines.append(out)
            if err:
                lines.append(f"[stderr]\n{err}")
            if not lines:
                lines.append("(no output)")
            result = "\n".join(lines)
            if len(result) > MAX_OUTPUT:
                result = result[:MAX_OUTPUT] + (
                    f"\n\n...(truncated {len(result) - MAX_OUTPUT} more chars)"
                )
            return result
        except Exception as exc:
            logger.exception("execute_code failed")
            return f"Error: {exc}"
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


_default_runner = CodeRunner()


def get_code_runner() -> CodeRunner:
    return _default_runner

"""Compatibility exports for plugin data models."""

from personal_agent.plugins.core.models import (
    CommandEntry,
    HookRegistration,
    LoadedPlugin,
    PluginManifest,
    PluginStatus,
)

__all__ = [
    "CommandEntry",
    "HookRegistration",
    "LoadedPlugin",
    "PluginManifest",
    "PluginStatus",
]

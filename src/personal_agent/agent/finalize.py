"""finalize_turn — persist new messages to DB, update session counters."""

from __future__ import annotations

import logging

from personal_agent.conversation.history_events import persist_api_messages

logger = logging.getLogger(__name__)


def unpack_message(msg: dict) -> tuple[str, str, list | None, str | None, str | None]:
    """Legacy unpack helper for callers that still flatten one API message."""
    from personal_agent.conversation.history_events import api_message_to_events

    events = api_message_to_events(msg)
    if not events:
        return msg.get("role", "user"), "", None, None, None
    if len(events) == 1:
        event = events[0]
        return (
            event.storage_role(),
            event.content,
            event.tool_calls,
            event.tool_name,
            event.tool_use_id,
        )
    # Multiple events: join text for compatibility; canonical save uses persist_api_messages.
    role = events[0].storage_role()
    content = "\n".join(event.content for event in events if event.content)
    tool_calls = None
    tool_name = None
    tool_call_id = None
    for event in events:
        if event.tool_calls:
            tool_calls = event.tool_calls
            tool_name = event.tool_name
            tool_call_id = event.tool_use_id
            break
    return role, content, tool_calls, tool_name, tool_call_id


async def finalize_turn(db, session_id: str, ctx, previous_message_count: int) -> None:
    """Persist new messages added during this turn."""
    new_messages = ctx.messages[previous_message_count:]
    if not new_messages:
        return

    for msg in new_messages:
        for event in persist_api_messages([msg]):
            await db.save_conversation_event(session_id, event)

    await db.update_last_active(session_id, increment_message=True)
    logger.debug("Persisted %d messages for session %s", len(new_messages), session_id)

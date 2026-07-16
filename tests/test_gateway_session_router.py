"""Gateway session routing rules."""

from __future__ import annotations

from types import SimpleNamespace

from personal_agent.gateway.session_router import GatewaySessionRouter, clean_session_name


def _source(chat_id: str = "c1", user_id: str = "u1"):
    return SimpleNamespace(platform="telegram", chat_id=chat_id, user_id=user_id)


def test_clean_session_name_strips_colons():
    assert clean_session_name("work:ops") == "work_ops"
    assert clean_session_name("  ") == "default"


def test_gateway_session_router_base_active_and_named_keys():
    router = GatewaySessionRouter()
    source = _source()

    assert router.base_key(source) == "telegram:c1:u1"
    assert router.active_key(source) == "telegram:c1:u1"
    assert router.named_key(source, "work") == "telegram:c1:work:u1"
    assert router.current_for_list(source) == "telegram:c1:u1"


def test_gateway_session_router_switch_rename_and_delete_active_session():
    router = GatewaySessionRouter()
    source = _source()

    switched = router.switch(source, "work")
    renamed_key = "telegram:c1:renamed:u1"
    router.rename(source, switched, renamed_key)
    fallback = router.delete(source, renamed_key)

    assert switched == "telegram:c1:work:u1"
    assert fallback == "telegram:c1:u1"
    assert router.active_key(source) == "telegram:c1:u1"
    assert router.overrides == {}


def test_gateway_session_router_renames_base_session_to_override():
    router = GatewaySessionRouter()
    source = _source()

    router.rename(source, "telegram:c1:u1", "telegram:c1:renamed:u1")

    assert router.active_key(source) == "telegram:c1:renamed:u1"


def test_gateway_session_router_accepts_initial_overrides():
    router = GatewaySessionRouter({"telegram:c1:u1": "telegram:c1:work:u1"})

    assert router.active_key(_source()) == "telegram:c1:work:u1"
    assert router.active_key(_source("c2")) == "telegram:c2:u1"


def test_named_sessions_with_same_name_are_isolated_across_chats():
    """AD-027: same user + same name in two chats must not share a session key."""
    router = GatewaySessionRouter()
    chat_a = _source("group-a")
    chat_b = _source("group-b")

    key_a = router.switch(chat_a, "work")
    key_b = router.switch(chat_b, "work")

    assert key_a == "telegram:group-a:work:u1"
    assert key_b == "telegram:group-b:work:u1"
    assert key_a != key_b
    assert router.active_key(chat_a) == key_a
    assert router.active_key(chat_b) == key_b
    # Overrides are keyed by base chat identity, so chats stay independent.
    assert router.overrides == {
        "telegram:group-a:u1": key_a,
        "telegram:group-b:u1": key_b,
    }

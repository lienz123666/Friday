"""AD-044: unified persistence sanitizer regression tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_agent.commands.runtime import _format_tool_run_detail_text
from personal_agent.conversation.query import _normalize_tool_run
from personal_agent.text_safety import (
    DEFAULT_PERSISTED_TOOL_OUTPUT_CHARS,
    PersistenceClass,
    classify_persistence_field,
    clean_text,
    sanitize_persistence_payload,
    sanitize_persistence_text,
    sanitize_tool_run_for_persistence,
)
from personal_agent.tools.audit import audit_log, set_audit_path
from personal_agent.tools.redact import redact


API_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz"
BEARER = "bearer-secret-abcdefghijklmnopqrstuvwxyz"
QUERY = "query-secret-abcdefghijklmnopqrstuvwxyz"
COOKIE = "sessionid=super-secret-cookie-value"


def test_clean_text_does_not_redact_secrets():
    raw = f"key={API_KEY}"
    assert API_KEY in clean_text(raw)


def test_classify_persistence_field_keeps_public_diagnostics():
    assert classify_persistence_field("session_id") is PersistenceClass.PUBLIC
    assert classify_persistence_field("session_key") is PersistenceClass.PUBLIC
    assert classify_persistence_field("cache_hit_tokens") is PersistenceClass.PUBLIC
    assert classify_persistence_field("safe_flag") is PersistenceClass.PUBLIC
    assert classify_persistence_field("api_key") is PersistenceClass.SECRET
    assert classify_persistence_field("Authorization") is PersistenceClass.SECRET
    assert classify_persistence_field("nested_access_token") is PersistenceClass.SECRET
    assert classify_persistence_field("data") is PersistenceClass.DEBUG_OPT_IN


def test_sanitize_persistence_redacts_nested_and_content_secrets():
    payload = sanitize_persistence_payload({
        "session_id": "cli:default:local",
        "cache_hit_tokens": 12,
        "nested": {"api_key": API_KEY, "note": f"Bearer {BEARER}"},
        "url": f"https://example.test/?access_token={QUERY}",
        "data": "raw-debug-bytes",
        "headers": {"Cookie": COOKIE},
    })
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["session_id"] == "cli:default:local"
    assert payload["cache_hit_tokens"] == 12
    assert payload["nested"]["api_key"] == "[REDACTED]"
    assert "data" not in payload
    for secret in (API_KEY, BEARER, QUERY, COOKIE):
        assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_sanitize_tool_run_truncates_and_redacts_full_output():
    long_secret = ("KEEP-" + API_KEY + "-") * 400
    run = sanitize_tool_run_for_persistence({
        "session_id": "sid",
        "session_key": "cli:default:local",
        "tool_name": "demo",
        "input_summary": f"Authorization: Bearer {BEARER}",
        "output_summary": f"https://example.test/?token={QUERY}",
        "full_output": long_secret,
        "artifacts": [{"kind": "file", "name": "x.bin", "data": "PRIVATE", "token": BEARER}],
        "result_metadata": {"password": "hunter2-not-short", "ok": True},
        "error": f"Cookie: {COOKIE}",
    })
    assert API_KEY not in run["full_output"]
    assert BEARER not in run["input_summary"]
    assert QUERY not in run["output_summary"]
    assert COOKIE not in run["error"]
    assert run["output_truncated"] is True
    assert len(run["full_output"]) <= DEFAULT_PERSISTED_TOOL_OUTPUT_CHARS + 80
    assert "chars omitted before persistence)" in run["full_output"]
    assert run["artifacts"] == [{"has_data": True, "kind": "file", "name": "x.bin"}]
    assert run["result_metadata"]["password"] == "[REDACTED]"
    assert run["result_metadata"]["ok"] is True
    # Second pass must not stack omission markers.
    again = sanitize_tool_run_for_persistence(run)
    assert again["full_output"].count("chars omitted before persistence)") == 1


def test_redact_masks_bearer_url_and_cookie():
    text = (
        f"Authorization: Bearer {BEARER}\n"
        f"https://example.test/?access_token={QUERY}\n"
        f"Cookie: {COOKIE}\n"
        f"api_key={API_KEY}"
    )
    redacted = redact(text)
    for secret in (API_KEY, BEARER, QUERY, COOKIE):
        assert secret not in redacted


def test_audit_log_uses_persistence_sanitizer(tmp_path: Path):
    audit_path = tmp_path / "audit.log"
    set_audit_path(audit_path)
    audit_log(
        "web_fetch",
        f"Authorization: Bearer {BEARER}",
        f"https://example.test/?access_token={QUERY}",
        True,
    )
    line = audit_path.read_text(encoding="utf-8")
    assert BEARER not in line
    assert QUERY not in line
    assert ("[REDACTED]" in line) or ("*" in line)


def test_tool_runs_show_projection_hides_plaintext_secrets():
    item = _normalize_tool_run({
        "id": 7,
        "session_id": "sid",
        "session_key": "cli:default:local",
        "tool_name": "demo",
        "status": "success",
        "input_summary": f"Authorization: Bearer {BEARER}",
        "output_summary": "ok",
        "full_output": f"key={API_KEY}; Cookie: {COOKIE}",
        "error": "",
    })
    text = _format_tool_run_detail_text(item)
    payload = json.dumps(item, ensure_ascii=False)
    for secret in (API_KEY, BEARER, COOKIE):
        assert secret not in text
        assert secret not in payload
    assert item["status"] == "success"
    assert item["session_key"] == "cli:default:local"

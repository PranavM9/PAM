"""Maya's synthetic export matches the Claude export layout that M1 reads."""

from __future__ import annotations

import json
import zipfile

from tests.helpers import ROOT, load_tool

FIXTURE = ROOT.parent.parent / "backend" / "tests" / "fixtures" / "claude" / "export.zip"
CONVERSATION_KEYS = {"uuid", "name", "summary", "created_at", "updated_at", "account", "chat_messages"}
MESSAGE_KEYS = {"uuid", "text", "content", "sender", "created_at", "updated_at", "attachments", "files"}
PHONE_LINES = ["my battery dies by 2pm", "the screen corner is cracked",
               "I can spend about $40 a month until my internship in June",
               "Leo wants a better camera for his photo class",
               "Mom asked me to check if our family plan is too expensive"]


def _build(tmp_path):
    out = load_tool("make_export").build(tmp_path / "claude-export.zip")
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["conversations.json"]
        return out, json.loads(zf.read("conversations.json"))


def test_ten_conversations_in_claude_shape(tmp_path):
    _, rows = _build(tmp_path)
    assert len(rows) == 10
    assert len({r["uuid"] for r in rows}) == 10
    assert [r["created_at"] for r in rows] == sorted(r["created_at"] for r in rows)
    for row in rows:
        assert set(row) == CONVERSATION_KEYS
        assert row["name"] and row["summary"] == ""
        for msg in row["chat_messages"]:
            assert set(msg) == MESSAGE_KEYS
            assert msg["sender"] in ("human", "assistant")
            assert msg["content"][0]["type"] == "text" and msg["content"][0]["text"] == msg["text"]


def test_same_keys_as_the_backend_fixture(tmp_path):
    if not FIXTURE.exists():
        import pytest

        pytest.skip("backend Claude fixture not present (mock built on its own)")
    fixture = json.loads(zipfile.ZipFile(FIXTURE).read("conversations.json"))
    _, rows = _build(tmp_path)
    assert set(rows[0]) == set(fixture[0])
    assert set(rows[0]["chat_messages"][0]) == set(fixture[0]["chat_messages"][0])
    fixture_block = next(b for c in fixture for m in c["chat_messages"] for b in m["content"] if b["type"] == "text")
    assert set(rows[0]["chat_messages"][0]["content"][0]) <= set(fixture_block)


def test_four_phone_conversations_and_six_unrelated(tmp_path):
    _, rows = _build(tmp_path)
    user_text = [" ".join(m["text"] for m in r["chat_messages"] if m["sender"] == "human") for r in rows]
    for line in PHONE_LINES:
        assert sum(line in t for t in user_text) == 1, line
    phone = [t for t in user_text if any(line in t for line in PHONE_LINES)]
    assert len(phone) == 4


def test_zip_is_byte_identical(tmp_path):
    tool = load_tool("make_export")
    a = tool.build(tmp_path / "a.zip").read_bytes()
    b = tool.build(tmp_path / "b.zip").read_bytes()
    assert a == b

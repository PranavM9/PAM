"""M1 importer acceptance tests for provider fixtures and malformed exports."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts.common import Source
from pam.contracts.raw import RawConversation
from pam.importers.detect import detect, extract

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _parsed(path: Path, source: str = "auto") -> tuple[list[RawConversation], list[str], str]:
    conversations, errors, selected = extract(path, source)
    validated = [RawConversation.model_validate(item.model_dump()) for item in conversations]
    return validated, errors, selected


def test_fixture_counts_and_contracts_by_source() -> None:
    expected = {"claude": (9, 1), "chatgpt": (5, 1), "gemini": (3, 0)}
    for source, (count, skipped) in expected.items():
        conversations, errors, selected = _parsed(FIXTURES / source / "export.zip")
        assert selected == source
        assert len(conversations) == count
        assert sum("skipped" in error for error in errors) == skipped
        assert all(conversation.source == Source(source) for conversation in conversations)


def test_gemini_prompted_and_details_layouts_are_supported() -> None:
    primary, primary_errors, _ = _parsed(FIXTURES / "gemini" / "export.zip")
    old_layout, old_errors, _ = _parsed(FIXTURES / "gemini" / "MyActivity.details.json")
    assert len(primary) == len(old_layout) == 3
    assert primary_errors == old_errors == []
    assert [m.text for m in primary[0].messages] == [m.text for m in old_layout[0].messages]


def test_gemini_groups_29_minute_gaps_and_splits_31_minute_gaps() -> None:
    conversations, errors, _ = _parsed(FIXTURES / "gemini" / "export.zip")
    assert errors == []
    assert [len(conversation.messages) for conversation in conversations] == [6, 6, 6]
    assert [conversation.source_conversation_id for conversation in conversations] == [
        "726a26fcb2066952cf112bb687a4979a3706dd67",
        "9baccb2b5a5912800fd2ab4de43617cafc149221",
        "149dbdfbcdcb37c5c23fcc7a4105803485a7239d",
    ]


def test_chatgpt_edited_and_regenerated_branches_select_current_path() -> None:
    conversations, errors, _ = _parsed(FIXTURES / "chatgpt" / "export.zip")
    assert len(conversations) == 5
    assert len(errors) == 1 and "empty conversation skipped" in errors[0]
    edited = next(item for item in conversations if item.title == "Edited prompt branch")
    regenerated = next(item for item in conversations if item.title == "Regenerated response")
    edited_text = [message.text for message in edited.messages]
    regenerated_text = [message.text for message in regenerated.messages]
    assert "How do I back up Immich originals and metadata to a NAS?" in edited_text
    assert "Use a scheduled backup that preserves both originals and metadata." in edited_text
    assert "How do I sync my photos?" not in edited_text
    assert "Keep three copies of your data, use two different storage types, and store one copy off-site." in regenerated_text
    assert "Three copies, on two kinds of media, with one off-site." not in regenerated_text


def test_chatgpt_hidden_messages_are_omitted_and_image_is_an_attachment() -> None:
    conversations, _, _ = _parsed(FIXTURES / "chatgpt" / "export.zip")
    photo = next(item for item in conversations if item.title == "Photo library issue")
    assert all("Hidden system context" not in message.text for message in photo.messages)
    image_message = next(message for message in photo.messages if message.attachments)
    assert [(attachment.kind, attachment.name) for attachment in image_message.attachments] == [("image", "image")]


def test_chatgpt_fixture_has_root_message_ids_and_typed_hidden_image_parts() -> None:
    with zipfile.ZipFile(FIXTURES / "chatgpt" / "export.zip") as archive:
        rows = json.loads(archive.read("conversations.json"))
    for conversation in rows:
        mapping = conversation["mapping"]
        roots = [node for node in mapping.values() if node["parent"] is None]
        assert len(roots) == 1
        assert roots[0]["message"] is None
        for node_key, node in mapping.items():
            assert node["id"] == node_key
            if isinstance(node.get("message"), dict):
                assert node["message"]["id"] == node_key
    photo = rows[3]["mapping"]
    hidden = photo["s"]["message"]
    image_part = photo["u"]["message"]["content"]["parts"][0]
    assert hidden["metadata"]["is_hidden"] is True
    assert image_part["content_type"] == "image"


def test_detect_command_reports_source_and_detects_each_fixture() -> None:
    for source in ("claude", "chatgpt", "gemini"):
        path = FIXTURES / source / "export.zip"
        assert detect(path).source == source
        result = runner.invoke(app, ["import", "detect", str(path)])
        assert result.exit_code == 0
        assert result.output.strip() == source


def test_bad_chatgpt_entries_are_reported_and_valid_rows_continue(tmp_path: Path) -> None:
    good = {
        "id": "good-conversation", "title": "Valid", "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["u"]},
            "u": {"id": "u", "message": {"id": "u", "author": {"role": "user"},
                "content": {"parts": ["keep this"]}}, "parent": "root", "children": []},
        }, "current_node": "u",
    }
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps([None, {"id": "broken", "mapping": "bad"}, good]), encoding="utf-8")
    conversations, errors, selected = _parsed(path)
    assert selected == "chatgpt"
    assert len(conversations) == 1 and conversations[0].messages[0].text == "keep this"
    assert len(errors) == 2


def test_chatgpt_hidden_and_empty_messages_are_skipped(tmp_path: Path) -> None:
    nodes = [
        ("hidden", {"role": "assistant", "text": "hidden"}, {"is_hidden": True}),
        ("empty", {"role": "assistant", "text": "   "}, {}),
        ("visible", {"role": "user", "text": "visible message"}, {}),
    ]
    mapping: dict[str, dict] = {"root": {"id": "root", "message": None, "parent": None, "children": ["hidden"]}}
    parent = "root"
    for index, (node_id, content, metadata) in enumerate(nodes):
        next_id = nodes[index + 1][0] if index + 1 < len(nodes) else None
        mapping[node_id] = {
            "id": node_id,
            "parent": parent,
            "children": [next_id] if next_id else [],
            "message": {
                "id": node_id,
                "author": {"role": content["role"]},
                "content": {"parts": [content["text"]]},
                "metadata": metadata,
            },
        }
        parent = node_id
    mapping["root"]["children"] = ["hidden"]
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps([{"id": "hidden-empty", "mapping": mapping, "current_node": "visible"}]), encoding="utf-8")
    conversations, errors, _ = _parsed(path)
    assert errors == []
    assert len(conversations) == 1
    assert [message.text for message in conversations[0].messages] == ["visible message"]


def test_import_parsing_does_not_write_files(tmp_path: Path, monkeypatch) -> None:
    fixture_bytes = (FIXTURES / "gemini" / "export.zip").read_bytes()
    export = tmp_path / "export.zip"
    export.write_bytes(fixture_bytes)
    monkeypatch.chdir(tmp_path)
    conversations, errors, _ = _parsed(export)
    assert len(conversations) == 3 and errors == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["export.zip"]


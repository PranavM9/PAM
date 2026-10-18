"""Memory-use guidance tests: the chat `MEMORY_GUIDE`, the MCP `INSTRUCTIONS`, and tool examples.

Behavior:
    Checks the guide's size and key rules, that the MCP instructions repeat the guide, and that every
    write tool's description carries a worked example that validates against its contract model.
"""

from __future__ import annotations

import json
import re

import pytest

from pam.chat import llm
from pam.core import tokens
from pam.mcp_server import tools
from pam.mcp_server.server import INSTRUCTIONS

MAX_GUIDE_TOKENS = 300
KEY_PHRASES = (
    "add_fact", "supersede_fact", "get_context", "search_memory", "Do not ask permission",
    "user.name", "Never say you saved something unless the tool result says ok", "Never invent memories",
)
EXAMPLE_TOOLS = (
    "add_fact", "supersede_fact", "log_episode", "update_project", "add_skill", "update_working_memory",
)


def test_guide_is_under_the_token_budget():
    assert tokens.count(llm.MEMORY_GUIDE) < MAX_GUIDE_TOKENS


@pytest.mark.parametrize("phrase", KEY_PHRASES)
def test_guide_and_mcp_instructions_share_the_key_rules(phrase):
    assert phrase in llm.MEMORY_GUIDE
    assert phrase in INSTRUCTIONS


def test_instructions_are_the_same_text_as_the_guide():
    assert INSTRUCTIONS == llm.MEMORY_GUIDE


@pytest.mark.parametrize("name", EXAMPLE_TOOLS)
def test_write_tool_example_validates_against_its_contract(name):
    spec = tools.TOOL_SPECS[name]
    found = re.search(r"Example: (\{.*\})$", spec.description)
    assert found, f"{name} has no worked example"
    spec.model.model_validate(json.loads(found.group(1)))


def test_add_fact_example_is_the_user_name():
    example = tools.TOOL_SPECS["add_fact"].description
    assert '"attribute":"name","value":"Jerry"' in example


def test_read_tools_tell_the_model_when_to_call_them():
    assert "I don't know" in tools.TOOL_SPECS["search_memory"].description
    assert "conflict" in tools.TOOL_SPECS["get_context"].description

"""M3 rule extractor tests, written before T08 (SPEC §8 M3, §9.3 T08).

Behavior:
    The sentence table pins what `pam.extract.facts.extract_candidates` must return for one
    user message: the exact set of `(attribute, value)` pairs, compared case-insensitively
    with whitespace collapsed. The rule table does the same for `pam.extract.rules.extract_rules`.
    The fixture tests run `pam init` -> `pam import run` -> `pam derive` on the Claude fixture
    and read the vault back. The whole module skips until `pam.extract.facts` exists.

API assumed by these tests (agreed for T08, not in SPEC):
    `facts.extract_candidates(text, role="user") -> list` of objects with `.attribute`,
    `.value`, `.pattern_id`. Only mines `role == "user"`.
    `rules.extract_rules(text, role="user") -> list[str]` of canonical rule sentences.
    `patterns.PATTERNS`: the declarative pattern dicts (`id`, `attribute`, `category`,
    `cardinality`, `confidence`, ...).

Design choices pinned here (log as `design` CHG entries in §10 when implementing):
    - New `attend` pattern: "I go to X" / "I attend X" -> `school` (ORG filter).
    - `use_tool` values split on `,` / `and` like `stack`, one MULTI fact per tool.
    - Capitalized value groups (`name`, `call_me`, `use_tool`) match case-sensitively
      even though the trigger is case-insensitive ("I use Python every day" -> `Python`).
    - `job_title` is non-greedy: it stops at the first role keyword.
    - `.` is a clause boundary only when followed by whitespace or end of text (`Node.js`).
    - `major` does not fire on "studying at <school>".
    - `live_in` also matches "I'm based in" (the §8 regex `i (?:...|'m based)` never can).
    - Acronym schools (`UW`, `WSU`) must pass the ORG filter even if spaCy misses them.
"""

import json
import re
import zipfile
from pathlib import Path

import pytest

facts = pytest.importorskip("pam.extract.facts")
rules = pytest.importorskip("pam.extract.rules")
patterns = pytest.importorskip("pam.extract.patterns")

FIXTURE = Path(__file__).parent / "fixtures" / "claude" / "export.zip"


def _norm(v: str) -> str:
    """Match `contracts.fact.normalize_value` without importing contracts."""
    return re.sub(r"\s+", " ", v.strip().lower())


def _pairs(text: str, role: str = "user") -> set[tuple[str, str]]:
    return {(c.attribute, _norm(c.value)) for c in facts.extract_candidates(text, role=role)}


NO_FACT: set[tuple[str, str]] = set()

# (id, user sentence, expected (attribute, value) pairs)
FACT_CASES = [
    # --- starter patterns ---
    ("name", "My name is Alex Chen.", {("name", "alex chen")}),
    ("name_trim_and", "My name is Alex and I study CS.", {("name", "alex")}),
    ("call_me", "Please just call me Sam.", {("preferred_name", "sam")}),
    ("go_by", "I go by Jo.", {("preferred_name", "jo")}),
    ("study_at_fixture", "I study at WSU, so I'll mostly be reaching it from campus.", {("school", "wsu")}),
    ("student_at", "I'm a grad student at Stanford University.",
     {("school", "stanford university"), ("role", "grad student")}),
    ("studying_at_not_major", "I am studying at Oregon State University.", {("school", "oregon state university")}),
    ("major", "I'm majoring in computer science.", {("major", "computer science")}),
    ("major_studying", "I am studying biology.", {("major", "biology")}),
    ("work_at", "I work at Microsoft.", {("works_at", "microsoft")}),
    ("intern_for", "I intern for Amazon.", {("works_at", "amazon")}),
    ("job_title_senior", "I'm a senior software engineer.", {("role", "senior software engineer")}),
    ("job_title", "I am a data scientist.", {("role", "data scientist")}),
    ("job_title_non_greedy", "I'm an international student working currently as a Dining Student Assistant.",
     {("role", "international student")}),
    ("live_in", "I live in Seattle.", {("location", "seattle")}),
    ("am_based_in", "I am based in Toronto.", {("location", "toronto")}),
    ("im_based_in", "I'm based in Berlin.", {("location", "berlin")}),
    ("from", "I'm from Texas.", {("hometown", "texas")}),
    ("prefer", "I prefer tabs over spaces.", {("likes", "tabs over spaces")}),
    ("really_like", "I really like dark mode.", {("likes", "dark mode")}),
    ("dislike", "I hate long meetings.", {("dislikes", "long meetings")}),
    ("cant_stand_is_not_negation", "I can't stand Java.", {("dislikes", "java")}),
    ("use_tool_case_sensitive_value", "I use Python every day.", {("uses_tool", "python")}),
    ("use_tool_split_and", "I'm using FastAPI and React.", {("uses_tool", "fastapi"), ("uses_tool", "react")}),
    ("use_tool_split_list", "I use Python, Go and Rust.",
     {("uses_tool", "python"), ("uses_tool", "go"), ("uses_tool", "rust")}),
    ("work_with", "I work with Docker.", {("uses_tool", "docker")}),
    ("use_tool_dotted_name", "I use Node.js and Postgres.", {("uses_tool", "node.js"), ("uses_tool", "postgres")}),
    ("stack_split", "My tech stack is Python, FastAPI and SQLite.",
     {("uses_tool", "python"), ("uses_tool", "fastapi"), ("uses_tool", "sqlite")}),
    ("stack_dotted", "My stack is Next.js and Postgres.", {("uses_tool", "next.js"), ("uses_tool", "postgres")}),
    ("building", "I'm building an Immich backup script.", {("working_on", "an immich backup script")}),
    # --- new attend pattern (fixture plant; no starter pattern matches it) ---
    ("go_to_fixture", "I go to UW and they use a network profile called eduroam.", {("school", "uw")}),
    ("attend", "I attend UW.", {("school", "uw")}),
    ("go_to_not_org", "I go to the gym every morning.", NO_FACT),
    # --- negations ---
    ("neg_dont_work", "I don't work at Google.", NO_FACT),
    ("neg_no_longer_live", "I no longer live in Portland.", NO_FACT),
    ("neg_not_that", "Not that I work at Google.", NO_FACT),
    ("neg_never_said", "Never said I live in Ohio.", NO_FACT),
    ("neg_not_from", "I'm not from Texas.", NO_FACT),
    ("neg_never_use", "I never use Java.", NO_FACT),
    # --- questions ---
    ("q_work_at", "So I work at Google?", NO_FACT),
    ("q_live_in", "Wait, I live in Seattle?", NO_FACT),
    ("q_job_title", "Do you think I'm a good engineer?", NO_FACT),
    # --- hypotheticals ---
    ("hyp_if", "If I work at Google next year, I'll move.", NO_FACT),
    ("hyp_imagine", "Imagine I live in Paris.", NO_FACT),
    ("hyp_pretend", "Pretend I'm from Texas.", NO_FACT),
    ("hyp_would", "Assuming I live in Paris, I would take the train.", NO_FACT),
    # --- clause trimming at , . and/but/because ---
    ("trim_comma", "I work at Microsoft, mostly on Azure.", {("works_at", "microsoft")}),
    ("trim_period", "I study at UW.", {("school", "uw")}),
    ("trim_and", "I live in Seattle and bike to work.", {("location", "seattle")}),
    ("trim_and_major", "I'm majoring in physics and I love it.", {("major", "physics")}),
    ("trim_but", "I'm from Ohio but I moved away.", {("hometown", "ohio")}),
    ("trim_because", "I love Rust because it is fast.", {("likes", "rust")}),
    ("trim_comma_working_on", "I'm working on PAM, a memory layer for agents.", {("working_on", "pam")}),
    # --- stopword junk filter ---
    ("junk_a_list", "I'm building a list of my favorite restaurants.", NO_FACT),
    ("junk_a_function", "I'm making a function that parses dates.", NO_FACT),
    ("junk_it", "I'm working on it.", NO_FACT),
    ("junk_this", "I love this.", NO_FACT),
    ("junk_lowercase_it", "I use it every day.", NO_FACT),
    # --- quotes and code fences are ignored ---
    ("quoted", 'He told me "I work at Google" yesterday.', NO_FACT),
    ("curly_quoted", "My friend said “I live in Denver” last week.", NO_FACT),
    ("code_fence", "```\n# I live in Seattle\nprint('hi')\n```", NO_FACT),
    ("quote_beside_real", 'I live in Boston. My friend said "I live in Denver".', {("location", "boston")}),
    ("fence_beside_real", "Here is my config:\n```python\n# I work at Google\nx = 1\n```\nI work at Microsoft.",
     {("works_at", "microsoft")}),
    # --- fixture guard: conv 8 was rewritten so it is not school evidence ---
    ("fixture_in_uw_cs", "i'm in UW cs.", NO_FACT),
]


@pytest.mark.parametrize("text,expected", [c[1:] for c in FACT_CASES], ids=[c[0] for c in FACT_CASES])
def test_fact_table(text, expected):
    assert _pairs(text) == expected


# One sentence per starter pattern id from the §8 M3 table.
PATTERN_ID_CASES = [
    ("name", "My name is Alex Chen."),
    ("call_me", "Call me Sam."),
    ("study_at", "I study at WSU."),
    ("major", "I'm majoring in computer science."),
    ("work_at", "I work at Microsoft."),
    ("job_title", "I am a data scientist."),
    ("live_in", "I live in Seattle."),
    ("from", "I'm from Texas."),
    ("prefer", "I prefer tabs over spaces."),
    ("dislike", "I hate long meetings."),
    ("use_tool", "I use Python every day."),
    ("stack", "My stack is Python and Go."),
    ("building", "I'm building an Immich backup script."),
]


@pytest.mark.parametrize("pattern_id,text", PATTERN_ID_CASES, ids=[c[0] for c in PATTERN_ID_CASES])
def test_pattern_id(pattern_id, text):
    got = {c.pattern_id for c in facts.extract_candidates(text, role="user")}
    assert got == {pattern_id}


def test_patterns_declare_starter_set():
    def val(x):
        return getattr(x, "value", x)

    by_id = {p["id"]: p for p in patterns.PATTERNS}
    assert {pid for pid, _ in PATTERN_ID_CASES} <= set(by_id)
    for p in patterns.PATTERNS:
        expected = 0.75 if val(p["category"]) in {"identity", "education", "work", "location"} else 0.6
        assert p["confidence"] == expected, p["id"]
    assert val(by_id["study_at"]["cardinality"]) == "single"
    assert val(by_id["use_tool"]["cardinality"]) == "multi"


def test_value_capped_at_60_chars():
    long_value = "an open source self hosted photo backup pipeline for my family archive server"
    assert len(long_value) > 60
    got = facts.extract_candidates(f"I'm building {long_value}.", role="user")
    assert len(got) == 1
    assert got[0].attribute == "working_on"
    assert 0 < len(got[0].value) <= 60
    assert long_value.startswith(_norm(got[0].value))


@pytest.mark.parametrize(
    "text",
    ["I work at Microsoft.", "My name is Alex Chen.", "I go to UW.", "I use Python, Go and Rust."],
)
def test_assistant_messages_never_mined(text):
    assert facts.extract_candidates(text, role="assistant") == []
    assert _pairs(text, role="user") != NO_FACT  # same text is minable as a user message


# --- rules (§8 M3 rules.py) ---

BULLETS = "Don't use bullet points."

# (id, user text, expected canonical rules)
RULE_CASES = [
    ("r1_please_dont", "Please don't use bullet points.", [BULLETS]),
    ("r1_do_not", "Do not use bullet points.", [BULLETS]),
    ("r3_no_bullets", "no bullet points pls", [BULLETS]),
    ("r3_singular", "No bullet point lists.", [BULLETS]),
    ("not_imperative", "I don't use bullet points myself.", []),
    ("question", "Do you use bullet points?", []),
    ("in_code_fence", "```\nno bullet points\n```", []),
    ("in_quotes", 'My teacher always says "no bullet points" in essays.', []),
]


@pytest.mark.parametrize("text,expected", [c[1:] for c in RULE_CASES], ids=[c[0] for c in RULE_CASES])
def test_rule_table(text, expected):
    assert rules.extract_rules(text, role="user") == expected


@pytest.mark.parametrize(
    "a,b",
    [
        ("No emojis.", "Don't use emojis."),
        ("no markdown please", "Do not use markdown."),
        ("Avoid using bullet points.", "no bullet points"),
    ],
)
def test_rule_phrasings_share_canonical_text(a, b):
    ra, rb = rules.extract_rules(a, role="user"), rules.extract_rules(b, role="user")
    assert len(ra) == 1
    assert ra == rb


@pytest.mark.parametrize(
    "text,word",
    [
        ("Keep it short.", "short"),
        ("keep answers concise please", "concise"),
        ("Always include type hints.", "type hints"),
        ("Never write comments in the code.", "comments"),
    ],
)
def test_rule_other_regexes(text, word):
    got = rules.extract_rules(text, role="user")
    assert len(got) == 1
    assert word in got[0].lower()
    assert got != [BULLETS]


def test_rules_ignore_assistant():
    assert rules.extract_rules("No bullet points.", role="assistant") == []


# --- fixture: pam init -> pam import run -> pam derive (M3 acceptance) ---

WSU_TITLE = "Setting up Tailscale VPN on Ubuntu server"  # conv 0, 2026-08-17: "I study at WSU"
UW_TITLE = "Tailscale access over eduroam network"  # conv 4, 2026-08-31: "I go to UW"

# Facts the fixture states in user messages. location=Seattle needs the conv 7 plant
# ("I live in Seattle ...") from the follow-up fixture PR.
EXPECTED_FIXTURE_FACTS = {
    ("school", "uw"),
    ("role", "international student"),
    ("location", "seattle"),
}


def _fixture_conversations() -> list[dict]:
    with zipfile.ZipFile(FIXTURE) as z:
        return json.loads(z.read("conversations.json"))


def _user_text(conv: dict) -> str:
    parts = []
    for m in conv["chat_messages"]:
        if m["sender"] == "human":
            parts.append(m.get("text") or "")
            parts += [b.get("text", "") for b in m.get("content", []) if b.get("type") == "text"]
    return _norm("\n".join(parts))


@pytest.fixture(scope="module")
def derived(tmp_path_factory):
    """Run the M0-M3 CLI on the fixture once and return `(vault, DeriveReport JSON)`."""
    from typer.testing import CliRunner

    from pam.cli.main import app

    vault = tmp_path_factory.mktemp("vault")
    runner = CliRunner()
    for args in (["init"], ["import", "run", str(FIXTURE)]):
        res = runner.invoke(app, ["--vault", str(vault), *args])
        assert res.exit_code == 0, res.output
    res = runner.invoke(app, ["--vault", str(vault), "--json", "derive"])
    assert res.exit_code == 0, res.output
    return vault, json.loads(res.stdout)


@pytest.fixture(scope="module")
def vault_facts(derived):
    from pam.contracts.fact import Fact
    from pam.core import mdio

    vault, _ = derived
    return [Fact.model_validate(mdio.read(p)[0]) for p in sorted(vault.glob("memory/*/facts/*.md"))]


def test_fixture_derive_report(derived):
    _, report = derived
    assert report["facts_created"] >= 3
    assert report["rules_derived"] >= 1


def test_fixture_at_least_3_correct_facts(vault_facts):
    active = {(f.attribute, _norm(f.value)) for f in vault_facts if f.status.value == "active"}
    assert EXPECTED_FIXTURE_FACTS <= active


def test_fixture_no_facts_from_assistant_text(vault_facts):
    user_text = "\n".join(_user_text(c) for c in _fixture_conversations())
    for f in vault_facts:
        assert f.extractor.value == "rule"
        assert _norm(f.value) in user_text, f"{f.attribute}={f.value!r} is not in any user message"


def test_fixture_newer_school_overwrites_older(vault_facts):
    """Both values are rule-extracted and UW is newer, so UW wins and WSU goes to history (§8 M3 merging)."""
    from pam.contracts.common import Source
    from pam.contracts.episode import episode_id
    from pam.contracts.fact import Cardinality, FactStatus, fact_id

    convs = {c["name"]: c for c in _fixture_conversations()}
    uw_episode = episode_id(Source.CLAUDE, convs[UW_TITLE]["uuid"])
    wsu_episode = episode_id(Source.CLAUDE, convs[WSU_TITLE]["uuid"])

    school = [f for f in vault_facts if f.attribute == "school"]
    assert len(school) == 1
    f = school[0]
    assert f.id == fact_id("shared", "user", "school", Cardinality.SINGLE, f.value)
    assert _norm(f.value) == "uw"
    assert f.status is FactStatus.ACTIVE
    assert f.conflict is None
    assert f.source_episode == uw_episode
    assert f.updated_by_episode == uw_episode
    old = [h for h in f.history if _norm(h.value) == "wsu"]
    assert len(old) == 1
    assert old[0].changed_by.value == "rule"
    assert old[0].episode_id == wsu_episode


def test_fixture_rule_no_bullet_points(derived):
    vault, _ = derived
    text = (vault / "agent" / "default" / "rules.md").read_text(encoding="utf-8")
    derived_part, sep, custom_part = text.partition("## Custom")
    assert sep, "rules.md lost its ## Custom section"
    assert "## Derived" in derived_part
    assert BULLETS.lower() in derived_part.lower()
    assert "bullet" not in custom_part.lower()


# --- review follow-ups (CHG-0006) ---


@pytest.mark.parametrize(
    "text,same_as",
    [
        ("Please don't use emojis, thanks", "No emojis."),
        ("Don't use bullet points, please.", "no bullet points"),
        ("never use markdown pls", "No markdown."),
    ],
)
def test_rule_polite_tail_keeps_canonical_text(text, same_as):
    got = rules.extract_rules(text, role="user")
    assert got == rules.extract_rules(same_as, role="user")
    assert not got[0].endswith(",.")


def test_bump_records_episode_and_counts_it_once(tmp_path):
    """Re-mining an episode that already confirmed a value does not raise its confidence again."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from pam.core.vault import Vault, init_vault

    init_vault(tmp_path)
    v = Vault(tmp_path)
    a, b = uuid4(), uuid4()
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    facts.write_candidates(v, "I work at Microsoft.", episode_id=a, created_at=t)
    (f,) = facts.write_candidates(v, "I work at Microsoft.", episode_id=b, created_at=t + timedelta(days=1))
    assert f.confidence == pytest.approx(0.8)
    assert f.updated_by_episode == b
    assert facts.write_candidates(v, "I work at Microsoft.", episode_id=b, created_at=t + timedelta(days=1)) == []
    (again,) = facts.load_shared_facts(v).values()
    assert again.confidence == pytest.approx(0.8)


def test_fixture_older_school_after_newer_goes_to_history(tmp_path):
    """Deriving the newer UW episode first, then the rest, ends like one chronological run."""
    from typer.testing import CliRunner

    from pam.cli.main import app
    from pam.contracts.common import Source
    from pam.contracts.episode import EpisodeFrontmatter, episode_id
    from pam.core import mdio
    from pam.core.vault import Vault

    convs = {c["name"]: c for c in _fixture_conversations()}
    uw_episode = episode_id(Source.CLAUDE, convs[UW_TITLE]["uuid"])
    wsu_episode = episode_id(Source.CLAUDE, convs[WSU_TITLE]["uuid"])
    runner = CliRunner()
    for args in (["init"], ["import", "run", str(FIXTURE)], ["derive", "--episode", str(uw_episode)], ["derive"]):
        res = runner.invoke(app, ["--vault", str(tmp_path), *args])
        assert res.exit_code == 0, res.output

    school = [f for f in facts.load_shared_facts(Vault(tmp_path)).values() if f.attribute == "school"]
    assert len(school) == 1
    f = school[0]
    assert _norm(f.value) == "uw"
    assert f.status.value == "active"
    assert f.conflict is None
    assert f.source_episode == uw_episode
    assert [(_norm(h.value), h.episode_id) for h in f.history] == [("wsu", wsu_episode)]
    (path,) = tmp_path.glob(f"memory/*/episodes/{wsu_episode}.md")
    fm, _ = mdio.read_model(path, EpisodeFrontmatter)
    assert f.id in fm.superseded_facts

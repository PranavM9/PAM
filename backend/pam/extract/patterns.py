"""Declarative fact patterns and shared extraction constants (SPEC §8 M3).

Behavior:
    `PATTERNS` holds one dict per pattern: `id`, `regex`, `attribute`, `category`, `cardinality`,
    `confidence`, `value_group`, plus the optional `ner_filter` (`ORG` or `GPE`), `split` (the
    value is a list split on `,` / `and`), and `reject` (a regex of values to drop). Regexes are
    matched case-insensitively; a capitalized value group opts back into case sensitivity with a
    scoped `(?-i:...)` flag. `category` and `cardinality` are the string values of the §7.4 enums,
    so this module stays free of contract imports.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

CONFIDENCE_BUMP = 0.05
CONFIDENCE_CAP = 0.95
MAX_VALUE_CHARS = 60
NEGATION_WINDOW = 3

_ID_CONFIDENCE = 0.75
_SOFT_CONFIDENCE = 0.6

_Q = "['’]"  # straight or curly apostrophe
_NAME_TOKEN = r"[A-Z][\w'’-]+"
_TOOL_TOKEN = r"[A-Z][\w.+#-]*"

PATTERNS: list[dict[str, Any]] = [
    {
        "id": "name",
        "regex": rf"\bmy name is (?P<v>(?-i:{_NAME_TOKEN}(?: {_NAME_TOKEN})?))",
        "attribute": "name", "category": "identity", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v",
    },
    {
        "id": "call_me",
        "regex": rf"\b(?:call me|i go by) (?P<v>(?-i:{_NAME_TOKEN}))",
        "attribute": "preferred_name", "category": "identity", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v",
    },
    {
        "id": "study_at",
        "regex": rf"\bi(?:{_Q}m| am)? (?:study(?:ing)?|a (?:\w+ )?student) at (?P<v>.+)",
        "attribute": "school", "category": "education", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v", "ner_filter": "ORG",
    },
    {
        "id": "attend",
        "regex": r"\bi (?:go to|attend) (?P<v>.+)",
        "attribute": "school", "category": "education", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v", "ner_filter": "ORG",
    },
    {
        "id": "major",
        "regex": rf"\bi(?:{_Q}m| am) (?:majoring|studying) (?:in )?(?!at\b)(?P<v>[\w &]+)",
        "attribute": "major", "category": "education", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v",
        "reject": r"^(?:for|to|how|about|with|on|the|an?|my|some|it|this|that)\b",
    },
    {
        "id": "work_at",
        "regex": r"\bi (?:work|intern(?:ing)?) (?:at|for) (?P<v>.+)",
        "attribute": "works_at", "category": "work", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v", "ner_filter": "ORG",
    },
    {
        "id": "job_title",
        "regex": (
            rf"\bi(?:{_Q}m| am) an? "
            r"(?P<v>(?:(?:senior|junior|lead) )?(?:\w+ ){0,3}?"
            r"(?:engineer|developer|designer|student|researcher|manager|scientist)\b)"
        ),
        "attribute": "role", "category": "work", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v",
    },
    {
        "id": "live_in",
        "regex": rf"\bi(?: live|{_Q}m based| am based) in (?P<v>.+)",
        "attribute": "location", "category": "location", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v", "ner_filter": "GPE",
    },
    {
        "id": "from",
        "regex": rf"\bi(?:{_Q}m| am) from (?P<v>.+)",
        "attribute": "hometown", "category": "location", "cardinality": "single",
        "confidence": _ID_CONFIDENCE, "value_group": "v", "ner_filter": "GPE",
    },
    {
        "id": "prefer",
        "regex": r"\bi (?:prefer|really like|love) (?P<v>.+)",
        "attribute": "likes", "category": "preference", "cardinality": "multi",
        "confidence": _SOFT_CONFIDENCE, "value_group": "v",
    },
    {
        "id": "dislike",
        "regex": rf"\bi (?:hate|dislike|can{_Q}t stand) (?P<v>.+)",
        "attribute": "dislikes", "category": "preference", "cardinality": "multi",
        "confidence": _SOFT_CONFIDENCE, "value_group": "v",
    },
    {
        "id": "use_tool",
        "regex": (
            rf"\bi(?:{_Q}m| am)? (?:using|use|work with) "
            rf"(?P<v>(?-i:{_TOOL_TOKEN}(?:,? (?:and )?{_TOOL_TOKEN})*))"
        ),
        "attribute": "uses_tool", "category": "tooling", "cardinality": "multi",
        "confidence": _SOFT_CONFIDENCE, "value_group": "v", "split": True,
    },
    {
        "id": "stack",
        "regex": r"\bmy (?:tech )?stack is (?P<v>.+)",
        "attribute": "uses_tool", "category": "tooling", "cardinality": "multi",
        "confidence": _SOFT_CONFIDENCE, "value_group": "v", "split": True,
    },
    {
        "id": "building",
        "regex": rf"\bi(?:{_Q}m| am) (?:building|working on|making) (?P<v>.+)",
        "attribute": "working_on", "category": "project", "cardinality": "multi",
        "confidence": _SOFT_CONFIDENCE, "value_group": "v",
    },
]

# A value ends at the first clause boundary; `.` counts only before whitespace or the end, so
# `Node.js` survives. List-valued patterns keep `,` and `and`, which they split on later.
CLAUSE_BOUNDARY = re.compile(r"[,;(\x00]|\.(?=\s|$)|\s(?:and|but|because)(?:\s|$)", re.I)
LIST_CLAUSE_BOUNDARY = re.compile(r"[;(\x00]|\.(?=\s|$)|\s(?:but|because)(?:\s|$)", re.I)
LIST_SEPARATOR = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+", re.I)

# Values that carry no information: pronouns and generic nouns, with an optional article.
JUNK_VALUE = re.compile(
    r"^(?:(?:an?|the|some|any|my|your|our|this|that)\s+)?"
    r"(?:list|lists|function|functions|thing|things|stuff|bunch|lot|lots|one|ones|way|ways"
    r"|method|methods|variable|variables|class|classes|something|anything|everything|nothing"
    r"|it|them|him|her|you|us|me|there|here|this|that|these|those)\b",
    re.I,
)

HYPOTHETICAL = re.compile(r"\b(?:if|would|imagine|pretend|suppose|assuming|hypothetically)\b", re.I)
NEGATION_TOKEN = re.compile(r"^(?:not|never|cannot|nor|neither)$|n['’]t$", re.I)
ACRONYM = re.compile(r"[A-Z]{2,8}|(?:[A-Z]\.){2,}")

# spaCy entity labels that satisfy each `ner_filter`.
NER_LABELS = {"ORG": {"ORG", "GPE", "LOC", "FAC", "PRODUCT"}, "GPE": {"GPE", "LOC", "FAC"}}


@lru_cache(maxsize=None)
def compiled(pattern_id: str) -> re.Pattern[str]:
    """Compile a pattern's regex case-insensitively.

    Behavior:
        The result is cached per pattern id.
    Exceptions:
        KeyError: No pattern has this id.
    Returns:
        The compiled regex.
    Parameters:
        pattern_id: Id of an entry in `PATTERNS`.
    """
    for pattern in PATTERNS:
        if pattern["id"] == pattern_id:
            return re.compile(pattern["regex"], re.I)
    raise KeyError(pattern_id)

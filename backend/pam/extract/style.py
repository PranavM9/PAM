"""Style statistics over user messages and their fixed-threshold sentences (SPEC §8 M3).

Behavior:
    `compute_stats` measures five properties of how the user writes; `style_sentences` maps them
    to instruction sentences with the thresholds below. Too few messages yield no sentences.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

MIN_MESSAGES = 5
BRIEF_MAX_MEDIAN_WORDS = 15
LONG_MIN_MEDIAN_WORDS = 60
CODE_HEAVY_SHARE = 0.25
QUESTION_HEAVY_RATIO = 0.5
EMOJI_MIN_RATIO = 0.10
BREVITY_MIN_SHARE = 0.10
TOP_LANGUAGES = 3

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_FENCE_LANG = re.compile(r"^```([A-Za-z][\w+#-]*)", re.M)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_BREVITY = re.compile(r"\b(?:short|concise)\b|tl;dr", re.I)
_LANGUAGE_NAMES = {
    "python": "Python", "typescript": "TypeScript", "javascript": "JavaScript", "bash": "Bash",
    "sh": "Shell", "sql": "SQL", "json": "JSON", "yaml": "YAML", "go": "Go", "rust": "Rust",
    "java": "Java", "cpp": "C++", "c": "C", "html": "HTML", "css": "CSS", "tsx": "TSX",
}


@dataclass(frozen=True)
class StyleStats:
    """The five statistics, each over the user's non-empty messages.

    Behavior:
        Shares and ratios are fractions in `[0, 1]`; `languages` lists the most used fenced
        languages, most frequent first.
    """

    messages: int
    median_words: float
    code_share: float
    languages: tuple[str, ...]
    question_ratio: float
    emoji_ratio: float
    brevity_share: float


def compute_stats(messages: Iterable[str]) -> StyleStats:
    """Compute the style statistics.

    Behavior:
        Word counts ignore fenced code. Empty messages are dropped. Languages tie-break by name.
    Returns:
        The statistics; all zero for no messages.
    Parameters:
        messages: User message texts.
    """
    texts = [m for m in messages if m.strip()]
    if not texts:
        return StyleStats(0, 0.0, 0.0, (), 0.0, 0.0, 0.0)
    n = len(texts)
    words = [len(_FENCE.sub(" ", t).split()) for t in texts]
    langs = Counter(lang.lower() for t in texts for lang in _FENCE_LANG.findall(t))
    ranked = sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_LANGUAGES]
    return StyleStats(
        messages=n,
        median_words=float(statistics.median(words)),
        code_share=sum("```" in t for t in texts) / n,
        languages=tuple(name for name, _ in ranked),
        question_ratio=sum("?" in _FENCE.sub(" ", t) for t in texts) / n,
        emoji_ratio=sum(bool(_EMOJI.search(t)) for t in texts) / n,
        brevity_share=sum(bool(_BREVITY.search(t)) for t in texts) / n,
    )


def _pct(x: float) -> int:
    return round(x * 100)


def style_sentences(stats: StyleStats) -> list[str]:
    """Map statistics to style instructions with fixed thresholds.

    Behavior:
        Returns nothing below `MIN_MESSAGES` messages. Length is always described; the code,
        question, emoji, and brevity sentences appear only above their thresholds.
    Returns:
        The sentences, in a fixed order.
    Parameters:
        stats: Output of `compute_stats`.
    """
    if stats.messages < MIN_MESSAGES:
        return []
    median = round(stats.median_words)
    if stats.median_words <= BRIEF_MAX_MEDIAN_WORDS:
        out = [f"The user writes briefly (median {median} words); prefer concise answers."]
    elif stats.median_words >= LONG_MIN_MEDIAN_WORDS:
        out = [f"The user writes long, detailed messages (median {median} words); detailed answers are welcome."]
    else:
        out = [f"The user writes moderate-length messages (median {median} words)."]
    if stats.code_share >= CODE_HEAVY_SHARE:
        favor = ", ".join(_LANGUAGE_NAMES.get(lang, lang.capitalize()) for lang in stats.languages)
        out.append(
            f"Code-heavy ({_pct(stats.code_share)}% of messages); include runnable code blocks"
            + (f"; favor {favor}." if favor else ".")
        )
    if stats.question_ratio >= QUESTION_HEAVY_RATIO:
        out.append(f"The user mostly asks questions ({_pct(stats.question_ratio)}% of messages); answer directly first.")
    if stats.emoji_ratio >= EMOJI_MIN_RATIO:
        out.append(f"The user uses emojis ({_pct(stats.emoji_ratio)}% of messages); emojis in replies are fine.")
    if stats.brevity_share >= BREVITY_MIN_SHARE:
        out.append(
            f"The user often asks for short answers ({_pct(stats.brevity_share)}% of messages "
            "mention short, concise, or tl;dr)."
        )
    return out

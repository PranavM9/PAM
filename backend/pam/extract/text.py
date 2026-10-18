"""Text helpers shared by the M3 extractors (SPEC §8 M3).

Behavior:
    Masks quoted text and code, splits user text into sentences (spaCy when its model is
    installed, a regex splitter otherwise), and parses episode bodies into messages.
"""

from __future__ import annotations

import functools
import re
import warnings
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from pam.extract import patterns as pat

MASK = "\x00"
ROLE_SEPARATOR = "·"

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_QUOTES = (re.compile(r'"[^"\n]*"'), re.compile(r"“[^”\n]*”"))
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=\S)")
_HEADING = re.compile(rf"^### (user|assistant|system|tool) {ROLE_SEPARATOR} (\S+)$", re.M)
_TRANSCRIPT = re.compile(r"^## Transcript$", re.M)
_ATTACHMENT = re.compile(r"^\[attachment: .*\]$", re.M)


@dataclass(frozen=True)
class Sentence:
    """One sentence of masked text.

    Behavior:
        `entities` holds `(start, end, label)` character spans relative to `text`. `has_ner` is true
        only when spaCy produced them, so an empty `entities` then means "no entity found".
    """

    text: str
    entities: tuple[tuple[int, int, str], ...] = ()
    has_ner: bool = False


def negated(prefix: str) -> bool:
    """Tell whether a negation sits within 3 tokens at the end of `prefix`.

    Behavior:
        Negations are `not`, `never`, `cannot`, `nor`, `neither`, `no longer`, and any `n't` word.
    Returns:
        `True` when a negation is in the window.
    Parameters:
        prefix: The sentence text before a trigger.
    """
    tokens = [t.strip('.,;:!"()[]“”').lower() for t in prefix.split() if t.strip(MASK)]
    window = tokens[-pat.NEGATION_WINDOW:]
    if any(pat.NEGATION_TOKEN.search(t) for t in window):
        return True
    return any(a == "no" and b == "longer" for a, b in zip(window, window[1:]))


def cap_value(value: str) -> str:
    """Cap a value at 60 characters, cutting at a word boundary when possible.

    Returns:
        The value, at most `MAX_VALUE_CHARS` long, without trailing punctuation.
    Parameters:
        value: A trimmed value.
    """
    if len(value) <= pat.MAX_VALUE_CHARS:
        return value
    head = value[: pat.MAX_VALUE_CHARS]
    if value[pat.MAX_VALUE_CHARS] != " " and " " in head:
        head = head.rsplit(" ", 1)[0]
    return head.rstrip(" .,;:!-–—")


def mask_ignored(text: str) -> str:
    """Blank out code fences, inline code, and quoted text.

    Behavior:
        Replaces every character of a masked span with `MASK` (newlines are kept), so offsets and
        line structure are unchanged and `MASK` acts as a clause boundary. An unterminated fence
        masks to the end of the text.
    Returns:
        The masked text, the same length as `text`.
    Parameters:
        text: One message.
    """

    def blank(m: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else MASK for ch in m.group())

    text = _FENCE.sub(blank, text)
    text = _INLINE_CODE.sub(blank, text)
    for quote in _QUOTES:
        text = quote.sub(blank, text)
    return text


@functools.lru_cache(maxsize=None)
def load_nlp(model: str):
    """Load a spaCy pipeline once per process.

    Behavior:
        Returns `None` and warns once when spaCy or the model is missing, so callers fall back to
        the regex splitter and the capitalization heuristic.
    Returns:
        The loaded `Language`, or `None`.
    Parameters:
        model: spaCy model name, e.g. `en_core_web_sm`.
    """
    try:
        import spacy

        return spacy.load(model, exclude=["lemmatizer"])
    except (ImportError, OSError, ValueError) as e:
        warnings.warn(
            f"spaCy model {model!r} is not installed ({e.__class__.__name__}), so facts are found with "
            "a simpler sentence splitter and name check. Install it with: uv sync (in backend/)",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def _regex_spans(line: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE_BREAK.finditer(line):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(line)))
    return [(s, e) for s, e in spans if line[s:e].replace(MASK, " ").strip()]


def iter_sentences(
    masked: str, nlp, prefilter: Callable[[str], bool] | None = None
) -> Iterator[Sentence]:
    """Yield the sentences of masked text, one line at a time.

    Behavior:
        Lines are processed independently. A line that fails `prefilter` is skipped without
        running spaCy. With spaCy, `doc.sents` and `doc.ents` give the sentences and entities;
        without it, sentences split after `.`, `!`, or `?` followed by whitespace.
    Returns:
        An iterator of `Sentence`.
    Parameters:
        masked: Output of `mask_ignored`.
        nlp: A spaCy pipeline, or `None` for the regex splitter.
        prefilter: Optional cheap test a line must pass to be analysed.
    """
    for line in masked.split("\n"):
        if not line.replace(MASK, " ").strip():
            continue
        if prefilter is not None and not prefilter(line):
            continue
        if nlp is None:
            for s, e in _regex_spans(line):
                yield Sentence(line[s:e])
            continue
        doc = nlp(line.replace(MASK, " "))
        ents = [(ent.start_char, ent.end_char, ent.label_) for ent in doc.ents]
        for sent in doc.sents:
            s, e = sent.start_char, sent.end_char
            inside = tuple((a - s, b - s, label) for a, b, label in ents if a >= s and b <= e)
            yield Sentence(line[s:e], inside, True)


def transcript_messages(body: str) -> list[tuple[str, str]]:
    """Parse an episode body into `(role, text)` messages.

    Behavior:
        Reads the `### <role> · <time>` blocks after `## Transcript` (§7.3). Attachment marker
        lines are dropped; the summary section is ignored.
    Returns:
        The messages in transcript order.
    Parameters:
        body: Episode body text.
    """
    start = _TRANSCRIPT.search(body)
    transcript = body[start.end():] if start else ""
    headings = list(_HEADING.finditer(transcript))
    messages = []
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(transcript)
        text = _ATTACHMENT.sub("", transcript[h.end():end]).strip()
        messages.append((h.group(1), text))
    return messages

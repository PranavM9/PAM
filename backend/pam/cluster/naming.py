"""Name projects and write their extractive summary with class-based TF-IDF (SPEC §8 M5)."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer

TOP_KEYWORDS = 5  # §8 M5: the top 5 terms become `keywords`
NAME_KEYWORDS = 2  # §8 M5: fallback name joins the top 2 keywords
TITLE_NGRAM_SHARE = 0.30  # §8 M5: a title n-gram names the project if in >= 30% of member titles
TITLE_NGRAM_MIN = 2  # and in at least 2 titles, so one title alone never names a project
SUMMARY_TITLES = 5  # §8 M5: the summary lists the 5 most recent member titles
NAME_SEPARATOR = " · "
SUMMARY_HEADING = "## Summary (auto)"


@dataclass(frozen=True)
class Member:
    """The parts of one member episode that naming and the summary use."""

    title: str
    text: str
    created_at: datetime


def _vectorizer() -> CountVectorizer:
    return CountVectorizer(ngram_range=(1, 2), stop_words="english", min_df=1)


def ctfidf(class_docs: Sequence[str], top_n: int = TOP_KEYWORDS) -> list[list[str]]:
    """Rank the terms of each class document by class-based TF-IDF.

    Behavior:
        Counts unigrams and bigrams with `CountVectorizer(ngram_range=(1, 2), stop_words="english")`
        and scores each term as `tf · log(1 + A / f)`, where `tf` is its count in the class, `A` the
        average word count per class, and `f` its count across all classes. Ties keep the
        vectorizer's alphabetical order. A corpus with no usable terms gives empty lists.
    Returns:
        For each class document, its top `top_n` terms, best first.
    Parameters:
        class_docs: One concatenated document per class.
        top_n: Number of terms to keep per class.
    """
    if not class_docs:
        return []
    vectorizer = _vectorizer()
    try:
        counts = vectorizer.fit_transform(class_docs).toarray().astype(float)
    except ValueError:  # empty vocabulary: only stop words or no text
        return [[] for _ in class_docs]
    terms = vectorizer.get_feature_names_out()
    words_per_class = np.array([len(re.findall(r"\b\w\w+\b", doc)) for doc in class_docs], dtype=float)
    average = max(words_per_class.mean(), 1.0)
    frequency = counts.sum(axis=0)
    scores = counts * np.log(1 + average / np.maximum(frequency, 1.0))
    ranked: list[list[str]] = []
    for row in scores:
        order = np.argsort(-row, kind="stable")
        ranked.append([str(terms[i]) for i in order[:top_n] if row[i] > 0])
    return ranked


def _title_case(term: str) -> str:
    return " ".join(word[:1].upper() + word[1:] for word in term.split())


def display_term(term: str, texts: Sequence[str]) -> str:
    """Write a lowercase vectorizer term the way the source text does.

    Behavior:
        Finds the term's first appearance in `texts` (case-insensitive, any non-word characters
        between its words). If that appearance has a capital letter it is used as written, e.g.
        `UW CS` or `Immich`; otherwise the term is title-cased.
    Returns:
        The display form of the term.
    Parameters:
        term: A unigram or bigram from `CountVectorizer`.
        texts: Texts to search, in priority order.
    """
    pattern = r"\b" + r"\W+".join(re.escape(word) for word in term.split()) + r"\b"
    for text in texts:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found = " ".join(match.group(0).split())
            return found if found != found.lower() else _title_case(found)
    return _title_case(term)


def project_name(titles: Sequence[str], keywords: Sequence[str], texts: Sequence[str] = ()) -> str:
    """Choose a project name from member titles and c-TF-IDF keywords.

    Behavior:
        Counts in how many member titles each title unigram or bigram (English stop words removed)
        appears. The most frequent one names the project when it appears in at least 30% of the
        titles and in at least 2 of them; ties prefer a term ranked higher in `keywords`, then a
        bigram, then alphabetical order. Otherwise the name is the top 2 keywords joined by ` · `.
        Terms are written as in the titles (then `texts`) when that casing has a capital letter,
        and title-cased otherwise (`display_term`).
    Returns:
        The project name; `Untitled project` when there are neither titles nor keywords.
    Parameters:
        titles: Member episode titles.
        keywords: The project's keywords, best first.
        texts: Member texts searched for a keyword's casing after the titles.
    """
    usable = [t for t in titles if t.strip()]
    if usable:
        vectorizer = CountVectorizer(ngram_range=(1, 2), stop_words="english", binary=True)
        try:
            present = vectorizer.fit_transform(usable).toarray().sum(axis=0)
        except ValueError:
            present = None
        if present is not None:
            terms = vectorizer.get_feature_names_out()
            rank = {k: i for i, k in enumerate(keywords)}
            best = min(
                range(len(terms)),
                key=lambda i: (-present[i], rank.get(terms[i], len(rank)), -len(terms[i].split()), terms[i]),
            )
            needed = max(TITLE_NGRAM_MIN, math.ceil(TITLE_NGRAM_SHARE * len(usable) - 1e-9))
            if present[best] >= needed:
                return display_term(str(terms[best]), usable)
    if keywords:
        sources = [*usable, *texts]
        return NAME_SEPARATOR.join(display_term(k, sources) for k in keywords[:NAME_KEYWORDS])
    return "Untitled project"


def summary_section(keywords: Sequence[str], members: Sequence[Member]) -> str:
    """Render the extractive `## Summary (auto)` section of a project.

    Behavior:
        Lists the keywords, the 5 most recent member titles with their dates, and the date range
        of all members. A project without members says so.
    Returns:
        The section, starting with its heading and ending with one newline.
    Parameters:
        keywords: The project's keywords.
        members: Every member episode.
    """
    lines = [SUMMARY_HEADING, ""]
    if not members:
        lines.append("No episodes.")
        return "\n".join(lines) + "\n"
    if keywords:
        lines += [f"Keywords: {', '.join(keywords)}", ""]
    recent = sorted(members, key=lambda m: (m.created_at, m.title), reverse=True)[:SUMMARY_TITLES]
    lines.append("Recent episodes:")
    lines += [f"- {m.created_at.date().isoformat()} {' '.join(m.title.split())}" for m in recent]
    first = min(m.created_at for m in members).date().isoformat()
    last = max(m.created_at for m in members).date().isoformat()
    count = f"{len(members)} episode" + ("" if len(members) == 1 else "s")
    lines += ["", f"Date range: {first} to {last} ({count})"]
    return "\n".join(lines) + "\n"


def replace_summary(body: str, section: str) -> str:
    """Replace the `## Summary (auto)` section of a project body and keep everything else.

    Behavior:
        The section runs from its heading to the next `## ` heading. A body without one gets the
        section at the top, followed by a blank line.
    Returns:
        The new body.
    Parameters:
        body: The current project body.
        section: The rendered section from `summary_section`.
    """
    lines = body.split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == SUMMARY_HEADING)
    except StopIteration:
        rest = body.lstrip("\n")
        return section + ("\n" + rest if rest else "")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    head = "\n".join(lines[:start])
    tail = "\n".join(lines[end:])
    out = (head + "\n" if head else "") + section
    return out + ("\n" + tail if tail else "")

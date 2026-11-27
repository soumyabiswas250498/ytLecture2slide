"""Domain logic for configurable video exclusion keywords and Unicode-aware matching."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

DEFAULT_SUGGESTED_KEYWORDS: tuple[str, ...] = (
    "Math",
    "Mathematics",
    "Reasoning",
    "অঙ্ক",
    "গণিত",
    "রিজনিং",
)


class VideoExcludedError(Exception):
    """Raised when a video is excluded from processing by configured exclusion keywords."""

    def __init__(self, message: str, matched_keywords: list[str] | None = None) -> None:
        super().__init__(message)
        self.matched_keywords = matched_keywords or []


@dataclass(frozen=True)
class ExclusionMatchResult:
    excluded: bool
    matched_keywords: list[str]


@dataclass(frozen=True)
class ExclusionSettings:
    keywords: list[str]
    updated_at: datetime | None = None


def normalize_text(text: str) -> str:
    """Normalize Unicode representation (NFC) and collapse internal/outer whitespace."""
    nfc = unicodedata.normalize("NFC", text)
    return " ".join(nfc.split())


def normalize_keyword(keyword: str) -> str:
    """Normalize a single exclusion keyword and reject empty values."""
    cleaned = normalize_text(keyword)
    if not cleaned:
        raise ValueError("Exclusion keyword must not be empty.")
    if len(cleaned) > 120:
        raise ValueError("Exclusion keyword must be at most 120 characters.")
    return cleaned


def deduplicate_keywords(keywords: Sequence[str], *, reject_duplicates: bool = False) -> list[str]:
    """Normalize and deduplicate keywords using Unicode case-insensitive comparison."""
    result: list[str] = []
    seen: set[str] = set()
    for raw in keywords:
        cleaned = normalize_keyword(raw)
        key = cleaned.casefold()
        if key in seen:
            if reject_duplicates:
                raise ValueError(f"Duplicate exclusion keyword: '{cleaned}'.")
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def is_word_char(ch: str) -> bool:
    """Return True for Unicode letters, combining marks (e.g. Bengali matras), and numbers."""
    if not ch:
        return False
    return unicodedata.category(ch)[0] in {"L", "M", "N"}


def _compile_keyword_pattern(normalized_keyword: str) -> re.Pattern[str]:
    tokens = normalized_keyword.casefold().split()
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    return re.compile(pattern)


def match_title(title: str, keywords: Sequence[str]) -> ExclusionMatchResult:
    """Match exclusion keywords against a video title using Unicode-aware boundaries.

    Supports English and Bengali text, multi-word phrases, and punctuation without
    unintended substring matches inside unrelated words.
    """
    normalized_title = normalize_text(title).casefold()
    if not normalized_title or not keywords:
        return ExclusionMatchResult(excluded=False, matched_keywords=[])

    matched: list[str] = []
    for raw_keyword in keywords:
        cleaned = normalize_text(raw_keyword)
        if not cleaned:
            continue
        pattern = _compile_keyword_pattern(cleaned)
        for found in pattern.finditer(normalized_title):
            start, end = found.span()
            before_ok = start == 0 or not is_word_char(normalized_title[start - 1])
            after_ok = end == len(normalized_title) or not is_word_char(normalized_title[end])
            if before_ok and after_ok:
                matched.append(cleaned)
                break

    return ExclusionMatchResult(excluded=bool(matched), matched_keywords=matched)


def format_exclusion_reason(matched_keywords: Sequence[str]) -> str:
    """Build a human-readable explanation for an excluded video."""
    if not matched_keywords:
        return "Video is excluded by configured exclusion keywords."
    joined = ", ".join(matched_keywords)
    return f"Excluded by keyword(s): {joined}"

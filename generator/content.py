"""Content model for the neofetch-style info card.

The card's copy lives in ``profile.json`` rather than in Python, so the text can
be edited without touching the renderer.  This module parses that file into a
typed model and resolves the ``{token}`` placeholders against live GitHub data,
which is what lets a hand-written line like::

    {"type": "kv", "label": "repos", "value": "{repos} public"}

render as ``repos  19 public`` after a build.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .github import ProfileSnapshot, format_compact_number, summarise_languages

LOGGER = logging.getLogger(__name__)

__all__ = ["RowKind", "InfoRow", "InfoSection", "InfoContent", "build_token_map"]


class RowKind(str, Enum):
    """The kinds of line the info card knows how to render."""

    KEY_VALUE = "kv"
    BULLET = "bullet"
    TEXT = "text"
    RULE = "rule"
    BLANK = "blank"


@dataclass(frozen=True)
class InfoRow:
    """One rendered line of the info card."""

    kind: RowKind
    label: str = ""
    value: str = ""


@dataclass(frozen=True)
class InfoSection:
    """A titled block of rows."""

    title: str
    rows: tuple[InfoRow, ...]

    @property
    def line_count(self) -> int:
        """Total lines occupied, including the header and its rule."""
        return 1 + len(self.rows)


@dataclass(frozen=True)
class InfoContent:
    """The whole card: an ordered list of sections."""

    sections: tuple[InfoSection, ...] = field(default_factory=tuple)

    @property
    def total_lines(self) -> int:
        """Sum of every section's line count."""
        return sum(section.line_count for section in self.sections)

    def iter_rows(self) -> Iterator[tuple[int, InfoSection, InfoRow | None]]:
        """Yield ``(global_line_index, section, row)``.

        ``row`` is ``None`` for a section's header line, which lets the renderer
        walk the whole card in one pass and keep the stagger monotonic.
        """
        line_index = 0
        for section in self.sections:
            yield line_index, section, None
            line_index += 1
            for row in section.rows:
                yield line_index, section, row
                line_index += 1

    # -- loading ------------------------------------------------------------

    @classmethod
    def load(cls, path: Path, tokens: Mapping[str, str]) -> "InfoContent":
        """Load and resolve ``profile.json``.

        Args:
            path: Path to the content file.
            tokens: Substitution map produced by :func:`build_token_map`.

        Returns:
            The parsed content, or :meth:`fallback` if the file is missing or
            malformed — a build must never fail because of a typo in copy.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            LOGGER.warning("%s not found; using built-in content", path)
            return cls.fallback(tokens)
        except json.JSONDecodeError as error:
            LOGGER.error("%s is not valid JSON (%s); using built-in content", path, error)
            return cls.fallback(tokens)
        return cls.from_mapping(raw, tokens)

    @classmethod
    def from_mapping(cls, raw: Any, tokens: Mapping[str, str]) -> "InfoContent":
        """Build content from an already-parsed mapping."""
        sections: list[InfoSection] = []
        for section_data in _as_sequence(raw.get("sections") if isinstance(raw, dict) else None):
            title = _substitute(str(section_data.get("title", "")), tokens)
            rows = tuple(
                _parse_row(row_data, tokens)
                for row_data in _as_sequence(section_data.get("rows"))
            )
            sections.append(InfoSection(title=title, rows=rows))
        if not sections:
            LOGGER.warning("content file declared no sections; using built-in content")
            return cls.fallback(tokens)
        return cls(sections=tuple(sections))

    @classmethod
    def fallback(cls, tokens: Mapping[str, str]) -> "InfoContent":
        """A complete, presentable card built purely from live data."""
        return cls.from_mapping(_FALLBACK_CONTENT, tokens)


def _parse_row(raw: Any, tokens: Mapping[str, str]) -> InfoRow:
    """Parse a single row object, defaulting unknown kinds to plain text."""
    if not isinstance(raw, dict):
        return InfoRow(kind=RowKind.TEXT, value=_substitute(str(raw), tokens))
    try:
        kind = RowKind(str(raw.get("type", "text")))
    except ValueError:
        LOGGER.warning("unknown row type %r; rendering as text", raw.get("type"))
        kind = RowKind.TEXT
    return InfoRow(
        kind=kind,
        label=_substitute(str(raw.get("label", "")), tokens),
        value=_substitute(str(raw.get("value", "")), tokens),
    )


def _as_sequence(value: Any) -> Sequence[Any]:
    """Coerce a possibly-missing JSON array into a sequence of mappings."""
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return []


def _substitute(text: str, tokens: Mapping[str, str]) -> str:
    """Replace ``{token}`` placeholders, leaving unknown ones untouched."""
    if "{" not in text:
        return text
    result = text
    for key, replacement in tokens.items():
        placeholder = "{" + key + "}"
        if placeholder in result:
            result = result.replace(placeholder, replacement)
    return result


def build_token_map(snapshot: ProfileSnapshot, *, tagline: str) -> dict[str, str]:
    """Build the ``{token}`` substitution map from a live profile snapshot.

    Args:
        snapshot: The resolved GitHub data.
        tagline: The configured one-line description.

    Returns:
        A flat mapping of token name to rendered string.  Every value is a
        string so that content authors never have to think about formatting.
    """
    user = snapshot.user
    calendar = snapshot.calendar
    languages = snapshot.language_stats(limit=4)

    tokens: dict[str, str] = {
        "login": user.login,
        "name": user.display_name,
        "tagline": tagline,
        "bio": user.bio or tagline,
        # No invented defaults.  If GitHub has no company or location on file,
        # the card says so rather than asserting something plausible — this is
        # copy about a real person, and a confident guess is worse than a dash.
        "company": user.company or "—",
        "location": user.location or "—",
        "repos": format_compact_number(user.public_repos),
        "followers": format_compact_number(user.followers),
        "following": format_compact_number(user.following),
        "stars": format_compact_number(snapshot.total_stars),
        "member_since": user.member_since,
        "account_age": f"{user.account_age_years:.1f}y",
        "top_language": snapshot.top_language,
        "languages": summarise_languages(languages) or "—",
        "language_list": ", ".join(stat.name for stat in languages) or "—",
        "today": date.today().isoformat(),
        "year": str(date.today().year),
        "data_source": user.source,
    }

    if calendar is not None:
        tokens.update(
            {
                "contributions": format_compact_number(calendar.total),
                "active_days": str(calendar.active_days),
                "longest_streak": f"{calendar.longest_streak()}d",
                "current_streak": f"{calendar.current_streak()}d",
                "busiest_day": (
                    str(calendar.busiest_day.count) if calendar.busiest_day else "0"
                ),
            }
        )
    else:  # pragma: no cover - only when the calendar is disabled entirely
        tokens.update(
            {
                "contributions": "0",
                "active_days": "0",
                "longest_streak": "0d",
                "current_streak": "0d",
                "busiest_day": "0",
            }
        )
    return tokens


#: Built-in content, used when ``profile.json`` is missing or unreadable.
#: It is intentionally complete rather than a stub: an offline first run should
#: still produce a card worth looking at.
_FALLBACK_CONTENT: dict[str, Any] = {
    "sections": [
        {
            "title": "ABOUT",
            "rows": [
                {"type": "kv", "label": "user", "value": "{login}@github"},
                {"type": "kv", "label": "focus", "value": "{tagline}"},
                {"type": "kv", "label": "location", "value": "{location}"},
                {"type": "kv", "label": "member since", "value": "{member_since}"},
                {"type": "kv", "label": "repositories", "value": "{repos} public"},
            ],
        },
        {
            "title": "STACK",
            "rows": [
                {"type": "bullet", "value": "{language_list}"},
                {"type": "bullet", "value": "Azure · AKS · Terraform"},
                {"type": "bullet", "value": "Docker · GitHub Actions"},
                {"type": "bullet", "value": "LangChain · RAG pipelines"},
            ],
        },
        {
            "title": "HIGHLIGHTS",
            "rows": [
                {"type": "kv", "label": "contributions", "value": "{contributions}"},
                {"type": "kv", "label": "active days", "value": "{active_days}"},
                {"type": "kv", "label": "longest streak", "value": "{longest_streak}"},
                {"type": "kv", "label": "languages", "value": "{languages}"},
            ],
        },
    ]
}

"""GitHub data acquisition with deterministic offline fallbacks.

A profile README must rebuild successfully on a laptop with no network, inside
a CI runner with an anonymous rate-limited IP, and on a machine where the user
has never created a personal access token.  Every fetch in this module
therefore follows the same three-tier strategy:

1. **Live** — hit GitHub and use the real answer.
2. **Cache** — replay the last successful response from ``assets/cache``.
3. **Synthetic** — generate deterministic, plausible data seeded by the
   username, so the build still produces a beautiful, stable artefact.

The contribution calendar is read from GitHub's public HTML fragment rather
than the GraphQL API, because that endpoint needs no authentication at all.
"""

from __future__ import annotations

import json
import logging
import math
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

try:  # pragma: no cover - exercised implicitly by the offline path
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

__all__ = [
    "ContributionDay",
    "ContributionCalendar",
    "Repository",
    "UserProfile",
    "LanguageStat",
    "ProfileSnapshot",
    "GitHubClient",
    "synthesize_calendar",
]

_API_ROOT = "https://api.github.com"
_HTML_ROOT = "https://github.com"
_USER_AGENT = "animated-profile-generator/1.0 (+https://github.com)"
_DAYS_PER_WEEK = 7
_MAX_LEVEL = 4

#: One ``<td>`` of GitHub's calendar table.
_CELL_PATTERN = re.compile(
    r"<td\b(?P<attributes>[^>]*?\bclass=\"[^\"]*ContributionCalendar-day[^\"]*\"[^>]*)>",
    re.IGNORECASE,
)
_ATTRIBUTE_PATTERN = re.compile(r'([a-zA-Z0-9_:-]+)="([^"]*)"')
_CELL_ID_PATTERN = re.compile(r"contribution-day-component-(?P<row>\d+)-(?P<column>\d+)")
_TOOLTIP_PATTERN = re.compile(
    r'<tool-tip\b[^>]*\bfor="(?P<target>contribution-day-component-[\d-]+)"[^>]*>'
    r"(?P<label>[^<]*)</tool-tip>",
    re.IGNORECASE,
)
_TOOLTIP_COUNT_PATTERN = re.compile(r"^(?P<count>[\d,]+)\s+contribution")
_TOTAL_PATTERN = re.compile(
    r"([\d,]+)\s*\n?\s*contributions?\s*\n?\s*in the last year", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContributionDay:
    """A single day cell of the contribution calendar."""

    day: date
    count: int
    level: int

    @property
    def is_active(self) -> bool:
        """Whether the day recorded at least one contribution."""
        return self.count > 0


@dataclass
class ContributionCalendar:
    """A 53x7 contribution calendar in GitHub's own column-major layout.

    Attributes:
        columns: ``columns[week][weekday]``; ``None`` marks a cell outside the
            reported range, exactly as GitHub renders blank corners.
        total: Total contributions in the window.
        source: ``"live"``, ``"cache"`` or ``"synthetic"``.
    """

    columns: list[list[ContributionDay | None]]
    total: int
    source: str = "synthetic"

    # -- shape --------------------------------------------------------------

    @property
    def column_count(self) -> int:
        """Number of week columns."""
        return len(self.columns)

    @property
    def row_count(self) -> int:
        """Number of weekday rows."""
        return _DAYS_PER_WEEK

    def cell(self, column: int, row: int) -> ContributionDay | None:
        """Return the day at ``(column, row)`` or ``None`` if out of range."""
        if 0 <= column < len(self.columns) and 0 <= row < _DAYS_PER_WEEK:
            return self.columns[column][row]
        return None

    def iter_cells(self) -> Iterator[tuple[int, int, ContributionDay | None]]:
        """Yield ``(column, row, day)`` for every grid position."""
        for column_index, column in enumerate(self.columns):
            for row_index, day in enumerate(column):
                yield column_index, row_index, day

    def iter_days(self) -> Iterator[ContributionDay]:
        """Yield every populated day in chronological order."""
        for _, _, day in sorted(
            self.iter_cells(), key=lambda item: (item[0], item[1])
        ):
            if day is not None:
                yield day

    # -- derived statistics -------------------------------------------------

    @property
    def days(self) -> list[ContributionDay]:
        """All populated days, chronologically."""
        return list(self.iter_days())

    @property
    def active_days(self) -> int:
        """Number of days with at least one contribution."""
        return sum(1 for day in self.iter_days() if day.is_active)

    @property
    def busiest_day(self) -> ContributionDay | None:
        """The single highest-count day, if any."""
        days = self.days
        return max(days, key=lambda day: day.count) if days else None

    @property
    def glowing_cell_count(self) -> int:
        """How many cells sit at or above the glow threshold level 3."""
        return sum(1 for day in self.iter_days() if day.level >= 3)

    def longest_streak(self) -> int:
        """Longest run of consecutive active days."""
        best = current = 0
        for day in self.iter_days():
            current = current + 1 if day.is_active else 0
            best = max(best, current)
        return best

    def current_streak(self) -> int:
        """Length of the active streak ending on the most recent day."""
        streak = 0
        for day in reversed(self.days):
            if not day.is_active:
                break
            streak += 1
        return streak

    def monthly_boundaries(self) -> list[tuple[int, str]]:
        """Return ``(column, month_abbreviation)`` for each month's first week.

        GitHub labels a column with a month name when that column contains the
        first appearance of the month, which is what this reproduces.
        """
        labels: list[tuple[int, str]] = []
        seen: set[tuple[int, int]] = set()
        for column_index, column in enumerate(self.columns):
            for day in column:
                if day is None:
                    continue
                key = (day.day.year, day.day.month)
                if key not in seen:
                    seen.add(key)
                    labels.append((column_index, day.day.strftime("%b")))
                break
        return labels


@dataclass(frozen=True)
class Repository:
    """A public repository, reduced to what the profile cards need."""

    name: str
    description: str | None
    language: str | None
    stars: int
    forks: int
    updated_at: datetime | None
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class LanguageStat:
    """Share of a user's public repositories written in one language."""

    name: str
    repository_count: int
    share: float


@dataclass(frozen=True)
class UserProfile:
    """The subset of a GitHub user record the cards render."""

    login: str
    name: str | None
    bio: str | None
    company: str | None
    location: str | None
    avatar_url: str
    public_repos: int
    followers: int
    following: int
    created_at: datetime | None
    source: str = "synthetic"

    @property
    def display_name(self) -> str:
        """Best available human-facing name."""
        return self.name or self.login

    @property
    def member_since(self) -> str:
        """Year the account was created, or ``"—"`` when unknown."""
        return str(self.created_at.year) if self.created_at else "—"

    @property
    def account_age_years(self) -> float:
        """Fractional account age in years."""
        if not self.created_at:
            return 0.0
        delta = datetime.now(timezone.utc) - self.created_at
        return delta.days / 365.25


@dataclass
class ProfileSnapshot:
    """Everything the generators need, resolved once per build."""

    user: UserProfile
    repositories: list[Repository] = field(default_factory=list)
    calendar: ContributionCalendar | None = None
    avatar_path: Path | None = None

    @property
    def total_stars(self) -> int:
        """Sum of stargazers across all public repositories."""
        return sum(repository.stars for repository in self.repositories)

    def language_stats(self, limit: int = 6) -> list[LanguageStat]:
        """Top languages by repository count.

        Args:
            limit: Maximum number of languages to return.

        Returns:
            Languages ordered by descending repository count.
        """
        counts: dict[str, int] = {}
        for repository in self.repositories:
            if repository.language:
                counts[repository.language] = counts.get(repository.language, 0) + 1
        total = sum(counts.values())
        if not total:
            return []
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [
            LanguageStat(name=name, repository_count=count, share=count / total)
            for name, count in ordered[:limit]
        ]

    @property
    def top_language(self) -> str:
        """The most-used language, or a sensible default."""
        stats = self.language_stats(limit=1)
        return stats[0].name if stats else "Python"


# ---------------------------------------------------------------------------
# Synthetic data
# ---------------------------------------------------------------------------


def synthesize_calendar(
    seed_text: str,
    *,
    columns: int = 53,
    end_day: date | None = None,
) -> ContributionCalendar:
    """Build a deterministic, realistic-looking contribution calendar.

    Real calendars are not uniform noise: they cluster into working weeks, dip
    at weekends, and punctuate quiet stretches with multi-day bursts.  The
    model below reproduces those three behaviours so that an offline build is
    visually indistinguishable from a live one.

    Args:
        seed_text: Any stable string; the same input always yields the same
            calendar, which keeps offline rebuilds byte-identical.
        columns: Number of week columns to emit.
        end_day: Last day of the window; defaults to today (UTC).

    Returns:
        A fully populated :class:`ContributionCalendar` with source
        ``"synthetic"``.
    """
    rng = random.Random(f"contribution-calendar::{seed_text}")
    last_day = end_day or datetime.now(timezone.utc).date()

    # GitHub's grid always ends on a Saturday-terminated week; align to it.
    # Python's weekday(): Monday == 0 ... Sunday == 6; GitHub rows start Sunday.
    trailing_days = (last_day.weekday() + 1) % _DAYS_PER_WEEK
    grid_start = last_day - timedelta(days=trailing_days + (columns - 1) * _DAYS_PER_WEEK)

    # A slow seasonal envelope so activity waxes and wanes across the year.
    phase = rng.uniform(0.0, math.tau)
    burst_remaining = 0
    burst_strength = 0.0

    grid: list[list[ContributionDay | None]] = []
    total = 0

    for column_index in range(columns):
        week: list[ContributionDay | None] = []
        for row_index in range(_DAYS_PER_WEEK):
            offset = column_index * _DAYS_PER_WEEK + row_index
            current = grid_start + timedelta(days=offset)

            if current > last_day:
                week.append(None)
                continue

            season = 0.55 + 0.45 * math.sin(phase + offset / 46.0)
            weekday_weight = 0.34 if row_index in (0, 6) else 1.0

            if burst_remaining > 0:
                burst_remaining -= 1
            elif rng.random() < 0.035:
                burst_remaining = rng.randint(2, 9)
                burst_strength = rng.uniform(1.8, 3.4)
            else:
                burst_strength = 1.0

            intensity = season * weekday_weight * (
                burst_strength if burst_remaining > 0 else 1.0
            )
            if rng.random() > 0.30 * intensity + 0.12:
                count = 0
            else:
                count = max(1, int(rng.gammavariate(1.7, 2.4 * intensity)))

            total += count
            week.append(ContributionDay(day=current, count=count, level=_level_for(count)))
        grid.append(week)

    return ContributionCalendar(columns=grid, total=total, source="synthetic")


def _level_for(count: int) -> int:
    """Map a raw contribution count onto GitHub's 0..4 intensity ramp."""
    if count <= 0:
        return 0
    if count <= 2:
        return 1
    if count <= 5:
        return 2
    if count <= 9:
        return 3
    return _MAX_LEVEL


def synthesize_user(login: str) -> UserProfile:
    """Build a placeholder profile when GitHub cannot be reached at all."""
    return UserProfile(
        login=login,
        name=login,
        bio=None,
        company=None,
        location=None,
        avatar_url=f"{_HTML_ROOT}/{login}.png",
        public_repos=0,
        followers=0,
        following=0,
        created_at=None,
        source="synthetic",
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Fetches everything the build needs, never raising on network failure.

    Args:
        username: The GitHub login to profile.
        cache_dir: Directory for replayable responses.
        token: Optional PAT; only lifts anonymous rate limits.
        timeout: Per-request timeout in seconds.
        use_cache: Whether to read and write the response cache.
    """

    def __init__(
        self,
        username: str,
        *,
        cache_dir: Path,
        token: str | None = None,
        timeout: float = 12.0,
        use_cache: bool = True,
    ) -> None:
        self.username = username
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.use_cache = use_cache
        self._session = self._build_session(token)

    # -- public API ---------------------------------------------------------

    def fetch_snapshot(self, *, avatar_path: Path) -> ProfileSnapshot:
        """Resolve the user, repositories, calendar and avatar in one call."""
        user = self.fetch_user()
        repositories = self.fetch_repositories()
        calendar = self.fetch_contributions()
        avatar = self.download_avatar(avatar_path)
        return ProfileSnapshot(
            user=user,
            repositories=repositories,
            calendar=calendar,
            avatar_path=avatar,
        )

    def fetch_user(self) -> UserProfile:
        """Return the user record, falling back to cache then to a stub."""
        payload, source = self._get_json(
            f"{_API_ROOT}/users/{self.username}", cache_key="user"
        )
        if payload is None:
            LOGGER.warning("using synthetic profile for %s", self.username)
            return synthesize_user(self.username)
        return UserProfile(
            login=payload.get("login", self.username),
            name=payload.get("name"),
            bio=payload.get("bio"),
            company=payload.get("company"),
            location=payload.get("location"),
            avatar_url=payload.get("avatar_url", f"{_HTML_ROOT}/{self.username}.png"),
            public_repos=int(payload.get("public_repos", 0) or 0),
            followers=int(payload.get("followers", 0) or 0),
            following=int(payload.get("following", 0) or 0),
            created_at=_parse_timestamp(payload.get("created_at")),
            source=source,
        )

    def fetch_repositories(self, *, per_page: int = 100) -> list[Repository]:
        """Return the user's public repositories, newest first."""
        payload, _ = self._get_json(
            f"{_API_ROOT}/users/{self.username}/repos"
            f"?per_page={per_page}&sort=updated&type=owner",
            cache_key="repos",
        )
        if not isinstance(payload, list):
            return []
        repositories = [
            Repository(
                name=item.get("name", ""),
                description=item.get("description"),
                language=item.get("language"),
                stars=int(item.get("stargazers_count", 0) or 0),
                forks=int(item.get("forks_count", 0) or 0),
                updated_at=_parse_timestamp(item.get("updated_at")),
                topics=tuple(item.get("topics") or ()),
            )
            for item in payload
            if not item.get("fork")
        ]
        return repositories

    def fetch_contributions(self) -> ContributionCalendar:
        """Return the live contribution calendar, or a synthetic stand-in."""
        markup, source = self._get_text(
            f"{_HTML_ROOT}/users/{self.username}/contributions",
            cache_key="contributions",
            accept="text/html",
        )
        if markup is None:
            LOGGER.warning("using synthetic calendar for %s", self.username)
            return synthesize_calendar(self.username)
        try:
            calendar = parse_contribution_html(markup)
        except ValueError as error:
            LOGGER.warning("contribution parse failed (%s); synthesising", error)
            return synthesize_calendar(self.username)
        calendar.source = source
        return calendar

    def download_avatar(self, destination: Path) -> Path | None:
        """Download the user's avatar, keeping any previously cached copy.

        Args:
            destination: Where to write the PNG.

        Returns:
            The path if an avatar is available on disk afterwards, else ``None``.
        """
        url = f"{_HTML_ROOT}/{self.username}.png?size=512"
        if self._session is not None:
            try:
                response = self._session.get(url, timeout=self.timeout)
                response.raise_for_status()
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.content)
                LOGGER.info("avatar downloaded (%d bytes)", len(response.content))
                return destination
            except Exception as error:  # noqa: BLE001 - offline builds are normal
                LOGGER.warning("avatar download failed: %s", error)
        return destination if destination.exists() else None

    # -- transport ----------------------------------------------------------

    @staticmethod
    def _build_session(token: str | None) -> Any | None:
        """Create a configured ``requests`` session, or ``None`` if unavailable."""
        if requests is None:
            LOGGER.warning("requests is not installed; running fully offline")
            return None
        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": _USER_AGENT,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if token:
            session.headers["Authorization"] = f"Bearer {token}"
        return session

    def _cache_path(self, cache_key: str, suffix: str) -> Path:
        return self.cache_dir / f"{self.username}.{cache_key}{suffix}"

    def _get_text(
        self, url: str, *, cache_key: str, accept: str | None = None
    ) -> tuple[str | None, str]:
        """Fetch text with cache write-through and cache-replay fallback."""
        cache_path = self._cache_path(cache_key, ".html")
        if self._session is not None:
            try:
                headers = {"Accept": accept} if accept else None
                response = self._session.get(url, timeout=self.timeout, headers=headers)
                response.raise_for_status()
                if self.use_cache:
                    self._write_cache(cache_path, response.text)
                return response.text, "live"
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("GET %s failed: %s", url, error)
        if self.use_cache and cache_path.exists():
            LOGGER.info("replaying cached response for %s", cache_key)
            return cache_path.read_text(encoding="utf-8"), "cache"
        return None, "synthetic"

    def _get_json(self, url: str, *, cache_key: str) -> tuple[Any | None, str]:
        """Fetch JSON with cache write-through and cache-replay fallback."""
        cache_path = self._cache_path(cache_key, ".json")
        if self._session is not None:
            try:
                response = self._session.get(url, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if self.use_cache:
                    self._write_cache(
                        cache_path, json.dumps(payload, indent=2, ensure_ascii=False)
                    )
                return payload, "live"
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("GET %s failed: %s", url, error)
        if self.use_cache and cache_path.exists():
            LOGGER.info("replaying cached response for %s", cache_key)
            try:
                return json.loads(cache_path.read_text(encoding="utf-8")), "cache"
            except json.JSONDecodeError as error:  # pragma: no cover
                LOGGER.warning("cache for %s is corrupt: %s", cache_key, error)
        return None, "synthetic"

    @staticmethod
    def _write_cache(path: Path, content: str) -> None:
        """Persist a response body, ignoring filesystem errors."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as error:  # pragma: no cover
            LOGGER.warning("could not write cache %s: %s", path, error)


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def parse_contribution_html(markup: str) -> ContributionCalendar:
    """Parse GitHub's public contribution fragment into a calendar.

    The fragment is a ``<table>`` whose cells carry ``data-date``,
    ``data-level`` and an id of the form
    ``contribution-day-component-<row>-<column>``.  Exact counts live in a
    sibling ``<tool-tip>`` element keyed by that id.

    Args:
        markup: The raw HTML returned by ``/users/<login>/contributions``.

    Returns:
        The parsed :class:`ContributionCalendar`.

    Raises:
        ValueError: If no calendar cells are present.
    """
    counts = _parse_tooltip_counts(markup)

    cells: dict[tuple[int, int], ContributionDay] = {}
    max_column = -1
    for match in _CELL_PATTERN.finditer(markup):
        attributes = dict(_ATTRIBUTE_PATTERN.findall(match["attributes"]))
        cell_id = attributes.get("id", "")
        position = _CELL_ID_PATTERN.search(cell_id)
        raw_date = attributes.get("data-date")
        if not position or not raw_date:
            continue
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:  # pragma: no cover - defensive
            continue

        row = int(position["row"])
        column = int(position["column"])
        level = _clamp_level(attributes.get("data-level"))
        count = counts.get(cell_id)
        if count is None:
            # Fall back to the midpoint of the level's plausible range.
            count = (0, 1, 3, 7, 12)[level]
        cells[(column, row)] = ContributionDay(day=day, count=count, level=level)
        max_column = max(max_column, column)

    if not cells:
        raise ValueError("no contribution cells found in markup")

    columns: list[list[ContributionDay | None]] = [
        [cells.get((column, row)) for row in range(_DAYS_PER_WEEK)]
        for column in range(max_column + 1)
    ]

    total = _parse_reported_total(markup)
    if total is None:
        total = sum(day.count for day in cells.values())

    return ContributionCalendar(columns=columns, total=total, source="live")


def _parse_tooltip_counts(markup: str) -> dict[str, int]:
    """Extract exact per-day counts from the accessibility tooltips."""
    counts: dict[str, int] = {}
    for match in _TOOLTIP_PATTERN.finditer(markup):
        label = match["label"].strip()
        target = match["target"]
        number = _TOOLTIP_COUNT_PATTERN.match(label)
        counts[target] = int(number["count"].replace(",", "")) if number else 0
    return counts


def _parse_reported_total(markup: str) -> int | None:
    """Read the "N contributions in the last year" headline, if present."""
    match = _TOTAL_PATTERN.search(markup)
    return int(match.group(1).replace(",", "")) if match else None


def _clamp_level(raw: str | None) -> int:
    """Coerce a ``data-level`` attribute into the 0..4 range."""
    try:
        return max(0, min(_MAX_LEVEL, int(raw or 0)))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 0


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse an ISO-8601 GitHub timestamp into an aware ``datetime``."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:  # pragma: no cover - defensive
        return None


def resolve_calendar(
    client: GitHubClient | None,
    *,
    source_mode: str,
    seed: str,
    columns: int,
) -> ContributionCalendar:
    """Apply the configured data-source policy to produce a calendar.

    Args:
        client: A live client, or ``None`` to force synthetic data.
        source_mode: ``"auto"``, ``"live"`` or ``"synthetic"``.
        seed: Seed string for synthetic generation.
        columns: Number of week columns to render.

    Returns:
        The calendar chosen by the policy, trimmed or padded to ``columns``.
    """
    if source_mode == "synthetic" or client is None:
        calendar = synthesize_calendar(seed, columns=columns)
    else:
        calendar = client.fetch_contributions()
        if source_mode == "live" and calendar.source == "synthetic":
            LOGGER.warning("live contributions unavailable; emitting empty calendar")
    return _fit_columns(calendar, columns)


def _fit_columns(calendar: ContributionCalendar, columns: int) -> ContributionCalendar:
    """Trim from the left, or left-pad with blanks, to hit ``columns`` exactly."""
    current = calendar.column_count
    if current == columns:
        return calendar
    if current > columns:
        calendar.columns = calendar.columns[current - columns :]
    else:
        blank: list[ContributionDay | None] = [None] * _DAYS_PER_WEEK
        calendar.columns = [list(blank) for _ in range(columns - current)] + calendar.columns
    return calendar


def format_compact_number(value: int) -> str:
    """Render an integer the way GitHub does: ``1.2k``, ``18``, ``4.5M``."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return str(value)


def summarise_languages(stats: Sequence[LanguageStat]) -> str:
    """Render language stats as a compact ``Python 62% · HCL 12%`` string."""
    return " · ".join(f"{stat.name} {stat.share * 100:.0f}%" for stat in stats)

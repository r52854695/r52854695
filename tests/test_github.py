"""Tests for GitHub data parsing and the synthetic fallback."""

from __future__ import annotations

import unittest
from datetime import date

from generator.github import (
    ContributionCalendar,
    ContributionDay,
    ProfileSnapshot,
    Repository,
    UserProfile,
    format_compact_number,
    parse_contribution_html,
    synthesize_calendar,
)

#: A faithful miniature of GitHub's contribution fragment: two week columns,
#: a blank leading cell, and the tooltips that carry the exact counts.
SAMPLE_MARKUP = """
<h2 class="f4 text-normal mb-2">
  1,234
  contributions
    in the last year
</h2>
<table>
<tbody>
<tr>
<td tabindex="0" data-ix="0" style="width: 11px" data-date="2025-07-20"
    id="contribution-day-component-0-0" data-level="0"
    class="ContributionCalendar-day"></td>
<td tabindex="0" data-ix="1" style="width: 11px" data-date="2025-07-27"
    id="contribution-day-component-0-1" data-level="4"
    class="ContributionCalendar-day"></td>
</tr>
<tr>
<td tabindex="0" data-ix="0" style="width: 11px" data-date="2025-07-21"
    id="contribution-day-component-1-0" data-level="2"
    class="ContributionCalendar-day"></td>
<td tabindex="0" data-ix="1" style="width: 11px" data-date="2025-07-28"
    id="contribution-day-component-1-1" data-level="1"
    class="ContributionCalendar-day"></td>
</tr>
</tbody>
</table>
<tool-tip for="contribution-day-component-0-0" class="sr-only">No contributions on July 20th.</tool-tip>
<tool-tip for="contribution-day-component-0-1" class="sr-only">17 contributions on July 27th.</tool-tip>
<tool-tip for="contribution-day-component-1-0" class="sr-only">4 contributions on July 21st.</tool-tip>
<tool-tip for="contribution-day-component-1-1" class="sr-only">1 contribution on July 28th.</tool-tip>
"""


class ContributionParsingTests(unittest.TestCase):
    """The HTML fragment is the only unauthenticated source of real data."""

    def setUp(self) -> None:
        self.calendar = parse_contribution_html(SAMPLE_MARKUP)

    def test_grid_is_column_major(self) -> None:
        self.assertEqual(self.calendar.column_count, 2)
        self.assertEqual(self.calendar.row_count, 7)

    def test_levels_are_read_from_the_cells(self) -> None:
        self.assertEqual(self.calendar.cell(0, 0).level, 0)
        self.assertEqual(self.calendar.cell(1, 0).level, 4)
        self.assertEqual(self.calendar.cell(0, 1).level, 2)

    def test_counts_come_from_the_tooltips(self) -> None:
        self.assertEqual(self.calendar.cell(1, 0).count, 17)
        self.assertEqual(self.calendar.cell(1, 1).count, 1)
        self.assertEqual(self.calendar.cell(0, 0).count, 0)

    def test_dates_are_parsed(self) -> None:
        self.assertEqual(self.calendar.cell(0, 0).day, date(2025, 7, 20))

    def test_headline_total_wins_over_the_cell_sum(self) -> None:
        # GitHub's headline counts private contributions the grid cannot show.
        self.assertEqual(self.calendar.total, 1234)

    def test_cells_outside_the_range_are_none(self) -> None:
        self.assertIsNone(self.calendar.cell(0, 5))

    def test_source_is_marked_live(self) -> None:
        self.assertEqual(self.calendar.source, "live")

    def test_empty_markup_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_contribution_html("<html><body>nothing</body></html>")


class CalendarStatisticsTests(unittest.TestCase):
    """Derived statistics feed both the calendar card and the info card."""

    def build(self, counts: list[int]) -> ContributionCalendar:
        """Build a single-week-per-column calendar from a flat count list."""
        columns: list[list[ContributionDay | None]] = []
        for index in range(0, len(counts), 7):
            week = counts[index : index + 7]
            columns.append(
                [
                    ContributionDay(
                        day=date(2025, 1, 1),
                        count=count,
                        level=min(4, count),
                    )
                    for count in week
                ]
                + [None] * (7 - len(week))
            )
        return ContributionCalendar(columns=columns, total=sum(counts))

    def test_active_days_counts_only_non_zero(self) -> None:
        self.assertEqual(self.build([0, 1, 0, 3, 0, 0, 2]).active_days, 3)

    def test_longest_streak_spans_column_boundaries(self) -> None:
        calendar = self.build([0, 0, 0, 0, 0, 1, 1] + [1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(calendar.longest_streak(), 4)

    def test_current_streak_counts_back_from_the_end(self) -> None:
        self.assertEqual(self.build([0, 5, 0, 2, 2, 2, 2]).current_streak(), 4)

    def test_current_streak_is_zero_when_the_last_day_is_empty(self) -> None:
        self.assertEqual(self.build([3, 3, 3, 3, 3, 3, 0]).current_streak(), 0)

    def test_busiest_day_is_the_maximum(self) -> None:
        self.assertEqual(self.build([1, 9, 4]).busiest_day.count, 9)

    def test_glowing_cell_count_uses_level_three_and_above(self) -> None:
        self.assertEqual(self.build([0, 1, 2, 3, 4, 4, 0]).glowing_cell_count, 3)

    def test_month_boundaries_label_the_first_column_of_each_month(self) -> None:
        columns: list[list[ContributionDay | None]] = [
            [ContributionDay(day=date(2025, 1, 6), count=0, level=0)] + [None] * 6,
            [ContributionDay(day=date(2025, 2, 3), count=0, level=0)] + [None] * 6,
        ]
        calendar = ContributionCalendar(columns=columns, total=0)
        self.assertEqual(calendar.monthly_boundaries(), [(0, "Jan"), (1, "Feb")])


class SyntheticCalendarTests(unittest.TestCase):
    """Offline builds must be deterministic and plausible."""

    def test_same_seed_produces_an_identical_calendar(self) -> None:
        end = date(2026, 7, 25)
        first = synthesize_calendar("someone", end_day=end)
        second = synthesize_calendar("someone", end_day=end)
        self.assertEqual(
            [day.count for day in first.iter_days()],
            [day.count for day in second.iter_days()],
        )

    def test_different_seeds_diverge(self) -> None:
        end = date(2026, 7, 25)
        first = synthesize_calendar("someone", end_day=end)
        second = synthesize_calendar("someone-else", end_day=end)
        self.assertNotEqual(
            [day.count for day in first.iter_days()],
            [day.count for day in second.iter_days()],
        )

    def test_shape_matches_a_real_calendar(self) -> None:
        calendar = synthesize_calendar("x", columns=53, end_day=date(2026, 7, 25))
        self.assertEqual(calendar.column_count, 53)
        self.assertTrue(0 < calendar.active_days < 53 * 7)
        self.assertTrue(all(0 <= day.level <= 4 for day in calendar.iter_days()))

    def test_no_day_falls_after_the_window(self) -> None:
        end = date(2026, 7, 25)
        calendar = synthesize_calendar("x", end_day=end)
        self.assertTrue(all(day.day <= end for day in calendar.iter_days()))

    def test_weekends_are_quieter_than_weekdays(self) -> None:
        calendar = synthesize_calendar("statistics", end_day=date(2026, 7, 25))
        weekend = sum(
            day.count
            for column, row, day in calendar.iter_cells()
            if day is not None and row in (0, 6)
        )
        weekday = sum(
            day.count
            for column, row, day in calendar.iter_cells()
            if day is not None and row not in (0, 6)
        )
        # Five weekday rows against two weekend rows, with a weekend penalty.
        self.assertGreater(weekday / 5.0, weekend / 2.0)


class SnapshotTests(unittest.TestCase):
    """Language statistics drive both the info card and the hero."""

    def snapshot(self, languages: list[str | None]) -> ProfileSnapshot:
        user = UserProfile(
            login="octocat",
            name=None,
            bio=None,
            company=None,
            location=None,
            avatar_url="",
            public_repos=len(languages),
            followers=0,
            following=0,
            created_at=None,
        )
        repositories = [
            Repository(
                name=f"repo{index}",
                description=None,
                language=language,
                stars=index,
                forks=0,
                updated_at=None,
            )
            for index, language in enumerate(languages)
        ]
        return ProfileSnapshot(user=user, repositories=repositories)

    def test_languages_are_ranked_by_repository_count(self) -> None:
        stats = self.snapshot(["Python", "Python", "Go", None]).language_stats()
        self.assertEqual([stat.name for stat in stats], ["Python", "Go"])
        self.assertAlmostEqual(stats[0].share, 2 / 3)

    def test_top_language_falls_back_when_nothing_is_typed(self) -> None:
        self.assertEqual(self.snapshot([None, None]).top_language, "Python")

    def test_total_stars_sums_every_repository(self) -> None:
        self.assertEqual(self.snapshot(["Go", "Go", "Go"]).total_stars, 0 + 1 + 2)

    def test_display_name_falls_back_to_the_login(self) -> None:
        self.assertEqual(self.snapshot([]).user.display_name, "octocat")


class CompactNumberTests(unittest.TestCase):
    """Counts are rendered the way GitHub renders them."""

    def test_small_numbers_are_literal(self) -> None:
        self.assertEqual(format_compact_number(18), "18")

    def test_thousands_are_abbreviated(self) -> None:
        self.assertEqual(format_compact_number(1234), "1.2k")

    def test_round_thousands_drop_the_decimal(self) -> None:
        self.assertEqual(format_compact_number(2000), "2k")

    def test_millions_are_abbreviated(self) -> None:
        self.assertEqual(format_compact_number(3_400_000), "3.4M")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

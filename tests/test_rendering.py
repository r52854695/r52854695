"""End-to-end tests: the generators must produce valid, standalone assets.

These run the real build pipeline against synthetic data and then assert the
guarantees the project makes about its output — no network, no JavaScript, no
external references, and animation timing that actually holds together.
"""

from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ElementTree
from datetime import date

from config import CONFIG
from generator.avatar_to_ascii import AvatarAsciiConverter
from generator.colors import lighten, mix, parse_color, relative_luminance, with_alpha
from generator.content import InfoContent, RowKind, build_token_map
from generator.contribution_generator import ContributionGenerator
from generator.github import ProfileSnapshot, UserProfile, synthesize_calendar
from generator.hero_generator import HeroGenerator, HeroStats
from generator.info_generator import InfoGenerator
from generator.terminal_generator import TerminalGenerator

SVG_NAMESPACE = "http://www.w3.org/2000/svg"
REMOTE_REFERENCE = re.compile(r"(?:https?:)?//|^data:", re.IGNORECASE)


def portrait():
    """A deterministic ASCII portrait built from the procedural placeholder."""
    return AvatarAsciiConverter(
        width=CONFIG.terminal.ascii_width,
        cell_aspect=(
            CONFIG.typography.mono_advance_ratio
            / CONFIG.terminal.ascii_line_height_ratio
        ),
        ramp_name=CONFIG.terminal.ascii_density,
    ).convert_file(None)


def snapshot() -> ProfileSnapshot:
    """A fully synthetic profile snapshot."""
    return ProfileSnapshot(
        user=UserProfile(
            login="octocat",
            name="Octo Cat",
            bio=None,
            company=None,
            location=None,
            avatar_url="",
            public_repos=12,
            followers=3,
            following=1,
            created_at=None,
        ),
        repositories=[],
        calendar=synthesize_calendar("octocat", end_day=date(2026, 7, 25)),
    )


def parse(markup: str) -> ElementTree.Element:
    """Parse rendered markup, failing the test if it is not well-formed."""
    return ElementTree.fromstring(markup)


def iter_all(root: ElementTree.Element):
    """Yield the root and every descendant."""
    yield root
    for child in root:
        yield from iter_all(child)


def local(tag: str) -> str:
    """Strip the namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


class AssetContractTests(unittest.TestCase):
    """Every generated asset must honour the same standalone guarantees."""

    @classmethod
    def setUpClass(cls) -> None:
        data = snapshot()
        art = portrait()
        cls.documents = {
            "terminal": TerminalGenerator(CONFIG, art).build(),
            "info": InfoGenerator(
                CONFIG,
                InfoContent.fallback(build_token_map(data, tagline=CONFIG.tagline)),
            ).build(),
            "contribution": ContributionGenerator(CONFIG, data.calendar).build(),
            "hero": HeroGenerator(
                CONFIG,
                HeroStats(repositories=12, contributions=940, top_language="Python"),
            ).build(),
        }
        cls.markup = {name: document.render() for name, document in cls.documents.items()}

    def test_every_asset_is_well_formed_xml(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                root = parse(markup)
                self.assertEqual(local(root.tag), "svg")

    def test_no_scripts_styles_or_embedded_objects(self) -> None:
        forbidden = {"script", "style", "foreignObject", "image"}
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                tags = {local(element.tag) for element in iter_all(parse(markup))}
                self.assertFalse(tags & forbidden, f"{name} contains {tags & forbidden}")

    def test_no_external_references(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                for element in iter_all(parse(markup)):
                    for key, value in element.attrib.items():
                        self.assertIsNone(
                            REMOTE_REFERENCE.search(value.strip()),
                            f"{name}: {local(key)}={value[:50]}",
                        )

    def test_no_web_fonts_are_referenced(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                self.assertNotIn("@font-face", markup)
                self.assertNotIn("fonts.googleapis", markup)

    def test_every_reference_resolves(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                root = parse(markup)
                declared = {
                    element.get("id")
                    for element in iter_all(root)
                    if element.get("id")
                }
                referenced: set[str] = set()
                for element in iter_all(root):
                    for key, value in element.attrib.items():
                        referenced.update(re.findall(r"url\(#([^)\s]+)\)", value))
                        if local(key) == "href" and value.startswith("#"):
                            referenced.add(value[1:])
                self.assertFalse(referenced - declared, f"{name}: dangling refs")

    def test_no_duplicate_ids(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                ids = [
                    element.get("id")
                    for element in iter_all(parse(markup))
                    if element.get("id")
                ]
                self.assertEqual(len(ids), len(set(ids)), f"{name} has duplicate ids")

    def test_every_animation_loops_indefinitely(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                for element in iter_all(parse(markup)):
                    if local(element.tag) in ("animate", "animateTransform"):
                        self.assertEqual(
                            element.get("repeatCount"),
                            "indefinite",
                            f"{name}: a non-looping animation would freeze the card",
                        )

    def test_documents_declare_a_viewbox(self) -> None:
        for name, markup in self.markup.items():
            with self.subTest(asset=name):
                self.assertIsNotNone(parse(markup).get("viewBox"))

    def test_builds_are_reproducible(self) -> None:
        data = snapshot()
        first = ContributionGenerator(CONFIG, data.calendar).render()
        second = ContributionGenerator(CONFIG, data.calendar).render()
        self.assertEqual(first, second)


class ContributionGeneratorTests(unittest.TestCase):
    """Calendar-specific structure and motion."""

    def setUp(self) -> None:
        self.calendar = synthesize_calendar("octocat", end_day=date(2026, 7, 25))
        self.generator = ContributionGenerator(CONFIG, self.calendar)
        self.root = parse(self.generator.render())

    def test_one_group_per_populated_day(self) -> None:
        glints = [
            element
            for element in iter_all(self.root)
            if local(element.tag) == "use"
            and element.get("href", "").endswith("cell-glint")
        ]
        self.assertEqual(len(glints), len(self.calendar.days))

    def test_squares_are_instanced_not_inlined(self) -> None:
        # Five level definitions plus the specular overlay; the 371 cells that
        # reference them must not carry their own geometry.
        definitions = {
            element.get("id")
            for element in iter_all(self.root)
            if local(element.tag) == "rect" and element.get("id")
        }
        self.assertTrue({"cell-lv0", "cell-glint"} <= definitions)

    def test_the_wave_sweeps_from_bottom_left_to_top_right(self) -> None:
        bottom_left = self.generator._cell_delay(0, CONFIG.contribution.rows - 1)
        top_right = self.generator._cell_delay(
            CONFIG.contribution.columns - 1, 0
        )
        middle = self.generator._cell_delay(26, 3)
        self.assertLess(bottom_left, middle)
        self.assertLess(middle, top_right)

    def test_cell_delays_are_stable_across_calls(self) -> None:
        self.assertEqual(
            self.generator._cell_delay(17, 4), self.generator._cell_delay(17, 4)
        )

    def test_glint_lasts_about_one_hundred_and_twenty_milliseconds(self) -> None:
        duration = CONFIG.animation.glint_duration_ms
        loop = self.generator._loop_duration_ms
        glint = next(
            element
            for element in iter_all(self.root)
            if local(element.tag) == "use"
            and element.get("href", "").endswith("cell-glint")
        )
        animation = glint[0]
        times = [float(part) for part in animation.get("keyTimes").split(";")]
        peak_to_rest = (times[3] - times[1]) * loop
        self.assertAlmostEqual(peak_to_rest, duration, delta=1.0)

    def test_every_keyframe_fits_inside_the_loop(self) -> None:
        for element in iter_all(self.root):
            if local(element.tag) in ("animate", "animateTransform"):
                times = element.get("keyTimes")
                if times:
                    parsed = [float(part) for part in times.split(";")]
                    self.assertLessEqual(parsed[-1], 1.0)
                    self.assertGreaterEqual(parsed[0], 0.0)

    def test_glow_falls_back_to_halos_over_the_filter_budget(self) -> None:
        dense = synthesize_calendar("busy-person", end_day=date(2026, 7, 25))
        for column in dense.columns:
            for index, day in enumerate(column):
                if day is not None:
                    column[index] = type(day)(day=day.day, count=99, level=4)
        generator = ContributionGenerator(CONFIG, dense)
        self.assertFalse(generator._use_glow_filters)
        self.assertNotIn("filter-glow", generator.render())


class TerminalGeneratorTests(unittest.TestCase):
    """ASCII portrait layout and the typing sequence."""

    def setUp(self) -> None:
        self.portrait = portrait()
        self.generator = TerminalGenerator(CONFIG, self.portrait, username="octocat")
        self.markup = self.generator.render()
        self.root = parse(self.markup)

    def test_the_character_grid_fills_the_content_width(self) -> None:
        expected = CONFIG.terminal.width - CONFIG.terminal.padding * 2
        self.assertAlmostEqual(self.generator.layout.ascii_width_px, expected, places=6)

    def test_one_clip_path_per_portrait_row(self) -> None:
        clips = [
            element
            for element in iter_all(self.root)
            if local(element.tag) == "clipPath"
            and (element.get("id") or "").startswith("clip-ascii-row-")
        ]
        self.assertEqual(len(clips), self.portrait.height)

    def test_the_portrait_is_roughly_square(self) -> None:
        ratio = self.generator.layout.ascii_height_px / self.generator.layout.ascii_width_px
        self.assertTrue(0.9 < ratio < 1.1, f"aspect ratio drifted to {ratio:.2f}")

    def test_the_prompt_sequence_is_ordered(self) -> None:
        self.assertLess(self.generator._portrait_end_ms, self.generator._command_start_ms)
        self.assertLess(self.generator._command_end_ms, self.generator._output_start_ms)
        self.assertLess(self.generator._output_end_ms, self.generator._prompt_return_ms)
        self.assertLess(self.generator._prompt_return_ms, self.generator._loop_duration_ms)

    def test_the_username_is_printed_as_command_output(self) -> None:
        self.assertIn(">octocat<", self.markup)

    def test_rows_preserve_significant_whitespace(self) -> None:
        self.assertIn('xml:space="preserve"', self.markup)

    def test_rows_pin_their_advance_width(self) -> None:
        texts = [
            element
            for element in iter_all(self.root)
            if local(element.tag) == "text" and element.get("textLength")
        ]
        self.assertGreaterEqual(len(texts), self.portrait.height)


class InfoGeneratorTests(unittest.TestCase):
    """Content model, colour roles and the printing stagger."""

    def setUp(self) -> None:
        self.tokens = build_token_map(snapshot(), tagline=CONFIG.tagline)
        self.content = InfoContent.fallback(self.tokens)
        self.generator = InfoGenerator(CONFIG, self.content)
        self.markup = self.generator.render()

    def test_every_line_gets_its_own_stagger(self) -> None:
        delays = [
            self.generator._line_delay(index)
            for index in range(self.content.total_lines)
        ]
        self.assertEqual(delays, sorted(delays))
        self.assertAlmostEqual(delays[1] - delays[0], CONFIG.info.row_stagger_ms)

    def test_colour_roles_are_all_present(self) -> None:
        for role in (
            CONFIG.info.header_color,
            CONFIG.info.bullet_color,
            CONFIG.info.value_color,
            CONFIG.info.label_color,
        ):
            self.assertIn(role, self.markup)

    def test_height_matching_stretches_the_card(self) -> None:
        stretched = InfoGenerator(CONFIG, self.content, min_height=900.0)
        self.assertAlmostEqual(stretched.layout.height, 900.0)

    def test_section_gaps_stay_bounded_when_stretched(self) -> None:
        stretched = InfoGenerator(CONFIG, self.content, min_height=1600.0)
        self.assertLessEqual(stretched.layout.section_gap, CONFIG.info.max_section_gap)

    def test_tokens_are_substituted(self) -> None:
        self.assertNotIn("{login}", self.markup)
        self.assertNotIn("{contributions}", self.markup)


class ContentTests(unittest.TestCase):
    """The JSON content model must be forgiving of author mistakes."""

    def test_rows_parse_into_typed_kinds(self) -> None:
        content = InfoContent.from_mapping(
            {
                "sections": [
                    {
                        "title": "A",
                        "rows": [
                            {"type": "kv", "label": "l", "value": "v"},
                            {"type": "bullet", "value": "b"},
                            {"type": "rule"},
                        ],
                    }
                ]
            },
            {},
        )
        kinds = [row.kind for row in content.sections[0].rows]
        self.assertEqual(kinds, [RowKind.KEY_VALUE, RowKind.BULLET, RowKind.RULE])

    def test_unknown_row_types_degrade_to_text(self) -> None:
        content = InfoContent.from_mapping(
            {"sections": [{"title": "A", "rows": [{"type": "nope", "value": "x"}]}]}, {}
        )
        self.assertEqual(content.sections[0].rows[0].kind, RowKind.TEXT)

    def test_empty_content_falls_back(self) -> None:
        content = InfoContent.from_mapping({"sections": []}, {"login": "x"})
        self.assertGreater(len(content.sections), 0)

    def test_unknown_tokens_are_left_alone(self) -> None:
        content = InfoContent.from_mapping(
            {"sections": [{"title": "A", "rows": [{"type": "text", "value": "{nope}"}]}]},
            {"login": "x"},
        )
        self.assertEqual(content.sections[0].rows[0].value, "{nope}")

    def test_line_index_is_monotonic_across_sections(self) -> None:
        content = InfoContent.fallback({})
        indices = [index for index, _, _ in content.iter_rows()]
        self.assertEqual(indices, list(range(content.total_lines)))


class AsciiTests(unittest.TestCase):
    """Portrait conversion must be deterministic and correctly proportioned."""

    def test_conversion_is_deterministic(self) -> None:
        self.assertEqual(portrait().rows, portrait().rows)

    def test_every_row_is_exactly_the_configured_width(self) -> None:
        art = portrait()
        self.assertTrue(all(len(row) == art.width for row in art.rows))

    def test_row_shading_stays_within_bounds(self) -> None:
        art = portrait()
        for index in range(art.height):
            shade = art.shade_of(index, floor=0.6)
            self.assertTrue(0.6 <= shade <= 1.0)

    def test_a_missing_avatar_produces_the_placeholder(self) -> None:
        self.assertEqual(portrait().source, "placeholder")

    def test_narrow_widths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AvatarAsciiConverter(width=4, cell_aspect=0.5)


class ColorTests(unittest.TestCase):
    """Colour maths backs every derived tint in the design system."""

    def test_hex_shorthand_expands(self) -> None:
        self.assertEqual(parse_color("#abc")[0], (170.0, 187.0, 204.0))

    def test_rgba_alpha_is_read(self) -> None:
        self.assertAlmostEqual(parse_color("rgba(255,255,255,0.08)")[1], 0.08)

    def test_alpha_composes_multiplicatively(self) -> None:
        self.assertEqual(with_alpha("rgba(0,0,0,0.5)", 0.5), "rgba(0,0,0,0.25)")

    def test_mix_interpolates_linearly(self) -> None:
        self.assertEqual(mix("#000000", "#ffffff", 0.5), "#808080")

    def test_lighten_moves_toward_white(self) -> None:
        self.assertGreater(
            relative_luminance(lighten("#3fb950", 0.4)),
            relative_luminance("#3fb950"),
        )

    def test_unsupported_colours_raise(self) -> None:
        with self.assertRaises(ValueError):
            parse_color("chartreuse")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

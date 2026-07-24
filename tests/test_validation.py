"""Tests for the SVG and SMIL validator.

The validator is the build's last line of defence, so it needs its own tests:
a check that never fires is indistinguishable from a check that passes.
"""

from __future__ import annotations

import unittest

from generator.validation import validate_markup

HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
)


def document(body: str, *, view_box: bool = True) -> str:
    """Wrap a fragment in a minimal SVG root."""
    header = HEADER if view_box else HEADER.replace(' viewBox="0 0 10 10"', "")
    return f"{header}{body}</svg>"


class WellFormednessTests(unittest.TestCase):
    def test_valid_document_passes(self) -> None:
        report = validate_markup(document("<rect/>"), "t.svg")
        self.assertTrue(report.ok, report.errors)

    def test_malformed_xml_fails(self) -> None:
        report = validate_markup("<svg><rect></svg>", "t.svg")
        self.assertFalse(report.ok)

    def test_wrong_root_fails(self) -> None:
        report = validate_markup('<html xmlns="http://www.w3.org/2000/svg"/>', "t.svg")
        self.assertFalse(report.ok)

    def test_missing_viewbox_fails(self) -> None:
        report = validate_markup(document("<rect/>", view_box=False), "t.svg")
        self.assertFalse(report.ok)


class StandaloneGuaranteeTests(unittest.TestCase):
    def test_script_is_rejected(self) -> None:
        report = validate_markup(document("<script>1</script>"), "t.svg")
        self.assertFalse(report.ok)

    def test_style_is_rejected(self) -> None:
        report = validate_markup(document("<style>a{}</style>"), "t.svg")
        self.assertFalse(report.ok)

    def test_remote_reference_is_rejected(self) -> None:
        report = validate_markup(
            document('<use xlink:href="https://example.com/a.svg#b"/>'), "t.svg"
        )
        self.assertFalse(report.ok)

    def test_data_uri_is_rejected(self) -> None:
        report = validate_markup(
            document('<rect fill="data:image/png;base64,AA"/>'), "t.svg"
        )
        self.assertFalse(report.ok)


class ReferenceTests(unittest.TestCase):
    def test_dangling_url_reference_is_caught(self) -> None:
        report = validate_markup(document('<rect fill="url(#nope)"/>'), "t.svg")
        self.assertFalse(report.ok)
        self.assertIn("dangling reference to #nope", report.errors[0])

    def test_resolved_reference_passes(self) -> None:
        markup = document(
            '<defs><linearGradient id="g"/></defs><rect fill="url(#g)"/>'
        )
        self.assertTrue(validate_markup(markup, "t.svg").ok)

    def test_duplicate_ids_are_caught(self) -> None:
        report = validate_markup(document('<rect id="a"/><rect id="a"/>'), "t.svg")
        self.assertFalse(report.ok)


class AnimationTests(unittest.TestCase):
    def animation(self, attributes: str) -> str:
        return document(f"<rect><animate {attributes}/></rect>")

    def test_mismatched_key_times_are_caught(self) -> None:
        report = validate_markup(
            self.animation(
                'attributeName="opacity" values="0;1;0" keyTimes="0;1" dur="1s"'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_non_increasing_key_times_are_caught(self) -> None:
        report = validate_markup(
            self.animation(
                'attributeName="opacity" values="0;1;0" keyTimes="0;0.5;0.5" dur="1s"'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_key_times_must_start_at_zero(self) -> None:
        report = validate_markup(
            self.animation(
                'attributeName="opacity" values="0;1" keyTimes="0.2;1" dur="1s"'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_missing_duration_is_caught(self) -> None:
        report = validate_markup(
            self.animation('attributeName="opacity" values="0;1" keyTimes="0;1"'),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_spline_count_must_match_segments(self) -> None:
        report = validate_markup(
            self.animation(
                'attributeName="opacity" values="0;1;0" keyTimes="0;0.5;1" '
                'dur="1s" calcMode="spline" keySplines="0 0 1 1"'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_omitted_key_times_are_allowed(self) -> None:
        # SMIL distributes values evenly when keyTimes is absent.
        report = validate_markup(
            self.animation('attributeName="opacity" values="0;1;0" dur="1s"'), "t.svg"
        )
        self.assertTrue(report.ok, report.errors)

    def test_transform_via_plain_animate_is_caught(self) -> None:
        # Invalid SMIL that renderers drop without any diagnostic.
        report = validate_markup(
            self.animation(
                'attributeName="transform" values="0 0;1 1" keyTimes="0;1" dur="1s"'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_animate_transform_needs_a_type(self) -> None:
        report = validate_markup(
            document(
                '<g><animateTransform attributeName="transform" values="0;1" '
                'keyTimes="0;1" dur="1s"/></g>'
            ),
            "t.svg",
        )
        self.assertFalse(report.ok)

    def test_animations_are_counted(self) -> None:
        report = validate_markup(
            document(
                '<rect><animate attributeName="opacity" values="0;1" '
                'keyTimes="0;1" dur="1s"/></rect>'
            ),
            "t.svg",
        )
        self.assertEqual(report.animation_count, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

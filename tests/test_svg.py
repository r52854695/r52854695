"""Tests for the SVG document model."""

from __future__ import annotations

import unittest

from generator.svg import Element, SvgDocument, escape_text, format_number


class FormatNumberTests(unittest.TestCase):
    """Number formatting must be compact but never lossy on screen."""

    def test_integers_lose_their_decimal_point(self) -> None:
        self.assertEqual(format_number(12.0), "12")

    def test_negative_zero_normalises(self) -> None:
        self.assertEqual(format_number(-0.0), "0")

    def test_trailing_zeros_are_stripped(self) -> None:
        self.assertEqual(format_number(0.5000001), "0.5")

    def test_precision_is_respected(self) -> None:
        self.assertEqual(format_number(1.23456, 2), "1.23")


class EscapingTests(unittest.TestCase):
    """Text and attribute values must be escaped exactly once."""

    def test_text_escapes_markup_characters(self) -> None:
        self.assertEqual(escape_text("a<b>&c"), "a&lt;b&gt;&amp;c")

    def test_ampersand_is_escaped_before_angle_brackets(self) -> None:
        # Escaping in the wrong order would produce "&amp;lt;".
        self.assertEqual(escape_text("&<"), "&amp;&lt;")

    def test_attribute_quotes_are_escaped(self) -> None:
        element = Element("text", font_family='a "b" c')
        self.assertIn('font-family="a &quot;b&quot; c"', element.to_string())

    def test_ascii_ramp_characters_survive_a_round_trip(self) -> None:
        # The ASCII portrait ramp contains <, > and & — the exact characters
        # that would corrupt the document if escaping were missed.
        ramp = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
        markup = Element("text", ramp).to_string()
        self.assertNotIn("<>", markup.replace("<text>", "").replace("</text>", ""))
        self.assertIn("&lt;", markup)
        self.assertIn("&amp;", markup)


class AttributeNamingTests(unittest.TestCase):
    """Python keyword arguments must map onto real SVG attribute names."""

    def test_underscores_become_hyphens(self) -> None:
        element = Element("rect", stroke_width=2)
        self.assertIn('stroke-width="2"', element.to_string())

    def test_trailing_underscore_is_stripped(self) -> None:
        element = Element("rect", class_="cell")
        self.assertIn('class="cell"', element.to_string())

    def test_double_underscore_becomes_a_namespace_colon(self) -> None:
        element = Element("use", xlink__href="#a")
        self.assertIn('xlink:href="#a"', element.to_string())

    def test_camel_case_attributes_pass_through(self) -> None:
        element = Element("animate", attributeName="opacity", keyTimes="0;1")
        markup = element.to_string()
        self.assertIn('attributeName="opacity"', markup)
        self.assertIn('keyTimes="0;1"', markup)

    def test_none_values_are_dropped(self) -> None:
        element = Element("rect", fill=None, stroke="#fff")
        self.assertNotIn("fill", element.to_string())


class DefinitionRegistryTests(unittest.TestCase):
    """``define`` is what keeps ``<defs>`` free of duplicates."""

    def test_a_definition_is_created_once(self) -> None:
        document = SvgDocument(10, 10)
        calls = 0

        def factory() -> Element:
            nonlocal calls
            calls += 1
            return Element("linearGradient")

        first = document.define("grad", factory)
        second = document.define("grad", factory)

        self.assertEqual(first, second)
        self.assertEqual(calls, 1)
        self.assertEqual(len(document.defs.children), 1)

    def test_the_id_is_applied_to_the_definition(self) -> None:
        document = SvgDocument(10, 10)
        document.define("grad", lambda: Element("linearGradient"))
        self.assertEqual(document.defs.children[0].attributes["id"], "grad")

    def test_url_helper_formats_a_paint_reference(self) -> None:
        self.assertEqual(SvgDocument.url("grad"), "url(#grad)")


class SerialisationTests(unittest.TestCase):
    """Output shape matters: it is what the size budget is measured against."""

    def test_text_elements_are_never_self_closed(self) -> None:
        self.assertEqual(Element("text").to_string(newlines=False), "<text></text>")

    def test_empty_shapes_self_close(self) -> None:
        self.assertEqual(Element("rect").to_string(newlines=False), "<rect/>")

    def test_indentation_can_be_disabled_while_keeping_newlines(self) -> None:
        parent = Element("g")
        parent.child("rect")
        markup = parent.to_string(indent="", newlines=True)
        self.assertEqual(markup, "<g>\n<rect/>\n</g>\n")

    def test_document_declares_both_namespaces(self) -> None:
        markup = SvgDocument(100, 50, title="t").render()
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', markup)
        self.assertIn('xmlns:xlink="http://www.w3.org/1999/xlink"', markup)
        self.assertIn('viewBox="0 0 100 50"', markup)
        self.assertIn("<title>t</title>", markup)

    def test_walk_visits_every_node(self) -> None:
        root = Element("g")
        root.child("rect")
        root.child("g").child("circle")
        self.assertEqual(len(list(root.walk())), 4)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

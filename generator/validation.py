"""Static validation of generated SVG assets.

A malformed SMIL animation does not raise, log, or crash: the renderer simply
drops it, and the asset silently loses a layer of motion that nobody notices
until it has been on a profile page for a week.  The same is true of a dangling
``url(#id)`` reference or a duplicated id.

This module encodes the invariants the SVG and SMIL specifications impose so
that a regression fails the build instead of quietly degrading it.  It runs as
part of ``python build.py`` and standalone via ``python tools/validate.py``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

__all__ = ["ValidationReport", "validate_markup", "validate_file", "SVG_NAMESPACE"]

SVG_NAMESPACE = "http://www.w3.org/2000/svg"

#: Elements that would break the standalone guarantee: scripting, external
#: styling, embedded HTML, or a raster that must be fetched separately.
_FORBIDDEN_TAGS = frozenset(
    {"script", "style", "foreignObject", "image", "audio", "video", "iframe"}
)
_ANIMATION_TAGS = frozenset({"animate", "animateTransform", "animateMotion", "set"})

_URL_REFERENCE = re.compile(r"url\(#([^)\s]+)\)")
_FRAGMENT = re.compile(r"^#(.+)$")
_REMOTE = re.compile(r"(?:https?:)?//|^data:", re.IGNORECASE)

#: Tolerance for floating point comparisons on keyTimes.
_EPSILON = 1e-6
#: Cap on how many findings a single report keeps, to bound console noise.
_MAX_ERRORS = 40


@dataclass
class ValidationReport:
    """Findings for one asset."""

    name: str
    errors: list[str] = field(default_factory=list)
    element_count: int = 0
    animation_count: int = 0
    definition_count: int = 0

    @property
    def ok(self) -> bool:
        """Whether the asset passed every check."""
        return not self.errors

    def fail(self, message: str) -> None:
        """Record a failure, keeping the list bounded."""
        if len(self.errors) < _MAX_ERRORS:
            self.errors.append(message)
        elif len(self.errors) == _MAX_ERRORS:
            self.errors.append("… further errors suppressed")

    def format_summary(self) -> str:
        """One aligned console row."""
        status = "ok  " if self.ok else "FAIL"
        return (
            f"  {status} {self.name:<38} "
            f"{self.element_count:>5} nodes  "
            f"{self.animation_count:>5} animations  "
            f"{self.definition_count:>3} defs"
        )

    def format_details(self, indent: str = "         ") -> str:
        """The failure list, one per line."""
        return "\n".join(f"{indent}- {message}" for message in self.errors)


def _local_name(tag: str) -> str:
    """Strip the XML namespace from a tag or attribute name."""
    return tag.rsplit("}", 1)[-1]


def _iter_elements(root: ElementTree.Element) -> Iterator[ElementTree.Element]:
    """Yield the root and every descendant, depth first."""
    yield root
    for child in root:
        yield from _iter_elements(child)


def _check_animation(element: ElementTree.Element, report: ValidationReport) -> None:
    """Assert the SMIL length and ordering invariants for one animation."""
    tag = _local_name(element.tag)
    label = f"<{tag} {element.get('attributeName', '?')}>"
    values = element.get("values")
    key_times = element.get("keyTimes")
    key_splines = element.get("keySplines")
    calc_mode = element.get("calcMode", "linear")

    if element.get("dur") is None:
        report.fail(f"{label}: missing dur")
    if tag == "animateTransform" and element.get("type") is None:
        report.fail(f"{label}: animateTransform without type")
    if tag == "animate" and element.get("attributeName") == "transform":
        report.fail(f"{label}: transform must be animated with <animateTransform>")

    if values is None:
        return
    value_count = len(values.split(";"))
    spline_count = len([part for part in (key_splines or "").split(";") if part.strip()])

    if calc_mode == "spline" and spline_count != value_count - 1:
        report.fail(
            f"{label}: {value_count} values need {value_count - 1} keySplines, "
            f"got {spline_count}"
        )
    if calc_mode != "spline" and key_splines is not None:
        report.fail(f"{label}: keySplines given but calcMode={calc_mode}")

    if key_times is None:
        # Valid: SMIL then distributes the values evenly across the duration.
        return

    try:
        times = [float(part) for part in key_times.split(";") if part.strip()]
    except ValueError:
        report.fail(f"{label}: keyTimes is not numeric")
        return

    if len(times) != value_count:
        report.fail(f"{label}: {value_count} values but {len(times)} keyTimes")
        return
    if abs(times[0]) > _EPSILON:
        report.fail(f"{label}: keyTimes must start at 0, got {times[0]}")
    if times[-1] > 1.0 + _EPSILON:
        report.fail(f"{label}: keyTimes must not exceed 1, got {times[-1]}")

    strict = calc_mode in ("linear", "spline")
    for index in range(1, len(times)):
        previous, current = times[index - 1], times[index]
        if current < previous - _EPSILON or (strict and current <= previous):
            report.fail(
                f"{label}: keyTimes must {'strictly ' if strict else ''}increase "
                f"(index {index}: {previous} -> {current})"
            )
            break


def _iter_references(element: ElementTree.Element) -> Iterator[str]:
    """Yield every internal id the element references."""
    for name, value in element.attrib.items():
        for match in _URL_REFERENCE.finditer(value):
            yield match.group(1)
        if _local_name(name) == "href":
            fragment = _FRAGMENT.match(value.strip())
            if fragment:
                yield fragment.group(1)


def validate_markup(markup: str, name: str) -> ValidationReport:
    """Validate a rendered SVG document.

    Args:
        markup: The complete SVG text.
        name: Label used in the report.

    Returns:
        A :class:`ValidationReport`; check :attr:`ValidationReport.ok`.
    """
    report = ValidationReport(name=name)

    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError as error:
        report.fail(f"not well-formed XML: {error}")
        return report

    if _local_name(root.tag) != "svg":
        report.fail(f"root element is <{_local_name(root.tag)}>, expected <svg>")
        return report
    if not root.tag.startswith(f"{{{SVG_NAMESPACE}}}"):
        report.fail("root element is not in the SVG namespace")
    if root.get("viewBox") is None:
        report.fail("root element has no viewBox, so the asset cannot scale")

    declared: set[str] = set()
    duplicated: set[str] = set()
    referenced: set[str] = set()

    for element in _iter_elements(root):
        report.element_count += 1
        tag = _local_name(element.tag)

        if tag in _FORBIDDEN_TAGS:
            report.fail(f"forbidden element <{tag}>: assets must be standalone")

        element_id = element.get("id")
        if element_id is not None:
            if element_id in declared:
                duplicated.add(element_id)
            declared.add(element_id)

        if tag in _ANIMATION_TAGS:
            report.animation_count += 1
            _check_animation(element, report)

        referenced.update(_iter_references(element))

        for attribute, value in element.attrib.items():
            if _REMOTE.search(value.strip()):
                report.fail(
                    f"<{tag}> {_local_name(attribute)} references external "
                    f"content: {value[:60]}"
                )

    defs = root.find(f"{{{SVG_NAMESPACE}}}defs")
    report.definition_count = len(list(defs)) if defs is not None else 0

    for element_id in sorted(duplicated):
        report.fail(f"duplicate id {element_id!r}")
    for element_id in sorted(referenced - declared):
        report.fail(f"dangling reference to #{element_id}")

    return report


def validate_file(path: Path) -> ValidationReport:
    """Validate an SVG asset on disk."""
    try:
        markup = path.read_text(encoding="utf-8")
    except OSError as error:
        report = ValidationReport(name=path.name)
        report.fail(f"could not be read: {error}")
        return report
    return validate_markup(markup, path.name)

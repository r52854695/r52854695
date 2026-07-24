"""A tiny, dependency-free SVG document object model.

The generators never concatenate markup by hand.  They build a tree of
:class:`Element` nodes and let :class:`SvgDocument` serialise it, which gives
us three things for free:

* **Correctness** — text and attribute values are XML-escaped exactly once.
* **Compactness** — numbers are emitted at the minimum precision that still
  looks pixel-perfect, which meaningfully shrinks calendars with 371 cells.
* **Reuse** — :meth:`SvgDocument.define` memoises ``<defs>`` children by id, so
  a gradient or filter requested by fifty call sites is emitted exactly once.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator, Mapping

__all__ = ["Element", "SvgDocument", "escape_text", "format_number"]

#: Coordinates are rounded to this many decimals.  Sub-hundredth-of-a-pixel
#: precision is invisible and costs bytes.
_COORD_PRECISION = 3

#: Elements that must never be self-closed even when empty, because some
#: renderers treat ``<text/>`` and friends inconsistently.
_NEVER_SELF_CLOSING = frozenset({"text", "tspan", "textPath", "style", "title", "desc"})

_XML_TEXT_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))
_XML_ATTR_ESCAPES = _XML_TEXT_ESCAPES + (('"', "&quot;"),)


def escape_text(value: str) -> str:
    """Escape ``value`` for use as XML character data."""
    for raw, encoded in _XML_TEXT_ESCAPES:
        value = value.replace(raw, encoded)
    return value


def _escape_attribute(value: str) -> str:
    """Escape ``value`` for use inside a double-quoted XML attribute."""
    for raw, encoded in _XML_ATTR_ESCAPES:
        value = value.replace(raw, encoded)
    return value


def format_number(value: float, precision: int = _COORD_PRECISION) -> str:
    """Render ``value`` as the shortest string that round-trips visually.

    ``12.0`` becomes ``"12"``, ``0.5000001`` becomes ``"0.5"`` and ``-0.0``
    becomes ``"0"`` so that diffing two builds stays readable.
    """
    if value == 0:  # also catches -0.0
        return "0"
    rounded = round(float(value), precision)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{precision}f}".rstrip("0").rstrip(".")


def _format_value(value: Any) -> str:
    """Coerce any attribute value into its SVG string form."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format_number(float(value))
    if isinstance(value, (list, tuple)):
        return " ".join(_format_value(item) for item in value)
    return str(value)


def _normalise_attribute_name(name: str) -> str:
    """Map a Python keyword argument onto its SVG attribute name.

    ``class_`` -> ``class``, ``stroke_width`` -> ``stroke-width``,
    ``xlink__href`` -> ``xlink:href``.  camelCase SVG attributes such as
    ``attributeName`` or ``stdDeviation`` contain no underscore and therefore
    pass through the substitutions below untouched.
    """
    name = name.rstrip("_")
    if "__" in name:
        return name.replace("__", ":", 1).replace("_", "-")
    return name.replace("_", "-")
class Element:
    """A single SVG node: a tag, ordered attributes, children and text."""

    __slots__ = ("tag", "attributes", "children", "text")

    def __init__(self, tag: str, text: str | None = None, **attributes: Any) -> None:
        self.tag = tag
        self.text = text
        self.attributes: dict[str, str] = {}
        self.children: list[Element] = []
        self.set(**attributes)

    # -- construction -------------------------------------------------------

    def set(self, **attributes: Any) -> "Element":
        """Set attributes, skipping any whose value is ``None``.  Chainable."""
        for key, value in attributes.items():
            if value is None:
                continue
            self.attributes[_normalise_attribute_name(key)] = _format_value(value)
        return self

    def set_raw(self, mapping: Mapping[str, Any]) -> "Element":
        """Set attributes from a mapping whose keys are already SVG-spelled."""
        for key, value in mapping.items():
            if value is None:
                continue
            self.attributes[key] = _format_value(value)
        return self

    def add(self, *children: "Element | None") -> "Element":
        """Append children, ignoring ``None``.  Returns *self* for chaining."""
        for child in children:
            if child is not None:
                self.children.append(child)
        return self

    def extend(self, children: Iterable["Element | None"]) -> "Element":
        """Append an iterable of children.  Returns *self*."""
        return self.add(*children)

    def child(self, tag: str, text: str | None = None, **attributes: Any) -> "Element":
        """Create a child element, append it, and return the **child**."""
        element = Element(tag, text, **attributes)
        self.children.append(element)
        return element

    def group(self, **attributes: Any) -> "Element":
        """Shorthand for ``child("g", ...)``."""
        return self.child("g", **attributes)

    # -- serialisation ------------------------------------------------------

    def _attribute_string(self) -> str:
        if not self.attributes:
            return ""
        return "".join(
            f' {name}="{_escape_attribute(value)}"'
            for name, value in self.attributes.items()
        )

    def _serialise(
        self, depth: int, indent: str, newline: str, out: list[str]
    ) -> None:
        pad = indent * depth if indent else ""
        attributes = self._attribute_string()

        if not self.children and self.text is None and self.tag not in _NEVER_SELF_CLOSING:
            out.append(f"{pad}<{self.tag}{attributes}/>{newline}")
            return

        # Text-only nodes stay on one line so that xml:space="preserve" cannot
        # pick up the indentation as meaningful whitespace.
        if not self.children:
            body = escape_text(self.text or "")
            out.append(f"{pad}<{self.tag}{attributes}>{body}</{self.tag}>{newline}")
            return

        out.append(f"{pad}<{self.tag}{attributes}>{newline}")
        if self.text:
            out.append(f"{pad}{indent}{escape_text(self.text)}{newline}")
        for child in self.children:
            child._serialise(depth + 1, indent, newline, out)
        out.append(f"{pad}</{self.tag}>{newline}")

    def to_string(
        self, *, indent: str = "", depth: int = 0, newlines: bool = True
    ) -> str:
        """Serialise this subtree to XML.

        Args:
            indent: Per-level indentation string; empty disables indentation.
            depth: Starting depth, used when embedding a subtree.
            newlines: Emit one element per line.  Keeping newlines while
                dropping indentation is the sweet spot for generated assets:
                the file stays diffable in git without paying for leading
                whitespace on every one of several thousand nodes.
        """
        out: list[str] = []
        self._serialise(depth, indent, "\n" if newlines else "", out)
        return "".join(out)

    def walk(self) -> Iterator["Element"]:
        """Depth-first iteration over this element and all descendants."""
        yield self
        for child in self.children:
            yield from child.walk()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Element {self.tag} {len(self.children)} children>"


class SvgDocument(Element):
    """Root ``<svg>`` element with a memoising ``<defs>`` section."""

    XMLNS = "http://www.w3.org/2000/svg"
    XMLNS_XLINK = "http://www.w3.org/1999/xlink"

    __slots__ = ("_defs", "_defined_ids")

    def __init__(
        self,
        width: float,
        height: float,
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__("svg")
        self.set_raw(
            {
                "xmlns": self.XMLNS,
                "xmlns:xlink": self.XMLNS_XLINK,
                "viewBox": f"0 0 {format_number(width)} {format_number(height)}",
                "width": format_number(width),
                "height": format_number(height),
                "role": "img",
                "preserveAspectRatio": "xMidYMid meet",
            }
        )
        if title:
            self.add(Element("title", title))
        if description:
            self.add(Element("desc", description))

        self._defs = Element("defs")
        self._defined_ids: set[str] = set()
        self.add(self._defs)

    # -- definition registry ------------------------------------------------

    @property
    def defs(self) -> Element:
        """The document's single ``<defs>`` node."""
        return self._defs

    def has_definition(self, element_id: str) -> bool:
        """Return whether ``element_id`` has already been registered."""
        return element_id in self._defined_ids

    def define(self, element_id: str, factory: Callable[[], Element]) -> str:
        """Register a reusable definition exactly once and return its id.

        ``factory`` is only invoked on the first request for ``element_id``,
        which is what keeps gradients and filters from being duplicated across
        hundreds of call sites.
        """
        if element_id not in self._defined_ids:
            element = factory()
            element.set(id=element_id)
            self._defs.add(element)
            self._defined_ids.add(element_id)
        return element_id

    @staticmethod
    def url(element_id: str) -> str:
        """Return the ``url(#id)`` paint reference for ``element_id``."""
        return f"url(#{element_id})"

    # -- output -------------------------------------------------------------

    def render(
        self,
        *,
        indent: str = "",
        newlines: bool = True,
        xml_declaration: bool = True,
    ) -> str:
        """Serialise the document to a complete, standalone SVG string.

        Args:
            indent: Per-level indentation; empty by default because a
                contribution calendar carries several thousand nodes and the
                leading whitespace alone would cost tens of kilobytes.
            newlines: Keep one element per line so builds stay diffable.
            xml_declaration: Emit the XML prologue.
        """
        prologue = '<?xml version="1.0" encoding="UTF-8"?>\n' if xml_declaration else ""
        return prologue + self.to_string(indent=indent, newlines=newlines)

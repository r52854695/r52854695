"""The shared paint and filter library.

Every gradient, filter, mask and pattern used anywhere in the project is
declared here and registered through :meth:`generator.svg.SvgDocument.define`,
which guarantees that a definition requested by one call site or by four
hundred is emitted into ``<defs>`` exactly once.

That single rule is responsible for most of the output-size budget: a
contribution calendar paints 371 cells with the same specular gradient and the
same pair of glow filters, and the file still stays small.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .colors import darken, lighten, mix
from .config_types import ConfigLike
from .svg import Element, SvgDocument
from .timeline import LoopClock

__all__ = ["PaintLibrary", "GradientStop"]


@dataclass(frozen=True)
class GradientStop:
    """One stop of a linear or radial gradient."""

    offset: float
    color: str
    opacity: float = 1.0

    def to_element(self) -> Element:
        """Render this stop as an SVG ``<stop>``."""
        element = Element("stop", offset=f"{self.offset:.4g}", stop_color=self.color)
        if self.opacity != 1.0:
            element.set(stop_opacity=f"{self.opacity:.4g}")
        return element


def _slugify_color(color: str) -> str:
    """Turn an arbitrary colour string into a safe id fragment."""
    return "".join(character for character in color if character.isalnum()).lower()


class PaintLibrary:
    """Creates and memoises the reusable ``<defs>`` content of one document.

    Args:
        document: The document whose ``<defs>`` will receive the definitions.
        config: The active configuration, used for palette and glow tuning.
    """

    def __init__(self, document: SvgDocument, config: ConfigLike) -> None:
        self._document = document
        self._config = config

    @property
    def document(self) -> SvgDocument:
        """The document this library writes definitions into."""
        return self._document

    def register(self, element_id: str, factory: Callable[[], Element]) -> str:
        """Register an arbitrary reusable definition and return its id.

        Escape hatch for definitions that are unique to a single generator —
        an animated per-row clip path, for instance — while still routing them
        through the document's memoising registry.
        """
        return self._document.define(element_id, factory)

    # -- primitives ---------------------------------------------------------

    def linear_gradient(
        self,
        element_id: str,
        stops: Sequence[GradientStop],
        *,
        x1: float = 0.0,
        y1: float = 0.0,
        x2: float = 1.0,
        y2: float = 0.0,
        units: str | None = None,
        spread: str | None = None,
    ) -> str:
        """Define a linear gradient and return its ``url(#id)`` reference."""

        def factory() -> Element:
            gradient = Element("linearGradient", x1=x1, y1=y1, x2=x2, y2=y2)
            gradient.set(gradientUnits=units, spreadMethod=spread)
            gradient.extend(stop.to_element() for stop in stops)
            return gradient

        return SvgDocument.url(self._document.define(element_id, factory))

    def radial_gradient(
        self,
        element_id: str,
        stops: Sequence[GradientStop],
        *,
        cx: float = 0.5,
        cy: float = 0.5,
        r: float = 0.5,
        fx: float | None = None,
        fy: float | None = None,
        units: str | None = None,
    ) -> str:
        """Define a radial gradient and return its ``url(#id)`` reference."""

        def factory() -> Element:
            gradient = Element("radialGradient", cx=cx, cy=cy, r=r, fx=fx, fy=fy)
            gradient.set(gradientUnits=units)
            gradient.extend(stop.to_element() for stop in stops)
            return gradient

        return SvgDocument.url(self._document.define(element_id, factory))

    # -- surfaces -----------------------------------------------------------

    def page_background(self, width: float, height: float) -> str:
        """The deep, softly-lit backdrop shared by every card."""
        palette = self._config.palette
        return self.linear_gradient(
            "grad-page",
            (
                GradientStop(0.0, lighten(palette.background, 0.035)),
                GradientStop(0.55, palette.background),
                GradientStop(1.0, palette.background_deep),
            ),
            x1=0,
            y1=0,
            x2=width * 0.35,
            y2=height,
            units="userSpaceOnUse",
        )

    def card_surface(self, width: float, height: float) -> str:
        """The glassy card fill: lit from the top-left, falling into shadow."""
        palette = self._config.palette
        return self.linear_gradient(
            "grad-card",
            (
                GradientStop(0.0, lighten(palette.surface, 0.06)),
                GradientStop(0.5, palette.surface),
                GradientStop(1.0, darken(palette.surface, 0.28)),
            ),
            x1=0,
            y1=0,
            x2=width * 0.3,
            y2=height,
            units="userSpaceOnUse",
        )

    def titlebar_glass(self, width: float, height: float) -> str:
        """Frosted-glass sheen for a macOS-style title bar."""
        palette = self._config.palette
        return self.linear_gradient(
            "grad-titlebar",
            (
                GradientStop(0.0, lighten(palette.surface_raised, 0.10)),
                GradientStop(0.62, palette.surface_raised),
                GradientStop(1.0, darken(palette.surface_raised, 0.16)),
            ),
            x1=0,
            y1=0,
            x2=0,
            y2=height,
            units="userSpaceOnUse",
        )

    def top_highlight(self, width: float) -> str:
        """The 1px specular hairline that sits on a card's top edge."""
        return self.linear_gradient(
            "grad-top-highlight",
            (
                GradientStop(0.0, "#ffffff", 0.0),
                GradientStop(0.5, "#ffffff", 0.30),
                GradientStop(1.0, "#ffffff", 0.0),
            ),
            x1=0,
            y1=0,
            x2=width,
            y2=0,
            units="userSpaceOnUse",
        )

    def accent_rule(self, width: float) -> str:
        """A cyan -> purple -> green hairline used to separate regions."""
        palette = self._config.palette
        return self.linear_gradient(
            "grad-accent-rule",
            (
                GradientStop(0.0, palette.cyan, 0.0),
                GradientStop(0.22, palette.cyan, 0.75),
                GradientStop(0.55, palette.purple, 0.65),
                GradientStop(0.82, palette.green, 0.55),
                GradientStop(1.0, palette.green, 0.0),
            ),
            x1=0,
            y1=0,
            x2=width,
            y2=0,
            units="userSpaceOnUse",
        )

    def specular_sweep(self) -> str:
        """The white raking highlight used for every glint.

        Deliberately defined in object bounding box units so that one gradient
        serves elements of any size.
        """
        return self.linear_gradient(
            "grad-specular",
            (
                GradientStop(0.0, "#ffffff", 0.0),
                GradientStop(0.34, "#ffffff", 0.55),
                GradientStop(0.5, "#ffffff", 1.0),
                GradientStop(0.66, "#ffffff", 0.55),
                GradientStop(1.0, "#ffffff", 0.0),
            ),
            x1=0.0,
            y1=1.0,
            x2=1.0,
            y2=0.0,
        )

    def halo(self, color: str) -> str:
        """A soft radial halo — the filter-free fallback for cell glow."""
        return self.radial_gradient(
            f"grad-halo-{_slugify_color(color)}",
            (
                GradientStop(0.0, color, 0.55),
                GradientStop(0.45, color, 0.22),
                GradientStop(1.0, color, 0.0),
            ),
        )

    def aurora(self, color: str, *, peak_opacity: float = 0.34) -> str:
        """A very soft coloured blob for ambient background motion."""
        return self.radial_gradient(
            f"grad-aurora-{_slugify_color(color)}",
            (
                GradientStop(0.0, color, peak_opacity),
                GradientStop(0.42, color, peak_opacity * 0.42),
                GradientStop(1.0, color, 0.0),
            ),
        )

    def vignette(self, width: float, height: float) -> str:
        """Darkens the card corners so content reads as lit from the centre."""
        return self.radial_gradient(
            "grad-vignette",
            (
                GradientStop(0.0, "#000000", 0.0),
                GradientStop(0.66, "#000000", 0.0),
                GradientStop(1.0, "#000000", 0.42),
            ),
            cx=width / 2,
            cy=height / 2,
            r=max(width, height) * 0.72,
            units="userSpaceOnUse",
        )

    def text_shimmer(self, width: float, colors: Sequence[str]) -> str:
        """A wide multi-stop gradient for headline text."""
        stops = [
            GradientStop(index / max(len(colors) - 1, 1), color)
            for index, color in enumerate(colors)
        ]
        return self.linear_gradient(
            "grad-text-shimmer",
            stops,
            x1=0,
            y1=0,
            x2=width,
            y2=0,
            units="userSpaceOnUse",
        )

    def ascii_gradient(self, x: float, y: float, width: float, height: float) -> str:
        """The cyan -> green wash applied across the whole ASCII portrait."""
        palette = self._config.palette
        return self.linear_gradient(
            "grad-ascii",
            (
                GradientStop(0.0, palette.cyan),
                GradientStop(0.34, mix(palette.cyan, palette.green, 0.55)),
                GradientStop(0.72, palette.green),
                GradientStop(1.0, mix(palette.green, palette.purple, 0.35)),
            ),
            x1=x,
            y1=y,
            x2=x + width * 0.45,
            y2=y + height,
            units="userSpaceOnUse",
        )

    # -- filters ------------------------------------------------------------

    def glow_filter(
        self,
        color: str,
        *,
        blur: float,
        clock: LoopClock | None = None,
        boost: float = 1.65,
        key: str | None = None,
    ) -> str:
        """Define an additive bloom filter and return its ``url(#id)``.

        The blur radius breathes on its own period so the brightest cells feel
        alive rather than statically lit.  Because the animation lives on the
        *filter primitive*, one animation drives every element that references
        the filter — the whole point of routing glow through ``<defs>``.

        Args:
            color: Only used to key the definition; the bloom is derived from
                the source graphic so it always matches the painted colour.
            blur: Base standard deviation, before the global glow intensity.
            clock: Unused for timing (the breathe runs free) but accepted so
                call sites read consistently.
            boost: Alpha multiplier applied to the blurred copy.
            key: Optional explicit id suffix.

        Returns:
            The ``url(#id)`` filter reference.
        """
        glow = self._config.glow
        radius = blur * glow.intensity
        suffix = key or f"{_slugify_color(color)}-{radius:.2f}".replace(".", "")
        element_id = f"filter-glow-{suffix}"

        def factory() -> Element:
            element = Element(
                "filter",
                x="-140%",
                y="-140%",
                width="380%",
                height="380%",
                filterUnits="objectBoundingBox",
                color_interpolation_filters="sRGB",
            )
            blur_node = element.child(
                "feGaussianBlur",
                in_="SourceGraphic",
                stdDeviation=radius,
                result="bloom",
            )
            blur_node.add(
                LoopClock.free_running(
                    "stdDeviation",
                    (
                        radius * glow.breathe_min,
                        radius * glow.breathe_max,
                        radius * glow.breathe_min,
                    ),
                    period_ms=glow.breathe_period_ms,
                )
            )
            transfer = element.child("feComponentTransfer", in_="bloom", result="bright")
            transfer.child("feFuncA", type="linear", slope=boost, intercept=0)
            merge = element.child("feMerge")
            merge.child("feMergeNode", in_="bright")
            merge.child("feMergeNode", in_="SourceGraphic")
            return element

        return SvgDocument.url(self._document.define(element_id, factory))
    def film_grain(self, *, opacity: float = 0.035) -> str:
        """Static monochrome grain that keeps flat fills from banding."""
        element_id = "filter-grain"

        def factory() -> Element:
            element = Element(
                "filter",
                x="0%",
                y="0%",
                width="100%",
                height="100%",
                color_interpolation_filters="sRGB",
            )
            element.child(
                "feTurbulence",
                type="fractalNoise",
                baseFrequency="0.85",
                numOctaves=2,
                stitchTiles="stitch",
                result="noise",
            )
            element.child(
                "feColorMatrix",
                in_="noise",
                type="saturate",
                values="0",
                result="mono",
            )
            transfer = element.child("feComponentTransfer", in_="mono", result="faded")
            transfer.child("feFuncA", type="linear", slope=opacity, intercept=0)
            return element

        return SvgDocument.url(self._document.define(element_id, factory))
    # -- reusable geometry --------------------------------------------------

    def rounded_clip(
        self,
        element_id: str,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        radius: float,
    ) -> str:
        """Define a rounded-rectangle ``clipPath`` and return its id."""

        def factory() -> Element:
            clip = Element("clipPath")
            clip.child("rect", x=x, y=y, width=width, height=height, rx=radius, ry=radius)
            return clip

        return self._document.define(element_id, factory)

    def symbol_rect(
        self,
        element_id: str,
        *,
        width: float,
        height: float,
        radius: float,
        fill: str,
        stroke: str | None = None,
        stroke_width: float | None = None,
        filter_url: str | None = None,
    ) -> str:
        """Define a reusable origin-centred ``<rect>`` for ``<use>`` instancing.

        The contribution calendar paints 371 squares drawn from five level
        colours and one specular overlay.  Defining six rectangles and
        referencing them keeps roughly a hundred bytes of duplicated geometry
        off every single cell.
        """

        def factory() -> Element:
            return Element(
                "rect",
                x=-width / 2,
                y=-height / 2,
                width=width,
                height=height,
                rx=radius,
                ry=radius,
                fill=fill,
                stroke=stroke,
                stroke_width=stroke_width,
                filter=filter_url,
                shape_rendering="geometricPrecision",
            )

        return self._document.define(element_id, factory)

    @staticmethod
    def use(element_id: str, **attributes: object) -> Element:
        """Build a ``<use>`` referencing ``element_id``.

        Both ``href`` and the legacy ``xlink:href`` are emitted so the asset
        renders identically on modern browsers and on older SVG 1.1 renderers.
        """
        element = Element("use", **attributes)
        element.set_raw({"href": f"#{element_id}", "xlink:href": f"#{element_id}"})
        return element

    def breathing_opacity(self, *, low: float, high: float, period_ms: float) -> Element:
        """A free-running opacity oscillation for ambient elements."""
        return LoopClock.free_running(
            "opacity",
            (low, high, low),
            period_ms=period_ms,
        )

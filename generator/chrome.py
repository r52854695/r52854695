"""Shared visual furniture: monospace grids and the macOS window frame.

Both the ASCII portrait card and the neofetch info card are terminal windows.
Rather than duplicating the rounded body, hairline border, frosted title bar
and traffic lights in two generators, the whole frame is built once here and
parameterised by size and title.
"""

from __future__ import annotations

from dataclasses import dataclass

from .colors import darken, lighten, with_alpha
from .config_types import ConfigLike
from .defs import GradientStop, PaintLibrary
from .easing import EASE_IN_OUT_SINE, EASE_OUT_EXPO
from .svg import Element
from .timeline import LoopClock

__all__ = ["MonoGrid", "WindowChrome", "WindowFrame"]

#: Radius of a macOS traffic-light button.
_TRAFFIC_LIGHT_RADIUS = 6.0
#: Horizontal gap between traffic-light centres.
_TRAFFIC_LIGHT_PITCH = 20.0
#: Distance from the card's left edge to the first traffic light's centre.
_TRAFFIC_LIGHT_INSET = 20.0
#: Thickness of the specular hairline riding the card's top edge.
_TOP_HIGHLIGHT_HEIGHT = 1.0
#: Title-bar sheen sweep width, as a fraction of the card width.
_SHEEN_WIDTH_RATIO = 0.34
#: Period of the title-bar sheen sweep.
_SHEEN_PERIOD_MS = 6400.0


@dataclass(frozen=True)
class MonoGrid:
    """A pixel-exact character grid for a monospaced font.

    SVG cannot query font metrics, so every terminal layout in this project is
    computed from a single assumption — that a monospaced glyph advances
    ``advance_ratio`` times the font size — and then *enforced* at render time
    with ``textLength``.  That combination makes the output identical whichever
    monospaced face the viewer happens to have installed.

    Attributes:
        font_size: Glyph size in user units.
        line_height: Vertical pitch between baselines.
        advance_ratio: Horizontal advance as a multiple of ``font_size``.
    """

    font_size: float
    line_height: float
    advance_ratio: float = 0.6

    @property
    def advance(self) -> float:
        """Horizontal advance of a single character cell."""
        return self.font_size * self.advance_ratio

    def width_of(self, characters: int) -> float:
        """Width of ``characters`` cells."""
        return self.advance * characters

    def column_x(self, origin_x: float, column: int) -> float:
        """Left edge of the given zero-based column."""
        return origin_x + self.advance * column

    def baseline_y(self, origin_y: float, row: int) -> float:
        """Baseline of the given zero-based row.

        The 0.78 factor places the baseline at a typographically natural
        position inside the line box for the monospaced faces we target.
        """
        return origin_y + self.line_height * row + self.font_size * 0.78

    def row_top(self, origin_y: float, row: int) -> float:
        """Top edge of the given zero-based row's line box."""
        return origin_y + self.line_height * row

    def text(
        self,
        content: str,
        *,
        x: float,
        y: float,
        fill: str,
        font_family: str,
        opacity: float | None = None,
        enforce_grid: bool = True,
        letter_count: int | None = None,
        weight: str | None = None,
    ) -> Element:
        """Build one grid-locked ``<text>`` run.

        Args:
            content: The literal text; leading and trailing spaces are kept.
            x: Left edge in user units.
            y: Baseline in user units.
            fill: Paint for the glyphs.
            font_family: The monospaced font stack.
            opacity: Optional fill opacity.
            enforce_grid: Pin the run's advance width with ``textLength`` so the
                character grid survives font substitution.
            letter_count: Override the character count used for ``textLength``.
            weight: Optional ``font-weight``.

        Returns:
            The configured ``<text>`` element.
        """
        element = Element(
            "text",
            content,
            x=x,
            y=y,
            fill=fill,
            font_family=font_family,
            font_size=self.font_size,
            font_weight=weight,
            opacity=None if opacity is None else round(opacity, 4),
        )
        element.set_raw({"xml:space": "preserve"})
        # `lengthAdjust="spacing"` distributes the correction between glyphs,
        # so it is meaningless — and, on some renderers, harmful — for a single
        # character.  Short runs simply rely on the font's natural advance.
        if enforce_grid and len(content) > 1:
            count = letter_count if letter_count is not None else len(content)
            element.set(textLength=self.width_of(count), lengthAdjust="spacing")
        return element


@dataclass(frozen=True)
class WindowFrame:
    """The content area left over after the chrome has been drawn."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        """Right edge of the content area."""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """Bottom edge of the content area."""
        return self.y + self.height


class WindowChrome:
    """Draws a macOS terminal window: body, border, title bar, buttons.

    Args:
        config: Active configuration.
        paint: The document's paint library.
        clock: The document's loop clock, used for the ambient title-bar sheen.
    """

    def __init__(self, config: ConfigLike, paint: PaintLibrary, clock: LoopClock) -> None:
        self._config = config
        self._paint = paint
        self._clock = clock

    def draw(
        self,
        parent: Element,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        titlebar_height: float,
        corner_radius: float,
        padding: float,
        title: str,
        accent: str,
    ) -> WindowFrame:
        """Render the full window frame into ``parent``.

        Args:
            parent: Element to append the chrome to.
            x: Card left edge.
            y: Card top edge.
            width: Card width.
            height: Card height.
            titlebar_height: Height of the frosted title bar.
            corner_radius: Card corner radius.
            padding: Inner padding applied to the content area.
            title: Text shown centred in the title bar.
            accent: Accent colour for the title bar's bottom rule.

        Returns:
            The :class:`WindowFrame` describing the usable content area.
        """
        palette = self._config.palette
        fonts = self._config.typography
        group = parent.group()

        clip_id = self._paint.rounded_clip(
            f"clip-window-{int(x)}-{int(y)}-{int(width)}-{int(height)}",
            x=x,
            y=y,
            width=width,
            height=height,
            radius=corner_radius,
        )

        # --- body ----------------------------------------------------------
        group.child(
            "rect",
            x=x,
            y=y,
            width=width,
            height=height,
            rx=corner_radius,
            ry=corner_radius,
            fill=self._paint.card_surface(width, height),
        )

        clipped = group.group(clip_path=f"url(#{clip_id})")

        # --- frosted title bar ---------------------------------------------
        clipped.child(
            "rect",
            x=x,
            y=y,
            width=width,
            height=titlebar_height,
            fill=self._paint.titlebar_glass(width, titlebar_height),
        )
        clipped.child(
            "rect",
            x=x,
            y=y + titlebar_height - 1,
            width=width,
            height=1,
            fill=with_alpha(accent, 0.28),
        )

        # A slow specular sheen drifting across the glass.
        sheen_width = width * _SHEEN_WIDTH_RATIO
        sheen = clipped.child(
            "rect",
            x=-sheen_width,
            y=y,
            width=sheen_width,
            height=titlebar_height,
            fill=self._paint.linear_gradient(
                "grad-titlebar-sheen",
                (
                    GradientStop(0.0, "#ffffff", 0.0),
                    GradientStop(0.5, "#ffffff", 0.055),
                    GradientStop(1.0, "#ffffff", 0.0),
                ),
            ),
        )
        sheen.add(
            LoopClock.free_running(
                "x",
                (x - sheen_width, x + width),
                period_ms=_SHEEN_PERIOD_MS,
            )
        )

        # --- top specular hairline -----------------------------------------
        clipped.child(
            "rect",
            x=x,
            y=y,
            width=width,
            height=_TOP_HIGHLIGHT_HEIGHT,
            fill=self._paint.top_highlight(width),
        )

        # --- traffic lights -------------------------------------------------
        self._draw_traffic_lights(
            clipped,
            x=x + _TRAFFIC_LIGHT_INSET,
            y=y + titlebar_height / 2,
        )

        # --- title ----------------------------------------------------------
        if title:
            clipped.add(
                Element(
                    "text",
                    title,
                    x=x + width / 2,
                    y=y + titlebar_height / 2 + 4,
                    fill=palette.text_muted,
                    font_family=fonts.mono,
                    font_size=11,
                    text_anchor="middle",
                    letter_spacing="0.4",
                )
            )

        # --- vignette + grain ----------------------------------------------
        clipped.child(
            "rect",
            x=x,
            y=y,
            width=width,
            height=height,
            fill=self._paint.vignette(width, height),
            pointer_events="none",
        )
        clipped.child(
            "rect",
            x=x,
            y=y,
            width=width,
            height=height,
            filter=self._paint.film_grain(),
            opacity=0.5,
            pointer_events="none",
        )

        # --- border ----------------------------------------------------------
        group.child(
            "rect",
            x=x + 0.5,
            y=y + 0.5,
            width=width - 1,
            height=height - 1,
            rx=corner_radius,
            ry=corner_radius,
            fill="none",
            stroke=palette.border,
            stroke_width=1,
        )

        content_top = y + titlebar_height + padding
        return WindowFrame(
            x=x + padding,
            y=content_top,
            width=width - padding * 2,
            height=y + height - padding - content_top,
        )

    # -- internals ----------------------------------------------------------

    def _draw_traffic_lights(self, parent: Element, *, x: float, y: float) -> None:
        """Draw the three macOS window buttons with a staggered wake-up."""
        palette = self._config.palette
        colors = (palette.traffic_red, palette.traffic_yellow, palette.traffic_green)

        for index, color in enumerate(colors):
            centre_x = x + _TRAFFIC_LIGHT_PITCH * index
            button = parent.group(transform=f"translate({centre_x:.2f},{y:.2f})")

            # Each button springs in, 90ms apart, then holds.
            start = 120.0 + index * 90.0
            button.add(
                self._clock.animate_transform(
                    "scale",
                    [(start, 0.0), (start + 260.0, 1.12), (start + 460.0, 1.0)],
                    ease=[EASE_OUT_EXPO, EASE_IN_OUT_SINE],
                )
            )

            gradient = self._paint.radial_gradient(
                f"grad-traffic-{index}",
                (
                    GradientStop(0.0, lighten(color, 0.34)),
                    GradientStop(0.55, color),
                    GradientStop(1.0, darken(color, 0.24)),
                ),
                cx=0.36,
                cy=0.3,
                r=0.78,
            )
            button.child("circle", r=_TRAFFIC_LIGHT_RADIUS, fill=gradient)
            button.child(
                "circle",
                r=_TRAFFIC_LIGHT_RADIUS,
                fill="none",
                stroke=darken(color, 0.42),
                stroke_width=0.6,
                opacity=0.7,
            )
            # Tiny specular dot in the upper-left of each button.
            button.child(
                "ellipse",
                cx=-1.7,
                cy=-2.0,
                rx=2.1,
                ry=1.4,
                fill="#ffffff",
                opacity=0.34,
            )

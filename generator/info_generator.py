"""Generates ``info-card.svg`` — the neofetch-style profile card.

A compact terminal window that prints an ``About / Stack / Highlights`` summary
line by line.  Each line rises ten pixels while fading in, sixty milliseconds
after the line above it, which reproduces the cadence of a real program writing
to a TTY rather than a UI element animating in.

Colour roles are fixed by the design system and enforced here in one place:
orange section headers, cyan separators, white labels, green values, blue
bullets.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import AssetGenerator
from .chrome import MonoGrid, WindowChrome
from .colors import with_alpha
from .config_types import ConfigLike
from .content import InfoContent, InfoRow, InfoSection, RowKind
from .easing import EASE_IN_OUT_SINE, EASE_OUT_CUBIC, EASE_OUT_EXPO
from .svg import Element, SvgDocument
from .timeline import LoopClock

__all__ = ["InfoGenerator", "InfoLayout"]

#: Height of the cyan hairline drawn beneath each section header.
_SEPARATOR_HEIGHT = 1.0
#: Vertical offset of that hairline below the header's baseline.
_SEPARATOR_DROP = 5.0
#: Fraction of a line height a section header's rule spans horizontally.
_SEPARATOR_WIDTH_RATIO = 1.0
#: Width of the accent bar to the left of each section header.
_HEADER_MARKER_WIDTH = 3.0
#: Extra opacity applied to values so they read brighter than labels.
_VALUE_OPACITY = 1.0
_LABEL_OPACITY = 0.92


@dataclass(frozen=True)
class InfoLayout:
    """Resolved geometry of the info card."""

    width: float
    height: float
    grid: MonoGrid
    content_x: float
    content_y: float
    content_width: float
    section_gap: float

    @classmethod
    def create(
        cls, config: ConfigLike, content: InfoContent, *, min_height: float | None
    ) -> "InfoLayout":
        """Derive the card geometry, optionally stretching to a target height.

        When the README places this card beside the terminal card, the two must
        share an aspect ratio or the table row will look ragged.  Rather than
        letting empty space pool at the bottom, any surplus height is
        distributed into the gaps between sections, which reads as deliberate
        typographic rhythm instead of padding.

        Args:
            config: Active configuration.
            content: The parsed card content, which fixes the line count.
            min_height: Optional height to match, in user units.

        Returns:
            A fully resolved :class:`InfoLayout`.
        """
        settings = config.info
        grid = MonoGrid(
            font_size=settings.font_size,
            line_height=settings.line_height,
            advance_ratio=config.typography.mono_advance_ratio,
        )

        content_x = settings.padding
        content_y = settings.titlebar_height + settings.padding
        content_width = settings.width - settings.padding * 2

        section_count = max(len(content.sections), 1)
        text_height = grid.line_height * content.total_lines
        gaps = max(section_count - 1, 0)
        natural_height = (
            content_y
            + text_height
            + settings.section_gap * gaps
            + settings.header_gap * section_count
            + settings.padding
        )

        section_gap = settings.section_gap
        height = natural_height
        if min_height is not None and min_height > natural_height:
            surplus = min_height - natural_height
            if gaps:
                per_gap = min(surplus / gaps, settings.max_section_gap - section_gap)
                section_gap += max(per_gap, 0.0)
                surplus -= max(per_gap, 0.0) * gaps
            # Whatever the gaps could not absorb centres the block vertically.
            content_y += surplus / 2.0
            height = min_height

        return cls(
            width=settings.width,
            height=height,
            grid=grid,
            content_x=content_x,
            content_y=content_y,
            content_width=content_width,
            section_gap=section_gap,
        )


class InfoGenerator(AssetGenerator):
    """Builds the neofetch-style info card."""

    filename = "info-card.svg"
    display_name = "info card"

    def __init__(
        self,
        config: ConfigLike,
        content: InfoContent,
        *,
        min_height: float | None = None,
    ) -> None:
        super().__init__(config)
        self.content = content
        self.layout = InfoLayout.create(config, content, min_height=min_height)
        self._loop_duration_ms = self._compute_loop_duration()

    # -- timing -------------------------------------------------------------

    def _line_delay(self, line_index: int) -> float:
        """Print delay for a line, staggered from the line above it."""
        return line_index * self.config.info.row_stagger_ms

    @property
    def _print_end_ms(self) -> float:
        """When the last line has finished printing."""
        last_line = max(self.content.total_lines - 1, 0)
        return self._line_delay(last_line) + self.config.info.row_reveal_ms

    def _compute_loop_duration(self) -> float:
        """Printing, then a hold, then the exit fade."""
        animation = self.config.animation
        return self._print_end_ms + animation.hold_ms + animation.loop_fade_ms

    @property
    def _exit_start_ms(self) -> float:
        """Absolute time at which the composition begins fading out."""
        return self._loop_duration_ms - self.config.animation.loop_fade_ms

    # -- build --------------------------------------------------------------

    def build(self) -> SvgDocument:
        """Assemble the complete info card document."""
        layout = self.layout
        settings = self.config.info
        document, paint = self.new_document(
            layout.width,
            layout.height,
            title=f"{self.config.username} profile summary",
            description=(
                "A neofetch-style terminal card printing an about, stack and "
                "highlights summary line by line."
            ),
        )
        clock = self.new_clock(self._loop_duration_ms)

        document.child(
            "rect",
            width=layout.width,
            height=layout.height,
            fill=paint.page_background(layout.width, layout.height),
        )

        chrome = WindowChrome(self.config, paint, clock)
        chrome.draw(
            document,
            x=0,
            y=0,
            width=layout.width,
            height=layout.height,
            titlebar_height=settings.titlebar_height,
            corner_radius=settings.corner_radius,
            padding=settings.padding,
            title=settings.window_title,
            accent=self.config.palette.orange,
        )

        stage = document.group()
        stage.add(
            clock.animate(
                "opacity",
                [(0.0, 1), (self._exit_start_ms, 1), (self._loop_duration_ms, 0)],
                ease=EASE_IN_OUT_SINE,
            )
        )
        self._draw_sections(stage, clock)
        return document

    # -- layers -------------------------------------------------------------

    def _draw_sections(self, parent: Element, clock: LoopClock) -> None:
        """Walk every section and row, emitting one printed line at a time."""
        layout = self.layout
        settings = self.config.info
        cursor_y = layout.content_y

        line_index = 0
        for section_index, section in enumerate(self.content.sections):
            if section_index:
                cursor_y += layout.section_gap

            self._draw_section_header(
                parent, clock, section=section, top=cursor_y, line_index=line_index
            )
            cursor_y += layout.grid.line_height + settings.header_gap
            line_index += 1

            for row in section.rows:
                self._draw_row(
                    parent, clock, row=row, top=cursor_y, line_index=line_index
                )
                cursor_y += layout.grid.line_height
                line_index += 1

    def _printed_line(self, clock: LoopClock, line_index: int) -> Element:
        """A group that slides up ten pixels while fading in, on schedule."""
        settings = self.config.info
        delay = self._line_delay(line_index)
        group = Element("g", opacity=0)
        group.add(
            clock.animate(
                "opacity",
                [(delay, 0), (delay + settings.row_reveal_ms * 0.62, 1)],
                ease=EASE_OUT_CUBIC,
            )
        )
        group.add(
            clock.animate_transform(
                "translate",
                [
                    (delay, (0.0, settings.row_rise_px)),
                    (delay + settings.row_reveal_ms, (0.0, 0.0)),
                ],
                ease=EASE_OUT_EXPO,
            )
        )
        return group

    def _draw_section_header(
        self,
        parent: Element,
        clock: LoopClock,
        *,
        section: InfoSection,
        top: float,
        line_index: int,
    ) -> None:
        """Orange section title, accent marker and the cyan separator rule."""
        layout = self.layout
        settings = self.config.info
        grid = layout.grid
        fonts = self.config.typography

        line = self._printed_line(clock, line_index)
        parent.add(line)

        marker_height = grid.font_size * 0.86
        line.child(
            "rect",
            x=layout.content_x,
            y=top + (grid.line_height - marker_height) / 2,
            width=_HEADER_MARKER_WIDTH,
            height=marker_height,
            rx=1.5,
            ry=1.5,
            fill=settings.header_color,
        )

        text_x = layout.content_x + _HEADER_MARKER_WIDTH + grid.advance
        line.add(
            grid.text(
                section.title,
                x=text_x,
                y=grid.baseline_y(top, 0),
                fill=settings.header_color,
                font_family=fonts.sans,
                weight="700",
                enforce_grid=False,
            )
        )

        # Cyan separator, drawn from the title's right edge to the card margin.
        title_width = grid.width_of(len(section.title)) + grid.advance * 2
        rule_x = text_x + title_width
        line.child(
            "rect",
            x=rule_x,
            y=grid.baseline_y(top, 0) + _SEPARATOR_DROP,
            width=max(
                (layout.content_x + layout.content_width - rule_x)
                * _SEPARATOR_WIDTH_RATIO,
                0.0,
            ),
            height=_SEPARATOR_HEIGHT,
            fill=with_alpha(settings.separator_color, 0.42),
        )

    def _draw_row(
        self,
        parent: Element,
        clock: LoopClock,
        *,
        row: InfoRow,
        top: float,
        line_index: int,
    ) -> None:
        """Render one content row according to its kind."""
        if row.kind is RowKind.BLANK:
            return

        layout = self.layout
        settings = self.config.info
        grid = layout.grid
        fonts = self.config.typography
        baseline = grid.baseline_y(top, 0)

        line = self._printed_line(clock, line_index)
        parent.add(line)

        if row.kind is RowKind.RULE:
            line.child(
                "rect",
                x=layout.content_x,
                y=top + grid.line_height / 2,
                width=layout.content_width,
                height=_SEPARATOR_HEIGHT,
                fill=with_alpha(settings.separator_color, 0.28),
            )
            return

        if row.kind is RowKind.BULLET:
            line.add(
                grid.text(
                    settings.bullet_glyph,
                    x=layout.content_x + grid.advance,
                    y=baseline,
                    fill=settings.bullet_color,
                    font_family=fonts.mono,
                    enforce_grid=False,
                )
            )
            line.add(
                grid.text(
                    row.value,
                    x=grid.column_x(layout.content_x, 3),
                    y=baseline,
                    fill=settings.label_color,
                    font_family=fonts.mono,
                    opacity=_LABEL_OPACITY,
                )
            )
            return

        if row.kind is RowKind.TEXT:
            line.add(
                grid.text(
                    row.value,
                    x=layout.content_x + grid.advance,
                    y=baseline,
                    fill=settings.label_color,
                    font_family=fonts.mono,
                    opacity=_LABEL_OPACITY,
                )
            )
            return

        # RowKind.KEY_VALUE — white label, green value, aligned on a column.
        line.add(
            grid.text(
                row.label,
                x=layout.content_x + grid.advance,
                y=baseline,
                fill=settings.label_color,
                font_family=fonts.mono,
                opacity=_LABEL_OPACITY,
            )
        )
        line.add(
            grid.text(
                row.value,
                x=grid.column_x(layout.content_x, settings.value_column),
                y=baseline,
                fill=settings.value_color,
                font_family=fonts.mono,
                opacity=_VALUE_OPACITY,
            )
        )

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        """One-line summary used by the build script."""
        return (
            f"{len(self.content.sections)} sections · {self.content.total_lines} lines "
            f"· {self.layout.width:.0f}x{self.layout.height:.0f}px"
        )

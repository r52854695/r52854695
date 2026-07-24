"""Generates ``terminal-card.svg`` — the ASCII portrait terminal.

The card is a macOS terminal window containing a dense ASCII rendering of the
user's GitHub avatar.  The portrait does not simply fade in: every row is
*typed*, revealed left-to-right by an animated ``clipPath`` while a white block
cursor rides the leading edge and jumps to the start of the next row when a
line completes.  A ``$ whoami`` prompt then types itself in the footer, prints
the username, and returns to a blinking cursor.

The font size is derived from the card width rather than configured, so the
character grid always fills the content area exactly; ``textLength`` then pins
that grid in place no matter which monospaced face the viewer has installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .avatar_to_ascii import AsciiPortrait
from .base import AssetGenerator
from .chrome import MonoGrid, WindowChrome
from .config_types import ConfigLike
from .defs import GradientStop, PaintLibrary
from .easing import EASE_IN_OUT_SINE, EASE_OUT_CUBIC, EASE_OUT_EXPO
from .svg import Element, SvgDocument
from .timeline import LoopClock

__all__ = ["TerminalGenerator", "TerminalLayout"]

#: Extra clip height around a portrait row, so the rise never crops a glyph.
_ROW_CLIP_BLEED = 2.0
#: Fade-in duration of a single portrait row, relative to its type duration.
_ROW_FADE_RATIO = 0.55
#: Height of the footer separator rule.
_RULE_HEIGHT = 1.0
#: Number of footer lines: command, output, trailing prompt.
_FOOTER_LINES = 3
#: Blink duty cycle keyframes for a terminal cursor.
_BLINK_VALUES = (1, 0, 1)
_BLINK_KEY_TIMES = (0.0, 0.5, 1.0)


@dataclass(frozen=True)
class TerminalLayout:
    """Resolved geometry of the terminal card."""

    width: float
    height: float
    ascii_grid: MonoGrid
    ascii_x: float
    ascii_y: float
    ascii_width_px: float
    ascii_height_px: float
    rule_y: float
    footer_grid: MonoGrid
    footer_y: float

    @classmethod
    def create(cls, config: ConfigLike, portrait: AsciiPortrait) -> "TerminalLayout":
        """Derive every coordinate from the card width and portrait shape.

        Args:
            config: Active configuration.
            portrait: The converted ASCII art, which fixes the row count.

        Returns:
            A fully resolved :class:`TerminalLayout`.
        """
        settings = config.terminal
        advance_ratio = config.typography.mono_advance_ratio

        content_width = settings.width - settings.padding * 2
        advance = content_width / portrait.width
        font_size = advance / advance_ratio
        line_height = font_size * settings.ascii_line_height_ratio

        ascii_grid = MonoGrid(
            font_size=font_size,
            line_height=line_height,
            advance_ratio=advance_ratio,
        )
        footer_grid = MonoGrid(
            font_size=settings.footer_font_size,
            line_height=settings.footer_line_height,
            advance_ratio=advance_ratio,
        )

        ascii_x = settings.padding
        ascii_y = settings.titlebar_height + settings.padding
        ascii_height_px = line_height * portrait.height

        rule_y = ascii_y + ascii_height_px + settings.footer_gap
        footer_y = rule_y + _RULE_HEIGHT + settings.footer_gap * 0.82
        height = (
            footer_y
            + settings.footer_line_height * _FOOTER_LINES
            + settings.padding * 0.6
        )

        return cls(
            width=settings.width,
            height=height,
            ascii_grid=ascii_grid,
            ascii_x=ascii_x,
            ascii_y=ascii_y,
            ascii_width_px=advance * portrait.width,
            ascii_height_px=ascii_height_px,
            rule_y=rule_y,
            footer_grid=footer_grid,
            footer_y=footer_y,
        )


class TerminalGenerator(AssetGenerator):
    """Builds the ASCII-portrait terminal card."""

    filename = "terminal-card.svg"
    display_name = "ascii terminal card"

    def __init__(
        self,
        config: ConfigLike,
        portrait: AsciiPortrait,
        *,
        username: str | None = None,
    ) -> None:
        super().__init__(config)
        self.portrait = portrait
        self.username = username or config.username
        self.layout = TerminalLayout.create(config, portrait)
        self._loop_duration_ms = self._compute_loop_duration()

    # -- timing -------------------------------------------------------------

    @property
    def _row_pitch_ms(self) -> float:
        """Time from the start of one portrait row to the start of the next."""
        settings = self.config.terminal
        return settings.row_type_ms + settings.row_gap_ms

    def _row_start_ms(self, row_index: int) -> float:
        """Absolute time at which a portrait row begins typing."""
        return row_index * self._row_pitch_ms

    @property
    def _portrait_end_ms(self) -> float:
        """Absolute time at which the last portrait row finishes."""
        return self._row_start_ms(self.portrait.height - 1) + self.config.terminal.row_type_ms

    @property
    def _command_text(self) -> str:
        """The full command line, prompt symbol included."""
        settings = self.config.terminal
        return f"{settings.prompt_symbol} {settings.prompt_command}"

    @property
    def _command_start_ms(self) -> float:
        """When the footer command begins typing."""
        return self._portrait_end_ms + self.config.terminal.row_gap_ms * 12.0

    @property
    def _command_end_ms(self) -> float:
        """When the footer command finishes typing."""
        return self._command_start_ms + len(self._command_text) * self.config.terminal.char_type_ms

    @property
    def _output_start_ms(self) -> float:
        """When the command's output begins printing."""
        return self._command_end_ms + self.config.terminal.command_output_delay_ms

    @property
    def _output_end_ms(self) -> float:
        """When the command's output finishes printing."""
        return self._output_start_ms + len(self.username) * self.config.terminal.char_type_ms

    @property
    def _prompt_return_ms(self) -> float:
        """When the trailing prompt and its blinking cursor appear."""
        return self._output_end_ms + self.config.terminal.prompt_return_delay_ms

    def _compute_loop_duration(self) -> float:
        """Portrait typing, prompt sequence, hold, then the exit fade."""
        animation = self.config.animation
        return self._prompt_return_ms + animation.hold_ms + animation.loop_fade_ms

    @property
    def _exit_start_ms(self) -> float:
        """Absolute time at which the composition begins fading out."""
        return self._loop_duration_ms - self.config.animation.loop_fade_ms

    # -- build --------------------------------------------------------------

    def build(self) -> SvgDocument:
        """Assemble the complete terminal card document."""
        layout = self.layout
        settings = self.config.terminal
        document, paint = self.new_document(
            layout.width,
            layout.height,
            title=f"{self.username} ASCII portrait terminal",
            description=(
                "A macOS terminal window in which the user's GitHub avatar is "
                "typed out as ASCII art, followed by a $ whoami prompt."
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
            accent=self.config.palette.cyan,
        )

        stage = document.group()
        stage.add(
            clock.animate(
                "opacity",
                [(0.0, 1), (self._exit_start_ms, 1), (self._loop_duration_ms, 0)],
                ease=EASE_IN_OUT_SINE,
            )
        )

        self._draw_portrait(stage, paint, clock)
        self._draw_scanline(stage, paint)
        self._draw_portrait_cursor(stage, clock)
        self._draw_separator(stage, paint, clock)
        self._draw_footer(stage, paint, clock)
        return document

    # -- layers -------------------------------------------------------------

    def _draw_portrait(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Type every ASCII row behind an animated clip rectangle."""
        layout = self.layout
        settings = self.config.terminal
        grid = layout.ascii_grid

        fill = paint.ascii_gradient(
            layout.ascii_x, layout.ascii_y, layout.ascii_width_px, layout.ascii_height_px
        )
        portrait_group = parent.group()

        for row_index, row_text in enumerate(self.portrait.rows):
            start = self._row_start_ms(row_index)
            row_top = grid.row_top(layout.ascii_y, row_index)

            clip_id = self._define_row_clip(
                paint,
                clip_id=f"clip-ascii-row-{row_index}",
                x=layout.ascii_x,
                y=row_top - _ROW_CLIP_BLEED,
                height=grid.line_height + _ROW_CLIP_BLEED * 2,
                width=layout.ascii_width_px,
                start_ms=start,
                clock=clock,
            )

            clipped = portrait_group.group(clip_path=f"url(#{clip_id})")
            revealed = clipped.group(opacity=0)
            revealed.add(
                clock.animate(
                    "opacity",
                    [(start, 0), (start + settings.row_type_ms * _ROW_FADE_RATIO, 1)],
                    ease=EASE_OUT_CUBIC,
                )
            )
            revealed.add(
                clock.animate_transform(
                    "translate",
                    [
                        (start, (0.0, settings.row_rise_px)),
                        (start + settings.row_type_ms, (0.0, 0.0)),
                    ],
                    ease=EASE_OUT_EXPO,
                )
            )
            revealed.add(
                grid.text(
                    row_text,
                    x=layout.ascii_x,
                    y=grid.baseline_y(layout.ascii_y, row_index),
                    fill=fill,
                    font_family=self.config.typography.mono,
                    opacity=self.portrait.shade_of(
                        row_index, floor=settings.ascii_row_shade_floor
                    ),
                )
            )

    def _define_row_clip(
        self,
        paint: PaintLibrary,
        *,
        clip_id: str,
        x: float,
        y: float,
        width: float,
        height: float,
        start_ms: float,
        clock: LoopClock,
    ) -> str:
        """Register one row's typing clip rectangle and animate its width."""
        settings = self.config.terminal

        def factory() -> Element:
            clip = Element("clipPath", clipPathUnits="userSpaceOnUse")
            rect = clip.child("rect", x=x, y=y, width=0, height=height)
            rect.add(
                clock.animate(
                    "width",
                    [(start_ms, 0.0), (start_ms + settings.row_type_ms, width)],
                    ease=EASE_OUT_CUBIC,
                )
            )
            return clip

        return paint.register(clip_id, factory)

    def _draw_scanline(self, parent: Element, paint: PaintLibrary) -> None:
        """A soft horizontal band drifting down the portrait, CRT-style."""
        layout = self.layout
        settings = self.config.terminal

        clip_id = paint.rounded_clip(
            "clip-ascii-area",
            x=layout.ascii_x,
            y=layout.ascii_y,
            width=layout.ascii_width_px,
            height=layout.ascii_height_px,
            radius=4,
        )
        wrapper = parent.group(clip_path=f"url(#{clip_id})", opacity=0.5)
        band_height = layout.ascii_height_px * 0.16
        band = wrapper.child(
            "rect",
            x=layout.ascii_x,
            y=layout.ascii_y - band_height,
            width=layout.ascii_width_px,
            height=band_height,
            fill=paint.linear_gradient(
                "grad-scanline",
                (
                    GradientStop(0.0, self.config.palette.cyan, 0.0),
                    GradientStop(0.5, self.config.palette.cyan, 0.10),
                    GradientStop(1.0, self.config.palette.cyan, 0.0),
                ),
                x1=0,
                y1=0,
                x2=0,
                y2=1,
            ),
        )
        band.add(
            LoopClock.free_running(
                "y",
                (
                    layout.ascii_y - band_height,
                    layout.ascii_y + layout.ascii_height_px,
                ),
                period_ms=settings.scanline_period_ms,
            )
        )

    def _draw_portrait_cursor(self, parent: Element, clock: LoopClock) -> None:
        """The block cursor that rakes each row and jumps to the next.

        A single rectangle serves every row: its translate track walks left to
        right across a row, then covers the carriage return in one millisecond,
        which reads as an instantaneous jump.
        """
        layout = self.layout
        settings = self.config.terminal
        grid = layout.ascii_grid

        cursor_group = parent.group(opacity=0)
        cursor_group.add(
            clock.gate(visible_from_ms=0.0, visible_to_ms=self._portrait_end_ms)
        )

        frames: list[tuple[float, tuple[float, float]]] = []
        for row_index in range(self.portrait.height):
            start = self._row_start_ms(row_index)
            end = start + settings.row_type_ms
            row_top = grid.row_top(layout.ascii_y, row_index)
            frames.append((start, (layout.ascii_x, row_top)))
            frames.append((end, (layout.ascii_x + layout.ascii_width_px, row_top)))
            if row_index + 1 < self.portrait.height:
                next_top = grid.row_top(layout.ascii_y, row_index + 1)
                frames.append((end + 1.0, (layout.ascii_x, next_top)))

        cursor_group.add(
            clock.animate_transform("translate", frames, ease=EASE_OUT_CUBIC)
        )
        cursor_group.child(
            "rect",
            width=grid.advance,
            height=grid.font_size * settings.cursor_height_ratio,
            y=(grid.line_height - grid.font_size * settings.cursor_height_ratio) / 2,
            rx=1,
            ry=1,
            fill=settings.cursor_color,
            opacity=settings.cursor_opacity,
        )

    def _draw_separator(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """The accent hairline between the portrait and the prompt."""
        layout = self.layout
        rule = parent.child(
            "rect",
            x=layout.ascii_x,
            y=layout.rule_y,
            width=0,
            height=_RULE_HEIGHT,
            fill=paint.accent_rule(layout.ascii_width_px),
        )
        rule.add(
            clock.animate(
                "width",
                [
                    (self._portrait_end_ms, 0.0),
                    (self._portrait_end_ms + 420.0, layout.ascii_width_px),
                ],
                ease=EASE_OUT_EXPO,
            )
        )

    def _draw_footer(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """The ``$ whoami`` sequence: command, output, trailing prompt."""
        layout = self.layout
        settings = self.config.terminal
        palette = self.config.palette
        fonts = self.config.typography
        grid = layout.footer_grid

        footer = parent.group()

        # --- line 1: the typed command -------------------------------------
        command = self._command_text
        self._draw_typed_line(
            footer,
            paint=paint,
            clock=clock,
            clip_id="clip-footer-command",
            grid=grid,
            row=0,
            segments=(
                (settings.prompt_symbol, palette.green),
                (" ", palette.text_primary),
                (settings.prompt_command, palette.text_primary),
            ),
            start_ms=self._command_start_ms,
            char_ms=settings.char_type_ms,
        )

        # --- line 2: the command's output ----------------------------------
        self._draw_typed_line(
            footer,
            paint=paint,
            clock=clock,
            clip_id="clip-footer-output",
            grid=grid,
            row=1,
            segments=((self.username, palette.cyan),),
            start_ms=self._output_start_ms,
            char_ms=settings.char_type_ms,
        )

        # --- line 3: the returning prompt ----------------------------------
        prompt = footer.group(opacity=0)
        prompt.add(
            clock.animate(
                "opacity",
                [(self._prompt_return_ms, 0), (self._prompt_return_ms + 180.0, 1)],
                ease=EASE_OUT_CUBIC,
            )
        )
        prompt.add(
            grid.text(
                settings.prompt_symbol,
                x=layout.ascii_x,
                y=grid.baseline_y(layout.footer_y, 2),
                fill=palette.green,
                font_family=fonts.mono,
            )
        )

        # --- the blinking cursor -------------------------------------------
        blink = footer.group(opacity=0)
        blink.add(
            clock.gate(
                visible_from_ms=self._prompt_return_ms,
                visible_to_ms=self._loop_duration_ms,
            )
        )
        cursor = blink.child(
            "rect",
            x=grid.column_x(layout.ascii_x, 2),
            y=grid.row_top(layout.footer_y, 2)
            + (grid.line_height - grid.font_size * settings.cursor_height_ratio) / 2,
            width=grid.advance,
            height=grid.font_size * settings.cursor_height_ratio,
            rx=1,
            ry=1,
            fill=settings.cursor_color,
            opacity=settings.cursor_opacity,
        )
        cursor.add(
            LoopClock.free_running(
                "opacity",
                _BLINK_VALUES,
                period_ms=self.config.animation.cursor_blink_ms,
                discrete=True,
                key_times=_BLINK_KEY_TIMES,
            )
        )

    def _draw_typed_line(
        self,
        parent: Element,
        *,
        paint: PaintLibrary,
        clock: LoopClock,
        clip_id: str,
        grid: MonoGrid,
        row: int,
        segments: tuple[tuple[str, str], ...],
        start_ms: float,
        char_ms: float,
    ) -> None:
        """Reveal a footer line one whole character at a time.

        Unlike the portrait rows — which are typed smoothly because a cursor
        rides their edge — footer text is revealed with ``calcMode="discrete"``
        so characters appear whole, exactly as a terminal emits them.

        Args:
            parent: Element to draw into.
            paint: Paint library, used to register the clip path.
            clock: The document clock.
            clip_id: Unique id for this line's clip path.
            grid: The footer character grid.
            row: Zero-based footer row.
            segments: ``(text, colour)`` runs rendered end to end.
            start_ms: When typing begins.
            char_ms: Time per character.
        """
        layout = self.layout
        total_characters = sum(len(text) for text, _ in segments)
        line_top = grid.row_top(layout.footer_y, row)

        def factory() -> Element:
            clip = Element("clipPath", clipPathUnits="userSpaceOnUse")
            rect = clip.child(
                "rect",
                x=layout.ascii_x,
                y=line_top - _ROW_CLIP_BLEED,
                width=0,
                height=grid.line_height + _ROW_CLIP_BLEED * 2,
            )
            frames = [
                (start_ms + index * char_ms, grid.width_of(index))
                for index in range(total_characters + 1)
            ]
            rect.add(clock.animate("width", frames, discrete=True))
            return clip

        line = parent.group(clip_path=f"url(#{paint.register(clip_id, factory)})")
        column = 0
        for text, color in segments:
            if text.strip():
                line.add(
                    grid.text(
                        text,
                        x=grid.column_x(layout.ascii_x, column),
                        y=grid.baseline_y(layout.footer_y, row),
                        fill=color,
                        font_family=self.config.typography.mono,
                    )
                )
            column += len(text)

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        """One-line summary used by the build script."""
        return (
            f"{self.portrait.width}x{self.portrait.height} ASCII "
            f"({self.portrait.source}) · {self.layout.width:.0f}x{self.layout.height:.0f}px"
        )

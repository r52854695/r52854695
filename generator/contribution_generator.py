"""Generates ``github-contribution-animation.svg``.

The calendar is GitHub's own geometry — 53 columns, 7 rows, 11px cells on a
3px gutter — driven by a diagonal wavefront that sweeps from the bottom-left
corner to the top-right.  Each square springs in from an offset position with
an overshoot, and is raked by a 120ms white specular glint at the moment it
lands.  Levels 3 and 4 additionally carry a bloom filter whose radius breathes
on its own slow period.

Everything is one synchronised, indefinitely repeating SMIL composition; see
:mod:`generator.timeline` for how that is achieved without JavaScript.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .base import AssetGenerator
from .colors import lighten
from .config_types import ConfigLike
from .defs import GradientStop, PaintLibrary
from .easing import (
    EASE_IN_OUT_SINE,
    EASE_OUT_CUBIC,
    EASE_OUT_EXPO,
    EASE_OUT_QUINT,
    spring_offset_track,
    spring_scale_track,
)
from .github import ContributionCalendar
from .svg import Element, SvgDocument
from .timeline import LoopClock

__all__ = ["ContributionGenerator", "CalendarLayout"]

#: Weekday rows GitHub labels, mapped to their row index.
_WEEKDAY_LABELS: dict[int, str] = {1: "Mon", 3: "Wed", 5: "Fri"}
#: Minimum column distance between two month labels before one is dropped.
_MIN_MONTH_LABEL_GAP = 3
#: Legend swatch size and spacing.
_LEGEND_SWATCH = 10.0
_LEGEND_GAP = 3.0
#: Radius multiplier of the halo fallback relative to the cell size.
_HALO_RADIUS_RATIO = 1.05
#: Opacity of the diagonal light sweep that follows the entrance wavefront.
_SWEEP_OPACITY = 0.16


@dataclass(frozen=True)
class CalendarLayout:
    """Every coordinate in the calendar card, derived from configuration.

    Computing the layout once, declaratively, is what keeps the drawing code
    free of magic numbers: nothing below ever adds a stray offset by hand.
    """

    width: float
    height: float
    grid_x: float
    grid_y: float
    grid_width: float
    grid_height: float
    pitch: float
    cell_size: float
    header_y: float
    month_label_y: float
    legend_y: float
    padding: float

    @classmethod
    def from_config(cls, config: ConfigLike) -> "CalendarLayout":
        """Derive the full layout from :class:`config.ContributionConfig`."""
        settings = config.contribution
        pitch = settings.cell_size + settings.cell_gap
        grid_width = settings.columns * pitch - settings.cell_gap
        grid_height = settings.rows * pitch - settings.cell_gap

        grid_x = settings.card_padding + settings.weekday_gutter
        grid_y = (
            settings.card_padding + settings.header_height + settings.month_label_height
        )

        width = settings.card_padding * 2 + settings.weekday_gutter + grid_width
        height = grid_y + grid_height + settings.legend_height + settings.card_padding

        return cls(
            width=width,
            height=height,
            grid_x=grid_x,
            grid_y=grid_y,
            grid_width=grid_width,
            grid_height=grid_height,
            pitch=pitch,
            cell_size=settings.cell_size,
            header_y=settings.card_padding,
            month_label_y=settings.card_padding + settings.header_height,
            legend_y=grid_y + grid_height + settings.legend_height * 0.5,
            padding=settings.card_padding,
        )

    def cell_center(self, column: int, row: int) -> tuple[float, float]:
        """Centre point of the square at ``(column, row)``."""
        return (
            self.grid_x + column * self.pitch + self.cell_size / 2.0,
            self.grid_y + row * self.pitch + self.cell_size / 2.0,
        )

    def column_x(self, column: int) -> float:
        """Left edge of a column."""
        return self.grid_x + column * self.pitch

    def row_y(self, row: int) -> float:
        """Top edge of a row."""
        return self.grid_y + row * self.pitch


class ContributionGenerator(AssetGenerator):
    """Builds the animated contribution calendar."""

    filename = "github-contribution-animation.svg"
    display_name = "contribution calendar"

    def __init__(self, config: ConfigLike, calendar: ContributionCalendar) -> None:
        super().__init__(config)
        self.calendar = calendar
        self.layout = CalendarLayout.from_config(config)
        self._jitter_table = self._build_jitter_table()
        self._loop_duration_ms = self._compute_loop_duration()
        # Filters are gorgeous but cost a full offscreen pass per element.  On
        # dense calendars we silently switch to pre-baked radial halos, which
        # are visually near-identical and roughly an order of magnitude cheaper.
        self._use_glow_filters = (
            calendar.glowing_cell_count <= config.glow.filter_budget
        )

    # -- timing -------------------------------------------------------------

    def _build_jitter_table(self) -> dict[tuple[int, int], float]:
        """Pre-roll one stable jitter value per grid position.

        The jitter must be a pure function of ``(column, row)``: month and
        weekday labels time themselves against the squares they sit beside, so
        drawing order must never be able to change a delay.
        """
        settings = self.config.contribution
        rng = random.Random(f"wave::{self.config.username}")
        return {
            (column, row): rng.random() * settings.wave_jitter_ms
            for column in range(settings.columns)
            for row in range(settings.rows)
        }

    @property
    def _max_wave_index(self) -> int:
        """Wavefront index of the last square to arrive (top-right corner)."""
        settings = self.config.contribution
        return (settings.columns - 1) + (settings.rows - 1)

    def _compute_loop_duration(self) -> float:
        """Total loop length: full sweep, then a hold, then the exit fade."""
        settings = self.config.contribution
        animation = self.config.animation
        sweep_ms = self._max_wave_index * settings.wave_step_ms + settings.wave_jitter_ms
        return sweep_ms + settings.cell_entrance_ms + animation.hold_ms + animation.loop_fade_ms

    @property
    def _exit_start_ms(self) -> float:
        """Absolute time at which the composition begins fading out."""
        return self._loop_duration_ms - self.config.animation.loop_fade_ms

    def _cell_delay(self, column: int, row: int) -> float:
        """Entrance delay for one square along the bottom-left -> top-right wave."""
        settings = self.config.contribution
        wave_index = column + (settings.rows - 1 - row)
        jitter = self._jitter_table.get((column, row), 0.0)
        return wave_index * settings.wave_step_ms + jitter

    def _glow_blur_for(self, level: int) -> float:
        """Bloom radius for a glowing level, so cells and legend always match."""
        glow = self.config.glow
        return (
            glow.soft_blur
            if level == self.config.contribution.glow_from_level
            else glow.strong_blur
        )

    # -- build --------------------------------------------------------------

    def build(self) -> SvgDocument:
        """Assemble the complete calendar document."""
        layout = self.layout
        document, paint = self.new_document(
            layout.width,
            layout.height,
            title=f"{self.config.username} contribution calendar",
            description=(
                f"{self.calendar.total} contributions over the last year, "
                "animated as a diagonal sweep."
            ),
        )
        clock = self.new_clock(self._loop_duration_ms)

        self._draw_backdrop(document, paint, clock)

        stage = document.group()
        stage.add(
            clock.animate(
                "opacity",
                [
                    (0.0, 1),
                    (self._exit_start_ms, 1),
                    (self._loop_duration_ms, 0),
                ],
                ease=EASE_IN_OUT_SINE,
            )
        )

        self._draw_header(stage, paint, clock)
        self._draw_month_labels(stage, clock)
        self._draw_weekday_labels(stage, clock)
        self._draw_grid(stage, paint, clock)
        self._draw_sweep(stage, paint, clock)
        self._draw_legend(stage, paint, clock)

        self._draw_border(document)
        return document

    # -- layers -------------------------------------------------------------

    def _draw_backdrop(
        self, document: SvgDocument, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Deep background plus the slowly drifting aurora blobs."""
        layout = self.layout
        palette = self.config.palette
        settings = self.config.contribution

        document.child(
            "rect",
            width=layout.width,
            height=layout.height,
            rx=14,
            ry=14,
            fill=paint.page_background(layout.width, layout.height),
        )

        clip_id = paint.rounded_clip(
            "clip-card",
            x=0,
            y=0,
            width=layout.width,
            height=layout.height,
            radius=14,
        )
        aurora_layer = document.group(
            clip_path=f"url(#{clip_id})", opacity=settings.aurora_opacity
        )

        # Three blobs on co-prime periods so the pattern never visibly repeats.
        blobs = (
            (palette.cyan, 0.16, 0.18, 300.0, 1.00, (36.0, 22.0)),
            (palette.purple, 0.72, 0.86, 340.0, 1.37, (-44.0, -26.0)),
            (palette.green, 0.46, 0.24, 260.0, 0.83, (28.0, -34.0)),
        )
        for index, (color, fx, fy, radius, period_scale, drift) in enumerate(blobs):
            group = aurora_layer.group()
            group.add(
                LoopClock.free_running_transform(
                    "translate",
                    ((0.0, 0.0), drift, (0.0, 0.0)),
                    period_ms=settings.aurora_drift_ms * period_scale,
                    ease=EASE_IN_OUT_SINE,
                )
            )
            group.child(
                "ellipse",
                cx=layout.width * fx,
                cy=layout.height * fy,
                rx=radius,
                ry=radius * 0.62,
                fill=paint.aurora(color),
            )
            group.add(
                paint.breathing_opacity(
                    low=0.55,
                    high=1.0,
                    period_ms=settings.aurora_drift_ms * (0.61 + index * 0.19),
                )
            )

        document.child(
            "rect",
            width=layout.width,
            height=layout.height,
            rx=14,
            ry=14,
            fill=paint.vignette(layout.width, layout.height),
        )

    def _draw_header(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Title, handle and the headline contribution total."""
        layout = self.layout
        palette = self.config.palette
        fonts = self.config.typography
        settings = self.config.contribution

        header = parent.group()
        header.add(
            clock.animate(
                "opacity", [(0.0, 0), (520.0, 1)], ease=EASE_OUT_EXPO
            )
        )
        header.add(
            clock.animate_transform(
                "translate",
                [(0.0, (0.0, -8.0)), (620.0, (0.0, 0.0))],
                ease=EASE_OUT_EXPO,
            )
        )

        title_y = layout.header_y + settings.title_font_size + 2
        header.add(
            Element(
                "text",
                "contribution graph",
                x=layout.padding,
                y=title_y,
                fill=paint.text_shimmer(
                    layout.width * 0.5,
                    (palette.text_primary, palette.cyan, palette.purple),
                ),
                font_family=fonts.sans,
                font_size=settings.title_font_size,
                font_weight="600",
                letter_spacing="-0.2",
            )
        )
        header.add(
            Element(
                "text",
                f"@{self.config.username} · last 12 months · {self.calendar.source} data",
                x=layout.padding,
                y=title_y + settings.subtitle_font_size + 6,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.subtitle_font_size,
            )
        )

        total_x = layout.width - layout.padding
        header.add(
            Element(
                "text",
                f"{self.calendar.total:,}",
                x=total_x,
                y=title_y + 2,
                fill=palette.neon_green,
                font_family=fonts.sans,
                font_size=settings.title_font_size + 7,
                font_weight="700",
                text_anchor="end",
                letter_spacing="-0.6",
            )
        )
        header.add(
            Element(
                "text",
                "contributions",
                x=total_x,
                y=title_y + settings.subtitle_font_size + 6,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.subtitle_font_size,
                text_anchor="end",
            )
        )

    def _draw_month_labels(self, parent: Element, clock: LoopClock) -> None:
        """Month names above the first column of each month."""
        if not self.config.contribution.show_month_labels:
            return
        layout = self.layout
        palette = self.config.palette
        fonts = self.config.typography
        settings = self.config.contribution

        group = parent.group()
        last_column = -_MIN_MONTH_LABEL_GAP
        for column, label in self.calendar.monthly_boundaries():
            if column - last_column < _MIN_MONTH_LABEL_GAP:
                continue
            if column > settings.columns - 2:
                continue
            last_column = column
            text = Element(
                "text",
                label,
                x=layout.column_x(column),
                y=layout.month_label_y + settings.label_font_size + 4,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.label_font_size,
                opacity=0,
            )
            delay = self._cell_delay(column, settings.rows - 1)
            text.add(
                clock.animate(
                    "opacity",
                    [(delay, 0), (delay + 380.0, 1)],
                    ease=EASE_OUT_CUBIC,
                )
            )
            group.add(text)

    def _draw_weekday_labels(self, parent: Element, clock: LoopClock) -> None:
        """Mon / Wed / Fri labels down the left gutter."""
        if not self.config.contribution.show_weekday_labels:
            return
        layout = self.layout
        palette = self.config.palette
        fonts = self.config.typography
        settings = self.config.contribution

        group = parent.group()
        for row, label in _WEEKDAY_LABELS.items():
            text = Element(
                "text",
                label,
                x=layout.grid_x - 8,
                y=layout.row_y(row) + settings.cell_size - 1.5,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.label_font_size,
                text_anchor="end",
                opacity=0,
            )
            delay = self._cell_delay(0, row)
            text.add(
                clock.animate(
                    "opacity",
                    [(delay, 0), (delay + 420.0, 1)],
                    ease=EASE_OUT_CUBIC,
                )
            )
            group.add(text)

    def _draw_grid(
        self,
        parent: Element,
        paint: PaintLibrary,
        clock: LoopClock,
    ) -> None:
        """Every contribution square, with spring entrance and specular glint."""
        settings = self.config.contribution
        glint_id = self._define_glint(paint)
        grid = parent.group()

        for column in range(settings.columns):
            for row in range(settings.rows):
                day = self.calendar.cell(column, row)
                if day is None:
                    # Out-of-range corners stay blank, exactly as GitHub renders.
                    continue
                grid.add(
                    self._build_cell(
                        paint=paint,
                        clock=clock,
                        glint_id=glint_id,
                        column=column,
                        row=row,
                        level=day.level,
                    )
                )

    def _build_cell(
        self,
        *,
        paint: PaintLibrary,
        clock: LoopClock,
        glint_id: str,
        column: int,
        row: int,
        level: int,
    ) -> Element:
        """Build one fully animated calendar square."""
        settings = self.config.contribution
        animation = self.config.animation
        centre_x, centre_y = self.layout.cell_center(column, row)
        delay = self._cell_delay(column, row)
        duration = settings.cell_entrance_ms

        cell = Element("g", opacity=0)

        # --- entrance: translate (spring) then scale (spring), composed -----
        offset_frames, offset_eases = spring_offset_track(
            duration, settings.entrance_offset
        )
        cell.add(
            clock.animate_transform(
                "translate",
                [
                    (delay + time, (centre_x + dx, centre_y + dy))
                    for time, (dx, dy) in offset_frames
                ],
                ease=offset_eases,
            )
        )
        scale_frames, scale_eases = spring_scale_track(
            duration,
            overshoot=animation.spring_overshoot,
            undershoot=animation.spring_undershoot,
        )
        cell.add(
            clock.animate_transform(
                "scale",
                [(delay + time, value) for time, value in scale_frames],
                ease=scale_eases,
                additive="sum",
            )
        )
        cell.add(
            clock.animate(
                "opacity",
                [(delay, 0), (delay + duration * 0.42, 1)],
                ease=EASE_OUT_QUINT,
            )
        )

        # --- glow, as a halo when the filter budget has been exceeded -------
        if level >= settings.glow_from_level and not self._use_glow_filters:
            cell.child(
                "circle",
                r=settings.cell_size * _HALO_RADIUS_RATIO * (1.0 + 0.18 * (level - 3)),
                fill=paint.halo(settings.level_colors[level]),
            )

        # --- the square itself, instanced from a shared definition ----------
        cell.add(PaintLibrary.use(self._define_square(paint, level)))

        # --- 120ms specular glint ------------------------------------------
        glint = PaintLibrary.use(glint_id, opacity=0)
        glint.add(
            clock.pulse(
                "opacity",
                start_ms=delay + animation.glint_peak_offset_ms,
                rise_ms=animation.glint_duration_ms * 0.22,
                fall_ms=animation.glint_duration_ms * 0.78,
                peak=animation.glint_opacity,
                ease=[EASE_OUT_EXPO, EASE_OUT_CUBIC],
            )
        )
        cell.add(glint)
        return cell

    def _define_glint(self, paint: PaintLibrary) -> str:
        """Register the single specular rectangle instanced by every square."""
        settings = self.config.contribution
        return paint.symbol_rect(
            "cell-glint",
            width=settings.cell_size,
            height=settings.cell_size,
            radius=settings.corner_radius,
            fill=paint.specular_sweep(),
        )

    def _define_square(self, paint: PaintLibrary, level: int) -> str:
        """Register the shared square for one contribution level."""
        settings = self.config.contribution
        color = settings.level_colors[level]
        glowing = level >= settings.glow_from_level and self._use_glow_filters
        return paint.symbol_rect(
            f"cell-lv{level}",
            width=settings.cell_size,
            height=settings.cell_size,
            radius=settings.corner_radius,
            fill=color,
            stroke=settings.empty_cell_stroke if level == 0 else None,
            stroke_width=1 if level == 0 else None,
            filter_url=(
                paint.glow_filter(color, blur=self._glow_blur_for(level), key=f"lv{level}")
                if glowing
                else None
            ),
        )

    def _draw_sweep(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """A wide diagonal light bar that travels with the entrance wavefront."""
        layout = self.layout
        palette = self.config.palette

        clip_id = paint.rounded_clip(
            "clip-grid",
            x=layout.grid_x - 4,
            y=layout.grid_y - 4,
            width=layout.grid_width + 8,
            height=layout.grid_height + 8,
            radius=6,
        )
        wrapper = parent.group(clip_path=f"url(#{clip_id})", opacity=_SWEEP_OPACITY)

        band_width = layout.grid_width * 0.22
        band = wrapper.group()
        band.add(
            clock.animate_transform(
                "translate",
                [
                    (0.0, (-band_width * 2.0, 0.0)),
                    (
                        self._max_wave_index * self.config.contribution.wave_step_ms
                        + self.config.contribution.cell_entrance_ms,
                        (layout.grid_width + band_width, 0.0),
                    ),
                ],
                ease=EASE_OUT_QUINT,
            )
        )
        band.child(
            "rect",
            x=layout.grid_x,
            y=layout.grid_y - layout.grid_height,
            width=band_width,
            height=layout.grid_height * 3,
            fill=paint.linear_gradient(
                "grad-sweep",
                (
                    GradientStop(0.0, palette.cyan, 0.0),
                    GradientStop(0.5, lighten(palette.cyan, 0.4), 0.9),
                    GradientStop(1.0, palette.cyan, 0.0),
                ),
            ),
            transform=(
                f"rotate(-32 {layout.grid_x + band_width / 2:.2f} "
                f"{layout.grid_y + layout.grid_height / 2:.2f})"
            ),
        )

    def _draw_legend(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Activity summary on the left, GitHub's Less/More ramp on the right."""
        if not self.config.contribution.show_legend:
            return
        layout = self.layout
        palette = self.config.palette
        fonts = self.config.typography
        settings = self.config.contribution

        group = parent.group(opacity=0)
        appear_at = (
            self._max_wave_index * settings.wave_step_ms + settings.cell_entrance_ms
        )
        group.add(
            clock.animate(
                "opacity",
                [(appear_at * 0.72, 0), (appear_at * 0.72 + 460.0, 1)],
                ease=EASE_OUT_CUBIC,
            )
        )

        baseline = layout.legend_y + settings.label_font_size * 0.36
        summary = (
            f"{self.calendar.active_days} active days"
            f"  ·  {self.calendar.longest_streak()}d longest streak"
            f"  ·  {self.calendar.current_streak()}d current"
        )
        group.add(
            Element(
                "text",
                summary,
                x=layout.grid_x,
                y=baseline,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.label_font_size,
            )
        )

        # --- Less [][][][][] More -----------------------------------------
        ramp_width = len(settings.level_colors) * (_LEGEND_SWATCH + _LEGEND_GAP)
        more_x = layout.width - layout.padding
        ramp_x = more_x - 34.0 - ramp_width
        group.add(
            Element(
                "text",
                "Less",
                x=ramp_x - 6,
                y=baseline,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.label_font_size,
                text_anchor="end",
            )
        )
        for index, color in enumerate(settings.level_colors):
            swatch = group.child(
                "rect",
                x=ramp_x + index * (_LEGEND_SWATCH + _LEGEND_GAP),
                y=layout.legend_y - _LEGEND_SWATCH / 2,
                width=_LEGEND_SWATCH,
                height=_LEGEND_SWATCH,
                rx=settings.corner_radius,
                ry=settings.corner_radius,
                fill=color,
                stroke=settings.empty_cell_stroke if index == 0 else None,
                stroke_width=1 if index == 0 else None,
            )
            if index >= settings.glow_from_level and self._use_glow_filters:
                swatch.set(
                    filter=paint.glow_filter(
                        color, blur=self._glow_blur_for(index), key=f"lv{index}"
                    )
                )
        group.add(
            Element(
                "text",
                "More",
                x=ramp_x + ramp_width + 4,
                y=baseline,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.label_font_size,
            )
        )

    def _draw_border(self, document: SvgDocument) -> None:
        """The card's hairline edge, drawn last so nothing overlaps it."""
        layout = self.layout
        document.child(
            "rect",
            x=0.5,
            y=0.5,
            width=layout.width - 1,
            height=layout.height - 1,
            rx=14,
            ry=14,
            fill="none",
            stroke=self.config.palette.border,
            stroke_width=1,
        )

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        """One-line summary used by the build script."""
        mode = "filters" if self._use_glow_filters else "halos"
        return (
            f"{self.calendar.total:,} contributions · {self.calendar.source} data "
            f"· {self.calendar.glowing_cell_count} glowing cells ({mode})"
        )

"""Generates ``hero-banner.svg`` — the README's animated masthead.

A wide cinematic banner: a parallax grid fading out through a radial mask,
drifting aurora, a twinkling star field, a wordmark lit by a travelling
specular gradient, a self-typing tagline that cycles, and a row of stack chips
that spring in on a stagger.

Every effect here is deliberately cheap.  The grid is one group of lines
transformed as a unit, the shimmer is a single animated ``gradientTransform``
rather than a mask sweep, and the stars share one circle definition — a banner
this wide has to stay light because it is the first thing the page paints.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .base import AssetGenerator
from .colors import lighten, with_alpha
from .config_types import ConfigLike
from .defs import GradientStop, PaintLibrary
from .easing import EASE_IN_OUT_SINE, EASE_OUT_CUBIC, EASE_OUT_EXPO, spring_scale_track
from .svg import Element, SvgDocument
from .timeline import LoopClock

__all__ = ["HeroGenerator", "HeroStats"]

#: Card padding.
_PADDING = 46.0
#: Baseline of the wordmark, measured from the top edge.
_WORDMARK_BASELINE = 132.0
#: Baseline of the typed tagline.
_TAGLINE_BASELINE = 166.0
#: Vertical centre of the chip row.
_CHIP_CENTER_Y = 210.0
#: Chip geometry.
_CHIP_HEIGHT = 24.0
_CHIP_PADDING_X = 11.0
_CHIP_GAP = 8.0
_CHIP_RADIUS = 6.0
#: Eyebrow label above the wordmark.
_EYEBROW_BASELINE = 74.0
_EYEBROW_TEXT = "GITHUB PROFILE"
#: Deletion speed relative to typing speed.
_DELETE_SPEED_RATIO = 0.45
#: Period of the wordmark's specular shimmer sweep.
_SHIMMER_TRAVEL_RATIO = 2.2
#: Opacity of the parallax grid before masking.
_GRID_OPACITY = 0.5
#: Star radius range.
_STAR_MIN_RADIUS = 0.6
_STAR_MAX_RADIUS = 1.5


@dataclass(frozen=True)
class TaglineCue:
    """When one tagline types itself in, rests, and deletes itself again."""

    text: str
    type_start: float
    type_end: float
    delete_start: float
    delete_end: float


@dataclass(frozen=True)
class HeroStats:
    """The handful of live numbers the banner puts on record."""

    repositories: int
    contributions: int
    top_language: str

    def format_line(self) -> str:
        """Render the right-aligned status line."""
        return (
            f"{self.repositories} repos  ·  {self.contributions:,} contributions"
            f"  ·  {self.top_language}"
        )


class HeroGenerator(AssetGenerator):
    """Builds the animated hero banner."""

    filename = "hero-banner.svg"
    display_name = "hero banner"

    def __init__(self, config: ConfigLike, stats: HeroStats) -> None:
        super().__init__(config)
        self.stats = stats
        self._random = random.Random(f"hero::{config.username}")
        self._tagline_schedule = self._build_tagline_schedule()
        self._loop_duration_ms = self._compute_loop_duration()

    # -- timing -------------------------------------------------------------

    def _build_tagline_schedule(self) -> list[TaglineCue]:
        """Lay every tagline out on the timeline, back to back."""
        settings = self.config.hero
        schedule: list[TaglineCue] = []
        cursor = 700.0  # let the wordmark land before anything types
        delete_ms = settings.type_char_ms * _DELETE_SPEED_RATIO

        for text in settings.taglines:
            type_end = cursor + len(text) * settings.type_char_ms
            delete_start = type_end + settings.tagline_hold_ms
            delete_end = delete_start + len(text) * delete_ms
            schedule.append(
                TaglineCue(
                    text=text,
                    type_start=cursor,
                    type_end=type_end,
                    delete_start=delete_start,
                    delete_end=delete_end,
                )
            )
            cursor = delete_end
        return schedule

    def _compute_loop_duration(self) -> float:
        """Every tagline cycle, plus the exit fade."""
        if not self._tagline_schedule:
            return 4000.0
        return self._tagline_schedule[-1].delete_end + self.config.animation.loop_fade_ms

    @property
    def _exit_start_ms(self) -> float:
        """Absolute time at which the composition begins fading out."""
        return self._loop_duration_ms - self.config.animation.loop_fade_ms

    # -- build --------------------------------------------------------------

    def build(self) -> SvgDocument:
        """Assemble the complete hero banner document."""
        settings = self.config.hero
        document, paint = self.new_document(
            settings.width,
            settings.height,
            title=f"{self.config.display_name} — animated profile banner",
            description=self.config.tagline,
        )
        clock = self.new_clock(self._loop_duration_ms)

        self._draw_backdrop(document, paint)
        self._draw_grid(document, paint)
        self._draw_stars(document, paint)

        stage = document.group()
        stage.add(
            clock.animate(
                "opacity",
                [(0.0, 1), (self._exit_start_ms, 1), (self._loop_duration_ms, 0)],
                ease=EASE_IN_OUT_SINE,
            )
        )
        self._draw_eyebrow(stage, clock)
        self._draw_wordmark(stage, paint, clock)
        self._draw_taglines(stage, paint, clock)
        self._draw_chips(stage, paint, clock)
        self._draw_frame(document, paint)
        return document

    # -- layers -------------------------------------------------------------

    def _draw_backdrop(self, document: SvgDocument, paint: PaintLibrary) -> None:
        """Deep gradient plus three slow aurora blobs."""
        settings = self.config.hero
        palette = self.config.palette

        document.child(
            "rect",
            width=settings.width,
            height=settings.height,
            rx=settings.corner_radius,
            ry=settings.corner_radius,
            fill=paint.page_background(settings.width, settings.height),
        )

        clip_id = paint.rounded_clip(
            "clip-hero",
            x=0,
            y=0,
            width=settings.width,
            height=settings.height,
            radius=settings.corner_radius,
        )
        layer = document.group(clip_path=f"url(#{clip_id})")

        blobs = (
            (palette.cyan, 0.14, 0.10, 300.0, 1.0, (54.0, 26.0)),
            (palette.purple, 0.52, 1.02, 340.0, 1.43, (-62.0, -30.0)),
            (palette.orange, 0.92, 0.22, 250.0, 0.87, (36.0, 34.0)),
        )
        for index, (color, fx, fy, radius, scale, drift) in enumerate(blobs):
            blob = layer.group()
            blob.add(
                LoopClock.free_running_transform(
                    "translate",
                    ((0.0, 0.0), drift, (0.0, 0.0)),
                    period_ms=settings.grid_drift_ms * 1.6 * scale,
                    ease=EASE_IN_OUT_SINE,
                )
            )
            blob.child(
                "ellipse",
                cx=settings.width * fx,
                cy=settings.height * fy,
                rx=radius,
                ry=radius * 0.55,
                fill=paint.aurora(color, peak_opacity=0.30),
            )
            blob.add(
                paint.breathing_opacity(
                    low=0.5, high=1.0, period_ms=9000.0 + index * 2300.0
                )
            )

    def _draw_grid(self, document: SvgDocument, paint: PaintLibrary) -> None:
        """A drifting technical grid, faded at the edges by a radial mask."""
        settings = self.config.hero
        palette = self.config.palette
        spacing = settings.grid_spacing

        mask_id = self._define_grid_mask(paint)
        clip_id = paint.rounded_clip(
            "clip-hero",
            x=0,
            y=0,
            width=settings.width,
            height=settings.height,
            radius=settings.corner_radius,
        )

        wrapper = document.group(
            clip_path=f"url(#{clip_id})",
            mask=f"url(#{mask_id})",
            opacity=_GRID_OPACITY,
        )
        drifting = wrapper.group()
        drifting.add(
            LoopClock.free_running_transform(
                "translate",
                ((0.0, 0.0), (spacing, spacing * 0.5), (0.0, 0.0)),
                period_ms=settings.grid_drift_ms,
                ease=EASE_IN_OUT_SINE,
            )
        )

        stroke = with_alpha(palette.cyan, 0.10)
        columns = int(settings.width / spacing) + 3
        rows = int(settings.height / spacing) + 3
        for index in range(columns):
            x = -spacing + index * spacing
            drifting.child(
                "line",
                x1=x,
                y1=-spacing,
                x2=x,
                y2=settings.height + spacing,
                stroke=stroke,
                stroke_width=1,
            )
        for index in range(rows):
            y = -spacing + index * spacing
            drifting.child(
                "line",
                x1=-spacing,
                y1=y,
                x2=settings.width + spacing,
                y2=y,
                stroke=stroke,
                stroke_width=1,
            )

    def _define_grid_mask(self, paint: PaintLibrary) -> str:
        """A radial luminance mask that dissolves the grid toward the edges."""
        settings = self.config.hero
        gradient = paint.radial_gradient(
            "grad-grid-mask",
            (
                GradientStop(0.0, "#ffffff", 0.95),
                GradientStop(0.55, "#ffffff", 0.35),
                GradientStop(1.0, "#000000", 0.0),
            ),
            cx=settings.width * 0.30,
            cy=settings.height * 0.5,
            r=settings.width * 0.62,
            units="userSpaceOnUse",
        )

        def factory() -> Element:
            mask = Element("mask", maskUnits="userSpaceOnUse")
            mask.set(x=0, y=0, width=settings.width, height=settings.height)
            mask.child(
                "rect",
                width=settings.width,
                height=settings.height,
                fill=gradient,
            )
            return mask

        return paint.register("mask-hero-grid", factory)

    def _draw_stars(self, document: SvgDocument, paint: PaintLibrary) -> None:
        """A sparse twinkling star field, seeded deterministically."""
        settings = self.config.hero
        palette = self.config.palette

        clip_id = paint.rounded_clip(
            "clip-hero",
            x=0,
            y=0,
            width=settings.width,
            height=settings.height,
            radius=settings.corner_radius,
        )
        field = document.group(clip_path=f"url(#{clip_id})")
        colors = (palette.white, palette.cyan, palette.purple)

        for index in range(settings.star_count):
            star = field.child(
                "circle",
                cx=self._random.uniform(0, settings.width),
                cy=self._random.uniform(0, settings.height),
                r=self._random.uniform(_STAR_MIN_RADIUS, _STAR_MAX_RADIUS),
                fill=colors[index % len(colors)],
                opacity=0.0,
            )
            star.add(
                LoopClock.free_running(
                    "opacity",
                    (
                        self._random.uniform(0.05, 0.25),
                        self._random.uniform(0.45, 0.9),
                        self._random.uniform(0.05, 0.25),
                    ),
                    period_ms=self._random.uniform(2400.0, 7200.0),
                )
            )

    def _draw_eyebrow(self, parent: Element, clock: LoopClock) -> None:
        """The small caps label and the right-aligned live stats line."""
        settings = self.config.hero
        palette = self.config.palette
        fonts = self.config.typography

        group = parent.group(opacity=0)
        group.add(
            clock.animate("opacity", [(120.0, 0), (620.0, 1)], ease=EASE_OUT_CUBIC)
        )
        group.add(
            Element(
                "text",
                _EYEBROW_TEXT,
                x=_PADDING,
                y=_EYEBROW_BASELINE,
                fill=palette.cyan,
                font_family=fonts.mono,
                font_size=settings.tag_font_size,
                font_weight="600",
                letter_spacing="3.4",
                opacity=0.85,
            )
        )
        group.add(
            Element(
                "text",
                self.stats.format_line(),
                x=settings.width - _PADDING,
                y=_EYEBROW_BASELINE,
                fill=palette.text_muted,
                font_family=fonts.mono,
                font_size=settings.tag_font_size,
                text_anchor="end",
            )
        )

    def _draw_wordmark(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """The username, lit by a specular gradient travelling across it."""
        settings = self.config.hero
        palette = self.config.palette
        fonts = self.config.typography

        shimmer_id = self._define_shimmer(paint)

        group = parent.group(opacity=0)
        group.add(
            clock.animate("opacity", [(180.0, 0), (760.0, 1)], ease=EASE_OUT_EXPO)
        )
        group.add(
            clock.animate_transform(
                "translate",
                [(180.0, (-18.0, 0.0)), (900.0, (0.0, 0.0))],
                ease=EASE_OUT_EXPO,
            )
        )

        group.add(
            Element(
                "text",
                "@",
                x=_PADDING,
                y=_WORDMARK_BASELINE,
                fill=with_alpha(palette.cyan, 0.7),
                font_family=fonts.sans,
                font_size=settings.title_font_size * 0.62,
                font_weight="600",
            )
        )
        group.add(
            Element(
                "text",
                self.config.display_name,
                x=_PADDING + settings.title_font_size * 0.44,
                y=_WORDMARK_BASELINE,
                fill=f"url(#{shimmer_id})",
                font_family=fonts.sans,
                font_size=settings.title_font_size,
                font_weight="800",
                letter_spacing="-1.6",
            )
        )

    def _define_shimmer(self, paint: PaintLibrary) -> str:
        """A wide gradient whose transform sweeps a white highlight across."""
        settings = self.config.hero
        palette = self.config.palette
        span = settings.width * 0.55

        def factory() -> Element:
            gradient = Element(
                "linearGradient",
                gradientUnits="userSpaceOnUse",
                x1=-span,
                y1=0,
                x2=0,
                y2=0,
            )
            for stop in (
                GradientStop(0.0, palette.text_primary),
                GradientStop(0.34, palette.cyan),
                GradientStop(0.5, lighten(palette.cyan, 0.72)),
                GradientStop(0.66, palette.purple),
                GradientStop(1.0, palette.text_primary),
            ):
                gradient.add(stop.to_element())
            gradient.add(
                LoopClock.free_running_transform(
                    "translate",
                    ((0.0, 0.0), (span * _SHIMMER_TRAVEL_RATIO, 0.0)),
                    period_ms=settings.sweep_period_ms,
                )
            )
            return gradient

        return paint.register("grad-hero-shimmer", factory)

    def _draw_taglines(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Cycle the taglines with a character-quantised typewriter."""
        settings = self.config.hero
        palette = self.config.palette
        fonts = self.config.typography
        advance = settings.subtitle_font_size * self.config.typography.mono_advance_ratio
        delete_ms = settings.type_char_ms * _DELETE_SPEED_RATIO

        group = parent.group()
        for index, cue in enumerate(self._tagline_schedule):
            clip_id = self._define_tagline_clip(
                paint, clock, index=index, cue=cue, advance=advance, delete_ms=delete_ms
            )
            line = group.group(clip_path=f"url(#{clip_id})")
            line.add(
                Element(
                    "text",
                    cue.text,
                    x=_PADDING,
                    y=_TAGLINE_BASELINE,
                    fill=palette.text_secondary,
                    font_family=fonts.mono,
                    font_size=settings.subtitle_font_size,
                    textLength=advance * len(cue.text),
                    lengthAdjust="spacing",
                ).set_raw({"xml:space": "preserve"})
            )

        # The caret that follows the text as it types and deletes.
        caret = parent.group()
        caret_frames: list[tuple[float, tuple[float, float]]] = []
        for cue in self._tagline_schedule:
            end_x = _PADDING + advance * len(cue.text)
            caret_frames.append((cue.type_start, (_PADDING, 0.0)))
            caret_frames.append((cue.type_end, (end_x, 0.0)))
            caret_frames.append((cue.delete_start, (end_x, 0.0)))
            caret_frames.append((cue.delete_end, (_PADDING, 0.0)))
        if caret_frames:
            caret.add(
                clock.animate_transform("translate", caret_frames, ease=EASE_IN_OUT_SINE)
            )
        caret_rect = caret.child(
            "rect",
            x=2,
            y=_TAGLINE_BASELINE - settings.subtitle_font_size * 0.88,
            width=advance * 0.86,
            height=settings.subtitle_font_size * 1.1,
            rx=1,
            ry=1,
            fill=palette.cyan,
        )
        caret_rect.add(
            LoopClock.free_running(
                "opacity",
                (1, 0, 1),
                period_ms=self.config.animation.cursor_blink_ms,
                discrete=True,
                key_times=(0.0, 0.5, 1.0),
            )
        )

    def _define_tagline_clip(
        self,
        paint: PaintLibrary,
        clock: LoopClock,
        *,
        index: int,
        cue: TaglineCue,
        advance: float,
        delete_ms: float,
    ) -> str:
        """Type a tagline in, hold it, then delete it — one character at a time."""
        settings = self.config.hero
        length = len(cue.text)

        def factory() -> Element:
            clip = Element("clipPath", clipPathUnits="userSpaceOnUse")
            rect = clip.child(
                "rect",
                x=_PADDING,
                y=_TAGLINE_BASELINE - settings.subtitle_font_size * 1.2,
                width=0,
                height=settings.subtitle_font_size * 1.7,
            )
            frames: list[tuple[float, float]] = [
                (cue.type_start + step * settings.type_char_ms, advance * step)
                for step in range(length + 1)
            ]
            frames += [
                (cue.delete_start + step * delete_ms, advance * (length - step))
                for step in range(1, length + 1)
            ]
            rect.add(clock.animate("width", frames, discrete=True))
            return clip

        return paint.register(f"clip-tagline-{index}", factory)

    def _draw_chips(
        self, parent: Element, paint: PaintLibrary, clock: LoopClock
    ) -> None:
        """Spring the technology chips in along the bottom edge."""
        settings = self.config.hero
        palette = self.config.palette
        fonts = self.config.typography
        accents = self.config.accent_cycle

        font_size = settings.tag_font_size
        advance = font_size * self.config.typography.mono_advance_ratio

        row = parent.group()
        cursor_x = _PADDING
        for index, label in enumerate(settings.chips):
            text_width = advance * len(label)
            chip_width = text_width + _CHIP_PADDING_X * 2
            accent = accents[index % len(accents)]
            delay = 420.0 + index * 70.0

            centre_x = cursor_x + chip_width / 2
            anchored = row.group(
                transform=f"translate({centre_x:.2f},{_CHIP_CENTER_Y:.2f})", opacity=0
            )
            anchored.add(
                clock.animate(
                    "opacity", [(delay, 0), (delay + 260.0, 1)], ease=EASE_OUT_CUBIC
                )
            )
            scale_frames, scale_eases = spring_scale_track(
                420.0,
                overshoot=self.config.animation.spring_overshoot,
                undershoot=self.config.animation.spring_undershoot,
                start=0.72,
            )
            chip = anchored.group()
            chip.add(
                clock.animate_transform(
                    "scale",
                    [(delay + time, value) for time, value in scale_frames],
                    ease=scale_eases,
                )
            )

            chip.child(
                "rect",
                x=-chip_width / 2,
                y=-_CHIP_HEIGHT / 2,
                width=chip_width,
                height=_CHIP_HEIGHT,
                rx=_CHIP_RADIUS,
                ry=_CHIP_RADIUS,
                fill=with_alpha(accent, 0.10),
                stroke=with_alpha(accent, 0.34),
                stroke_width=1,
            )
            chip.add(
                Element(
                    "text",
                    label,
                    x=0,
                    y=font_size * 0.36,
                    fill=accent,
                    font_family=fonts.mono,
                    font_size=font_size,
                    text_anchor="middle",
                    letter_spacing="0.2",
                )
            )
            cursor_x += chip_width + _CHIP_GAP

        # A soft accent rule anchoring the composition's bottom edge.
        row.child(
            "rect",
            x=_PADDING,
            y=settings.height - 1,
            width=settings.width - _PADDING * 2,
            height=1,
            fill=paint.accent_rule(settings.width - _PADDING * 2),
            opacity=0.6,
        )

    def _draw_frame(self, document: SvgDocument, paint: PaintLibrary) -> None:
        """Vignette, grain and the hairline border."""
        settings = self.config.hero
        clip_id = paint.rounded_clip(
            "clip-hero",
            x=0,
            y=0,
            width=settings.width,
            height=settings.height,
            radius=settings.corner_radius,
        )
        overlay = document.group(clip_path=f"url(#{clip_id})")
        overlay.child(
            "rect",
            width=settings.width,
            height=settings.height,
            fill=paint.vignette(settings.width, settings.height),
        )
        overlay.child(
            "rect",
            width=settings.width,
            height=settings.height,
            filter=paint.film_grain(),
            opacity=0.6,
        )
        document.child(
            "rect",
            x=0.5,
            y=0.5,
            width=settings.width - 1,
            height=settings.height - 1,
            rx=settings.corner_radius,
            ry=settings.corner_radius,
            fill="none",
            stroke=self.config.palette.border,
            stroke_width=1,
        )

    # -- reporting ----------------------------------------------------------

    def describe(self) -> str:
        """One-line summary used by the build script."""
        return (
            f"{len(self.config.hero.taglines)} taglines · "
            f"{len(self.config.hero.chips)} chips · "
            f"{self.config.hero.width:.0f}x{self.config.hero.height:.0f}px"
        )

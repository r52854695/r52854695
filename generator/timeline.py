"""Absolute-time authoring on top of SMIL's fraction-based keyframes.

Every asset in this project is a *single* looping composition: hundreds of
independent elements that must stay frame-accurate relative to one another,
forever, without a line of JavaScript.

SMIL cannot express that directly — each ``<animate>`` has its own ``dur`` and
its ``keyTimes`` are fractions of that duration.  Chaining animations with
``begin="other.end"`` works but drifts and is brittle across renderers.

:class:`LoopClock` removes the problem entirely.  Every animation in a document
shares one ``dur`` (the loop length) and ``repeatCount="indefinite"``; the clock
converts the millisecond timings the generators actually think in into
fractions of that shared loop.  The result is a composition that is
sample-accurate on every renderer and restarts seamlessly.
"""

from __future__ import annotations

from typing import Any, Sequence

from .easing import LINEAR, Ease
from .svg import Element, format_number

__all__ = ["LoopClock", "Keyframes"]

#: ``keyTimes`` are emitted with this many decimals.  On a ten-second loop that
#: is a 0.1ms resolution — far below the threshold of perception, and several
#: characters per keyframe cheaper than full float precision across the several
#: thousand keyframes a contribution calendar carries.
_TIME_PRECISION = 5

#: The number of representable steps in ``[0, 1]`` at that precision.
#: Monotonicity is enforced on these integer steps rather than on floats: the
#: alternative — nudging floats by an epsilon finer than the output precision —
#: silently collapses back into a duplicate keyTime when the value is rounded
#: for serialisation, and SMIL drops the whole animation without a word.
_TIME_STEPS = 10**_TIME_PRECISION

#: Smallest representable gap between two consecutive ``keyTimes``.
_MIN_TIME_DELTA = 1.0 / _TIME_STEPS

#: Decimals kept in interpolated values.  Coordinates are user units, so this
#: is a thousandth of a pixel.
_VALUE_PRECISION = 3

#: A frame is ``(milliseconds, value)``; the value may be a scalar or a tuple
#: (for ``translate``/``scale`` pairs) or a pre-formatted string.
Keyframes = Sequence[tuple[float, Any]]


def _format_animation_value(value: Any) -> str:
    """Render one keyframe value into its SMIL ``values`` list entry."""
    if isinstance(value, (int, float)):
        return format_number(float(value), _VALUE_PRECISION)
    if isinstance(value, (tuple, list)):
        return " ".join(_format_animation_value(item) for item in value)
    return str(value)


class LoopClock:
    """Maps absolute milliseconds onto one shared, indefinitely repeating loop.

    Args:
        duration_ms: Length of one full loop at 1.0x speed.
        speed: Wall-clock multiplier.  ``2.0`` plays the same composition twice
            as fast; all authored timings stay unchanged.

    Attributes:
        duration_ms: The authored (unscaled) loop length.
    """

    __slots__ = ("duration_ms", "_speed")

    def __init__(self, duration_ms: float, *, speed: float = 1.0) -> None:
        if duration_ms <= 0:
            raise ValueError("LoopClock duration must be positive")
        if speed <= 0:
            raise ValueError("LoopClock speed must be positive")
        self.duration_ms = float(duration_ms)
        self._speed = float(speed)

    # -- basics -------------------------------------------------------------

    @property
    def duration_attribute(self) -> str:
        """The ``dur`` attribute shared by every animation on this clock."""
        return self.scaled_seconds(self.duration_ms)

    def fraction(self, milliseconds: float) -> float:
        """Convert an absolute time into a loop fraction in ``[0, 1]``."""
        return max(0.0, min(1.0, milliseconds / self.duration_ms))

    def scaled_seconds(self, milliseconds: float) -> str:
        """Render ``milliseconds`` as a speed-adjusted SMIL clock value."""
        seconds = milliseconds / self._speed / 1000.0
        text = f"{seconds:.4f}".rstrip("0").rstrip(".")
        return f"{text or '0'}s"

    # -- animation factories ------------------------------------------------

    def animate(
        self,
        attribute_name: str,
        frames: Keyframes,
        *,
        ease: Ease | Sequence[Ease] = LINEAR,
        transform_type: str | None = None,
        discrete: bool = False,
        additive: str | None = None,
        accumulate: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Element:
        """Build one looping ``<animate>`` / ``<animateTransform>`` element.

        Frames are authored in absolute milliseconds; the clock pads the head
        and tail so the value simply holds before the first and after the last
        keyframe, which is what makes independent elements composable.

        Args:
            attribute_name: SVG attribute to drive (ignored for transforms,
                where ``"transform"`` is implied).
            frames: ``(milliseconds, value)`` pairs, in any order.
            ease: One :class:`~generator.easing.Ease` applied to every segment,
                or a sequence with exactly ``len(frames) - 1`` entries.
            transform_type: ``"translate"``, ``"scale"``, ``"rotate"`` … .  When
                given, an ``<animateTransform>`` is emitted.
            discrete: Emit ``calcMode="discrete"`` for hard, non-interpolated
                steps (cursor row jumps, character-quantised typing).
            additive: SMIL ``additive`` attribute, typically ``"sum"`` when
                stacking a second transform on the same element.
            accumulate: SMIL ``accumulate`` attribute.
            extra: Any further raw attributes to merge in.

        Returns:
            The configured animation :class:`~generator.svg.Element`.
        """
        times, values, eases = self._prepare(frames, ease, discrete)

        tag = "animateTransform" if transform_type else "animate"
        element = Element(tag)
        element.set(
            attributeName="transform" if transform_type else attribute_name,
            type=transform_type,
            values=";".join(values),
            keyTimes=";".join(self._format_time(t) for t in times),
            dur=self.duration_attribute,
            repeatCount="indefinite",
            additive=additive,
            accumulate=accumulate,
        )
        if discrete:
            element.set(calcMode="discrete")
        else:
            element.set(
                calcMode="spline",
                keySplines=";".join(item.to_spline() for item in eases),
            )
        if extra:
            element.set_raw(extra)
        return element

    def animate_transform(
        self,
        transform_type: str,
        frames: Keyframes,
        *,
        ease: Ease | Sequence[Ease] = LINEAR,
        additive: str | None = None,
        discrete: bool = False,
    ) -> Element:
        """Convenience wrapper around :meth:`animate` for transforms."""
        return self.animate(
            "transform",
            frames,
            ease=ease,
            transform_type=transform_type,
            additive=additive,
            discrete=discrete,
        )

    def fade(
        self,
        frames: Keyframes,
        *,
        ease: Ease | Sequence[Ease] = LINEAR,
    ) -> Element:
        """Convenience wrapper for opacity animation."""
        return self.animate("opacity", frames, ease=ease)

    def pulse(
        self,
        attribute_name: str,
        *,
        start_ms: float,
        rise_ms: float,
        fall_ms: float,
        peak: float,
        rest: float = 0.0,
        ease: Ease | Sequence[Ease] = LINEAR,
    ) -> Element:
        """Build a short rise-and-decay pulse — the specular glint primitive.

        Args:
            attribute_name: Attribute to pulse, usually ``"opacity"``.
            start_ms: Absolute time at which the pulse begins.
            rise_ms: Time from ``rest`` to ``peak``.
            fall_ms: Time from ``peak`` back to ``rest``.
            peak: Value at the top of the pulse.
            rest: Value held before and after the pulse.
            ease: Easing applied to both the rise and the decay.
        """
        frames = [
            (start_ms, rest),
            (start_ms + rise_ms, peak),
            (start_ms + rise_ms + fall_ms, rest),
        ]
        return self.animate(attribute_name, frames, ease=ease)

    def gate(self, *, visible_from_ms: float, visible_to_ms: float) -> Element:
        """Hard-switch opacity on for a window and off outside it.

        Used to hand control of an attribute between the global composition and
        a free-running child animation (for example a blinking cursor that only
        exists during the prompt phase).
        """
        frames: list[tuple[float, Any]] = []
        if visible_from_ms <= 0.0:
            frames.append((0.0, 1))
        else:
            frames.append((0.0, 0))
            frames.append((visible_from_ms, 1))
        if visible_to_ms < self.duration_ms:
            frames.append((visible_to_ms, 1))
            frames.append((min(visible_to_ms + 1.0, self.duration_ms), 0))
        return self.animate("opacity", frames, discrete=True)

    @staticmethod
    def free_running_transform(
        transform_type: str,
        values: Sequence[Any],
        *,
        period_ms: float,
        ease: Ease | None = None,
    ) -> Element:
        """Build an ``<animateTransform>`` on its own period.

        The ``transform`` attribute may only be animated by
        ``<animateTransform>``; this is the transform-flavoured counterpart to
        :meth:`free_running` and exists so ambient drift never accidentally
        emits an invalid ``<animate attributeName="transform">``.

        Args:
            transform_type: ``"translate"``, ``"scale"``, ``"rotate"`` … .
            values: Ordered keyframe values; tuples are joined with spaces.
            period_ms: Length of one cycle.
            ease: Optional easing applied uniformly to every segment.
        """
        element = Element("animateTransform")
        element.set(
            attributeName="transform",
            type=transform_type,
            values=";".join(_format_animation_value(value) for value in values),
            dur=f"{period_ms / 1000.0:.4f}s",
            repeatCount="indefinite",
        )
        if ease is not None:
            element.set(
                calcMode="spline",
                keySplines=";".join([ease.to_spline()] * (len(values) - 1)),
            )
        return element

    @staticmethod
    def free_running(
        attribute_name: str,
        values: Sequence[Any],
        *,
        period_ms: float,
        discrete: bool = False,
        key_times: Sequence[float] | None = None,
    ) -> Element:
        """Build an animation on its **own** period, independent of the loop.

        Reserved for genuinely aperiodic ambience — a cursor blink whose rhythm
        should not be quantised to the composition length.

        Args:
            attribute_name: Attribute to drive.
            values: Ordered keyframe values.
            period_ms: Length of one cycle.
            discrete: Emit ``calcMode="discrete"``.
            key_times: Optional explicit fractions; defaults to even spacing.
        """
        element = Element("animate")
        element.set(
            attributeName=attribute_name,
            values=";".join(_format_animation_value(value) for value in values),
            dur=f"{period_ms / 1000.0:.4f}s",
            repeatCount="indefinite",
        )
        if key_times is not None:
            element.set(keyTimes=";".join(f"{t:.4g}" for t in key_times))
        if discrete:
            element.set(calcMode="discrete")
        return element

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _format_time(fraction: float) -> str:
        text = f"{fraction:.{_TIME_PRECISION}f}"
        return text.rstrip("0").rstrip(".") or "0"

    def _prepare(
        self,
        frames: Keyframes,
        ease: Ease | Sequence[Ease],
        discrete: bool,
    ) -> tuple[list[float], list[str], list[Ease]]:
        """Sort, validate, pad and normalise an authored keyframe list."""
        if not frames:
            raise ValueError("an animation needs at least one keyframe")

        ordered = sorted(frames, key=lambda frame: frame[0])
        first_time = ordered[0][0]
        last_time = ordered[-1][0]
        if first_time < -_MIN_TIME_DELTA:
            raise ValueError(f"keyframe at {first_time}ms precedes the loop start")
        if last_time > self.duration_ms + _MIN_TIME_DELTA:
            raise ValueError(
                f"keyframe at {last_time}ms overruns the {self.duration_ms}ms loop"
            )

        per_segment = self._expand_eases(ease, len(ordered) - 1)

        # Hold the first value from t=0 and the last value until t=duration so
        # that callers only ever describe the interesting part of the timeline.
        if first_time > _MIN_TIME_DELTA:
            ordered.insert(0, (0.0, ordered[0][1]))
            per_segment.insert(0, LINEAR)
        if last_time < self.duration_ms - _MIN_TIME_DELTA:
            ordered.append((self.duration_ms, ordered[-1][1]))
            per_segment.append(LINEAR)

        steps = [
            round(self.fraction(time) * _TIME_STEPS) for time, _ in ordered
        ]
        values = [_format_animation_value(value) for _, value in ordered]
        times = self._resolve_key_times(steps)

        if len(per_segment) != len(values) - 1:  # pragma: no cover - guard
            raise AssertionError("easing/segment count mismatch")
        return times, values, per_segment

    @staticmethod
    def _expand_eases(ease: Ease | Sequence[Ease], segments: int) -> list[Ease]:
        """Normalise the ``ease`` argument into one entry per segment."""
        if isinstance(ease, Ease):
            return [ease] * max(segments, 0)
        expanded = list(ease)
        if len(expanded) != segments:
            raise ValueError(
                f"expected {segments} easing curves for {segments + 1} keyframes, "
                f"got {len(expanded)}"
            )
        return expanded

    @staticmethod
    def _resolve_key_times(steps: list[int]) -> list[float]:
        """Turn quantised times into a strictly increasing ``keyTimes`` list.

        Two keyframes may legitimately land on the same millisecond — an
        instantaneous cursor carriage return, for instance.  SMIL rejects
        duplicate times, so coincident entries are pushed apart by exactly one
        representable step, which survives serialisation intact.

        Args:
            steps: Times quantised to :data:`_TIME_STEPS` subdivisions.

        Returns:
            Fractions in ``[0, 1]``, first exactly ``0`` and last exactly ``1``.

        Raises:
            ValueError: If separating the keyframes would push the last one
                past the end of the loop, meaning the composition is over-packed.
        """
        resolved = [max(0, min(_TIME_STEPS, steps[0]))]
        for step in steps[1:]:
            resolved.append(max(step, resolved[-1] + 1))
        if resolved[-1] > _TIME_STEPS:
            raise ValueError(
                f"keyframes are too densely packed for the loop: "
                f"{len(steps)} frames need more than {_TIME_STEPS} time steps. "
                "Lengthen the loop or reduce the number of keyframes."
            )
        resolved[0] = 0
        resolved[-1] = _TIME_STEPS
        return [step / _TIME_STEPS for step in resolved]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LoopClock {self.duration_ms:.0f}ms @{self._speed}x>"

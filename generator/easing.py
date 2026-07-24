"""Easing curves and spring solvers used by every animated asset.

SMIL expresses easing through ``calcMode="spline"`` plus a ``keySplines`` list
of cubic Bezier control points — exactly the same parametrisation as CSS
``cubic-bezier()``.  This module names the curves we care about so that motion
intent reads clearly at the call site (``ease=EASE_OUT_EXPO``) instead of as an
anonymous quadruple of floats.

The spring helpers do not solve a differential equation at runtime; they bake a
critically-damped response into a handful of keyframes, which keeps the emitted
SVG small while still reading as physical rather than robotic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "Ease",
    "LINEAR",
    "EASE_IN_OUT_SINE",
    "EASE_OUT_QUAD",
    "EASE_OUT_CUBIC",
    "EASE_OUT_QUINT",
    "EASE_OUT_EXPO",
    "EASE_OUT_BACK",
    "EASE_IN_OUT_EXPO",
    "EASE_IN_QUAD",
    "EASE_OUT_CIRC",
    "spring_scale_track",
    "spring_offset_track",
]


@dataclass(frozen=True)
class Ease:
    """A named cubic Bezier timing function.

    Attributes:
        name: Human readable label, used only for debugging.
        control_points: ``(x1, y1, x2, y2)`` in the SMIL ``keySplines`` order.
    """

    name: str
    control_points: tuple[float, float, float, float]

    def to_spline(self) -> str:
        """Render the curve as one ``keySplines`` entry."""
        return " ".join(f"{value:.4g}" for value in self.control_points)


LINEAR: Final[Ease] = Ease("linear", (0.0, 0.0, 1.0, 1.0))
EASE_IN_QUAD: Final[Ease] = Ease("ease-in-quad", (0.55, 0.085, 0.68, 0.53))
EASE_OUT_QUAD: Final[Ease] = Ease("ease-out-quad", (0.25, 0.46, 0.45, 0.94))
EASE_OUT_CUBIC: Final[Ease] = Ease("ease-out-cubic", (0.215, 0.61, 0.355, 1.0))
EASE_OUT_QUINT: Final[Ease] = Ease("ease-out-quint", (0.23, 1.0, 0.32, 1.0))
EASE_OUT_EXPO: Final[Ease] = Ease("ease-out-expo", (0.16, 1.0, 0.3, 1.0))
EASE_OUT_CIRC: Final[Ease] = Ease("ease-out-circ", (0.075, 0.82, 0.165, 1.0))
EASE_OUT_BACK: Final[Ease] = Ease("ease-out-back", (0.34, 1.56, 0.64, 1.0))
EASE_IN_OUT_SINE: Final[Ease] = Ease("ease-in-out-sine", (0.445, 0.05, 0.55, 0.95))
EASE_IN_OUT_EXPO: Final[Ease] = Ease("ease-in-out-expo", (0.87, 0.0, 0.13, 1.0))


def spring_scale_track(
    duration_ms: float,
    *,
    overshoot: float,
    undershoot: float,
    start: float = 0.0,
) -> tuple[list[tuple[float, float]], list[Ease]]:
    """Bake a springy 0 -> 1 scale response into four keyframes.

    The response rises fast, overshoots, dips just below unity and settles.
    Returning the per-segment easing alongside the keyframes lets the caller
    hand both straight to :meth:`generator.timeline.LoopClock.animate`.

    Args:
        duration_ms: Total settle time of the spring.
        overshoot: Peak scale, e.g. ``1.14``.
        undershoot: Scale at the rebound trough, e.g. ``0.97``.
        start: Initial scale, normally ``0``.

    Returns:
        ``(frames, eases)`` where ``frames`` is a list of ``(offset_ms, value)``
        offsets relative to the spring's own start, and ``eases`` has exactly
        ``len(frames) - 1`` entries.
    """
    peak_at = duration_ms * 0.42
    trough_at = duration_ms * 0.72
    frames = [
        (0.0, start),
        (peak_at, overshoot),
        (trough_at, undershoot),
        (duration_ms, 1.0),
    ]
    eases = [EASE_OUT_EXPO, EASE_IN_OUT_SINE, EASE_OUT_CUBIC]
    return frames, eases


def spring_offset_track(
    duration_ms: float,
    offset: tuple[float, float],
    *,
    overshoot_ratio: float = -0.12,
) -> tuple[list[tuple[float, tuple[float, float]]], list[Ease]]:
    """Bake a springy translation from ``offset`` back to the origin.

    The element slightly overshoots past its resting position before settling,
    which is what separates a spring from a plain ease-out.

    Args:
        duration_ms: Total settle time.
        offset: Starting ``(dx, dy)`` displacement in user units.
        overshoot_ratio: Fraction of ``offset`` to travel *past* the origin.

    Returns:
        ``(frames, eases)`` in the same shape as :func:`spring_scale_track`.
    """
    dx, dy = offset
    past = (dx * overshoot_ratio, dy * overshoot_ratio)
    frames = [
        (0.0, (dx, dy)),
        (duration_ms * 0.55, past),
        (duration_ms, (0.0, 0.0)),
    ]
    eases = [EASE_OUT_EXPO, EASE_OUT_CUBIC]
    return frames, eases

"""Tests for the SMIL loop clock.

These assert the invariants a renderer enforces *silently*: an animation whose
``keyTimes`` are malformed is dropped without any error, so the only place the
mistake can be caught is here.
"""

from __future__ import annotations

import unittest

from generator.easing import EASE_OUT_EXPO, LINEAR
from generator.timeline import LoopClock


def key_times(element) -> list[float]:
    """Parse an animation element's ``keyTimes`` into floats."""
    return [float(part) for part in element.attributes["keyTimes"].split(";")]


def values(element) -> list[str]:
    """Parse an animation element's ``values`` list."""
    return element.attributes["values"].split(";")


class DurationTests(unittest.TestCase):
    """The shared ``dur`` is the only thing the speed multiplier touches."""

    def test_duration_is_rendered_in_seconds(self) -> None:
        self.assertEqual(LoopClock(5150).duration_attribute, "5.15s")

    def test_speed_scales_the_duration_only(self) -> None:
        clock = LoopClock(4000, speed=2.0)
        self.assertEqual(clock.duration_attribute, "2s")
        # Authored timings stay in unscaled milliseconds.
        self.assertAlmostEqual(clock.fraction(2000), 0.5)

    def test_invalid_arguments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LoopClock(0)
        with self.assertRaises(ValueError):
            LoopClock(1000, speed=0)


class KeyTimeTests(unittest.TestCase):
    """Every emitted animation must satisfy the SMIL ordering rules."""

    def setUp(self) -> None:
        self.clock = LoopClock(1000)

    def test_key_times_span_the_whole_loop(self) -> None:
        animation = self.clock.animate("opacity", [(200, 0), (400, 1)])
        times = key_times(animation)
        self.assertEqual(times[0], 0.0)
        self.assertEqual(times[-1], 1.0)

    def test_head_and_tail_values_are_held(self) -> None:
        animation = self.clock.animate("opacity", [(200, 0), (400, 1)])
        self.assertEqual(values(animation), ["0", "0", "1", "1"])

    def test_key_times_strictly_increase(self) -> None:
        animation = self.clock.animate("opacity", [(200, 0), (400, 1)])
        times = key_times(animation)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_coincident_frames_survive_serialisation(self) -> None:
        # Regression: separating duplicate times by an epsilon finer than the
        # output precision let them collapse back together when rounded, which
        # silently invalidated the whole animation.
        animation = self.clock.animate(
            "opacity", [(100, 0), (500, 1), (500, 0), (900, 1)]
        )
        times = key_times(animation)
        self.assertEqual(len(times), len(values(animation)))
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_many_coincident_frames_still_increase(self) -> None:
        frames = [(500.0, index) for index in range(12)]
        times = key_times(self.clock.animate("opacity", frames))
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_frames_are_sorted_by_time(self) -> None:
        animation = self.clock.animate("opacity", [(600, 1), (200, 0)])
        self.assertEqual(values(animation), ["0", "0", "1", "1"])

    def test_overrunning_the_loop_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            self.clock.animate("opacity", [(0, 0), (1500, 1)])

    def test_overpacking_the_loop_is_an_error(self) -> None:
        clock = LoopClock(1000)
        with self.assertRaises(ValueError):
            clock.animate("opacity", [(500.0, index) for index in range(200_000)])


class SplineTests(unittest.TestCase):
    """``keySplines`` must always pair with the segment count."""

    def setUp(self) -> None:
        self.clock = LoopClock(1000)

    def test_one_spline_per_segment(self) -> None:
        animation = self.clock.animate("opacity", [(0, 0), (500, 1), (1000, 0)])
        splines = animation.attributes["keySplines"].split(";")
        self.assertEqual(len(splines), len(values(animation)) - 1)

    def test_a_single_ease_is_broadcast(self) -> None:
        animation = self.clock.animate(
            "opacity", [(0, 0), (500, 1), (1000, 0)], ease=EASE_OUT_EXPO
        )
        self.assertEqual(
            animation.attributes["keySplines"].split(";"),
            [EASE_OUT_EXPO.to_spline()] * 2,
        )

    def test_padding_segments_use_linear_easing(self) -> None:
        animation = self.clock.animate(
            "opacity", [(200, 0), (400, 1)], ease=EASE_OUT_EXPO
        )
        splines = animation.attributes["keySplines"].split(";")
        self.assertEqual(splines[0], LINEAR.to_spline())
        self.assertEqual(splines[1], EASE_OUT_EXPO.to_spline())
        self.assertEqual(splines[2], LINEAR.to_spline())

    def test_mismatched_ease_sequence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.clock.animate(
                "opacity", [(0, 0), (500, 1), (1000, 0)], ease=[EASE_OUT_EXPO]
            )

    def test_discrete_mode_omits_splines(self) -> None:
        animation = self.clock.animate("width", [(0, 0), (500, 10)], discrete=True)
        self.assertEqual(animation.attributes["calcMode"], "discrete")
        self.assertNotIn("keySplines", animation.attributes)


class TransformTests(unittest.TestCase):
    """Transforms need their own element type and value shape."""

    def setUp(self) -> None:
        self.clock = LoopClock(1000)

    def test_transform_emits_animate_transform(self) -> None:
        animation = self.clock.animate_transform(
            "translate", [(0, (0.0, 0.0)), (500, (10.0, 20.0))]
        )
        self.assertEqual(animation.tag, "animateTransform")
        self.assertEqual(animation.attributes["type"], "translate")
        self.assertEqual(animation.attributes["attributeName"], "transform")

    def test_tuple_values_join_with_spaces(self) -> None:
        animation = self.clock.animate_transform(
            "translate", [(0, (1.5, 2.5)), (1000, (3.0, 4.0))]
        )
        self.assertEqual(values(animation), ["1.5 2.5", "3 4"])

    def test_free_running_transform_is_never_a_plain_animate(self) -> None:
        # Animating `transform` with <animate> is invalid SMIL and is dropped.
        element = LoopClock.free_running_transform(
            "translate", ((0.0, 0.0), (5.0, 5.0)), period_ms=1000
        )
        self.assertEqual(element.tag, "animateTransform")

    def test_free_running_animations_carry_their_own_period(self) -> None:
        element = LoopClock.free_running("opacity", (0, 1), period_ms=2500)
        self.assertEqual(element.attributes["dur"], "2.5000s")
        self.assertEqual(element.attributes["repeatCount"], "indefinite")


class GateTests(unittest.TestCase):
    """The visibility gate must never emit duplicate times."""

    def test_gate_from_zero_starts_visible(self) -> None:
        clock = LoopClock(1000)
        animation = clock.gate(visible_from_ms=0.0, visible_to_ms=400.0)
        self.assertEqual(values(animation)[0], "1")
        times = key_times(animation)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_gate_to_the_end_omits_the_trailing_switch(self) -> None:
        clock = LoopClock(1000)
        animation = clock.gate(visible_from_ms=200.0, visible_to_ms=1000.0)
        self.assertEqual(values(animation), ["0", "1", "1"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

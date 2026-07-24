"""Colour maths for the SVG generators.

SVG has no ``color-mix()``, no ``opacity`` channel on arbitrary paint servers
and no relative colour syntax, so every tint, shade and translucent variant in
the design system is resolved here, at build time, into a literal colour
string.  Keeping that in one module is what lets :mod:`config` expose a handful
of accent colours and still produce a coherent, layered composition.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = [
    "RGB",
    "parse_color",
    "to_hex",
    "with_alpha",
    "mix",
    "lighten",
    "darken",
    "relative_luminance",
]

RGB = tuple[float, float, float]

_HEX_PATTERN: Final = re.compile(r"^#?(?P<digits>[0-9a-fA-F]{3,8})$")
_RGB_FUNCTION_PATTERN: Final = re.compile(
    r"^rgba?\(\s*(?P<r>[\d.]+)\s*,\s*(?P<g>[\d.]+)\s*,\s*(?P<b>[\d.]+)"
    r"\s*(?:,\s*(?P<a>[\d.]+)\s*)?\)$"
)

_NAMED_COLORS: Final[dict[str, str]] = {
    "black": "#000000",
    "white": "#ffffff",
    "transparent": "#00000000",
}


def parse_color(value: str) -> tuple[RGB, float]:
    """Parse any colour string the config may contain.

    Supports ``#rgb``, ``#rrggbb``, ``#rrggbbaa``, ``rgb()``, ``rgba()`` and a
    small set of names.

    Args:
        value: The colour string.

    Returns:
        ``((r, g, b), alpha)`` with channels in ``0..255`` and alpha in ``0..1``.

    Raises:
        ValueError: If the string is not a recognised colour.
    """
    text = value.strip()
    text = _NAMED_COLORS.get(text.lower(), text)

    function_match = _RGB_FUNCTION_PATTERN.match(text)
    if function_match:
        channels = (
            float(function_match["r"]),
            float(function_match["g"]),
            float(function_match["b"]),
        )
        alpha = float(function_match["a"]) if function_match["a"] is not None else 1.0
        return channels, alpha

    hex_match = _HEX_PATTERN.match(text)
    if hex_match:
        digits = hex_match["digits"]
        if len(digits) in (3, 4):
            digits = "".join(character * 2 for character in digits)
        if len(digits) not in (6, 8):
            raise ValueError(f"unsupported hex colour: {value!r}")
        channels = (
            float(int(digits[0:2], 16)),
            float(int(digits[2:4], 16)),
            float(int(digits[4:6], 16)),
        )
        alpha = int(digits[6:8], 16) / 255.0 if len(digits) == 8 else 1.0
        return channels, alpha

    raise ValueError(f"unsupported colour: {value!r}")


def _clamp(value: float, low: float = 0.0, high: float = 255.0) -> float:
    return max(low, min(high, value))


def to_hex(channels: RGB) -> str:
    """Render ``(r, g, b)`` channels as ``#rrggbb``."""
    red, green, blue = (int(round(_clamp(channel))) for channel in channels)
    return f"#{red:02x}{green:02x}{blue:02x}"


def with_alpha(color: str, alpha: float) -> str:
    """Return ``color`` as an ``rgba()`` string at the given ``alpha``.

    The source colour's own alpha is multiplied in, so stacking translucency
    behaves the way a designer expects.
    """
    channels, base_alpha = parse_color(color)
    red, green, blue = (int(round(_clamp(channel))) for channel in channels)
    effective = max(0.0, min(1.0, alpha * base_alpha))
    return f"rgba({red},{green},{blue},{effective:.4g})"


def mix(color_a: str, color_b: str, weight: float) -> str:
    """Blend two colours in linear RGB space.

    Args:
        color_a: The colour returned when ``weight`` is ``0``.
        color_b: The colour returned when ``weight`` is ``1``.
        weight: Blend position in ``0..1``.

    Returns:
        The blended colour as ``#rrggbb``.
    """
    ratio = max(0.0, min(1.0, weight))
    (ar, ag, ab), _ = parse_color(color_a)
    (br, bg, bb), _ = parse_color(color_b)
    return to_hex(
        (
            ar + (br - ar) * ratio,
            ag + (bg - ag) * ratio,
            ab + (bb - ab) * ratio,
        )
    )


def lighten(color: str, amount: float) -> str:
    """Move ``color`` ``amount`` of the way toward white."""
    return mix(color, "#ffffff", amount)


def darken(color: str, amount: float) -> str:
    """Move ``color`` ``amount`` of the way toward black."""
    return mix(color, "#000000", amount)


def relative_luminance(color: str) -> float:
    """Return the WCAG relative luminance of ``color`` in ``0..1``."""
    (red, green, blue), _ = parse_color(color)

    def channel(value: float) -> float:
        normalised = value / 255.0
        if normalised <= 0.03928:
            return normalised / 12.92
        return ((normalised + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

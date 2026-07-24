"""Avatar to ASCII portrait conversion.

The conversion is a small imaging pipeline rather than a naive luminance
lookup, because the difference between "recognisable portrait" and "grey mush"
at 66 columns lives almost entirely in the preprocessing:

    composite on the card colour  ->  greyscale  ->  autocontrast
      ->  unsharp mask  ->  aspect-corrected resample  ->  gamma
      ->  ramp quantisation

Per-row mean luminance is carried alongside the characters so the renderer can
restore tonal depth that a character ramp alone cannot express.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

LOGGER = logging.getLogger(__name__)

__all__ = ["AsciiPortrait", "AvatarAsciiConverter", "RAMPS"]

#: Character ramps ordered from darkest (first) to brightest (last).
#: On a dark terminal background, denser glyphs read as *brighter* pixels, so
#: these are indexed directly by luminance.
RAMPS: Final[dict[str, str]] = {
    # 70 levels — maximum tonal resolution, the default.
    "ultra": (
        " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
    ),
    # 40 levels — cleaner at small font sizes.
    "dense": " .:-=+*#%@abcdefghijklmnopqrstuvwxyz0123456",
    # 16 levels — the classic ramp, very legible.
    "standard": " .:-=+*#%@$&WM█",
    # Unicode block elements — poster-like, no fine detail.
    "blocks": " ░▒▓█",
}

#: Fallback ramp when an unknown density name is configured.
_DEFAULT_RAMP_NAME: Final[str] = "ultra"


def _pixels(image: Image.Image) -> list[int]:
    """Read an image's pixels as a flat list, across Pillow versions.

    Pillow 12 deprecated ``Image.getdata()`` in favour of
    ``get_flattened_data()``, which does not exist on Pillow 10 or 11.  The
    project supports both, so the accessor is resolved at call time.
    """
    flattened = getattr(image, "get_flattened_data", None)
    if flattened is not None:
        return list(flattened())
    return list(image.getdata())  # pragma: no cover - Pillow < 12 only

#: Size of the procedurally generated placeholder portrait.
_PLACEHOLDER_SIZE: Final[int] = 512

#: Width of the border ring sampled by automatic polarity detection, as a
#: fraction of the shorter image edge.
_POLARITY_BORDER_RATIO: Final[float] = 0.08
#: How much brighter the border must be than the image mean before the source
#: is treated as dark-subject-on-light-background and inverted.
_POLARITY_MARGIN: Final[float] = 8.0


@dataclass(frozen=True)
class AsciiPortrait:
    """A rendered ASCII portrait plus the tonal data needed to shade it.

    Attributes:
        rows: One string per line, every row padded to exactly ``width``.
        row_luminance: Mean normalised luminance (0..1) of each row.
        width: Character columns.
        source: ``"avatar"`` or ``"placeholder"``.
    """

    rows: tuple[str, ...]
    row_luminance: tuple[float, ...]
    width: int
    source: str = "avatar"

    @property
    def height(self) -> int:
        """Number of character rows."""
        return len(self.rows)

    @property
    def peak_luminance(self) -> float:
        """Brightest row luminance, used to normalise row shading."""
        return max(self.row_luminance) if self.row_luminance else 1.0

    def shade_of(self, row_index: int, *, floor: float) -> float:
        """Opacity multiplier for one row, in ``[floor, 1]``.

        Args:
            row_index: Zero-based row.
            floor: Minimum opacity for the darkest row.

        Returns:
            A per-row opacity that reintroduces tonal depth lost to
            quantisation, without ever making a row invisible.
        """
        peak = self.peak_luminance or 1.0
        normalised = self.row_luminance[row_index] / peak
        return floor + (1.0 - floor) * normalised


class AvatarAsciiConverter:
    """Converts a raster avatar into an :class:`AsciiPortrait`.

    Args:
        width: Target character columns.
        cell_aspect: Character advance divided by line height.  This is what
            keeps the portrait's proportions correct instead of stretched.
        ramp_name: Key into :data:`RAMPS`.
        gamma: Applied after resampling; ``< 1`` lifts shadows.
        contrast: Multiplier applied before resampling.
        brightness: Multiplier applied before resampling.
        sharpen: Whether to unsharp-mask before downsampling.
        polarity: ``"auto"`` inspects the image and inverts it when the subject
            is dark on a light background — the case for GitHub's default
            identicons and most logo avatars.  ``"normal"`` and ``"invert"``
            force the decision.
        circular_mask: Crop the source to a circle before conversion.
        background: Colour composited under transparent avatar pixels.
    """

    def __init__(
        self,
        *,
        width: int,
        cell_aspect: float,
        ramp_name: str = _DEFAULT_RAMP_NAME,
        gamma: float = 1.0,
        contrast: float = 1.0,
        brightness: float = 1.0,
        sharpen: bool = True,
        polarity: str = "auto",
        circular_mask: bool = False,
        background: tuple[int, int, int] = (13, 17, 23),
    ) -> None:
        if width < 8:
            raise ValueError("ASCII width must be at least 8 columns")
        self.width = width
        self.cell_aspect = cell_aspect
        self.ramp = RAMPS.get(ramp_name, RAMPS[_DEFAULT_RAMP_NAME])
        self.gamma = gamma
        self.contrast = contrast
        self.brightness = brightness
        self.sharpen = sharpen
        self.polarity = polarity
        self.circular_mask = circular_mask
        self.background = background

    # -- public API ---------------------------------------------------------

    def convert_file(self, path: Path | None) -> AsciiPortrait:
        """Convert an image file, falling back to a generated placeholder.

        Args:
            path: Path to the avatar, or ``None``.

        Returns:
            The converted portrait; never raises for a missing or corrupt file.
        """
        if path is not None and path.exists():
            try:
                with Image.open(path) as image:
                    return self.convert(image)
            except Exception as error:  # noqa: BLE001 - any decode failure
                LOGGER.warning("avatar %s could not be decoded: %s", path, error)
        LOGGER.info("rendering procedural placeholder portrait")
        return self.convert(self._placeholder_image(), source="placeholder")

    def convert(self, image: Image.Image, *, source: str = "avatar") -> AsciiPortrait:
        """Convert an in-memory image into an ASCII portrait."""
        prepared = self._prepare(image)
        grid = self._resample(prepared)
        return self._quantise(grid, source=source)

    # -- pipeline stages ----------------------------------------------------

    def _prepare(self, image: Image.Image) -> Image.Image:
        """Flatten, mask, enhance and greyscale the source image."""
        rgba = image.convert("RGBA")
        flattened = Image.new("RGB", rgba.size, self.background)
        flattened.paste(rgba, mask=rgba.split()[3])

        if self.circular_mask:
            flattened = self._apply_circular_mask(flattened)

        grey = ImageOps.grayscale(flattened)
        grey = ImageOps.autocontrast(grey, cutoff=2)

        if self.sharpen:
            # Sharpening *before* the downsample is what preserves eyes, jaw
            # lines and hair edges once the image is only 66 pixels wide.
            grey = grey.filter(ImageFilter.UnsharpMask(radius=2.4, percent=155, threshold=3))

        if self.contrast != 1.0:
            grey = ImageEnhance.Contrast(grey).enhance(self.contrast)
        if self.brightness != 1.0:
            grey = ImageEnhance.Brightness(grey).enhance(self.brightness)
        if self._should_invert(grey):
            grey = ImageOps.invert(grey)
        return grey

    def _should_invert(self, grey: Image.Image) -> bool:
        """Decide whether the source needs its luminance flipped.

        A character ramp reads density as brightness, so an ASCII portrait is
        only legible when the *subject* is the bright region.  Photographs
        usually satisfy that already; identicons, logos and screenshots on a
        white field do not, and rendering them unflipped fills the card with
        solid glyphs and punches the subject out as holes.

        The test compares the image's outer border — which is almost always
        background — against its overall mean.
        """
        if self.polarity == "invert":
            return True
        if self.polarity != "auto":
            return False

        width, height = grey.size
        inset = max(1, int(min(width, height) * _POLARITY_BORDER_RATIO))
        border_pixels: list[int] = []
        for box in (
            (0, 0, width, inset),
            (0, height - inset, width, height),
            (0, 0, inset, height),
            (width - inset, 0, width, height),
        ):
            border_pixels.extend(_pixels(grey.crop(box)))
        if not border_pixels:  # pragma: no cover - degenerate images only
            return False

        border_mean = sum(border_pixels) / len(border_pixels)
        overall = grey.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        overall_mean = float(overall if isinstance(overall, (int, float)) else overall[0])

        invert = border_mean > overall_mean + _POLARITY_MARGIN
        LOGGER.info(
            "polarity: border %.0f vs mean %.0f -> %s",
            border_mean,
            overall_mean,
            "invert" if invert else "keep",
        )
        return invert

    def _resample(self, grey: Image.Image) -> Image.Image:
        """Downsample to the character grid, correcting for cell aspect."""
        source_width, source_height = grey.size
        rows = max(
            1,
            int(round(self.width * (source_height / source_width) * self.cell_aspect)),
        )
        return grey.resize((self.width, rows), Image.LANCZOS)

    def _quantise(self, grid: Image.Image, *, source: str) -> AsciiPortrait:
        """Map every cell's luminance onto the character ramp."""
        pixels = _pixels(grid)
        columns, rows = grid.size
        ramp_last_index = len(self.ramp) - 1

        text_rows: list[str] = []
        luminances: list[float] = []

        for row_index in range(rows):
            offset = row_index * columns
            line = pixels[offset : offset + columns]
            characters: list[str] = []
            row_total = 0.0
            for value in line:
                normalised = value / 255.0
                if self.gamma != 1.0:
                    normalised = math.pow(normalised, self.gamma)
                row_total += normalised
                characters.append(self.ramp[int(round(normalised * ramp_last_index))])
            text_rows.append("".join(characters))
            luminances.append(row_total / columns)

        return AsciiPortrait(
            rows=tuple(text_rows),
            row_luminance=tuple(luminances),
            width=columns,
            source=source,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _apply_circular_mask(image: Image.Image) -> Image.Image:
        """Composite the image onto its own background outside a circle."""
        width, height = image.size
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, width - 1, height - 1), fill=255)
        result = Image.new("RGB", (width, height), (0, 0, 0))
        result.paste(image, mask=mask)
        return result

    def _placeholder_image(self) -> Image.Image:
        """Generate a lit sphere so an avatar-less build still looks intentional.

        A procedurally shaded sphere quantises into a convincing portrait-like
        form: it has a specular highlight, a terminator and a falloff, which is
        exactly the tonal range an ASCII ramp needs to look good.
        """
        size = _PLACEHOLDER_SIZE
        image = Image.new("L", (size, size), 0)
        pixels = image.load()
        assert pixels is not None  # keeps type checkers happy

        radius = size * 0.44
        centre = size / 2.0
        # Light direction, normalised, pointing up-left toward the viewer.
        light = (-0.42, -0.58, 0.70)

        for y in range(size):
            for x in range(size):
                dx = (x - centre) / radius
                dy = (y - centre) / radius
                squared = dx * dx + dy * dy
                if squared > 1.0:
                    continue
                dz = math.sqrt(1.0 - squared)
                lambert = max(0.0, dx * light[0] + dy * light[1] + dz * light[2])
                specular = math.pow(lambert, 22.0)
                value = 26.0 + 190.0 * lambert + 60.0 * specular
                pixels[x, y] = int(min(255.0, value))

        return image.filter(ImageFilter.GaussianBlur(radius=1.1))

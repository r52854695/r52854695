"""The contract every SVG asset generator implements.

Each concrete generator owns exactly one output file.  It computes its own
layout, builds a :class:`~generator.svg.SvgDocument` and hands it back; writing
to disk, timing the build and reporting the result are handled once, here.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .config_types import ConfigLike
from .defs import PaintLibrary
from .svg import SvgDocument
from .timeline import LoopClock

__all__ = ["AssetGenerator", "BuildResult"]


@dataclass(frozen=True)
class BuildResult:
    """What one generator produced."""

    name: str
    path: Path
    byte_size: int
    element_count: int
    loop_seconds: float
    elapsed_ms: float

    @property
    def kilobytes(self) -> float:
        """Output size in KiB."""
        return self.byte_size / 1024.0

    def format_row(self) -> str:
        """Render one aligned console row summarising the build."""
        return (
            f"  {self.name:<34} {self.kilobytes:>8.1f} KiB "
            f"{self.element_count:>7} nodes  "
            f"{self.loop_seconds:>6.2f}s loop  "
            f"{self.elapsed_ms:>7.1f} ms"
        )


class AssetGenerator(ABC):
    """Base class for every generated SVG asset.

    Args:
        config: The active :class:`config.Config`.

    Attributes:
        filename: Output file name, relative to the output directory.
    """

    #: Overridden by every concrete subclass.
    filename: str = "asset.svg"
    #: Human-readable label used in build output.
    display_name: str = "asset"

    def __init__(self, config: ConfigLike) -> None:
        self.config = config

    # -- subclass hooks -----------------------------------------------------

    @abstractmethod
    def build(self) -> SvgDocument:
        """Construct and return the fully populated document."""

    # -- shared helpers -----------------------------------------------------

    def new_document(
        self,
        width: float,
        height: float,
        *,
        title: str,
        description: str,
    ) -> tuple[SvgDocument, PaintLibrary]:
        """Create a document together with its memoising paint library."""
        document = SvgDocument(width, height, title=title, description=description)
        return document, PaintLibrary(document, self.config)

    def new_clock(self, duration_ms: float) -> LoopClock:
        """Create a loop clock honouring the global speed multiplier."""
        return LoopClock(duration_ms, speed=self.config.animation.speed)

    # -- output -------------------------------------------------------------

    def render(self) -> str:
        """Build the document and serialise it."""
        return self.build().render()

    def write(self, output_dir: Path) -> BuildResult:
        """Build, serialise and write the asset, returning a summary.

        Args:
            output_dir: Directory to write into; created if missing.

        Returns:
            A :class:`BuildResult` describing the emitted file.
        """
        started = time.perf_counter()
        document = self.build()
        markup = document.render()
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / self.filename
        path.write_text(markup, encoding="utf-8")

        return BuildResult(
            name=self.filename,
            path=path,
            byte_size=len(markup.encode("utf-8")),
            element_count=sum(1 for _ in document.walk()),
            loop_seconds=self.loop_seconds(),
            elapsed_ms=elapsed_ms,
        )

    def loop_seconds(self) -> float:
        """Length of one animation loop, for build reporting.

        Subclasses that expose a ``_loop_duration_ms`` attribute get this for
        free; others may override.
        """
        duration = getattr(self, "_loop_duration_ms", 0.0)
        return float(duration) / 1000.0 / self.config.animation.speed

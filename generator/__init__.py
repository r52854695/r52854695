"""Standalone animated SVG generation for a GitHub profile README.

The package is a small rendering stack, layered bottom-up:

``svg``
    A minimal SVG DOM with number formatting and a memoising ``<defs>``
    registry.
``easing`` / ``timeline``
    The motion system: named Bezier curves, baked springs, and a loop clock
    that turns absolute millisecond timings into synchronised SMIL keyframes.
``colors`` / ``defs`` / ``chrome``
    The design system: colour maths, the shared gradient and filter library,
    and the macOS window frame plus monospace grid.
``github`` / ``avatar_to_ascii`` / ``content``
    Data acquisition and transformation, each with an offline fallback.
``*_generator``
    One module per emitted asset.
``readme``
    Template substitution for ``README.md``.

Nothing produced here depends on JavaScript, external CSS, web fonts or any
runtime framework: the SVGs animate with SMIL alone, directly inside GitHub.
"""

from __future__ import annotations

from .avatar_to_ascii import AsciiPortrait, AvatarAsciiConverter, RAMPS
from .base import AssetGenerator, BuildResult
from .chrome import MonoGrid, WindowChrome, WindowFrame
from .colors import darken, lighten, mix, with_alpha
from .content import InfoContent, InfoRow, InfoSection, RowKind, build_token_map
from .contribution_generator import CalendarLayout, ContributionGenerator
from .defs import GradientStop, PaintLibrary
from .easing import Ease
from .github import (
    ContributionCalendar,
    ContributionDay,
    GitHubClient,
    ProfileSnapshot,
    Repository,
    UserProfile,
    resolve_calendar,
    synthesize_calendar,
)
from .hero_generator import HeroGenerator, HeroStats
from .info_generator import InfoGenerator, InfoLayout
from .readme import AssetReference, ReadmeRenderer
from .svg import Element, SvgDocument
from .terminal_generator import TerminalGenerator, TerminalLayout
from .timeline import LoopClock
from .validation import ValidationReport, validate_file, validate_markup

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # svg core
    "Element",
    "SvgDocument",
    # motion
    "Ease",
    "LoopClock",
    # design system
    "GradientStop",
    "PaintLibrary",
    "MonoGrid",
    "WindowChrome",
    "WindowFrame",
    "darken",
    "lighten",
    "mix",
    "with_alpha",
    # data
    "AsciiPortrait",
    "AvatarAsciiConverter",
    "RAMPS",
    "ContributionCalendar",
    "ContributionDay",
    "GitHubClient",
    "ProfileSnapshot",
    "Repository",
    "UserProfile",
    "resolve_calendar",
    "synthesize_calendar",
    "InfoContent",
    "InfoRow",
    "InfoSection",
    "RowKind",
    "build_token_map",
    # generators
    "AssetGenerator",
    "BuildResult",
    "CalendarLayout",
    "ContributionGenerator",
    "HeroGenerator",
    "HeroStats",
    "InfoGenerator",
    "InfoLayout",
    "TerminalGenerator",
    "TerminalLayout",
    # readme
    "AssetReference",
    "ReadmeRenderer",
    # validation
    "ValidationReport",
    "validate_file",
    "validate_markup",
]

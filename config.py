"""Single source of truth for every tunable value in the profile generator.

Nothing in :mod:`generator` hard-codes a colour, a duration or a dimension.
Every module receives an immutable :class:`Config` instance and reads what it
needs from it, which keeps the rendering code declarative and makes the whole
visual system re-themeable from this one file.

All time values are expressed in **milliseconds at 1.0x speed**.  The global
``AnimationConfig.speed`` multiplier is applied once, at the clock level, so
changing it re-times every asset coherently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------

ROOT_DIR: Final[Path] = Path(__file__).resolve().parent
ASSETS_DIR: Final[Path] = ROOT_DIR / "assets"
CACHE_DIR: Final[Path] = ASSETS_DIR / "cache"
OUTPUT_DIR: Final[Path] = ROOT_DIR / "output"
TEMPLATE_PATH: Final[Path] = ROOT_DIR / "README.template.md"
README_PATH: Final[Path] = ROOT_DIR / "README.md"
PROFILE_CONTENT_PATH: Final[Path] = ROOT_DIR / "profile.json"
AVATAR_PATH: Final[Path] = ASSETS_DIR / "avatar.png"

#: Filenames of the generated assets, relative to :data:`OUTPUT_DIR`.
HERO_FILENAME: Final[str] = "hero-banner.svg"
TERMINAL_FILENAME: Final[str] = "terminal-card.svg"
INFO_FILENAME: Final[str] = "info-card.svg"
CONTRIBUTION_FILENAME: Final[str] = "github-contribution-animation.svg"


# ---------------------------------------------------------------------------
# Colour system
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """The GitHub-dark derived colour system shared by every asset.

    Values are plain CSS colour strings so they can be dropped straight into
    SVG paint attributes without conversion.
    """

    # Structural surfaces.
    background: str = "#0d1117"
    background_deep: str = "#010409"
    surface: str = "#161b22"
    surface_raised: str = "#1c2128"
    surface_sunken: str = "#0b0f14"

    # Hairlines and glass edges.
    border: str = "rgba(255,255,255,0.08)"
    border_strong: str = "rgba(255,255,255,0.14)"
    border_hairline: str = "rgba(255,255,255,0.04)"

    # Typography.
    text_primary: str = "#e6edf3"
    text_secondary: str = "#8b949e"
    text_muted: str = "#6e7681"
    text_faint: str = "#484f58"
    white: str = "#ffffff"

    # Accents — the four glow colours that carry the whole design language.
    cyan: str = "#22d3ee"
    purple: str = "#a78bfa"
    green: str = "#3fb950"
    orange: str = "#f0883e"

    # Supporting accents.
    blue: str = "#58a6ff"
    pink: str = "#f778ba"
    yellow: str = "#e3b341"
    red: str = "#ff7b72"
    neon_green: str = "#39ff8a"

    # macOS traffic lights.
    traffic_red: str = "#ff5f57"
    traffic_yellow: str = "#febc2e"
    traffic_green: str = "#28c840"


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Typography:
    """Font stacks.

    Only *generic, locally available* families are referenced: the SVGs must be
    completely standalone, so no web font may ever be embedded or linked.
    """

    mono: str = (
        "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
        "'DejaVu Sans Mono', 'Liberation Mono', monospace"
    )
    sans: str = (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, Roboto, "
        "Helvetica, Arial, sans-serif"
    )

    #: Horizontal advance of one glyph, as a multiple of the font size.
    #: 0.6em is the near-universal advance of monospaced faces and is what the
    #: layout engine uses to build pixel-perfect character grids.
    mono_advance_ratio: float = 0.6


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnimationConfig:
    """Global motion parameters.

    ``speed`` is a wall-clock multiplier: 2.0 plays every asset twice as fast
    without touching a single keyframe.
    """

    speed: float = 1.0

    #: Spring overshoot for entrance scale animations (1.0 == no overshoot).
    spring_overshoot: float = 1.14
    #: Secondary undershoot of the spring settle.
    spring_undershoot: float = 0.97

    #: Duration of the white specular glint that rakes across each element.
    glint_duration_ms: float = 120.0
    #: Time from element birth to the glint peak.
    glint_peak_offset_ms: float = 26.0
    #: Peak opacity of the specular glint.
    glint_opacity: float = 0.85

    #: How long a finished composition rests before the loop restarts.
    hold_ms: float = 2600.0
    #: Cross-fade used to make the loop restart invisible.
    loop_fade_ms: float = 620.0

    #: Period of a terminal cursor blink cycle.
    cursor_blink_ms: float = 1060.0


@dataclass(frozen=True)
class GlowConfig:
    """Filter-based glow tuning shared by every asset."""

    #: Master multiplier applied to every blur radius below.
    intensity: float = 1.0

    soft_blur: float = 1.6
    strong_blur: float = 2.9
    halo_blur: float = 7.0

    #: The animated glow "breathes" between these two blur multipliers.
    breathe_min: float = 0.78
    breathe_max: float = 1.28
    breathe_period_ms: float = 3400.0

    #: Above this many simultaneously glowing cells the contribution graph
    #: automatically swaps Gaussian filters for pre-baked radial halos, which
    #: render an order of magnitude faster on large calendars.
    filter_budget: int = 180


# ---------------------------------------------------------------------------
# Asset: contribution calendar
# ---------------------------------------------------------------------------

ContributionSource = Literal["auto", "live", "synthetic"]


@dataclass(frozen=True)
class ContributionConfig:
    """Geometry, colour and motion of ``github-contribution-animation.svg``."""

    # --- data ---------------------------------------------------------------
    #: ``auto`` scrapes GitHub and falls back to deterministic synthetic data.
    source: ContributionSource = "auto"
    columns: int = 53
    rows: int = 7

    # --- geometry (GitHub's native calendar metrics) -------------------------
    cell_size: float = 11.0
    cell_gap: float = 3.0
    corner_radius: float = 2.0

    card_padding: float = 26.0
    weekday_gutter: float = 34.0
    month_label_height: float = 22.0
    header_height: float = 54.0
    legend_height: float = 34.0

    # --- colour ramp, index 0..4 -------------------------------------------
    level_colors: tuple[str, str, str, str, str] = (
        "#151b23",  # 0 — empty
        "#0e4429",  # 1 — green
        "#006d32",  # 2 — brighter green
        "#26a641",  # 3 — bright green
        "#39d353",  # 4 — neon green
    )
    #: Levels at or above this index receive an animated glow.
    glow_from_level: int = 3

    empty_cell_stroke: str = "rgba(255,255,255,0.045)"

    # --- motion -------------------------------------------------------------
    #: Delay added per diagonal wavefront step (bottom-left -> top-right).
    wave_step_ms: float = 22.0
    #: Extra per-column jitter, keeps the sweep organic rather than robotic.
    wave_jitter_ms: float = 34.0
    #: Duration of a single square's spring entrance.
    cell_entrance_ms: float = 620.0
    #: Distance a square travels during its entrance, in px.
    entrance_offset: tuple[float, float] = (-5.0, 7.0)

    #: Ambient aurora blobs painted behind the grid.
    aurora_drift_ms: float = 15000.0
    aurora_opacity: float = 0.5

    show_month_labels: bool = True
    show_weekday_labels: bool = True
    show_legend: bool = True

    label_font_size: float = 10.0
    title_font_size: float = 15.0
    subtitle_font_size: float = 11.5


# ---------------------------------------------------------------------------
# Asset: ASCII terminal card
# ---------------------------------------------------------------------------

AsciiDensity = Literal["ultra", "dense", "standard", "blocks"]
AsciiPolarity = Literal["auto", "normal", "invert"]


@dataclass(frozen=True)
class TerminalConfig:
    """Geometry, ASCII conversion and motion of ``terminal-card.svg``."""

    # --- card ---------------------------------------------------------------
    width: float = 540.0
    titlebar_height: float = 38.0
    padding: float = 22.0
    corner_radius: float = 12.0
    window_title: str = "avatar@github — ascii"

    # --- ASCII portrait -----------------------------------------------------
    ascii_width: int = 66
    ascii_density: AsciiDensity = "ultra"
    #: Line pitch as a multiple of the derived font size.  The font size itself
    #: is *computed* so that ``ascii_width`` characters exactly fill the card's
    #: content width — the portrait is always crisp, whatever the card width.
    ascii_line_height_ratio: float = 1.06
    #: Post-resize gamma; < 1 lifts shadows, > 1 crushes them.
    ascii_gamma: float = 0.92
    ascii_contrast: float = 1.35
    ascii_brightness: float = 1.04
    ascii_sharpen: bool = True
    #: ``auto`` detects a light-background avatar (identicons, logos) and flips
    #: it so the subject renders as the dense, bright region.  ``normal`` and
    #: ``invert`` override the detection.
    ascii_polarity: AsciiPolarity = "auto"
    #: Crop the avatar to a circle before conversion.
    ascii_circular_mask: bool = False
    #: Per-row opacity floor; rows darker than average fade slightly, which
    #: restores tonal depth that a pure character ramp cannot express.
    ascii_row_shade_floor: float = 0.62

    # --- motion -------------------------------------------------------------
    #: Time to "type" one row of the portrait.
    row_type_ms: float = 74.0
    #: Gap between the end of one row and the start of the next.
    row_gap_ms: float = 6.0
    #: Vertical rise of each row as it is revealed.
    row_rise_px: float = 3.0
    #: Period of the slow scanline shimmer that drifts over the portrait.
    scanline_period_ms: float = 5200.0

    cursor_height_ratio: float = 1.15
    cursor_color: str = "#ffffff"
    cursor_opacity: float = 0.92

    # --- footer prompt ------------------------------------------------------
    prompt_symbol: str = "$"
    prompt_command: str = "whoami"
    footer_font_size: float = 12.5
    footer_line_height: float = 21.0
    #: Vertical space between the portrait and the footer separator.
    footer_gap: float = 17.0
    #: Time to type a single character in the footer prompt.
    char_type_ms: float = 62.0
    #: Pause between the command finishing and its output appearing.
    command_output_delay_ms: float = 420.0
    #: Pause after the output before the trailing prompt appears.
    prompt_return_delay_ms: float = 300.0


# ---------------------------------------------------------------------------
# Asset: neofetch-style info card
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InfoConfig:
    """Geometry, colour roles and motion of ``info-card.svg``."""

    width: float = 540.0
    #: When set, the card is padded to exactly this height so that it lines up
    #: with the terminal card inside the README's two-column table.
    match_height_to_terminal: bool = True

    titlebar_height: float = 38.0
    padding: float = 22.0
    corner_radius: float = 12.0
    window_title: str = "neofetch — profile"

    font_size: float = 12.0
    line_height: float = 19.0
    section_gap: float = 14.0
    #: Upper bound on the section gap when the card is stretched to match the
    #: terminal card; any surplus beyond this is used to centre the block
    #: vertically instead, which stops sections from drifting apart.
    max_section_gap: float = 58.0
    header_gap: float = 7.0
    #: Column at which values start, measured in character cells.
    value_column: int = 16

    # --- colour roles (spec-mandated) ---------------------------------------
    header_color: str = "#f0883e"  # orange
    bullet_color: str = "#58a6ff"  # blue
    value_color: str = "#3fb950"  # green
    label_color: str = "#e6edf3"  # white
    separator_color: str = "#22d3ee"  # cyan

    bullet_glyph: str = "▸"
    separator_glyph: str = "─"

    # --- motion -------------------------------------------------------------
    #: Delay between consecutive rows printing.
    row_stagger_ms: float = 60.0
    #: Distance each row slides upward while fading in.
    row_rise_px: float = 10.0
    row_reveal_ms: float = 460.0


# ---------------------------------------------------------------------------
# Asset: hero banner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HeroConfig:
    """Geometry and motion of ``hero-banner.svg``."""

    width: float = 1100.0
    height: float = 260.0
    corner_radius: float = 16.0

    title_font_size: float = 58.0
    subtitle_font_size: float = 15.0
    tag_font_size: float = 11.5

    #: Rotating strings typed under the wordmark.
    taglines: tuple[str, ...] = (
        "building resilient cloud platforms",
        "python · azure · kubernetes · terraform",
        "LLM systems that survive production",
    )
    #: Chips rendered along the bottom edge.
    chips: tuple[str, ...] = (
        "Python",
        "Azure",
        "Kubernetes",
        "Terraform",
        "LangChain",
        "Docker",
        "GitHub Actions",
    )

    #: Time to type one tagline character.
    type_char_ms: float = 34.0
    #: How long a completed tagline stays on screen.
    tagline_hold_ms: float = 1500.0
    #: Period of the light sweep that rakes across the wordmark.
    sweep_period_ms: float = 5200.0
    #: Period of the animated grid parallax.
    grid_drift_ms: float = 12000.0

    grid_spacing: float = 34.0
    star_count: int = 46


# ---------------------------------------------------------------------------
# Root configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Aggregate configuration handed to every generator."""

    username: str = "r52854695"
    display_name: str = "r52854695"
    tagline: str = "Cloud · Python · Platform Engineering"

    #: Optional PAT.  Only used to lift REST rate limits; never required.
    github_token_env_var: str = "GITHUB_TOKEN"
    request_timeout_s: float = 12.0
    #: Reuse cached API responses when the network is unreachable.
    use_cache: bool = True

    palette: Palette = field(default_factory=Palette)
    typography: Typography = field(default_factory=Typography)
    animation: AnimationConfig = field(default_factory=AnimationConfig)
    glow: GlowConfig = field(default_factory=GlowConfig)

    contribution: ContributionConfig = field(default_factory=ContributionConfig)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    info: InfoConfig = field(default_factory=InfoConfig)
    hero: HeroConfig = field(default_factory=HeroConfig)

    #: Append a content hash to README image URLs so GitHub's image proxy
    #: (camo) serves the freshly generated asset instead of a stale copy.
    cache_bust_readme_assets: bool = True

    @property
    def accent_cycle(self) -> tuple[str, str, str, str]:
        """The four glow accents in their canonical rotation order."""
        p = self.palette
        return (p.cyan, p.purple, p.green, p.orange)


#: The instance every entry point imports.
CONFIG: Final[Config] = Config()

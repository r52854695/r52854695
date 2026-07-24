#!/usr/bin/env python3
"""Build every profile asset and regenerate ``README.md``.

    python build.py                 # full build against live GitHub data
    python build.py --offline       # no network: cache, then synthetic data
    python build.py --speed 1.5     # re-time every animation
    python build.py --only hero      # rebuild a single asset

The pipeline is deliberately linear and side-effect free until the very end:
resolve data, convert the avatar, build four independent SVG documents, then
write them and the README together.  A failure at any stage falls back rather
than aborting, because a profile README that stops rendering is worse than one
built from cached data.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

from config import (
    ASSETS_DIR,
    AVATAR_PATH,
    CACHE_DIR,
    CONFIG,
    OUTPUT_DIR,
    PROFILE_CONTENT_PATH,
    README_PATH,
    TEMPLATE_PATH,
    Config,
)
from generator import (
    AssetReference,
    AvatarAsciiConverter,
    BuildResult,
    ContributionGenerator,
    GitHubClient,
    HeroGenerator,
    HeroStats,
    InfoContent,
    InfoGenerator,
    ProfileSnapshot,
    ReadmeRenderer,
    TerminalGenerator,
    build_token_map,
    resolve_calendar,
    synthesize_calendar,
)
from generator.github import format_compact_number, summarise_languages, synthesize_user
from generator.validation import validate_file

LOGGER = logging.getLogger("build")

#: Asset selector names accepted by ``--only``.
ASSET_NAMES = ("hero", "terminal", "info", "contribution")

#: Template token names for each generated asset.
_ASSET_TOKENS = {
    "hero": "HERO_SVG",
    "terminal": "TERMINAL_SVG",
    "info": "INFO_SVG",
    "contribution": "CONTRIBUTION_SVG",
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line options."""
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="Generate animated SVG assets and rewrite README.md.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--username",
        default=CONFIG.username,
        help="GitHub login to profile.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Never touch the network; use cached responses, then synthetic data.",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=CONFIG.animation.speed,
        help="Global animation speed multiplier.",
    )
    parser.add_argument(
        "--only",
        choices=ASSET_NAMES,
        action="append",
        help="Build only the named asset; may be repeated.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory to write the SVG assets into.",
    )
    parser.add_argument(
        "--no-readme",
        action="store_true",
        help="Skip regenerating README.md.",
    )
    parser.add_argument(
        "--no-cache-bust",
        action="store_true",
        help="Emit plain asset URLs without a content hash.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip the post-build SVG and SMIL validation pass.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log every network call and fallback decision.",
    )
    return parser.parse_args(argv)


def configure_logging(verbose: bool) -> None:
    """Set up concise, readable console logging."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname).1s  %(message)s",
        stream=sys.stderr,
    )
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def apply_overrides(config: Config, arguments: argparse.Namespace) -> Config:
    """Return a copy of ``config`` with CLI overrides applied.

    :class:`config.Config` is frozen, so overrides are expressed as a replaced
    copy rather than mutation — the configuration a build ran with stays a
    single immutable value that can be logged or asserted against.
    """
    animation = dataclasses.replace(config.animation, speed=arguments.speed)
    return dataclasses.replace(
        config,
        username=arguments.username,
        display_name=(
            config.display_name
            if arguments.username == config.username
            else arguments.username
        ),
        animation=animation,
        cache_bust_readme_assets=not arguments.no_cache_bust,
    )


# ---------------------------------------------------------------------------
# Data resolution
# ---------------------------------------------------------------------------


def resolve_snapshot(config: Config, *, offline: bool) -> ProfileSnapshot:
    """Fetch (or synthesise) everything the generators need.

    Args:
        config: The active configuration.
        offline: Skip the network entirely.

    Returns:
        A populated :class:`~generator.github.ProfileSnapshot`.
    """
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if offline:
        LOGGER.info("offline mode: skipping all network access")
        snapshot = ProfileSnapshot(
            user=synthesize_user(config.username),
            repositories=[],
            calendar=synthesize_calendar(
                config.username, columns=config.contribution.columns
            ),
            avatar_path=AVATAR_PATH if AVATAR_PATH.exists() else None,
        )
        return snapshot

    client = GitHubClient(
        config.username,
        cache_dir=CACHE_DIR,
        token=os.environ.get(config.github_token_env_var) or None,
        timeout=config.request_timeout_s,
        use_cache=config.use_cache,
    )
    snapshot = ProfileSnapshot(
        user=client.fetch_user(),
        repositories=client.fetch_repositories(),
        calendar=resolve_calendar(
            client,
            source_mode=config.contribution.source,
            seed=config.username,
            columns=config.contribution.columns,
        ),
        avatar_path=client.download_avatar(AVATAR_PATH),
    )
    return snapshot


def summarise_snapshot(snapshot: ProfileSnapshot) -> str:
    """One-line description of the data a build is about to render."""
    calendar = snapshot.calendar
    languages = summarise_languages(snapshot.language_stats(limit=3)) or "no languages"
    return (
        f"{snapshot.user.login} · {snapshot.user.source} profile · "
        f"{snapshot.user.public_repos} repos · "
        f"{calendar.total if calendar else 0} contributions "
        f"({calendar.source if calendar else 'none'}) · {languages}"
    )


# ---------------------------------------------------------------------------
# Asset construction
# ---------------------------------------------------------------------------


def build_assets(
    config: Config,
    snapshot: ProfileSnapshot,
    *,
    selected: Iterable[str],
    output_dir: Path,
) -> dict[str, BuildResult]:
    """Construct and write every selected SVG asset.

    The terminal card is always laid out first, even when it is not being
    written, because the info card matches its height so the README's
    two-column table stays perfectly aligned.

    Args:
        config: Active configuration.
        snapshot: Resolved GitHub data.
        selected: Asset names to write.
        output_dir: Destination directory.

    Returns:
        Asset name -> :class:`~generator.base.BuildResult`.
    """
    wanted = set(selected)
    results: dict[str, BuildResult] = {}

    portrait = AvatarAsciiConverter(
        width=config.terminal.ascii_width,
        cell_aspect=(
            config.typography.mono_advance_ratio / config.terminal.ascii_line_height_ratio
        ),
        ramp_name=config.terminal.ascii_density,
        gamma=config.terminal.ascii_gamma,
        contrast=config.terminal.ascii_contrast,
        brightness=config.terminal.ascii_brightness,
        sharpen=config.terminal.ascii_sharpen,
        polarity=config.terminal.ascii_polarity,
        circular_mask=config.terminal.ascii_circular_mask,
    ).convert_file(snapshot.avatar_path)

    terminal = TerminalGenerator(config, portrait, username=snapshot.user.login)
    LOGGER.info("terminal card: %s", terminal.describe())

    if "terminal" in wanted:
        results["terminal"] = terminal.write(output_dir)

    if "info" in wanted:
        tokens = build_token_map(snapshot, tagline=config.tagline)
        content = InfoContent.load(PROFILE_CONTENT_PATH, tokens)
        info = InfoGenerator(
            config,
            content,
            min_height=(
                terminal.layout.height if config.info.match_height_to_terminal else None
            ),
        )
        LOGGER.info("info card: %s", info.describe())
        results["info"] = info.write(output_dir)

    if "contribution" in wanted:
        calendar = snapshot.calendar or synthesize_calendar(
            config.username, columns=config.contribution.columns
        )
        contribution = ContributionGenerator(config, calendar)
        LOGGER.info("contribution calendar: %s", contribution.describe())
        results["contribution"] = contribution.write(output_dir)

    if "hero" in wanted:
        hero = HeroGenerator(
            config,
            HeroStats(
                repositories=snapshot.user.public_repos,
                contributions=snapshot.calendar.total if snapshot.calendar else 0,
                top_language=snapshot.top_language,
            ),
        )
        LOGGER.info("hero banner: %s", hero.describe())
        results["hero"] = hero.write(output_dir)

    return results


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_results(results: dict[str, BuildResult]) -> bool:
    """Check every written asset against the SVG and SMIL invariants.

    An invalid animation is dropped silently by renderers, so this pass is the
    only thing standing between a typo in a keyframe list and a profile page
    that quietly stops moving.

    Args:
        results: The assets just written.

    Returns:
        ``True`` when every asset is valid.
    """
    reports = [validate_file(result.path) for result in results.values()]
    failures = [report for report in reports if not report.ok]

    checked = sum(report.animation_count for report in reports)
    if not failures:
        print(f"  valid    {checked} animations, {len(reports)} assets")
        return True

    print("\n  validation failed\n")
    for report in failures:
        print(report.format_summary())
        print(report.format_details())
    print()
    return False


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------


def build_readme_tokens(config: Config, snapshot: ProfileSnapshot) -> dict[str, str]:
    """Assemble the non-asset token map for the README template."""
    calendar = snapshot.calendar
    languages = snapshot.language_stats(limit=5)
    return {
        "USERNAME": snapshot.user.login,
        "DISPLAY_NAME": config.display_name,
        "TAGLINE": config.tagline,
        "BIO": snapshot.user.bio or config.tagline,
        "REPO_COUNT": format_compact_number(snapshot.user.public_repos),
        "FOLLOWER_COUNT": format_compact_number(snapshot.user.followers),
        "STAR_COUNT": format_compact_number(snapshot.total_stars),
        "MEMBER_SINCE": snapshot.user.member_since,
        "TOP_LANGUAGE": snapshot.top_language,
        "LANGUAGE_LIST": ", ".join(stat.name for stat in languages) or "—",
        "CONTRIBUTION_COUNT": format_compact_number(calendar.total if calendar else 0),
        "ACTIVE_DAYS": str(calendar.active_days if calendar else 0),
        "LONGEST_STREAK": f"{calendar.longest_streak()}d" if calendar else "0d",
        "CURRENT_STREAK": f"{calendar.current_streak()}d" if calendar else "0d",
    }


def write_readme(
    config: Config,
    snapshot: ProfileSnapshot,
    results: dict[str, BuildResult],
    *,
    output_dir: Path,
) -> Path | None:
    """Regenerate ``README.md`` from the template.

    Returns:
        The path written, or ``None`` if the template is missing.
    """
    if not TEMPLATE_PATH.exists():
        LOGGER.error("template %s is missing; README not regenerated", TEMPLATE_PATH)
        return None

    root = README_PATH.parent
    assets = {
        _ASSET_TOKENS[name]: AssetReference(
            token=_ASSET_TOKENS[name], path=result.path, relative_to=root
        )
        for name, result in results.items()
        if name in _ASSET_TOKENS
    }

    # Assets that were not rebuilt this run still need a URL if they exist.
    for name, token in _ASSET_TOKENS.items():
        if token in assets:
            continue
        candidate = output_dir / _filename_for(name)
        if candidate.exists():
            assets[token] = AssetReference(
                token=token, path=candidate, relative_to=root
            )

    renderer = ReadmeRenderer(
        TEMPLATE_PATH, README_PATH, cache_bust=config.cache_bust_readme_assets
    )
    return renderer.write(assets, build_readme_tokens(config, snapshot))


def _filename_for(asset_name: str) -> str:
    """Map an asset selector onto its output filename."""
    return {
        "hero": HeroGenerator.filename,
        "terminal": TerminalGenerator.filename,
        "info": InfoGenerator.filename,
        "contribution": ContributionGenerator.filename,
    }[asset_name]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run a full build.

    Returns:
        ``0`` on success, ``1`` if nothing could be produced.
    """
    arguments = parse_arguments(argv)
    configure_logging(arguments.verbose)
    started = time.perf_counter()

    config = apply_overrides(CONFIG, arguments)
    selected = tuple(arguments.only) if arguments.only else ASSET_NAMES

    print(f"\n  animated profile build · @{config.username}\n")

    snapshot = resolve_snapshot(config, offline=arguments.offline)
    print(f"  data     {summarise_snapshot(snapshot)}\n")

    results = build_assets(
        config, snapshot, selected=selected, output_dir=arguments.output
    )
    if not results:
        LOGGER.error("no assets were produced")
        return 1

    print("  assets")
    for name in ASSET_NAMES:
        if name in results:
            print(results[name].format_row())

    total_bytes = sum(result.byte_size for result in results.values())
    print(f"\n  total    {total_bytes / 1024:.1f} KiB across {len(results)} files")

    if not arguments.no_validate and not validate_results(results):
        return 1

    if not arguments.no_readme:
        readme = write_readme(
            config, snapshot, results, output_dir=arguments.output
        )
        if readme is not None:
            print(f"  readme   {readme.name} regenerated")

    elapsed = (time.perf_counter() - started) * 1000.0
    print(f"  done     {elapsed:.0f} ms\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

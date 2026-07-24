# Architecture

> `README.md` at the repository root is the *rendered profile*. This file is the
> developer documentation for the system that generates it.

```
python build.py
```

That regenerates every SVG in `output/`, validates them, and rewrites
`README.md` from `README.template.md`.

---

## The constraint that shapes everything

GitHub renders README images through an `<img>` tag behind its camo proxy. Inside
an `<img>`, an SVG is a **document, not a page**:

| Not available | Available |
| --- | --- |
| JavaScript | SMIL (`<animate>`, `<animateTransform>`) |
| External CSS | Presentation attributes |
| Web fonts (`@font-face`, remote `@import`) | Generic font stacks the viewer already has |
| Remote images, `fetch`, cookies | Gradients, filters, masks, clip paths, `<use>` |

So every asset here is a single self-contained file whose entire motion system is
SMIL. There is no runtime, no hydration and no network dependency after the file
is served. `generator/validation.py` enforces those rules on every build.

---

## Package layout

```
config.py                  every tunable value, in one frozen dataclass tree
build.py                   CLI orchestrator: resolve data -> build -> validate -> README
profile.json               editable copy for the info card
README.template.md         the README, with {{TOKEN}} placeholders

generator/
  svg.py                   minimal SVG DOM, number formatting, memoising <defs>
  easing.py                named Bezier curves and baked spring responses
  timeline.py              LoopClock: absolute milliseconds -> synchronised SMIL
  colors.py                colour maths (SVG has no color-mix())
  defs.py                  PaintLibrary: every gradient, filter and mask
  chrome.py                MonoGrid + the macOS window frame
  github.py                data acquisition with cache and synthetic fallbacks
  avatar_to_ascii.py       the avatar -> ASCII imaging pipeline
  content.py               profile.json -> typed content model
  base.py                  AssetGenerator contract and BuildResult
  hero_generator.py        -> output/hero-banner.svg
  terminal_generator.py    -> output/terminal-card.svg
  info_generator.py        -> output/info-card.svg
  contribution_generator.py-> output/github-contribution-animation.svg
  readme.py                template substitution and asset cache-busting
  validation.py            SVG + SMIL invariant checks

tools/
  preview.html             open in a browser to see every asset animating
  validate.py              standalone CLI for validation.py

tests/                     115 tests, stdlib unittest only
```

The `generator` package never imports `config` at runtime — see
`generator/config_types.py`. It is a library that accepts a configuration
object, which keeps the import graph acyclic and the package relocatable.

---

## The motion system

### Why a loop clock exists

Each asset is one composition of hundreds of independent elements that must stay
frame-accurate relative to one another, forever. SMIL cannot express that
directly: every `<animate>` has its own `dur`, and its `keyTimes` are fractions
of *that* duration. Chaining with `begin="other.end"` works but drifts and is
brittle across renderers.

`LoopClock` removes the problem. Every animation in a document shares one `dur`
(the loop length) and `repeatCount="indefinite"`; the clock converts the
millisecond timings the generators actually think in into fractions of that
shared loop:

```python
clock = self.new_clock(5150)                    # one 5.15s loop
cell.add(clock.animate_transform(
    "scale",
    [(delay, 0.0), (delay + 260, 1.14), (delay + 447, 0.97), (delay + 620, 1.0)],
    ease=[EASE_OUT_EXPO, EASE_IN_OUT_SINE, EASE_OUT_CUBIC],
))
```

The clock also:

* **pads the head and tail** so a caller only describes the interesting part of
  the timeline and the value simply holds either side;
* **quantises `keyTimes` to integer steps** before enforcing strict monotonicity.
  This matters more than it sounds: nudging coincident floats apart by an epsilon
  finer than the output precision lets them collapse back together when rounded
  for serialisation, and SMIL then drops the whole animation without a word.
  There is a regression test for exactly this;
* **rejects over-packed loops** with an actionable error instead of emitting
  something the renderer will silently discard.

`LoopClock.free_running` and `free_running_transform` opt out of the shared clock
for genuinely aperiodic ambience — cursor blink, aurora drift, glow breathing —
where quantising to the composition length would look mechanical.

### Springs

`easing.spring_scale_track` and `spring_offset_track` bake a critically-damped
response into four keyframes rather than solving a differential equation at
runtime. Entrances rise fast, overshoot, dip just below rest and settle, which is
what separates a spring from a plain ease-out.

---

## Per-asset notes

### `github-contribution-animation.svg`

GitHub's own geometry: 53 columns, 7 rows, 11px cells on a 3px gutter, `rx=2`.

* **The wave.** Delay is `column + (rows - 1 - row)`, so the front sweeps from the
  bottom-left corner to the top-right, plus a per-cell jitter that keeps it
  organic. The jitter is pre-rolled into a table in the constructor so it is a
  pure function of `(column, row)` — month and weekday labels time themselves
  against the squares beside them, and drawing order must never change a delay.
* **The glint.** Each square is raked by a 120ms white specular pulse at the
  moment it lands, instanced from one `<use>` of a single gradient-filled rect.
* **Glow.** Levels 3 and 4 carry a bloom filter whose `stdDeviation` breathes on
  its own period. Because the animation lives on the *filter primitive*, one
  animation drives every cell that references it.
* **Performance guard.** Filters cost a full offscreen pass per element. Above
  `glow.filter_budget` glowing cells the generator silently switches to pre-baked
  radial halos, which look near-identical and are roughly an order of magnitude
  cheaper. On a calendar with a few bright days you get filters; on a wall of
  green you get halos.

### `terminal-card.svg`

The ASCII font size is **derived, not configured**: `advance = content_width /
ascii_width`. The grid therefore always fills the card exactly, and `textLength`
with `lengthAdjust="spacing"` pins it there regardless of which monospaced face
the viewer has installed.

Each portrait row is revealed by an animated `clipPath` width while a single
white block cursor walks its leading edge; the carriage return is a 1ms segment
in the same translate track, which reads as an instantaneous jump. The footer
types `$ whoami`, prints the login and returns to a blinking prompt.

**Avatar polarity** is detected automatically. A character ramp reads density as
brightness, so an ASCII portrait is only legible when the *subject* is the bright
region. Photographs usually satisfy that; identicons and logos on a white field
do not, and rendering them unflipped fills the card with solid glyphs and punches
the subject out as holes. The converter compares the image border against its
mean and inverts when needed (`terminal.ascii_polarity = "auto" | "normal" |
"invert"`).

### `info-card.svg`

Copy lives in `profile.json`, resolved through `{token}` placeholders against
live GitHub data. Row kinds: `kv`, `bullet`, `text`, `rule`, `blank`.

Colour roles are fixed by the design system and applied in one place: orange
section headers, cyan separators, white labels, green values, blue bullets.

The card matches the terminal card's height so the README's two-column table
stays aligned. Surplus height goes into the gaps between sections up to
`info.max_section_gap`; anything beyond that centres the block vertically rather
than letting sections drift apart.

### `hero-banner.svg`

Parallax grid dissolved by a radial `<mask>`, drifting aurora, a twinkling star
field, a wordmark lit by a travelling gradient (an animated `gradientTransform`,
not a mask sweep — far cheaper), a self-typing tagline cycle, and stack chips
that spring in on a stagger.

---

## Output size

The contribution calendar is ~410 KiB of markup and about 1,500 SMIL animations.
That sounds heavy and is not:

| Asset | Raw | Gzipped |
| --- | ---: | ---: |
| `github-contribution-animation.svg` | ~410 KiB | **~22 KiB** |
| `terminal-card.svg` | ~55 KiB | ~5 KiB |
| `hero-banner.svg` | ~30 KiB | ~5 KiB |
| `info-card.svg` | ~28 KiB | ~3 KiB |

SVG is extremely compressible and GitHub serves it gzipped, so the whole profile
costs roughly 35 KiB on the wire. The techniques that get it there:

* every gradient, filter, mask and clip path is registered through
  `SvgDocument.define`, so a definition requested by four hundred call sites is
  emitted once;
* the 371 calendar squares are `<use>` instances of six shared rects rather than
  inline geometry;
* output carries newlines but no indentation — one element per line keeps builds
  diffable in git without paying for leading whitespace on thousands of nodes;
* coordinates round to three decimals, `keyTimes` to five.

---

## Configuration

Everything lives in `config.py` as frozen dataclasses: username, accent colours,
animation speed, card sizes, font stacks, ASCII density and polarity,
contribution colours, glow intensity, per-asset geometry and timing.

`AnimationConfig.speed` is a single wall-clock multiplier applied at the clock
level, so `python build.py --speed 1.5` re-times every asset coherently without
touching a keyframe.

---

## Data resolution

Every fetch follows the same three tiers:

1. **Live** — hit GitHub and use the real answer.
2. **Cache** — replay the last successful response from `assets/cache/`.
3. **Synthetic** — deterministic data seeded by the username.

The contribution calendar is scraped from GitHub's public HTML fragment
(`/users/<login>/contributions`) rather than GraphQL, because that endpoint needs
no authentication at all. `GITHUB_TOKEN` is optional and only lifts REST rate
limits.

Synthetic calendars are not uniform noise — they model weekday bias, weekend
dips and multi-day bursts, so `python build.py --offline` still produces
something worth looking at, and produces the *same* thing every time.

---

## Development

```bash
python -m pip install -r requirements.txt

python build.py                  # full build
python build.py --offline        # no network at all
python build.py --only hero      # rebuild one asset
python build.py --speed 2.0      # re-time everything
python build.py --no-validate    # skip the invariant checks

python -m unittest discover -s tests -t . -v
python tools/validate.py
```

Then open `tools/preview.html` in a browser to watch every asset animate at its
real size, laid out the way the README arranges them. It loads from `../output`
with relative paths, so no server is needed.

`.github/workflows/build-profile.yml` runs the same sequence daily and commits
only when the output actually changed.

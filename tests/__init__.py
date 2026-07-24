"""Test suite for the animated profile generator.

The tests use :mod:`unittest` from the standard library so they run with a bare
interpreter — ``python -m unittest discover -s tests`` — as well as under
pytest.  A profile repository should never need a test runner installed just to
prove its build still works.
"""

from __future__ import annotations

import logging

# Several tests deliberately exercise the fallback paths, which log warnings by
# design.  Silencing the generator's loggers keeps the output readable without
# hiding real failures — those surface as assertions, never as log lines.
logging.getLogger("generator").setLevel(logging.ERROR)
for _module in (
    "generator.avatar_to_ascii",
    "generator.content",
    "generator.github",
    "generator.readme",
):
    logging.getLogger(_module).setLevel(logging.ERROR)

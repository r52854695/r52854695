"""Typing shim that lets :mod:`generator` stay import-independent of the root.

The ``generator`` package is a library: it accepts a configuration object and
renders SVG.  It should not import the top-level :mod:`config` module at
runtime, because doing so would make the package unusable outside this
repository's directory layout.

Under a type checker the alias below resolves to the real
:class:`config.Config` dataclass, so every attribute access in the generators
is fully checked.  At runtime it degrades to :data:`typing.Any`, which keeps
the import graph acyclic and the package relocatable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from config import Config

    ConfigLike = Config
else:
    ConfigLike = Any

__all__ = ["ConfigLike"]

"""core.env — environment-variable parsing helpers (isolated to avoid cycles)."""

from __future__ import annotations

import os

_TRUTHY = ("1", "true", "yes", "on")
_FALSY = ("0", "false", "no", "off")


def env_flag(name: str, default: bool = True,
             truthy: tuple = _TRUTHY, falsy: tuple = _FALSY) -> bool:
    """Parse a boolean env var, defaulting to ``default`` when unset or blank.

    Central, consistent parsing for the many ``CIK_*`` / ``*_ENABLED`` flags
    that previously each rolled their own ``os.environ.get(...) in (...)``
    check (with subtle drift — e.g. some stripped whitespace, some didn't, and
    ``core.digest`` treated an explicit empty string as "off"):
      * an unset or unrecognized value falls back to ``default``
      * a recognized truthy value (1/true/yes/on) -> True
      * a recognized falsy value (0/false/no/off) -> False
    """
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in truthy:
        return True
    if value in falsy:
        return False
    return default
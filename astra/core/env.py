"""core.env — environment-variable parsing helpers (isolated to avoid cycles)."""

from __future__ import annotations

import os

_TRUTHY = ("1", "true", "yes", "on")
_FALSY = ("0", "false", "no", "off")


def env_flag(name: str, default: bool = True,
             truthy: tuple = _TRUTHY, falsy: tuple = _FALSY) -> bool:
    """Parse a boolean env var, defaulting to ``default`` when unset or blank.

    Central, consistent parsing for the many ``ASTRA_*`` / ``*_ENABLED`` flags
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

#: Environment variables carried the ``CIK_`` prefix before the product was
#: renamed to Astra. Deployments outside this repo — a systemd unit file, a
#: shell profile, a CI secret — can still be exporting the old names, and a
#: silently ignored ``CIK_SECRET_KEY`` is worse than a loud failure: the app
#: would generate a fresh key and sign every existing session out.
_LEGACY_PREFIX = "CIK_"
_PREFIX = "ASTRA_"


def adopt_legacy_env() -> list[str]:
    """Copy any ``CIK_*`` variable to its ``ASTRA_*`` name, once, at startup.

    The new name always wins: a variable set under both prefixes keeps the
    ``ASTRA_`` value, so this can never override a deliberate setting. Returns
    the legacy names it adopted, for the caller to warn about.
    """
    adopted = []
    for name, value in list(os.environ.items()):
        if not name.startswith(_LEGACY_PREFIX):
            continue
        new_name = _PREFIX + name[len(_LEGACY_PREFIX):]
        if new_name not in os.environ:
            os.environ[new_name] = value
            adopted.append(name)
    return adopted

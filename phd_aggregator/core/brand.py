"""core.brand — Astra's fixed strings and the CLI header.

The identity spec (section 04) fixes this copy verbatim; it is kept here so the
CLI, the API and the dashboard cannot drift into three slightly different
products. The dashboard's copy of the same strings is ``dashboard/lib/brand.ts``
— change both together.

Naming rules the spec is explicit about:
  * "Astra" is always capitalised — never ASTRA in prose, never Astra.app
  * ``astra`` is lowercase in every code context
  * surfaces are "Astra CLI", "Astra Dashboard", "Astra Desktop"
  * domain terms are position, supervisor, programme, call, deadline,
    shortlist — never "job", never "lead"
"""

from __future__ import annotations

import os
import sys

NAME = "Astra"
TAGLINE = "Your academic constellation"
TOP_LINE = "Astra: your academic constellation"
DESCRIPTOR = "Positions and supervisors in academia"
DESCRIPTOR_LABEL = "Positions & supervisors"

MEMO = ("Astra finds academic positions and supervisors — PhD openings, "
        "postdocs, funded programmes and the people running them — and keeps "
        "the search on your own machine.")

SUMMARY = ("Academic openings are scattered across faculty pages, mailing "
           "lists and PDF calls. Astra collects them, matches them to your "
           "field and stage, and shows you who supervises what — so the search "
           "becomes a shortlist you can act on. Runs as a command, a local "
           "dashboard or a desktop app; your data never leaves your machine.")

#: Origin note. Colophons and about screens only — never used as a tagline.
MOTTO = "Per aspera ad astra"

# --- colour -------------------------------------------------------------------
# Accent #ec3013 on ground; #ff563c on ink, which is what a dark terminal is.
_ACCENT_ON_INK = (255, 86, 60)
_DIM = (155, 151, 151)


def _color_depth() -> int:
    """0 = no colour, 8 = basic, 24 = truecolor.

    Honours NO_COLOR (https://no-color.org) and never colours a redirected
    stream — piping the header into a file should not embed escape codes.
    """
    if os.environ.get("NO_COLOR") is not None:
        return 0
    if os.environ.get("TERM", "") == "dumb":
        return 0
    if not sys.stdout.isatty():
        return 0
    if os.environ.get("COLORTERM", "") in ("truecolor", "24bit"):
        return 24
    return 8


def _fg(text: str, rgb: tuple[int, int, int], depth: int) -> str:
    if depth == 0:
        return text
    if depth == 24:
        r, g, b = rgb
        return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"
    # Basic terminals: the accent is the one thing worth spending a colour on.
    return f"\x1b[31m{text}\x1b[0m" if rgb == _ACCENT_ON_INK else f"\x1b[90m{text}\x1b[0m"


def mark(depth: int | None = None) -> str:
    """The mark as three block glyphs — two ink nodes and the accent keystone.

    The spec forbids approximating the constellation in ASCII art: either these
    three blocks, or no mark at all. The keystone is the middle block.
    """
    depth = _color_depth() if depth is None else depth
    keystone = _fg("▪", _ACCENT_ON_INK, depth)
    return f"▪ {keystone} ▪"


def header(version: str = "", width: int = 72) -> str:
    """The Astra CLI header — lockup, descriptor, version, then a rule.

    This is the only place the lockup appears in the CLI; everything below is
    plain mono output. Returns a string rather than printing so callers can
    send it wherever they like (and so tests can assert on it).
    """
    depth = _color_depth()
    left = f"{mark(depth)}  {NAME.upper()}  {_fg(DESCRIPTOR_LABEL.upper(), _DIM, depth)}"
    # Pad using the VISIBLE length, not the escaped one.
    visible = len(f"{mark(0)}  {NAME.upper()}  {DESCRIPTOR_LABEL.upper()}")
    version = version.strip()
    if version:
        pad = max(1, width - visible - len(version))
        left += " " * pad + _fg(version, _DIM, depth)
    rule = _fg("─" * width, _DIM, depth)
    return f"{left}\n{rule}"


def print_header(version: str = "", stream=None) -> None:
    """Write the header to stderr by default.

    stderr, not stdout: the CLI's stdout is data people pipe into other tools,
    and a banner in the middle of it is a bug waiting to be reported.
    """
    print(header(version), file=stream or sys.stderr)

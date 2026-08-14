#!/usr/bin/env python3
"""Regenerate phd_aggregator/core/iso3166.py from pycountry.

The country table is VENDORED, not depended on: this app is used from behind a
censored connection where PyPI is often unreachable, and a 249-entry tuple is
cheaper than a runtime dependency. pycountry is needed only to regenerate it.

    pip install pycountry
    python scripts/gen_iso3166.py

Colloquial aliases ("Holland", "UK", "Deutschland") are deliberately NOT
generated here — they are judgement calls and live in core.normalize.
"""

from __future__ import annotations

import datetime
import os
import sys

TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "phd_aggregator", "core", "iso3166.py")

HEADER = '''"""core.iso3166 — the ISO-3166-1 country list, vendored as data.

GENERATED FILE — do not hand-edit. Regenerate with:

    pip install pycountry && python scripts/gen_iso3166.py

Vendored rather than depended on: the app must work on a machine that cannot
reach PyPI (this project is used from behind a censored connection), and a
{count}-entry table is far cheaper than a dependency. Source: pycountry
{version}, ISO-3166-1, generated {date}.

Each entry: (alpha-2, alpha-3, canonical name, extra official/common names).
Colloquial aliases ("Holland", "UK", "Deutschland") live in
core.normalize.EXTRA_ALIASES — those are judgement calls, not ISO data.
"""

from __future__ import annotations

#: (alpha_2, alpha_3, name, aliases)
COUNTRIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
'''


def main() -> int:
    try:
        import pycountry
    except ImportError:
        sys.stderr.write("pycountry is required: pip install pycountry\n")
        return 1

    rows = []
    for country in sorted(pycountry.countries, key=lambda c: c.alpha_2):
        name = country.name
        extra = [a for a in (getattr(country, "common_name", None),
                             getattr(country, "official_name", None))
                 if a and a != name]
        rows.append((country.alpha_2, country.alpha_3, name, extra))

    lines = [HEADER.format(count=len(rows), version=pycountry.__version__,
                           date=datetime.date.today())]
    for alpha2, alpha3, name, extra in rows:
        joined = ", ".join(f'"{a}"' for a in extra)
        tail = (f"({joined},)" if len(extra) == 1
                else f"({joined})" if extra else "()")
        lines.append(f'    ("{alpha2}", "{alpha3}", "{name}", {tail}),')
    lines.append(")")

    with open(TARGET, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {TARGET} — {len(rows)} countries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

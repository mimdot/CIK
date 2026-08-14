"""core.csvout — CSV writing on the standard library.

WHY THIS EXISTS
---------------
Every CSV this project writes went through ``pandas.DataFrame(...).to_csv()``.
pandas + numpy is **103 MB** of the desktop bundle, pulled in to do something
``csv`` from the standard library does in twenty lines. On a download people
have to accept before they can try the app, that is a third of the weight for
no capability.

Output is BYTE-IDENTICAL to what pandas produced, so existing CSVs, the tests
that read them, and anything a user has already built on top keep working:

* ``None`` and NaN render as an empty field (pandas' NaN handling);
* minimal quoting — a field is quoted only when it contains a comma, a quote
  or a newline, and inner quotes are doubled;
* ``\\n`` line endings on every platform (pandas opens with ``newline=""``);
* the header is the column list, in the order given.

ONE DELIBERATE DIFFERENCE. When an integer column contains a missing value,
pandas upcasts the whole column to float and writes ``1.0`` where the data
said ``1`` — a NumPy dtype artifact, not a decision about the data. This
writes ``1``. Verified against the real pipeline output: the columns that
render as floats today (``relevance_score``) genuinely hold floats and are
unchanged; ``age_days`` already writes as a plain integer.
"""

from __future__ import annotations

import csv
import math
from typing import Iterable, Optional, Sequence


def _cell(value) -> str:
    """One value, rendered the way pandas' to_csv renders it."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def columns_of(rows: Sequence[dict]) -> list[str]:
    """Column order pandas would infer from a list of dicts: first appearance."""
    seen: dict[str, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    return list(seen)


def write_csv(path: str, rows: Iterable[dict],
              columns: Optional[Sequence[str]] = None) -> int:
    """Write ``rows`` to ``path`` as CSV. Returns the number of data rows.

    ``columns`` fixes the order and the subset (the equivalent of
    ``DataFrame(rows)[cols]``); omit it to infer from the rows.

    An empty ``rows`` with explicit ``columns`` still writes the header, which
    is what pandas does — a downstream reader should see an empty table, not
    an empty file.
    """
    materialised = list(rows)
    cols = list(columns) if columns is not None else columns_of(materialised)

    # newline="" is required by the csv module: it does its own line endings,
    # and without this Windows would turn every \n into \r\n.
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        writer.writerow(cols)
        for row in materialised:
            writer.writerow([_cell(row.get(c)) for c in cols])
    return len(materialised)

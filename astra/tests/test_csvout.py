"""CSV writing on the standard library, replacing pandas.

pandas + numpy was 103 MB of a 346 MB desktop download, imported to do what
the `csv` module does in twenty lines. These tests pin the output format so
existing CSVs, the code that reads them, and anything a user has already built
on top keep working.

Where pandas is installed, the parametrised cases below compare BYTE FOR BYTE
against it. Where it is not (the shipped bundle excludes it), they skip and
the explicit format assertions still run.
"""

from __future__ import annotations

import csv as csv_mod

import pytest

from core.csvout import columns_of, write_csv


CASES = {
    "typical pipeline row": ([
        {"title": "PhD in Radio Astronomy", "institution": "MPIfR",
         "country": "Germany", "relevance_score": 12.5, "is_new": True,
         "matched_keywords": "radio astronomy; ISM", "url": "https://x/1"},
        {"title": "PhD, with a comma", "institution": None,
         "country": "France", "relevance_score": 0.0, "is_new": False,
         "matched_keywords": "", "url": "https://x/2"},
    ], None),
    "quotes, newlines, unicode": ([
        {"a": 'He said "hello"', "b": "line1\nline2",
         "c": "Côte d'Ivoire", "d": "tab\there"},
        {"a": "plain", "b": "", "c": None, "d": "semi;colon"},
    ], None),
    "explicit column subset and order": ([
        {"z": 1, "a": 2, "m": 3}, {"z": 4, "a": 5, "m": 6},
    ], ["m", "z"]),
    "floats and ints": ([{"f": 12.5, "g": 0.0, "h": 1, "i": -3.25}], None),
    "empty rows, explicit columns": ([], ["a", "b", "c"]),
}


@pytest.mark.parametrize("name", list(CASES))
def test_output_is_byte_identical_to_pandas(name, tmp_path):
    # Only this test needs pandas — it exists to prove parity. The format
    # assertions below must run everywhere, including the pandas-free bundle.
    pd = pytest.importorskip("pandas", reason="only needed to prove parity")
    rows, cols = CASES[name]
    ours, theirs = tmp_path / "ours.csv", tmp_path / "theirs.csv"

    frame = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
    if cols:
        frame = frame[cols]
    frame.to_csv(theirs, index=False)
    write_csv(str(ours), rows, cols)

    assert ours.read_bytes() == theirs.read_bytes()


# --- the format, asserted directly (runs with or without pandas) ------------

def test_none_becomes_an_empty_field(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"a": None, "b": "x"}])
    assert path.read_text(encoding="utf-8") == "a,b\n,x\n"


def test_quoting_is_minimal_and_quotes_are_doubled(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"a": "no comma", "b": "has,comma",
                           "c": 'say "hi"'}])
    text = path.read_text(encoding="utf-8")
    assert "no comma" in text and '"has,comma"' in text
    assert '"say ""hi"""' in text


def test_line_endings_are_unix_on_every_platform(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"a": 1}, {"a": 2}])
    assert b"\r\n" not in path.read_bytes()


def test_booleans_render_as_python_literals(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"a": True, "b": False}])
    assert path.read_text(encoding="utf-8") == "a,b\nTrue,False\n"


def test_a_header_is_written_even_with_no_rows(tmp_path):
    """A downstream reader should see an empty TABLE, not an empty file."""
    path = tmp_path / "a.csv"
    assert write_csv(str(path), [], ["a", "b"]) == 0
    assert path.read_text(encoding="utf-8") == "a,b\n"


def test_columns_are_inferred_in_first_appearance_order():
    assert columns_of([{"z": 1, "a": 2}, {"m": 3, "z": 4}]) == ["z", "a", "m"]


def test_explicit_columns_select_and_order(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"z": 1, "a": 2, "m": 3}], columns=["m", "z"])
    assert path.read_text(encoding="utf-8") == "m,z\n3,1\n"


def test_a_missing_key_is_an_empty_field_not_a_crash(tmp_path):
    path = tmp_path / "a.csv"
    write_csv(str(path), [{"a": 1}, {"b": 2}])
    assert path.read_text(encoding="utf-8") == "a,b\n1,\n,2\n"


def test_round_trips_through_the_csv_reader(tmp_path):
    """Whatever we write, the stdlib reader must give back."""
    rows = [{"a": 'x,y "z"', "b": "line\nbreak", "c": None}]
    path = tmp_path / "a.csv"
    write_csv(str(path), rows)
    with open(path, newline="", encoding="utf-8") as fh:
        back = list(csv_mod.DictReader(fh))
    assert back[0]["a"] == 'x,y "z"'
    assert back[0]["b"] == "line\nbreak"
    assert back[0]["c"] == ""


# --- the pipeline no longer needs pandas at all ------------------------------

def test_the_pipeline_writes_its_csv_without_pandas(tmp_path, monkeypatch):
    """The shipped bundle excludes pandas — the pipeline must not need it."""
    import argparse
    import builtins

    from core.config import build_config
    from core.records import make_record
    from pipeline.run import run

    real_import = builtins.__import__

    def blocked(name, *a, **kw):
        if name.split(".")[0] in ("pandas", "numpy"):
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)

    cfg = build_config(argparse.Namespace(field="astronomy", no_config=True))
    cfg.output_path = str(tmp_path / "positions")
    cfg.write_html = False
    cfg.state_file = str(tmp_path / ".seen.json")

    kept = run(cfg, injected_raw=[make_record(
        title="PhD in Radio Astronomy", url="https://x/1", institution="MPIfR",
        short_description="radio astronomy interstellar medium", source="aas")])

    assert len(kept) == 1
    header = open(cfg.csv_path, encoding="utf-8").readline()
    assert header.startswith("title,institution,country")

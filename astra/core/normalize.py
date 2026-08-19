"""core.normalize — country and institution auto-correct (Phase 2D).

WHY
---
Country handling used to be a 53-entry hand-written alias map: fine for the
countries someone happened to think of, silent for the other ~200, and with no
tolerance for a typo. Institutions had no normalisation at all, so "MIT",
"M.I.T." and "Massachusetts Institute of Technology" were three different
things to dedupe and grouping.

WHAT THIS DOES
--------------
* **Countries** resolve against the full vendored ISO-3166 list (249 entries:
  names, official/common names, alpha-2 and alpha-3 codes) plus a curated
  alias table for the colloquial forms ISO does not carry ("Holland", "UK",
  "Deutschland", "USA").
* **Institutions** resolve against a curated alias table plus the institution
  names the field profiles already ship in their ``departments:`` blocks —
  several hundred real universities and institutes, free.
* **Both tolerate misspellings** via ``difflib`` (stdlib — no dependency),
  with a similarity floor so a wrong answer is never invented.

USED ON BOTH SIDES, as the brief requires:
* on **user input**, to suggest the corrected form ("Germny" -> "Germany?");
* on **scraped data**, to normalise before dedupe and grouping.

The floor matters more than the cleverness: below it this returns ``None``
rather than guessing, because silently turning "Niger" into "Nigeria" is worse
than leaving it alone.
"""

from __future__ import annotations

import difflib
import functools
import re
import unicodedata
from typing import NamedTuple, Optional

from core.iso3166 import COUNTRIES

#: Minimum difflib ratio for a fuzzy hit. 0.86 accepts "Germny"/"Deutschlnd"
#: and rejects "Niger"/"Nigeria" (0.83) — verified in tests.
FUZZY_THRESHOLD = 0.86
#: Short strings are mostly codes; fuzzy-matching them invites nonsense
#: ("US" -> "UZ"). Exact/alias lookup still handles codes.
MIN_FUZZY_LENGTH = 5


class Suggestion(NamedTuple):
    """A resolved name plus how it was reached."""
    value: str
    #: "exact" | "alias" | "code" | "fuzzy"
    how: str
    #: 1.0 for exact/alias/code; the difflib ratio for a fuzzy hit.
    score: float

    @property
    def is_correction(self) -> bool:
        """True when the input was not already the canonical form."""
        return self.how in ("alias", "code", "fuzzy")


# --- colloquial country aliases ISO-3166 does not carry ----------------------
# Judgement calls, deliberately separate from the generated ISO data.
EXTRA_ALIASES: dict[str, tuple[str, ...]] = {
    "United Kingdom": ("uk", "u.k.", "great britain", "britain", "gb",
                       "england", "scotland", "wales", "northern ireland",
                       "united kingdom of great britain"),
    "United States": ("usa", "u.s.a.", "u.s.", "us", "america",
                      "united states of america", "the states"),
    "Germany": ("deutschland", "brd", "federal republic of germany"),
    "Netherlands": ("holland", "the netherlands", "nederland"),
    "Switzerland": ("schweiz", "suisse", "svizzera", "helvetia"),
    "Czechia": ("czech republic", "czech rep", "cesko"),
    "Türkiye": ("turkey", "turkiye"),
    "Korea, Republic of": ("south korea", "korea", "republic of korea",
                           "s. korea", "daehan minguk"),
    "Korea, Democratic People's Republic of": ("north korea",),
    "Russian Federation": ("russia",),
    "Iran, Islamic Republic of": ("iran", "islamic republic of iran"),
    "Viet Nam": ("vietnam",),
    "Syrian Arab Republic": ("syria",),
    "Lao People's Democratic Republic": ("laos",),
    "Tanzania, United Republic of": ("tanzania",),
    "Bolivia, Plurinational State of": ("bolivia",),
    "Venezuela, Bolivarian Republic of": ("venezuela",),
    "Moldova, Republic of": ("moldova",),
    "Taiwan, Province of China": ("taiwan",),
    "Hong Kong": ("hong kong sar", "hongkong"),
    "Macao": ("macau",),
    "Brunei Darussalam": ("brunei",),
    "Cabo Verde": ("cape verde",),
    "Côte d'Ivoire": ("ivory coast", "cote d'ivoire", "cote divoire"),
    "Congo, The Democratic Republic of the": ("dr congo", "drc", "zaire"),
    "Palestine, State of": ("palestine",),
    "Micronesia, Federated States of": ("micronesia",),
    "Spain": ("españa", "espana"),
    "France": ("french republic",),
    "Italy": ("italia",),
    "Sweden": ("sverige",),
    "Norway": ("norge",),
    "Denmark": ("danmark",),
    "Finland": ("suomi",),
    "Austria": ("österreich", "osterreich"),
    "Belgium": ("belgique", "belgie", "belgië"),
    "Poland": ("polska",),
    "Greece": ("hellas", "hellenic republic"),
    "Japan": ("nippon", "nihon"),
    "China": ("prc", "people's republic of china", "mainland china"),
    "India": ("bharat",),
    "Ireland": ("republic of ireland", "eire", "éire"),
}

# --- institution aliases -----------------------------------------------------
# The abbreviations job ads actually use. The long tail comes free from the
# field profiles' departments: blocks (see _profile_institutions).
INSTITUTION_ALIASES: dict[str, tuple[str, ...]] = {
    "Massachusetts Institute of Technology": ("mit", "m.i.t."),
    "California Institute of Technology": ("caltech", "cal tech"),
    "Swiss Federal Institute of Technology Zurich": ("eth", "eth zurich",
                                                     "eth zürich", "ethz"),
    "Swiss Federal Institute of Technology Lausanne": ("epfl",),
    "University of California, Berkeley": ("uc berkeley", "berkeley", "ucb"),
    "University of California, Los Angeles": ("ucla",),
    "University College London": ("ucl",),
    "Imperial College London": ("imperial college", "imperial"),
    "London School of Economics": ("lse",),
    "University of Oxford": ("oxford", "oxford university"),
    "University of Cambridge": ("cambridge", "cambridge university"),
    "Ludwig Maximilian University of Munich": ("lmu", "lmu munich",
                                               "lmu münchen"),
    "Technical University of Munich": ("tum", "tu munich", "tu münchen"),
    "Max Planck Institute for Radio Astronomy": ("mpifr",),
    "Max Planck Institute for Astronomy": ("mpia",),
    "Max Planck Institute for Astrophysics": ("mpa",),
    "European Southern Observatory": ("eso",),
    "European Space Agency": ("esa",),
    "National Aeronautics and Space Administration": ("nasa",),
    "Delft University of Technology": ("tu delft", "tudelft"),
    "Eindhoven University of Technology": ("tu eindhoven", "tue"),
    "KTH Royal Institute of Technology": ("kth",),
    "Nanyang Technological University": ("ntu",),
    "National University of Singapore": ("nus",),
    "Indian Institute of Technology": ("iit",),
    "Chinese Academy of Sciences": ("cas",),
    "Centre National de la Recherche Scientifique": ("cnrs",),
    "Institut National de la Santé et de la Recherche Médicale": ("inserm",),
    "Karlsruhe Institute of Technology": ("kit",),
    "Georgia Institute of Technology": ("georgia tech",),
    "University of North Carolina": ("unc",),
    "New York University": ("nyu",),
    "Johns Hopkins University": ("jhu", "johns hopkins"),
}


def _fold(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    "Côte d'Ivoire", "COTE D IVOIRE" and "cote-d'ivoire" all fold together.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", stripped)
    return re.sub(r"\s+", " ", cleaned).strip().casefold()


@functools.lru_cache(maxsize=1)
def _country_index() -> dict[str, str]:
    """folded form -> canonical country name (names, codes, every alias)."""
    index: dict[str, str] = {}
    for alpha2, alpha3, name, extra in COUNTRIES:
        index.setdefault(_fold(name), name)
        index.setdefault(_fold(alpha2), name)
        index.setdefault(_fold(alpha3), name)
        for alias in extra:
            index.setdefault(_fold(alias), name)
    for canonical, aliases in EXTRA_ALIASES.items():
        # An alias must not resurrect a country the ISO list does not know.
        target = index.get(_fold(canonical), canonical)
        for alias in aliases:
            index[_fold(alias)] = target
    return index


@functools.lru_cache(maxsize=1)
def _country_names() -> tuple[str, ...]:
    return tuple(name for _, _, name, _ in COUNTRIES)


def _profile_institutions() -> set[str]:
    """Institution names the shipped field profiles already list.

    Several hundred real universities and institutes, already curated per
    discipline — reused here rather than maintaining a second list.
    """
    names: set[str] = set()
    try:
        from core.config import list_field_profiles, load_field_profile
        for field_name in list_field_profiles():
            profile = load_field_profile(field_name) or {}
            for entry in (profile.get("departments") or []):
                if isinstance(entry, dict):
                    institution = str(entry.get("institution") or "").strip()
                    if institution:
                        # Department registries write "University — Institute";
                        # the university is the part worth matching.
                        names.add(re.split(r"\s+[—–-]\s+", institution)[0])
    except Exception:  # never let a bad profile break normalisation
        pass
    return names


@functools.lru_cache(maxsize=1)
def _institution_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for canonical, aliases in INSTITUTION_ALIASES.items():
        index.setdefault(_fold(canonical), canonical)
        for alias in aliases:
            index[_fold(alias)] = canonical
    for name in _profile_institutions():
        index.setdefault(_fold(name), name)
    return index


def _resolve(value: Optional[str], index: dict[str, str],
             threshold: float = FUZZY_THRESHOLD) -> Optional[Suggestion]:
    """Exact -> alias -> fuzzy, or None. Never guesses below the threshold.

    Fuzzy matching runs over the WHOLE index, aliases included, so a
    misspelled alias ("Nederlnd", "Deutschlnd") resolves too — and the result
    is still the canonical name, because the index maps back to it.
    """
    if not value or not str(value).strip():
        return None
    raw = str(value).strip()
    folded = _fold(raw)
    if not folded:
        return None

    hit = index.get(folded)
    if hit is not None:
        how = "exact" if _fold(hit) == folded else "alias"
        if len(raw) <= 3 and how == "alias":
            how = "code"
        return Suggestion(hit, how, 1.0)

    if len(folded) < MIN_FUZZY_LENGTH:
        return None      # too short to fuzzy-match safely ("US" -> "UZ")

    # Only match against keys of a comparable length; difflib will happily
    # rate a short string against a much longer one.
    pool = [k for k in index if abs(len(k) - len(folded)) <= max(4, len(folded) // 2)]
    close = difflib.get_close_matches(folded, pool, n=1, cutoff=threshold)
    if not close:
        return None
    ratio = difflib.SequenceMatcher(None, folded, close[0]).ratio()
    return Suggestion(index[close[0]], "fuzzy", round(ratio, 3))


def suggest_country(value: Optional[str]) -> Optional[Suggestion]:
    """Resolve a country, tolerating codes, aliases and misspellings.

    >>> suggest_country("DE").value, suggest_country("Deutschland").value
    ('Germany', 'Germany')
    >>> suggest_country("Germny").how
    'fuzzy'
    """
    return _resolve(value, _country_index())


def normalize_country(value: Optional[str]) -> Optional[str]:
    """The canonical country name, or None. For scraped data and dedupe."""
    hit = suggest_country(value)
    return hit.value if hit else None


def suggest_institution(value: Optional[str]) -> Optional[Suggestion]:
    """Resolve an institution, tolerating abbreviations and misspellings.

    >>> suggest_institution("MIT").value
    'Massachusetts Institute of Technology'
    """
    return _resolve(value, _institution_index())


def normalize_institution(value: Optional[str]) -> Optional[str]:
    """The canonical institution name, or the cleaned input when unknown.

    Unlike countries this does NOT return None for an unrecognised name: the
    world has far more institutions than any list can hold, and dropping a
    real employer would be worse than leaving its name as written.
    """
    if not value or not str(value).strip():
        return None
    hit = suggest_institution(value)
    return hit.value if hit else re.sub(r"\s+", " ", str(value)).strip()


def country_choices() -> list[str]:
    """Every canonical country name, for a picker or type-ahead."""
    return sorted(_country_names())

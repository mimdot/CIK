"""core.position_types — the position-type registry (Phase 2C).

WHY
---
Position types used to be two hardcoded dicts in :mod:`core.taxonomy`
(``_TYPE_PATTERNS`` + ``_TYPE_PRIORITY``) plus one regex of "PhD mentioned as a
requirement" noise. Adding Master's or Scholarship meant editing Python in
several places, and PhD vs postdoc could never be presented as a real user
choice because nothing described the types as data.

They are now entries in ``position_types.yaml``: label, help text, whether the
type is enabled (offered to users) or merely classified, and its own patterns.
Shipping a new type is a YAML edit.

SAFETY
------
Classification is load-bearing — every kept record passes through it — so the
built-in defaults below are a complete, working copy of the historical
behaviour. A missing, unparseable or partial YAML degrades to them with a
warning rather than silently classifying everything as "unknown".
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field as dc_field
from typing import Optional

log = logging.getLogger("phd_aggregator")

TYPES_FILE = "position_types.yaml"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class PositionType:
    """One hunt-able (or merely recognised) kind of position."""
    name: str
    label: str
    description: str = ""
    #: False = shipped but not offered yet; the UI shows it as "coming soon".
    enabled: bool = True
    #: False = classified internally but never a user-facing target
    #: (faculty/staff exist so senior ads are recognised and excluded).
    selectable: bool = True
    patterns: tuple[str, ...] = ()
    requirement_noise: tuple[str, ...] = ()
    _rx: tuple = dc_field(default=(), repr=False, compare=False)
    _noise_rx: Optional[re.Pattern] = dc_field(default=None, repr=False,
                                               compare=False)

    @property
    def is_offered(self) -> bool:
        """True when a user may pick this type for a search right now."""
        return self.enabled and self.selectable

    def matches(self, text: str) -> bool:
        return any(rx.search(text) for rx in self._rx)

    def strip_requirement_noise(self, text: str) -> str:
        """Remove "must hold a PhD"-style phrases before desc classification."""
        if not text or self._noise_rx is None:
            return text or ""
        return self._noise_rx.sub(" ", text)


# --- built-in defaults: a complete copy of the historical behaviour ----------
# Kept verbatim so a broken YAML can never change what qualifies.
_BUILTIN: list[dict] = [
    {
        "name": "phd", "label": "PhD",
        "description": "Doctoral positions and studentships.",
        "patterns": [
            r"\bph\.?\s?d\b", r"\bdphil\b", r"\bdoctorate\b",
            r"(?<!post-)(?<!post )\bdoctoral\b",
            r"\bpre-?doctoral", r"\bpredoc",
            r"\bgraduate (student|researcher|position|fellowship|assistantship|programme|program)",
            r"\bstudentship", r"\bdoktorand", r"\bpromovend", r"\bdoctorant",
            r"th[eè]se de doctorat", r"\bdottorato", r"\bdoctorado",
            r"first[- ]stage researcher", r"early[- ]stage researcher",
        ],
        "requirement_noise": [
            r"(?:must|should|to) (?:have|hold)(?: been awarded)? (?:a|an|the) "
            r"(?:ph\.?d|doctorate|doctoral degree)",
            r"ph\.?d(?: degree)? (?:is |are )?(?:required|essential|preferred|desirable)",
            r"hold(?:ing|s)? a (?:ph\.?d|doctorate|doctoral degree)",
            r"ph\.?d in hand",
            r"completed (?:a |their |your )?ph\.?d",
            r"ph\.?d \(or equivalent\)",
            r"after (?:your|the|their) ph\.?d",
            r"ph\.?d (?:degree )?or equivalent",
            r"newly minted .{0,20}ph\.?d",
        ],
    },
    {
        "name": "postdoc", "label": "Postdoc",
        "description": "Postdoctoral research positions and research fellowships.",
        "patterns": [r"post-?\s?doc", r"postdoctoral",
                     r"research (fellow|associate)\b", r"junior research"],
    },
    {
        "name": "faculty", "label": "Faculty", "selectable": False,
        "description": "Professorships, lectureships and tenure-track posts.",
        "patterns": [r"\bprofessor", r"\blecturer\b", r"tenure", r"faculty",
                     r"assistant prof", r"associate prof", r"\breader\b",
                     r"\bchair\b", r"\bdozent", r"director general"],
    },
    {
        "name": "staff", "label": "Staff", "selectable": False,
        "description": "Engineering, technical, scientist and administrative roles.",
        "patterns": [
            r"\bengineer\b", r"\btechnician\b", r"administrator",
            r"\bmanager\b", r"software developer", r"data scientist",
            r"support officer", r"\bscientist\b", r"\badvis[eo]r\b",
            r"\bintern(ship)?\b", r"\bofficer\b", r"\bsecretary\b",
            r"procurement", r"\bcoordinator\b",
            r"junior professional", r"young researcher",
            r"research specialist", r"research engineer",
            r"scientific programmer", r"senior researcher",
            r"research scientist", r"visiting researcher",
            r"researcher (member|assistant|position)",
        ],
    },
]


def _compile(entry: dict) -> Optional[PositionType]:
    """Build one PositionType, dropping it if its regexes do not compile."""
    name = str(entry.get("name") or "").strip().lower()
    if not name:
        log.warning("position type without a name — ignored")
        return None
    patterns = [str(p) for p in (entry.get("patterns") or []) if str(p).strip()]
    if not patterns:
        log.warning("position type %r has no patterns — ignored", name)
        return None
    try:
        rx = tuple(re.compile(p, re.I) for p in patterns)
    except re.error as exc:
        log.warning("position type %r has an invalid pattern (%s) — ignored",
                    name, exc)
        return None
    noise = [str(p) for p in (entry.get("requirement_noise") or [])
             if str(p).strip()]
    noise_rx = None
    if noise:
        try:
            noise_rx = re.compile("|".join(noise), re.I)
        except re.error as exc:
            log.warning("position type %r: bad requirement_noise (%s) — "
                        "ignored", name, exc)
    return PositionType(
        name=name,
        label=str(entry.get("label") or name.title()),
        description=str(entry.get("description") or ""),
        enabled=bool(entry.get("enabled", True)),
        selectable=bool(entry.get("selectable", True)),
        patterns=tuple(patterns),
        requirement_noise=tuple(noise),
        _rx=rx,
        _noise_rx=noise_rx,
    )


def _yaml_path() -> Optional[str]:
    """position_types.yaml, in the CWD or next to the package."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for base in (os.getcwd(), here):
        candidate = os.path.join(base, TYPES_FILE)
        if os.path.isfile(candidate):
            return candidate
    return None


def _load() -> list[PositionType]:
    """Load the registry: YAML if usable, else the built-in defaults."""
    path = _yaml_path()
    entries: list[dict] = []
    if path:
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                # Mapping preserves file order in Python 3.7+, and order IS
                # the classifier's priority.
                entries = [{"name": k, **v} for k, v in data.items()
                           if isinstance(v, dict)]
            else:
                log.warning("%s: top level must be a mapping — using built-in "
                            "position types", path)
        except ImportError:
            log.debug("PyYAML unavailable — using built-in position types")
        except Exception as exc:
            log.warning("could not read %s (%s) — using built-in position "
                        "types", path, exc)

    loaded = [t for t in (_compile(e) for e in entries) if t is not None]
    # Every historically-classified type must survive, or a typo in the YAML
    # would silently change what qualifies.
    required = {e["name"] for e in _BUILTIN}
    if not required.issubset({t.name for t in loaded}):
        if loaded:
            missing = sorted(required - {t.name for t in loaded})
            log.warning("%s is missing required position type(s) %s — using "
                        "built-in defaults", path, ", ".join(missing))
        return [t for t in (_compile(e) for e in _BUILTIN) if t is not None]
    log.debug("loaded %d position types from %s", len(loaded), path)
    return loaded


#: The registry, in classifier-priority order. Reload with reload_types().
TYPES: list[PositionType] = _load()


def reload_types() -> list[PositionType]:
    """Re-read the YAML (used by tests that write a temporary registry)."""
    global TYPES
    TYPES = _load()
    return TYPES


def get(name: str) -> Optional[PositionType]:
    lowered = (name or "").strip().lower()
    return next((t for t in TYPES if t.name == lowered), None)


def type_names() -> list[str]:
    return [t.name for t in TYPES]


def offered_types() -> list[PositionType]:
    """Types a user can search for right now (PhD, Postdoc)."""
    return [t for t in TYPES if t.is_offered]


def coming_soon_types() -> list[PositionType]:
    """Selectable but not enabled yet — shown disabled in the UI."""
    return [t for t in TYPES if t.selectable and not t.enabled]

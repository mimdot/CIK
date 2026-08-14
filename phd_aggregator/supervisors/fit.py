"""supervisors.fit — an explainable 0-100 supervisor fit score (Phase 4C).

WHAT WAS WRONG
--------------
``fit_score`` was whatever the ranking pass happened to produce: roughly
"h-index plus a bonus per recent paper", an unbounded raw number on no
particular scale. Two candidates from different fields, countries or backends
were not comparable, a "43" meant nothing on its own, and nothing anywhere
said how it was arrived at. Hence: "the fit value is very strange and not
adjusted / not usable".

WHAT IT MEANS NOW
-----------------
Fit answers exactly one question: **how well does this researcher match what
you are looking for, as a potential supervisor?** It is the weighted sum of
four bounded components, so it is always 0-100 and always comparable:

    topic     40   how much of YOUR vocabulary appears in their recent work
    recency   25   how actively they publish in the window (not lifetime)
    seniority 20   how often they are last/corresponding author — i.e. a PI
                   running a group, not a group member
    country   15   whether their recent work confirms the country you asked for

Every component is returned alongside the number, with the terms that produced
it, so clicking a score can show its reasoning instead of a bare figure.

Deliberate choices:
* recent output beats lifetime output — a prolific 1990s record does not make
  someone a good supervisor today;
* seniority uses the per-profile signal (economics orders authors
  alphabetically, so last-author means nothing there and the weight is
  redistributed rather than awarded blindly);
* the scale is anchored, not relative — a weak field does not get inflated
  scores just because everyone in it is weak.
"""

from __future__ import annotations

from typing import Optional

from core.taxonomy import _compile_term

# Weights sum to 100. Anchored, not relative to the result set.
WEIGHT_TOPIC = 40.0
WEIGHT_RECENCY = 25.0
WEIGHT_SENIORITY = 20.0
WEIGHT_COUNTRY = 15.0

# Recent papers at which the recency component saturates. Beyond this, more
# output says nothing further about supervisory availability.
RECENCY_SATURATION = 12
# Share of recent papers as senior author at which seniority saturates. A PI
# is not last author on literally everything.
SENIORITY_SATURATION = 0.5
# Share of the requested keywords that earns a full topic score.
TOPIC_FULL_MARKS_SHARE = 0.6
# A researcher CONFIRMED to be in a different country than the one asked for
# is not a near miss — you cannot go and work with them. Their remaining
# strengths are kept visible but heavily discounted, so they sink below every
# genuine local candidate instead of ranking on raw output alone.
WRONG_COUNTRY_PENALTY = 0.35


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def topic_component(keywords: list[str], haystack: str) -> tuple[float, list[str]]:
    """Share of the user's keywords that appear in the researcher's work.

    Uses the SAME matching rules as the relevance engine, so a term that
    matches a position also matches a supervisor.
    """
    terms = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if not terms:
        # Nothing asked for: this component cannot discriminate, so award the
        # neutral middle rather than a misleading 0 or 100.
        return 0.5, []
    text = haystack or ""
    matched = []
    for term in terms:
        try:
            if _compile_term(term).search(text):
                matched.append(term)
        except Exception:
            continue
    # Full marks at 60% of the keyword list. An earlier 25% threshold gave a
    # single match out of four terms a perfect topic score, which flattened
    # the whole scale — everyone with one hit looked like a perfect match.
    target = max(1.0, len(terms) * TOPIC_FULL_MARKS_SHARE)
    return _clamp(len(matched) / target), matched


def recency_component(recent_papers: int) -> float:
    """How active they are NOW, saturating so volume cannot dominate."""
    return _clamp(max(0, recent_papers) / RECENCY_SATURATION)


def seniority_component(senior_papers: int, recent_papers: int,
                        signal: str = "last_author") -> Optional[float]:
    """How often they are the senior author — the PI signal.

    Returns ``None`` when the field's author order carries no seniority
    information (economics and finance order alphabetically). The caller then
    redistributes this weight instead of scoring everyone zero.
    """
    if signal == "none":
        return None
    if recent_papers <= 0:
        return 0.0
    share = max(0, senior_papers) / recent_papers
    return _clamp(share / SENIORITY_SATURATION)


def country_component(candidate_country: Optional[str],
                      wanted_country: Optional[str]) -> float:
    """1.0 confirmed in-country, 0.4 unverified, 0.0 confirmed elsewhere."""
    if not wanted_country:
        return 1.0                      # nothing asked: no penalty
    if not candidate_country or candidate_country == "unverified":
        return 0.4
    return 1.0 if candidate_country == wanted_country else 0.0


def _is_wrong_country(candidate_country: Optional[str],
                      wanted_country: Optional[str]) -> bool:
    return bool(wanted_country and candidate_country
                and candidate_country != "unverified"
                and candidate_country != wanted_country)


def passes_relevance_gate(candidate: dict, keywords: list[str]) -> bool:
    """True if the researcher's RECENT work touches the requested topics.

    Phase 4B: a productive, senior, correctly-located researcher who works on
    something else entirely is not a weak match — they are the wrong person,
    and they are exactly what "I saw non-related field results" was about.
    Scoring alone could not sink them, because output and seniority still
    earned points. This gate removes them.

    With no keywords requested nothing can be judged, so nobody is excluded.
    """
    terms = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if not terms:
        return True
    haystack = " \n ".join(str(candidate.get(k) or "")
                           for k in ("topics", "representative_papers"))
    _, matched = topic_component(terms, haystack)
    return bool(matched)


def compute_fit(candidate: dict, keywords: list[str],
                wanted_country: Optional[str] = None,
                senior_signal: str = "last_author") -> dict:
    """Score one candidate 0-100 and return the reasoning alongside it.

    ``candidate`` is a ranked row as produced by the OpenAlex/ADS/arXiv paths:
    ``topics``, ``representative_papers``, ``papers``, ``last_author_papers``,
    ``country``.
    """
    haystack = " \n ".join(str(candidate.get(k) or "")
                           for k in ("topics", "representative_papers",
                                     "institution"))
    recent = int(candidate.get("papers") or 0)
    senior = int(candidate.get("last_author_papers") or 0)

    topic, matched_terms = topic_component(keywords, haystack)
    recency = recency_component(recent)
    seniority = seniority_component(senior, recent, senior_signal)
    country = country_component(candidate.get("country"), wanted_country)

    parts = [
        ("topic", topic, WEIGHT_TOPIC),
        ("recency", recency, WEIGHT_RECENCY),
        ("country", country, WEIGHT_COUNTRY),
    ]
    if seniority is None:
        # Author order says nothing in this field — spread its weight over the
        # components that DO carry signal, rather than penalising everyone.
        total_weight = WEIGHT_TOPIC + WEIGHT_RECENCY + WEIGHT_COUNTRY
        scale = 100.0 / total_weight
        parts = [(n, v, w * scale) for n, v, w in parts]
    else:
        parts.append(("seniority", seniority, WEIGHT_SENIORITY))

    score = sum(value * weight for _, value, weight in parts)
    wrong_country = _is_wrong_country(candidate.get("country"), wanted_country)
    if wrong_country:
        score *= WRONG_COUNTRY_PENALTY
    breakdown = {
        name: {
            "value": round(value, 3),
            "weight": round(weight, 1),
            "points": round(value * weight, 1),
        }
        for name, value, weight in parts
    }
    return {
        "fit_score": round(score, 1),
        "fit_breakdown": breakdown,
        "fit_matched_terms": matched_terms,
        "fit_wrong_country": wrong_country,
        "fit_explanation": explain(breakdown, matched_terms, recent, senior,
                                   candidate.get("country"), wanted_country,
                                   wrong_country),
    }


def explain(breakdown: dict, matched_terms: list[str], recent: int,
            senior: int, candidate_country: Optional[str],
            wanted_country: Optional[str],
            wrong_country: bool = False) -> str:
    """One human sentence per component — never a bare number."""
    bits: list[str] = []
    topic = breakdown.get("topic")
    if topic:
        if matched_terms:
            shown = ", ".join(matched_terms[:4])
            more = f" (+{len(matched_terms) - 4} more)" if len(matched_terms) > 4 else ""
            bits.append(f"{topic['points']:.0f} pts — matches your terms: "
                        f"{shown}{more}")
        else:
            bits.append(f"{topic['points']:.0f} pts — none of your keywords "
                        "appear in their recent work")
    recency = breakdown.get("recency")
    if recency:
        bits.append(f"{recency['points']:.0f} pts — {recent} recent paper"
                    f"{'' if recent == 1 else 's'} in the window")
    seniority = breakdown.get("seniority")
    if seniority:
        bits.append(f"{seniority['points']:.0f} pts — senior author on "
                    f"{senior} of {recent}")
    else:
        bits.append("seniority not scored — this field orders authors "
                    "alphabetically")
    country = breakdown.get("country")
    if country:
        if not wanted_country:
            bits.append(f"{country['points']:.0f} pts — no country requested")
        elif candidate_country == wanted_country:
            bits.append(f"{country['points']:.0f} pts — confirmed in "
                        f"{wanted_country}")
        elif not candidate_country or candidate_country == "unverified":
            bits.append(f"{country['points']:.0f} pts — country unverified")
        else:
            bits.append(f"0 pts — based in {candidate_country}, not "
                        f"{wanted_country}")
    if wrong_country:
        bits.append(f"score reduced to {int(WRONG_COUNTRY_PENALTY * 100)}% — "
                    f"they are not in {wanted_country}")
    return "; ".join(bits)

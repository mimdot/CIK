"""core.llm — provider-agnostic LLM interface via LiteLLM (migration Phase 2,
Track B1).

Wraps ``litellm.completion()`` with retry + fallback logic. LiteLLM is
imported lazily so the rest of the package (and the offline test suite)
works even when the dependency is not installed — which matters in
restricted-network environments where ``pip install litellm`` fails (see
SPRINT_02.md risk register).

``LLMRouter`` is also safe to use with a mock/stub in tests: the unit test
for profile extraction substitutes a fake backend, so no provider or API key
is required to run the suite.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Optional

log = logging.getLogger("phd_aggregator")

DEFAULT_LLM = os.environ.get("LLM_DEFAULT_MODEL", "openai/gpt-4o-mini")
FALLBACK_LLM = os.environ.get("LLM_FALLBACK_MODEL", "ollama/llama3.1:8b")


def parse_model_chain(raw: str) -> list[str]:
    """Comma-separated model ids -> a non-empty list, deduped in order.

    Used to build the provider failover chain from ``LLM_MODEL_CHAIN`` (e.g.
    ``gemini/gemini-2.5-flash-lite,mistral/mistral-large-latest``) so lanes are
    walked from highest capacity down. A trailing/leading space around each id
    is tolerated."""
    out: list[str] = []
    for piece in raw.split(","):
        model = piece.strip()
        if model and model not in out:
            out.append(model)
    return out


def _default_max_retries() -> int:
    """Retries per non-final provider lane. Env ``LLM_CHAIN_RETRIES`` (default
    2, preserved from the previous single-fallback behavior). Lower it to speed
    failover when a lane is blackholed (e.g. a blocked provider)."""
    raw = os.environ.get("LLM_CHAIN_RETRIES", "2").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 2


def env_model_chain() -> list[str]:
    """The ordered ``LLM_MODEL_CHAIN`` env list, if configured.

    Read at construction time (not at import) so tests and callers can control
    it per-instance and module import stays side-effect free."""
    return parse_model_chain(os.environ.get("LLM_MODEL_CHAIN", ""))

# --- Sprint 09, Track C1: cost accounting + guardrails ------------------------
# Per-1M-token prices as (input, output) USD, used to estimate spend from the
# llm_usage rows and to enforce LLM_MONTHLY_CAP_USD. Unknown models use a
# cautious upper bound so an unlisted model is never under-billed.
_MODEL_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "gpt-4o": (2.50, 10.00),
    "ollama/llama3.1:8b": (0.0, 0.0),     # local = free
    "ollama/llama3:8b": (0.0, 0.0),
}
_DEFAULT_PRICE: tuple[float, float] = (1.0, 2.0)


class MonthlyCapExceeded(RuntimeError):
    """Raised when LLM_MONTHLY_CAP_USD would be exceeded by this call."""


def model_prices(model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a model id."""
    return _MODEL_PRICES.get(model, _DEFAULT_PRICE)


def estimate_cost_usd(model: str, prompt_tokens: int,
                      completion_tokens: int) -> float:
    """Estimated USD cost of one call from a small model-prices map."""
    inp, out = model_prices(model)
    return (prompt_tokens * inp + completion_tokens * out) / 1_000_000


def _estimate_tokens(text: str) -> int:
    """A rough token estimate (words) for accounting when the provider does
    not return usage metadata (which the fake test backend does not)."""
    return len((text or "").split())


def monthly_cap_usd() -> Optional[float]:
    """The configured monthly cap in USD, or None when disabled."""
    raw = os.environ.get("LLM_MONTHLY_CAP_USD", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        log.warning("LLM_MONTHLY_CAP_USD=%r is not a number — cap disabled",
                    raw)
        return None


def feature_enabled(name: str) -> bool:
    """Feature-toggle helper (Sprint 09, C1): enabled unless ``{NAME}_ENABLED``
    is set to a falsy value. Lets ops cut an AI feature without a deploy."""
    val = os.environ.get(f"{name.upper()}_ENABLED", "1").strip().lower()
    return val not in ("0", "false", "off", "")


# --- llm_usage persistence (best-effort, never raises) -----------------------
# A test seam: ``set_usage_session_factory(factory)`` swaps in a session for
# offline tests; the default opens one over the default engine (creating the
# table via Base.metadata.create_all when missing).
_usage_session_factory = None


def set_usage_session_factory(factory) -> None:
    """Test hook: ``factory()`` returns a SQLAlchemy Session (owned by the
    test) used for llm_usage writes and monthly-spend queries."""
    global _usage_session_factory
    _usage_session_factory = factory


def _usage_session():
    """``(session, owned)`` for accounting; ``(None, False)`` when unusable."""
    if _usage_session_factory is not None:
        try:
            return _usage_session_factory(), False
        except Exception:
            return None, False
    if os.environ.get("CIK_TESTING", "") == "1":
        # Offline suite: LLM calls only record usage when a test injects a
        # session factory (see tests/test_llm_usage.py). Prevents the test
        # run from touching a real dev database.
        return None, False
    try:
        from db.init import init_db, resolve_db_url
        from sqlalchemy.orm import Session
        return Session(init_db(resolve_db_url())), True
    except Exception as exc:
        log.warning("no DB session for llm_usage accounting: %s", exc)
        return None, False


def _with_session(fn):
    """Run ``fn(session)`` in a usage session, committing/cleaning up when the
    session was created here (not injected by a test factory)."""
    session, owned = _usage_session()
    if session is None:
        return None
    try:
        result = fn(session)
        if owned:
            session.commit()
        return result
    finally:
        if owned:
            session.close()


def record_usage(*, user_id: Optional[int], feature: str, model: str,
                 prompt_tokens: int, completion_tokens: int,
                 latency_ms: Optional[int]) -> None:
    """Append one LLM call to the ``llm_usage`` table. Never raises."""
    try:
        from db.models import LlmUsage
        def _write(session):
            session.add(LlmUsage(
                user_id=user_id, feature=feature, model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens, latency_ms=latency_ms))
        _with_session(_write)
    except Exception as exc:
        log.warning("llm usage recording failed: %s", exc)


def monthly_spend_usd(now=None) -> float:
    """Estimated USD spent on LLM calls since the start of the current UTC
    month (from llm_usage rows). 0.0 when the DB is unavailable."""
    def _query(session):
        from sqlalchemy import select
        from db.models import LlmUsage
        from datetime import datetime, timezone
        month_start = now or datetime.utcnow()
        if month_start.tzinfo is not None:
            month_start = month_start.astimezone(timezone.utc)
        month_start = month_start.replace(day=1, hour=0, minute=0, second=0,
                                          microsecond=0)
        if month_start.tzinfo is not None:
            month_start = month_start.replace(tzinfo=None)
        rows = session.execute(
            select(LlmUsage.model, LlmUsage.prompt_tokens,
                   LlmUsage.completion_tokens)
            .where(LlmUsage.created_at >= month_start)).all()
        return sum(estimate_cost_usd(m, p, c) for m, p, c in rows)
    result = _with_session(_query)
    return result if result is not None else 0.0


def _import_litellm():
    """Import litellm lazily. Raises ImportError with a clear message."""
    try:
        import litellm  # type: ignore
        return litellm
    except ImportError as exc:  # pragma: no cover - env guard
        raise ImportError(
            "litellm is not installed. Install it with "
            "`pip install litellm`, or pass a stub LLM for offline testing."
        ) from exc


class LLMRouter:
    """Provider-agnostic LLM interface.

    ``complete`` calls the primary model with retry; on repeated failure it
    falls back to ``fallback_model``. ``backend`` may be injected for tests
    (any callable with the same signature as ``litellm.completion``).
    """

    def __init__(self, default_model: str = DEFAULT_LLM,
                 fallback_model: str = FALLBACK_LLM,
                 backend=None, max_retries: Optional[int] = None,
                 temperature: float = 0.0,
                 model_chain: Optional[list[str]] = None):
        """``model_chain`` is an explicit ordered lane list (highest capacity
        first, tried in order). When unset, the ``LLM_MODEL_CHAIN`` env var is
        read at construction time; if that is empty,
        ``[default_model, fallback_model]`` is used (the original two-lane
        fallback). ``max_retries`` defaults to ``LLM_CHAIN_RETRIES`` (2) and
        applies to every lane before the last; the final lane is attempted
        once."""
        self.default_model = default_model
        self.fallback_model = fallback_model
        self._backend = backend            # injectable for tests
        self._litellm = None               # resolved lazily
        self.max_retries = (max_retries if max_retries is not None
                            else _default_max_retries())
        self.temperature = temperature
        # An empty model list is treated as "unset" so a blank LLM_MODEL_CHAIN
        # (or parse of it) still falls through to default/fallback.
        self.model_chain = (list(model_chain) if model_chain is not None
                            else env_model_chain()) or None

    def _call(self, model: str, prompt: str, schema) -> str:
        """Single completion call, returning the text. Raises on failure.

        The schema is embedded in the prompt text (see core/profile.py); it is
        deliberately NOT passed via response_format, because litellm's
        json_object mode does not support a schema key. Both the injected
        test backend and the real litellm path behave identically here."""
        if self._backend is not None:
            kwargs = {"messages": [{"role": "user", "content": prompt}]}
            resp = self._backend(model=model, **kwargs)
            if isinstance(resp, str):
                return resp
            return resp.choices[0].message.content
        if self._litellm is None:
            self._litellm = _import_litellm()
        kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}],
                  "temperature": self.temperature}
        resp = self._litellm.completion(**kwargs)
        return resp.choices[0].message.content

    def _models(self) -> list[str]:
        """The ordered provider-lane list: the explicit ``model_chain``, else
        the env ``LLM_MODEL_CHAIN`` resolved at construction, else
        ``[default_model, fallback_model]`` — deduped, empty ids dropped."""
        candidates = self.model_chain or []
        models = list(candidates)
        if not models and self.default_model:
            models.append(self.default_model)
            if self.fallback_model and self.fallback_model != self.default_model:
                models.append(self.fallback_model)
        out: list[str] = []
        for model in models:
            if model and model not in out:
                out.append(model)
        return out

    def _run_completion(self, prompt: str, schema) -> str:
        """Walk the provider chain from the highest-capacity lane down.

        Every non-final lane gets ``1 + max_retries`` attempts before moving to
        the next lane; the final lane is attempted once. This generalizes the
        original behavior (retry the primary, then one fallback attempt) while
        preserving the exact call counts the tests pin."""
        models = self._models()
        if not models:
            raise RuntimeError("LLMRouter: no models configured")
        last_exc: Optional[Exception] = None
        for idx, model in enumerate(models):
            is_last = idx == len(models) - 1
            attempts = (1 if is_last else 1 + self.max_retries) if len(models) > 1 \
                else 1 + self.max_retries
            for attempt in range(attempts):
                try:
                    return self._call(model, prompt, schema)
                except Exception as exc:
                    last_exc = exc
                    log.warning("LLM attempt %d on %s failed: %s",
                                attempt + 1, model, exc)
                    if attempt < attempts - 1:
                        time.sleep(min(0.5 * (2 ** attempt) +
                                       random.uniform(0, 0.5), 5.0))
        # Unreachable in practice (at least one attempt always runs); keep the
        # final raise explicit rather than relying on an assert (which python -O
        # strips) for the exception flow.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLMRouter: provider chain failed without an error")

    def complete(self, prompt: str, schema: dict | None = None,
                 *, user_id: Optional[int] = None,
                 feature: str = "generic") -> str:
        """Run the prompt on the primary model, then the fallback model, with
        retries in between. Returns the raw completion text.

        Sprint 09 (C1): every call is checked against the monthly USD cap
        (``MonthlyCapExceeded`` raised when over) and recorded in the
        ``llm_usage`` table. ``user_id`` / ``feature`` are optional accounting
        metadata; existing callers keep working unchanged."""
        cap = monthly_cap_usd()
        if cap is not None and monthly_spend_usd() >= cap:
            raise MonthlyCapExceeded(
                f"LLM monthly cost cap (${cap:.2f}) reached — call refused")
        started = time.monotonic()
        text = self._run_completion(prompt, schema)
        latency_ms = int((time.monotonic() - started) * 1000)
        record_usage(user_id=user_id, feature=feature,
                     model=self.default_model,
                     prompt_tokens=_estimate_tokens(prompt),
                     completion_tokens=_estimate_tokens(text),
                     latency_ms=latency_ms)
        return text


def extract_json_block(text: str) -> dict:
    """Best-effort parse of an LLM answer into a dict: strip code fences and
    leading prose, then json.loads. Raises ValueError if nothing parses."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.endswith("```"):
            t = t[:-3]
        t = t.strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise ValueError("no JSON object found in LLM output")

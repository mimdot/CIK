"""tests.test_llm_chain — provider failover chain in core.llm (Sprint 10, beta).

Pins the ordered-lane behavior: every non-final lane is tried ``1 + max_retries``
times, the final lane once, and success on any lane short-circuits the chain.
All backends are fakes — nothing touches the network.
"""

from __future__ import annotations

import pytest

from core.llm import LLMRouter, env_model_chain, parse_model_chain


@pytest.fixture(autouse=True)
def _no_env_chain(monkeypatch):
    """Pin the env-loaded chain to empty so these tests are deterministic
    regardless of a developer's local LLM_MODEL_CHAIN."""
    monkeypatch.setattr("core.llm.env_model_chain", lambda: [])


def _backend(calls: list[str], fail: set[str] = (),
             result: str = '{"ok": 1}'):
    def backend(model, messages, **kw):
        calls.append(model)
        if model in fail:
            raise RuntimeError(f"boom on {model}")
        return result
    return backend


def test_parse_model_chain_dedupes_in_order():
    assert parse_model_chain(" a/m , a/m, b/m ,") == ["a/m", "b/m"]
    assert parse_model_chain("") == []
    assert parse_model_chain("only") == ["only"]


def test_chain_walks_lanes_and_stops_on_first_success():
    calls: list[str] = []
    llm = LLMRouter(model_chain=["a/m", "b/m", "c/m"], max_retries=0,
                    backend=_backend(calls, fail={"a/m"}))
    out = llm.complete("hi")
    assert out == '{"ok": 1}'
    assert calls == ["a/m", "b/m"]          # c/m never tried


def test_chain_retries_non_last_lanes_then_last_once():
    calls: list[str] = []
    llm = LLMRouter(model_chain=["a/m", "b/m", "c/m"], max_retries=1,
                    backend=_backend(calls, fail={"a/m", "b/m", "c/m"}))
    with pytest.raises(RuntimeError):
        llm.complete("hi")
    assert calls == ["a/m", "a/m", "b/m", "b/m", "c/m"]  # 1+retries, final once


def test_model_chain_overrides_default_and_fallback():
    calls: list[str] = []
    llm = LLMRouter(default_model="p/m", fallback_model="f/m",
                    model_chain=["x/m", "y/m"], max_retries=0,
                    backend=_backend(calls, fail={"x/m"}))
    llm.complete("hi")
    assert calls == ["x/m", "y/m"]          # p/f unused


def test_chain_from_default_and_fallback_when_unset():
    calls: list[str] = []
    llm = LLMRouter(default_model="p/m", fallback_model="f/m", max_retries=0,
                    backend=_backend(calls, fail={"p/m", "f/m"}))
    with pytest.raises(RuntimeError):
        llm.complete("hi")
    assert calls == ["p/m", "f/m"]          # original two-lane behavior


def test_models_dedupes_equal_default_and_fallback():
    llm = LLMRouter(default_model="solo/m", fallback_model="solo/m",
                    backend=_backend([]))
    assert llm._models() == ["solo/m"]


def test_env_model_chain_reads_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CHAIN", "a/m , b/m")
    assert env_model_chain() == ["a/m", "b/m"]


def test_constructor_resolves_env_chain(monkeypatch):
    """The chain is resolved at construction (not import), so re-instantiating
    a router after env changes picks up the new chain."""
    monkeypatch.setattr("core.llm.env_model_chain",
                        lambda: ["a/m", "b/m"])
    calls: list[str] = []
    llm = LLMRouter(default_model="p/m", fallback_model="f/m", max_retries=0,
                    backend=_backend(calls, fail={"a/m"}))
    llm.complete("hi")
    assert calls == ["a/m", "b/m"]          # env chain beats default/fallback


def test_blank_env_chain_falls_back_to_default_and_fallback(monkeypatch):
    monkeypatch.setattr("core.llm.env_model_chain", lambda: [])
    calls: list[str] = []
    llm = LLMRouter(default_model="p/m", fallback_model="f/m", max_retries=0,
                    backend=_backend(calls, fail={"p/m", "f/m"}))
    with pytest.raises(RuntimeError):
        llm.complete("hi")
    assert calls == ["p/m", "f/m"]
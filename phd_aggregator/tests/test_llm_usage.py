"""tests.test_llm_usage — Sprint 09, Track C1 (LLM cost accounting + cap).

Covers the model-price estimate, llm_usage row recording, the monthly-spend
query, and the monthly-cap enforcement + feature toggles. A session factory is
injected for the accounting writes so the suite stays offline; the LLM call
itself uses a fake backend.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from core import llm
from core.llm import (LLMRouter, MonthlyCapExceeded, estimate_cost_usd,
                      feature_enabled, model_prices, monthly_cap_usd,
                      monthly_spend_usd, record_usage)
from db.models import Base, LlmUsage


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def usage_session(db_session):
    llm.set_usage_session_factory(lambda: db_session)
    yield db_session
    llm.set_usage_session_factory(None)


@pytest.fixture()
def fake_llm(usage_session):
    def backend(model, messages, **kw):
        return "a fake completion"
    return LLMRouter(default_model="fake/model", backend=backend)


# --- pricing ------------------------------------------------------------------
def test_model_prices_known_and_unknown():
    assert model_prices("openai/gpt-4o-mini") == (0.15, 0.60)
    assert model_prices("totally/unknown-model") == (1.0, 2.0)  # cautious


def test_estimate_cost_usd():
    # gpt-4o-mini: 1_000_000 prompt @ $0.15/M + 500_000 completion @ $0.60/M
    cost = estimate_cost_usd("openai/gpt-4o-mini", 1_000_000, 500_000)
    assert cost == pytest.approx(0.45, abs=1e-9)


# --- recording + spend --------------------------------------------------------
def test_record_usage_writes_row(db_session, usage_session):
    record_usage(user_id=7, feature="assistant", model="openai/gpt-4o-mini",
                 prompt_tokens=100, completion_tokens=50, latency_ms=120)
    rows = db_session.execute(select(LlmUsage)).all()
    assert len(rows) == 1
    row = rows[0][0]
    assert row.user_id == 7
    assert row.feature == "assistant"
    assert row.model == "openai/gpt-4o-mini"
    assert row.prompt_tokens == 100 and row.completion_tokens == 50
    assert row.latency_ms == 120


def test_complete_records_usage(db_session, fake_llm):
    out = fake_llm.complete("hello model", feature="test")
    assert out == "a fake completion"
    count = db_session.scalar(select(func.count()).select_from(LlmUsage)) or 0
    assert count == 1
    row = db_session.scalar(select(LlmUsage))
    assert row.feature == "test"
    assert row.model == "fake/model"
    assert row.completion_tokens == 3  # "a fake completion" = 3 words


def test_monthly_spend_sums_current_month(db_session, usage_session):
    now = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    record_usage(user_id=None, feature="digest", model="ollama/llama3.1:8b",
                 prompt_tokens=1_000_000, completion_tokens=0, latency_ms=1)
    record_usage(user_id=None, feature="digest", model="openai/gpt-4o-mini",
                 prompt_tokens=1_000_000, completion_tokens=0, latency_ms=1)
    spend = monthly_spend_usd(now)
    assert spend == pytest.approx(0.15, abs=1e-9)  # only the paid model counts


# --- monthly cap --------------------------------------------------------------
def test_monthly_cap_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LLM_MONTHLY_CAP_USD", raising=False)
    assert monthly_cap_usd() is None


def test_monthly_cap_parsed(monkeypatch):
    monkeypatch.setenv("LLM_MONTHLY_CAP_USD", "12.5")
    assert monthly_cap_usd() == pytest.approx(12.5)


def test_cap_blocks_call_when_exceeded(monkeypatch, fake_llm):
    monkeypatch.setenv("LLM_MONTHLY_CAP_USD", "1.0")
    monkeypatch.setattr(llm, "monthly_spend_usd", lambda now=None: 1.5)
    with pytest.raises(MonthlyCapExceeded):
        fake_llm.complete("hi")


def test_cap_allows_call_under_limit(monkeypatch, fake_llm):
    monkeypatch.setenv("LLM_MONTHLY_CAP_USD", "1.0")
    monkeypatch.setattr(llm, "monthly_spend_usd", lambda now=None: 0.5)
    assert fake_llm.complete("hi") == "a fake completion"


# --- feature toggles ----------------------------------------------------------
def test_feature_enabled_default_on(monkeypatch):
    monkeypatch.delenv("ASSISTANT_ENABLED", raising=False)
    assert feature_enabled("assistant") is True


def test_feature_enabled_can_be_cut(monkeypatch):
    for val in ("0", "false", "off", ""):
        monkeypatch.setenv("ASSISTANT_ENABLED", val)
        assert feature_enabled("assistant") is False
    monkeypatch.setenv("ASSISTANT_ENABLED", "1")
    assert feature_enabled("assistant") is True


def test_complete_still_falls_back_to_fallback_model(monkeypatch, usage_session):
    calls = []

    def backend(model, messages, **kw):
        calls.append(model)
        raise RuntimeError("boom")

    llm2 = LLMRouter(default_model="p/m", fallback_model="f/m",
                     backend=backend, max_retries=0)
    monkeypatch.setattr(llm, "monthly_spend_usd", lambda now=None: 0.0)
    with pytest.raises(RuntimeError):
        llm2.complete("hi")
    assert calls[-1] == "f/m"

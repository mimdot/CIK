# LLM Provider Decision (D1)

Status: **Draft for founder discussion** (Week 1, Sprint 01)
Scope: choose the LLM provider(s) for **Phase 2's Identity Engine** — converting
CV/bio text into a typed `UserProfile`, plus Phase 3/4 helpers (description
extraction, natural-language query). **Not** for scoring: ranking stays
deterministic (see `docs/06_Operating_Rules.md`). The LLM is used only where it
adds value.

---

## 1. Decision criteria

The sprint asks us to weigh **five** things. Their relative priority for THIS
project (single-user, Iran-based, cost-sensitive, quality-critical structured
output):

| Criterion | Weight | Why it matters here |
|---|---|---|
| Structured-extraction quality | **High** | A `UserProfile` built from free CV/bio text is the whole point of Phase 2. A model that reliably emits valid, complete JSON beats a slightly cheaper one that hallucinates fields. |
| Cost | High | Solo/personal use. Penny-per-1M-token differences matter at low volume but explode if a pipeline re-parse loops. |
| Offline / local capability (Iran) | High | Sanctions/network reality means we cannot assume a reachable US/EU API on every run. Must degrade gracefully to a local model. |
| Latency | Medium | Async digest + batch profile builds. Sub-second is nice, seconds are acceptable. |
| No single-vendor lock-in | Medium | Underlying rule: "do not make the system dependent on one model provider" (Operating Rules). A thin abstraction layer solves this. |

---

## 2. Options evaluated

### 2.1 OpenAI (GPT-4o-mini extraction / GPT-4o explanation)
- **Cost:** ~$0.15 / 1M input tokens (4o-mini). Cheapest API option here.
- **Quality:** Strong, reliable `JSON` / `json_schema` structured output; the
  `response_format={"type": "json_object"}` path is battle-tested.
- **Latency:** ~0.5–3s per call; good.
- **Offline/Iran:** **No** — requires a reachable endpoint over the proxy. No
  local fallback from OpenAI.
- **Lock-in:** Vendor SDK or `openai` client; switching means a rewrite unless
  abstracted.
- **Verdict:** Best outright *quality-per-dollar* for cloud.

### 2.2 Anthropic (Claude Haiku / Sonnet)
- **Cost:** ~$0.80/1M input (≈5× OpenAI's cheap tier).
- **Quality:** Excellent reasoning and instruction-following; JSON mode exists
  but historically slightly less rigid than OpenAI's schema-typed output.
- **Latency:** 1–4s; fine.
- **Offline/Iran:** **No** local path.
- **Lock-in:** Same abstraction issue as OpenAI.
- **Verdict:** Pricier than OpenAI with no decisive extraction advantage → not
  the default, keep behind the abstraction.

### 2.3 Ollama (local) — Llama 3.x / Qwen / Phi small models
- **Cost:** Free, unlimited (compute only).
- **Quality:** Smaller models do *okay* JSON but need a guarded schema + prompt +
  retry; a 7–14B model approaches cloud quality for *simple* profile fields but
  lags on long/messy CV text.
- **Latency:** Slow on consumer hardware (seconds to tens of seconds).
- **Offline/Iran:** **Yes — runs fully offline.** This is the only option that
  works on a sanctioned network, which is decisive as a fallback.
- **Lock-in:** None locally; `ollama` is OpenAI-compatible HTTP (drop-in).
- **Verdict:** The offline backbone and the lock-in breaker.

### 2.4 LiteLLM (abstraction layer)
- Not a model — a **shim** (`completion()`/`acompletion()` calls with provider
  config). Wraps OpenAI, Anthropic, Ollama, many others behind one interface;
  model = `"openai/...`", `"anthropic/..."`, `"ollama/..."`.
- **Cost/latency:** inherit the underlying provider.
- **Offline:** can point at local Ollama identically to a cloud provider.
- **Lock-in:** **Removes vendor lock-in by construction** — switch the model
  string at runtime, no code isolation. Exactly what Operating rules require.
- **Verdict:** The recommended abstraction.

---

## 3. Recommendation

**Adopt LiteLLM as the provider-agnostic interface; default to `openai/gpt-4o`
(or `gpt-4o-mini`) with a fully configured `ollama/` local fallback.**

Rationale:
1. **No single-vendor lock-in** (required): the whole pipeline talks only to
   the LiteLLM interface. Swapping OpenAI → Anthropic → Ollama is a config
   change.
2. **Cost/latency** default: `gpt-4o-mini` gives the best cloud extraction
   per dollar *when* reachable.
3. **Iran/offline resilience:** if the API is unreachable (proxy down, sanction
   edge), we route to the same `ModelRouter` pointing at local `ollama` and
   still produce a profile — degraded quality, never a hard failure.
4. **Quality where it matters:** for the strict JSON we need, we pass an explicit
   schema + a validation wrapper (see below) so even the weaker local model is
   corrected/orchestrated rather than trusted.

Decision criteria trade-off: **Ollama-only would be hardest offline but slowest
and lowest quality. OpenAI-only would be best quality/cost but breaks on the
Iranian network. Neither alone is acceptable.** The hybrid via LiteLLM gives
quality (cloud) AND resilience (local) without lock-in. That is the whole point of
the criteria, and it is the only option that satisfies **all** of them
simultaneously.

---

## 5. Abstracted interface (proposed, for Phase 2)

Keep this thin so any later provider/choice is a drop-in:

```python
# core/llm.py  (future; not built in this sprint)
class ProfileExtractor:
    def __init__(self, router, model, schema): ...
    def extract(self, raw_text: str) -> UserProfile:
        # 1) prompt + typed JSON schema (strict field ranges)
        # 2) ask ModelRouter.acompletion(model=cfg.model, ...)
        # 3) validate with a Pydantic guard; on failure retry once, else
        #    fall back to the configured fallback model (e.g. ollama)
```

- Default config: `MODEL_EXTRACT = "openai/gpt-4o-mini"`,
  `MODEL_EXTRACT_FALLBACK = "ollama/llama3.1:8b"`.
- **LLM never enters the scoring path.** `score_relevance` stays deterministic;
  `UserProfile` extraction is the only sanctioned LLM use.

---

## 6. Recommended decision

> **Adopt LiteLLM as the universal LLM interface. Default extraction to
> OpenAI's `gpt-4o-mini`; configure an automatic `ollama` (Llama 3.1 8B) local
> fallback so the product keeps working fully offline. Keep the LLM strictly out
> of the deterministic ranking.**

Founder to confirm 1: accept `gpt-4o-mini` as the cloud default, or substitute a
leaner/cheaper family. 2: whether to budget time to first buy a demo of the
extraction quality on local `ollama` before Phase 2.

---

## 7. Summary table

| Provider | Cost | Latency | Extraction quality | Offline (Iran) | Lock-in |
|---|---|---|---|---|---|
| OpenAI | ~$0.15/1M | ~0.5–3s | Excellent (json_schema) | No | high unless abstracted |
| Anthropic | ~$0.80/1M | 1–4s | Very good | No | high unless abstracted |
| Ollama | Free | seconds | Good (guarded) | **Full** | none |
| **LiteLLM** | inherits | inherits | inherits+guards | **Same as backend** | **none** |
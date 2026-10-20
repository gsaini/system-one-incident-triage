"""The players. Each one answers the same `system_one(state, questions)` call.

- **keyword rules**: offline, through the real SDK over a mock transport (baseline.py).
- **a local model** served by Ollama, through TypeSafe's `system-one-adapter`, which asks the model
  for the same typed answers with schema-constrained JSON. Free; needs `ollama serve`.
- **Jev** itself would be `TypeSafeClient()` with a `TYPESAFE_API_KEY`. It is left out here on
  purpose; system-one-models-getting-started has the live arms and the cost gates.

`Arm.ask` times every call and turns failures into recorded errors instead of exceptions, so a
run over many reports finishes and reports them.
"""

from __future__ import annotations

import json
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from typesafe_sdk import RetryPolicy, SystemOneResponse, TypeSafeClient, TypeSafeError

from incident_triage.baseline import Answerer, KeywordBaseline

DEFAULT_OLLAMA = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434/v1"


class NoModel(RuntimeError):
    """Ollama isn't running, or doesn't have the model."""


@dataclass(frozen=True)
class Call:
    ok: bool
    latency_ms: float
    model: str = ""
    error: str = ""


@dataclass
class Arm:
    name: str
    client: Any  # TypeSafeClient or SystemOneAdapterClient: both expose .system_one(state, questions)
    calls: list[Call] = field(default_factory=list)

    def ask(self, state: Any, questions: Any) -> SystemOneResponse | None:
        started = time.perf_counter()
        try:
            response = self.client.system_one(state, questions)
        except TypeSafeError as exc:
            elapsed = (time.perf_counter() - started) * 1000
            self.calls.append(Call(False, elapsed, error=f"{type(exc).__name__}: {exc}"))
            return None
        self.calls.append(Call(True, (time.perf_counter() - started) * 1000, response.model))
        return response

    def summary(self) -> dict[str, Any]:
        ok = sorted(c.latency_ms for c in self.calls if c.ok)
        return {
            "arm": self.name,
            "calls": len(self.calls),
            "errors": len(self.calls) - len(ok),
            "latency_p50_ms": statistics.median(ok) if ok else 0.0,
            "latency_max_ms": ok[-1] if ok else 0.0,
        }


def baseline_arm(answerer: Answerer) -> Arm:
    baseline = KeywordBaseline(answerer)
    client = TypeSafeClient(
        api_key="offline-keyword-baseline", transport=baseline.transport(), retry=RetryPolicy(max_retries=0)
    )
    return Arm("keyword rules", client)


def ollama_arm(model: str = DEFAULT_OLLAMA, *, base_url: str = OLLAMA_URL) -> Arm:
    """A local model, through the adapter's OpenAI-compatible Chat Completions provider."""
    from system_one_adapter import SystemOneAdapterClient
    from system_one_adapter.providers.openai import OpenAIProvider

    # Fail once up front rather than recording a connection error for every report.
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=3) as resp:
            served = {m["id"] for m in json.load(resp)["data"]}
    except (OSError, ValueError, KeyError) as exc:
        raise NoModel(f"No Ollama server at {base_url} (start it with `ollama serve`): {exc}") from exc
    if model not in served and f"{model}:latest" not in served:
        raise NoModel(f"Ollama doesn't have {model!r}; run `ollama pull {model}`.")

    provider = OpenAIProvider(model, base_url=base_url, api_key="ollama", api="chat_completions")
    client = SystemOneAdapterClient(
        structured_outputs=True,  # Ollama constrains decoding to the JSON schema
        llm_answer_mode="probabilities",  # ask for a distribution, like Jev returns
        normalize_probabilities=True,  # rescale a distribution that doesn't sum to 1 instead of failing
        n_retry_malformed_structure=1,
        provider="openai",
        model=provider,
    )
    return Arm(f"{model} (Ollama)", client)

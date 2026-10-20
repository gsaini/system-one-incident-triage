"""Keyword rules served through the real TypeSafe SDK, so everything runs offline.

Adapted from system-one-models-getting-started (its baseline.py and confidence.py). This is **not
Jev**: it is the if-this-word-then-that logic a team has before a model, behind an
`httpx2.MockTransport` that speaks TypeSafe's `POST /v1/systemone` wire format. The rest of the
code can't tell the difference, so the same `system_one(state, questions)` call runs with or
without a model.

An `Answerer` gets each question (by name, as the wire dict) plus the raw state and returns an
answer dict, or None for "no rule": the baseline then answers with maximum uncertainty
(Noul 0.5, uniform Choice/Score), which callers must treat as "don't know".
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

Answerer = Callable[[str, Mapping[str, Any], Any], dict[str, Any] | None]

SMOOTHING = 0.02


def choice_confidence(probabilities: Sequence[float]) -> float:
    """TypeSafe's formula (https://docs.typesafe.ai/confidence): 0 for uniform, 1 when one option has it all."""
    n = len(probabilities)
    if n < 2:
        return 1.0
    return max(0.0, min(1.0, (n * max(probabilities) - 1) / (n - 1)))


def score_confidence(probabilities: Sequence[float]) -> float:
    """1 - (expected distance from the peak level) / (that distance for an even spread)."""
    n = len(probabilities)
    if n < 2:
        return 1.0
    total = sum(probabilities) or 1.0
    p = [value / total for value in probabilities]
    peak = p.index(max(p))
    spread = sum(value * abs(i - peak) for i, value in enumerate(p))
    even_spread = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return max(0.0, min(1.0, 1 - spread / even_spread))


def noul_answer(p: float) -> dict[str, Any]:
    return {"type": "noul", "noul": max(0.0, min(1.0, float(p)))}


def choice_answer(labels: Sequence[str], weights: Mapping[str, float]) -> dict[str, Any]:
    """Turn non-negative per-label weights into a distribution; ties go to the first label."""
    raw = [max(0.0, float(weights.get(label, 0.0))) + SMOOTHING for label in labels]
    total = sum(raw)
    probs = [value / total for value in raw]
    return {
        "type": "choice",
        "choice": labels[probs.index(max(probs))],
        "confidence": choice_confidence(probs),
        "probabilities": dict(zip(labels, probs, strict=True)),
    }


def score_answer(levels: Sequence[Any], weights: Sequence[float]) -> dict[str, Any]:
    raw = [max(0.0, float(w)) + SMOOTHING for w in list(weights)[: len(levels)]]
    raw += [SMOOTHING] * (len(levels) - len(raw))
    total = sum(raw)
    probs = [value / total for value in raw]
    return {
        "type": "score",
        "score": sum(i * p for i, p in enumerate(probs)),
        "confidence": score_confidence(probs),
        "legend": {str(i): level if isinstance(level, str) else json.dumps(level) for i, level in enumerate(levels)},
        "probabilities": {str(i): p for i, p in enumerate(probs)},
    }


def uncertain(question: Mapping[str, Any]) -> dict[str, Any]:
    kind = question["type"]
    if kind == "noul":
        return noul_answer(0.5)
    if kind == "choice":
        return choice_answer(list(question["criteria"]), {})
    if kind == "score":
        return score_answer(list(question["criteria"]), [])
    raise ValueError(f"unknown question type {kind!r}")


def text_of(state: Any) -> str:
    """The state as lowercase text, for keyword rules."""
    return (state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)).lower()


def any_of(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def count_of(text: str, *needles: str) -> int:
    return sum(needle in text for needle in needles)


@dataclass
class KeywordBaseline:
    answer: Answerer
    model: str = "keyword-baseline"
    requests: list[dict[str, Any]] = field(default_factory=list)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path.endswith("/v1/models"):
            models = [{"name": self.model, "description": "Offline keyword baseline", "release_date": "2026-10-19"}]
            return httpx2.Response(200, json={"models": models})
        body = json.loads(request.content)
        self.requests.append(body)
        answers = {name: self.answer(name, q, body["state"]) or uncertain(q) for name, q in body["questions"].items()}
        usage = {"input_tokens": max(1, len(request.content) // 4), "output_tokens": 0}
        return httpx2.Response(200, json={"model": self.model, "answers": answers, "usage": usage})

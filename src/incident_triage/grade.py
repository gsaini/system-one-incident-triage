"""Grade every player on the bundled reports: 20 incidents, each labelled by hand with the six answers.

A player is right on a question when the box it ticks matches the label: the most likely Score
level, the chosen team, or yes/no at p ≥ 0.5. Severity also gets a "within one level" score,
because the line between degraded and major is a judgement call.

`split=True` asks the six questions in six requests instead of one: the post's "parallel" claim,
tested from the other side. For a model that answers all six at once worse than one at a time,
batching is not free.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from incident_triage.arms import Arm
from incident_triage.form import LABELS, QUESTIONS, state_for

DATA = Path(__file__).resolve().parents[2] / "data" / "incidents.jsonl"


@dataclass(frozen=True)
class Incident:
    id: str
    report: str
    labels: dict[str, Any]  # severity: level index; owner: team; the four Nouls: bool


def load_incidents(path: Path = DATA) -> list[Incident]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [Incident(r["id"], r["report"], {name: r[name] for name in QUESTIONS}) for r in rows]


def decided(answer: Any) -> Any:
    """What the player decided: the most likely Score level, the Choice, or yes/no for a Noul."""
    if answer.type == "noul":
        return answer.noul >= 0.5
    if answer.type == "choice":
        return answer.choice
    return int(max(answer.probabilities.items(), key=lambda kv: kv[1])[0])


def ask_form(arm: Arm, report: str, *, split: bool = False) -> dict[str, Any] | None:
    """All six answers: from one request for the whole form, or (split) from one request per question."""
    state = state_for(report)
    if not split:
        response = arm.ask(state, QUESTIONS)
        return None if response is None else dict(response.answers)
    answers = {}
    for name, question in QUESTIONS.items():
        response = arm.ask(state, {name: question})
        if response is None:
            return None
        answers[name] = response.answers[name]
    return answers


def grade(arms: list[Arm], incidents: list[Incident], *, split: bool = False) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for arm in arms:
        right = dict.fromkeys(QUESTIONS, 0)
        within_one, all_right, rows = 0, 0, []
        for incident in incidents:
            answers = ask_form(arm, incident.report, split=split)
            if answers is None:
                rows.append({"id": incident.id, "error": arm.calls[-1].error})
                continue
            got = {name: decided(answer) for name, answer in answers.items()}
            for name in QUESTIONS:
                right[name] += got[name] == incident.labels[name]
            within_one += abs(got["severity"] - incident.labels["severity"]) <= 1
            all_right += all(got[name] == incident.labels[name] for name in QUESTIONS)
            rows.append({"id": incident.id, "got": got})
        results[arm.name + (" · one question per request" if split else "")] = {
            "answered": sum("got" in r for r in rows),
            "right": right,
            "severity_within_one": within_one,
            "all_right": all_right,
            "rows": rows,
            "summary": arm.summary(),
        }
    return {"n": len(incidents), "results": results}


def markdown(report: dict[str, Any]) -> str:
    n, results = report["n"], report["results"]
    names = list(results)

    def row(label: str, cell: Callable[[dict[str, Any]], str]) -> str:
        return f"| {label} | " + " | ".join(cell(results[name]) for name in names) + " |"

    lines = [
        f"{n} reports, labelled by hand. Right answers out of {n}; a rejected answer counts as wrong.",
        "",
        "| question | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for name, label in LABELS.items():
        lines.append(row(label, lambda r, name=name: f"{r['right'][name]}/{n}"))
    lines += [
        row("severity within one level", lambda r: f"{r['severity_within_one']}/{n}"),
        row("**all six right**", lambda r: f"**{r['all_right']}/{n}**"),
        row("answers the SDK rejected", lambda r: str(n - r["answered"])),
        row(
            "latency p50 / max",
            lambda r: f"{r['summary']['latency_p50_ms']:,.0f} / {r['summary']['latency_max_ms']:,.0f} ms",
        ),
    ]
    return "\n".join(lines)

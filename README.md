# Incident triage with System One questions

**One incident report goes in. Six typed answers with probabilities come out: how bad, which team, page the on-call, customers can see it, data at risk, caused by a recent change. No text to parse.** This repo is one concrete use case of the "System One model" idea from [TypeSafe's launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev), built so you can run it with no keys and no cost: keyword rules and a local model answer the same form through the same SDK call, and a grader scores both against 20 hand-labelled reports.

[![CI](https://github.com/gsaini/system-one-incident-triage/actions/workflows/ci.yml/badge.svg)](https://github.com/gsaini/system-one-incident-triage/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Offline](https://img.shields.io/badge/runs-offline%2C%20free-16A34A?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-EAB308?style=for-the-badge)

> A companion to [system-one-models-getting-started](https://github.com/gsaini/system-one-models-getting-started), which tests the post's claims experiment by experiment. An independent learning project, not affiliated with TypeSafe or Anthropic.

## The form

The state is the report as a person wrote it. The questions are fixed, and so are the answers a model may give:

| question | type | the model answers with |
|---|---|---|
| How bad is it? | **Score** | one of four levels: cosmetic, degraded, major, critical, each described in a sentence |
| Who should own it? | **Choice** | one of six teams: platform, payments, frontend, data, security, or *unknown* |
| Page the on-call now? | **Noul** | P(yes) |
| Can customers see it? | **Noul** | P(yes) |
| Is data at risk? | **Noul** | P(yes) |
| Did a recent change cause it? | **Noul** | P(yes) |

The whole form is one call, and code acts on the typed answers directly:

```python
from typesafe_sdk import TypeSafeClient
from incident_triage.form import QUESTIONS, state_for

response = TypeSafeClient().system_one(state_for(report), QUESTIONS)  # Jev, with a TYPESAFE_API_KEY

if response.nouls["page_oncall"].noul >= 0.8:
    page(oncall_for(response.choices["owner"].choice))
if response.nouls["data_at_risk"].noul >= 0.5:
    open_data_review(report)
```

The questions live in [form.py](src/incident_triage/form.py). The keyword rules that answer them offline are in the same file, served through the real SDK over a mock transport ([baseline.py](src/incident_triage/baseline.py)), so the code above runs unchanged without a model.

## Quick start

```bash
git clone https://github.com/gsaini/system-one-incident-triage.git
cd system-one-incident-triage
uv sync                                   # or: python -m venv .venv && .venv/bin/pip install -e . pytest

uv run triage ask "api.example.com is down for everyone since the 14:05 deploy"
uv run triage demo                        # the first five bundled reports
uv run triage grade                       # all 20 reports against their labels
uv run pytest -q
```

With a local model, free, through [Ollama](https://ollama.com) and TypeSafe's own [system-one-adapter](https://github.com/typesafe-ai/system-one-adapter-python):

```bash
ollama pull qwen2.5:7b                    # 4.7 GB; any Ollama model works: --ollama llama3.2
uv run triage demo --ollama               # qwen2.5:7b by default
uv run triage grade --ollama
uv run triage grade --ollama --split      # one request per question instead of one per report
```

`triage ask` shows every player side by side. The bar is how much probability the player put on the box it ticked:

```text
“Checkout is returning 502s for every customer since the 14:05 deploy. Stripe webhooks are piling up and we're…”

                               keyword rules                     qwen2.5:7b (Ollama)
How bad is it?                 critical       ██████████  98%  degraded       ██████████ 100%
Who should own it?             platform       █████░░░░░  54%  unknown        ██████████ 100%
Page the on-call now?          yes            █████████░  90%  yes            ██████████ 100%
Can customers see it?          yes            ████████░░  85%  yes            ██████████ 100%
Is data at risk?               no             ██████████  95%  no             ██████████ 100%
Did a recent change cause it?  yes            █████████░  90%  no             ██████████ 100%

time                           1 ms                             7,985 ms
```

Jev itself is not wired in here on purpose: the live arms, the cost gates and the measurements that matter for the post's claims (calibration, latency, cost) are in the [getting-started repo](https://github.com/gsaini/system-one-models-getting-started). Any client with a `.system_one(state, questions)` method drops into [`Arm`](src/incident_triage/arms.py), so adding `TypeSafeClient()` with a key is one line.

## Results, 2026-10-19

20 reports in [data/incidents.jsonl](data/incidents.jsonl), each labelled by hand with the six answers. A player is right when the box it ticks matches the label: the most likely severity level, the chosen team, or yes/no at p ≥ 0.5. `qwen2.5:7b` ran through Ollama on a laptop.

| question | keyword rules | qwen2.5:7b, one request per report | qwen2.5:7b, one request per question |
|---|---|---|---|
| How bad is it? | 17/20 | 3/20 | 4/20 |
| Who should own it? | 17/20 | 0/20 | 0/20 |
| Page the on-call now? | 19/20 | 13/20 | 12/20 |
| Can customers see it? | 19/20 | 15/20 | 16/20 |
| Is data at risk? | 19/20 | 18/20 | 10/20 |
| Did a recent change cause it? | 20/20 | 17/20 | 14/20 |
| severity within one level | 20/20 | 13/20 | 13/20 |
| **all six right** | **12/20** | **0/20** | **0/20** |
| answers the SDK rejected | 0 | 0 | 0 |
| latency p50 / max, per request | 0 / 1 ms | 8,974 / 18,019 ms | 1,960 / 9,470 ms |

What to make of it:

- **The rules' score is the bar, not an achievement.** They were written with these 20 reports in view, so 12/20 with all six right is flattering. A model sees the reports cold. Jev would have to clear this bar on reports the rules have never seen.
- **The model never breaks the form.** Ollama constrains its output to the schema, so all 240 answers were valid. That part of the post's type-safety claim is reproducible for free. The *values* are another matter.
- **On the two questions with more than two answers, it hides.** Asked which team owns the checkout outage above, it put 0.67 on *unknown: can't tell from the report* and 0.33 on payments, with "Stripe" and "checkout" in the text. For a Safari legend bug it put 1.00 on *unknown*. An "I can't tell" option is where a small model goes to hide, and it took it on every report. The rules can only pick *unknown* when no team's words appear. If you give a Choice an escape hatch, measure how often it is taken.
- **It under-rates severity.** "Degraded" at 0.80 for checkout down for every customer, and only 13/20 within one level of the label. The yes/no questions are where it is closest to useful, at 12–18 out of 20, which on 20 reports is 60–90% with wide error bars.
- **Batching is not what breaks it.** One request per question gave the same owner and severity scores and shuffled the yes/no ones within noise (the model samples; two runs differ by a few answers). What batching did change is time: about 9 s per report as one request, about 12 s as six. The post's claim is that Jev answers the whole form in one 70–500 ms request, calibrated. That is the number to compare against, and this repo gives you the form and the labels to do it.

## How it works

```text
src/incident_triage/
  form.py        the six questions, the plain-English labels, and the keyword rules
  baseline.py    the rules served through the real SDK over an httpx2.MockTransport (not Jev)
  arms.py        Arm: one interface for the rules and a local model; per-call timing and errors
  grade.py       the 20 labelled reports graded per question, batched or one question per request
  cli.py         `triage ask | demo | grade`
data/            incidents.jsonl, written for this repo: 20 reports with six labels each
tests/           9 offline tests: the SDK round trip, the rules on known reports, the grader, the CLI
```

The adapter asks the local model for a probability per option, in JSON constrained to the form's schema, and normalises a distribution that doesn't sum to one. Probabilities of exactly 1.00 everywhere, as in the example above, are the model's doing, not the adapter's.

## License

[MIT](LICENSE). The incident reports are written for this repo and carry the same license.

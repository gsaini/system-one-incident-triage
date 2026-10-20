"""The triage form: six typed questions about one incident report.

The state is the report as a person wrote it: an alert, a bug, a message from support. The
questions are a Score (how bad), a Choice (which team), and four Nouls that code can act on
directly: page the on-call, tell customers, start a data review, look at the last deploy.

The keyword rules at the bottom are the offline stand-in for a model. They were written with the
bundled reports in view, so their score on those is flattering; a model sees the reports cold.
"""

from __future__ import annotations

import re
from typing import Any

from typesafe_sdk import Choice, Noul, Score

from incident_triage.baseline import any_of, choice_answer, count_of, noul_answer, score_answer, text_of

TEAMS: dict[str, str] = {
    "unknown": "Can't tell from the report",
    "platform": "Infrastructure: deploys, Kubernetes, networking, DNS, capacity, backups and restores",
    "payments": "Billing: invoices, checkout, Stripe, charges, refunds, subscriptions",
    "frontend": "The web app: pages, dashboards, buttons, browser-specific problems",
    "data": "Pipelines and reporting: exports, warehouse, ETL, metrics, wrong numbers in reports",
    "security": "Auth and access: logins, tokens, permissions, suspicious activity, leaks",
}

SEVERITY = [
    "Cosmetic: nothing is blocked",
    "Degraded: slower, flaky, or wrong in a way that has a workaround",
    "Major: a feature is down or wrong for some customers, with no workaround",
    "Critical: the product is down for everyone, or money or data is at risk",
]

QUESTIONS: dict[str, Any] = {
    "severity": Score(instructions="How severe is the incident described in `report`?", criteria=SEVERITY),
    "owner": Choice(
        instructions="Which team should own the incident in `report`? Pick the team whose area it falls in.",
        criteria=TEAMS,
    ),
    "page_oncall": Noul(
        instructions="Should the on-call engineer be paged now for `report`, rather than it waiting for business hours?"
    ),
    "customer_facing": Noul(instructions="Can customers see the problem described in `report`?"),
    "data_at_risk": Noul(
        instructions="Does `report` describe data being lost, corrupted, or shown to the wrong people?"
    ),
    "regression": Noul(
        instructions="Does `report` say the problem started after a recent deploy, release, upgrade, or config change?"
    ),
}

LABELS = {
    "severity": "How bad is it?",
    "owner": "Who should own it?",
    "page_oncall": "Page the on-call now?",
    "customer_facing": "Can customers see it?",
    "data_at_risk": "Is data at risk?",
    "regression": "Did a recent change cause it?",
}

SHORT = {"severity": ["cosmetic", "degraded", "major", "critical"]}


def state_for(report: str) -> dict[str, Any]:
    return {"report": report}


def options(name: str) -> list[tuple[str, str]]:
    """(key, short name) for each box on the form: Score levels, Choice labels, or yes/no."""
    question = QUESTIONS[name]
    if question.type == "noul":
        return [("yes", "yes"), ("no", "no")]
    if question.type == "choice":
        return [(key, key) for key in question.criteria]
    return [(str(i), short) for i, short in enumerate(SHORT[name])]


def ticked(name: str, answer: Any) -> tuple[str, float]:
    """The box a person should read for one typed answer, and the probability the player put on it."""
    if answer.type == "noul":
        return ("yes", answer.noul) if answer.noul >= 0.5 else ("no", 1 - answer.noul)
    if answer.type == "choice":
        return answer.choice, answer.probabilities[answer.choice]
    # A Score's `score` is the probability-weighted level (1.37); the box to tick is the most likely level.
    level, p = max(answer.probabilities.items(), key=lambda kv: kv[1])
    return SHORT[name][int(level)], p


# --- the keyword rules -------------------------------------------------------------------------

_COSMETIC = ("cosmetic", "typo", "misaligned", "overlap", "visual", "colour", "color", "font", "spacing")
_DEGRADED = ("slow", "flaky", "intermittent", "sometimes", "workaround", "annoying", "not blocking", "behind",
             "delay", "stale", "catch up", "still work", "can still", "no errors yet")  # fmt: skip
_MAJOR = ("some users", "some customers", "few customers", "failing", "fails", "errors", "broken", "timing out",
          "timeout", "wrong", "does nothing", "blank", "locked out", "can't sign up", "cannot sign up",
          "not working")  # fmt: skip
_CRITICAL = ("down for everyone", "is down", "outage", "502", "503", "500", "nobody can", "no one can",
             "all customers", "every customer", "everyone", "losing orders", "revenue", "data loss", "lost",
             "corrupt", "overwrote", "leak", "exposed", "breach", "charged twice", "charging customers twice",
             "duplicate charge", "previous customer", "another customer", "bulk download")  # fmt: skip
_NOW = ("right now", "urgent", "asap", "immediately", "climbing", "piling up", "locked out")
_INTERNAL = ("staging", "internal", "dev environment", "no sign it", "no errors yet")
_CUSTOMER = ("customer", "users", "everyone", "checkout", "login", "sign up", "signup", "public", "api.",
             "dashboard", "invoice", "search", "webhook", "export", "report")  # fmt: skip
_DATA = ("data loss", "lost", "gone", "dropping rows", "drops rows", "missing rows", "corrupt", "deleted",
         "overwrote", "leak", "exposed", "breach", "download", "wrong totals", "totals are wrong",
         "previous customer", "another customer", "wrong customer")  # fmt: skip
_REGRESSION = re.compile(
    r"\b(since|after)\b[^.]*\b(deploy|release|rollout|rolled out|upgrade|update|change|migration|policy)"
)
_TEAM_CUES = {
    "platform": ("deploy", "kubernetes", "k8s", "pod", "node", "dns", "network", "latency", "cluster", "502", "503",
                 "cdn", "load balancer", "capacity", "memory", "disk", "region", "restore", "backup", "webhook",
                 "slow"),
    "payments": ("invoice", "billing", "stripe", "checkout", "charge", "payment", "card", "refund", "subscription",
                 "price", "plan"),
    "frontend": ("button", "page", "dashboard", "browser", "safari", "chrome", "firefox", "ui", "css", "layout",
                 "legend", "chart", "modal", "screen", "banner", "theme"),
    "data": ("export", "report", "pipeline", "warehouse", "etl", "rows", "csv", "sync", "totals", "metrics", "usage"),
    "security": ("login attempt", "unknown ip", "auth", "sso", "password", "token", "unauthori", "leak", "breach",
                 "suspicious", "2fa", "phishing", "admin account", "access", "permission"),
}  # fmt: skip


def answerer(name: str, question: dict[str, Any], state: Any) -> dict[str, Any] | None:
    """Keyword rules for the six questions. Returns None for a question it has no rule for."""
    text = text_of(state.get("report", state) if isinstance(state, dict) else state)
    hits = [count_of(text, *_COSMETIC), count_of(text, *_DEGRADED), count_of(text, *_MAJOR), count_of(text, *_CRITICAL)]
    if name == "severity":
        return score_answer(question["criteria"], hits if any(hits) else [0.2, 0.5, 0.3, 0.1])
    if name == "owner":
        weights = {team: float(count_of(text, *cues)) for team, cues in _TEAM_CUES.items()}
        weights["unknown"] = 0.5  # wins only when no team's words appear
        return choice_answer(list(question["criteria"]), weights)
    if name == "page_oncall":
        if hits[3] or any_of(text, *_NOW):
            return noul_answer(0.9)
        return noul_answer(0.45 if hits[2] else 0.1)
    if name == "customer_facing":
        if any_of(text, *_INTERNAL):
            return noul_answer(0.1)
        return noul_answer(0.85 if any_of(text, *_CUSTOMER) else 0.4)
    if name == "data_at_risk":
        return noul_answer(0.9 if any_of(text, *_DATA) else 0.05)
    if name == "regression":
        return noul_answer(0.9 if _REGRESSION.search(text) or any_of(text, "new version", "latest release") else 0.15)
    return None

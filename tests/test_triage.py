"""Offline tests: the form, the keyword rules through the real SDK, the grader, the CLI."""

import pytest
from typesafe_sdk import Noul

from incident_triage.arms import NoModel, baseline_arm, constrained_by_default, ollama_arm
from incident_triage.cli import main, render
from incident_triage.form import LABELS, QUESTIONS, SEVERITY, TEAMS, answerer, state_for, ticked
from incident_triage.grade import grade, load_incidents, markdown


def test_the_form_has_all_three_kinds_of_question_and_a_label_for_each():
    assert {q.type for q in QUESTIONS.values()} == {"score", "choice", "noul"}
    assert set(LABELS) == set(QUESTIONS)


def test_rules_answer_an_outage_through_the_real_sdk():
    arm = baseline_arm(answerer)
    report = "Checkout is returning 502s for every customer since the 14:05 deploy. We're losing orders right now."
    response = arm.ask(state_for(report), QUESTIONS)
    assert response is not None and set(response.answers) == set(QUESTIONS)
    assert ticked("severity", response.answers["severity"])[0] == "critical"
    assert response.answers["page_oncall"].noul >= 0.5
    assert response.answers["regression"].noul >= 0.5
    assert response.answers["owner"].choice in TEAMS
    assert arm.calls[-1].ok and arm.calls[-1].model == "keyword-baseline"


def test_rules_leave_a_cosmetic_report_alone():
    response = baseline_arm(answerer).ask(
        state_for("The dashboard chart legend overlaps the axis labels in Safari. Cosmetic, nobody is blocked."),
        QUESTIONS,
    )
    assert response is not None
    assert ticked("severity", response.answers["severity"])[0] == "cosmetic"
    assert response.answers["owner"].choice == "frontend"
    assert response.answers["page_oncall"].noul < 0.5 and response.answers["data_at_risk"].noul < 0.5


def test_a_question_with_no_rule_gets_maximum_uncertainty():
    response = baseline_arm(answerer).ask(state_for("anything"), {"mystery": Noul(instructions="Is it a mystery?")})
    assert response is not None and response.answers["mystery"].noul == 0.5


def test_bundled_reports_are_labelled_for_every_question():
    incidents = load_incidents()
    assert len(incidents) == 20
    for incident in incidents:
        assert set(incident.labels) == set(QUESTIONS)
        assert incident.labels["severity"] in range(len(SEVERITY))
        assert incident.labels["owner"] in TEAMS
        for question in ("page_oncall", "customer_facing", "data_at_risk", "regression"):
            assert isinstance(incident.labels[question], bool)


def test_grade_counts_right_answers_per_question():
    incidents = load_incidents()[:5]
    report = grade([baseline_arm(answerer)], incidents)
    (result,) = report["results"].values()
    assert result["answered"] == 5 and all(0 <= v <= 5 for v in result["right"].values())
    assert 0 <= result["severity_within_one"] <= 5 and 0 <= result["all_right"] <= 5
    (split_result,) = grade([baseline_arm(answerer)], incidents, split=True)["results"].values()
    assert split_result["right"] == result["right"]  # the rules are deterministic, so batching changes nothing
    assert split_result["summary"]["calls"] == 6 * 5
    text = markdown(report)
    assert all(label in text for label in LABELS.values()) and "all six right" in text


def test_render_shows_each_question_and_the_time():
    text = render("api.example.com is down for everyone", [baseline_arm(answerer)])
    assert all(label in text for label in LABELS.values())
    assert "critical" in text and "keyword rules" in text and " ms" in text


def test_ollama_arm_fails_once_up_front_without_a_server():
    with pytest.raises(NoModel, match="No Ollama server"):
        ollama_arm("qwen2.5:7b", base_url="http://127.0.0.1:9/v1")


def test_cli_runs_offline(capsys):
    assert main(["ask", "The site is down for everyone"]) == 0
    assert main(["grade"]) == 0
    out = capsys.readouterr().out
    assert "Page the on-call now?" in out and "| keyword rules |" in out


def test_cloud_models_get_prompted_json_and_local_ones_the_schema():
    assert constrained_by_default("qwen2.5:7b") and constrained_by_default("tinyllama")
    assert not constrained_by_default("minimax-m3.1-flash:cloud")

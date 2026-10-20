"""triage ask | demo | grade: offline by default; --ollama [MODEL] adds a local model served by Ollama."""

from __future__ import annotations

import argparse
import sys

from incident_triage.arms import DEFAULT_OLLAMA, OLLAMA_URL, Arm, NoModel, baseline_arm, ollama_arm
from incident_triage.form import LABELS, QUESTIONS, answerer, state_for, ticked
from incident_triage.grade import grade, load_incidents, markdown

COL = 34


def build_arms(args: argparse.Namespace) -> list[Arm]:
    arms = [baseline_arm(answerer)]
    if args.ollama:
        arms.append(ollama_arm(args.ollama, base_url=args.ollama_url))
    return arms


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def bar(p: float, width: int = 10) -> str:
    full = round(max(0.0, min(1.0, p)) * width)
    return "█" * full + "░" * (width - full)


def render(report: str, arms: list[Arm]) -> str:
    """Rows are the questions, columns the players; each cell is the box ticked and how sure the player was."""
    responses = [arm.ask(state_for(report), QUESTIONS) for arm in arms]
    width = max(len(label) for label in LABELS.values()) + 2
    lines = [f"“{clip(report, 110)}”", "", " " * width + "".join(clip(a.name, COL - 2).ljust(COL) for a in arms)]
    for name, label in LABELS.items():
        row = label.ljust(width)
        for response in responses:
            if response is None:
                row += "✗ broken answer".ljust(COL)
            else:
                box, p = ticked(name, response.answers[name])
                row += f"{clip(box, 14).ljust(15)}{bar(p)} {p:>4.0%}  "
        lines.append(row)
    lines += ["", "time".ljust(width) + "".join(f"{a.calls[-1].latency_ms:,.0f} ms".ljust(COL) for a in arms)]
    lines += [f"{a.name}: {clip(a.calls[-1].error, 140)}" for a in arms if a.calls[-1].error]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_ in [
        ("ask", "fill in the triage form for a report you type ('-' or nothing reads stdin)"),
        ("demo", "the first five bundled reports, each player side by side"),
        ("grade", "all bundled reports against their labels: right answers per question, per player"),
    ]:
        p = sub.add_parser(name, help=help_)
        p.add_argument(
            "--ollama", nargs="?", const=DEFAULT_OLLAMA, metavar="MODEL",
            help=f"add a local model served by Ollama, free (default {DEFAULT_OLLAMA})",
        )  # fmt: skip
        p.add_argument(
            "--ollama-url", default=OLLAMA_URL, help=f"Ollama's OpenAI-compatible URL (default {OLLAMA_URL})"
        )
        if name == "ask":
            p.add_argument("report", nargs="?", default="-")
        if name == "demo":
            p.add_argument("--count", type=int, default=5, help="how many bundled reports to show")
        if name == "grade":
            p.add_argument("--split", action="store_true", help="one request per question instead of one per report")
    args = parser.parse_args(argv)

    try:
        arms = build_arms(args)
    except NoModel as exc:
        print(exc, file=sys.stderr)
        return 2
    if not args.ollama:
        print("▸ Offline: the keyword rules answer, not a model. Add --ollama for a local one.\n", file=sys.stderr)

    if args.cmd == "ask":
        report = (sys.stdin.read() if args.report == "-" else args.report).strip()
        if not report:
            print('Give a report: triage ask "api.example.com is down for everyone"', file=sys.stderr)
            return 2
        print(render(report, arms))
    elif args.cmd == "demo":
        for incident in load_incidents()[: args.count]:
            print(render(incident.report, arms), end="\n\n")
    else:
        print(markdown(grade(arms, load_incidents(), split=args.split)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Live runner for the Phase 7 emails: draft, write, and stop at the AP review pause.

Every case the graph handles (the PO path, and an exact duplicate) runs through the graph
with the SQLite checkpointer until it pauses for review. The PO investigator's answers are
replayed from a saved run by default, so no 3-hour rerun is needed; --investigator live runs
the model instead. The communicator model writes every paragraph live. The non-PO cases have
no graph path until Phase 8, so their drafts are built from the eval's agent verdicts (as
check_emails.py does) and written by the same communicator, with no review. Saves
output/phase7/emails_<model>.json and .md. Exit code 0 when every paragraph passed the fact
check on the first try, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_emails.py
    .venv\\Scripts\\python.exe scripts\\run_emails.py --plant EX-001
    .venv\\Scripts\\python.exe scripts\\run_emails.py --investigator live

A case already in the checkpoint file is not started again: delete
output/phase7/checkpoints.sqlite to start over. --plant runs one case into its own files
and adds an invented number to its first paragraph.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUTPUT = ROOT / "output" / "phase7"
SAVED_RUN = ROOT / "output" / "phase6" / "po_run_qwen3-14b.json"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver

from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.emails import EXPORT_DATE, draft_emails, write_paragraph
from ap_copilot.graph import build_graph
from ap_copilot.investigator import OllamaClient
from ap_copilot.replay import ReplayClient, load_run
from ap_copilot.review import DecisionLog
from ap_copilot.rules import assess
from check_emails import eval_outcome  # same folder: scripts\ is first on sys.path

PLANT = "The difference comes to 999.99 in total."


class PlantingWriter:
    """Wraps the communicator and adds an invented number to its first paragraph."""

    def __init__(self, writer):
        self.writer = writer
        self.model = writer.model
        self.planted = ""

    def chat(self, messages, tools=None, schema=None) -> dict:
        reply = self.writer.chat(messages, tools=tools, schema=schema)
        if not self.planted:
            reply["message"]["content"] += " " + PLANT
            self.planted = f"added to the first paragraph: {PLANT}"
        return reply


def graph_cases(invoices, ref) -> list[str]:
    """The exception IDs the graph handles until Phase 8: the PO path and exact duplicates, in sheet order."""
    cases = []
    for invoice in invoices:
        assessment = assess(invoice, ref)
        if assessment.path == "po" or "exact_duplicate" in assessment.findings:
            cases.append(invoice.exception_id)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft every email with the live communicator, up to the AP review.")
    parser.add_argument("--investigator", choices=("saved", "live"), default="saved",
                        help="replay the saved PO investigator run (default) or run the model live")
    parser.add_argument("--plant", metavar="EXCEPTION_ID",
                        help="run one case into its own files, with an invented number in its first paragraph")
    args = parser.parse_args()

    ref = load_reference()
    invoices = {invoice.exception_id: invoice for invoice in load_invoices()}
    if args.plant and args.plant not in invoices:
        parser.error(f"unknown case {args.plant}")
    expected = {row["exception_id"]: row for row in read_csv(EVALS / "expected_outcomes.csv")}
    in_graph = graph_cases(invoices.values(), ref)

    writer = OllamaClient("communicator")
    model = writer.model
    if args.plant:
        writer = PlantingWriter(writer)
    if args.investigator == "saved":
        saved_model, saved = load_run(SAVED_RUN)
        clients = {exception_id: ReplayClient(saved.get(exception_id, {"exception_id": exception_id}), saved_model)
                   for exception_id in in_graph}
        investigator = "replay of output/phase6/po_run_qwen3-14b.json"
    else:
        live = OllamaClient("po_investigator")
        clients = {exception_id: live for exception_id in in_graph}
        investigator = "live"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(OUTPUT / ("checkpoints_planted.sqlite" if args.plant else "checkpoints.sqlite"),
                                 check_same_thread=False)
    saver = SqliteSaver(connection)
    log = DecisionLog(OUTPUT / "decision_log.jsonl")
    print(f"email run: communicator {model}; PO investigator {investigator}; as of {EXPORT_DATE}")

    cases = []
    paused = 0
    for exception_id in [args.plant] if args.plant else list(invoices):
        if exception_id in in_graph:
            graph = build_graph(ref, invoices, clients[exception_id], writer=writer, checkpointer=saver, log=log)
            config = {"configurable": {"thread_id": exception_id}}
            snapshot = graph.get_state(config)
            if snapshot.values:
                label = "already started: " + ("paused for review" if snapshot.next else "reviewed")
            else:
                graph.invoke({"exception_id": exception_id, "as_of": EXPORT_DATE}, config)
                label = "paused for review"
                snapshot = graph.get_state(config)
            state = snapshot.values
            paused += bool(snapshot.next)
            source = "graph"
        else:
            assessment, outcome = eval_outcome(invoices[exception_id], ref, expected[exception_id])
            emails, calls = [], []
            for email in draft_emails(assessment, outcome, {}, ref, EXPORT_DATE):
                written, call = write_paragraph(email, writer, ref)
                emails.append(written)
                calls.append(call)
            state = {"exception_id": exception_id, "outcome": outcome, "emails": emails, "writer_calls": calls}
            label = "non-PO: eval verdicts until Phase 8; no review"
            source = "non_po_eval_verdicts"
        cases.append({"exception_id": exception_id, "source": source, **state})

        print(f"{exception_id}  {label}")
        for email in state.get("emails", []):
            when = email["release_on"] or email["opens_after"]
            print(f"   {email['template']} to {email['recipient_id']} {email['status']}"
                  f"{f' ({when})' if when else ''}: paragraph {email['paragraph_source']}")
            for problem in email["fact_check"]:
                print(f"      ! fact check: {problem}")
    connection.close()

    calls = [call for case in cases for call in case.get("writer_calls", [])]
    drafted = sum(len(case.get("emails", [])) for case in cases)
    passed = sum(not call["problems"] for call in calls)
    print("summary")
    print(f"  emails drafted: {drafted}; paused for review: {paused}")
    print(f"  fact check: {passed} of {len(calls)} paragraphs passed; {len(calls) - passed} fallbacks")
    print(f"  communicator: {round(sum(call['seconds'] for call in calls), 1)} s")
    if args.plant:
        print(f"  plant: {writer.planted}")

    name = "emails_" + ("planted_" if args.plant else "") + model.replace(":", "-")
    run = {"communicator": model, "investigator": investigator, "as_of": EXPORT_DATE, "plant": args.plant,
           "cases": cases}
    (OUTPUT / f"{name}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# Email drafts — communicator {model}, as of {EXPORT_DATE}"]
    for case in cases:
        for email in case.get("emails", []):
            when = email["release_on"] or email["opens_after"]
            lines += ["", f"## {email['email_id']} — {email['status']}{f' ({when})' if when else ''}, "
                          f"paragraph {email['paragraph_source']}"]
            lines += [f"- fact check: {problem}" for problem in email["fact_check"]]
            lines += ["", "```text", email["body"], "```"]
    (OUTPUT / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved output/phase7/{name}.json and output/phase7/{name}.md")
    print(f"{passed} of {len(calls)} paragraphs passed the fact check")
    return 0 if passed == len(calls) else 1


if __name__ == "__main__":
    sys.exit(main())

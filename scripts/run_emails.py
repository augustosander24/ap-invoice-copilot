"""Live runner for the emails: draft, write, and stop at the AP review pause.

Every invoice runs through the graph with the SQLite checkpointer until it pauses for
review. Both investigators' answers are replayed from saved runs by default: the PO
investigator's from output/phase6/po_run_qwen3-14b.json, the non-PO investigator's from
output/phase8/nonpo_run_<its model>.json (written by scripts/run_nonpo_agent.py), so no long
rerun is needed; --investigator live runs both models instead. The communicator model writes
every paragraph live. The drafts are compared with evals/expected_threads.csv as
check_emails.py compares its own. Saves output/phase8/emails_<model>.json and .md. Exit code 0
when every paragraph passed the fact check on the first try and every thread matches,
otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_emails.py
    .venv\\Scripts\\python.exe scripts\\run_emails.py --plant EX-001
    .venv\\Scripts\\python.exe scripts\\run_emails.py --investigator live

A case already in the checkpoint file is not started again: delete
output/phase8/checkpoints.sqlite to start over. --plant runs one case into its own files
and adds an invented number to its first paragraph.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUTPUT = ROOT / "output" / "phase8"
SAVED_RUN = ROOT / "output" / "phase6" / "po_run_qwen3-14b.json"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver

from ap_copilot.config import get_model
from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.emails import EXPORT_DATE
from ap_copilot.graph import build_graph
from ap_copilot.investigator import OllamaClient
from ap_copilot.replay import ReplayClient, load_run
from ap_copilot.review import DecisionLog
from ap_copilot.rules import assess
from check_emails import thread_problems  # same folder: scripts\ is first on sys.path

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


def saved_nonpo_run() -> Path:
    """The non-PO investigator's saved run for the model it is set to use."""
    return OUTPUT / f"nonpo_run_{get_model('nonpo_investigator').replace(':', '-')}.json"


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
    paths = {exception_id: assess(invoice, ref).path for exception_id, invoice in invoices.items()}
    threads = {}
    for row in read_csv(EVALS / "expected_threads.csv"):
        threads.setdefault(row["exception_id"], []).append(row)

    writer = OllamaClient("communicator")
    model = writer.model
    if args.plant:
        writer = PlantingWriter(writer)
    if args.investigator == "saved":
        nonpo_run = saved_nonpo_run()
        if not nonpo_run.exists():
            parser.error(f"no saved non-PO run: run scripts\\run_nonpo_agent.py first ({nonpo_run.name})")
        runs = {"po": load_run(SAVED_RUN), "non_po": load_run(nonpo_run)}
        clients = {}
        for exception_id, path in paths.items():
            run_model, saved = runs[path]
            clients[exception_id] = ReplayClient(saved.get(exception_id, {"exception_id": exception_id}), run_model)
        investigator = f"replay of output/phase6/po_run_qwen3-14b.json and output/phase8/{nonpo_run.name}"
    else:
        live = {"po": OllamaClient("po_investigator"), "non_po": OllamaClient("nonpo_investigator")}
        clients = {exception_id: live[path] for exception_id, path in paths.items()}
        investigator = "live"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(OUTPUT / ("checkpoints_planted.sqlite" if args.plant else "checkpoints.sqlite"),
                                 check_same_thread=False)
    saver = SqliteSaver(connection)
    log = DecisionLog(OUTPUT / "decision_log.jsonl")
    print(f"email run: communicator {model}; investigators {investigator}; as of {EXPORT_DATE}")

    cases = []
    paused = matched_threads = thread_rows = thread_failures = 0
    for exception_id in [args.plant] if args.plant else list(invoices):
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
        rows = threads.get(exception_id, [])
        problems, matched = thread_problems(state.get("emails", []), rows)
        matched_threads += matched
        thread_rows += len(rows)
        thread_failures += len(problems)
        cases.append({"exception_id": exception_id, "thread_problems": problems, **state})

        print(f"{exception_id}  {label}")
        for email in state.get("emails", []):
            when = email["release_on"] or email["opens_after"]
            print(f"   {email['template']} to {email['recipient_id']} {email['status']}"
                  f"{f' ({when})' if when else ''}: paragraph {email['paragraph_source']}")
            for problem in email["fact_check"]:
                print(f"      ! fact check: {problem}")
        for problem in problems:
            print(f"   ! thread: {problem}")
    connection.close()

    calls = [call for case in cases for call in case.get("writer_calls", [])]
    drafted = sum(len(case.get("emails", [])) for case in cases)
    passed = sum(not call["problems"] for call in calls)
    print("summary")
    print(f"  emails drafted: {drafted}; paused for review: {paused}")
    print(f"  fact check: {passed} of {len(calls)} paragraphs passed; {len(calls) - passed} fallbacks")
    print(f"  communicator: {round(sum(call['seconds'] for call in calls), 1)} s")
    print(f"  threads: {matched_threads} of {thread_rows} match")
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
    print(f"saved output/phase8/{name}.json and output/phase8/{name}.md")
    print(f"{passed} of {len(calls)} paragraphs passed the fact check")
    return 0 if passed == len(calls) and not thread_failures else 1


if __name__ == "__main__":
    sys.exit(main())

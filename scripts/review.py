"""The AP operator's review: show each paused invoice, take a decision, resume the run.

For each invoice paused in output/phase8/checkpoints.sqlite it prints what the operator
reviews (recommendation, findings, the AP-queue facts, every draft) and asks for a decision
and a reason, then resumes the run: the graph applies the decision to the drafts and writes
one line to output/phase8/decision_log.jsonl. No model runs on resume. An invoice already
reviewed is reported and left as it is.

    .venv\\Scripts\\python.exe scripts\\review.py
    .venv\\Scripts\\python.exe scripts\\review.py EX-008
    .venv\\Scripts\\python.exe scripts\\review.py --decisions data\\input\\review_decisions.csv

With no arguments it reviews every paused invoice and asks in the terminal; exception IDs
limit it to those invoices; --decisions reads the decisions from a CSV instead of asking.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "phase8"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.graph import build_graph
from ap_copilot.review import DecisionLog


class NoModel:
    """Stands in for both models: resuming a review must never call one."""

    model = "none"

    def chat(self, messages, tools=None, schema=None) -> dict:
        raise RuntimeError("a model was called while resuming a review")


def show(exception_id: str, packet: dict) -> None:
    """Print what the operator reviews: the recommendation, the AP-queue facts, every draft, and any problems."""
    print(f"=== {exception_id}: recommendation {packet['recommendation']}; "
          f"findings {';'.join(packet['findings']) or 'none'}")
    for line in packet["ap_items"]:
        print(f"   AP: {line}")
    for email in packet["emails"]:
        release = f" (goes out if AP rules {email['release_on']})" if email["release_on"] else ""
        print(f"--- {email['email_id']} {email['status']}{release}")
        print(email["body"])
    for problem in packet.get("problems", []):
        print(f"   ! {problem}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review the paused invoices and resume their runs.")
    parser.add_argument("ids", nargs="*", metavar="EXCEPTION_ID", help="review only these invoices")
    parser.add_argument("--decisions", metavar="CSV", help="read the decisions from this file instead of asking")
    args = parser.parse_args()
    checkpoints = OUTPUT / "checkpoints.sqlite"
    if not checkpoints.exists():
        parser.error("no checkpoints yet: run scripts\\run_emails.py first")

    ref = load_reference()
    invoices = {invoice.exception_id: invoice for invoice in load_invoices()}
    decisions = {row["exception_id"]: row for row in read_csv(Path(args.decisions))} if args.decisions else {}
    connection = sqlite3.connect(checkpoints, check_same_thread=False)
    saver = SqliteSaver(connection)
    log = DecisionLog(OUTPUT / "decision_log.jsonl")
    graph = build_graph(ref, invoices, NoModel(), writer=NoModel(), checkpointer=saver, log=log)
    threads = sorted({checkpoint.config["configurable"]["thread_id"] for checkpoint in saver.list(None)})

    for exception_id in args.ids or (sorted(decisions) if args.decisions else threads):
        config = {"configurable": {"thread_id": exception_id}}
        snapshot = graph.get_state(config)
        if not snapshot.values:
            print(f"{exception_id}: not started; run scripts\\run_emails.py first")
            continue
        if not snapshot.next:
            print(f"{exception_id}: already reviewed ({snapshot.values['review']['decision']}); nothing changed")
            continue
        while snapshot.next:
            packet = snapshot.tasks[0].interrupts[-1].value
            if args.decisions:
                if packet.get("problems"):
                    print(f"{exception_id}: {'; '.join(packet['problems'])}; left paused")
                    break
                row = decisions[exception_id]
                decision = {"decision": row["decision"], "reason": row["reason"]}
            else:
                show(exception_id, packet)
                choice = input(f"Decision ({' / '.join(packet['decisions'])}): ").strip()
                prompt = "Reason (required): " if choice in packet["reason_required"] else "Reason (optional): "
                decision = {"decision": choice, "reason": input(prompt).strip()}
            graph.invoke(Command(resume=decision), config)
            snapshot = graph.get_state(config)
        else:  # no break: the decision went through
            state = snapshot.values
            print(f"{exception_id}: {state['review']['decision']} -> {state['final_recommendation']}; "
                  f"logged {state['logged'][-1]}")
            for email in state["emails"]:
                reply_by = f", reply by {email['reply_by']}" if email["reply_by"] else ""
                print(f"   {email['email_id']} {email['status']}{reply_by}")

    reviewed = [graph.get_state({"configurable": {"thread_id": thread}}).values for thread in threads]
    (OUTPUT / "reviewed.json").write_text(json.dumps(reviewed, indent=2, ensure_ascii=False), encoding="utf-8")
    connection.close()
    print(f"decision log: {len(log.entries())} entries")
    print("saved output/phase8/reviewed.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

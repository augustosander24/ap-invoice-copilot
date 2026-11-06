"""The AP operator's review: show each paused invoice, take a decision, resume the run.

For each invoice paused in output/phase10/checkpoints.sqlite it prints what the operator
reviews (recommendation, findings, the AP-queue facts, every draft, numbered), lets the operator
edit a draft's paragraph or explanation, and asks for a decision and a reason, then resumes the
run: the graph applies the edits and the decision to the drafts and writes one line to
output/phase10/decision_log.jsonl. No model runs on resume. An invoice already reviewed is
reported and left as it is.

    .venv\\Scripts\\python.exe scripts\\review.py
    .venv\\Scripts\\python.exe scripts\\review.py EX-008
    .venv\\Scripts\\python.exe scripts\\review.py --decisions data\\input\\review_decisions.csv --edits data\\input\\review_edits.csv

With no arguments it reviews every paused invoice and asks in the terminal; exception IDs
limit it to those invoices; --decisions reads the decisions from a CSV instead of asking, and
--edits the operator's edits. --set reviews a held-out batch in output/phase10/<set>/.

    .venv\\Scripts\\python.exe scripts\\review.py --set heldout_a --decisions data\\heldout_a\\input\\review_decisions.csv
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "phase10"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ap_copilot.data import DATA_SETS, data_set, load_invoices, load_reference, read_csv
from ap_copilot.graph import build_graph
from ap_copilot.inbox import CsvInbox
from ap_copilot.replay import NoModel
from ap_copilot.review import DecisionLog


def show(exception_id: str, packet: dict) -> None:
    """Print what the operator reviews: the recommendation, the AP-queue facts, every draft, and any problems."""
    print(f"=== {exception_id}: recommendation {packet['recommendation']}; "
          f"findings {';'.join(packet['findings']) or 'none'}")
    for line in packet["ap_items"]:
        print(f"   AP: {line}")
    for number, email in enumerate(packet["emails"], 1):
        release = f" (goes out if AP rules {email['release_on']})" if email["release_on"] else ""
        print(f"--- {number}. {email['email_id']} {email['status']}{release}")
        print(email["body"])
    for problem in packet.get("problems", []):
        print(f"   ! {problem}")


def ask_edits(packet: dict) -> list[dict]:
    """The operator's edits, typed in the terminal: a draft's number, the part, the issue, the new text."""
    edits = []
    while packet["emails"]:
        choice = input("Edit a draft? Its number, or Enter for none: ").strip()
        if not choice:
            return edits
        if not choice.isdigit() or not 1 <= int(choice) <= len(packet["emails"]):
            print(f"   ! type a number from 1 to {len(packet['emails'])}")
            continue
        part = input("Part (paragraph / explanation): ").strip()
        issue = input("Issue number: ").strip() if part == "explanation" else ""
        edits.append({"email_id": packet["emails"][int(choice) - 1]["email_id"], "part": part, "issue": issue,
                      "text": input("New text: ").strip()})
    return edits


def main() -> int:
    parser = argparse.ArgumentParser(description="Review the paused invoices and resume their runs.")
    parser.add_argument("ids", nargs="*", metavar="EXCEPTION_ID", help="review only these invoices")
    parser.add_argument("--decisions", metavar="CSV", help="read the decisions from this file instead of asking")
    parser.add_argument("--edits", metavar="CSV", help="with --decisions: read the operator's edits from this file")
    parser.add_argument("--set", choices=DATA_SETS, default="eval", help="the data set (default: the 22-case eval)")
    args = parser.parse_args()
    if args.edits and not args.decisions:
        parser.error("--edits needs --decisions")
    folders = data_set(args.set)
    output = OUTPUT if args.set == "eval" else OUTPUT / args.set
    checkpoints = output / "checkpoints.sqlite"
    if not checkpoints.exists():
        parser.error("no checkpoints yet: run scripts\\run_emails.py first")

    ref = load_reference(folders.reference)
    invoices = {invoice.exception_id: invoice for invoice in load_invoices(folders.input / "exception_list.xlsx")}
    decisions = {row["exception_id"]: row for row in read_csv(Path(args.decisions))} if args.decisions else {}
    edits = {}
    for row in read_csv(Path(args.edits)) if args.edits else []:
        edits.setdefault(row["exception_id"], []).append({key: row[key] for key in ("email_id", "part", "issue", "text")})
    connection = sqlite3.connect(checkpoints, check_same_thread=False)
    saver = SqliteSaver(connection)
    log = DecisionLog(output / "decision_log.jsonl")
    graph = build_graph(ref, invoices, NoModel(), writer=NoModel(), checkpointer=saver, log=log,
                        interpreter=NoModel(), inbox=CsvInbox(folders.input / "inbox.csv"))
    threads = sorted({checkpoint.config["configurable"]["thread_id"] for checkpoint in saver.list(None)})

    for exception_id in args.ids or (sorted(decisions) if args.decisions else threads):
        config = {"configurable": {"thread_id": exception_id}}
        snapshot = graph.get_state(config)
        if not snapshot.values:
            print(f"{exception_id}: not started; run scripts\\run_emails.py first")
            continue
        if snapshot.next != ("review",):
            print(f"{exception_id}: already reviewed ({snapshot.values['review']['decision']}); nothing changed")
            continue
        submitted = False  # a packet's problems count only after this run has answered it
        while snapshot.next == ("review",):
            packet = snapshot.tasks[0].interrupts[-1].value
            if args.decisions:
                if submitted and packet.get("problems"):
                    print(f"{exception_id}: {'; '.join(packet['problems'])}; left paused")
                    break
                row = decisions[exception_id]
                decision = {"decision": row["decision"], "reason": row["reason"], "edits": edits.get(exception_id, [])}
            else:
                show(exception_id, packet)
                changes = ask_edits(packet)
                choice = input(f"Decision ({' / '.join(packet['decisions'])}): ").strip()
                prompt = "Reason (required): " if choice in packet["reason_required"] else "Reason (optional): "
                decision = {"decision": choice, "reason": input(prompt).strip(), "edits": changes}
            graph.invoke(Command(resume=decision), config)
            submitted = True
            snapshot = graph.get_state(config)
        else:  # no break: the decision went through
            state = snapshot.values
            print(f"{exception_id}: {state['review']['decision']} -> {state['final_recommendation']}; "
                  f"logged {state['logged'][-1]}")
            for email in state["emails"]:
                reply_by = f", reply by {email['reply_by']}" if email["reply_by"] else ""
                print(f"   {email['email_id']} {email['status']}{reply_by}")
                for edit in email.get("edits", []):
                    where = f" (issue {edit['issue']})" if edit["issue"] else ""
                    print(f"      edited {edit['part']}{where}: {edit['after']}")

    reviewed = [graph.get_state({"configurable": {"thread_id": thread}}).values for thread in threads]
    (output / "reviewed.json").write_text(json.dumps(reviewed, indent=2, ensure_ascii=False), encoding="utf-8")
    connection.close()
    print(f"decision log: {len(log.entries())} entries")
    print(f"saved {(output / 'reviewed.json').relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

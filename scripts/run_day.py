"""One follow-up run: read the replies up to the as-of date and send what is due.

Each invoice waiting in output/phase9/checkpoints.sqlite resumes with the as-of date: the graph
reads the inbox replies dated up to it, the reply interpreter labels each new one (replayed
from output/phase9/replies_<its model>.json, written by scripts/run_replies.py, by default;
--interpreter live runs the model), code sends what is due (a waiting approval, a reminder, an
escalation), the communicator writes each follow-up paragraph live, and the day is logged in
output/phase9/decision_log.jsonl. The threads are compared with evals/expected_threads.csv as
check_followups.py compares its own. An invoice already run for that date is left as it is, so a
second run of the same day changes nothing. Saves output/phase9/day_<as_of>.json and .md, built
from the saved state, so a second run writes the same files. Exit code 0 when every follow-up
paragraph passed the fact check on the first try and every thread and reply matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_day.py --day 4
    .venv\\Scripts\\python.exe scripts\\run_day.py --day 5
    .venv\\Scripts\\python.exe scripts\\run_day.py --as-of 2026-12-08 --interpreter live

--day N is the demo calendar's day N: N business days after day 0 (2026-11-30).
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
OUTPUT = ROOT / "output" / "phase9"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ap_copilot.config import get_model
from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.emails import EXPORT_DATE, add_business_days
from ap_copilot.graph import as_of_problems, build_graph
from ap_copilot.inbox import CsvInbox
from ap_copilot.investigator import OllamaClient
from ap_copilot.replay import CallReplay, NoModel, load_calls
from ap_copilot.review import DecisionLog
from check_followups import followup_problems, ruling_problems  # same folder: scripts\ is first on sys.path


def saved_replies_run() -> Path:
    """The reply interpreter's saved run for the model it is set to use."""
    return OUTPUT / f"replies_{get_model('reply_interpreter').replace(':', '-')}.json"


def print_case(exception_id: str, label: str, state: dict, as_of: str) -> None:
    """The invoice's day: its status, the replies read today, what went out today, and what is left with AP."""
    print(f"{exception_id}  {label}: {state.get('invoice_status', '')}")
    for reply in state.get("replies", []):
        if reply["as_of"] == as_of:
            detail = f" {reply['detail']}" if reply["detail"] else ""
            print(f"   reply {reply['message_id']} {reply['received_date']} -> {reply['email_id'] or 'no email'}: "
                  f"{reply['label']}{detail}; {reply['next_step']}")
            print(f"      reason: {reply['reason']}")
            for problem in reply["problems"]:
                print(f"      ! check: {problem}")
    for email in state.get("emails", []):
        if email["sent_on"] == as_of:
            cc = f" cc {email['cc_id']}" if email.get("cc_id") else ""
            print(f"   {email['template']} to {email['recipient_id']}{cc} sent, reply by {email['reply_by']}: "
                  f"paragraph {email['paragraph_source']}")
            for problem in email["fact_check"]:
                print(f"      ! fact check: {problem}")
    if state.get("day", {}).get("as_of") == as_of:
        for item in state["day"]["ap_items"]:
            print(f"   AP: {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one follow-up day on every waiting invoice.")
    when = parser.add_mutually_exclusive_group(required=True)
    when.add_argument("--day", type=int, help="the demo calendar's day: business days after day 0")
    when.add_argument("--as-of", help="the run's date, YYYY-MM-DD")
    parser.add_argument("--interpreter", choices=("saved", "live"), default="saved",
                        help="replay the saved reply interpreter run (default) or run the model live")
    args = parser.parse_args()
    as_of = add_business_days(EXPORT_DATE, args.day) if args.day is not None else args.as_of
    problems = as_of_problems({"as_of": EXPORT_DATE}, {"as_of": as_of})
    if problems:
        parser.error(problems[0])
    checkpoints = OUTPUT / "checkpoints.sqlite"
    if not checkpoints.exists():
        parser.error("no checkpoints yet: run scripts\\run_emails.py and scripts\\review.py first")

    ref = load_reference()
    invoices = {invoice.exception_id: invoice for invoice in load_invoices()}
    rows = {}
    for row in read_csv(EVALS / "expected_threads.csv"):
        rows.setdefault(row["exception_id"], []).append(row)
    if args.interpreter == "saved":
        replies_run = saved_replies_run()
        if not replies_run.exists():
            parser.error(f"no saved reply interpreter run: run scripts\\run_replies.py first ({replies_run.name})")
        model, calls = load_calls(replies_run, "calls")
        interpreter = CallReplay(calls, model, f"output/phase9/{replies_run.name}")
        source = f"replay of output/phase9/{replies_run.name}"
    else:
        interpreter = OllamaClient("reply_interpreter")
        source = interpreter.model
    writer = OllamaClient("communicator")
    connection = sqlite3.connect(checkpoints, check_same_thread=False)
    saver = SqliteSaver(connection)
    log = DecisionLog(OUTPUT / "decision_log.jsonl")
    graph = build_graph(ref, invoices, NoModel(), writer=writer, checkpointer=saver, log=log,
                        interpreter=interpreter, inbox=CsvInbox())
    print(f"follow-up run: as of {as_of}; reply interpreter {source}; communicator {writer.model}")

    cases, matched, thread_rows, failures, ran = [], 0, 0, 0, 0
    for exception_id in invoices:
        config = {"configurable": {"thread_id": exception_id}}
        snapshot = graph.get_state(config)
        state = snapshot.values
        if not state or snapshot.next == ("review",):
            label = "not reviewed yet: run scripts\\review.py first"
        elif not snapshot.next:
            label = "follow-up done"
        elif state["as_of"] == as_of:
            label = f"already run for {as_of}; nothing changed"
        elif state["as_of"] > as_of:
            label = f"already run for {state['as_of']}; not run for an earlier date"
        else:
            graph.invoke(Command(resume={"as_of": as_of}), config)
            snapshot = graph.get_state(config)
            state = snapshot.values
            label = "ran" if snapshot.next else "ran; follow-up done"
            ran += 1
        problems, good = followup_problems(state.get("emails", []), state.get("threads", []),
                                           state.get("replies", []), rows.get(exception_id, []), as_of)
        problems += ruling_problems(state.get("emails", []), state.get("threads", []), as_of)
        matched += good
        thread_rows += len(rows.get(exception_id, []))
        failures += len(problems)
        print_case(exception_id, label, state, as_of)
        for problem in problems:
            print(f"   ! thread: {problem}")
        cases.append({"exception_id": exception_id, "thread_problems": problems, **state})
    connection.close()

    sent = [email for case in cases for email in case.get("emails", []) if email["sent_on"] == as_of]
    follow_ups = [email for email in sent if email.get("follows")]
    calls = [call for case in cases for call in case.get("writer_calls", [])
             if call["email_id"] in {email["email_id"] for email in follow_ups}]
    passed = sum(not call["problems"] for call in calls)
    replies = [reply for case in cases for reply in case.get("replies", []) if reply["as_of"] <= as_of]
    print("summary")
    print(f"  invoices run: {ran}; replies read: {len(replies)} in all")
    print(f"  sent today: {sum(e['template'] == 'reminder' for e in sent)} reminders, "
          f"{sum(e['template'] == 'escalation' for e in sent)} escalations, "
          f"{len(sent) - len(follow_ups)} approvals after their confirmations")
    print(f"  fact check: {passed} of {len(calls)} follow-up paragraphs passed; {len(calls) - passed} fallbacks")
    statuses = Counter(case.get("invoice_status", "") for case in cases)
    print("  status: " + ", ".join(f"{status} {count}" for status, count in sorted(statuses.items())))
    print(f"  threads: {matched} of {thread_rows} match")
    print(f"  decision log: {len(log.entries())} entries")

    name = f"day_{as_of}"
    run = {"as_of": as_of, "interpreter": source, "communicator": writer.model, "cases": cases}
    (OUTPUT / f"{name}.json").write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"# Follow-up run — as of {as_of}, communicator {writer.model}"]
    for email in sent:
        lines += ["", f"## {email['email_id']} — sent {as_of}, paragraph {email['paragraph_source'] or 'day 0'}"]
        lines += [f"- fact check: {problem}" for problem in email["fact_check"]]
        lines += ["", "```text", email["body"], "```"]
    (OUTPUT / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved output/phase9/{name}.json and output/phase9/{name}.md")
    print(f"{matched} of {thread_rows} threads match")
    return 0 if passed == len(calls) and not failures else 1


if __name__ == "__main__":
    sys.exit(main())

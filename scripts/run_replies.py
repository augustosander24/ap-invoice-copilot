"""Live runner for the reply interpreter: every reply in the mock inbox, scored against the eval.

Each reply is matched to the email it answers, drafted by code as check_emails.py drafts it
(agent verdicts from evals/expected_outcomes.csv) after the scripted review
(data/input/review_decisions.csv). The interpreter sees only who the email went to, its subject,
and the action it asked for, which the live drafts share. The local
Ollama model labels each reply in one fresh request, and code checks the promised date or the
person named. The label and detail are compared with evals/expected_threads.csv. Saves
output/phase9/replies_<model>.json, which scripts/run_day.py replays. Exit code 0 when every
reply matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_replies.py
    .venv\\Scripts\\python.exe scripts\\run_replies.py M-08 M-15

Message IDs limit the run to those replies, saved under a separate name.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
INPUT = ROOT / "data" / "input"
OUTPUT = ROOT / "output" / "phase9"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.emails import EXPORT_DATE, draft_emails
from ap_copilot.inbox import CsvInbox
from ap_copilot.investigator import OllamaClient
from ap_copilot.reply_interpreter import interpret
from ap_copilot.review import apply_decision
from check_emails import eval_outcome  # same folder: scripts\ is first on sys.path


def reply_emails(ref, invoices) -> dict[tuple[str, str], list[dict]]:
    """The emails that go out after the scripted review, by (vendor_id, invoice_number), as code drafts them."""
    expected = {row["exception_id"]: row for row in read_csv(EVALS / "expected_outcomes.csv")}
    decisions = {row["exception_id"]: row["decision"] for row in read_csv(INPUT / "review_decisions.csv")}
    drafts = {}
    for invoice in invoices:
        assessment, outcome = eval_outcome(invoice, ref, expected[invoice.exception_id])
        emails = apply_decision(draft_emails(assessment, outcome, {}, ref),
                                decisions.get(invoice.exception_id, "confirm"), EXPORT_DATE)
        drafts[(invoice.vendor_id, invoice.invoice_number)] = [email for email in emails
                                                               if email["status"] in ("sent", "waiting")]
    return drafts


def main() -> int:
    parser = argparse.ArgumentParser(description="Label every inbox reply with the live reply interpreter.")
    parser.add_argument("ids", nargs="*", metavar="MESSAGE_ID", help="run only these replies")
    args = parser.parse_args()
    ref = load_reference()
    invoices = load_invoices()
    drafts = reply_emails(ref, invoices)
    expected = {row["reply_message_id"]: row for row in read_csv(EVALS / "expected_threads.csv")
                if row["reply_message_id"]}
    replies = [reply for reply in CsvInbox().replies("9999-12-31") if not args.ids or reply.message_id in args.ids]
    unknown = set(args.ids) - {reply.message_id for reply in replies}
    if unknown:
        parser.error(f"not in the inbox: {', '.join(sorted(unknown))}")
    client = OllamaClient("reply_interpreter")
    print(f"reply interpreter run: {len(replies)} replies, model {client.model}")

    calls, matched, started = [], 0, time.perf_counter()
    for reply in replies:
        email = next(email for email in drafts[(reply.vendor_id, reply.invoice_number)]
                     if email["to_email"] == reply.from_email)
        record, call = interpret(reply, email, client, ref)
        row = expected[reply.message_id]
        got = (record["label"], record["detail"])
        want = (row["reply_label"], row["reply_detail"])
        matched += got == want
        detail = f" {record['detail']}" if record["detail"] else ""
        print(f"{'PASS' if got == want else 'FAIL'} {reply.message_id} {email['email_id']}: {record['label']}{detail}"
              f"  ({call['seconds']} s)")
        print(f"   reason: {record['reason']}")
        if record["model_label"] != record["label"]:
            print(f"   model said {record['model_label']}; the check made it unclear")
        for problem in record["problems"]:
            print(f"   ! check: {problem}")
        if got != want:
            print(f"   ! expected {want[0]}{' ' + want[1] if want[1] else ''}")
        calls.append({**call, "exception_id": email["exception_id"], "email_id": email["email_id"],
                      "label": record["label"], "detail": record["detail"], "model_label": record["model_label"],
                      "reason": record["reason"], "expected_label": want[0], "expected_detail": want[1]})

    print("summary")
    print(f"  replies {matched} of {len(replies)} match (label and detail)")
    print(f"  checks failed: {sum(bool(call['problems']) for call in calls)}")
    print(f"  model calls: {len(calls)}; {round(time.perf_counter() - started, 1)} s")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    name = "replies_" + client.model.replace(":", "-") + ("_" + "_".join(args.ids) if args.ids else "") + ".json"
    (OUTPUT / name).write_text(json.dumps({"model": client.model, "calls": calls}, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    print(f"saved output/phase9/{name}")
    print(f"{matched} of {len(replies)} replies match")
    return 0 if matched == len(replies) else 1


if __name__ == "__main__":
    sys.exit(main())

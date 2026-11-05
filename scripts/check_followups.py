"""Code-only check of the follow-up: day 0, day 4, and day 5 with no model and no saved run.

It drafts every invoice's emails as check_emails.py does (agent verdicts from
evals/expected_outcomes.csv, the fixed paragraph), applies the scripted review
(data/input/review_decisions.csv), then runs day 4 (2026-12-04) and day 5 (2026-12-07): the
replies dated up to each day are matched to their emails and labeled with the eval's
reply_label and reply_detail in place of the reply interpreter, and code sends what is due.
It compares every thread with evals/expected_threads.csv (the reply each thread gets, the day
the email opens, the day 4 reminder and its cc, the day 5 escalation and who it goes to),
checks that EX-008's released duplicate notice follows the vendor rule, and runs each day twice
to check that the second run changes nothing. Prints PASS or FAIL per case, "replies: N of 18
matched to their threads", "threads: N of 21 match", and "N of 22 cases match". Exit code 0 when
every case matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\check_followups.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "evals"
INPUT = ROOT / "data" / "input"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import load_invoices, load_reference, read_csv
from ap_copilot.emails import EXPORT_DATE, FALLBACK_PARAGRAPH, add_business_days, draft_emails, render
from ap_copilot.followup import follow_up, invoice_status, match_reply, open_threads
from ap_copilot.inbox import CsvInbox
from ap_copilot.review import apply_decision, final_recommendation
from check_emails import compare, eval_outcome  # same folder: scripts\ is first on sys.path

DAY4 = add_business_days(EXPORT_DATE, 4)
DAY5 = add_business_days(EXPORT_DATE, 5)


def followup_problems(emails: list[dict], threads: list[dict], replies: list[dict], rows: list[dict[str, str]],
                      as_of: str) -> tuple[list[str], int]:
    """Compare the threads with the invoice's thread rows up to as_of; return the problems and the rows that match.

    A row is checked on the days the run has reached: the reply its thread got, the day it opened, the
    day 4 reminder and its cc, and the day 5 escalation and who it went to."""
    ruled = {email["email_id"] for email in emails if email["release_on"]}  # released by AP's ruling: no thread row
    by_recipient = {thread["recipient_id"]: thread for thread in threads if thread["email_id"] not in ruled}
    follow = {(email["follows"], email["template"]): email for email in emails if email.get("follows")}
    labeled = {reply["message_id"]: reply for reply in replies}
    problems, matched = [], 0
    for row in rows:
        label = f"thread to {row['recipient_id']}"
        thread = by_recipient.pop(row["recipient_id"], None)
        if thread is None:
            problems.append(f"{label}: got none")
            continue
        before = len(problems)
        reply = labeled.get(row["reply_message_id"])
        if row["reply_message_id"] and reply is not None:
            compare(problems, f"{label} reply {row['reply_message_id']} thread", reply["email_id"], thread["email_id"])
            compare(problems, f"{label} reply_label", reply["label"], row["reply_label"])
            compare(problems, f"{label} reply_detail", reply["detail"], row["reply_detail"])
        if row["opens_on_day"] == "4" and as_of >= DAY4:
            compare(problems, f"{label} sent_on", thread["sent_on"], DAY4)
        reminder = follow.get((thread["email_id"], "reminder"))
        escalation = follow.get((thread["email_id"], "escalation"))
        if as_of >= DAY4:
            got = "reminder" if reminder and reminder["sent_on"] == DAY4 else "none"
            compare(problems, f"{label} day4_action", got, row["day4_action"])
            if reminder:
                compare(problems, f"{label} day4_cc", reminder["cc_id"], row["day4_cc"])
        if as_of >= DAY5:
            got = "escalation" if escalation and escalation["sent_on"] == DAY5 else "none"
            compare(problems, f"{label} day5_action", got, row["day5_action"])
            if escalation:
                compare(problems, f"{label} day5_to", escalation["recipient_id"], row["day5_to"])
        matched += len(problems) == before
    for recipient_id, thread in by_recipient.items():
        problems.append(f"thread to {recipient_id}: got {thread['template']}, expected none")
    return problems, matched


def ruling_problems(emails: list[dict], threads: list[dict], as_of: str) -> list[str]:
    """An email released by AP's ruling (EX-008): the vendor rule, day 4 reminder cc P-104, day 5 escalation to P-103."""
    problems = []
    for thread in threads:
        email = next(e for e in emails if e["email_id"] == thread["email_id"])
        if not email["release_on"]:
            continue
        follow = {e["template"]: e for e in emails if e.get("follows") == email["email_id"]}
        if as_of >= DAY4 and not thread["replies"]:
            reminder = follow.get("reminder")
            if not (reminder and reminder["sent_on"] == DAY4 and reminder["cc_id"] == "P-104"):
                problems.append(f"{email['email_id']}: expected a day 4 reminder cc P-104")
        if as_of >= DAY5 and not thread["replies"]:
            escalation = follow.get("escalation")
            if not (escalation and escalation["sent_on"] == DAY5 and escalation["recipient_id"] == "P-103"):
                problems.append(f"{email['email_id']}: expected a day 5 escalation to P-103")
    return problems


def main() -> int:
    ref = load_reference()
    invoices = load_invoices()
    expected = {row["exception_id"]: row for row in read_csv(EVALS / "expected_outcomes.csv")}
    threads_by_case, labels = {}, {}
    for row in read_csv(EVALS / "expected_threads.csv"):
        threads_by_case.setdefault(row["exception_id"], []).append(row)
        if row["reply_message_id"]:
            labels[row["reply_message_id"]] = (row["reply_label"], row["reply_detail"])
    decisions = {row["exception_id"]: row["decision"] for row in read_csv(INPUT / "review_decisions.csv")}
    inbox = CsvInbox()
    print(f"follow-up check: {len(invoices)} cases; agent verdicts and reply labels from evals/; "
          f"fixed paragraph (no model); days {DAY4} and {DAY5}")

    matched_cases = matched_threads = matched_replies = 0
    for invoice in invoices:
        assessment, outcome = eval_outcome(invoice, ref, expected[invoice.exception_id])
        state = {"outcome": outcome}
        emails = [{**email, "paragraph": FALLBACK_PARAGRAPH, "paragraph_source": "fixed"}
                  for email in draft_emails(assessment, outcome, {}, ref)]
        decision = decisions.get(invoice.exception_id, "confirm")
        emails = apply_decision(emails, decision, EXPORT_DATE)
        final = final_recommendation(state, decision)
        threads, replies, ap_items, read, problems = open_threads(emails), [], [], set(), []
        for as_of in (DAY4, DAY5):
            for run in (1, 2):  # the second run of the same day must change nothing
                new = [reply for reply in inbox.replies(as_of) if reply.message_id not in read
                       and (reply.vendor_id, reply.invoice_number) == (invoice.vendor_id, invoice.invoice_number)]
                records = []
                for reply in new:
                    read.add(reply.message_id)
                    label, detail = labels.get(reply.message_id, ("unclear", ""))
                    records.append({"message_id": reply.message_id, "received_date": reply.received_date,
                                    "from_email": reply.from_email, "body": reply.body, "problems": [],
                                    "email_id": match_reply(reply, invoice, threads, ref),
                                    "label": label, "detail": detail})
                emails, threads, sent, drafts, items, _ = follow_up(emails, threads, records, as_of, ref)
                if run == 2 and (records or sent or drafts or items):
                    problems.append(f"{as_of}: the second run changed something")
                emails += [{**draft, "paragraph": FALLBACK_PARAGRAPH, "paragraph_source": "fixed",
                            "body": render({**draft, "paragraph": FALLBACK_PARAGRAPH})} for draft in drafts]
                replies += records
                ap_items += items
        thread_issues, matched = followup_problems(emails, threads, replies, threads_by_case.get(invoice.exception_id, []), DAY5)
        problems += thread_issues + ruling_problems(emails, threads, DAY5)
        matched_threads += matched
        matched_replies += sum(1 for reply in replies if reply["email_id"])
        matched_cases += not problems
        status = invoice_status(final, outcome["findings"], threads, ap_items)
        print(f"{'FAIL' if problems else 'PASS'} {invoice.exception_id}  {status}")
        for problem in problems:
            print(f"   ! {problem}")
        for reply in replies:
            detail = f" {reply['detail']}" if reply["detail"] else ""
            print(f"      {reply['message_id']} {reply['received_date']} -> {reply['email_id'] or 'no email'}: "
                  f"{reply['label']}{detail}")
        for email in emails:
            if email.get("follows") or email["sent_on"] not in ("", EXPORT_DATE):
                cc = f" cc {email['cc_id']}" if email.get("cc_id") else ""
                print(f"      {email['sent_on']} {email['template']} to {email['recipient_id']}{cc}, "
                      f"reply by {email['reply_by']}")
        for item in ap_items:
            print(f"      AP: {item}")

    print(f"replies: {matched_replies} of {len(inbox.replies(DAY5))} matched to their threads")
    print(f"threads: {matched_threads} of {sum(len(rows) for rows in threads_by_case.values())} match")
    print(f"{matched_cases} of {len(invoices)} cases match")
    return 0 if matched_cases == len(invoices) else 1


if __name__ == "__main__":
    sys.exit(main())

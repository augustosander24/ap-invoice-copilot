"""Code-only check of the Phase 7 email drafts: no model, no saved run.

It builds every invoice's Outcome as check_rules.py does (agent verdicts from
evals/expected_outcomes.csv), drafts its emails with the fixed paragraph, and compares them
with evals/expected_threads.csv: recipient, role, findings, the day the email opens, and the
follow-up contacts. It also checks that a possible duplicate's drafts are held, that the AP
queue gets no email, that every number in an email is in its facts, and that no vendor email
shows an AP-only fact or another vendor. Prints PASS or FAIL per case, "threads: N of 21
match", and "N of 22 cases match". Exit code 0 when every case matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\check_emails.py
    .venv\\Scripts\\python.exe scripts\\check_emails.py --set heldout_a

--set runs a held-out batch (data/<set>/ and evals/<set>/) instead of the 22-case eval.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import DATA_SETS, data_set, load_invoices, load_reference, read_csv
from ap_copilot.emails import FALLBACK_PARAGRAPH, draft_emails, facts_text, render
from ap_copilot.evidence import numbers_in
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import AP_TEAM, assess

GOING_OUT = ("send", "waiting")  # the statuses of an email that goes out without an AP ruling


def compare(problems: list[str], label: str, got: str, expected: str) -> None:
    """Record a mismatch as "label: got X, expected Y"."""
    if got != expected:
        problems.append(f"{label}: got {got}, expected {expected}")


def eval_outcome(invoice, ref, expected: dict[str, str]):
    """The Assessment and the Outcome as plain data, with the agent verdicts from the eval, as check_rules.py builds them."""
    assessment = assess(invoice, ref)
    requested = {request.kind for request in assessment.agent_requests}
    verdicts = Verdicts(
        duplicate=expected["duplicate_verdict"] == "yes" if "duplicate_check" in requested else None,
        mismatch=expected["mismatch_flag"] == "yes" if "content_check" in requested else None,
    )
    return assessment, outcome_dict(finalize(assessment, ref, verdicts))


def thread_problems(emails: list[dict], rows: list[dict[str, str]]) -> tuple[list[str], int]:
    """Compare the emails that go out with the invoice's thread rows; return the problems and how many rows match."""
    going = {email["recipient_id"]: email for email in emails if email["status"] in GOING_OUT}
    problems, matched = [], 0
    for row in rows:
        label = f"email to {row['recipient_id']}"
        email = going.pop(row["recipient_id"], None)
        if email is None:
            problems.append(f"{label}: got none, expected {row['recipient_role']}")
            continue
        before = len(problems)
        compare(problems, f"{label} role", "vendor" if "vendor" in email["roles"] else email["roles"][0],
                row["recipient_role"])
        compare(problems, f"{label} findings", ";".join(email["findings"]), row["findings"])
        compare(problems, f"{label} opens_on_day", "4" if email["opens_after"] == "confirmation" else "0",
                row["opens_on_day"])
        if row["day4_cc"]:
            compare(problems, f"{label} day4_cc", email["reminder_cc"], row["day4_cc"])
        if row["day5_to"]:
            compare(problems, f"{label} day5_to", email["escalation_to"], row["day5_to"])
        matched += len(problems) == before
    for recipient_id, email in going.items():
        problems.append(f"email to {recipient_id}: got {email['template']}, expected none")
    return problems, matched


def content_problems(email: dict, invoice, ref) -> list[str]:
    """Problems with one email rendered with the fixed paragraph: stray numbers, AP-only facts, other vendors."""
    text = render({**email, "paragraph": FALLBACK_PARAGRAPH})
    allowed = numbers_in(" ".join((facts_text(email), email["reply_by"], email["to_email"])))
    problems = [f"{email['email_id']}: the number {n} is not in its facts" for n in sorted(numbers_in(text) - allowed)]
    if "agent verdict" in text or "duplicate candidate" in text:
        problems.append(f"{email['email_id']}: shows an AP-only fact")
    if "vendor" in email["roles"]:
        others = [value for vendor_id, vendor in ref.vendors.items() if vendor_id != invoice.vendor_id
                  for value in (vendor_id, vendor["vendor_name"]) if value in text]
        if others:
            problems.append(f"{email['email_id']}: names another vendor ({', '.join(others)})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the email drafts with a data set's expected threads.")
    parser.add_argument("--set", choices=DATA_SETS, default="eval", help="the data set (default: the 22-case eval)")
    folders = data_set(parser.parse_args().set)
    ref = load_reference(folders.reference)
    invoices = load_invoices(folders.input / "exception_list.xlsx")
    expected = {row["exception_id"]: row for row in read_csv(folders.evals / "expected_outcomes.csv")}
    threads = {}
    for row in read_csv(folders.evals / "expected_threads.csv"):
        threads.setdefault(row["exception_id"], []).append(row)
    print(f"email check: {len(invoices)} cases; agent verdicts from evals/expected_outcomes.csv; "
          "fixed paragraph (no model)")

    matched_cases = matched_threads = 0
    for invoice in invoices:
        assessment, outcome = eval_outcome(invoice, ref, expected[invoice.exception_id])
        emails = draft_emails(assessment, outcome, {}, ref)
        problems, matched = thread_problems(emails, threads.get(invoice.exception_id, []))
        matched_threads += matched
        if "possible_duplicate" in outcome["findings"]:
            notices = [email for email in emails if email["release_on"] == "duplicate"]
            others = [email for email in emails if email["release_on"] != "duplicate"]
            if not (len(notices) == 1 and notices[0]["template"] == "duplicate_notice"
                    and notices[0]["status"] == "held"
                    and all(email["status"] == "held" and email["release_on"] == "not_duplicate" for email in others)):
                problems.append("a possible duplicate needs every draft held until AP clears it, "
                                "plus one held duplicate notice for AP to confirm")
        elif any(email["status"] == "held" for email in emails):
            problems.append("a draft is held without a possible duplicate")
        for email in emails:
            if email["recipient_id"] == AP_TEAM:
                problems.append(f"{email['email_id']}: an email to the AP queue")
            problems += content_problems(email, invoice, ref)
        matched_cases += not problems

        print(f"{'FAIL' if problems else 'PASS'} {invoice.exception_id}  {';'.join(outcome['findings']) or 'none'}")
        for problem in problems:
            print(f"   ! {problem}")
        for email in emails:
            when = email["release_on"] or email["opens_after"]
            print(f"      -> {email['template']} to {email['recipient_id']} {email['status']}"
                  f"{f' ({when})' if when else ''}: {';'.join(email['findings'])}")

    print(f"threads: {matched_threads} of {sum(len(rows) for rows in threads.values())} match")
    print(f"{matched_cases} of {len(invoices)} cases match")
    return 0 if matched_cases == len(invoices) else 1


if __name__ == "__main__":
    sys.exit(main())

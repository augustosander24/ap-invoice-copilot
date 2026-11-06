"""Eval runner for the Phase 5 rules engine.

Runs rules.assess() and routing.finalize() on every invoice in the exception
list and compares the result with evals/expected_outcomes.csv (agent requests,
path, findings, approval, GL, day-0 recommendation, AP queue, held actions) and
evals/expected_threads.csv (each email sent on day 0 or day 4). No model runs
in Phase 5, so the agent verdicts come from the eval file. Prints PASS or FAIL
per case with its fact lines and actions, the agent-request counts, and
"N of 22 cases match". Exit code 0 when every case matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\check_rules.py
    .venv\\Scripts\\python.exe scripts\\check_rules.py --set heldout_a

--set runs a held-out batch (data/<set>/ and evals/<set>/) instead of the 22-case eval.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import DATA_SETS, data_set, load_invoices, load_reference, read_csv
from ap_copilot.routing import Verdicts, finalize
from ap_copilot.rules import AP_QUEUE_FINDINGS, assess

# Each agent request kind, the eval column that is filled exactly when it is requested, and its printed label.
REQUESTS = (("duplicate_check", "duplicate_verdict", "duplicate check"),
            ("po_match", "po_match", "PO match"),
            ("content_check", "mismatch_flag", "content check"),
            ("category_suggestion", "category_suggestion", "category suggestion"))


def compare(problems: list[str], label: str, got: str, expected: str) -> None:
    """Record a mismatch as "label: got X, expected Y"."""
    if got != expected:
        problems.append(f"{label}: got {got}, expected {expected}")


def check_case(invoice, ref, expected: dict[str, str], threads: list[dict[str, str]]):
    """Run one invoice through assess() and finalize(); return the Outcome, the requested kinds, and the mismatches."""
    problems = []
    assessment = assess(invoice, ref)
    requested = {request.kind for request in assessment.agent_requests}
    for kind, column, label in REQUESTS:
        compare(problems, f"{label} request", "yes" if kind in requested else "no",
                "yes" if expected[column] else "no")

    verdicts = Verdicts(
        duplicate=expected["duplicate_verdict"] == "yes" if "duplicate_check" in requested else None,
        mismatch=expected["mismatch_flag"] == "yes" if "content_check" in requested else None,
    )
    outcome = finalize(assessment, ref, verdicts)

    for label, got, want in (("path", outcome.path, expected["path"]),
                             ("findings", ";".join(outcome.findings) or "none", expected["findings"]),
                             ("approval_reason", outcome.approval_reason, expected["approval_reason"]),
                             ("approver_id", outcome.approver_id, expected["approver_id"]),
                             ("gl_account", outcome.gl_account, expected["gl_account"]),
                             ("day0_recommendation", outcome.recommendation, expected["day0_recommendation"])):
        compare(problems, label, got, want)

    rows = {row["recipient_id"]: row for row in threads}
    for action in outcome.actions:
        if action.status != "send":
            continue
        email = f"email to {action.recipient_id}"
        row = rows.pop(action.recipient_id, None)
        if row is None:
            problems.append(f"{email}: got {action.role} {';'.join(action.findings)}, expected none")
            continue
        compare(problems, f"{email} role", action.role, row["recipient_role"])
        compare(problems, f"{email} findings", ";".join(action.findings), row["findings"])
        compare(problems, f"{email} opens_on_day", "4" if action.after == "confirmation" else "0",
                row["opens_on_day"])
        if row["day4_cc"]:
            compare(problems, f"{email} day4_cc", action.reminder_cc, row["day4_cc"])
        if row["day5_to"]:
            compare(problems, f"{email} day5_to", action.escalation_to, row["day5_to"])
    for recipient_id, row in rows.items():
        problems.append(f"email to {recipient_id}: got none, expected {row['recipient_role']} {row['findings']}")

    queue = [action for action in outcome.actions if action.role == "ap_queue"]
    compare(problems, "ap_queue", ";".join(queue[0].findings) if queue else "none",
            ";".join(f for f in expected["findings"].split(";") if f in AP_QUEUE_FINDINGS) or "none")

    hold = "possible_duplicate" in outcome.findings
    for action in outcome.actions:
        if action.role != "ap_queue":
            compare(problems, f"{action.role} {action.recipient_id} status", action.status,
                    "held" if hold else "send")
    return outcome, requested, problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare the rules engine with a data set's expected outcomes.")
    parser.add_argument("--set", choices=DATA_SETS, default="eval", help="the data set (default: the 22-case eval)")
    folders = data_set(parser.parse_args().set)
    ref = load_reference(folders.reference)
    invoices = load_invoices(folders.input / "exception_list.xlsx")
    expected = {row["exception_id"]: row for row in read_csv(folders.evals / "expected_outcomes.csv")}
    threads = {}
    for row in read_csv(folders.evals / "expected_threads.csv"):
        threads.setdefault(row["exception_id"], []).append(row)
    source = "evals" if folders.name == "eval" else f"evals/{folders.name}"
    print(f"rules check: {len(invoices)} cases; agent verdicts from {source}/expected_outcomes.csv (no model in Phase 5)")

    requested_by_kind = {kind: [] for kind, _, _ in REQUESTS}
    matched = 0
    for invoice in invoices:
        outcome, requested, problems = check_case(invoice, ref, expected[invoice.exception_id],
                                                  threads.get(invoice.exception_id, []))
        for kind in requested:
            requested_by_kind[kind].append(invoice.exception_id)
        matched += not problems
        print(f"{'FAIL' if problems else 'PASS'} {outcome.exception_id}  {outcome.path:<7} "
              f"{';'.join(outcome.findings) or 'none'}")
        for problem in problems:
            print(f"   ! {problem}")
        for fact in outcome.facts:
            print(f"      {fact}")
        for action in outcome.actions:
            after = " after confirmation" if action.after == "confirmation" else ""
            print(f"      -> {action.role} {action.recipient_id} {action.status}: {';'.join(action.findings)}{after}")

    print("agent requests")
    for kind, _, label in REQUESTS:
        ids = requested_by_kind[kind]
        print(f"  {label} {len(ids)}: {', '.join(ids)}")
    print(f"{matched} of {len(invoices)} cases match")
    return 0 if matched == len(invoices) else 1


if __name__ == "__main__":
    sys.exit(main())

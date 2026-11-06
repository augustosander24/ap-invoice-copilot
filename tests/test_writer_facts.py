"""Tests for the Phase 10 communicator facts (a Phase 7 rollback), with no model: the paragraph gets only what it
needs, each fact named for what it is, and the template shows the rest."""

import json

from ap_copilot.data import load_invoices, load_reference
from ap_copilot.emails import check_paragraph, draft_emails, facts_text, follow_up_email, writer_messages
from ap_copilot.reply_interpreter import interpreter_messages
from ap_copilot.inbox import CsvInbox
from ap_copilot.review import apply_decision
from ap_copilot.followup import open_threads
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import assess

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}
KEYS = ("recipient", "invoice_number", "vendor", "invoice_total", "issues_found", "action_requested")


def emails_of(exception_id: str, **verdicts) -> list[dict]:
    assessment = assess(INVOICES[exception_id], REF)
    return draft_emails(assessment, outcome_dict(finalize(assessment, REF, Verdicts(**verdicts))), {}, REF)


def test_the_paragraph_gets_only_what_it_needs():
    [email] = emails_of("EX-001")
    assert list(email["writer_facts"]) == list(KEYS)
    assert email["writer_facts"]["issues_found"] == ["Price differs from the PO"]
    assert json.loads(writer_messages(email)[1]["content"]) == email["writer_facts"]
    assert "36.25" in facts_text(email) and "36.25" not in writer_messages(email)[1]["content"]  # the template's


def test_an_approval_says_why_in_words():
    [email] = emails_of("EX-013", mismatch=False)[1:]
    assert email["writer_facts"]["why_approval_is_needed"] == (
        "this is bill 3 from a new utility vendor, and the first 3 bills always need approval")
    [confirmation, approval] = emails_of("EX-020", mismatch=False)
    assert "why_confirmation_is_needed" in confirmation["writer_facts"]
    assert approval["writer_facts"]["why_approval_is_needed"].endswith(
        "only after the requester of the service has confirmed it was received")


def test_a_figure_only_the_template_shows_fails_the_fact_check():
    [email] = emails_of("EX-001")
    facts = writer_messages(email)[1]["content"]
    assert check_paragraph("Invoice HIS-40817 from Harbor Industrial Supply for 3315.00 has a price that differs "
                           "from the PO. Please tell us how to proceed.", facts, REF) == []
    assert check_paragraph("The towel price is 36.25 against 34.75 on the PO.", facts, REF) == [
        "the number 34.75 is not in the facts", "the number 36.25 is not in the facts"]


def test_a_follow_up_names_what_it_is_and_no_dates():
    emails = apply_decision(emails_of("EX-012", mismatch=False), "confirm", "2026-11-30")
    [thread] = open_threads(emails)
    reminder = follow_up_email(emails[0], "reminder", thread, "2026-12-04", REF)
    writer = reminder["writer_facts"]
    assert writer["this_email_is"].startswith("a reminder") and writer["copied_to"] == "Laura Mendes (your manager)"
    assert "2026-" not in json.dumps(writer)
    escalation = follow_up_email(emails[0], "escalation", {**thread, "reminded_on": "2026-12-04"}, "2026-12-07", REF)
    assert escalation["writer_facts"]["our_earlier_email_went_to"] == "Kevin Doyle (approver)"


def test_the_interpreter_request_is_unchanged():
    emails = apply_decision(emails_of("EX-001"), "confirm", "2026-11-30")
    reply = next(reply for reply in CsvInbox().replies("2026-12-07") if reply.message_id == "M-01")
    our_email = json.loads(interpreter_messages(reply, emails[0], REF)[1]["content"])["our_email"]
    assert our_email == {"to": "Sofia Ramos (buyer)", "subject": emails[0]["subject"],
                         "action_requested": emails[0]["facts"]["action_requested"]}

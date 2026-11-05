"""Tests for the Phase 9 follow-up: the inbox, the reply check, reminders, escalations, and edits.

Like tests/test_emails.py, these use the real data files with no model: the eval's verdicts stand
in for the investigators (or no investigator runs, as on EX-016), and scripted stand-ins answer for
the reply interpreter and the communicator, so every run gives the same result.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ap_copilot.data import load_invoices, load_reference
from ap_copilot.emails import FALLBACK_PARAGRAPH, draft_emails, facts_text, writer_messages
from ap_copilot.followup import follow_up, invoice_status, match_reply, open_threads
from ap_copilot.graph import as_of_problems, build_graph
from ap_copilot.inbox import CsvInbox
from ap_copilot.replay import CallReplay, ReplayMismatch
from ap_copilot.reply_interpreter import interpret
from ap_copilot.review import DecisionLog, apply_decision, apply_edits, decision_problems
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import assess

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}
INBOX = {reply.message_id: reply for reply in CsvInbox().replies("2026-12-31")}
DAY4, DAY5 = "2026-12-04", "2026-12-07"


class Answer:
    """Stands in for one single-request model: the same JSON answer, or text, every time."""

    model = "scripted"

    def __init__(self, content):
        self.content = content if isinstance(content, str) else json.dumps(content)
        self.calls = 0

    def chat(self, messages, tools=None, schema=None) -> dict:
        self.calls += 1
        return {"message": {"role": "assistant", "content": self.content}, "seconds": 0.0, "prompt_tokens": 0,
                "output_tokens": 0}


class Labels:
    """Stands in for the reply interpreter: a scripted answer per reply text."""

    model = "scripted"

    def __init__(self, answers: dict[str, dict]):
        self.answers = {INBOX[message_id].body: answer for message_id, answer in answers.items()}

    def chat(self, messages, tools=None, schema=None) -> dict:
        answer = {"date": "", "person": "", "reason": "Scripted for the test.",
                  **self.answers[json.loads(messages[1]["content"])["reply"]["text"]]}
        return {"message": {"role": "assistant", "content": json.dumps(answer)}, "seconds": 0.0, "prompt_tokens": 0,
                "output_tokens": 0}


def sent_emails(exception_id: str, decision: str = "confirm", **verdicts):
    """The emails after the review, with the fixed paragraph, and their threads."""
    assessment = assess(INVOICES[exception_id], REF)
    outcome = outcome_dict(finalize(assessment, REF, Verdicts(**verdicts)))
    emails = [{**email, "paragraph": FALLBACK_PARAGRAPH} for email in draft_emails(assessment, outcome, {}, REF)]
    emails = apply_decision(emails, decision, "2026-11-30")
    return outcome, emails, open_threads(emails)


def record(message_id: str, threads: list[dict], label: str, detail: str = "") -> dict:
    """An interpreted reply, matched to its thread."""
    reply = INBOX[message_id]
    invoice = next(i for i in INVOICES.values() if (i.vendor_id, i.invoice_number) == (reply.vendor_id,
                                                                                         reply.invoice_number))
    return {"message_id": message_id, "received_date": reply.received_date, "from_email": reply.from_email,
            "body": reply.body, "email_id": match_reply(reply, invoice, threads, REF), "label": label,
            "detail": detail, "problems": []}


def test_inbox_reads_only_replies_up_to_the_as_of_date():
    assert [reply.message_id for reply in CsvInbox().replies(DAY4)][-3:] == ["M-14", "M-15", "M-16"]
    assert len(CsvInbox().replies(DAY4)) == 16 and len(CsvInbox().replies(DAY5)) == 18
    assert CsvInbox().replies("2026-11-30") == []


def test_a_reply_matches_the_email_its_sender_was_sent():
    _, _, threads = sent_emails("EX-019", mismatch=False)
    invoice = INVOICES["EX-019"]
    assert match_reply(INBOX["M-06"], invoice, threads, REF) == "EX-019:P-102:service_confirmation"
    assert match_reply(INBOX["M-18"], invoice, threads, REF) == ""  # the approval waits: nothing sent to P-101 yet
    assert match_reply(INBOX["M-05"], invoice, threads, REF) == ""  # another invoice


def test_the_reply_check_keeps_details_the_reply_supports():
    _, emails, _ = sent_emails("EX-009", duplicate=None)
    vendor = next(email for email in emails if email["recipient_id"] == "V-1004")
    today, _ = interpret(INBOX["M-03"], vendor, Answer({"label": "correction_coming", "date": "2026-12-01",
                                                        "person": "", "reason": "A corrected invoice follows today."}), REF)
    assert (today["label"], today["detail"], today["problems"]) == ("correction_coming", "2026-12-01", [])
    _, emails, _ = sent_emails("EX-005")
    redirected, call = interpret(INBOX["M-13"], emails[0], Answer({"label": "redirected", "date": "", "person": "Sofia Ramos",
                                                                    "reason": "Sofia Ramos took over the account."}), REF)
    assert (redirected["label"], redirected["detail"]) == ("redirected", "P-106")
    assert json.loads(call["prompt"])["our_email"]["to"] == "Tom Keller (buyer)"


def test_a_detail_the_reply_does_not_support_makes_it_unclear():
    _, emails, _ = sent_emails("EX-007")
    for answer, problem in (({"date": "2026-12-05"}, "the date 2026-12-05 is not in the reply"),
                            ({"date": "2026-11-30"}, "the date 2026-11-30 is before the reply was received (2026-12-01)"),
                            ({"date": "Dec 2"}, "the date 'Dec 2' is not YYYY-MM-DD")):
        result, _ = interpret(INBOX["M-02"], emails[0], Answer({"label": "correction_coming", "person": "",
                                                                "reason": "x", **answer}), REF)
        assert (result["model_label"], result["label"], result["problems"]) == ("correction_coming", "unclear", [problem])
    _, emails, _ = sent_emails("EX-005")
    for person, problem in (("Laura Gomez", "'Laura Gomez' is not one person on file"),
                            ("Tom Keller", "Tom Keller is not named in the reply")):
        result, _ = interpret(INBOX["M-13"], emails[0], Answer({"label": "redirected", "date": "", "person": person,
                                                                "reason": "x"}), REF)
        assert (result["label"], result["problems"]) == ("unclear", [problem])
    result, _ = interpret(INBOX["M-13"], emails[0], Answer("not JSON"), REF)
    assert result["label"] == "unclear" and result["problems"][0].startswith("the answer is not valid JSON")


def test_no_reply_brings_a_reminder_on_day_4_and_an_escalation_on_day_5():
    _, emails, threads = sent_emails("EX-012", mismatch=False)
    emails, threads, _, [reminder], _, _ = follow_up(emails, threads, [], DAY4, REF)
    assert (reminder["template"], reminder["recipient_id"], reminder["cc_id"], reminder["reply_by"]) == (
        "reminder", "P-109", "P-108", DAY5)
    assert reminder["facts"]["reply_was_due_on"] == "2026-12-03" and DAY5 not in facts_text(reminder)  # template-only
    assert writer_messages(reminder)[0]["content"].startswith(
        "You write one short paragraph (2 to 4 sentences) for an accounts payable email to the approver (reminder, "
        "their manager in copy).")
    _, threads, _, none, _, _ = follow_up(emails, threads, [], DAY4, REF)  # the same day again: nothing new
    assert none == []
    _, threads, _, [escalation], _, _ = follow_up(emails, threads, [], DAY5, REF)
    assert (escalation["recipient_id"], escalation["cc_id"], threads[0]["owner_id"]) == ("P-108", "P-109", "P-108")
    assert "Escalation: we sent this request to Kevin Doyle (approver) on 2026-11-30" in escalation["body"]


def test_a_vendor_reminder_copies_ap_team_and_escalates_to_the_ap_manager():
    _, emails, threads = sent_emails("EX-013", mismatch=False)
    approved = record("M-10", threads, "approved")
    emails, threads, _, [reminder], _, _ = follow_up(emails, threads, [approved], DAY4, REF)
    assert (reminder["recipient_id"], reminder["cc_id"]) == ("V-2003", "P-104")
    assert "Cc: AP Team <ap@northgate.example>" in reminder["body"]
    _, _, _, [escalation], _, _ = follow_up(emails, threads, [], DAY5, REF)
    assert (escalation["recipient_id"], escalation["cc_id"]) == ("P-103", "")
    assert escalation["facts"]["action_requested"] == [
        "Ask GreenCycle Waste Services to send a corrected invoice with the missing or incorrect details fixed."]


def test_any_reply_stops_the_clock():
    outcome, emails, threads = sent_emails("EX-014", mismatch=False)
    _, threads, _, drafts, items, steps = follow_up(emails, threads, [record("M-16", threads, "rejected")], DAY4, REF)
    assert drafts == [] and threads[0]["status"] == "closed"
    assert steps == {"M-16": "closed: rejected; AP acts on it"} and items[0].startswith("Laura Mendes says not to pay")
    assert invoice_status("hold", outcome["findings"], threads, items) == "with_ap"


def test_a_confirmation_sends_the_waiting_approval():
    _, emails, threads = sent_emails("EX-020", mismatch=False)
    waiting = emails[1]
    emails, threads, [approval], _, _, _ = follow_up(emails, threads, [record("M-12", threads, "approved")], DAY4, REF)
    assert (approval["status"], approval["sent_on"], approval["reply_by"]) == ("sent", DAY4, "2026-12-09")
    assert approval["paragraph"] == waiting["paragraph"] and "Reply by: 2026-12-09" in approval["body"]
    assert threads[1]["status"] == "open"
    _, emails, threads = sent_emails("EX-020", mismatch=False)
    emails, threads, sent, _, _, _ = follow_up(emails, threads, [record("M-12", threads, "rejected")], DAY4, REF)
    assert sent == [] and emails[1]["status"] == "cancelled" and threads[1]["status"] == "cancelled"


def test_with_no_manager_the_reminder_has_no_cc_and_ap_follows_up():
    _, emails, threads = sent_emails("EX-019", mismatch=False)
    emails, threads, _, _, _, _ = follow_up(emails, threads, [record("M-06", threads, "approved")], DAY4, REF)
    emails, threads, _, [reminder], _, _ = follow_up(emails, threads, [], "2026-12-10", REF)
    assert (reminder["recipient_id"], reminder["cc_id"], reminder["writer_recipient"]) == ("P-101", "", "approver (reminder)")
    assert "Cc:" not in reminder["body"]
    _, threads, _, drafts, [item], _ = follow_up(emails, threads, [], "2026-12-11", REF)
    assert drafts == [] and item.endswith("and no manager to escalate to: AP follows up")


def test_a_question_a_redirect_or_an_unclear_reply_goes_to_ap():
    for exception_id, message_id, label, detail, item in (
            ("EX-017", "M-11", "question", "", "Daniel Ortiz asks a question"),
            ("EX-005", "M-13", "redirected", "P-106", "Tom Keller says Sofia Ramos (P-106) is responsible"),
            ("EX-018", "M-15", "unclear", "", "unclear reply from Priya Nair")):
        _, emails, threads = sent_emails(exception_id, **({} if exception_id == "EX-005" else {"mismatch": False}))
        emails, threads, _, _, [found], _ = follow_up(emails, threads, [record(message_id, threads, label, detail)],
                                                      DAY4, REF)
        assert found.startswith(item) and threads[0]["status"] == "with_ap", exception_id
        _, _, _, drafts, _, _ = follow_up(emails, threads, [], DAY5, REF)
        assert drafts == [], exception_id  # no reminder: the reply stopped the clock
        if exception_id == "EX-017":  # a later reply on the same thread still counts
            later = {**record("M-11", threads, "approved"), "message_id": "M-99"}
            _, closed, _, _, _, steps = follow_up(emails, threads, [later], DAY5, REF)
            assert steps == {"M-99": "closed: approved"} and closed[0]["status"] == "closed"


def test_each_invoice_status():
    outcome, _, threads = sent_emails("EX-016", mismatch=None)
    closed = [{**threads[0], "status": "closed", "outcome": "approved"}]
    assert invoice_status("hold", outcome["findings"], closed, []) == "ready_to_release"
    assert invoice_status("hold", outcome["findings"], [{**closed[0], "outcome": "correction_coming"}], []) == \
        "awaiting_correction"
    assert invoice_status("hold", outcome["findings"], threads, []) == "open"
    assert invoice_status("release", [], [], []) == "released"
    assert invoice_status("hold", ["no_category"], [], []) == "with_ap"
    _, _, notice = sent_emails("EX-010")
    assert invoice_status("hold", ["exact_duplicate"], [{**notice[0], "status": "closed", "outcome": "approved"}],
                          []) == "void"


class NoReplies:
    """Stands in for the inbox: nobody replies."""

    def replies(self, as_of: str) -> list:
        return []


def test_the_graph_waits_between_days_and_logs_each_day_once(tmp_path):
    writer = Answer("We have had no reply about invoice MCT-2026-H2 from Marlow County Treasurer.")
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    graph = build_graph(REF, INVOICES, Answer(""), writer=writer, checkpointer=InMemorySaver(), log=log,
                        interpreter=Labels({}), inbox=NoReplies())
    config = {"configurable": {"thread_id": "EX-016"}}  # taxes: no investigator task
    graph.invoke({"exception_id": "EX-016"}, config)
    graph.invoke(Command(resume={"decision": "confirm"}), config)
    assert graph.get_state(config).next == ("wait",)
    state = graph.invoke(Command(resume={"as_of": DAY4}), config)
    assert [(email["template"], email.get("cc_id", "")) for email in state["emails"]] == [
        ("approval_request", ""), ("reminder", "P-101")]
    graph.invoke(Command(resume={"as_of": DAY4}), config)  # the same day again: asked again, nothing runs
    snapshot = graph.get_state(config)
    assert snapshot.tasks[0].interrupts[-1].value["problems"] == ["as_of must be after the last run (2026-12-04)"]
    calls = writer.calls
    state = graph.invoke(Command(resume={"as_of": DAY5}), config)
    assert (state["emails"][-1]["template"], state["emails"][-1]["recipient_id"]) == ("escalation", "P-101")
    assert writer.calls == calls + 1 and state["invoice_status"] == "open"
    assert [entry["entry_id"] for entry in log.entries()] == [
        "EX-016:2026-11-30:review", "EX-016:2026-12-04:follow_up", "EX-016:2026-12-07:follow_up"]
    assert as_of_problems({"as_of": DAY4}, {"as_of": "2026-12-05"}) == ["2026-12-05 is not a business day"]


def test_a_reply_is_interpreted_logged_and_closes_the_invoice(tmp_path):
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    graph = build_graph(REF, INVOICES, Answer(""), writer=Answer("Invoice MCT-2026-H2 needs your approval."),
                        checkpointer=InMemorySaver(), log=log, interpreter=Labels({"M-05": {"label": "approved"}}),
                        inbox=CsvInbox())
    config = {"configurable": {"thread_id": "EX-016"}}
    graph.invoke({"exception_id": "EX-016"}, config)
    graph.invoke(Command(resume={"decision": "confirm"}), config)
    state = graph.invoke(Command(resume={"as_of": DAY4}), config)
    assert [(reply["message_id"], reply["label"], reply["next_step"]) for reply in state["replies"]] == [
        ("M-05", "approved", "closed: approved")]
    assert (state["invoice_status"], graph.get_state(config).next) == ("ready_to_release", ())
    assert [entry["entry_id"] for entry in log.entries()][1:] == ["EX-016:M-05:reply", "EX-016:2026-12-04:follow_up"]


def test_an_override_leaves_no_thread_to_follow_up(tmp_path):
    graph = build_graph(REF, INVOICES, Answer(""), writer=Answer("Invoice MCT-2026-H2 needs your approval."),
                        checkpointer=InMemorySaver(), log=DecisionLog(tmp_path / "decision_log.jsonl"),
                        interpreter=Labels({}), inbox=CsvInbox())
    config = {"configurable": {"thread_id": "EX-016"}}
    graph.invoke({"exception_id": "EX-016"}, config)
    state = graph.invoke(Command(resume={"decision": "override", "reason": "Paid by the county portal"}), config)
    assert (state["threads"], state["invoice_status"], graph.get_state(config).next) == ([], "with_ap", ())


def test_the_operator_edits_a_paragraph_and_an_explanation():
    assessment = assess(INVOICES["EX-013"], REF)
    outcome = outcome_dict(finalize(assessment, REF, Verdicts(mismatch=False)))
    accepted = {"bill_change_explanation": {"explanation": "Bill 3 (bill_count: 2 in history) is in line.",
                                            "evidence": ["bill_history:V-2003"]}}
    emails = [{**email, "paragraph": "Old.", "paragraph_source": "model"}
              for email in draft_emails(assessment, outcome, accepted, REF)]
    state = {"outcome": outcome, "emails": emails}
    approval = "EX-013:P-108:approval_request"
    good = [{"email_id": approval, "part": "explanation", "issue": "1",
             "text": "This is the third bill from this vendor, so it needs approval."},
            {"email_id": approval, "part": "paragraph", "issue": "", "text": "Please approve or reject invoice GCW-0043."}]
    assert decision_problems(state, {"decision": "confirm", "edits": good}, REF) == []
    [_, edited] = apply_edits(emails, good)
    assert edited["paragraph_source"] == "operator" and "bill_count" not in edited["body"]
    assert "From our review: This is the third bill from this vendor, so it needs approval." in edited["body"]
    assert [edit["before"] for edit in edited["edits"]] == ["Bill 3 (bill_count: 2 in history) is in line.", "Old."]
    bad = [{"email_id": approval, "part": "paragraph", "issue": "", "text": "Please pay 999.99 now."},
           {"email_id": "EX-013:V-2003:vendor_correction", "part": "explanation", "issue": "1", "text": "x"}]
    assert decision_problems(state, {"decision": "confirm", "edits": bad}, REF) == [
        "edit of EX-013:P-108:approval_request paragraph: the number 999.99 is not in the facts",
        "edit of EX-013:V-2003:vendor_correction: issue 1 has no explanation to edit"]
    assert decision_problems(state, {"decision": "override", "reason": "x", "edits": good}, REF) == [
        "an override cancels every draft, so there is nothing to edit"]


def test_call_replay_returns_saved_replies_and_detects_a_changed_request():
    replay = CallReplay([{"prompt": "facts", "reply": "Saved paragraph.", "seconds": 1.0, "prompt_tokens": 1,
                          "output_tokens": 1}], "llama3.1:8b", "a saved run")
    assert replay.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "facts"}])["message"][
        "content"] == "Saved paragraph."
    with pytest.raises(ReplayMismatch, match="a saved run"):
        replay.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "other facts"}])

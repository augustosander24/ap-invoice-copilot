"""Tests for the Phase 7 emails, review pause, and decision log, with no model.

Like tests/test_po_agent.py, these use the real data files. The investigator replays
tests/po_agent_scripts.json, and a scripted writer stands in for the communicator, so the
drafts, the fact check, the pause, the AP ruling, and the log run the same way every time.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from ap_copilot.data import load_invoices, load_reference
from ap_copilot.emails import (FALLBACK_PARAGRAPH, add_business_days, check_paragraph, draft_emails, facts_text,
                               readable, write_paragraph)
from ap_copilot.graph import build_graph
from ap_copilot.replay import ReplayClient, ReplayMismatch
from ap_copilot.review import DecisionLog
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import FINDINGS, assess

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}
SCRIPTS = json.loads(Path(__file__).with_name("po_agent_scripts.json").read_text(encoding="utf-8"))


def turns(steps: list[dict]) -> list[dict]:
    """The model turns for a script, as in test_po_agent.py: one per tool step; DONE, then the answer, per answer step."""
    result = []
    for step in steps:
        if "tool" in step:
            result.append({"role": "assistant", "content": "",
                           "tool_calls": [{"function": {"name": step["tool"], "arguments": step["args"]}}]})
        else:
            result += [{"role": "assistant", "content": "DONE"},
                       {"role": "assistant", "content": json.dumps(step["answer"])}]
    return result


class Scripted:
    """Stands in for the investigator model: returns the scripted replies in order."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)

    def chat(self, messages, tools=None, schema=None) -> dict:
        return {"message": deepcopy(self.replies.pop(0)), "seconds": 0.0, "prompt_tokens": 0, "output_tokens": 0}


class Writer:
    """Stands in for the communicator: the given text, or a sentence built only from the facts."""

    model = "scripted writer"

    def __init__(self, text: str = ""):
        self.text = text

    def chat(self, messages, tools=None, schema=None) -> dict:
        facts = json.loads(messages[1]["content"])
        content = self.text or f"Invoice {facts['invoice_number']} from {facts['vendor']} needs your action."
        return {"message": {"role": "assistant", "content": content}, "seconds": 0.0, "prompt_tokens": 0,
                "output_tokens": 0}


def outcome_of(exception_id: str, **verdicts):
    """The Assessment and the Outcome as plain data, with the given agent verdicts."""
    assessment = assess(INVOICES[exception_id], REF)
    return assessment, outcome_dict(finalize(assessment, REF, Verdicts(**verdicts)))


def graph_for(exception_id: str, tmp_path: Path, checkpointer=None, writer=None):
    """The full graph for one case, its thread config, and a DecisionLog in tmp_path."""
    client = Scripted(turns(SCRIPTS.get(exception_id, [])))
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    graph = build_graph(REF, INVOICES, client, writer=Writer() if writer is None else writer,
                        checkpointer=InMemorySaver() if checkpointer is None else checkpointer, log=log)
    return graph, {"configurable": {"thread_id": exception_id}}, log


def test_every_fact_line_names_its_findings():
    for exception_id, invoice in INVOICES.items():
        assessment = assess(invoice, REF)
        assert assessment.facts == tuple(fact.text for fact in assessment.fact_records), exception_id
        assert all(fact.findings and set(fact.findings) <= set(FINDINGS) for fact in assessment.fact_records), exception_id


def test_each_email_shows_only_its_own_facts():
    buyer, vendor = draft_emails(*outcome_of("EX-009"), {}, REF)
    assert "total price variance 150.00 in dollars: over the tolerance limit 60.20" in buyer["body"]
    assert "header amount" not in buyer["body"]
    assert "header amount 3010.00 does not equal the lines total 3100.00" in vendor["body"]
    assert "tolerance" not in vendor["body"]


def test_vendor_email_hides_internal_facts():
    [email] = draft_emails(*outcome_of("EX-003"), {}, REF)
    assert "PO-26108 was not issued to Harbor Industrial Supply" in email["body"]
    assert "V-1004" not in email["body"] and "Pioneer" not in email["body"]


def test_accepted_answers_reach_the_emails():
    [email] = draft_emails(*outcome_of("EX-006", duplicate=False), SCRIPTS["EX-006"][-1]["answer"], REF)
    assert "Our open purchase order PO-26106 includes the item(s) on this invoice (PKG-1210)" in email["body"]
    assert (readable("price on po_line:PO-26101:2 (evidence_id invoice_line:EX-001:2) vs receipts:PO-26103")
            == "price on PO-26101 line 2 vs the PO-26103 receipts")


def test_possible_duplicate_drafts_are_held_with_a_notice():
    emails = draft_emails(*outcome_of("EX-008", duplicate=True), {}, REF)
    assert [(e["template"], e["status"], e["release_on"]) for e in emails] == [
        ("vendor_correction", "held", "not_duplicate"), ("duplicate_notice", "held", "duplicate")]
    assert not any("agent verdict" in e["body"] for e in emails)
    assert "matches invoice 008817 dated 2026-08-24 for 5352.00" in emails[1]["body"]


def test_approval_after_a_confirmation_waits():
    confirmation, approval = draft_emails(*outcome_of("EX-020", mismatch=False), {}, REF)
    assert (confirmation["status"], confirmation["reply_by"]) == ("send", "2026-12-03")
    assert (approval["status"], approval["opens_after"], approval["reply_by"]) == ("waiting", "confirmation", "")


def test_one_person_with_two_roles_gets_one_email():
    assessment, outcome = outcome_of("EX-001")
    outcome["actions"].append({**outcome["actions"][0], "role": "approver", "findings": ["approval_required"]})
    [email] = draft_emails(assessment, outcome, {}, REF)
    assert email["roles"] == ["buyer", "approver"]
    assert email["findings"] == ["price_variance", "approval_required"]


def test_email_figures_are_labeled():
    [email] = draft_emails(*outcome_of("EX-001"), {}, REF)
    assert ("line 2 IND-2415: invoice unit price 36.25, PO unit price 34.75, a difference of 1.50 per unit on 60 "
            "units billed: price variance 90.00 in dollars") in email["body"]
    assert "line 1: IND-2210 Nitrile work gloves box of 100: 40 units at 28.50 each, line amount 1140.00" in email["body"]
    notice = draft_emails(*outcome_of("EX-008", duplicate=True), {}, REF)[1]
    assert ("the same invoice number once leading zeros and punctuation are dropped (8817 and 008817)"
            in notice["body"])
    assert "line 2 IND-2415: price 36.25 vs PO 34.75 x 60 = 90.00" in assess(INVOICES["EX-001"], REF).facts


def test_business_days_skip_the_weekend():
    assert add_business_days("2026-11-30", 3) == "2026-12-03"
    assert add_business_days("2026-12-04", 1) == "2026-12-07"


def test_fact_check_rejects_invented_numbers_and_names():
    facts = facts_text(draft_emails(*outcome_of("EX-001"), {}, REF)[0])
    paragraph = ("Invoice HIS-40817 bills the towels at 36.25, not the PO price of 34.75. The 90.00 difference "
                 "is over the limit of 66.30, so please reply by Thursday")
    assert check_paragraph(paragraph + ", December 3.", facts, REF) == ["the number 3 is not in the facts"]
    assert check_paragraph(paragraph + ".", facts, REF) == []
    assert check_paragraph("The towels cost 2.75 more.", facts, REF) == ["the number 2.75 is not in the facts"]
    assert "the name Tom Keller is not in the facts" in check_paragraph("Tom Keller handles this.", facts, REF)
    assert check_paragraph("Please ask Bob Smith.", facts, REF) == ["the name Bob is not in the facts",
                                                                    "the name Smith is not in the facts"]
    assert "PO-26199 is not in the facts" in check_paragraph("It may be PO-26199.", facts, REF)


def test_rejected_paragraph_becomes_the_fixed_sentence():
    email = draft_emails(*outcome_of("EX-001"), {}, REF)[0]
    written, call = write_paragraph(email, Writer("The difference comes to 999.99 in total."), REF)
    assert (written["paragraph"], written["paragraph_source"]) == (FALLBACK_PARAGRAPH, "fallback")
    assert call["problems"] == ["the number 999.99 is not in the facts"]
    assert FALLBACK_PARAGRAPH in written["body"]


def test_review_pauses_then_confirm_sends(tmp_path):
    graph, config, log = graph_for("EX-001", tmp_path)
    state = graph.invoke({"exception_id": "EX-001", "as_of": "2026-11-30"}, config)
    assert "__interrupt__" in state
    assert graph.get_state(config).next == ("review",)
    assert [email["status"] for email in state["emails"]] == ["send"]
    assert log.entries() == []
    state = graph.invoke(Command(resume={"decision": "confirm"}), config)
    [email] = state["emails"]
    assert (email["status"], email["sent_on"]) == ("sent", "2026-11-30")
    assert [entry["entry_id"] for entry in log.entries()] == ["EX-001:2026-11-30:review"]


def test_bad_decision_is_asked_again(tmp_path):
    graph, config, log = graph_for("EX-002", tmp_path)
    graph.invoke({"exception_id": "EX-002"}, config)
    graph.invoke(Command(resume={"decision": "override"}), config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("review",)
    assert snapshot.tasks[0].interrupts[-1].value["problems"] == ["override needs a reason"]
    state = graph.invoke(Command(resume={"decision": "override", "reason": "Buyer approved the price by phone"}),
                         config)
    assert state["final_recommendation"] == "release"
    assert [email["status"] for email in state["emails"]] == ["cancelled"]
    assert len(log.entries()) == 1


def test_ap_ruling_releases_or_replaces_the_held_drafts(tmp_path):
    for ruling, statuses in (("duplicate", ["cancelled", "sent"]), ("not_duplicate", ["sent", "cancelled"])):
        graph, config, _ = graph_for("EX-008", tmp_path / ruling)
        graph.invoke({"exception_id": "EX-008"}, config)
        state = graph.invoke(Command(resume={"decision": ruling, "reason": "AP compared it with posted 008817"}),
                             config)
        assert [email["status"] for email in state["emails"]] == statuses, ruling


def test_resume_in_a_new_process_without_a_model(tmp_path):
    path = tmp_path / "checkpoints.sqlite"
    first = sqlite3.connect(path, check_same_thread=False)
    graph, config, _ = graph_for("EX-010", tmp_path, checkpointer=SqliteSaver(first))
    graph.invoke({"exception_id": "EX-010"}, config)
    first.close()

    class NoModel:
        def chat(self, *args, **kwargs):
            raise AssertionError("no model may be called on resume")

    second = sqlite3.connect(path, check_same_thread=False)
    try:
        graph = build_graph(REF, INVOICES, NoModel(), writer=NoModel(), checkpointer=SqliteSaver(second),
                            log=DecisionLog(tmp_path / "decision_log.jsonl"))
        state = graph.invoke(Command(resume={"decision": "confirm"}), config)
        assert state["status"] == "reviewed"
        assert graph.get_state(config).next == ()
    finally:
        second.close()


def test_log_entry_is_written_once(tmp_path):
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    entry = {"entry_id": "EX-001:2026-11-30:review", "decision": "confirm"}
    assert log.write(entry) is True
    assert log.write(entry) is False
    assert log.entries() == [entry]


def test_replay_reuses_a_saved_run_and_detects_a_changed_prompt():
    state = build_graph(REF, INVOICES, Scripted(turns(SCRIPTS["EX-004"]))).invoke({"exception_id": "EX-004"})
    case = {"exception_id": "EX-004", "transcript": state["transcript"], "model_calls": state["model_calls"]}
    replayed = build_graph(REF, INVOICES, ReplayClient(case, "scripted")).invoke({"exception_id": "EX-004"})
    assert (replayed["accepted"], replayed["outcome"]) == (state["accepted"], state["outcome"])
    edited = deepcopy(case)
    edited["transcript"][0]["prompt"] += " (edited)"
    with pytest.raises(ReplayMismatch, match="EX-004"):
        build_graph(REF, INVOICES, ReplayClient(edited, "scripted")).invoke({"exception_id": "EX-004"})

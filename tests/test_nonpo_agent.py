"""Tests for the Phase 8 non-PO investigator, its emails, and its review, with a scripted model.

As in tests/test_po_agent.py, these use the real data files. A scripted client stands in for
Ollama: it replays the tool calls and answers in tests/nonpo_agent_scripts.json, or planted bad
ones, so the evidence check, retry, fallback, and review rules run the same way every time.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ap_copilot.data import ROOT, load_invoices, load_reference, read_csv
from ap_copilot.emails import FALLBACK_PARAGRAPH, draft_emails, readable
from ap_copilot.graph import build_graph
from ap_copilot.nonpo_investigator import needs_lookups, nonpo_tasks
from ap_copilot.review import DecisionLog
from ap_copilot.rules import assess
from ap_copilot.tools import NONPO_TOOL_SPECS, evidence_ids, get_bill_history, run_tool

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}
EXPECTED = {row["exception_id"]: row for row in read_csv(ROOT / "evals" / "expected_outcomes.csv")}
SCRIPTS = json.loads(Path(__file__).with_name("nonpo_agent_scripts.json").read_text(encoding="utf-8"))
NON_PO = [exception_id for exception_id, invoice in INVOICES.items()
          for assessment in [assess(invoice, REF)]
          if assessment.path == "non_po" and "exact_duplicate" not in assessment.findings]

DONE = {"role": "assistant", "content": "DONE"}


def tool_turn(name: str, **args) -> dict:
    """An assistant message with one tool call."""
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def answer_turn(answer) -> dict:
    """An assistant message whose content is the JSON answer."""
    return {"role": "assistant", "content": json.dumps(answer)}


def turns(steps: list[dict], lookups: bool = True) -> list[dict]:
    """The model turns for a script: one per tool step; per answer step, DONE (only when the case has tool
    steps), then the answer."""
    result = []
    for step in steps:
        if "tool" in step:
            result.append(tool_turn(step["tool"], **step["args"]))
        else:
            result += ([DONE] if lookups else []) + [answer_turn(step["answer"])]
    return result


def _lookups(exception_id: str) -> bool:
    """Whether the case's investigator runs the tool steps, so each answer comes after a DONE."""
    return needs_lookups(nonpo_tasks(assess(INVOICES[exception_id], REF)))


def script(exception_id: str) -> list[dict]:
    """The case's scripted turns; [] for a case with no script (no agent task)."""
    return turns(SCRIPTS.get(exception_id, []), _lookups(exception_id))


def planted(exception_id: str, task: str, **changes) -> list[dict]:
    """The case's turns with one claim of its last answer changed."""
    steps = deepcopy(SCRIPTS[exception_id])
    steps[-1]["answer"][task].update(changes)
    return turns(steps, _lookups(exception_id))


def good_answer(exception_id: str) -> list[dict]:
    """What a retry replies once it needs no more lookups: DONE (only when the case has tool steps), then
    the scripted answer."""
    return ([DONE] if _lookups(exception_id) else []) + [answer_turn(SCRIPTS[exception_id][-1]["answer"])]


class ScriptedClient:
    """Replays model turns in order; records whether each call was a tool step or the answer, and each request."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.steps = []
        self.requests = []

    def chat(self, messages, tools=None, schema=None) -> dict:
        self.steps.append("answer" if schema is not None else "tools")
        self.requests.append(deepcopy(messages))
        return {"message": deepcopy(self.replies.pop(0)), "seconds": 0.0, "prompt_tokens": 0, "output_tokens": 0}


class Writer:
    """Stands in for the communicator: a sentence built only from the facts."""

    model = "scripted writer"

    def chat(self, messages, tools=None, schema=None) -> dict:
        facts = json.loads(messages[1]["content"])
        return {"message": {"role": "assistant", "content": f"Invoice {facts['invoice_number']} needs your action."},
                "seconds": 0.0, "prompt_tokens": 0, "output_tokens": 0}


def run(exception_id: str, replies: list[dict], invoices=None) -> tuple[dict, ScriptedClient]:
    """The final state of one investigator run (no writer), and the client; every scripted reply must be used."""
    client = ScriptedClient(replies)
    state = build_graph(REF, invoices or INVOICES, client).invoke({"exception_id": exception_id})
    assert client.replies == [], f"{exception_id}: {len(client.replies)} scripted replies not used"
    return state, client


def reviewed(exception_id: str, decision: dict, tmp_path: Path, invoices=None) -> tuple[dict, dict, DecisionLog]:
    """The full graph for one case, run to the review pause and resumed with the decision: the state after the
    review, the packet shown at the pause, and the DecisionLog in tmp_path."""
    log = DecisionLog(tmp_path / "decision_log.jsonl")
    graph = build_graph(REF, invoices or INVOICES, ScriptedClient(script(exception_id)), writer=Writer(),
                        checkpointer=InMemorySaver(), log=log)
    config = {"configurable": {"thread_id": exception_id}}
    paused = graph.invoke({"exception_id": exception_id}, config)
    packet = paused["__interrupt__"][0].value
    return graph.invoke(Command(resume=decision), config), packet, log


def test_bill_history_and_the_non_po_tools():
    history = get_bill_history(REF, "V-2003")
    assert evidence_ids(history) == ["bill_history:V-2003", "posted:V-2003:GCW-0041", "posted:V-2003:GCW-0042"]
    assert history["bill_count"] == "2"
    assert get_bill_history(REF, "V-9999") == {"error": "vendor V-9999 is not on file"}
    assert [spec["function"]["name"] for spec in NONPO_TOOL_SPECS] == ["get_bill_history", "get_vendor"]
    assert run_tool(REF, "get_bill_history", {"vendor_id": "V-2003"}, "non_po") == history
    assert run_tool(REF, "get_bill_history", {"vendor_id": "V-2003"})["error"].startswith(  # not a PO investigator tool
        "unknown tool get_bill_history; use one of: get_purchase_order")
    assert run_tool(REF, "get_purchase_order", {"po_number": "PO-26101"}, "non_po")["error"] == (
        "unknown tool get_purchase_order; use one of: get_bill_history, get_vendor")


def test_nonpo_tasks_come_from_the_assessment():
    assert {exception_id: nonpo_tasks(assess(INVOICES[exception_id], REF)) for exception_id in NON_PO} == {
        "EX-011": ("content_check",),
        "EX-012": ("content_check", "bill_change_explanation"),
        "EX-013": ("content_check", "bill_change_explanation"),
        "EX-014": ("content_check", "rent_difference_explanation"),
        "EX-015": (),
        "EX-016": (),
        "EX-017": ("content_check",),
        "EX-018": ("content_check",),
        "EX-019": ("content_check",),
        "EX-020": ("content_check",),
        "EX-021": (),
        "EX-022": ("category_suggestion",),
    }
    with pytest.raises(ValueError, match="EX-003"):  # a PO match is the PO investigator's job
        nonpo_tasks(assess(INVOICES["EX-003"], REF))


def test_scripted_answers_match_the_eval_on_every_non_po_case():
    for exception_id in NON_PO:
        expected = EXPECTED[exception_id]
        state, _ = run(exception_id, script(exception_id))
        assert all(check["passed"] for check in state["checks"]), exception_id
        assert len(state["checks"]) <= 1, exception_id
        if expected["first_tool"]:
            assert state["tool_calls"][0]["kind"] in expected["first_tool"].split("|"), exception_id
        if expected["mismatch_flag"]:
            verdict = "yes" if state["accepted"]["content_check"]["mismatch"] else "no"
            assert verdict == expected["mismatch_flag"], exception_id
        if expected["category_suggestion"]:
            assert (state["accepted"]["category_suggestion"]["category"]
                    == expected["category_suggestion"]), exception_id
        outcome = state["outcome"]
        assert (";".join(outcome["findings"]) or "none") == expected["findings"], exception_id
        assert (outcome["approver_id"], outcome["gl_account"], outcome["recommendation"]) == (
            expected["approver_id"], expected["gl_account"], expected["day0_recommendation"]), exception_id


def test_a_content_check_alone_skips_the_tool_steps():
    state, client = run("EX-017", script("EX-017"))
    assert client.steps == ["answer"]
    assert state["tool_calls"] == []
    request = client.requests[0][1]["content"]
    assert "Records you looked up:\nnone" in request
    assert ("content_check: decide whether every line of this invoice fits the vendor's category, subscriptions"
            in request)
    state, client = run("EX-015", [])  # no task: no model call
    assert client.steps == []
    assert state["outcome"]["recommendation"] == "release"


def test_an_unproven_content_check_goes_to_ap():
    state, _ = run("EX-014", planted("EX-014", "content_check", evidence=["invoice_line:EX-014:1"])
                   + good_answer("EX-014"))  # "every line fits" must cite every line
    assert state["checks"][0]["problems"] == {
        "content_check": ["cite every invoice line you checked: invoice_line:EX-014:2"]}
    state, _ = run("EX-018", planted("EX-018", "content_check", evidence=["vendor:V-5002"]) + good_answer("EX-018"))
    assert ("cite the invoice line that does not fit: invoice_line:EX-018:1, invoice_line:EX-018:2"
            in state["checks"][0]["problems"]["content_check"])

    uncited = planted("EX-011", "content_check", evidence=[])
    state, _ = run("EX-011", uncited * 3)
    assert state["checks"][0]["problems"] == {
        "content_check": ["cites no evidence_id", "cite every invoice line you checked: invoice_line:EX-011:1"]}
    assert state["fallbacks"] == ["content_check"]
    assert state["outcome"]["findings"] == ["category_mismatch"]
    assert state["outcome"]["recommendation"] == "hold"
    assert [action["role"] for action in state["outcome"]["actions"]] == ["ap_queue"]


def test_explanations_must_cite_the_history_or_the_lease():
    state, _ = run("EX-012", planted("EX-012", "bill_change_explanation", evidence=["invoice_line:EX-012:1"])
                   + good_answer("EX-012"))
    assert state["checks"][0]["problems"] == {
        "bill_change_explanation": ["cite bill_history:V-2002, the bill history you looked up"]}
    assert state["checks"][1]["passed"]

    vague = "This bill is about 22% above the vendor's usual water bills, which is unusual for November."
    state, _ = run("EX-012", planted("EX-012", "bill_change_explanation", explanation=vague) + good_answer("EX-012"))
    assert state["checks"][0]["problems"] == {
        "bill_change_explanation": ["the number 22 is not in any record you were shown"]}

    state, _ = run("EX-014", planted("EX-014", "rent_difference_explanation", evidence=["invoice_line:EX-014:2"])
                   + good_answer("EX-014"))
    assert state["checks"][0]["problems"] == {"rent_difference_explanation": [
        "cite vendor:V-3001, the vendor record with the lease amount, or bill_history:V-3001"]}


def test_a_category_suggestion_must_rest_on_the_lines():
    bad = planted("EX-022", "category_suggestion", evidence=["vendor:V-7001"])
    state, _ = run("EX-022", bad + bad[-2:] + bad[-2:])
    assert state["checks"][0]["problems"] == {"category_suggestion": [
        "cite the invoice lines your suggestion is based on: invoice_line:EX-022:1"]}
    assert state["fallbacks"] == ["category_suggestion"]
    assert state["accepted"]["category_suggestion"]["category"] == ""
    assert state["outcome"]["findings"] == ["no_category"]  # AP sets the category either way


def test_a_non_po_duplicate_candidate_goes_to_ap_whatever_the_agent_says(tmp_path):
    invoices = {**INVOICES, "EX-011": replace(INVOICES["EX-011"], invoice_number="RPL 104834")}  # not an exact match
    assert nonpo_tasks(assess(invoices["EX-011"], REF)) == ("duplicate_check", "content_check")
    answer = {"duplicate_check": {"likely_duplicate": False, "evidence": ["posted:V-2001:RPL-104834"],
                                  "reason": "Posted RPL-104834 is the October bill for 4129.90, and this one is "
                                            "4402.35."},
              "content_check": SCRIPTS["EX-011"][-1]["answer"]["content_check"]}
    replies = [tool_turn("get_bill_history", vendor_id="V-2001"), DONE, answer_turn(answer)]
    state, _ = run("EX-011", replies, invoices)
    assert state["tool_calls"][0]["kind"] == "bill_history"
    assert state["checks"][-1]["passed"]
    assert state["outcome"]["findings"] == ["possible_duplicate"]  # the same invoice number once normalized

    graph = build_graph(REF, invoices, ScriptedClient(replies), writer=Writer(), checkpointer=InMemorySaver(),
                        log=DecisionLog(tmp_path / "decision_log.jsonl"))
    paused = graph.invoke({"exception_id": "EX-011"}, {"configurable": {"thread_id": "EX-011"}})
    assert [(email["template"], email["status"], email["release_on"]) for email in paused["emails"]] == [
        ("duplicate_notice", "held", "duplicate")]


def test_explanations_reach_the_approval_email():
    state, _ = run("EX-014", script("EX-014"))
    body = draft_emails(assess(INVOICES["EX-014"], REF), state["outcome"], state["accepted"], REF)[0]["body"]
    assert ("   From our review: Line 1 bills the lease amount of 18500.00, and line 2 adds a late payment fee "
            "of 925.00, which is the whole difference.") in body
    assert "agent" not in body and "content check" not in body
    assert readable("see bill_history:V-2002 and posted:V-2002:CWA-77323") == (
        "see the bill history and posted invoice CWA-77323")


def test_an_override_never_releases_a_non_po_invoice(tmp_path):
    state, _, log = reviewed("EX-015", {"decision": "override", "reason": "Lease renewal pending; hold for AP"},
                             tmp_path / "EX-015")
    assert (state["outcome"]["recommendation"], state["final_recommendation"]) == ("release", "hold")
    assert log.entries()[0]["decision"] == "override"

    state, _, _ = reviewed("EX-012", {"decision": "override", "reason": "Meter misread; AP asks the vendor"},
                           tmp_path / "EX-012")
    assert state["final_recommendation"] == "hold"
    assert [email["status"] for email in state["emails"]] == ["cancelled"]

    state, _, _ = reviewed("EX-011", {"decision": "confirm"}, tmp_path / "EX-011")
    assert state["final_recommendation"] == "release"
    assert state["emails"] == []


def test_the_review_packet_shows_the_agent_checks(tmp_path):
    state, packet, _ = reviewed("EX-018", {"decision": "confirm"}, tmp_path / "EX-018")
    assert packet["ap_items"] == [
        "agent verdict: content doesn't fit the category",
        "agent content check: does not fit the vendor's category: Line 2 bills 8 rugged handheld barcode "
        "scanners for 2960.00, which is hardware, not a subscription."]
    [approval] = [email for email in state["emails"] if email["template"] == "approval_request"]
    assert approval["status"] == "sent"  # the approval still goes to Priya Nair
    assert FALLBACK_PARAGRAPH not in approval["body"]

    _, packet, _ = reviewed("EX-022", {"decision": "confirm"}, tmp_path / "EX-022")
    assert packet["ap_items"][-1].startswith("agent category suggestion: subscriptions: ")

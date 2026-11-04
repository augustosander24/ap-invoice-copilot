"""Tests for the Phase 6 PO investigator graph, with a scripted model.

Unlike tests/test_rules.py, these use the real data files (data/reference/,
data/input/exception_list.xlsx, evals/expected_outcomes.csv), because the
graph runs real invoices. A scripted client stands in for Ollama: it replays
the tool calls and answers in tests/po_agent_scripts.json, or planted bad ones,
so the evidence check, retry, fallback, and cap rules run the same way every time.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ap_copilot.data import ROOT, load_invoices, load_reference, read_csv
from ap_copilot.graph import MAX_TOOL_CALLS, build_graph
from ap_copilot.investigator import po_tasks
from ap_copilot.rules import assess
from ap_copilot.tools import (PO_TOOL_SPECS, TOOL_KINDS, evidence_ids, find_similar_invoices,
                              get_goods_receipts, get_purchase_order, run_tool)

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}
EXPECTED = {row["exception_id"]: row for row in read_csv(ROOT / "evals" / "expected_outcomes.csv")}
SCRIPTS = json.loads(Path(__file__).with_name("po_agent_scripts.json").read_text(encoding="utf-8"))

DONE = {"role": "assistant", "content": "DONE"}


def tool_turn(name: str, **args) -> dict:
    """An assistant message with one tool call."""
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def answer_turn(answer) -> dict:
    """An assistant message whose content is the JSON answer."""
    return {"role": "assistant", "content": json.dumps(answer)}


def turns(steps: list[dict]) -> list[dict]:
    """The model turns for a script: one per tool step; DONE, then the answer, per answer step."""
    result = []
    for step in steps:
        if "tool" in step:
            result.append(tool_turn(step["tool"], **step["args"]))
        else:
            result += [DONE, answer_turn(step["answer"])]
    return result


class ScriptedClient:
    """Replays model turns in order; records whether each call was a tool turn or the answer."""

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.steps = []
        self.requests = []

    def chat(self, messages, tools=None, schema=None) -> dict:
        self.steps.append("answer" if schema is not None else "tools")
        self.requests.append(deepcopy(messages))
        return {"message": deepcopy(self.script.pop(0)), "seconds": 0.0, "prompt_tokens": 0,
                "output_tokens": 0}


def run(exception_id: str, script: list[dict]) -> tuple[dict, ScriptedClient]:
    """The final state of one graph run, and the client; every scripted turn must be used."""
    client = ScriptedClient(script)
    state = build_graph(REF, INVOICES, client).invoke({"exception_id": exception_id})
    assert client.script == [], f"{exception_id}: {len(client.script)} scripted turns not used"
    return state, client


def planted(exception_id: str, task: str, **changes) -> list[dict]:
    """The case's turns with one claim of its answer changed."""
    steps = deepcopy(SCRIPTS[exception_id])
    steps[-1]["answer"][task].update(changes)
    return turns(steps)


def good_answer(exception_id: str) -> list[dict]:
    """DONE, then the case's scripted answer: what a retry replies once it needs no more lookups."""
    return [DONE, answer_turn(SCRIPTS[exception_id][-1]["answer"])]


def test_tool_kinds_cover_the_eval_lookup_kinds():
    assert set(TOOL_KINDS.values()) == {"po", "receipts", "open_pos", "similar_invoices",
                                        "bill_history", "vendor"}
    names = [spec["function"]["name"] for spec in PO_TOOL_SPECS]
    assert set(names) <= set(TOOL_KINDS)
    assert "get_bill_history" not in names


def test_tools_return_evidence_ids():
    assert evidence_ids(get_goods_receipts(REF, "PO-26103")) == [
        "receipts:PO-26103", "receipt:R-5005", "receipt:R-5006", "receipt:R-5007"]
    match = find_similar_invoices(REF, "V-1003", "8817", "PO-26105")["posted_matches"][0]
    assert match["evidence_id"] == "posted:V-1003:008817"
    assert match["matched_on"] == ["same PO number", "same invoice number once normalized"]
    assert get_purchase_order(REF, "26105") == {"error": "26105 is not on file"}
    assert run_tool(REF, "get_purchase_order", {"po": "PO-26105"})["error"].startswith("bad arguments")


def test_po_tasks_come_from_the_assessment():
    assert po_tasks(assess(INVOICES["EX-005"], REF)) == ("price_variance_explanation",
                                                         "quantity_variance_explanation")
    assert po_tasks(assess(INVOICES["EX-006"], REF)) == ("duplicate_check", "po_match")
    with pytest.raises(ValueError, match="EX-011"):  # a content check is the non-PO investigator's job
        po_tasks(assess(INVOICES["EX-011"], REF))


def test_scripted_answers_match_the_eval_on_every_po_case():
    for exception_id, steps in SCRIPTS.items():
        expected = EXPECTED[exception_id]
        state, _ = run(exception_id, turns(steps))
        assert state["checks"] == [{"attempt": 1, "passed": True, "problems": {}}], exception_id
        assert state["tool_calls"][0]["kind"] in expected["first_tool"].split("|"), exception_id
        if expected["duplicate_verdict"]:
            verdict = "yes" if state["accepted"]["duplicate_check"]["likely_duplicate"] else "no"
            assert verdict == expected["duplicate_verdict"], exception_id
        if expected["po_match"]:
            assert state["accepted"]["po_match"]["po_number"] == expected["po_match"], exception_id
        assert ";".join(state["outcome"]["findings"]) == expected["findings"], exception_id
        assert state["outcome"]["recommendation"] == expected["day0_recommendation"], exception_id


def test_closed_po_is_rejected_then_retried():
    state, _ = run("EX-006", planted("EX-006", "po_match", po_number="PO-26105") + good_answer("EX-006"))
    assert [check["passed"] for check in state["checks"]] == [False, True]
    assert state["checks"][0]["problems"] == {
        "po_match": ["PO-26105 is closed; give an open PO of V-1003 or none"]}
    assert any("PO-26105 is closed" in entry["prompt"] for entry in state["transcript"])
    assert state["accepted"]["po_match"]["po_number"] == "PO-26106"


def test_evidence_not_returned_by_a_tool_is_rejected():
    steps = [step for step in SCRIPTS["EX-006"] if step.get("tool") != "find_open_purchase_orders"]
    retry = [tool_turn("find_open_purchase_orders", vendor_id="V-1003")] + good_answer("EX-006")
    state, _ = run("EX-006", turns(steps) + retry)
    assert ("po_line:PO-26106:1 was not returned by any tool in this run"
            in state["checks"][0]["problems"]["po_match"])
    assert state["checks"][1]["passed"]


def test_invented_number_is_rejected():
    claim = SCRIPTS["EX-001"][-1]["answer"]["price_variance_explanation"]
    script = planted("EX-001", "price_variance_explanation",
                     explanation=claim["explanation"] + " That is 1.50 more.")
    state, _ = run("EX-001", script + good_answer("EX-001"))
    assert state["checks"][0]["problems"] == {
        "price_variance_explanation": ["the number 1.50 is not in any record you were shown"]}


def test_another_vendors_po_is_rejected():
    script = planted("EX-003", "po_match", po_number="PO-26108", evidence=["po_line:PO-26108:1"])
    state, _ = run("EX-003", script + good_answer("EX-003"))
    assert state["checks"][0]["problems"] == {"po_match": ["PO-26108 belongs to V-1004, not V-1001"]}


def test_none_needs_the_open_po_search():
    steps = [step for step in SCRIPTS["EX-008"] if step.get("tool") != "find_open_purchase_orders"]
    retry = [tool_turn("find_open_purchase_orders", vendor_id="V-1003")] + good_answer("EX-008")
    state, _ = run("EX-008", turns(steps) + retry)
    assert "open_pos:V-1003 was not returned by any tool in this run" in state["checks"][0]["problems"]["po_match"]
    assert state["accepted"]["po_match"]["po_number"] == "none"


def test_duplicate_verdict_must_cite_the_candidate():
    script = planted("EX-008", "duplicate_check", evidence=["po:PO-26105"])
    state, _ = run("EX-008", script + good_answer("EX-008"))
    assert state["checks"][0]["problems"] == {
        "duplicate_check": ["cite posted:V-1003:008817, the posted invoice you compared"]}


def test_answer_that_is_not_json_is_retried():
    script = turns(SCRIPTS["EX-002"][:-1]) + [DONE, {"role": "assistant", "content": "The price is wrong."}]
    state, _ = run("EX-002", script + good_answer("EX-002"))
    assert state["checks"][0]["problems"]["price_variance_explanation"][0].startswith(
        "the answer is not valid JSON for the schema")
    assert state["checks"][1]["passed"]


def test_three_failures_use_the_fallbacks():
    closed = planted("EX-006", "po_match", po_number="PO-26105")
    state, _ = run("EX-006", closed + closed[-2:] + closed[-2:])
    assert len(state["checks"]) == 3
    assert state["fallbacks"] == ["po_match"]
    assert state["accepted"]["po_match"]["po_number"] == "none"
    assert state["outcome"]["findings"] == ["invalid_po"]

    uncited = planted("EX-006", "duplicate_check", evidence=["po:PO-26105"])
    state, _ = run("EX-006", uncited + uncited[-2:] + uncited[-2:])
    assert state["fallbacks"] == ["duplicate_check"]
    assert state["outcome"]["findings"] == ["invalid_po", "possible_duplicate"]
    assert [action["status"] for action in state["outcome"]["actions"]] == ["held", "queue"]


def test_tool_call_cap():
    assert MAX_TOOL_CALLS == 6
    eight = {"role": "assistant", "content": "",
             "tool_calls": tool_turn("get_purchase_order", po_number="PO-26101")["tool_calls"] * 8}
    state, client = run("EX-001", [eight, answer_turn(SCRIPTS["EX-001"][-1]["answer"])])
    assert len(state["tool_calls"]) == 8
    assert sum(call["error"].startswith("not run") for call in state["tool_calls"]) == 2
    assert client.steps == ["tools", "answer"]


def test_exact_duplicate_and_a_case_with_no_task_skip_the_agent():
    state, client = run("EX-010", [])
    assert state["status"] == "finalized"
    assert state["outcome"]["findings"] == ["exact_duplicate"]
    assert client.steps == []

    state, client = run("EX-016", [])  # taxes: a non-PO invoice with no agent task
    assert state["status"] == "finalized"
    assert state["outcome"]["findings"] == ["approval_required"]
    assert client.steps == []


def test_text_tool_calls_repeats_and_extra_arguments():
    script = [{"role": "assistant", "content": '{"name": "get_po", "parameters": {"po_number": "PO-26101"}}'},
              tool_turn("get_purchase_order", po_number="PO-26101", line_number="2"),
              tool_turn("get_purchase_order", po_number="PO-26101"),
              answer_turn(SCRIPTS["EX-001"][-1]["answer"])]  # the repeat ends the lookups: no DONE turn
    state, _ = run("EX-001", script)
    calls = state["tool_calls"]
    assert [call["tool"] for call in calls] == ["get_po", "get_purchase_order", "get_purchase_order"]
    assert calls[0]["error"].startswith("unknown tool get_po; use one of: get_purchase_order")
    assert calls[1]["error"] == "" and "po_line:PO-26101:2" in calls[1]["evidence_ids"]
    assert calls[1]["result"]["ignored_arguments"] == ["line_number"]
    assert calls[2]["error"].startswith("already looked up")
    assert state["checks"][-1]["passed"]


def test_reason_and_explanation_must_be_sentences():
    state, _ = run("EX-007", planted("EX-007", "po_match", reason="open PO") + good_answer("EX-007"))
    assert state["checks"][0]["problems"] == {
        "po_match": ["write the reason as a plain sentence of at least 5 words, not an evidence ID"]}
    state, _ = run("EX-001", planted("EX-001", "price_variance_explanation", explanation="po_line:PO-26101:2")
                   + good_answer("EX-001"))
    assert state["checks"][0]["problems"] == {"price_variance_explanation": [
        "write the explanation as a plain sentence of at least 5 words, not an evidence ID"]}


def test_po_match_problem_says_why():
    state, _ = run("EX-003", planted("EX-003", "po_match", po_number="PO-26101", evidence=["po_line:PO-26101:1"])
                   + good_answer("EX-003"))
    assert state["checks"][0]["problems"] == {"po_match": [
        "none of PO-26101's lines has an item on this invoice (IND-2630); give an open PO of V-1001 "
        "with that item, or none"]}
    state, _ = run("EX-006", planted("EX-006", "po_match", evidence=["po:PO-26106"]) + good_answer("EX-006"))
    assert state["checks"][0]["problems"] == {"po_match": [
        "cite po_line:PO-26106:1, the PO-26106 line whose item is on the invoice"]}


def test_each_model_call_is_a_fresh_single_turn():
    state, client = run("EX-001", turns(SCRIPTS["EX-001"]))
    assert all([m["role"] for m in request] == ["system", "user"] for request in client.requests)
    first_step, second_step, answer = (request[1]["content"] for request in client.requests)
    assert "Code facts:" not in first_step and "Lookups so far:\nnone" in first_step
    assert '1. get_purchase_order {"po_number": "PO-26101"} -> {"evidence_id": "po:PO-26101"' in second_step
    assert "Code facts:" in answer and "Records you looked up:" in answer
    assert [entry["step"] for entry in state["transcript"]] == ["tools", "tools", "answer"]


def test_numbers_in_a_rejection_never_count_as_shown():
    text = SCRIPTS["EX-001"][-1]["answer"]["price_variance_explanation"]["explanation"] + " That is 1.50 more."
    bad = planted("EX-001", "price_variance_explanation", explanation=text)
    state, client = run("EX-001", bad + bad[-2:] + good_answer("EX-001"))
    assert "the number 1.50 is not in any record you were shown" in client.requests[3][1]["content"]  # the retry step shows the reason
    assert [check["passed"] for check in state["checks"]] == [False, False, True]


def test_a_step_of_only_repeats_ends_the_lookups():
    script = [tool_turn("get_purchase_order", po_number="PO-26101"),
              tool_turn("get_purchase_order", po_number="PO-26101"),
              answer_turn(SCRIPTS["EX-001"][-1]["answer"])]
    state, client = run("EX-001", script)
    assert client.steps == ["tools", "tools", "answer"]
    assert state["tool_calls"][1]["error"].startswith("already looked up")
    failed = [tool_turn("get_purchase_order", po_number="PO-26101:2")] * 2
    retry = [tool_turn("get_purchase_order", po_number="PO-26101")] + good_answer("EX-001")
    state, client = run("EX-001", failed + [answer_turn(SCRIPTS["EX-001"][-1]["answer"])] + retry)
    assert client.steps == ["tools", "tools", "answer", "tools", "tools", "answer"]  # a failed lookup repeated counts too
    assert [check["passed"] for check in state["checks"]] == [False, True]

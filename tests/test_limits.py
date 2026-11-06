"""Tests for the Phase 10 output cap and reasoning setting, with no model: the settings, the request the
client sends, and what each agent does with a reply the cap cut off.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

import pytest

from ap_copilot import config
from ap_copilot.data import load_invoices, load_reference
from ap_copilot.emails import FALLBACK_PARAGRAPH, draft_emails, write_paragraph
from ap_copilot.graph import build_graph
from ap_copilot.inbox import CsvInbox
from ap_copilot.investigator import OllamaClient
from ap_copilot.reply_interpreter import interpret
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import assess

REF = load_reference()
INVOICES = {invoice.exception_id: invoice for invoice in load_invoices()}


class CutOff:
    """Stands in for a model whose every reply the output cap cut off before any answer."""

    model = "cut off"

    def chat(self, messages, tools=None, schema=None) -> dict:
        return {"message": {"role": "assistant", "content": ""}, "seconds": 0.0, "prompt_tokens": 0,
                "output_tokens": 4096, "done_reason": "length"}


def first_email(exception_id: str) -> dict:
    """The first draft of an invoice with no agent verdicts."""
    assessment = assess(INVOICES[exception_id], REF)
    return draft_emails(assessment, outcome_dict(finalize(assessment, REF, Verdicts())), {}, REF)[0]


def test_each_agent_has_a_cap_and_a_reasoning_setting(monkeypatch):
    assert {agent: config.get_max_tokens(agent) for agent in config.AGENTS} == {
        "po_investigator": 4096, "nonpo_investigator": 4096, "reply_interpreter": 4096, "communicator": 512}
    for agent in config.AGENTS:
        monkeypatch.delenv(f"THINK_{agent.upper()}", raising=False)
        assert config.get_think(agent) is None
    monkeypatch.setenv("THINK_PO_INVESTIGATOR", "on")
    monkeypatch.setenv("THINK_REPLY_INTERPRETER", "Off")
    assert (config.get_think("po_investigator"), config.get_think("reply_interpreter")) == (True, False)


def test_a_bad_setting_stops_with_its_name(monkeypatch):
    monkeypatch.setenv("THINK_COMMUNICATOR", "maybe")
    with pytest.raises(ValueError, match="THINK_COMMUNICATOR"):
        config.get_think("communicator")
    with pytest.raises(ValueError, match="Unknown agent"):
        config.get_max_tokens("auditor")


def test_the_client_sends_the_cap_and_the_setting(monkeypatch):
    sent = {}

    class Response:
        class message:
            content, tool_calls = "ok", None
        prompt_eval_count, eval_count, done_reason = 3, 2, "stop"

    class Client:
        def __init__(self, host):
            pass

        def chat(self, **request):
            sent.update(request)
            return Response()

    monkeypatch.setattr("ollama.Client", Client)
    monkeypatch.setenv("THINK_NONPO_INVESTIGATOR", "on")
    reply = OllamaClient("nonpo_investigator").chat([{"role": "user", "content": "hi"}])
    assert sent["options"] == {"temperature": 0, "num_ctx": 8192, "num_predict": 4096} and sent["think"] is True
    assert reply["done_reason"] == "stop"


def test_a_cut_off_answer_is_retried_then_falls_back():
    state = build_graph(REF, INVOICES, CutOff()).invoke({"exception_id": "EX-011"})
    assert [check["passed"] for check in state["checks"]] == [False, False, False]
    assert state["fallbacks"] == ["content_check"] and state["outcome"]["findings"] == ["category_mismatch"]
    assert {call["done_reason"] for call in state["model_calls"]} == {"length"}


def test_a_cut_off_paragraph_becomes_the_fixed_sentence():
    written, call = write_paragraph(first_email("EX-001"), CutOff(), REF)
    assert (written["paragraph"], call["done_reason"]) == (FALLBACK_PARAGRAPH, "length")


def test_a_cut_off_reply_label_is_unclear():
    reply = next(reply for reply in CsvInbox().replies("2026-12-07") if reply.message_id == "M-01")
    record, call = interpret(reply, first_email("EX-001"), CutOff(), REF)
    assert record["label"] == "unclear" and call["done_reason"] == "length"

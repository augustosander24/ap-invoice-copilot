"""The PO investigator: its tasks, prompts, answer schema, and model client.

Code decides the tasks from the Assessment; the model only looks records up
and answers those tasks. The answer is JSON in a schema built from the tasks,
so the evidence check can read every claim.
"""

import json
import re
import time

from pydantic import BaseModel, create_model

from ap_copilot.config import OLLAMA_HOST, get_model
from ap_copilot.evidence import EXPLANATION_FINDINGS
from ap_copilot.rules import Assessment

STEP_SYSTEM_PROMPT = (
    "You are the PO invoice investigator in an accounts payable team. Code has already run every "
    "rule check on the invoice; you investigate only the tasks you are given. Each turn, call one "
    "tool to look up a record you still need, or reply with the single word DONE when you have every "
    "record you need. Every record a tool returns has an evidence_id."
)
ANSWER_SYSTEM_PROMPT = (
    "You are the PO invoice investigator in an accounts payable team. Code has already run every "
    "rule check on the invoice. Answer your tasks as JSON, using only the invoice, the code facts, "
    "and the records you looked up."
)
TASK_TEXT = {
    "duplicate_check": "duplicate_check: decide whether this invoice bills the same charge as "
                       "posted invoice {candidates}. A shared PO number alone is not a duplicate: "
                       "compare the items, amounts, and dates.",
    "po_match": "po_match: find the vendor's open PO this invoice belongs to, or answer none.",
    "price_variance_explanation": "price_variance_explanation: explain the likely cause of the "
                                  "price variance.",
    "quantity_variance_explanation": "quantity_variance_explanation: explain the likely cause of "
                                     "the quantity variance, using the receipts.",
}
CITE_TEXT = {
    "duplicate_check": "duplicate_check: cite the posted invoice you compared.",
    "po_match": "po_match: cite the PO line that matches an invoice item, or cite "
                "open_pos:{vendor_id} when you answer none.",
    "price_variance_explanation": "price_variance_explanation: cite the PO line whose price differs.",
    "quantity_variance_explanation": "quantity_variance_explanation: cite receipts:{po_number}.",
}
ANSWER_PROMPT_OPENING = ("Answer now as JSON with one entry per task. Cite evidence_id values exactly "
                         "as the tools returned them. Use only figures that appear in the records. "
                         "Put evidence_id values only in the evidence list, and write each reason or "
                         "explanation as one or two plain sentences.")
RETRY_OPENING = "The evidence check rejected your answer:"
RETRY_CLOSING = "Look up any record you still need, then reply DONE."

MODEL_OPTIONS = {"temperature": 0, "num_ctx": 8192}


class DuplicateClaim(BaseModel):
    likely_duplicate: bool
    reason: str
    evidence: list[str]


class PoMatchClaim(BaseModel):
    po_number: str
    reason: str
    evidence: list[str]


class ExplanationClaim(BaseModel):
    explanation: str
    evidence: list[str]


_CLAIMS = {"duplicate_check": DuplicateClaim, "po_match": PoMatchClaim,
           "price_variance_explanation": ExplanationClaim,
           "quantity_variance_explanation": ExplanationClaim}
_REQUEST_TASKS = ("duplicate_check", "po_match")


def po_tasks(assessment: Assessment) -> tuple[str, ...]:
    """The investigator's tasks: the agent requests it handles, then one explanation per variance."""
    kinds = [request.kind for request in assessment.agent_requests]
    others = [kind for kind in kinds if kind not in _REQUEST_TASKS]
    if others:
        raise ValueError(f"{assessment.invoice.exception_id}: the PO investigator can't answer "
                         f"{', '.join(others)}")
    return (tuple(task for task in _REQUEST_TASKS if task in kinds)
            + tuple(task for finding, task in EXPLANATION_FINDINGS.items()
                    if finding in assessment.findings))


def candidates_of(assessment: Assessment) -> tuple[str, ...]:
    """The posted invoice numbers the code sent with its duplicate_check request."""
    for request in assessment.agent_requests:
        if request.kind == "duplicate_check":
            return request.detail
    return ()


def invoice_block(assessment: Assessment) -> list[str]:
    """The invoice header and its lines, each with its evidence_id."""
    invoice = assessment.invoice
    ident = invoice.exception_id
    amount = invoice.amount if invoice.amount is not None else "blank"
    lines = [f"Invoice {ident} (evidence_id invoice:{ident}): vendor {invoice.vendor_id} "
             f"{invoice.vendor_name}, invoice number {invoice.invoice_number}, dated "
             f"{invoice.invoice_date}, PO number {invoice.po_number or 'none'}, amount {amount}.",
             "Lines:"]
    lines += [f"- line {line.line} (evidence_id invoice_line:{ident}:{line.line}): {line.item} "
              f"{line.description}, quantity {line.quantity}, unit price {line.unit_price}, "
              f"amount {line.line_amount}, PO line {line.po_line or 'none'}"
              for line in invoice.lines]
    return lines


def _task_lines(assessment: Assessment, tasks: tuple[str, ...]) -> list[str]:
    candidates = ", ".join(candidates_of(assessment))
    return ["Your tasks:"] + [f"{number}. {TASK_TEXT[task].format(candidates=candidates)}"
                              for number, task in enumerate(tasks, start=1)]


def _lookup_lines(lookups: list[dict]) -> list[str]:
    """One line per lookup made so far: the tool, its arguments, and its result as JSON."""
    return [f"{number}. {call['tool']} {to_json(call['args'])} -> {to_json(call['result'])}"
            for number, call in enumerate(lookups, start=1)]


def _retry_lines(reasons: list[str]) -> list[str]:
    return [RETRY_OPENING] + [f"- {reason}" for reason in reasons] if reasons else []


def step_message(assessment: Assessment, tasks: tuple[str, ...], lookups: list[dict],
                 reasons: list[str]) -> str:
    """One tool step, sent fresh each turn: the invoice, the findings, the tasks, any rejection
    reasons, and every lookup so far. The code facts are left out, so the records must come from
    the tools."""
    lines = invoice_block(assessment)
    lines.append(f"Code findings: {', '.join(assessment.findings) or 'none'}")
    lines += _task_lines(assessment, tasks)
    if reasons:
        lines += _retry_lines(reasons) + [RETRY_CLOSING]
    lines += ["Lookups so far:"] + (_lookup_lines(lookups) or ["none"])
    lines.append("Call one tool for the next record you need, or reply DONE.")
    return "\n".join(lines)


def answer_message(assessment: Assessment, tasks: tuple[str, ...], lookups: list[dict],
                   reasons: list[str]) -> str:
    """The answer step: the invoice, findings, code facts, tasks, the records looked up, any
    rejection reasons, and one citation rule per task."""
    invoice = assessment.invoice
    lines = invoice_block(assessment)
    lines.append(f"Code findings: {', '.join(assessment.findings) or 'none'}")
    lines.append("Code facts:")
    lines += [f"- {fact}" for fact in assessment.facts]
    lines += _task_lines(assessment, tasks)
    lines += ["Records you looked up:"] + (_lookup_lines(lookups) or ["none"])
    lines += _retry_lines(reasons)
    lines.append(ANSWER_PROMPT_OPENING)
    lines += [CITE_TEXT[task].format(vendor_id=invoice.vendor_id, po_number=invoice.po_number)
              for task in tasks]
    return "\n".join(lines)


def shown_text(assessment: Assessment, lookups: list[dict]) -> str:
    """Everything the answer step shows as data: the invoice, the code facts, and the successful
    lookups. Rejection reasons are not data, so their numbers never count as shown."""
    parts = invoice_block(assessment) + list(assessment.facts)
    parts += [to_json(call["result"]) for call in lookups if not call["error"]]
    return "\n".join(parts)


def _answer_model(tasks: tuple[str, ...]) -> type[BaseModel]:
    """A pydantic model with one required claim per task."""
    return create_model("InvestigationAnswer", **{task: (_CLAIMS[task], ...) for task in tasks})


def answer_schema(tasks: tuple[str, ...]) -> dict:
    """The JSON schema the answer call sends as its format."""
    return _answer_model(tasks).model_json_schema()


def parse_answer(text: str, tasks: tuple[str, ...]) -> dict:
    """The answer as a plain dict; invalid JSON or a missing claim raises ValueError."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    return _answer_model(tasks).model_validate_json(cleaned).model_dump()


class OllamaClient:
    """One Ollama chat call, returned as plain dicts; tests swap in a scripted client."""

    def __init__(self, agent: str = "po_investigator"):
        from ollama import Client  # imported here so tests never need a server
        self.model = get_model(agent)
        self.client = Client(host=OLLAMA_HOST)

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             schema: dict | None = None) -> dict:
        """Send the conversation; return the reply message, seconds, and token counts."""
        started = time.perf_counter()
        response = self.client.chat(model=self.model, messages=messages, tools=tools,
                                    format=schema, options=MODEL_OPTIONS)
        seconds = round(time.perf_counter() - started, 1)
        message = {"role": "assistant", "content": response.message.content or ""}
        if response.message.tool_calls:
            message["tool_calls"] = [{"function": {"name": call.function.name,
                                                   "arguments": dict(call.function.arguments)}}
                                     for call in response.message.tool_calls]
        return {"message": message, "seconds": seconds,
                "prompt_tokens": response.prompt_eval_count, "output_tokens": response.eval_count}


def to_json(value) -> str:
    """JSON text for a message, keeping non-ASCII characters as they are."""
    return json.dumps(value, ensure_ascii=False)

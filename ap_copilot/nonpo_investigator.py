"""The non-PO investigator: its tasks, prompts, and answer schema.

Code decides the tasks from the Assessment; the model only looks records up
and answers those tasks, in the same fresh-request design as the PO
investigator. The model client is investigator.OllamaClient, with the agent
name "nonpo_investigator".
"""

import re
from typing import Literal

from pydantic import BaseModel, create_model

from ap_copilot.evidence import APPROVAL_EXPLANATIONS, CATEGORIES
from ap_copilot.investigator import (ANSWER_PROMPT_OPENING, RETRY_CLOSING, DuplicateClaim,
                                     ExplanationClaim, _lookup_lines, _retry_lines, candidates_of,
                                     to_json)
from ap_copilot.rules import Assessment

STEP_SYSTEM_PROMPT = (
    "You are the non-PO invoice investigator in an accounts payable team. Code has already run every "
    "rule check on the invoice; you investigate only the tasks you are given. Each turn, call one "
    "tool to look up a record you still need, or reply with the single word DONE when you have every "
    "record you need. Every record a tool returns has an evidence_id."
)
ANSWER_SYSTEM_PROMPT = (
    "You are the non-PO invoice investigator in an accounts payable team. Code has already run every "
    "rule check on the invoice. Answer your tasks as JSON, using only the invoice, the code facts, "
    "and the records you looked up."
)
TASK_TEXT = {
    "duplicate_check": "duplicate_check: decide whether this invoice bills the same charge as "
                       "posted invoice {candidates}: compare the service months, amounts, and dates.",
    "content_check": "content_check: decide whether every line of this invoice fits the vendor's "
                     "category, {category}; set mismatch to true if any line does not fit.",
    "category_suggestion": "category_suggestion: the vendor has no category; suggest the one its "
                           "invoices belong to: " + ", ".join(CATEGORIES) + ".",
    "bill_change_explanation": "bill_change_explanation: explain how this bill compares with the "
                               "vendor's earlier bills.",
    "rent_difference_explanation": "rent_difference_explanation: explain the likely cause of the "
                                   "difference between this bill and the lease amount.",
}
CITE_TEXT = {
    "duplicate_check": "duplicate_check: cite the posted invoice you compared.",
    "content_check": "content_check: cite every invoice line you checked, or the line that does not fit.",
    "category_suggestion": "category_suggestion: cite the invoice lines your suggestion is based on.",
    "bill_change_explanation": "bill_change_explanation: cite bill_history:{vendor_id} or the posted "
                               "bills you compared.",
    "rent_difference_explanation": "rent_difference_explanation: cite vendor:{vendor_id} for the lease "
                                   "amount, or bill_history:{vendor_id}.",
}


class ContentClaim(BaseModel):
    mismatch: bool
    reason: str
    evidence: list[str]


class CategoryClaim(BaseModel):
    category: Literal[CATEGORIES]
    reason: str
    evidence: list[str]


_CLAIMS = {"duplicate_check": DuplicateClaim, "content_check": ContentClaim,
           "category_suggestion": CategoryClaim,
           "bill_change_explanation": ExplanationClaim,
           "rent_difference_explanation": ExplanationClaim}
_REQUEST_TASKS = ("duplicate_check", "content_check", "category_suggestion")
NO_LOOKUP_TASKS = ("content_check",)  # everything it needs is in the message: the lines and the category


def nonpo_tasks(assessment: Assessment) -> tuple[str, ...]:
    """The investigator's tasks: the agent requests it handles, then the explanation the approval reason calls for."""
    kinds = [request.kind for request in assessment.agent_requests]
    others = [kind for kind in kinds if kind not in _REQUEST_TASKS]
    if others:
        raise ValueError(f"{assessment.invoice.exception_id}: the non-PO investigator can't answer "
                         f"{', '.join(others)}")
    tasks = tuple(task for task in _REQUEST_TASKS if task in kinds)
    explanation = APPROVAL_EXPLANATIONS.get(assessment.approval_reason)
    return tasks + ((explanation,) if explanation else ())


def needs_lookups(tasks: tuple[str, ...]) -> bool:
    """False when every task can be answered from the message alone, so the tool steps are skipped."""
    return any(task not in NO_LOOKUP_TASKS for task in tasks)


def invoice_block(assessment: Assessment) -> list[str]:
    """The invoice header and its lines, each with its evidence_id; the PO-only fields are left out."""
    invoice = assessment.invoice
    ident = invoice.exception_id
    amount = invoice.amount if invoice.amount is not None else "blank"
    lines = [f"Invoice {ident} (evidence_id invoice:{ident}): vendor {invoice.vendor_id} "
             f"{invoice.vendor_name}, invoice number {invoice.invoice_number}, dated "
             f"{invoice.invoice_date}, service month {invoice.service_month or 'none'}, amount {amount}.",
             "Lines:"]
    lines += [f"- line {line.line} (evidence_id invoice_line:{ident}:{line.line}): "
              f"{line.description}, amount {line.line_amount}"
              for line in invoice.lines]
    return lines


def _task_lines(assessment: Assessment, category: str, tasks: tuple[str, ...]) -> list[str]:
    candidates = ", ".join(candidates_of(assessment))
    return ["Your tasks:"] + [f"{number}. {TASK_TEXT[task].format(candidates=candidates, category=category)}"
                              for number, task in enumerate(tasks, start=1)]


def step_message(assessment: Assessment, category: str, tasks: tuple[str, ...], lookups: list[dict],
                 reasons: list[str]) -> str:
    """One tool step, sent fresh each turn, as for the PO investigator: the code facts are left out, so
    the records must come from the tools."""
    lines = invoice_block(assessment)
    lines.append(f"Code findings: {', '.join(assessment.findings) or 'none'}")
    lines += _task_lines(assessment, category, tasks)
    if reasons:
        lines += _retry_lines(reasons) + [RETRY_CLOSING]
    lines += ["Lookups so far:"] + (_lookup_lines(lookups) or ["none"])
    lines.append("Call one tool for the next record you need, or reply DONE.")
    return "\n".join(lines)


def answer_message(assessment: Assessment, category: str, tasks: tuple[str, ...], lookups: list[dict],
                   reasons: list[str]) -> str:
    """The answer step: the invoice, findings, code facts, tasks, the records looked up, any
    rejection reasons, and one citation rule per task."""
    invoice = assessment.invoice
    lines = invoice_block(assessment)
    lines.append(f"Code findings: {', '.join(assessment.findings) or 'none'}")
    lines.append("Code facts:")
    lines += [f"- {fact}" for fact in assessment.facts]
    lines += _task_lines(assessment, category, tasks)
    lines += ["Records you looked up:"] + (_lookup_lines(lookups) or ["none"])
    lines += _retry_lines(reasons)
    lines.append(ANSWER_PROMPT_OPENING)
    lines += [CITE_TEXT[task].format(vendor_id=invoice.vendor_id) for task in tasks]
    return "\n".join(lines)


def shown_text(assessment: Assessment, lookups: list[dict]) -> str:
    """Everything the answer step shows as data: the invoice, the code facts, and the successful
    lookups. Rejection reasons are not data, so their numbers never count as shown."""
    parts = invoice_block(assessment) + list(assessment.facts)
    parts += [to_json(call["result"]) for call in lookups if not call["error"]]
    return "\n".join(parts)


def _answer_model(tasks: tuple[str, ...]) -> type[BaseModel]:
    """A pydantic model with one required claim per task."""
    return create_model("NonPoAnswer", **{task: (_CLAIMS[task], ...) for task in tasks})


def answer_schema(tasks: tuple[str, ...]) -> dict:
    """The JSON schema the answer call sends as its format."""
    return _answer_model(tasks).model_json_schema()


def parse_answer(text: str, tasks: tuple[str, ...]) -> dict:
    """The answer as a plain dict; invalid JSON or a missing claim raises ValueError."""
    cleaned = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    return _answer_model(tasks).model_validate_json(cleaned).model_dump()

"""Routing for AP Invoice Copilot: the agent's verdicts, the final findings, and the actions.

finalize() takes an Assessment from rules.assess() and the agent's verdicts,
and returns the Outcome: final findings, recommendation, and one action per
recipient with its follow-up contacts. Code decides all of it; no model runs here.
"""

from dataclasses import dataclass

from ap_copilot.data import Reference
from ap_copilot.rules import AP_MANAGER, AP_QUEUE_FINDINGS, AP_TEAM, BUYER_FINDINGS, FINDINGS, VENDOR_FINDINGS, Assessment, Fact


@dataclass(frozen=True)
class Verdicts:
    duplicate: bool | None = None
    mismatch: bool | None = None


@dataclass(frozen=True)
class Action:
    recipient_id: str
    role: str
    findings: tuple[str, ...]
    status: str
    after: str
    reminder_cc: str
    escalation_to: str


@dataclass(frozen=True)
class Outcome:
    exception_id: str
    path: str
    findings: tuple[str, ...]
    approval_reason: str
    approver_id: str
    gl_account: str
    recommendation: str
    actions: tuple[Action, ...]
    facts: tuple[str, ...]
    fact_records: tuple[Fact, ...] = ()


_VERDICTS = (("duplicate", "duplicate_check"), ("mismatch", "content_check"))


def _check_verdicts(assessment: Assessment, verdicts: Verdicts) -> None:
    """Each requested check needs its verdict, and no verdict may answer a check that wasn't requested."""
    requested = {request.kind for request in assessment.agent_requests}
    exception_id = assessment.invoice.exception_id
    for name, kind in _VERDICTS:
        given = getattr(verdicts, name) is not None
        if kind in requested and not given:
            raise ValueError(f"{exception_id}: {kind} was requested but verdicts.{name} is missing")
        if given and kind not in requested:
            raise ValueError(f"{exception_id}: verdicts.{name} was given but {kind} was not requested")


def _apply_verdicts(assessment: Assessment, verdicts: Verdicts) -> tuple[tuple[str, ...], tuple[Fact, ...]]:
    """The assessment's findings and facts, plus the agent findings, in canonical order.

    A yes adds the agent finding. A duplicate candidate with the same invoice number once
    normalized is a possible duplicate even on a no: the agent can't clear it, AP decides.
    """
    findings = set(assessment.findings)
    facts = list(assessment.fact_records)
    same_number = next((request.same_number for request in assessment.agent_requests
                        if request.kind == "duplicate_check"), ())
    if verdicts.duplicate is True:
        findings.add("possible_duplicate")
        facts.append(Fact(("possible_duplicate",), "agent verdict: likely duplicate"))
    elif same_number:
        findings.add("possible_duplicate")
        facts.append(Fact(("possible_duplicate",), f"agent verdict: not a duplicate; AP reviews it anyway, because "
                          f"posted {', '.join(same_number)} has the same invoice number once normalized"))
    if verdicts.mismatch is True:
        findings.add("category_mismatch")
        facts.append(Fact(("category_mismatch",), "agent verdict: content doesn't fit the category"))
    return tuple(finding for finding in FINDINGS if finding in findings), tuple(facts)


def _recipient(finding: str, assessment: Assessment, ref: Reference) -> tuple[str, str]:
    """(recipient_id, role) for one finding."""
    invoice = assessment.invoice
    if finding in BUYER_FINDINGS:
        return ref.purchase_orders[invoice.po_number]["buyer_id"], "buyer"
    if finding in VENDOR_FINDINGS:
        return invoice.vendor_id, "vendor"
    if finding == "approval_required":
        return assessment.approver_id, "approver"
    if finding == "confirmation_required":
        return invoice.requester_id, "requester"
    if finding in AP_QUEUE_FINDINGS:
        return AP_TEAM, "ap_queue"
    raise ValueError(f"{invoice.exception_id}: no recipient for finding {finding}")


def _follow_up(recipient_id: str, role: str, ref: Reference) -> tuple[str, str]:
    """(reminder_cc, escalation_to): a person's manager for both; AP Team and AP Manager for a vendor; none for the AP queue."""
    if role == "ap_queue":
        return "", ""
    if role == "vendor":
        return AP_TEAM, AP_MANAGER
    manager = ref.people[recipient_id]["reports_to"]
    return manager, manager


def _actions(assessment: Assessment, ref: Reference, findings: tuple[str, ...]) -> tuple[Action, ...]:
    """One action per recipient, ordered by each action's first finding in canonical order."""
    grouped = {}
    for finding in findings:
        grouped.setdefault(_recipient(finding, assessment, ref), []).append(finding)
    held = "possible_duplicate" in findings
    actions = []
    for (recipient_id, role), its_findings in grouped.items():
        if role == "ap_queue":
            status = "queue"
        elif held:
            status = "held"
        else:
            status = "send"
        after = "confirmation" if role == "approver" and "confirmation_required" in findings else ""
        reminder_cc, escalation_to = _follow_up(recipient_id, role, ref)
        actions.append(Action(recipient_id, role, tuple(its_findings), status, after, reminder_cc, escalation_to))
    return tuple(actions)


def finalize(assessment: Assessment, ref: Reference, verdicts: Verdicts) -> Outcome:
    """Apply the agent's verdicts and route every finding.

    finalize() turns the agent's verdicts into findings, so the agent never writes
    a finding itself, and its no can't clear a same-number duplicate candidate. On a
    possible duplicate, every finding is listed and the non-AP actions are held until
    AP rules (design section 4).
    """
    _check_verdicts(assessment, verdicts)
    findings, facts = _apply_verdicts(assessment, verdicts)
    return Outcome(
        exception_id=assessment.invoice.exception_id,
        path=assessment.path,
        findings=findings,
        approval_reason=assessment.approval_reason,
        approver_id=assessment.approver_id,
        gl_account=assessment.gl_account,
        recommendation="hold" if findings else "release",
        actions=_actions(assessment, ref, findings),
        facts=tuple(fact.text for fact in facts),
        fact_records=facts,
    )


def outcome_dict(outcome: Outcome) -> dict:
    """An Outcome as plain data, for graph state and run files."""
    return {
        "path": outcome.path,
        "findings": list(outcome.findings),
        "approval_reason": outcome.approval_reason,
        "approver_id": outcome.approver_id,
        "gl_account": outcome.gl_account,
        "recommendation": outcome.recommendation,
        "actions": [{"recipient_id": action.recipient_id, "role": action.role,
                     "findings": list(action.findings), "status": action.status,
                     "after": action.after, "reminder_cc": action.reminder_cc,
                     "escalation_to": action.escalation_to}
                    for action in outcome.actions],
        "facts": list(outcome.facts),
        "fact_records": [{"findings": list(fact.findings), "text": fact.text, "vendor_text": fact.vendor_text,
                          "email_text": fact.email_text} for fact in outcome.fact_records],
    }

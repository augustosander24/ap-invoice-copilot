"""Deterministic rules for AP Invoice Copilot.

Code decides every financial control here: intake checks, the PO and non-PO
rules, the approver, and GL coding. Each check is a small private function
that records findings, fact lines, and agent requests for one invoice.
Amounts are Decimal, never float. No model runs in this module.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

from ap_copilot.data import Invoice, InvoiceLine, Reference

FINDINGS = ("price_variance", "quantity_variance", "missing_po", "invalid_po", "exact_duplicate",
            "possible_duplicate", "missing_data", "approval_required", "confirmation_required",
            "no_requester", "no_category", "category_mismatch")
AP_QUEUE_FINDINGS = ("possible_duplicate", "category_mismatch", "no_requester", "no_category")
BUYER_FINDINGS = ("price_variance", "quantity_variance")
VENDOR_FINDINGS = ("missing_po", "invalid_po", "exact_duplicate", "missing_data")
AGENT_FINDINGS = ("possible_duplicate", "category_mismatch")  # only finalize() adds these
SERVICE_MONTH_REQUIRED = ("utilities", "rent", "taxes", "subscriptions")

TOLERANCE_RATE = Decimal("0.02")
TOLERANCE_CAP = Decimal("100.00")
UTILITY_VARIANCE_RATE = Decimal("0.10")
NEW_VENDOR_BILLS = 3
BASELINE_BILLS = 12

AP_TEAM = "P-104"
AP_MANAGER = "P-103"

AGENT_REQUEST_KINDS = ("duplicate_check", "po_match", "content_check", "category_suggestion")

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class AgentRequest:
    kind: str
    detail: tuple[str, ...] = ()
    same_number: tuple[str, ...] = ()  # duplicate_check: candidates with the same normalized invoice number


@dataclass(frozen=True)
class Assessment:
    invoice: Invoice
    path: str
    findings: tuple[str, ...]
    approval_reason: str
    approver_id: str
    gl_account: str
    agent_requests: tuple[AgentRequest, ...]
    facts: tuple[str, ...]


class RuleDataError(Exception):
    """The master data can't support a rule; the message names the exception_id."""


@dataclass
class _Notes:
    """What the checks record for one invoice while assess() runs."""
    findings: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    requests: list[AgentRequest] = field(default_factory=list)
    approval_reason: str = ""


def normalize_invoice_number(number: str) -> str:
    """Uppercase, keep only A-Z and 0-9, and drop leading zeros from each run of digits."""
    cleaned = re.sub(r"[^A-Z0-9]", "", number.upper())
    return re.sub(r"[0-9]+", lambda run: run.group().lstrip("0") or "0", cleaned)


def tolerance_limit(amount: Decimal) -> Decimal:
    """2% of the amount, rounded to the cent, capped at 100.00."""
    return min((amount * TOLERANCE_RATE).quantize(_CENT, rounding=ROUND_HALF_UP), TOLERANCE_CAP)


def _money(amount) -> str:
    """Two decimals, no thousands separator: Decimal("4129.9") → "4129.90"."""
    return str(Decimal(amount).quantize(_CENT, rounding=ROUND_HALF_UP))


def _percent(rate: Decimal) -> str:
    """A rate as a whole percentage text: Decimal("0.02") → "2%", Decimal("0.10") → "10%"."""
    return f"{(rate * 100).normalize():f}%"


def _lines_total(invoice: Invoice) -> Decimal:
    """Sum of the invoice's line amounts."""
    return sum((line.line_amount for line in invoice.lines), Decimal("0"))


def _working_amount(invoice: Invoice) -> Decimal:
    """The header amount, or the lines total when the header is blank."""
    return invoice.amount if invoice.amount is not None else _lines_total(invoice)


def _vendor(invoice: Invoice, ref: Reference) -> dict[str, str]:
    """Check 0: the invoice's vendor row. A blank or unknown vendor can't be routed."""
    if not invoice.vendor_id:
        raise RuleDataError(f"{invoice.exception_id}: vendor_id is blank")
    if invoice.vendor_id not in ref.vendors:
        raise RuleDataError(f"{invoice.exception_id}: vendor {invoice.vendor_id} is not on file")
    return ref.vendors[invoice.vendor_id]


def _exact_duplicate(invoice: Invoice, ref: Reference, notes: _Notes) -> bool:
    """Check 1: same vendor and same invoice number text as a posted invoice. True stops every other check."""
    for posted in ref.history.get(invoice.vendor_id, ()):
        if posted["invoice_number"] == invoice.invoice_number:
            notes.findings.append("exact_duplicate")
            notes.facts.append(f"exact duplicate of posted {posted['invoice_number']} "
                               f"({posted['invoice_date']}, {_money(posted['amount'])})")
            return True
    return False


def _duplicate_candidates(invoice: Invoice, ref: Reference, notes: _Notes) -> None:
    """Check 2: posted invoices of the same vendor with the same PO or the same normalized number.

    Amount and date are never compared. Candidates go to the agent; no finding is added here.
    A same-number candidate is also listed in same_number: finalize() sends it to AP whatever
    the agent's verdict.
    """
    number = normalize_invoice_number(invoice.invoice_number)
    candidates, same_number = [], []
    for posted in ref.history.get(invoice.vendor_id, ()):
        matches = []
        if invoice.po_number and posted["po_number"] == invoice.po_number:
            matches.append(f"same PO {invoice.po_number}")
        if normalize_invoice_number(posted["invoice_number"]) == number:
            matches.append("same invoice number once normalized")
            same_number.append(posted["invoice_number"])
        if matches:
            candidates.append(posted["invoice_number"])
            notes.facts.append(f"duplicate candidate: posted {posted['invoice_number']} "
                               f"({posted['invoice_date']}, {_money(posted['amount'])}): "
                               f"{', '.join(matches)}")
    if candidates:
        notes.requests.append(AgentRequest("duplicate_check", tuple(candidates), tuple(same_number)))


def _missing_data(invoice: Invoice, vendor: dict[str, str], notes: _Notes) -> None:
    """Check 3: required header fields, the service month where the category needs one, and the header total."""
    problems = [f"{name} is blank" for name in ("invoice_number", "invoice_date", "amount")
                if getattr(invoice, name) in ("", None)]
    if vendor["category"] in SERVICE_MONTH_REQUIRED and not invoice.service_month:
        problems.append(f"service_month is blank on a {vendor['category']} bill")
    lines_total = _lines_total(invoice)
    if invoice.amount is not None and invoice.amount != lines_total:
        problems.append(f"header amount {_money(invoice.amount)} does not equal the lines total "
                        f"{_money(lines_total)}")
    for problem in problems:
        notes.findings.append("missing_data")
        notes.facts.append(problem)


def _path(invoice: Invoice, vendor: dict[str, str]) -> str:
    """Check 4: "po" when the invoice quotes a PO or the vendor is inventory; otherwise "non_po". The hold code is ignored."""
    return "po" if invoice.po_number or vendor["category"] == "inventory" else "non_po"


def _po_checks(invoice: Invoice, ref: Reference, notes: _Notes) -> None:
    """PO path: missing PO, invalid PO, then line matching and tolerance on a valid PO.

    No approval, approver, or GL here; a PO invoice is coded through its PO.
    """
    if _missing_po(invoice, notes) or _invalid_po(invoice, ref, notes):
        return
    matched = _match_lines(invoice, ref, notes)
    _tolerance(invoice, ref, matched, notes)


def _missing_po(invoice: Invoice, notes: _Notes) -> bool:
    """PO check 1: no PO number (only an inventory vendor reaches here without one). True stops the PO checks."""
    if invoice.po_number:
        return False
    notes.findings.append("missing_po")
    notes.facts.append("no PO number on an inventory vendor's invoice")
    notes.requests.append(AgentRequest("po_match"))
    return True


def _invalid_po(invoice: Invoice, ref: Reference, notes: _Notes) -> bool:
    """PO check 2: the PO is not on file, is closed, or belongs to another vendor. True stops the PO checks."""
    po = ref.purchase_orders.get(invoice.po_number)
    if po is None:
        problem = f"{invoice.po_number} is not on file"
    elif po["status"] == "closed":
        problem = f"{invoice.po_number} is closed"
    elif po["vendor_id"] != invoice.vendor_id:
        problem = f"{invoice.po_number} belongs to {po['vendor_id']}, not {invoice.vendor_id}"
    else:
        return False
    notes.findings.append("invalid_po")
    notes.facts.append(problem)
    notes.requests.append(AgentRequest("po_match"))
    return True


def _match_lines(invoice: Invoice, ref: Reference, notes: _Notes) -> list[tuple[InvoiceLine, dict[str, str]]]:
    """PO check 3: pair each invoice line with its PO line (same po_line and item). An unmatched line is missing_data."""
    matched = []
    for line in invoice.lines:
        po_line = ref.po_lines.get((invoice.po_number, line.po_line))
        if po_line is None or po_line["item"] != line.item:
            notes.findings.append("missing_data")
            notes.facts.append(f"line {line.line} does not match a line on {invoice.po_number}")
        else:
            matched.append((line, po_line))
    return matched


def _tolerance(invoice: Invoice, ref: Reference, matched: list[tuple[InvoiceLine, dict[str, str]]],
               notes: _Notes) -> None:
    """PO check 4: price and quantity variances on the matched lines, each tested on its own against the limit."""
    amount = _working_amount(invoice)
    limit = tolerance_limit(amount)
    notes.facts.append(f"tolerance limit {_money(limit)}: {_percent(TOLERANCE_RATE)} of {_money(amount)} "
                       f"is {_money(amount * TOLERANCE_RATE)}, cap {_money(TOLERANCE_CAP)}")
    totals = (("price_variance", _price_variance(matched, notes)),
              ("quantity_variance", _quantity_variance(invoice.po_number, ref, matched, notes)))
    for finding, total in totals:
        over = total > limit
        notes.facts.append(f"{finding.replace('_', ' ')} {_money(total)}: {'over' if over else 'within'} "
                           f"the limit {_money(limit)}")
        if over:
            notes.findings.append(finding)


def _price_variance(matched: list[tuple[InvoiceLine, dict[str, str]]], notes: _Notes) -> Decimal:
    """Σ |invoice price − PO price| × billed quantity, with one fact per line whose price differs."""
    total = Decimal("0")
    for line, po_line in matched:
        po_price = Decimal(po_line["unit_price"])
        if line.unit_price != po_price:
            value = abs(line.unit_price - po_price) * line.quantity
            total += value
            notes.facts.append(f"line {line.line} {line.item}: price {_money(line.unit_price)} vs PO "
                               f"{_money(po_price)} x {line.quantity} = {_money(value)}")
    return total


def _quantity_variance(po_number: str, ref: Reference, matched: list[tuple[InvoiceLine, dict[str, str]]],
                       notes: _Notes) -> Decimal:
    """Σ (billed − received to date, when positive) × PO price, with one fact per short line."""
    total = Decimal("0")
    for line, po_line in matched:
        received = ref.received.get((po_number, line.po_line), 0)
        short = line.quantity - received
        if short > 0:
            po_price = Decimal(po_line["unit_price"])
            value = short * po_price
            total += value
            notes.facts.append(f"line {line.line} {line.item}: billed {line.quantity}, received {received}, "
                               f"short {short} x PO price {_money(po_price)} = {_money(value)}")
    return total


def _non_po_checks(invoice: Invoice, ref: Reference, vendor: dict[str, str], notes: _Notes) -> None:
    """Non-PO path: the vendor's category picks the rule. Any approval reason adds approval_required."""
    category = vendor["category"]
    if not category:
        _no_category(notes)
    elif category == "utilities":
        _utilities(invoice, ref, notes)
    elif category == "rent":
        _rent(invoice, vendor, notes)
    elif category == "taxes":
        _taxes(notes)
    elif category == "subscriptions":
        _subscriptions(notes)
    elif category == "professional_services":
        _professional_services(invoice, notes)
    if notes.approval_reason:
        notes.findings.append("approval_required")


def _no_category(notes: _Notes) -> None:
    """Blank category: AP sets one; the agent suggests it. No other rule and no GL."""
    notes.findings.append("no_category")
    notes.facts.append("vendor has no category: AP sets one")
    notes.requests.append(AgentRequest("category_suggestion"))


def _utilities(invoice: Invoice, ref: Reference, notes: _Notes) -> None:
    """Bills 1-3 always need approval; from bill 4 on, compare with the average of up to 12 prior bills."""
    prior = sorted(ref.history.get(invoice.vendor_id, ()),
                   key=lambda bill: (bill["service_month"], bill["invoice_date"]))
    bill = len(prior) + 1
    if bill <= NEW_VENDOR_BILLS:
        notes.approval_reason = "utilities_first_3_bills"
        notes.facts.append(f"bill {bill} from this vendor: the first {NEW_VENDOR_BILLS} bills always need approval")
    else:
        baseline = prior[-BASELINE_BILLS:]
        average = (sum((Decimal(b["amount"]) for b in baseline), Decimal("0")) / len(baseline)).quantize(
            _CENT, rounding=ROUND_HALF_UP)
        amount = _working_amount(invoice)
        percent = ((amount - average) / average * 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        over = abs(amount - average) > average * UTILITY_VARIANCE_RATE
        if over:
            notes.approval_reason = "utilities_over_10pct"
        notes.facts.append(f"bill {bill}: average of the last {len(baseline)} bills is {_money(average)}; "
                           f"{_money(amount)} is {percent:+f}%, {'over' if over else 'within'} "
                           f"{_percent(UTILITY_VARIANCE_RATE)}")
    notes.requests.append(AgentRequest("content_check"))


def _rent(invoice: Invoice, vendor: dict[str, str], notes: _Notes) -> None:
    """Rent that differs from the lease, either way, needs approval and a content check."""
    lease = Decimal(vendor["lease_amount"])
    amount = _working_amount(invoice)
    difference = amount - lease
    notes.facts.append(f"lease {_money(lease)}, billed {_money(amount)}, difference {_money(difference)}")
    if difference:
        notes.approval_reason = "rent_differs"
        notes.requests.append(AgentRequest("content_check"))


def _taxes(notes: _Notes) -> None:
    """Taxes always need approval; no agent check."""
    notes.approval_reason = "taxes"
    notes.facts.append("taxes always need approval")


def _subscriptions(notes: _Notes) -> None:
    """Subscriptions always need approval; the agent checks the content."""
    notes.approval_reason = "subscriptions"
    notes.facts.append("subscriptions always need approval")
    notes.requests.append(AgentRequest("content_check"))


def _professional_services(invoice: Invoice, notes: _Notes) -> None:
    """Services need a requester: confirmation, then approval. With no requester, AP finds one first."""
    if not invoice.requester_id:
        notes.findings.append("no_requester")
        notes.facts.append("no requester on a professional services invoice: AP finds one")
        return
    notes.findings.append("confirmation_required")
    notes.approval_reason = "professional_services"
    notes.facts.append("professional services need a requester confirmation, then approval")
    notes.requests.append(AgentRequest("content_check"))


def _approver(invoice: Invoice, ref: Reference, vendor: dict[str, str], notes: _Notes) -> str:
    """The cost center owner; when the requester is that owner, the owner's manager (segregation of duties)."""
    cost_center = vendor["cost_center"]
    owner = ref.cost_centers[cost_center]["owner_id"]
    if invoice.requester_id == owner:
        manager = ref.people[owner]["reports_to"]
        if not manager:
            raise RuleDataError(f"{invoice.exception_id}: requester {owner} owns {cost_center} "
                                f"and has no manager to approve")
        notes.facts.append(f"approver {manager}: requester {owner} owns {cost_center}, "
                           f"so approval goes to their manager")
        return manager
    notes.facts.append(f"approver {owner}: owner of {cost_center}")
    return owner


def _gl_account(ref: Reference, vendor: dict[str, str], notes: _Notes) -> str:
    """The GL account mapped to the vendor's category."""
    account = ref.gl_by_category[vendor["category"]]
    notes.facts.append(f"GL {account} from category {vendor['category']}")
    return account


def assess(invoice: Invoice, ref: Reference) -> Assessment:
    """Run every code check on one invoice and list the agent checks it needs.

    assess() never adds possible_duplicate or category_mismatch; finalize() does,
    from the agent's verdicts.
    """
    vendor = _vendor(invoice, ref)
    notes = _Notes()
    exact_duplicate = _exact_duplicate(invoice, ref, notes)
    path = _path(invoice, vendor)
    approver_id = gl_account = ""
    if not exact_duplicate:
        _duplicate_candidates(invoice, ref, notes)
        _missing_data(invoice, vendor, notes)
        if path == "po":
            _po_checks(invoice, ref, notes)
        else:
            _non_po_checks(invoice, ref, vendor, notes)
            if "approval_required" in notes.findings:
                approver_id = _approver(invoice, ref, vendor, notes)
            if vendor["category"]:
                gl_account = _gl_account(ref, vendor, notes)
    requests = {}
    for request in notes.requests:
        requests.setdefault(request.kind, request)
    return Assessment(
        invoice=invoice,
        path=path,
        findings=tuple(finding for finding in FINDINGS if finding in notes.findings),
        approval_reason=notes.approval_reason,
        approver_id=approver_id,
        gl_account=gl_account,
        agent_requests=tuple(requests[kind] for kind in AGENT_REQUEST_KINDS if kind in requests),
        facts=tuple(notes.facts),
    )

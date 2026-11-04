"""Evidence check for the AP Invoice Copilot investigator's answer.

Code checks that every agent claim points to data the agent was shown in this
run. check_answer() returns the problems per task; an empty list means the
claim passed. fallback() gives the fixed answer for a task that still fails
after the last retry. No model runs in this module.
"""

import re
from decimal import Decimal

from ap_copilot.data import Invoice, Reference

TASKS = ("duplicate_check", "po_match", "price_variance_explanation",
         "quantity_variance_explanation", "content_check", "category_suggestion",
         "bill_change_explanation", "rent_difference_explanation")
EXPLANATION_FINDINGS = {"price_variance": "price_variance_explanation",
                        "quantity_variance": "quantity_variance_explanation"}
APPROVAL_EXPLANATIONS = {"utilities_over_10pct": "bill_change_explanation",
                         "utilities_first_3_bills": "bill_change_explanation",
                         "rent_differs": "rent_difference_explanation"}
CATEGORIES = ("inventory", "utilities", "rent", "taxes", "subscriptions", "professional_services")
FALLBACK_EXPLANATION = "No explanation passed the evidence check; see the figures from the rules."

MIN_WORDS = 5

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_in(text: str) -> set[Decimal]:
    """Every number in the text, commas removed: "5,352.00" equals 5352, and "008817" is 8817."""
    return {Decimal(match.replace(",", "")) for match in _NUMBER.findall(text)}


def invoice_ids(invoice: Invoice) -> set[str]:
    """The evidence IDs of the invoice itself and each of its lines."""
    return ({f"invoice:{invoice.exception_id}"}
            | {f"invoice_line:{invoice.exception_id}:{line.line}" for line in invoice.lines})


def _common_problems(claim: dict, cited: list, allowed: set[str], shown: set[Decimal]) -> list[str]:
    """Checks 1-3 for every claim: some evidence, every ID traceable, every number shown."""
    problems = []
    if not cited:
        problems.append("cites no evidence_id")
    problems += [f"{evidence_id} was not returned by any tool in this run"
                 for evidence_id in cited if evidence_id not in allowed]
    text = " ".join(str(claim.get(key, "")) for key in ("reason", "explanation"))
    problems += [f"the number {number} is not in any record you were shown"
                 for number in sorted(numbers_in(text)) if number not in shown]
    field = "reason" if "reason" in claim else "explanation"
    words = [word for word in text.split() if ":" not in word]
    if len(words) < MIN_WORDS:
        problems.append(f"write the {field} as a plain sentence of at least {MIN_WORDS} words, "
                        f"not an evidence ID")
    return problems


def _duplicate_problems(cited: list, invoice: Invoice, candidates: tuple[str, ...]) -> list[str]:
    """The verdict must cite every candidate the code sent."""
    return [f"cite posted:{invoice.vendor_id}:{number}, the posted invoice you compared"
            for number in candidates if f"posted:{invoice.vendor_id}:{number}" not in cited]


def _po_match_problems(claim: dict, cited: list, invoice: Invoice, ref: Reference) -> list[str]:
    """Rules a to f; only the first that fails is reported."""
    vendor_id = invoice.vendor_id
    po = str(claim.get("po_number", "")).strip()
    if po.lower() == "none":
        if f"open_pos:{vendor_id}" in cited:
            return []
        return [f"answer none only after searching: cite open_pos:{vendor_id}"]
    record = ref.purchase_orders.get(po)
    if record is None:
        return [f"{po or 'a blank PO number'} is not on file; give an open PO of {vendor_id} or none"]
    if record["status"] != "open":
        return [f"{po} is {record['status']}; give an open PO of {vendor_id} or none"]
    if record["vendor_id"] != vendor_id:
        return [f"{po} belongs to {record['vendor_id']}, not {vendor_id}"]
    items = {line.item for line in invoice.lines}
    matching = sorted(f"po_line:{po}:{line}" for (number, line), row in ref.po_lines.items()
                      if number == po and row["item"] in items)
    if not matching:
        return [f"none of {po}'s lines has an item on this invoice ({', '.join(sorted(items))}); "
                f"give an open PO of {vendor_id} with that item, or none"]
    if not set(matching) & set(cited):
        return [f"cite {', '.join(matching)}, the {po} line whose item is on the invoice"]
    return []


def _price_problems(cited: list, invoice: Invoice, ref: Reference) -> list[str]:
    """Must cite a PO line whose item matches an invoice line and whose price differs."""
    differing = set()
    for line in invoice.lines:
        row = ref.po_lines.get((invoice.po_number, line.po_line))
        if (row is not None and row["item"] == line.item and line.unit_price is not None
                and line.unit_price != Decimal(row["unit_price"])):
            differing.add(f"po_line:{invoice.po_number}:{line.po_line}")
    if differing & set(cited):
        return []
    return [f"cite the PO line whose price differs: {', '.join(sorted(differing))}"]


def _quantity_problems(cited: list, invoice: Invoice, ref: Reference) -> list[str]:
    """Must cite the receipts lookup on the invoice's PO, or one of its receipts."""
    po = invoice.po_number
    accepted = {f"receipts:{po}"} | {f"receipt:{row['receipt_id']}" for row in ref.receipts.get(po, ())}
    if accepted & set(cited):
        return []
    return [f"cite receipts:{po}, the receipts you looked up"]


def _line_problems(cited: list, invoice: Invoice, what: str) -> list[str]:
    """Must cite at least one line of this invoice."""
    lines = sorted(invoice_ids(invoice) - {f"invoice:{invoice.exception_id}"})
    if set(lines) & set(cited):
        return []
    return [f"cite {what}: {', '.join(lines)}"]


def _content_problems(claim: dict, cited: list, invoice: Invoice) -> list[str]:
    """A fit is a claim about every line, so it cites every line; a mismatch cites the line that doesn't fit."""
    if claim.get("mismatch"):
        return _line_problems(cited, invoice, "the invoice line that does not fit")
    missing = sorted(invoice_ids(invoice) - {f"invoice:{invoice.exception_id}"} - set(cited))
    if missing:
        return [f"cite every invoice line you checked: {', '.join(missing)}"]
    return []


def _category_problems(claim: dict, cited: list, invoice: Invoice) -> list[str]:
    """The suggestion must be a vendor category, based on the invoice's lines."""
    category = str(claim.get("category", "")).strip()
    if category not in CATEGORIES:
        return [f"{category or 'a blank category'} is not a vendor category; answer one of {', '.join(CATEGORIES)}"]
    return _line_problems(cited, invoice, "the invoice lines your suggestion is based on")


def _history_problems(cited: list, invoice: Invoice, ref: Reference, lease: bool) -> list[str]:
    """Must cite the vendor's bill history or one of its posted bills; a rent explanation may cite the
    vendor record, which holds the lease amount, instead."""
    vendor_id = invoice.vendor_id
    accepted = ({f"bill_history:{vendor_id}"}
                | {f"posted:{vendor_id}:{row['invoice_number']}" for row in ref.history.get(vendor_id, ())})
    if lease:
        accepted.add(f"vendor:{vendor_id}")
    if accepted & set(cited):
        return []
    if lease:
        return [f"cite vendor:{vendor_id}, the vendor record with the lease amount, or bill_history:{vendor_id}"]
    return [f"cite bill_history:{vendor_id}, the bill history you looked up"]


def check_answer(answer: dict | None, tasks: tuple[str, ...], invoice: Invoice, ref: Reference,
                 candidates: tuple[str, ...], seen: set[str], shown: set[Decimal]) -> dict[str, list[str]]:
    """Each task's problems: the common checks, then the task's own check. [] means passed."""
    allowed = set(seen) | invoice_ids(invoice)
    results = {}
    for task in tasks:
        claim = answer.get(task) if isinstance(answer, dict) else None
        if not isinstance(claim, dict):
            results[task] = ["missing from the answer"]
            continue
        cited = list(claim.get("evidence") or [])
        problems = _common_problems(claim, cited, allowed, shown)
        if task == "duplicate_check":
            problems += _duplicate_problems(cited, invoice, candidates)
        elif task == "po_match":
            problems += _po_match_problems(claim, cited, invoice, ref)
        elif task == "price_variance_explanation":
            problems += _price_problems(cited, invoice, ref)
        elif task == "quantity_variance_explanation":
            problems += _quantity_problems(cited, invoice, ref)
        elif task == "content_check":
            problems += _content_problems(claim, cited, invoice)
        elif task == "category_suggestion":
            problems += _category_problems(claim, cited, invoice)
        elif task == "bill_change_explanation":
            problems += _history_problems(cited, invoice, ref, lease=False)
        elif task == "rent_difference_explanation":
            problems += _history_problems(cited, invoice, ref, lease=True)
        results[task] = problems
    return results


def fallback(task: str) -> dict:
    """The fixed answer for a task that failed its last attempt."""
    if task == "duplicate_check":
        return {"likely_duplicate": True, "reason": "evidence check failed: AP reviews the candidate",
                "evidence": []}  # an unproven duplicate goes to AP review
    if task == "po_match":
        return {"po_number": "none", "reason": "evidence check failed: no PO suggested", "evidence": []}
    if task == "content_check":
        return {"mismatch": True, "reason": "evidence check failed: AP reviews the content",
                "evidence": []}  # an unproven fit goes to AP review
    if task == "category_suggestion":
        return {"category": "", "reason": "evidence check failed: no category suggested", "evidence": []}
    return {"explanation": FALLBACK_EXPLANATION, "evidence": []}

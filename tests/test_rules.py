"""Unit tests for the Phase 5 rules engine, on small made-up data.

Each test builds its own Reference and Invoice in code; no files are read.
They cover the rules with no case in the real data (tolerance boundaries,
utility bills 1-3, 4-12, and 13 on, an unmatched PO line) and the key
controls (segregation of duties, the duplicate-candidate rule, held actions,
verdict errors). The real data is covered by scripts/check_rules.py.

    .venv\\Scripts\\python.exe -m pytest tests -q
"""

from decimal import Decimal

import pytest

from ap_copilot.data import Invoice, InvoiceLine, Reference
from ap_copilot.routing import Verdicts, finalize
from ap_copilot.rules import assess, tolerance_limit


def person(person_id: str, role: str, reports_to: str) -> dict[str, str]:
    """A people.csv row."""
    return {"person_id": person_id, "name": f"Test Person {person_id}", "email": f"{person_id.lower()}@northgate.example",
            "title": role.title(), "department": "Operations", "role": role, "reports_to": reports_to}


PEOPLE = {row["person_id"]: row for row in (
    person("P-1", "manager", ""),     # the owner's manager; has no manager
    person("P-2", "manager", "P-1"),  # owns CC-1
    person("P-3", "staff", "P-2"),    # a requester who is not the owner
    person("P-4", "buyer", "P-1"),    # buyer on the test POs
)}
COST_CENTERS = {"CC-1": {"cost_center": "CC-1", "name": "Operations", "owner_id": "P-2"}}
GL_BY_CATEGORY = {"utilities": "6100", "rent": "6200", "taxes": "6300", "subscriptions": "6400",
                  "professional_services": "6500"}


def vendor(vendor_id: str, category: str) -> dict[str, str]:
    """A vendors.csv row on cost center CC-1."""
    return {"vendor_id": vendor_id, "vendor_name": f"Test Vendor {vendor_id}", "category": category,
            "cost_center": "CC-1", "contact_email": f"billing@{vendor_id.lower()}.example", "lease_amount": ""}


VENDORS = {row["vendor_id"]: row for row in (
    vendor("V-1", "inventory"),
    vendor("V-2", "utilities"),
    vendor("V-3", "taxes"),
    vendor("V-4", "professional_services"),
    vendor("V-5", "taxes"),           # a second vendor, for "same number at another vendor"
)}


def po(po_number: str, vendor_id: str = "V-1", status: str = "open") -> dict[str, str]:
    """A purchase_orders.csv row, buyer P-4."""
    return {"po_number": po_number, "vendor_id": vendor_id, "buyer_id": "P-4", "po_date": "2026-10-01",
            "status": status}


def po_line(po_number: str, line: str, quantity: int, unit_price: str, item: str = "ITM-1") -> dict[str, str]:
    """A po_lines.csv row; values are text, as in the CSV."""
    return {"po_number": po_number, "line": line, "item": item, "description": "Test item",
            "qty_ordered": str(quantity), "unit_price": unit_price}


def posted(vendor_id: str, invoice_number: str, amount: str, invoice_date: str = "2026-09-01",
           service_month: str = "", po_number: str = "") -> dict[str, str]:
    """An invoice_history.csv row."""
    return {"vendor_id": vendor_id, "invoice_number": invoice_number, "invoice_date": invoice_date,
            "service_month": service_month, "po_number": po_number, "amount": amount}


def make_reference(purchase_orders=(), po_lines=(), received=None, history=()) -> Reference:
    """A Reference shaped like load_reference()'s, from rows given in code."""
    by_vendor = {}
    for row in history:
        by_vendor.setdefault(row["vendor_id"], []).append(row)
    return Reference(
        people=PEOPLE,
        cost_centers=COST_CENTERS,
        gl_by_category=GL_BY_CATEGORY,
        vendors=VENDORS,
        purchase_orders={row["po_number"]: row for row in purchase_orders},
        po_lines={(row["po_number"], row["line"]): row for row in po_lines},
        received=received or {},
        history={vendor_id: tuple(rows) for vendor_id, rows in by_vendor.items()},
    )


def line(po_line: str, quantity: int, unit_price: str, item: str = "ITM-1") -> InvoiceLine:
    """Invoice line 1; line_amount = quantity × unit price."""
    return InvoiceLine(line=1, po_line=po_line, item=item, description="Test item", quantity=quantity,
                       unit_price=Decimal(unit_price), line_amount=quantity * Decimal(unit_price))


def make_invoice(vendor_id: str, amount: str, number: str = "N-1", invoice_date: str = "2026-11-10",
                 po_number: str = "", service_month: str = "2026-10", requester_id: str = "",
                 lines=None) -> Invoice:
    """An Invoice; by default one charge line equal to the header amount, so the totals agree."""
    if lines is None:
        lines = [InvoiceLine(line=1, po_line="", item="", description="Charges", quantity=None, unit_price=None,
                             line_amount=Decimal(amount))]
    return Invoice(exception_id="EX-900", hold_code="", vendor_id=vendor_id, vendor_name=f"Test Vendor {vendor_id}",
                   invoice_number=number, invoice_date=invoice_date, po_number=po_number,
                   service_month=service_month, requester_id=requester_id, amount=Decimal(amount),
                   lines=tuple(lines))


def assess_po_invoice(po_quantity: int, po_price: str, received: int, quantity: int, price: str,
                      amount: str):
    """Assess a V-1 invoice on open PO-1 with one line against PO line 1."""
    ref = make_reference(purchase_orders=[po("PO-1")], po_lines=[po_line("PO-1", "1", po_quantity, po_price)],
                         received={("PO-1", "1"): received})
    return assess(make_invoice("V-1", amount, po_number="PO-1", lines=[line("1", quantity, price)]), ref)


def utility_bill(prior_amounts: list[str], amount: str):
    """Assess a V-2 utility bill after the given posted bills (oldest first, one month apart)."""
    history = [posted("V-2", f"U-{n + 1}", prior, service_month=f"{2025 + n // 12}-{n % 12 + 1:02d}")
               for n, prior in enumerate(prior_amounts)]
    return assess(make_invoice("V-2", amount, number="U-NEW"), make_reference(history=history))


def requests(assessment) -> dict[str, tuple[str, ...]]:
    """The agent requests as {kind: detail}."""
    return {request.kind: request.detail for request in assessment.agent_requests}


def test_tolerance_limit():
    assert tolerance_limit(Decimal("4000.00")) == Decimal("80.00")
    assert tolerance_limit(Decimal("5000.00")) == Decimal("100.00")
    assert tolerance_limit(Decimal("9201.00")) == Decimal("100.00")


def test_price_variance_at_limit_is_within():
    assessment = assess_po_invoice(1, "5000.00", 1, 1, "5100.00", "5100.00")
    assert "price_variance" not in assessment.findings
    assert "price variance 100.00: within the limit 100.00" in assessment.facts


def test_price_variance_one_cent_over_holds():
    assessment = assess_po_invoice(1, "5000.00", 1, 1, "5100.01", "5100.01")
    assert "price_variance" in assessment.findings


def test_quantity_variance_valued_at_po_price():
    assessment = assess_po_invoice(50, "10.00", 40, 50, "10.20", "510.00")
    assert assessment.findings == ("quantity_variance",)
    assert "quantity variance 100.00: over the limit 10.20" in assessment.facts
    assert "price variance 10.00: within the limit 10.20" in assessment.facts


def test_unmatched_po_line_is_missing_data():
    ref = make_reference(purchase_orders=[po("PO-1")], po_lines=[po_line("PO-1", "1", 10, "10.00")])
    assessment = assess(make_invoice("V-1", "100.00", po_number="PO-1", lines=[line("9", 10, "10.00")]), ref)
    assert "missing_data" in assessment.findings
    assert "line 1 does not match a line on PO-1" in assessment.facts


def test_utilities_first_three_bills():
    for count in (0, 1, 2):
        assert utility_bill(["100.00"] * count, "5000.00").approval_reason == "utilities_first_3_bills"


def test_utilities_bills_4_to_12_use_prior_average():
    prior = ["100.00", "110.00", "120.00"]
    assert utility_bill(prior, "121.00").approval_reason == ""
    assert utility_bill(prior, "121.01").approval_reason == "utilities_over_10pct"
    assert utility_bill(prior, "99.00").approval_reason == ""
    assert utility_bill(prior, "98.99").approval_reason == "utilities_over_10pct"


def test_utilities_bill_13_on_uses_last_12():
    prior = ["500.00"] + ["100.00"] * 12
    assert utility_bill(prior, "109.00").approval_reason == ""
    assessment = utility_bill(prior, "111.00")
    assert assessment.approval_reason == "utilities_over_10pct"
    assert any("average of the last 12 bills is 100.00" in fact for fact in assessment.facts)


def test_requester_owns_cost_center_goes_to_manager():
    assessment = assess(make_invoice("V-4", "1200.00", requester_id="P-2"), make_reference())
    assert assessment.approver_id == "P-1"


def test_requester_not_owner_goes_to_owner():
    assessment = assess(make_invoice("V-4", "1200.00", requester_id="P-3"), make_reference())
    assert assessment.approver_id == "P-2"


def test_normalized_number_is_duplicate_candidate():
    history = [posted("V-3", "INV-00123", "900.00", invoice_date="2026-09-01")]
    invoice = make_invoice("V-3", "50.00", number="inv 123", invoice_date="2026-11-10")
    assessment = assess(invoice, make_reference(history=history))
    assert requests(assessment) == {"duplicate_check": ("INV-00123",)}
    assert "exact_duplicate" not in assessment.findings
    other_vendor = [posted("V-5", "INV-00123", "900.00", invoice_date="2026-09-01")]
    assert requests(assess(invoice, make_reference(history=other_vendor))) == {}


def test_same_po_is_candidate_but_date_and_amount_are_not():
    ref = make_reference(purchase_orders=[po("PO-1")], po_lines=[po_line("PO-1", "1", 1, "50.00")],
                         received={("PO-1", "1"): 1},
                         history=[posted("V-1", "S-1", "900.00", invoice_date="2026-09-01", po_number="PO-1")])
    assessment = assess(make_invoice("V-1", "50.00", number="S-2", po_number="PO-1",
                                     lines=[line("1", 1, "50.00")]), ref)
    assert requests(assessment)["duplicate_check"] == ("S-1",)
    assert "duplicate candidate: posted S-1 (2026-09-01, 900.00): same PO PO-1" in assessment.facts
    history = [posted("V-3", "T-1", "70.00", invoice_date="2026-11-01")]
    same_date_and_amount = make_invoice("V-3", "70.00", number="T-2", invoice_date="2026-11-01")
    assert requests(assess(same_date_and_amount, make_reference(history=history))) == {}


def test_exact_duplicate_stops_other_checks():
    ref = make_reference(history=[posted("V-2", "U-7", "80.00", service_month="2026-09")])
    assessment = assess(make_invoice("V-2", "95.00", number="U-7", service_month=""), ref)
    assert assessment.findings == ("exact_duplicate",)
    assert assessment.agent_requests == ()
    assert assessment.gl_account == ""


def test_possible_duplicate_holds_non_ap_actions():
    ref = make_reference(history=[posted("V-3", "T-001", "70.00")])
    assessment = assess(make_invoice("V-3", "70.00", number="T-1"), ref)
    outcome = finalize(assessment, ref, Verdicts(duplicate=True))
    actions = {action.role: action for action in outcome.actions}
    assert "possible_duplicate" in outcome.findings
    assert actions["approver"].status == "held"
    assert actions["ap_queue"].status == "queue"
    assert actions["ap_queue"].findings == ("possible_duplicate",)


def test_missing_or_unrequested_verdict_raises():
    ref = make_reference(history=[posted("V-3", "T-001", "70.00")])
    with pytest.raises(ValueError, match="duplicate_check"):
        finalize(assess(make_invoice("V-3", "70.00", number="T-1"), ref), ref, Verdicts())
    with pytest.raises(ValueError, match="duplicate_check"):
        finalize(assess(make_invoice("V-3", "70.00", number="T-2"), ref), ref, Verdicts(duplicate=False))


def test_no_requester_has_no_approval():
    assessment = assess(make_invoice("V-4", "1200.00"), make_reference())
    assert assessment.findings == ("no_requester",)
    assert assessment.approval_reason == ""
    assert assessment.approver_id == ""
    assert assessment.gl_account == "6500"

"""Consistency checker for the AP Invoice Copilot reference data.

Reads every CSV in data/reference/ and prints one PASS or FAIL line per
check, then row counts, vendor counts by category, and the trailing
12-month average for each established utility vendor.

Standard library only. Runs from any working directory:

    .venv\\Scripts\\python.exe scripts\\check_data.py
"""

import csv
import sys
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"

HISTORY_CUTOFF = date(2026, 10, 31)

ROLES = {"manager", "buyer", "staff", "ap"}
NON_PO_CATEGORIES = ("utilities", "rent", "taxes", "subscriptions", "professional_services")
VENDOR_CATEGORIES = {"inventory", "", *NON_PO_CATEGORIES}
PO_STATUSES = {"open", "closed"}
ACCOUNT_TYPES = {"asset", "liability", "expense"}

HEADERS = {
    "people.csv": ["person_id", "name", "email", "title", "department", "role", "reports_to"],
    "cost_centers.csv": ["cost_center", "name", "owner_id"],
    "gl_accounts.csv": ["gl_account", "name", "account_type", "category"],
    "vendors.csv": ["vendor_id", "vendor_name", "category", "cost_center", "contact_email", "lease_amount"],
    "purchase_orders.csv": ["po_number", "vendor_id", "buyer_id", "po_date", "status"],
    "po_lines.csv": ["po_number", "line", "item", "description", "qty_ordered", "unit_price"],
    "receipts.csv": ["receipt_id", "po_number", "line", "receipt_date", "qty_received"],
    "invoice_history.csv": ["vendor_id", "invoice_number", "invoice_date", "service_month", "po_number", "amount"],
}


class Report:
    """Collects failures per check so every problem is reported, not just the first."""

    def __init__(self):
        self.checks = []

    def start(self, name):
        self.checks.append([name, []])

    def fail(self, file, row=None, column=None, value=None, reason=""):
        where = file
        if row is not None:
            where += f", row {row}"
        if column is not None:
            where += f", {column}={value if value else '(blank)'}"
        self.checks[-1][1].append(f"{where} — {reason}")

    def print_results(self):
        failed = 0
        for name, problems in self.checks:
            if problems:
                failed += 1
                for problem in problems:
                    print(f"FAIL {name}: {problem}")
            else:
                print(f"PASS {name}")
        return failed


def money(text):
    """Return the Decimal value if text is an exact two-place decimal above zero, else None."""
    whole, dot, fraction = text.partition(".")
    if not dot or not whole.isdigit() or len(fraction) != 2 or not fraction.isdigit():
        return None
    value = Decimal(text)
    return value if value > 0 else None


def whole_number(text):
    """Return the int if text is a whole number above zero, else None."""
    return int(text) if text.isdigit() and int(text) > 0 else None


def parse_date(text):
    """Return the date if text is YYYY-MM-DD, else None."""
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def month_index(text):
    """Return a sortable month number if text is YYYY-MM, else None."""
    try:
        when = datetime.strptime(text, "%Y-%m")
    except ValueError:
        return None
    return when.year * 12 + when.month


def load_all(report):
    """Check 1: files exist, have no BOM, and carry the expected header. Returns the rows."""
    report.start("files and headers")
    tables = {}
    for name, header in HEADERS.items():
        path = REF / name
        if not path.exists():
            report.fail(name, reason="file not found")
            tables[name] = []
            continue
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            report.fail(name, reason="file starts with a UTF-8 BOM")
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != header:
                report.fail(name, reason=f"header is {reader.fieldnames}, expected {header}")
                tables[name] = []
                continue
            rows = []
            for line_number, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    report.fail(name, row=line_number,
                                reason=f"wrong number of fields, expected {len(header)}")
                    continue
                row["_row"] = line_number
                rows.append(row)
            tables[name] = rows
    return tables


def check_unique_ids(tables, report):
    report.start("unique ids")
    keys = (
        ("people.csv", ("person_id",)),
        ("cost_centers.csv", ("cost_center",)),
        ("gl_accounts.csv", ("gl_account",)),
        ("vendors.csv", ("vendor_id",)),
        ("purchase_orders.csv", ("po_number",)),
        ("po_lines.csv", ("po_number", "line")),
        ("receipts.csv", ("receipt_id",)),
        ("invoice_history.csv", ("vendor_id", "invoice_number")),
    )
    for name, columns in keys:
        seen = {}
        for row in tables[name]:
            key = tuple(row[column] for column in columns)
            if key in seen:
                report.fail(name, row["_row"], "+".join(columns), " ".join(key),
                            f"duplicate of row {seen[key]}")
            else:
                seen[key] = row["_row"]


def check_links(tables, report):
    report.start("links resolve")
    people = {row["person_id"] for row in tables["people.csv"]}
    centers = {row["cost_center"] for row in tables["cost_centers.csv"]}
    vendors = {row["vendor_id"] for row in tables["vendors.csv"]}
    orders = {row["po_number"] for row in tables["purchase_orders.csv"]}
    lines = {(row["po_number"], row["line"]) for row in tables["po_lines.csv"]}

    def link(name, column, targets, label, required=True):
        for row in tables[name]:
            value = row[column]
            if not value:
                if required:
                    report.fail(name, row["_row"], column, value, f"blank {label} reference")
            elif value not in targets:
                report.fail(name, row["_row"], column, value, f"no such {label}")

    link("cost_centers.csv", "owner_id", people, "person")
    link("people.csv", "reports_to", people, "person", required=False)
    link("vendors.csv", "cost_center", centers, "cost center", required=False)
    link("purchase_orders.csv", "vendor_id", vendors, "vendor")
    link("purchase_orders.csv", "buyer_id", people, "person")
    link("po_lines.csv", "po_number", orders, "purchase order")
    link("invoice_history.csv", "vendor_id", vendors, "vendor")
    link("invoice_history.csv", "po_number", orders, "purchase order", required=False)

    for row in tables["receipts.csv"]:
        if (row["po_number"], row["line"]) not in lines:
            report.fail("receipts.csv", row["_row"], "po_number+line",
                        f"{row['po_number']} {row['line']}", "no such PO line")


def check_chain(tables, report):
    report.start("reporting chain")
    people = tables["people.csv"]
    manager = {row["person_id"]: row["reports_to"] for row in people}
    tops = [row for row in people if not row["reports_to"]]
    if len(tops) > 1:
        for row in tops:
            report.fail("people.csv", row["_row"], "reports_to", "",
                        f"{len(tops)} people have a blank reports_to; expected exactly 1")
    elif not tops and people:
        report.fail("people.csv", reason="no person has a blank reports_to; expected exactly 1")
    top = tops[0]["person_id"] if len(tops) == 1 else None

    for person in people:
        walked = []
        current = person["person_id"]
        while current and current not in walked:
            walked.append(current)
            current = manager.get(current, "")
        if current:
            report.fail("people.csv", person["_row"], "person_id", person["person_id"],
                        "reporting loop: " + " -> ".join(walked + [current]))
        elif top is not None and walked[-1] != top:
            report.fail("people.csv", person["_row"], "person_id", person["person_id"],
                        f"chain ends at {walked[-1]}, not {top}")


def check_allowed_values(tables, report):
    report.start("allowed values")
    for row in tables["people.csv"]:
        if row["role"] not in ROLES:
            report.fail("people.csv", row["_row"], "role", row["role"],
                        f"not one of {sorted(ROLES)}")
    for row in tables["vendors.csv"]:
        if row["category"] not in VENDOR_CATEGORIES:
            report.fail("vendors.csv", row["_row"], "category", row["category"],
                        "not an allowed vendor category")
    for row in tables["purchase_orders.csv"]:
        if row["status"] not in PO_STATUSES:
            report.fail("purchase_orders.csv", row["_row"], "status", row["status"],
                        f"not one of {sorted(PO_STATUSES)}")
    for row in tables["gl_accounts.csv"]:
        if row["account_type"] not in ACCOUNT_TYPES:
            report.fail("gl_accounts.csv", row["_row"], "account_type", row["account_type"],
                        f"not one of {sorted(ACCOUNT_TYPES)}")
        if row["category"] not in ("", *NON_PO_CATEGORIES):
            report.fail("gl_accounts.csv", row["_row"], "category", row["category"],
                        "not a non-PO category or blank")


def check_vendor_rules(tables, report):
    report.start("vendor rules")
    blanks = []
    for row in tables["vendors.csv"]:
        category, center, lease = row["category"], row["cost_center"], row["lease_amount"]
        if category in NON_PO_CATEGORIES and not center:
            report.fail("vendors.csv", row["_row"], "cost_center", center,
                        f"a {category} vendor must have a cost center")
        if category in ("inventory", "") and center:
            report.fail("vendors.csv", row["_row"], "cost_center", center,
                        f"a {category or 'blank-category'} vendor must not have a cost center")
        if category == "rent" and not lease:
            report.fail("vendors.csv", row["_row"], "lease_amount", lease,
                        "a rent vendor must have a lease_amount")
        if category != "rent" and lease:
            report.fail("vendors.csv", row["_row"], "lease_amount", lease,
                        f"only rent vendors have a lease_amount, not {category or 'blank-category'}")
        if not category:
            blanks.append(row)
    if len(blanks) != 1:
        report.fail("vendors.csv", column="category", value="",
                    reason=f"{len(blanks)} vendors have a blank category; expected exactly 1")


def check_po_rules(tables, report):
    report.start("po rules")
    category = {row["vendor_id"]: row["category"] for row in tables["vendors.csv"]}
    role = {row["person_id"]: row["role"] for row in tables["people.csv"]}
    for row in tables["purchase_orders.csv"]:
        if category.get(row["vendor_id"]) != "inventory":
            report.fail("purchase_orders.csv", row["_row"], "vendor_id", row["vendor_id"],
                        f"vendor category is {category.get(row['vendor_id'], 'unknown') or 'blank'}, expected inventory")
        if role.get(row["buyer_id"]) != "buyer":
            report.fail("purchase_orders.csv", row["_row"], "buyer_id", row["buyer_id"],
                        f"role is {role.get(row['buyer_id'], 'unknown')}, expected buyer")


def check_gl_mapping(tables, report):
    report.start("gl mapping")
    for category in NON_PO_CATEGORIES:
        matches = [row for row in tables["gl_accounts.csv"] if row["category"] == category]
        if len(matches) == 0:
            report.fail("gl_accounts.csv", column="category", value=category,
                        reason="no GL account maps to this category")
        elif len(matches) > 1:
            for row in matches:
                report.fail("gl_accounts.csv", row["_row"], "category", category,
                            f"{len(matches)} GL accounts map to this category; expected 1")


def check_numbers(tables, report):
    report.start("number formats")
    money_columns = (
        ("vendors.csv", "lease_amount", False),
        ("po_lines.csv", "unit_price", True),
        ("invoice_history.csv", "amount", True),
    )
    for name, column, required in money_columns:
        for row in tables[name]:
            text = row[column]
            if not text:
                if required:
                    report.fail(name, row["_row"], column, text, "is blank")
            elif money(text) is None:
                report.fail(name, row["_row"], column, text,
                            "not an exact two-place decimal above zero")
    for name, column in (("po_lines.csv", "line"), ("po_lines.csv", "qty_ordered"),
                         ("receipts.csv", "line"), ("receipts.csv", "qty_received")):
        for row in tables[name]:
            if whole_number(row[column]) is None:
                report.fail(name, row["_row"], column, row[column],
                            "not a whole number above zero")


def check_receipts(tables, report):
    report.start("receipts")
    po_date = {}
    for row in tables["purchase_orders.csv"]:
        when = parse_date(row["po_date"])
        if when is None:
            report.fail("purchase_orders.csv", row["_row"], "po_date", row["po_date"],
                        "not a YYYY-MM-DD date")
        else:
            po_date[row["po_number"]] = when
    ordered = {(row["po_number"], row["line"]): row for row in tables["po_lines.csv"]}
    received = {}
    for row in tables["receipts.csv"]:
        when = parse_date(row["receipt_date"])
        if when is None:
            report.fail("receipts.csv", row["_row"], "receipt_date", row["receipt_date"],
                        "not a YYYY-MM-DD date")
        elif row["po_number"] in po_date and when < po_date[row["po_number"]]:
            report.fail("receipts.csv", row["_row"], "receipt_date", row["receipt_date"],
                        f"before the PO date {po_date[row['po_number']]}")
        key = (row["po_number"], row["line"])
        total, _ = received.get(key, (0, 0))
        received[key] = (total + (whole_number(row["qty_received"]) or 0), row["_row"])

    for key, (total, last_row) in received.items():
        line = ordered.get(key)
        if line is None:
            continue
        limit = whole_number(line["qty_ordered"])
        if limit is not None and total > limit:
            report.fail("receipts.csv", last_row, "qty_received", total,
                        f"{key[0]} line {key[1]} received {total} of {limit} ordered")


def check_history(tables, report):
    report.start("invoice history")
    orders = {row["po_number"]: row for row in tables["purchase_orders.csv"]}
    for row in tables["invoice_history.csv"]:
        when = parse_date(row["invoice_date"])
        if when is None:
            report.fail("invoice_history.csv", row["_row"], "invoice_date", row["invoice_date"],
                        "not a YYYY-MM-DD date")
        elif when > HISTORY_CUTOFF:
            report.fail("invoice_history.csv", row["_row"], "invoice_date", row["invoice_date"],
                        f"after the history cut-off {HISTORY_CUTOFF}")
        if not row["po_number"]:
            continue
        order = orders.get(row["po_number"])
        if order is None:
            continue
        if order["status"] != "closed":
            report.fail("invoice_history.csv", row["_row"], "po_number", row["po_number"],
                        f"PO status is {order['status']}; history holds invoices for closed POs only")
        if order["vendor_id"] != row["vendor_id"]:
            report.fail("invoice_history.csv", row["_row"], "vendor_id", row["vendor_id"],
                        f"{row['po_number']} belongs to vendor {order['vendor_id']}")


def check_utility_history(tables, report):
    report.start("utility history")
    bills = {}
    for row in tables["invoice_history.csv"]:
        bills.setdefault(row["vendor_id"], []).append(row)
    for vendor in [row for row in tables["vendors.csv"] if row["category"] == "utilities"]:
        rows = bills.get(vendor["vendor_id"], [])
        months, seen = [], {}
        for row in rows:
            index = month_index(row["service_month"])
            if index is None:
                report.fail("invoice_history.csv", row["_row"], "service_month",
                            row["service_month"], "not a YYYY-MM month")
            elif index in seen:
                report.fail("invoice_history.csv", row["_row"], "service_month",
                            row["service_month"], f"repeats row {seen[index]}")
            else:
                seen[index] = row["_row"]
                months.append(index)
        if len(rows) <= 2:
            continue
        if len(months) < 12:
            report.fail("invoice_history.csv", column="vendor_id", value=vendor["vendor_id"],
                        reason=f"{len(rows)} bills; a utilities vendor needs 12 or more months, or 2 or fewer bills")
        elif max(months) - min(months) + 1 != len(months):
            report.fail("invoice_history.csv", column="vendor_id", value=vendor["vendor_id"],
                        reason="service months are not consecutive")


def check_emails(tables, report):
    report.start("emails")
    for name, column in (("people.csv", "email"), ("vendors.csv", "contact_email")):
        for row in tables[name]:
            if not row[column].endswith(".example"):
                report.fail(name, row["_row"], column, row[column], "does not end in .example")


def print_summary(tables):
    print()
    print("row counts")
    for name in HEADERS:
        print(f"  {name:<22}{len(tables[name]):>4}")

    print()
    print("vendors by category")
    for category in ("inventory", *NON_PO_CATEGORIES):
        matches = [row for row in tables["vendors.csv"] if row["category"] == category]
        print(f"  {category:<22}{len(matches):>4}")
    blanks = [row for row in tables["vendors.csv"] if not row["category"]]
    names = ", ".join(row["vendor_name"] for row in blanks)
    print(f"  {'blank':<22}{len(blanks):>4}" + (f"  {names}" if names else ""))

    print()
    for vendor in [row for row in tables["vendors.csv"] if row["category"] == "utilities"]:
        rows = sorted((row for row in tables["invoice_history.csv"]
                       if row["vendor_id"] == vendor["vendor_id"]),
                      key=lambda row: row["service_month"])
        if len(rows) < 12:
            continue
        total = sum((Decimal(row["amount"]) for row in rows[-12:]), Decimal("0"))
        average = (total / 12).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        print(f"trailing 12-month average {vendor['vendor_id']} {vendor['vendor_name']}: {average}")


def main():
    report = Report()
    tables = load_all(report)
    check_unique_ids(tables, report)
    check_links(tables, report)
    check_chain(tables, report)
    check_allowed_values(tables, report)
    check_vendor_rules(tables, report)
    check_po_rules(tables, report)
    check_gl_mapping(tables, report)
    check_numbers(tables, report)
    check_receipts(tables, report)
    check_history(tables, report)
    check_utility_history(tables, report)
    check_emails(tables, report)

    failed = report.print_results()
    print_summary(tables)
    print()
    if failed:
        print(f"{failed} check{'s' if failed != 1 else ''} failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

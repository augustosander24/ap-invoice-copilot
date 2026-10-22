"""Consistency checker for the AP Invoice Copilot data.

Reads the reference CSVs in data/reference/, the exception list and mock
inbox in data/input/, and the expected results in evals/. Prints one PASS
or FAIL line per check, then row counts, vendor counts by category, the
trailing 12-month average for each established utility vendor, input row
counts, and the demo calendar.

Standard library plus openpyxl. Runs from any working directory:

    .venv\\Scripts\\python.exe scripts\\check_data.py
"""

import csv
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"
INPUT = ROOT / "data" / "input"
EVALS = ROOT / "evals"

HISTORY_CUTOFF = date(2026, 10, 31)
DAY0 = date(2026, 11, 30)
# Demo days 0-5: business dates from DAY0 on, skipping Saturdays and Sundays (no holiday list).
# Ten calendar days always hold six business days.
DAYS = [when for when in (DAY0 + timedelta(days=offset) for offset in range(10))
        if when.weekday() < 5][:6]

ROLES = {"manager", "buyer", "staff", "ap"}
NON_PO_CATEGORIES = ("utilities", "rent", "taxes", "subscriptions", "professional_services")
VENDOR_CATEGORIES = {"inventory", "", *NON_PO_CATEGORIES}
PO_STATUSES = {"open", "closed"}
ACCOUNT_TYPES = {"asset", "liability", "expense"}
HOLD_CODES = ("price", "quantity", "po", "duplicate", "non_po")
FINDINGS = ("price_variance", "quantity_variance", "missing_po", "invalid_po", "exact_duplicate",
            "possible_duplicate", "missing_data", "approval_required", "confirmation_required",
            "no_requester", "no_category", "category_mismatch")
AP_QUEUE_FINDINGS = ("possible_duplicate", "category_mismatch", "no_requester", "no_category")
APPROVAL_REASONS = ("utilities_over_10pct", "utilities_first_3_bills", "rent_differs", "taxes",
                    "subscriptions", "professional_services")
LOOKUP_KINDS = ("po", "receipts", "open_pos", "similar_invoices", "bill_history", "vendor")
RECIPIENT_ROLES = ("buyer", "vendor", "approver", "requester")
REPLY_LABELS = ("approved", "rejected", "correction_coming", "question", "redirected", "unclear")
SERVICE_MONTH_REQUIRED = ("utilities", "rent", "taxes", "subscriptions")
VENDOR_REMINDER_CC = "P-104"    # AP Team
VENDOR_ESCALATION_TO = "P-103"  # AP Manager, who becomes the action owner

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

ID_COLUMNS = {
    "people.csv": ("person_id",),
    "cost_centers.csv": ("cost_center",),
    "gl_accounts.csv": ("gl_account",),
    "vendors.csv": ("vendor_id",),
    "purchase_orders.csv": ("po_number",),
    "po_lines.csv": ("po_number", "line"),
    "receipts.csv": ("receipt_id",),
    "invoice_history.csv": ("vendor_id", "invoice_number"),
}

WORKBOOK = "exception_list.xlsx"
SHEETS = ("invoices", "lines")
INVOICES, LINES = (f"{WORKBOOK}[{sheet}]" for sheet in SHEETS)

INPUT_HEADERS = {
    INVOICES: ["exception_id", "hold_code", "vendor_id", "vendor_name", "invoice_number", "invoice_date",
               "po_number", "service_month", "requester_id", "amount"],
    LINES: ["exception_id", "line", "po_line", "item", "description", "quantity", "unit_price", "line_amount"],
    "inbox.csv": ["message_id", "received_date", "from_email", "vendor_id", "invoice_number", "body"],
    "expected_outcomes.csv": ["exception_id", "scenario", "expected_result", "path", "findings",
                              "approval_reason", "approver_id", "gl_account", "day0_recommendation",
                              "first_tool", "duplicate_verdict", "po_match", "mismatch_flag",
                              "category_suggestion"],
    "expected_threads.csv": ["exception_id", "recipient_id", "recipient_role", "opens_on_day", "findings",
                             "reply_message_id", "reply_label", "reply_detail", "day4_action", "day4_cc",
                             "day5_action", "day5_to"],
}

INPUT_ID_COLUMNS = {
    INVOICES: ("exception_id",),
    LINES: ("exception_id", "line"),
    "inbox.csv": ("message_id",),
    "expected_outcomes.csv": ("exception_id",),
    "expected_threads.csv": ("exception_id", "recipient_id"),
}


class Report:
    """Collects failures per check so every problem is reported, not just the first."""

    def __init__(self):
        self.checks = []

    def start(self, name):
        self.checks.append([name, []])

    def fail(self, file, row=None, column=None, value=None, reason=""):
        """row is a loaded row (prints its line number and record ID) or a plain line number."""
        where = file
        if isinstance(row, dict):
            columns = ID_COLUMNS[file] if file in ID_COLUMNS else INPUT_ID_COLUMNS[file]
            where += f", row {row['_row']} ({'+'.join(columns)}={row['_id']})"
        elif row is not None:
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


def is_code(text, prefix, digits):
    """True if text is the prefix followed by exactly `digits` digits, such as EX-001."""
    number = text[len(prefix):]
    return text.startswith(prefix) and len(number) == digits and number.isdigit()


def finding_list(text):
    """The findings in text as a list ([] for "none"), or None if any is unknown, repeated, or out of order."""
    if text == "none":
        return []
    found = text.split(";")
    if any(finding not in FINDINGS for finding in found) or found != sorted(set(found), key=FINDINGS.index):
        return None
    return found


def read_csv(path, name, header, id_columns, report):
    """Read one CSV: it must exist, have no BOM, and carry the exact header. Returns its rows."""
    if not path.exists():
        report.fail(name, reason="file not found")
        return []
    if path.read_bytes().startswith(b"\xef\xbb\xbf"):
        report.fail(name, reason="file starts with a UTF-8 BOM")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != header:
            report.fail(name, reason=f"header is {reader.fieldnames}, expected {header}")
            return []
        rows = []
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                report.fail(name, row=line_number,
                            reason=f"wrong number of fields, expected {len(header)}")
                continue
            row["_row"] = line_number
            row["_id"] = " ".join(row[column] for column in id_columns)
            rows.append(row)
    return rows


def load_all(report):
    """Check 1: files exist, have no BOM, and carry the expected header. Returns the rows."""
    report.start("files and headers")
    return {name: read_csv(REF / name, name, header, ID_COLUMNS[name], report)
            for name, header in HEADERS.items()}


def check_unique_ids(tables, report):
    report.start("unique ids")
    for name, columns in ID_COLUMNS.items():
        seen = {}
        for row in tables[name]:
            key = tuple(row[column] for column in columns)
            if key in seen:
                report.fail(name, row, "+".join(columns), " ".join(key),
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
                    report.fail(name, row, column, value, f"blank {label} reference")
            elif value not in targets:
                report.fail(name, row, column, value, f"no such {label}")

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
            report.fail("receipts.csv", row, "po_number+line",
                        f"{row['po_number']} {row['line']}", "no such PO line")


def check_chain(tables, report):
    report.start("reporting chain")
    people = tables["people.csv"]
    manager = {row["person_id"]: row["reports_to"] for row in people}
    tops = [row for row in people if not row["reports_to"]]
    if len(tops) > 1:
        for row in tops:
            report.fail("people.csv", row, "reports_to", "",
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
            report.fail("people.csv", person, "person_id", person["person_id"],
                        "reporting loop: " + " -> ".join(walked + [current]))
        elif top is not None and walked[-1] != top:
            report.fail("people.csv", person, "person_id", person["person_id"],
                        f"chain ends at {walked[-1]}, not {top}")


def check_allowed_values(tables, report):
    report.start("allowed values")
    for row in tables["people.csv"]:
        if row["role"] not in ROLES:
            report.fail("people.csv", row, "role", row["role"],
                        f"not one of {sorted(ROLES)}")
    for row in tables["vendors.csv"]:
        if row["category"] not in VENDOR_CATEGORIES:
            report.fail("vendors.csv", row, "category", row["category"],
                        "not an allowed vendor category")
    for row in tables["purchase_orders.csv"]:
        if row["status"] not in PO_STATUSES:
            report.fail("purchase_orders.csv", row, "status", row["status"],
                        f"not one of {sorted(PO_STATUSES)}")
    for row in tables["gl_accounts.csv"]:
        if row["account_type"] not in ACCOUNT_TYPES:
            report.fail("gl_accounts.csv", row, "account_type", row["account_type"],
                        f"not one of {sorted(ACCOUNT_TYPES)}")
        if row["category"] not in ("", *NON_PO_CATEGORIES):
            report.fail("gl_accounts.csv", row, "category", row["category"],
                        "not a non-PO category or blank")


def check_vendor_rules(tables, report):
    report.start("vendor rules")
    blanks = []
    for row in tables["vendors.csv"]:
        category, center, lease = row["category"], row["cost_center"], row["lease_amount"]
        if category in NON_PO_CATEGORIES and not center:
            report.fail("vendors.csv", row, "cost_center", center,
                        f"a {category} vendor must have a cost center")
        if category in ("inventory", "") and center:
            report.fail("vendors.csv", row, "cost_center", center,
                        f"a {category or 'blank-category'} vendor must not have a cost center")
        if category == "rent" and not lease:
            report.fail("vendors.csv", row, "lease_amount", lease,
                        "a rent vendor must have a lease_amount")
        if category != "rent" and lease:
            report.fail("vendors.csv", row, "lease_amount", lease,
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
            report.fail("purchase_orders.csv", row, "vendor_id", row["vendor_id"],
                        f"vendor category is {category.get(row['vendor_id'], 'unknown') or 'blank'}, expected inventory")
        if role.get(row["buyer_id"]) != "buyer":
            report.fail("purchase_orders.csv", row, "buyer_id", row["buyer_id"],
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
                report.fail("gl_accounts.csv", row, "category", category,
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
                    report.fail(name, row, column, text, "is blank")
            elif money(text) is None:
                report.fail(name, row, column, text,
                            "not an exact two-place decimal above zero")
    for name, column in (("po_lines.csv", "line"), ("po_lines.csv", "qty_ordered"),
                         ("receipts.csv", "line"), ("receipts.csv", "qty_received")):
        for row in tables[name]:
            if whole_number(row[column]) is None:
                report.fail(name, row, column, row[column],
                            "not a whole number above zero")


def check_receipts(tables, report):
    report.start("receipts")
    po_date = {}
    for row in tables["purchase_orders.csv"]:
        when = parse_date(row["po_date"])
        if when is None:
            report.fail("purchase_orders.csv", row, "po_date", row["po_date"],
                        "not a YYYY-MM-DD date")
        else:
            po_date[row["po_number"]] = when
    ordered = {(row["po_number"], row["line"]): row for row in tables["po_lines.csv"]}
    received = {}
    for row in tables["receipts.csv"]:
        when = parse_date(row["receipt_date"])
        if when is None:
            report.fail("receipts.csv", row, "receipt_date", row["receipt_date"],
                        "not a YYYY-MM-DD date")
        elif row["po_number"] in po_date and when < po_date[row["po_number"]]:
            report.fail("receipts.csv", row, "receipt_date", row["receipt_date"],
                        f"before the PO date {po_date[row['po_number']]}")
        key = (row["po_number"], row["line"])
        total, _ = received.get(key, (0, 0))
        received[key] = (total + (whole_number(row["qty_received"]) or 0), row)

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
            report.fail("invoice_history.csv", row, "invoice_date", row["invoice_date"],
                        "not a YYYY-MM-DD date")
        elif when > HISTORY_CUTOFF:
            report.fail("invoice_history.csv", row, "invoice_date", row["invoice_date"],
                        f"after the history cut-off {HISTORY_CUTOFF}")
        if not row["po_number"]:
            continue
        order = orders.get(row["po_number"])
        if order is None:
            continue
        if order["status"] != "closed":
            report.fail("invoice_history.csv", row, "po_number", row["po_number"],
                        f"PO status is {order['status']}; history holds invoices for closed POs only")
        if order["vendor_id"] != row["vendor_id"]:
            report.fail("invoice_history.csv", row, "vendor_id", row["vendor_id"],
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
                report.fail("invoice_history.csv", row, "service_month",
                            row["service_month"], "not a YYYY-MM month")
            elif index in seen:
                report.fail("invoice_history.csv", row, "service_month",
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
                report.fail(name, row, column, row[column], "does not end in .example")


def read_sheet(sheet, name, report):
    """Read one worksheet: Text format and string values in every cell, no formulas, exact header."""
    header = INPUT_HEADERS[name]
    grid = list(sheet.iter_rows())
    values = [[cell.value for cell in cells] for cells in grid]
    found = values[0] if values else []
    rows, by_row = [], {}
    if found[:len(header)] != header or any(value is not None for value in found[len(header):]):
        report.fail(name, reason=f"header is {found}, expected {header}")
    else:
        for row_number, cells in enumerate(values[1:], start=2):
            if any(value is not None for value in cells[len(header):]):
                report.fail(name, row=row_number, reason=f"wrong number of fields, expected {len(header)}")
                continue
            row = {column: "" if value is None else str(value) for column, value in zip(header, cells)}
            row["_row"] = row_number
            row["_id"] = " ".join(row[column] for column in INPUT_ID_COLUMNS[name])
            rows.append(row)
            by_row[row_number] = row
    for cells in grid:
        for cell in cells:
            where = by_row.get(cell.row, cell.row)
            column = header[cell.column - 1] if cell.column <= len(header) else cell.column_letter
            if cell.data_type == "f":
                report.fail(name, where, column, cell.value, "cell holds a formula")
            elif cell.value is not None and not isinstance(cell.value, str):
                report.fail(name, where, column, cell.value,
                            f"cell holds a {type(cell.value).__name__}, not text")
            if cell.number_format != "@":
                report.fail(name, where, column, cell.value,
                            f"number format is {cell.number_format}, expected @ (Text)")
    return rows


def load_inputs(report):
    """Check 14: the workbook and the three new CSVs exist and have the exact layout. Returns the rows."""
    report.start("input files")
    tables = {name: [] for name in INPUT_HEADERS}
    path = INPUT / WORKBOOK
    if not path.exists():
        report.fail(WORKBOOK, reason="file not found")
    else:
        book = load_workbook(path)
        if book.sheetnames != list(SHEETS):
            report.fail(WORKBOOK, reason=f"sheets are {book.sheetnames}, expected {list(SHEETS)}")
        for sheet, name in zip(SHEETS, (INVOICES, LINES)):
            if sheet in book.sheetnames:
                tables[name] = read_sheet(book[sheet], name, report)
    for name, folder in (("inbox.csv", INPUT), ("expected_outcomes.csv", EVALS),
                         ("expected_threads.csv", EVALS)):
        tables[name] = read_csv(folder / name, name, INPUT_HEADERS[name], INPUT_ID_COLUMNS[name], report)
    return tables


def check_input_ids(tables, report):
    report.start("input ids")
    invoices = {}
    for row in tables[INVOICES]:
        exception_id = row["exception_id"]
        if not is_code(exception_id, "EX-", 3):
            report.fail(INVOICES, row, "exception_id", exception_id, "not EX- + 3 digits")
        if exception_id in invoices:
            report.fail(INVOICES, row, "exception_id", exception_id,
                        f"duplicate of row {invoices[exception_id]['_row']}")
        else:
            invoices[exception_id] = row
    seen, numbers = {}, {}
    for row in tables[LINES]:
        key = (row["exception_id"], row["line"])
        if key in seen:
            report.fail(LINES, row, "exception_id+line", " ".join(key), f"duplicate of row {seen[key]}")
        else:
            seen[key] = row["_row"]
        if row["exception_id"] not in invoices:
            report.fail(LINES, row, "exception_id", row["exception_id"], "no such invoice")
        numbers.setdefault(row["exception_id"], []).append(whole_number(row["line"]) or 0)
    for exception_id, row in invoices.items():
        found = sorted(numbers.get(exception_id, []))
        if not found:
            report.fail(INVOICES, row, reason="invoice has no lines")
        elif found != list(range(1, len(found) + 1)):
            report.fail(INVOICES, row, reason=f"lines are numbered {found}, expected 1 to {len(found)}")
    messages = {}
    for row in tables["inbox.csv"]:
        message_id = row["message_id"]
        if not is_code(message_id, "M-", 2):
            report.fail("inbox.csv", row, "message_id", message_id, "not M- + 2 digits")
        if message_id in messages:
            report.fail("inbox.csv", row, "message_id", message_id, f"duplicate of row {messages[message_id]}")
        else:
            messages[message_id] = row["_row"]


def check_input_links(tables, report):
    report.start("input links")
    vendors = {row["vendor_id"]: row for row in tables["vendors.csv"]}
    orders = {row["po_number"] for row in tables["purchase_orders.csv"]}
    po_items = {(row["po_number"], row["line"]): row["item"] for row in tables["po_lines.csv"]}
    people = {row["person_id"] for row in tables["people.csv"]}
    senders = ({row["email"] for row in tables["people.csv"]}
               | {row["contact_email"] for row in tables["vendors.csv"]})
    invoices = {row["exception_id"]: row for row in tables[INVOICES]}
    by_number = {}
    for row in tables[INVOICES]:
        by_number.setdefault((row["vendor_id"], row["invoice_number"]), []).append(row)
        vendor = vendors.get(row["vendor_id"])
        if vendor is None:
            report.fail(INVOICES, row, "vendor_id", row["vendor_id"], "no such vendor")
        elif row["vendor_name"] != vendor["vendor_name"]:
            report.fail(INVOICES, row, "vendor_name", row["vendor_name"],
                        f"vendor master has {vendor['vendor_name']}")
        if row["po_number"] and row["po_number"] not in orders:
            report.fail(INVOICES, row, "po_number", row["po_number"], "no such purchase order")
        if row["requester_id"] and row["requester_id"] not in people:
            report.fail(INVOICES, row, "requester_id", row["requester_id"], "no such person")
    for row in tables[LINES]:
        invoice = invoices.get(row["exception_id"])
        if not row["po_line"] or invoice is None:
            continue
        key = (invoice["po_number"], row["po_line"])
        if not invoice["po_number"]:
            report.fail(LINES, row, "po_line", row["po_line"], "filled, but the invoice quotes no PO")
        elif key not in po_items:
            report.fail(LINES, row, "po_line", row["po_line"], f"{key[0]} has no line {key[1]}")
        elif po_items[key] != row["item"]:
            report.fail(LINES, row, "item", row["item"], f"{key[0]} line {key[1]} is item {po_items[key]}")
    for row in tables["inbox.csv"]:
        key = (row["vendor_id"], row["invoice_number"])
        matches = len(by_number.get(key, []))
        if matches != 1:
            report.fail("inbox.csv", row, "vendor_id+invoice_number", " ".join(key),
                        f"matches {matches} invoices; expected exactly 1")
        if row["from_email"] not in senders:
            report.fail("inbox.csv", row, "from_email", row["from_email"],
                        "not a person's email or a vendor's contact_email")


def check_input_formats(tables, report):
    report.start("input formats")
    category = {row["vendor_id"]: row["category"] for row in tables["vendors.csv"]}
    invoices = {row["exception_id"]: row for row in tables[INVOICES]}
    for row in tables[INVOICES]:
        when = parse_date(row["invoice_date"])
        if when is None:
            report.fail(INVOICES, row, "invoice_date", row["invoice_date"], "not a YYYY-MM-DD date")
        elif when > DAY0:
            report.fail(INVOICES, row, "invoice_date", row["invoice_date"], f"after day 0 ({DAY0})")
        if row["service_month"] and month_index(row["service_month"]) is None:
            report.fail(INVOICES, row, "service_month", row["service_month"], "not a YYYY-MM month")
        if money(row["amount"]) is None:
            report.fail(INVOICES, row, "amount", row["amount"], "not an exact two-place decimal above zero")
        if row["hold_code"] not in HOLD_CODES:
            report.fail(INVOICES, row, "hold_code", row["hold_code"], f"not one of {list(HOLD_CODES)}")
    for row in tables[LINES]:
        if not row["description"]:
            report.fail(LINES, row, "description", "", "is blank")
        line_amount = money(row["line_amount"])
        if line_amount is None:
            report.fail(LINES, row, "line_amount", row["line_amount"], "not an exact two-place decimal above zero")
        invoice = invoices.get(row["exception_id"])
        if invoice is None:
            continue
        if category.get(invoice["vendor_id"]) == "inventory":
            quantity, price = whole_number(row["quantity"]), money(row["unit_price"])
            if not row["item"]:
                report.fail(LINES, row, "item", "", "is blank on a PO-path line")
            if quantity is None:
                report.fail(LINES, row, "quantity", row["quantity"], "not a whole number above zero")
            if price is None:
                report.fail(LINES, row, "unit_price", row["unit_price"], "not an exact two-place decimal above zero")
            if None not in (quantity, price, line_amount) and quantity * price != line_amount:
                report.fail(LINES, row, "line_amount", row["line_amount"],
                            f"quantity x unit_price is {quantity * price}")
        else:
            for column in ("po_line", "item", "quantity", "unit_price"):
                if row[column]:
                    report.fail(LINES, row, column, row[column], "must be blank on a non-PO line")
    for row in tables["inbox.csv"]:
        if parse_date(row["received_date"]) not in DAYS[1:]:
            report.fail("inbox.csv", row, "received_date", row["received_date"],
                        f"not a business day from day 1 ({DAYS[1]}) to day 5 ({DAYS[5]})")
        if not row["body"]:
            report.fail("inbox.csv", row, "body", "", "is blank")
        if not row["from_email"].endswith(".example"):
            report.fail("inbox.csv", row, "from_email", row["from_email"], "does not end in .example")


def check_planted(tables, report):
    report.start("planted problems")
    category = {row["vendor_id"]: row["category"] for row in tables["vendors.csv"]}
    posted = {(row["vendor_id"], row["invoice_number"]) for row in tables["invoice_history.csv"]}
    declared = {row["exception_id"]: row["findings"].split(";") for row in tables["expected_outcomes.csv"]}
    totals = {}
    for row in tables[LINES]:
        amount = money(row["line_amount"]) or Decimal("0")
        totals[row["exception_id"]] = totals.get(row["exception_id"], Decimal("0")) + amount
    invoices = {}
    for row in tables[INVOICES]:
        invoices[row["exception_id"]] = row
        vendor_category = category.get(row["vendor_id"])
        amount, total = money(row["amount"]), totals.get(row["exception_id"], Decimal("0"))
        conditions = []
        if amount is not None and amount != total:
            conditions.append((f"header amount {amount} does not equal its lines {total}", "missing_data"))
        if not row["service_month"] and vendor_category in SERVICE_MONTH_REQUIRED:
            conditions.append((f"service_month is blank on a {vendor_category} bill", "missing_data"))
        if vendor_category == "inventory" and not row["po_number"]:
            conditions.append(("inventory vendor and po_number is blank", "missing_po"))
        if vendor_category == "professional_services" and not row["requester_id"]:
            conditions.append(("professional_services vendor and requester_id is blank", "no_requester"))
        if vendor_category == "":
            conditions.append(("vendor has no category", "no_category"))
        if (row["vendor_id"], row["invoice_number"]) in posted:
            conditions.append(("vendor_id+invoice_number is in invoice_history.csv", "exact_duplicate"))
        for condition, finding in conditions:
            if finding not in declared.get(row["exception_id"], []):
                report.fail(INVOICES, row, reason=f"{condition}, but expected_outcomes.csv does not list {finding}")
    for row in tables["expected_outcomes.csv"]:
        invoice = invoices.get(row["exception_id"])
        if "exact_duplicate" in row["findings"].split(";") and (
                invoice is None or (invoice["vendor_id"], invoice["invoice_number"]) not in posted):
            report.fail("expected_outcomes.csv", row, "findings", row["findings"],
                        "exact_duplicate is listed, but invoice_history.csv has no matching vendor_id+invoice_number")


def check_outcomes(tables, report):
    report.start("expected outcomes")
    name = "expected_outcomes.csv"
    category = {row["vendor_id"]: row["category"] for row in tables["vendors.csv"]}
    people = {row["person_id"] for row in tables["people.csv"]}
    gl_for = {row["category"]: row["gl_account"] for row in tables["gl_accounts.csv"] if row["category"]}
    orders = {row["po_number"]: row for row in tables["purchase_orders.csv"]}
    invoices = {row["exception_id"]: row for row in tables[INVOICES]}
    seen = {}
    for row in tables[name]:
        exception_id = row["exception_id"]
        if exception_id in seen:
            report.fail(name, row, "exception_id", exception_id, f"duplicate of row {seen[exception_id]}")
            continue
        seen[exception_id] = row["_row"]
        invoice = invoices.get(exception_id)
        if invoice is None:
            report.fail(name, row, "exception_id", exception_id, "no such invoice")
            continue
        vendor_category = category.get(invoice["vendor_id"])
        path = "po" if invoice["po_number"] or vendor_category == "inventory" else "non_po"
        if row["path"] != path:
            report.fail(name, row, "path", row["path"], f"expected {path}")
        found = finding_list(row["findings"])
        if found is None:
            report.fail(name, row, "findings", row["findings"],
                        "not none, or known findings in canonical order with no repeats")
            found = row["findings"].split(";")
        for column in ("approval_reason", "approver_id"):
            if "approval_required" in found and not row[column]:
                report.fail(name, row, column, "", "is blank, but approval_required is listed")
            elif "approval_required" not in found and row[column]:
                report.fail(name, row, column, row[column], "must be blank unless approval_required is listed")
        if row["approval_reason"] and row["approval_reason"] not in APPROVAL_REASONS:
            report.fail(name, row, "approval_reason", row["approval_reason"], f"not one of {list(APPROVAL_REASONS)}")
        if row["approver_id"] and row["approver_id"] not in people:
            report.fail(name, row, "approver_id", row["approver_id"], "no such person")
        gl = (gl_for.get(vendor_category, "")
              if path == "non_po" and vendor_category and "exact_duplicate" not in found else "")
        if row["gl_account"] != gl:
            report.fail(name, row, "gl_account", row["gl_account"], f"expected {gl or '(blank)'}")
        recommendation = "release" if row["findings"] == "none" else "hold"
        if row["day0_recommendation"] != recommendation:
            report.fail(name, row, "day0_recommendation", row["day0_recommendation"], f"expected {recommendation}")
        if row["first_tool"] and any(kind not in LOOKUP_KINDS for kind in row["first_tool"].split("|")):
            report.fail(name, row, "first_tool", row["first_tool"], "not lookup kinds joined by |")
        for column in ("duplicate_verdict", "mismatch_flag"):
            if row[column] not in ("yes", "no", ""):
                report.fail(name, row, column, row[column], "not yes, no, or blank")
        order = orders.get(row["po_match"])
        if row["po_match"] not in ("", "none") and (
                order is None or order["status"] != "open" or order["vendor_id"] != invoice["vendor_id"]):
            report.fail(name, row, "po_match", row["po_match"], "not none or an open PO of this invoice's vendor")
        suggestion = row["category_suggestion"]
        if suggestion and suggestion not in NON_PO_CATEGORIES:
            report.fail(name, row, "category_suggestion", suggestion, "not a non-PO category")
        if suggestion and "no_category" not in found:
            report.fail(name, row, "category_suggestion", suggestion, "filled, but no_category is not listed")
        for column in ("scenario", "expected_result"):
            if not row[column]:
                report.fail(name, row, column, "", "is blank")
        for column in INPUT_HEADERS[name]:
            if not row[column].isascii():
                report.fail(name, row, reason=f"{column} is not plain ASCII")
    for exception_id, invoice in invoices.items():
        if exception_id not in seen:
            report.fail(INVOICES, invoice, reason="no expected_outcomes.csv row")


def check_threads(tables, report):
    report.start("expected threads")
    name = "expected_threads.csv"
    people = {row["person_id"]: row for row in tables["people.csv"]}
    vendors = {row["vendor_id"]: row for row in tables["vendors.csv"]}
    orders = {row["po_number"]: row for row in tables["purchase_orders.csv"]}
    invoices = {row["exception_id"]: row for row in tables[INVOICES]}
    outcomes = {row["exception_id"]: row for row in tables["expected_outcomes.csv"]}
    messages = {row["message_id"]: row for row in tables["inbox.csv"]}

    def reply_date(row):
        message = messages.get(row["reply_message_id"])
        return parse_date(message["received_date"]) if message else None

    def replied_by(row, day):
        when = reply_date(row)
        return when is not None and when <= DAYS[day]

    seen, used, by_case = {}, {}, {}
    for row in tables[name]:
        key = (row["exception_id"], row["recipient_id"])
        if key in seen:
            report.fail(name, row, "exception_id+recipient_id", " ".join(key), f"duplicate of row {seen[key]}")
        else:
            seen[key] = row["_row"]
        outcome, invoice = outcomes.get(row["exception_id"]), invoices.get(row["exception_id"])
        if outcome is None:
            report.fail(name, row, "exception_id", row["exception_id"], "no expected_outcomes.csv row")
            continue
        if invoice is None:
            continue
        by_case.setdefault(row["exception_id"], []).append(row)

        role, recipient = row["recipient_role"], row["recipient_id"]
        if role not in RECIPIENT_ROLES:
            report.fail(name, row, "recipient_role", role, f"not one of {list(RECIPIENT_ROLES)}")
        else:
            expected = {"vendor": invoice["vendor_id"],
                        "buyer": orders.get(invoice["po_number"], {}).get("buyer_id", ""),
                        "requester": invoice["requester_id"],
                        "approver": outcome["approver_id"]}[role]
            if recipient != expected:
                report.fail(name, row, "recipient_id", recipient, f"the {role} for this invoice is {expected or '(none)'}")

        found = finding_list(row["findings"])
        if found is None:
            report.fail(name, row, "findings", row["findings"], "not known findings in canonical order with no repeats")
        else:
            for finding in found:
                if finding not in outcome["findings"].split(";"):
                    report.fail(name, row, "findings", row["findings"], f"{finding} is not on the expected_outcomes.csv row")
        opens = row["opens_on_day"]
        if opens not in ("0", "4"):
            report.fail(name, row, "opens_on_day", opens, "not 0 or 4")
        opened = DAYS[4] if opens == "4" else DAYS[0]

        person, vendor = people.get(recipient), vendors.get(recipient)
        email = person["email"] if person else vendor["contact_email"] if vendor else ""
        message_id, replied = row["reply_message_id"], reply_date(row)
        if message_id:
            message = messages.get(message_id)
            if message is None:
                report.fail(name, row, "reply_message_id", message_id, "no such inbox message")
            else:
                if message_id in used:
                    report.fail(name, row, "reply_message_id", message_id, f"already used by row {used[message_id]}")
                else:
                    used[message_id] = row["_row"]
                if message["from_email"] != email:
                    report.fail(name, row, "reply_message_id", message_id,
                                f"sent by {message['from_email']}, not the recipient {email or '(unknown)'}")
                if (message["vendor_id"], message["invoice_number"]) != (invoice["vendor_id"], invoice["invoice_number"]):
                    report.fail(name, row, "reply_message_id", message_id,
                                f"is about {message['vendor_id']} {message['invoice_number']}, not this invoice")
                if replied is not None and replied < opened:
                    report.fail(name, row, "reply_message_id", message_id,
                                f"dated {replied}, before the thread opens on {opened}")

        label, detail = row["reply_label"], row["reply_detail"]
        if message_id and label not in REPLY_LABELS:
            report.fail(name, row, "reply_label", label, f"not one of {list(REPLY_LABELS)}")
        elif not message_id and label:
            report.fail(name, row, "reply_label", label, "filled, but there is no reply")
        if label == "correction_coming" and parse_date(detail) is None:
            report.fail(name, row, "reply_detail", detail, "expected the promised date, YYYY-MM-DD")
        elif label == "redirected" and detail not in people:
            report.fail(name, row, "reply_detail", detail, "expected the person_id named")
        elif label not in ("correction_coming", "redirected") and detail:
            report.fail(name, row, "reply_detail", detail, "must be blank for this label")

        reminder = opens == "0" and not replied_by(row, 4)
        escalation = reminder and not replied_by(row, 5)
        if row["day4_action"] != ("reminder" if reminder else "none"):
            why = f"opens on day {opens}" if opens != "0" else f"reply dated {replied}"
            report.fail(name, row, "day4_action", row["day4_action"],
                        f"a day 4 reminder is due (no reply on or before {DAYS[4]})" if reminder
                        else f"no day 4 reminder is due ({why})")
        if row["day5_action"] != ("escalation" if escalation else "none"):
            why = "no day 4 reminder" if not reminder else f"reply dated {replied}"
            report.fail(name, row, "day5_action", row["day5_action"],
                        f"a day 5 escalation is due (no reply on or before {DAYS[5]})" if escalation
                        else f"no day 5 escalation is due ({why})")
        cc, to = (person["reports_to"], person["reports_to"]) if person else (VENDOR_REMINDER_CC, VENDOR_ESCALATION_TO)
        if row["day4_action"] == "reminder" and person and not person["reports_to"]:
            report.fail(name, row, "day4_action", "reminder", "no manager on file for follow-up")
        if row["day4_cc"] != (cc if row["day4_action"] == "reminder" else ""):
            report.fail(name, row, "day4_cc", row["day4_cc"],
                        f"expected {(cc if row['day4_action'] == 'reminder' else '') or '(blank)'}")
        if row["day5_to"] != (to if row["day5_action"] == "escalation" else ""):
            report.fail(name, row, "day5_to", row["day5_to"],
                        f"expected {(to if row['day5_action'] == 'escalation' else '') or '(blank)'}")

    for exception_id, outcome in outcomes.items():
        threads = by_case.get(exception_id, [])
        declared = [] if outcome["findings"] == "none" else outcome["findings"].split(";")
        if "possible_duplicate" in declared:
            for row in threads:
                report.fail(name, row, reason="the invoice is a possible duplicate: "
                            "its emails are held until AP rules, so it has no threads")
            continue
        covered = [finding for row in threads for finding in row["findings"].split(";")]
        covered += [finding for finding in declared if finding in AP_QUEUE_FINDINGS]
        if sorted(covered) != sorted(declared):
            report.fail("expected_outcomes.csv", outcome, "findings", outcome["findings"],
                        f"thread findings plus AP-queue findings are {';'.join(covered) or 'none'}")
        for row in threads:
            if row["opens_on_day"] != "4":
                continue
            confirmed = any(other["recipient_role"] == "requester" and other["reply_label"] == "approved"
                            and replied_by(other, 4) for other in threads)
            if row["recipient_role"] != "approver" or not confirmed:
                report.fail(name, row, "opens_on_day", "4",
                            f"day 4 is only for an approver thread after the requester's approved reply "
                            f"on or before {DAYS[4]}")
    for message_id, message in messages.items():
        if message_id not in used:
            report.fail("inbox.csv", message, "message_id", message_id, "not used by any thread")


def coverage(tables):
    """Every coverage item, in a fixed order, with the IDs of the cases that cover it."""
    category = {row["vendor_id"]: row["category"] for row in tables["vendors.csv"]}
    outcomes = tables["expected_outcomes.csv"]
    threads = tables["expected_threads.csv"]
    items = []
    for finding in (*FINDINGS, "none"):
        items.append((f"finding {finding}",
                      [row["exception_id"] for row in outcomes if finding in row["findings"].split(";")]))
    for reason in APPROVAL_REASONS:
        items.append((f"approval reason {reason}",
                      [row["exception_id"] for row in outcomes if row["approval_reason"] == reason]))
    for vendor_category in ("inventory", *NON_PO_CATEGORIES, ""):
        items.append((f"vendor category {vendor_category or 'blank'}",
                      [row["exception_id"] for row in tables[INVOICES]
                       if category.get(row["vendor_id"]) == vendor_category]))
    for label in REPLY_LABELS:
        items.append((f"reply label {label}",
                      sorted(row["reply_message_id"] for row in threads if row["reply_label"] == label)))
    for column, value in (("day0_recommendation", "release"), ("day0_recommendation", "hold"),
                          ("duplicate_verdict", "yes"), ("duplicate_verdict", "no")):
        items.append((f"{column} {value}", [row["exception_id"] for row in outcomes if row[column] == value]))
    items.append(("po_match none", [row["exception_id"] for row in outcomes if row["po_match"] == "none"]))
    items.append(("po_match a PO number",
                  [row["exception_id"] for row in outcomes if row["po_match"] not in ("", "none")]))
    for value in ("yes", "no"):
        items.append((f"mismatch_flag {value}", [row["exception_id"] for row in outcomes if row["mismatch_flag"] == value]))
    for recipient in ("person", "vendor"):
        for action, column in (("reminder", "day4_action"), ("escalation", "day5_action")):
            items.append((f"{action} to a {recipient}",
                          [row["exception_id"] for row in threads if row[column] == action
                           and (row["recipient_role"] == "vendor") == (recipient == "vendor")]))
    return items


def check_coverage(tables, report):
    report.start("coverage")
    for item, ids in coverage(tables):
        if not ids:
            report.fail("evals", reason=f"no case covers {item}")


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


def print_input_summary(tables):
    print()
    print("input row counts")
    for name in INPUT_HEADERS:
        print(f"  {name:<32}{len(tables[name]):>4}")

    print()
    print("demo calendar")
    for day, when in enumerate(DAYS):
        print(f"  day {day}  {when}  {when:%A}")


def print_eval_summary(tables):
    print()
    print("coverage")
    for item, ids in coverage(tables):
        print(f"  {item:<42}{', '.join(ids) or '-'}")

    print()
    print("agent checkpoints")
    for label, column in (("first lookup", "first_tool"), ("duplicate verdict", "duplicate_verdict"),
                          ("PO match", "po_match"), ("content check", "mismatch_flag"),
                          ("category suggestion", "category_suggestion")):
        count = sum(1 for row in tables["expected_outcomes.csv"] if row[column])
        print(f"  {label:<22}{count:>4}")
    replies = sum(1 for row in tables["expected_threads.csv"] if row["reply_label"])
    print(f"  {'reply interpretation':<22}{replies:>4}")


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
    tables.update(load_inputs(report))
    check_input_ids(tables, report)
    check_input_links(tables, report)
    check_input_formats(tables, report)
    check_planted(tables, report)
    check_outcomes(tables, report)
    check_threads(tables, report)
    check_coverage(tables, report)

    failed = report.print_results()
    print_summary(tables)
    print_input_summary(tables)
    print_eval_summary(tables)
    print()
    if failed:
        print(f"{failed} check{'s' if failed != 1 else ''} failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

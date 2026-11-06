"""Builds a held-out batch: data/<set>/reference/, data/<set>/input/, and evals/<set>/.

The batch's rows come from data/heldout_tables/<set>.json, their single source, written in the
planning chat and keyed blind by Max before any model saw them (plan decisions 11 to 15). The
company master (people, cost centers, GL accounts) is copied from data/reference/, so a batch has
the same people and accounts as the eval but its own vendors, POs, receipts, and history. Every
CSV is UTF-8 without a BOM, LF line endings; every workbook cell is stored as text, as in
build_exception_list.py. scripts/check_data.py --set <set> then checks the result.

    .venv\\Scripts\\python.exe scripts\\build_heldout.py heldout_a
"""

import csv
import json
import shutil
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "data" / "heldout_tables"
SETS = ("heldout_a", "heldout_b")
COMPANY = ("people.csv", "cost_centers.csv", "gl_accounts.csv")
REFERENCE = {
    "vendors": ("vendors.csv", ["vendor_id", "vendor_name", "category", "cost_center", "contact_email", "lease_amount"]),
    "purchase_orders": ("purchase_orders.csv", ["po_number", "vendor_id", "buyer_id", "po_date", "status"]),
    "po_lines": ("po_lines.csv", ["po_number", "line", "item", "description", "qty_ordered", "unit_price"]),
    "receipts": ("receipts.csv", ["receipt_id", "po_number", "line", "receipt_date", "qty_received"]),
    "invoice_history": ("invoice_history.csv", ["vendor_id", "invoice_number", "invoice_date", "service_month",
                                                "po_number", "amount"]),
}
INPUT = {
    "inbox": ("inbox.csv", ["message_id", "received_date", "from_email", "vendor_id", "invoice_number", "body"]),
    "review_decisions": ("review_decisions.csv", ["exception_id", "decision", "reason"]),
}
EVALS = {
    "expected_outcomes": ("expected_outcomes.csv", ["exception_id", "scenario", "expected_result", "path", "findings",
                                                    "approval_reason", "approver_id", "gl_account",
                                                    "day0_recommendation", "first_tool", "duplicate_verdict",
                                                    "po_match", "mismatch_flag", "category_suggestion"]),
    "expected_threads": ("expected_threads.csv", ["exception_id", "recipient_id", "recipient_role", "opens_on_day",
                                                  "findings", "reply_message_id", "reply_label", "reply_detail",
                                                  "day4_action", "day4_cc", "day5_action", "day5_to"]),
}
SHEETS = (("invoices", ["exception_id", "hold_code", "vendor_id", "vendor_name", "invoice_number", "invoice_date",
                        "po_number", "service_month", "requester_id", "amount"]),
          ("lines", ["exception_id", "line", "po_line", "item", "description", "quantity", "unit_price",
                     "line_amount"]))


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """One CSV: the header, then the rows, UTF-8 with no BOM and LF line endings."""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_sheet(sheet, rows: list[list[str]]) -> None:
    """Rows as text cells: Text format on every cell, bold frozen header, fitted widths."""
    for row_number, values in enumerate(rows, start=1):
        for column_number, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_number, column=column_number, value=value or None)
            cell.number_format = "@"
            if row_number == 1:
                cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for column_number in range(1, len(rows[0]) + 1):
        sheet.column_dimensions[get_column_letter(column_number)].width = max(len(row[column_number - 1])
                                                                              for row in rows)


def build(name: str) -> None:
    """Write every file of one batch from its tables."""
    tables = json.loads((TABLES / f"{name}.json").read_text(encoding="utf-8"))
    reference, inputs, evals = (ROOT / "data" / name / "reference", ROOT / "data" / name / "input",
                                ROOT / "evals" / name)
    for folder in (reference, inputs, evals):
        folder.mkdir(parents=True, exist_ok=True)
    for file_name in COMPANY:
        shutil.copyfile(ROOT / "data" / "reference" / file_name, reference / file_name)
    for folder, files in ((reference, REFERENCE), (inputs, INPUT), (evals, EVALS)):
        for key, (file_name, header) in files.items():
            write_csv(folder / file_name, header, tables[key])
    book = Workbook()
    book.remove(book.active)
    for (sheet_name, header), key in zip(SHEETS, ("invoices", "lines")):
        write_sheet(book.create_sheet(sheet_name), [header] + tables[key])
    book.save(inputs / "exception_list.xlsx")
    counts = ", ".join(f"{key} {len(rows)}" for key, rows in tables.items())
    print(f"{name}: {counts}")
    print(f"wrote data/{name}/reference (8 files), data/{name}/input (3 files), evals/{name} (2 files)")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SETS:
        sys.exit(f"usage: build_heldout.py {' | '.join(SETS)}")
    build(sys.argv[1])

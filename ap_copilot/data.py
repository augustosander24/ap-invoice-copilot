"""Loaders for the AP Invoice Copilot data.

load_reference() reads the eight CSVs in data/reference/ into lookups keyed
by ID. load_invoices() reads the invoices and lines sheets of
data/input/exception_list.xlsx into Invoice records. Every amount is a
Decimal parsed from its text, never a float. Nothing is validated beyond
parsing; scripts/check_data.py is the validator.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_DIR = ROOT / "data" / "reference"
EXCEPTION_LIST = ROOT / "data" / "input" / "exception_list.xlsx"
DATA_SETS = ("eval", "heldout_a", "heldout_b")


@dataclass(frozen=True)
class DataSet:
    """Where one set's files live: the 22-case eval (the regression check) or a held-out batch."""
    name: str
    reference: Path
    input: Path
    evals: Path


def data_set(name: str = "eval") -> DataSet:
    """The folders of a data set: "eval" is data/reference, data/input, and evals; a held-out batch has
    the same three folders under data/<name>/ and evals/<name>/."""
    if name not in DATA_SETS:
        raise ValueError(f"Unknown data set {name!r}; expected one of {', '.join(DATA_SETS)}")
    if name == "eval":
        return DataSet(name, REFERENCE_DIR, ROOT / "data" / "input", ROOT / "evals")
    return DataSet(name, ROOT / "data" / name / "reference", ROOT / "data" / name / "input", ROOT / "evals" / name)


@dataclass(frozen=True)
class InvoiceLine:
    line: int
    po_line: str
    item: str
    description: str
    quantity: int | None
    unit_price: Decimal | None
    line_amount: Decimal


@dataclass(frozen=True)
class Invoice:
    exception_id: str
    hold_code: str
    vendor_id: str
    vendor_name: str
    invoice_number: str
    invoice_date: str
    po_number: str
    service_month: str
    requester_id: str
    amount: Decimal | None
    lines: tuple[InvoiceLine, ...]


@dataclass(frozen=True)
class Reference:
    people: dict[str, dict[str, str]]
    cost_centers: dict[str, dict[str, str]]
    gl_by_category: dict[str, str]
    vendors: dict[str, dict[str, str]]
    purchase_orders: dict[str, dict[str, str]]
    po_lines: dict[tuple[str, str], dict[str, str]]
    received: dict[tuple[str, str], int]
    history: dict[str, tuple[dict[str, str], ...]]
    receipts: dict[str, tuple[dict[str, str], ...]] = field(default_factory=dict)


def read_csv(path: Path) -> list[dict[str, str]]:
    """Return a CSV's rows as dicts of strings; a blank field is ""."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_reference(folder: Path = REFERENCE_DIR) -> Reference:
    """Read the eight reference CSVs into lookups."""
    folder = Path(folder)
    received = defaultdict(int)
    receipts = defaultdict(list)
    for row in read_csv(folder / "receipts.csv"):
        received[(row["po_number"], row["line"])] += int(row["qty_received"])
        receipts[row["po_number"]].append(row)
    history = defaultdict(list)
    for row in read_csv(folder / "invoice_history.csv"):
        history[row["vendor_id"]].append(row)
    return Reference(
        people={row["person_id"]: row for row in read_csv(folder / "people.csv")},
        cost_centers={row["cost_center"]: row for row in read_csv(folder / "cost_centers.csv")},
        gl_by_category={row["category"]: row["gl_account"]
                        for row in read_csv(folder / "gl_accounts.csv") if row["category"]},
        vendors={row["vendor_id"]: row for row in read_csv(folder / "vendors.csv")},
        purchase_orders={row["po_number"]: row for row in read_csv(folder / "purchase_orders.csv")},
        po_lines={(row["po_number"], row["line"]): row for row in read_csv(folder / "po_lines.csv")},
        received=dict(received),
        history={vendor_id: tuple(rows) for vendor_id, rows in history.items()},
        receipts={po_number: tuple(rows) for po_number, rows in receipts.items()},
    )


def read_sheet(sheet) -> list[dict[str, str]]:
    """Return a worksheet's rows as dicts keyed by the header row; an empty cell is ""."""
    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    return [{column: "" if value is None else str(value) for column, value in zip(header, values)}
            for values in rows]


def load_invoices(path: Path = EXCEPTION_LIST) -> list[Invoice]:
    """Read the exception list into Invoice records, in sheet order, each with its lines."""
    book = load_workbook(path)
    lines = defaultdict(list)
    for row in read_sheet(book["lines"]):
        lines[row["exception_id"]].append(InvoiceLine(
            line=int(row["line"]),
            po_line=row["po_line"],
            item=row["item"],
            description=row["description"],
            quantity=int(row["quantity"]) if row["quantity"] else None,
            unit_price=Decimal(row["unit_price"]) if row["unit_price"] else None,
            line_amount=Decimal(row["line_amount"]),
        ))
    return [
        Invoice(
            exception_id=row["exception_id"],
            hold_code=row["hold_code"],
            vendor_id=row["vendor_id"],
            vendor_name=row["vendor_name"],
            invoice_number=row["invoice_number"],
            invoice_date=row["invoice_date"],
            po_number=row["po_number"],
            service_month=row["service_month"],
            requester_id=row["requester_id"],
            amount=Decimal(row["amount"]) if row["amount"] else None,
            lines=tuple(sorted(lines[row["exception_id"]], key=lambda line: line.line)),
        )
        for row in read_sheet(book["invoices"])
    ]

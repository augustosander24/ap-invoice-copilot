"""Builds data/input/exception_list.xlsx, the ERP-style exception list.

INVOICES and LINES below are the single source of the workbook: one row
per invoice and one row per invoice line. Every cell is stored as text,
so leading zeros (009102) and exact amounts survive Excel. After saving,
the script reopens the file and prints both sheets with a text-cell count.

openpyxl and the standard library. Runs from any working directory:

    .venv\\Scripts\\python.exe scripts\\build_exception_list.py
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "input" / "exception_list.xlsx"

INVOICES = (
    ("exception_id", "hold_code", "vendor_id", "vendor_name", "invoice_number", "invoice_date", "po_number", "service_month", "requester_id", "amount"),
    ("EX-001", "price", "V-1001", "Harbor Industrial Supply", "HIS-40817", "2026-11-09", "PO-26101", "", "", "3315.00"),
    ("EX-002", "price", "V-1001", "Harbor Industrial Supply", "HIS-40852", "2026-11-12", "PO-26102", "", "", "9201.00"),
    ("EX-003", "po", "V-1001", "Harbor Industrial Supply", "HIS-40903", "2026-11-18", "PO-26108", "", "", "1404.00"),
    ("EX-004", "quantity", "V-1002", "Keystone Fasteners", "KF-23318", "2026-11-06", "PO-26103", "", "", "4909.20"),
    ("EX-005", "quantity", "V-1002", "Keystone Fasteners", "KF-23342", "2026-11-16", "PO-26104", "", "", "2182.50"),
    ("EX-006", "po", "V-1003", "Summit Packaging", "009087", "2026-11-02", "PO-26105", "", "", "2160.00"),
    ("EX-007", "po", "V-1003", "Summit Packaging", "009102", "2026-11-04", "", "", "", "6671.00"),
    ("EX-008", "po", "V-1003", "Summit Packaging", "8817", "2026-08-24", "PO-26105", "", "", "5352.00"),
    ("EX-009", "price", "V-1004", "Pioneer Electrical Wholesale", "PEW-77104", "2026-11-20", "PO-26108", "", "", "3010.00"),
    ("EX-010", "duplicate", "V-2001", "Riverside Power & Light", "RPL-104834", "2026-10-28", "", "2026-10", "", "4129.90"),
    ("EX-011", "non_po", "V-2001", "Riverside Power & Light", "RPL-104835", "2026-11-28", "", "2026-11", "", "4402.35"),
    ("EX-012", "non_po", "V-2002", "Clearwater Water Authority", "CWA-77324", "2026-11-28", "", "2026-11", "", "1046.30"),
    ("EX-013", "non_po", "V-2003", "GreenCycle Waste Services", "GCW-0043", "2026-11-28", "", "", "", "646.20"),
    ("EX-014", "non_po", "V-3001", "Lakeside Industrial Properties", "LIP-2026-11", "2026-11-01", "", "2026-11", "", "19425.00"),
    ("EX-015", "non_po", "V-3002", "Oakmont Office Park", "OOP-2026-11", "2026-11-01", "", "2026-11", "", "6200.00"),
    ("EX-016", "non_po", "V-4001", "Marlow County Treasurer", "MCT-2026-H2", "2026-11-02", "", "2026-11", "", "9850.00"),
    ("EX-017", "non_po", "V-5001", "CloudLedger Software", "CL-88210", "2026-11-01", "", "2026-11", "", "1450.00"),
    ("EX-018", "non_po", "V-5002", "RouteWise Logistics Software", "RW-3317", "2026-11-01", "", "2026-11", "", "3740.00"),
    ("EX-019", "non_po", "V-6001", "Bennett & Cole CPAs", "BC-2026-041", "2026-11-20", "", "", "P-102", "7500.00"),
    ("EX-020", "non_po", "V-6002", "Ironbridge IT Consulting", "IBC-1233", "2026-11-23", "", "", "P-112", "4860.00"),
    ("EX-021", "non_po", "V-6002", "Ironbridge IT Consulting", "IBC-1240", "2026-11-25", "", "", "", "2850.00"),
    ("EX-022", "non_po", "V-7001", "Delta Signage Co.", "DS-1042", "2026-11-02", "", "2026-11", "", "395.00"),
)

LINES = (
    ("exception_id", "line", "po_line", "item", "description", "quantity", "unit_price", "line_amount"),
    ("EX-001", "1", "1", "IND-2210", "Nitrile work gloves box of 100", "40", "28.50", "1140.00"),
    ("EX-001", "2", "2", "IND-2415", "Shop towel rolls case of 12", "60", "36.25", "2175.00"),
    ("EX-002", "1", "1", "IND-3120", "Heavy-duty pallet jack 2500 kg", "6", "785.00", "4710.00"),
    ("EX-002", "2", "2", "IND-3305", "Steel shelving unit 5-tier", "18", "249.50", "4491.00"),
    ("EX-003", "1", "", "IND-2630", "Safety glasses clear lens box of 12", "30", "46.80", "1404.00"),
    ("EX-004", "1", "1", "FAS-1050", "Hex bolts M12 x 60 mm box of 250", "48", "62.90", "3019.20"),
    ("EX-004", "2", "2", "FAS-1180", "Stainless washers M12 box of 500", "100", "18.90", "1890.00"),
    ("EX-005", "1", "1", "FAS-1265", "Socket head cap screws M8 x 30 mm box of 500", "24", "41.25", "990.00"),
    ("EX-005", "2", "2", "FAS-1390", "Threaded rod M10 x 1 m", "150", "7.95", "1192.50"),
    ("EX-006", "1", "", "PKG-1210", "Poly mailers 10x13 in case of 500", "45", "48.00", "2160.00"),
    ("EX-007", "1", "", "PKG-1455", "Kraft paper void fill 30 in x 1200 ft roll", "36", "54.25", "1953.00"),
    ("EX-007", "2", "", "PKG-1620", "Carton sealing tape 2 in x 110 yd case of 36", "70", "67.40", "4718.00"),
    ("EX-008", "1", "1", "PKG-1040", "Corrugated shipping cartons 18x12x10 in bundle of 25", "120", "23.60", "2832.00"),
    ("EX-008", "2", "2", "PKG-1125", "Stretch wrap film 18 in x 1500 ft roll", "80", "31.50", "2520.00"),
    ("EX-009", "1", "1", "ELC-4075", "THHN building wire 12 AWG 500 ft spool", "25", "124.00", "3100.00"),
    ("EX-010", "1", "", "", "Electric service October 2026", "", "", "4129.90"),
    ("EX-011", "1", "", "", "Electric service November 2026", "", "", "4402.35"),
    ("EX-012", "1", "", "", "Water and sewer service November 2026", "", "", "1046.30"),
    ("EX-013", "1", "", "", "Waste and recycling collection", "", "", "646.20"),
    ("EX-014", "1", "", "", "Warehouse base rent November 2026", "", "", "18500.00"),
    ("EX-014", "2", "", "", "Late payment fee", "", "", "925.00"),
    ("EX-015", "1", "", "", "Office rent November 2026", "", "", "6200.00"),
    ("EX-016", "1", "", "", "Real property tax second half 2026", "", "", "9850.00"),
    ("EX-017", "1", "", "", "CloudLedger Enterprise plan November 2026", "", "", "1450.00"),
    ("EX-018", "1", "", "", "RouteWise Pro plan November 2026", "", "", "780.00"),
    ("EX-018", "2", "", "", "Rugged handheld barcode scanners 8 units", "", "", "2960.00"),
    ("EX-019", "1", "", "", "Year-end audit planning phase 1", "", "", "7500.00"),
    ("EX-020", "1", "", "", "Firewall upgrade project completed November 20 2026", "", "", "4860.00"),
    ("EX-021", "1", "", "", "Network switch configuration support", "", "", "2850.00"),
    ("EX-022", "1", "", "", "Digital signage content service November 2026", "", "", "395.00"),
)

SHEETS = (("invoices", INVOICES), ("lines", LINES))


def write_sheet(sheet, rows):
    """Write rows as text cells: Text format on every cell, bold frozen header, fitted widths."""
    for row_number, values in enumerate(rows, start=1):
        for column_number, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_number, column=column_number, value=value or None)
            cell.number_format = "@"
            if row_number == 1:
                cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    for column_number in range(1, len(rows[0]) + 1):
        width = max(len(values[column_number - 1]) for values in rows)
        sheet.column_dimensions[get_column_letter(column_number)].width = width


def build():
    book = Workbook()
    book.remove(book.active)
    for name, rows in SHEETS:
        write_sheet(book.create_sheet(name), rows)
    book.save(OUT)


def print_back():
    """Reopen the saved file, print each sheet as a table, and count the text cells."""
    book = load_workbook(OUT)
    for sheet in book.worksheets:
        cells = list(sheet.iter_rows())
        table = [["" if cell.value is None else str(cell.value) for cell in row] for row in cells]
        widths = [max(len(row[index]) for row in table) for index in range(len(table[0]))]
        print(f"sheet {sheet.title}")
        for row in table:
            print("  " + "  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip())
        filled = [cell for row in cells for cell in row if cell.value is not None]
        text = [cell for cell in filled if cell.data_type == "s"]
        print(f"text cells: {len(text)} of {len(filled)}")
        print()


if __name__ == "__main__":
    build()
    print_back()

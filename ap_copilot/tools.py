"""Read-only lookups for the AP Invoice Copilot investigator agents.

Each tool reads the Reference and returns a plain dict. Every record and every
search result carries an evidence_id, so code can check that each agent claim
points to data the agent was shown. TOOL_KINDS maps tool names to the eval's
lookup kinds (evals/README.md, first_tool). No model runs in this module.
"""

from ap_copilot.data import Reference
from ap_copilot.rules import normalize_invoice_number

TOOL_KINDS = {
    "get_purchase_order": "po",
    "get_goods_receipts": "receipts",
    "find_open_purchase_orders": "open_pos",
    "find_similar_invoices": "similar_invoices",
    "get_bill_history": "bill_history",  # non-PO investigator; built in Phase 8
    "get_vendor": "vendor",
}


def _spec(name: str, description: str, parameters: dict[str, str], required: list[str]) -> dict:
    """One Ollama tool definition; every parameter is a string."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {param: {"type": "string", "description": text}
                               for param, text in parameters.items()},
                "required": required,
            },
        },
    }


PO_TOOL_SPECS = [
    _spec("get_purchase_order",
          "Look up a purchase order: its vendor, buyer, status, and lines with unit prices "
          "and ordered quantities.",
          {"po_number": "the PO number, for example PO-26101"},
          ["po_number"]),
    _spec("get_goods_receipts",
          "Look up the goods receipts posted against a purchase order: quantities received "
          "and dates.",
          {"po_number": "the PO number, for example PO-26101"},
          ["po_number"]),
    _spec("find_open_purchase_orders",
          "List a vendor's open purchase orders with their lines, to find the PO an invoice "
          "belongs to.",
          {"vendor_id": "the vendor ID, for example V-1001"},
          ["vendor_id"]),
    _spec("find_similar_invoices",
          "Search posted invoices from the same vendor that quote the same PO number or have "
          "the same invoice number once leading zeros and punctuation are removed.",
          {"vendor_id": "the vendor ID, for example V-1001",
           "invoice_number": "the invoice number as printed",
           "po_number": "optional: the PO number on the invoice; leave out when there is none"},
          ["vendor_id", "invoice_number"]),
    _spec("get_vendor",
          "Look up a vendor master record: name, category, cost center, and contact.",
          {"vendor_id": "the vendor ID, for example V-1001"},
          ["vendor_id"]),
]


def _no_po(po_number: str) -> dict:
    return {"error": f"{po_number} is not on file"}


def _no_vendor(vendor_id: str) -> dict:
    return {"error": f"vendor {vendor_id} is not on file"}


def _line_records(ref: Reference, po_number: str) -> list[dict]:
    """The PO's lines, sorted by line number, each with its evidence_id."""
    rows = sorted((row for (po, _), row in ref.po_lines.items() if po == po_number),
                  key=lambda row: int(row["line"]))
    return [{"evidence_id": f"po_line:{po_number}:{row['line']}", "line": row["line"],
             "item": row["item"], "description": row["description"],
             "qty_ordered": row["qty_ordered"], "unit_price": row["unit_price"]}
            for row in rows]


def get_purchase_order(ref: Reference, po_number: str) -> dict:
    """The PO header and its lines; values are the CSV text."""
    po = ref.purchase_orders.get(po_number)
    if po is None:
        return _no_po(po_number)
    return {"evidence_id": f"po:{po_number}", "po_number": po_number, "vendor_id": po["vendor_id"],
            "buyer_id": po["buyer_id"], "po_date": po["po_date"], "status": po["status"],
            "lines": _line_records(ref, po_number)}


def get_goods_receipts(ref: Reference, po_number: str) -> dict:
    """Each receipt against the PO, in file order, and the total received per line."""
    if po_number not in ref.purchase_orders:
        return _no_po(po_number)
    totals = {line: total for (po, line), total in ref.received.items() if po == po_number}
    return {
        "evidence_id": f"receipts:{po_number}",
        "po_number": po_number,
        "receipts": [{"evidence_id": f"receipt:{row['receipt_id']}", "line": row["line"],
                      "receipt_date": row["receipt_date"], "qty_received": row["qty_received"]}
                     for row in ref.receipts.get(po_number, ())],
        "total_received_by_line": {line: str(totals[line]) for line in sorted(totals, key=int)},
    }


def find_open_purchase_orders(ref: Reference, vendor_id: str) -> dict:
    """The vendor's open POs, in file order, each with its lines."""
    if vendor_id not in ref.vendors:
        return _no_vendor(vendor_id)
    return {
        "evidence_id": f"open_pos:{vendor_id}",
        "vendor_id": vendor_id,
        "open_purchase_orders": [
            {"evidence_id": f"po:{po_number}", "po_number": po_number, "po_date": po["po_date"],
             "buyer_id": po["buyer_id"], "lines": _line_records(ref, po_number)}
            for po_number, po in ref.purchase_orders.items()
            if po["vendor_id"] == vendor_id and po["status"] == "open"
        ],
    }


def find_similar_invoices(ref: Reference, vendor_id: str, invoice_number: str,
                          po_number: str = "") -> dict:
    """The vendor's posted invoices with the same PO number or the same normalized invoice number."""
    if vendor_id not in ref.vendors:
        return _no_vendor(vendor_id)
    normalized = normalize_invoice_number(invoice_number)
    matches = []
    for row in ref.history.get(vendor_id, ()):
        matched_on = []
        if po_number and po_number == row["po_number"]:
            matched_on.append("same PO number")
        if normalize_invoice_number(row["invoice_number"]) == normalized:
            matched_on.append("same invoice number once normalized")
        if matched_on:
            matches.append({"evidence_id": f"posted:{vendor_id}:{row['invoice_number']}",
                            "invoice_number": row["invoice_number"],
                            "invoice_date": row["invoice_date"], "po_number": row["po_number"],
                            "amount": row["amount"], "matched_on": matched_on})
    return {"evidence_id": f"similar_invoices:{vendor_id}", "vendor_id": vendor_id,
            "posted_matches": matches}


def get_vendor(ref: Reference, vendor_id: str) -> dict:
    """The vendor master row."""
    vendor = ref.vendors.get(vendor_id)
    if vendor is None:
        return _no_vendor(vendor_id)
    return {"evidence_id": f"vendor:{vendor_id}", **vendor}


_PO_TOOLS = {
    "get_purchase_order": get_purchase_order,
    "get_goods_receipts": get_goods_receipts,
    "find_open_purchase_orders": find_open_purchase_orders,
    "find_similar_invoices": find_similar_invoices,
    "get_vendor": get_vendor,
}
_PARAMETERS = {spec["function"]["name"]: tuple(spec["function"]["parameters"]["properties"])
               for spec in PO_TOOL_SPECS}


def known_arguments(name: str, args: dict) -> dict:
    """The arguments the tool takes, as text; any other argument is left out."""
    return {key: str(value) for key, value in args.items() if key in _PARAMETERS.get(name, ())}


def run_tool(ref: Reference, name: str, args: dict) -> dict:
    """Run one PO tool by name. Arguments the tool doesn't take are left out and listed in
    ignored_arguments; an unknown name or a missing argument returns an error, never raises."""
    tool = _PO_TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}; use one of: {', '.join(_PO_TOOLS)}"}
    try:
        result = tool(ref, **known_arguments(name, args))
    except TypeError as error:
        return {"error": f"bad arguments for {name}: {error}"}
    ignored = sorted(set(args) - set(_PARAMETERS[name]))
    if ignored:
        result["ignored_arguments"] = ignored
    return result


def evidence_ids(result) -> list[str]:
    """Every evidence_id in a tool result: outer record first, then depth first, in order."""
    found = []
    if isinstance(result, dict):
        if "evidence_id" in result:
            found.append(result["evidence_id"])
        for value in result.values():
            found += evidence_ids(value)
    elif isinstance(result, list):
        for item in result:
            found += evidence_ids(item)
    return found

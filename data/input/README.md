# Input data

What the AP Invoice Copilot works from: the exception list of invoices on
payment hold, and a mock mailbox of replies to the emails it sends.

**All companies, people, and email addresses in these files are fictional.**
Emails use the reserved `.example` domain, which can never receive real mail.
IDs and invoice numbers are text, not numbers; invoice numbers may carry
leading zeros.

- `exception_list.xlsx` is generated. To change it, edit the rows in
  `scripts/build_exception_list.py` and rerun it:

      .venv\Scripts\python.exe scripts\build_exception_list.py

  Open the workbook in Excel only to view it, and **never save from Excel**.
- Open `inbox.csv` in VS Code, not Excel.

## exception_list.xlsx

Modeled on an ERP exception-list export: invoices on payment hold, each with
a hold reason code. It does not follow any specific ERP's layout. Every cell
is stored as text, so leading zeros and exact amounts survive Excel.

Two sheets: `invoices` (one row per invoice) and `lines` (one row per invoice
line).

### invoices

| Column | Meaning | Allowed values / format |
|---|---|---|
| `exception_id` | Row key | `EX-` + 3 digits |
| `hold_code` | The ERP's primary hold reason. Context only: the rules re-check every invoice and can find more or less than the code says | `price`, `quantity`, `po`, `duplicate`, `non_po` |
| `vendor_id` | Vendor that billed | a `vendor_id` in `vendors.csv` |
| `vendor_name` | Name as on the invoice | matches the vendor master |
| `invoice_number` | Number as printed on the invoice | text, may have leading zeros |
| `invoice_date` | Date on the invoice | `YYYY-MM-DD`, on or before the export date 2026-11-30 |
| `po_number` | PO the invoice quotes | a `po_number`; blank when the invoice quotes none |
| `service_month` | Period billed | `YYYY-MM`; blank when not stated |
| `requester_id` | Person who asked for the service | a `person_id`; blank when none given |
| `amount` | Invoice total | two-place decimal |

### lines

A PO-path line is a line on an invoice from an `inventory` vendor, whether or
not the invoice quotes a PO. All other lines leave `item`, `quantity`, and
`unit_price` blank.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `exception_id` | Invoice this line belongs to | an `exception_id` on the `invoices` sheet |
| `line` | Line number within the invoice | 1, 2, … per invoice |
| `po_line` | PO line billed | a `line` on the quoted PO; blank when the invoice quotes no valid PO line |
| `item` | Item code | text; PO-path lines only |
| `description` | Line text | text |
| `quantity` | Units billed | whole number; PO-path lines only |
| `unit_price` | Price per unit | two-place decimal; PO-path lines only |
| `line_amount` | Line total | two-place decimal; `quantity` × `unit_price` on PO-path lines |

## inbox.csv

A mock mailbox: one row per reply to an email the copilot sent. People who
never reply have no row. Each run reads only replies dated up to its as-of
date.

`vendor_id` + `invoice_number` + `from_email` is the thread key, the one a
mail connector would derive from the email thread. One invoice can have
several threads, one per recipient.

Format: UTF-8 with no byte-order mark, comma-separated, one header row. A
body that contains a comma is double-quoted.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `message_id` | Row key | `M-` + 2 digits |
| `received_date` | Day the reply arrived | `YYYY-MM-DD`, a business day from 2026-12-01 to 2026-12-07 |
| `from_email` | Sender | a person's `email` or a vendor's `contact_email` |
| `vendor_id` | Vendor on the invoice the reply is about | a `vendor_id` |
| `invoice_number` | Invoice the reply is about | with `vendor_id`, matches one invoice on the exception list |
| `body` | Reply text | plain text |

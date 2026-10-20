# Reference data

Static master data for the AP Invoice Copilot. Every later phase reads these
files; nothing here is generated at run time.

**All companies, people, vendors, and email addresses in these files are
fictional.** Emails use the reserved `.example` domain, which can never
receive real mail. All IDs are text, not numbers: the letter prefixes
(`P-`, `CC-`, `V-`, `PO-`, `R-`) stop spreadsheets reformatting them, and
invoice numbers may carry leading zeros. **Open these files in Excel only to
view, never to save from Excel** — saving strips leading zeros and can rewrite
dates and amounts.

Format for every file: UTF-8 with no byte-order mark, comma-separated, one
header row. A blank value is an empty field, never `None`, `NULL`, or `N/A`.
Amounts have exactly two decimal places, no currency symbol, no thousands
separator. Dates are `YYYY-MM-DD`; service months are `YYYY-MM`. History ends
2026-10-31.

Run `scripts/check_data.py` after any edit. It validates every rule stated
below and prints a `FAIL` line naming the file, row, column, and value.

## people.csv

Everyone an invoice can be routed to, and who each of them reports to.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `person_id` | Unique key other files point at | `P-` + 3 digits |
| `name` | Name used in a drafted email | text |
| `email` | Address a routed email is sent to | ends in `.example` |
| `title` | Job title, used in email wording | text |
| `department` | Grouping for "who owns this area" | text |
| `role` | What routing code keys on | `manager`, `buyer`, `staff`, `ap` |
| `reports_to` | This person's manager; the escalation target | a `person_id`, blank on exactly one person (top of the chain) |

## cost_centers.csv

The spending areas a non-PO invoice is approved against.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `cost_center` | Unique key | `CC-` + 3 digits |
| `name` | Label used in emails and reports | text |
| `owner_id` | Person who approves spend against it | a `person_id` |

## gl_accounts.csv

The chart of accounts an invoice is coded to.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `gl_account` | Account number | 4 digits |
| `name` | Account name | text |
| `account_type` | Where it sits in the ledger | `asset`, `liability`, `expense` |
| `category` | Vendor category this account codes | one of the five non-PO categories, or blank where the account is not a coding target |

Each of the five non-PO categories maps to exactly one account, so coding a
non-PO invoice is a lookup, not a judgment call.

## vendors.csv

The vendor master. `category` decides how an invoice is treated.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `vendor_id` | Unique key | `V-` + 4 digits |
| `vendor_name` | Name as printed on the invoice | text |
| `category` | Treatment; `inventory` means a PO was expected | `inventory`, `utilities`, `rent`, `taxes`, `subscriptions`, `professional_services`, or blank |
| `cost_center` | Approver route for a non-PO invoice | a `cost_center`; required for the five non-PO categories, blank for `inventory` and for the blank category |
| `contact_email` | Vendor's accounts-receivable address | ends in `.example` |
| `lease_amount` | Contracted monthly rent | two-place decimal above zero on `rent` vendors, blank on all others |

Exactly one vendor has a blank category: the deliberate uncategorised case.

## purchase_orders.csv

Purchase order headers.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `po_number` | Unique key | `PO-` + 5 digits |
| `vendor_id` | Vendor the PO was raised on | a `vendor_id` whose category is `inventory` |
| `buyer_id` | Purchasing person who owns the PO | a `person_id` whose role is `buyer` |
| `po_date` | Date the PO was raised | `YYYY-MM-DD` |
| `status` | Whether the PO still accepts invoices | `open`, `closed` |

## po_lines.csv

What each PO ordered. Keyed by `po_number` + `line`.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `po_number` | PO this line belongs to | a `po_number` |
| `line` | Line number within the PO | whole number above zero, starting at 1 on each PO |
| `item` | Vendor-neutral item code | text |
| `description` | Line text an invoice line is matched against | text, no commas |
| `qty_ordered` | Units ordered; the ceiling for receipts | whole number above zero |
| `unit_price` | Contracted price per unit | two-place decimal above zero |

## receipts.csv

Goods booked in against a PO line. A line may have several receipts.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `receipt_id` | Unique key | `R-` + 4 digits |
| `po_number` | PO the goods landed against | a `po_number` |
| `line` | PO line the goods landed against | a `line` on that PO |
| `receipt_date` | When the warehouse booked it | `YYYY-MM-DD`, on or after the PO date |
| `qty_received` | Units booked on this receipt | whole number above zero; the total per line never exceeds `qty_ordered` |

## invoice_history.csv

Invoices already posted. The basis for the duplicate check and for every
historical average. Sorted by `vendor_id`, then `invoice_date`.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `vendor_id` | Vendor that billed | a `vendor_id` |
| `invoice_number` | Number as printed on the invoice | text, may have leading zeros; unique per vendor |
| `invoice_date` | Date on the invoice | `YYYY-MM-DD`, on or before 2026-10-31 |
| `service_month` | Period the bill covers | `YYYY-MM`; blank on PO and professional-services invoices |
| `po_number` | PO the invoice bills against | a `po_number` with status `closed` and the same vendor; blank on non-PO invoices |
| `amount` | Invoice total | two-place decimal above zero |

A utilities vendor has either 12 or more consecutive service months with no
gaps or repeats, or 2 bills or fewer. Nothing in between: the design defines
no rule for 3 to 11 bills, so the data does not contain that case.

# Eval set

## Purpose

These files hold the expected result for every case: one case per
exception-list invoice (22), plus the expected interpretation of every inbox
reply (18). Phase 10 scores runs against them.

The project README's test-scenarios table (scenario, expected result,
pass/fail) is built from `expected_outcomes.csv` plus the Phase 10 results.
**These files hold expectations only, never results.**

Format for both CSVs: UTF-8 with no byte-order mark, comma-separated, one
header row, plain ASCII. A blank value is an empty field.

## Demo calendar

Business days only; the weekend between day 4 and day 5 is skipped.

| Day | Date | |
|---|---|---|
| 0 | Mon 2026-11-30 | export date |
| 1 | Tue 2026-12-01 | |
| 2 | Wed 2026-12-02 | |
| 3 | Thu 2026-12-03 | replies to day-0 emails due |
| 4 | Fri 2026-12-04 | |
| 5 | Mon 2026-12-07 | |

## expected_outcomes.csv

One row per invoice on the exception list.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `exception_id` | Case key | an `exception_id` on the exception list, one row each |
| `scenario` | What the case tests, in plain English | text |
| `expected_result` | The expected outcome in plain English, with figures a reader can check | text |
| `path` | Which rule set applies | `po`, `non_po` |
| `findings` | Every issue the rules should find | `none`, or findings from the list below in canonical order, separated by `;` |
| `approval_reason` | Why approval is needed | a reason below; blank when no approval is required |
| `approver_id` | Who approves | a `person_id`; blank when no approval is required |
| `gl_account` | GL code from the vendor category on a non-PO invoice | a `gl_account`; blank on PO invoices (coded through the PO), on an exact duplicate, and for a vendor with no category |
| `day0_recommendation` | What the day 0 run recommends | `release`, `hold` |
| `first_tool` | Agent: the first lookup it should make | lookup kinds below; `\|` separates accepted alternatives |
| `duplicate_verdict` | Agent: whether a duplicate candidate is a duplicate | `yes`, `no` |
| `po_match` | Agent: the open PO the invoice belongs to | a `po_number`, or `none` |
| `mismatch_flag` | Agent content check: whether any invoice content doesn't fit the vendor's category | `yes`, `no` |
| `category_suggestion` | Agent: a category for a vendor that has none | a vendor category |

**Agent columns** (`first_tool`, `duplicate_verdict`, `po_match`,
`mismatch_flag`, `category_suggestion`): blank means the agent is not expected
to run there, so the column is not scored.

### Findings, in canonical order

| Finding | Meaning |
|---|---|
| `price_variance` | Invoice unit price differs from the PO price beyond tolerance (2% of the invoice amount, capped at $100) |
| `quantity_variance` | Billed quantity is more than received, including a missing receipt |
| `missing_po` | An inventory vendor's invoice quotes no PO |
| `invalid_po` | The quoted PO can't be billed: a closed PO or another vendor's PO |
| `exact_duplicate` | Same vendor and invoice number as a posted invoice |
| `possible_duplicate` | Close to a posted invoice without being an exact match; AP decides |
| `missing_data` | Missing or incorrect invoice data, such as a required field left blank or a header total that doesn't equal its lines |
| `approval_required` | A non-PO rule requires approval |
| `confirmation_required` | The requester must confirm the service was received |
| `no_requester` | A services invoice names no requester |
| `no_category` | The vendor has no category |
| `category_mismatch` | Invoice content doesn't fit the vendor's category |

`none` when nothing is found.

### Approval reasons

| Reason | Meaning |
|---|---|
| `utilities_over_10pct` | Utility bill more than 10% away from the vendor's 12-month average |
| `utilities_first_3_bills` | One of a utility vendor's first 3 bills |
| `rent_differs` | Rent differs from the lease amount |
| `taxes` | Taxes always need approval |
| `subscriptions` | Subscriptions always need approval |
| `professional_services` | Services need a confirmation, then approval |

### Lookup kinds (`first_tool`)

| Kind | Looks up |
|---|---|
| `po` | The PO quoted on the invoice |
| `receipts` | Receipts against that PO |
| `open_pos` | The vendor's open POs |
| `similar_invoices` | Posted invoices similar to this one |
| `bill_history` | The vendor's past bills |
| `vendor` | The vendor master record |

`|` separates accepted alternatives. For a quantity hold, either the PO or the
receipts lookup first is accepted (`po|receipts`). These are kinds, not tool
names; tool names are mapped to them in Phase 6.

### AP-queue findings

`possible_duplicate`, `category_mismatch`, `no_requester`, and `no_category`
go to the AP exception queue (P-104, AP Team). They have no email thread.

### Duplicates

- **Exact duplicate:** stops every other check.
- **Possible duplicate:** every check still runs and every finding is listed.
  Emails for the non-AP findings are drafted and held until AP rules, so they
  have no thread row (EX-008). If AP confirms the duplicate, the vendor gets a
  duplicate notice; if AP clears it, the held drafts go out.

## expected_threads.csv

One row per email thread that goes out: invoice × recipient.

| Column | Meaning | Allowed values / format |
|---|---|---|
| `exception_id` | Invoice the email is about | an `exception_id` |
| `recipient_id` | Who the email goes to | a `person_id`, or a `vendor_id` for a vendor |
| `recipient_role` | Picks the email template | `buyer`, `vendor`, `approver`, `requester` |
| `opens_on_day` | Demo day the email is sent | `0`; `4` for an approval that follows a service confirmation |
| `findings` | Findings this email covers | findings from the list above, in canonical order, separated by `;` |
| `reply_message_id` | The reply in `inbox.csv` | a `message_id`; blank when there is no reply |
| `reply_label` | Expected interpretation of the reply | a reply label below; blank when there is no reply |
| `reply_detail` | Detail for the label | the promised date (`YYYY-MM-DD`) for `correction_coming`; the `person_id` named for `redirected`; blank otherwise |
| `day4_action` | Follow-up on day 4 | `none`, `reminder` |
| `day4_cc` | Who the reminder is cc'd to | a `person_id`; blank when there is no reminder |
| `day5_action` | Follow-up on day 5 | `none`, `escalation` |
| `day5_to` | Who the escalation goes to | a `person_id`; blank when there is no escalation |

### Roles and templates

| Role | Template |
|---|---|
| `buyer` | buyer query |
| `vendor` | vendor correction request (also used for the duplicate notice) |
| `approver` | approval request |
| `requester` | service confirmation |

### Follow-up rules

- A day-0 thread gets a **day 4 reminder** when no reply is dated on or
  before day 4, and a **day 5 escalation** when there is still no reply dated
  on or before day 5.
- **For a person,** the reminder is cc'd to their manager (`reports_to`) and
  the escalation goes to that manager. This includes taxes.
- **For a vendor,** the reminder is cc'd to the AP Team (P-104) and the
  escalation goes to the AP Manager (P-103), who becomes the action owner.
- Any reply stops the clock.
- A thread opened on day 4 starts its own clock, so it has no follow-up within
  the demo.

### Reply labels

| Label | Meaning | `reply_detail` |
|---|---|---|
| `approved` | Approves, confirms, or releases as asked | blank |
| `rejected` | Don't pay as billed, including "ask for a credit" | blank |
| `correction_coming` | A fix is on its way | the promised date |
| `question` | Asks a question | blank |
| `redirected` | Points to someone else | the `person_id` named |
| `unclear` | Can't be read either way; the operator decides | blank |

## How a case passes

A case passes when every column of its `expected_outcomes.csv` row matches,
and so does every thread row for it: recipient, findings, reply label and
detail, and the day 4 and day 5 actions.

Each agent job is scored only on the cases where that agent ran. Per job,
Phase 10 reports a pass rate against the 80% bar where the job has 5 or more
cases, and n of N otherwise.

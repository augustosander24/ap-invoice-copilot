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
| `possible_duplicate` | Same vendor and the same PO number, or the same invoice number once leading zeros and punctuation are removed, as a posted invoice, without being an exact match; the agent judges it a likely duplicate and AP decides. A same-number match goes to AP even when the agent says no |
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

| Kind | Looks up | Tool |
|---|---|---|
| `po` | The PO quoted on the invoice | `get_purchase_order` |
| `receipts` | Receipts against that PO | `get_goods_receipts` |
| `open_pos` | The vendor's open POs | `find_open_purchase_orders` |
| `similar_invoices` | Posted invoices from the same vendor with the same PO number, or the same invoice number once normalized | `find_similar_invoices` |
| `bill_history` | The vendor's past bills | `get_bill_history` (non-PO investigator) |
| `vendor` | The vendor master record | `get_vendor` |

`|` separates accepted alternatives. For a quantity hold, either the PO or the
receipts lookup first is accepted (`po|receipts`). The agent's first tool call
is mapped to its kind with `TOOL_KINDS` in `ap_copilot/tools.py` and scored
against this column.

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

## Held-out batches

The 22 cases above are the **tuned set**: the prompts and checks were
adjusted on them, so their results show regression, not generalization.
The held-out batches test the same agent jobs on cases no prompt was
tuned on.

| Batch | Cases | Replies | Files | Status |
|---|---|---|---|---|
| A (`heldout_a`) | 29: `EX-101`–`EX-129` (13 PO, 16 non-PO) | 18: `M-21`–`M-38` | `data/heldout_a/`, `evals/heldout_a/` | generated, keyed, frozen, run in Phase 10 |
| B (`heldout_b`) | 29: `EX-201`–`EX-229` (13 PO, 16 non-PO) | 18: `M-51`–`M-68` | `data/heldout_b/`, `evals/heldout_b/` | generated, keyed blind by the owner, frozen, run once in Phase 11 as the confirmation run |

**How they are built.** `scripts/build_heldout.py <set>` writes a batch
from its case tables, `data/heldout_tables/<set>.json`, the single source
(never typed into the CSVs). A batch copies the company master (people,
cost centers, GL accounts) from `data/reference/` and has its own
vendors, POs, receipts, and history, so no lookup returns a tuned-set
record. The data rules of the tuned set hold: text IDs, `.example`
addresses, fictional names, Decimal amounts, the same demo calendar.

**How the expected answers were checked,** before any model saw a
held-out case:

1. **By script, the code columns.** `check_data.py --set heldout_a`
   (every check, with a held-out coverage list) and `check_rules.py`,
   `check_emails.py`, and `check_followups.py --set heldout_a`, and the
   same for `heldout_b`. The
   unchanged rules engine computes each case independently of the
   generator, and every case and thread matches.
2. **By script, the judgment columns code can test:** an expected PO match
   is the only open PO of that vendor with an invoice item; a duplicate
   "yes" has the same amount, PO, and date as the posted invoice; a
   promised date or a named person passes the reply check.
3. **Blind second key.** A separate Claude agent, given only a key sheet of
   the evidence (no answers), keyed batch A's 39 judgment items: duplicate
   verdicts (5), content checks (11), category suggestions (5), and reply
   labels (18). It agreed on 38 of 39; the one miss came from the sheet
   leaving out the people on file.
4. **Domain review.** The project owner (18 years of accounts payable)
   reviewed all 39 with the expected answers shown, and changed 4: a reply
   that answers only part of the email is `unclear`; a partial approval is
   `unclear`; "I want to understand the license line before I sign off" is
   a `question`; add-ons beyond a subscription plan (extra seats, extra
   storage) don't fit the category, so AP reviews them. Two replies were
   reworded so every label keeps 3 cases. The same rules were applied to
   batch B.
5. **Batch B, keyed blind by the owner.** Before batch B's files were
   generated, the project owner keyed its 39 judgment items blind, from
   an evidence-only sheet that listed the owner's batch A rulings. Three
   of the 39 had been set by the owner when the rulings were applied to
   batch B, so they were not blind. The owner agreed with the expected
   answers on 35 of 39. The four differences were settled to the
   expected answers: two by the owner's batch A rulings (asking for a
   credit is `rejected`; a partial approval
   is `unclear`), one category read (a monthly plan for a software
   platform is a subscription), and one duplicate verdict. That invoice
   bills the same goods, PO, date, and amount as a posted invoice under
   a new number, so it bills the same charge and AP reviews it; in the
   owner's words, in AP terms it is a billing error. No case or answer
   changed.

**The seal.** Both batches' tables and batch A's files were committed
before the first held-out run, and batch B's files before its own run.
Every run file records its start time, so the history shows the answers
were fixed first.

**The bar and the rule for a shortfall.** 80% on every scored column with
5 or more cases, n of N below 5, as for the tuned set. A held-out result is
reported as it stands: no prompt, wording, fact, tool, or check changes
because of held-out outputs, and expected answers change only for a data
error the files prove. Batch B was used once, in Phase 11, as a
confirmation run of the code as it ships, with no change before or after
it. That used it up: no model or design change can be tested on held-out
data now, and there is no batch C.

**Running a batch:** add `--set heldout_a` or `--set heldout_b` to any
checker or runner, for example
`.venv\Scripts\python.exe scripts\check_rules.py --set heldout_a`.
Held-out runs save to `output/phase10/<set>/`.

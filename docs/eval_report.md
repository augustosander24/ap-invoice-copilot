# AP Invoice Copilot: evaluation report

Built by `scripts/eval_report.py` from the saved run files, the four checkers, `docs/hand_scores.csv`, and `docs/agent_history.csv`. The 22-case eval is the **tuned set**: its results show regression, not generalization. Held-out batch A is the **untuned set**: it was keyed and committed before any model saw it, and its results stand as recorded.

## 1. Summary

| Job | 22-case eval (tuned or untuned) | Fix rounds | Held-out A | Bar | Bar met on held-out A |
|---|---|---|---|---|---|
| PO investigator | 9 of 9 (100%) cases match every column; tuned: the code came from fix rounds 1-3 on these 9 cases with llama3.1:8b; qwen3:14b had no round of its own | 3 | 12 of 13 (92%) cases match every column | 80% | met |
| Non-PO investigator | 9 of 12 (75%) cases match every column; untuned | 0 | 9 of 16 (56%) cases match every column | 80% | not met: first_tool 5 of 10 |
| Reply interpreter | 18 of 18 (100%) replies; untuned, except M-08's label meaning, worded with that case in view | 0 | 16 of 18 (89%) replies | 80% | met |
| Communicator, day 0 | hand score 23 of 23 (100%); fact check first try 23 of 23 (100%); tuned: Phase 7 rounds 1-2 on these cases, then the Phase 10 rollback and one design round (5b) on the same cases | 2 (Phase 7) + rollback + 1 design round | hand score 28 of 28 (100%); fact check first try 28 of 28 (100%) | 80% | met |
| Communicator, follow-ups | hand score 7 of 7 (100%); fact check first try 7 of 7 (100%); tuned: Phase 9 fixes 1-2 on these 7 paragraphs, then the Phase 10 rollback and one design round (5b) on the same cases | 2 (Phase 9) + rollback + 1 design round | hand score 12 of 13 (92%); fact check first try 13 of 13 (100%) | 80% | met |

The non-PO first lookup scores an order between two reasonable lookups on multi-task cases (Phase 8); its number stands as recorded. A job meets the bar when every column with 5 or more cases reaches 80%; columns with fewer cases are n of N with no bar.

## 2. Rules (code only, no model)

| Checker | Data set | Last lines |
|---|---|---|
| check_data.py | 22-case eval | all checks passed |
| check_data.py | held-out A | all checks passed |
| check_rules.py | 22-case eval | 22 of 22 cases match |
| check_rules.py | held-out A | 29 of 29 cases match |
| check_emails.py | 22-case eval | threads: 21 of 21 match / 22 of 22 cases match |
| check_emails.py | held-out A | threads: 21 of 21 match / 29 of 29 cases match |
| check_followups.py | 22-case eval | replies: 18 of 18 matched to their threads / threads: 21 of 21 match / 22 of 22 cases match |
| check_followups.py | held-out A | replies: 18 of 18 matched to their threads / threads: 21 of 21 match / 29 of 29 cases match |

## 3. Each agent job

Reasoning: the 22-case runs of qwen3:14b used the model's default (it thinks by default); the held-out runs used `THINK=on`, which asks for the same thing. Run times are recorded, not scored.

### po_investigator, 22-case eval (model qwen3:14b, cap 4096 tokens, 3 h 11 min)

| Column | Cases matching |
|---|---|
| first_tool | 9 of 9 (100%) |
| duplicate_verdict | 2 of 2 (100%) (under 5: no bar) |
| po_match | 4 of 4 (100%) (under 5: no bar) |
| rules_fields | 9 of 9 (100%) |

- Task answers right on the first attempt: 6 of 12 (50%); after retries: 12 of 12 (100%); fallbacks: 0.
- Evidence-check correction rate: 6 of 6 (100%) rejected answers corrected on a retry.
- Cases with every task right on the first attempt: 4 of 9 (44%).

### nonpo_investigator, 22-case eval (model qwen3:14b, cap 4096 tokens, 48 min)

| Column | Cases matching |
|---|---|
| first_tool | 1 of 4 (25%) (under 5: no bar) |
| mismatch_flag | 8 of 8 (100%) |
| category_suggestion | 1 of 1 (100%) (under 5: no bar) |
| rules_fields | 12 of 12 (100%) |

- Task answers right on the first attempt: 12 of 12 (100%); after retries: 12 of 12 (100%); fallbacks: 0.
- Evidence-check correction rate: 0 of 0 rejected answers corrected on a retry.
- Cases with every task right on the first attempt: 12 of 12 (100%).

### reply_interpreter, 22-case eval (model qwen3:14b, cap 4096 tokens, 31 min)

- Replies matching (label and detail): 18 of 18 (100%).
- Code check corrections (the model's label made unclear by a failed date or person): 0.

| Expected label | Matching |
|---|---|
| approved | 8 of 8 (100%) |
| correction_coming | 4 of 4 (100%) |
| question | 2 of 2 (100%) |
| redirected | 1 of 1 (100%) |
| rejected | 2 of 2 (100%) |
| unclear | 1 of 1 (100%) |

### po_investigator, held-out A (model qwen3:14b, cap 4096 tokens, 4 h 14 min)

| Column | Cases matching |
|---|---|
| first_tool | 13 of 13 (100%) |
| duplicate_verdict | 4 of 5 (80%) |
| po_match | 7 of 7 (100%) |
| rules_fields | 13 of 13 (100%) |

- Task answers right on the first attempt: 11 of 18 (61%); after retries: 17 of 18 (94%); fallbacks: 1.
- Evidence-check correction rate: 6 of 7 (86%) rejected answers corrected on a retry.
- Cases with every task right on the first attempt: 7 of 13 (54%).
- Explanations by hand: 5 of 6 (83%).

### nonpo_investigator, held-out A (model qwen3:14b, cap 4096 tokens, 1 h 34 min)

| Column | Cases matching |
|---|---|
| first_tool | 5 of 10 (50%) |
| mismatch_flag | 9 of 11 (82%) |
| category_suggestion | 5 of 5 (100%) |
| rules_fields | 14 of 16 (88%) |

- Task answers right on the first attempt: 20 of 21 (95%); after retries: 21 of 21 (100%); fallbacks: 0.
- Evidence-check correction rate: 1 of 1 (100%) rejected answers corrected on a retry.
- Cases with every task right on the first attempt: 15 of 16 (94%).
- Explanations by hand: 5 of 5 (100%).

### reply_interpreter, held-out A (model qwen3:14b, cap 4096 tokens, 26 min)

- Replies matching (label and detail): 16 of 18 (89%).
- Code check corrections (the model's label made unclear by a failed date or person): 1; M-29 said correction_coming.

| Expected label | Matching |
|---|---|
| approved | 3 of 3 (100%) |
| correction_coming | 3 of 3 (100%) |
| question | 3 of 3 (100%) |
| redirected | 3 of 3 (100%) |
| rejected | 3 of 3 (100%) |
| unclear | 1 of 3 (33%) |

Earlier runs, from `docs/agent_history.csv`:

| Job | Phase | Run | Model | Result | Tuned? | Fix rounds | Note |
|---|---|---|---|---|---|---|---|
| po_investigator | 6 | 1 | llama3.1:8b | 5 of 9 | untuned | 0 | First live run, before any fix |
| po_investigator | 6 | 2 | llama3.1:8b | 5 of 9 | tuned | 1 | After fix round 1: tool-call handling, evidence rules, duplicate-task wording |
| po_investigator | 6 | 3 | llama3.1:8b | 8 of 9 | tuned | 2 | After fix round 2: one fresh single-turn request per model call; EX-008 duplicate verdict missed |
| po_investigator | 6 | 4 | qwen3:14b | 9 of 9 | tuned: the code came from fix rounds 1-3 on these 9 cases with llama3.1:8b; qwen3:14b had no round of its own | 3 | first_tool 9 of 9, duplicate_verdict 2 of 2, po_match 4 of 4, rules_fields 9 of 9; 8 retries, 0 fallbacks; 4 of 9 cases right on the first attempt; 56 model calls, 3 h 11 min |
| nonpo_investigator | 8 | 1 | llama3.1:8b | 8 of 12 | untuned | 0 | first_tool 2 of 4, mismatch 7 of 8 (EX-018 missed), category 0 of 1; 0 retries, 0 fallbacks; 21 calls, 595 s; explanations by hand 2 of 3 |
| nonpo_investigator | 8 | 2 | qwen3:14b | 9 of 12 | untuned | 0 | first_tool 1 of 4, mismatch 8 of 8, category 1 of 1; 0 retries, 0 fallbacks; 19 calls, about 48 min; explanations by hand 3 of 3; the first lookup stands as recorded with no eval or prompt change (2026-11-04) |
| reply_interpreter | 9 | 1 | llama3.1:8b | 17 of 18 | untuned | 0 | M-15 read as a question; 3.5 min |
| reply_interpreter | 9 | 2 | qwen3:14b | 18 of 18 | untuned, except M-08's label meaning, worded with that case in view | 0 | 0 check failures; 31.5 min |
| communicator_day0 | 7 | 1 | llama3.1:8b | fact check 23 of 23; by hand 17 of 23 | untuned | 0 | Phase 7 run 1 |
| communicator_day0 | 7 | 2 | llama3.1:8b | fact check 23 of 23; by hand 19 of 23 | tuned | 1 | After Phase 7 fix round 1 (wording) |
| communicator_day0 | 7 | 3 | llama3.1:8b | fact check 23 of 23; by hand 23 of 23 | tuned | 2 | After Phase 7 fix round 2 (labeled figures) |
| communicator_day0 | 8 | 1 | llama3.1:8b | fact check 23 of 23; the 3 new paragraphs 3 of 3 by hand | untuned (new paragraphs only) | 2 | Phase 8: EX-012, EX-013, EX-014 approvals |
| communicator_day0 | 10 | 2 | llama3.1:8b | see section 4 | tuned: Phase 7 rounds 1-2 on these cases, then the Phase 10 rollback and one design round (5b) on the same cases | 2 (Phase 7) + rollback + 1 design round | Phase 10 on the 22-case eval, from the narrower writer_facts |
| communicator_followup | 9 | 1 | llama3.1:8b | fact check 7 of 7; by hand 4 of 7 | untuned | 0 | Phase 9 first run |
| communicator_followup | 9 | 2 | llama3.1:8b | fact check 7 of 7; by hand 5 of 7 | tuned | 1 | After Phase 9 fix 1 (fact names: whose email, which date) |
| communicator_followup | 9 | 3 | llama3.1:8b | fact check 7 of 7; by hand 7 of 7 | tuned | 2 | After Phase 9 fix 2 (the reminder's own deadline; Ask <vendor> to ...) |
| communicator_followup | 10 | 2 | llama3.1:8b | see section 4 | tuned: Phase 9 fixes 1-2 on these 7 paragraphs, then the Phase 10 rollback and one design round (5b) on the same cases | 2 (Phase 9) + rollback + 1 design round | Phase 10 on the 22-case eval, from the narrower writer_facts |

## 4. Communicator (llama3.1:8b, cap 512 tokens)

| Set | Paragraphs | Fact check, first try | Read correctly by hand | Time |
|---|---|---|---|---|
| eval, run 1 (before 5b) | day 0 | 23 of 23 (100%) | 20 of 23 (87%) (hand run 1) | 4 min |
| eval, run 1 (before 5b) | follow-ups | 7 of 7 (100%) | 7 of 7 (100%) (hand run 1) | 2 min |
| eval | day 0 | 23 of 23 (100%) | 23 of 23 (100%) (hand run 2) | 4 min |
| eval | follow-ups | 7 of 7 (100%) | 7 of 7 (100%) (hand run 2) | 2 min |
| heldout_a | day 0 | 28 of 28 (100%) | 28 of 28 (100%) (hand run 1) | 5 min |
| heldout_a | follow-ups | 13 of 13 (100%) | 12 of 13 (92%) (hand run 1) | 3 min |

The fact check proves figures and names exist in the facts, not that a sentence is right; the hand score reads each paragraph the model wrote, before any operator edit. The eval's paragraphs are design-informed (Phase 7 rounds, Phase 9 fixes, the Phase 10 rollback); the held-out paragraphs are not.

## 5. Caps

A call stops at its cap, thinking tokens included. `done_reason` is blank in runs before Phase 10.

| Set | Agent | Calls | Longest prompt (tokens) | Longest reply | Cut by the cap |
|---|---|---|---|---|---|
| eval | po_investigator | 56 | 1867 | 1792 of 4096 | 0 |
| eval | nonpo_investigator | 19 | 1732 | 802 of 4096 | 0 |
| eval | reply_interpreter | 18 | 333 | 1373 of 4096 | 0 |
| eval | communicator | 30 | 243 | 104 of 512 | 0 |
| held-out A | po_investigator | 69 | 1796 | 4096 of 4096 | 1 |
| held-out A | nonpo_investigator | 39 | 1786 | 912 of 4096 | 0 |
| held-out A | reply_interpreter | 18 | 338 | 686 of 4096 | 0 |
| held-out A | communicator | 41 | 253 | 105 of 512 | 0 |

## 6. Per-case appendix

Each cell is what the agent gave / what the eval expects; ✗ marks a miss.

### po investigator, 22-case eval

| Case | First lookup | Duplicate | PO match | Content mismatch | Category | Rules fields | Attempts | Fallbacks | Explanations (hand) |
|---|---|---|---|---|---|---|---|---|---|
| EX-001 | po / po | - | - | - | - | ok | 2 | 0 | - |
| EX-002 | po / po | - | - | - | - | ok | 2 | 0 | - |
| EX-003 | po / po\|open_pos | - | none / none | - | - | ok | 1 | 0 | - |
| EX-004 | receipts / po\|receipts | - | - | - | - | ok | 1 | 0 | - |
| EX-005 | po / po\|receipts | - | - | - | - | ok | 1 | 0 | - |
| EX-006 | similar_invoices / po\|open_pos\|similar_invoices | no / no | PO-26106 / PO-26106 | - | - | ok | 3 | 0 | - |
| EX-007 | open_pos / open_pos | - | PO-26107 / PO-26107 | - | - | ok | 1 | 0 | - |
| EX-008 | similar_invoices / similar_invoices\|po | yes / yes | none / none | - | - | ok | 3 | 0 | - |
| EX-009 | po / po | - | - | - | - | ok | 3 | 0 | - |

### nonpo investigator, 22-case eval

| Case | First lookup | Duplicate | PO match | Content mismatch | Category | Rules fields | Attempts | Fallbacks | Explanations (hand) |
|---|---|---|---|---|---|---|---|---|---|
| EX-011 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-012 | vendor / bill_history ✗ | - | - | no / no | - | ok | 1 | 0 | - |
| EX-013 | vendor / bill_history ✗ | - | - | no / no | - | ok | 1 | 0 | - |
| EX-014 | vendor / vendor\|bill_history | - | - | no / no | - | ok | 1 | 0 | - |
| EX-015 | - | - | - | - | - | ok | 0 | 0 | - |
| EX-016 | - | - | - | - | - | ok | 0 | 0 | - |
| EX-017 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-018 | - | - | - | yes / yes | - | ok | 1 | 0 | - |
| EX-019 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-020 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-021 | - | - | - | - | - | ok | 0 | 0 | - |
| EX-022 | none / vendor ✗ | - | - | - | subscriptions / subscriptions | ok | 1 | 0 | - |

### reply interpreter, 22-case eval

| Reply | Email | Got / expected | Model said | Check |
|---|---|---|---|---|
| M-01 | EX-001:P-106:buyer_query | approved / approved | - | - |
| M-02 | EX-007:V-1003:vendor_correction | correction_coming 2026-12-02 / correction_coming 2026-12-02 | - | - |
| M-03 | EX-009:V-1004:vendor_correction | correction_coming 2026-12-01 / correction_coming 2026-12-01 | - | - |
| M-04 | EX-010:V-2001:duplicate_notice | approved / approved | - | - |
| M-05 | EX-016:P-102:approval_request | approved / approved | - | - |
| M-06 | EX-019:P-102:service_confirmation | approved / approved | - | - |
| M-07 | EX-006:V-1003:vendor_correction | correction_coming 2026-12-03 / correction_coming 2026-12-03 | - | - |
| M-08 | EX-004:P-106:buyer_query | correction_coming 2026-12-09 / correction_coming 2026-12-09 | - | - |
| M-09 | EX-009:P-107:buyer_query | approved / approved | - | - |
| M-10 | EX-013:P-108:approval_request | approved / approved | - | - |
| M-11 | EX-017:P-102:approval_request | question / question | - | - |
| M-12 | EX-020:P-112:service_confirmation | approved / approved | - | - |
| M-13 | EX-005:P-107:buyer_query | redirected P-106 / redirected P-106 | - | - |
| M-14 | EX-003:V-1001:vendor_correction | question / question | - | - |
| M-15 | EX-018:P-110:approval_request | unclear / unclear | - | - |
| M-16 | EX-014:P-108:approval_request | rejected / rejected | - | - |
| M-17 | EX-002:P-107:buyer_query | rejected / rejected | - | - |
| M-18 | EX-019:P-101:approval_request | approved / approved | - | - |

### communicator paragraphs, 22-case eval

| Email | Done reason | Fact check | Hand verdict | Note |
|---|---|---|---|---|
| EX-001:P-106:buyer_query | stop | passed | correct |  |
| EX-002:P-107:buyer_query | stop | passed | correct |  |
| EX-003:V-1001:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-004:P-106:buyer_query | stop | passed | correct |  |
| EX-005:P-107:buyer_query | stop | passed | correct |  |
| EX-006:V-1003:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-007:V-1003:vendor_correction | stop | passed | correct |  |
| EX-008:V-1003:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-008:V-1003:duplicate_notice | stop | passed | correct |  |
| EX-009:P-107:buyer_query | stop | passed | correct |  |
| EX-009:V-1004:vendor_correction | stop | passed | correct |  |
| EX-010:V-2001:duplicate_notice | stop | passed | correct |  |
| EX-012:P-109:approval_request | stop | passed | correct |  |
| EX-013:V-2003:vendor_correction | stop | passed | correct |  |
| EX-013:P-108:approval_request | stop | passed | correct | Style: 'required to approve' without 'or reject'; ends 'Approval is needed.' (redundant) |
| EX-014:P-108:approval_request | stop | passed | correct |  |
| EX-016:P-102:approval_request | stop | passed | correct |  |
| EX-017:P-102:approval_request | stop | passed | correct |  |
| EX-018:P-110:approval_request | stop | passed | correct |  |
| EX-019:P-102:service_confirmation | stop | passed | correct | Style: the confirmation is called 'an issue' |
| EX-019:P-101:approval_request | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |
| EX-020:P-112:service_confirmation | stop | passed | correct | Style: the confirmation is called 'an issue' |
| EX-020:P-110:approval_request | stop | passed | correct |  |
| EX-002:P-107:buyer_query:reminder | stop | passed | correct |  |
| EX-008:V-1003:duplicate_notice:reminder | stop | passed | correct |  |
| EX-008:V-1003:duplicate_notice:escalation | stop | passed | correct | Style: 'You have been escalated' |
| EX-012:P-109:approval_request:reminder | stop | passed | correct |  |
| EX-012:P-109:approval_request:escalation | stop | passed | correct | Style: says a reminder was 'ignored' |
| EX-013:V-2003:vendor_correction:reminder | stop | passed | correct |  |
| EX-013:V-2003:vendor_correction:escalation | stop | passed | correct |  |

### po investigator, held-out A

| Case | First lookup | Duplicate | PO match | Content mismatch | Category | Rules fields | Attempts | Fallbacks | Explanations (hand) |
|---|---|---|---|---|---|---|---|---|---|
| EX-101 | po / po | - | - | - | - | ok | 1 | 0 | correct |
| EX-102 | po / po | - | - | - | - | ok | 2 | 0 | correct |
| EX-103 | po / po\|receipts | - | - | - | - | ok | 1 | 0 | misread |
| EX-104 | po / po\|receipts | - | - | - | - | ok | 1 | 0 | correct |
| EX-105 | po / po\|receipts | - | - | - | - | ok | 1 | 0 | correct, correct |
| EX-106 | open_pos / open_pos | - | PO-27106 / PO-27106 | - | - | ok | 1 | 0 | - |
| EX-107 | open_pos / po\|open_pos | - | PO-27107 / PO-27107 | - | - | ok | 1 | 0 | - |
| EX-108 | po / po\|open_pos | - | none / none | - | - | ok | 1 | 0 | - |
| EX-109 | similar_invoices / po\|open_pos\|similar_invoices | no / no | PO-27109 / PO-27109 | - | - | ok | 2 | 0 | - |
| EX-110 | similar_invoices / po\|open_pos\|similar_invoices | yes / yes | none / none | - | - | ok | 2 | 0 | - |
| EX-111 | similar_invoices / po\|open_pos\|similar_invoices | yes / yes | none / none | - | - | ok | 2 | 0 | - |
| EX-112 | similar_invoices / similar_invoices | yes / no ✗ | - | - | - | ok | 3 | 1 | - |
| EX-113 | similar_invoices / po\|open_pos\|similar_invoices | yes / yes | none / none | - | - | ok | 2 | 0 | - |

### nonpo investigator, held-out A

| Case | First lookup | Duplicate | PO match | Content mismatch | Category | Rules fields | Attempts | Fallbacks | Explanations (hand) |
|---|---|---|---|---|---|---|---|---|---|
| EX-114 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-115 | bill_history / bill_history | - | - | no / no | - | ok | 1 | 0 | correct |
| EX-116 | vendor / bill_history ✗ | - | - | no / no | - | ok | 2 | 0 | correct |
| EX-117 | vendor / bill_history ✗ | - | - | no / no | - | ok | 1 | 0 | correct |
| EX-118 | - | - | - | no / yes ✗ | - | findings: got none, expected category_mismatch; recommendation: got release, expected hold | 1 | 0 | - |
| EX-119 | vendor / vendor\|bill_history | - | - | no / no | - | ok | 1 | 0 | correct |
| EX-120 | vendor / vendor\|bill_history | - | - | yes / yes | - | ok | 1 | 0 | correct |
| EX-121 | - | - | - | no / yes ✗ | - | findings: got approval_required, expected approval_required;category_mismatch | 1 | 0 | - |
| EX-122 | - | - | - | yes / yes | - | ok | 1 | 0 | - |
| EX-123 | - | - | - | no / no | - | ok | 1 | 0 | - |
| EX-124 | - | - | - | yes / yes | - | ok | 1 | 0 | - |
| EX-125 | vendor / vendor | - | - | - | utilities / utilities | ok | 1 | 0 | - |
| EX-126 | none / vendor ✗ | - | - | - | rent / rent | ok | 1 | 0 | - |
| EX-127 | none / vendor ✗ | - | - | - | subscriptions / subscriptions | ok | 1 | 0 | - |
| EX-128 | vendor / vendor | - | - | - | professional_services / professional_services | ok | 1 | 0 | - |
| EX-129 | none / vendor ✗ | - | - | - | taxes / taxes | ok | 1 | 0 | - |

### reply interpreter, held-out A

| Reply | Email | Got / expected | Model said | Check |
|---|---|---|---|---|
| M-21 | EX-101:P-106:buyer_query | approved / approved | - | - |
| M-26 | EX-106:V-1103:vendor_correction | redirected P-107 / redirected P-107 | - | - |
| M-31 | EX-119:P-108:approval_request | redirected P-109 / redirected P-109 | - | - |
| M-35 | EX-123:P-111:service_confirmation | approved / approved | - | - |
| M-22 | EX-101:V-1101:vendor_correction | correction_coming 2026-12-03 / correction_coming 2026-12-03 | - | - |
| M-23 | EX-102:P-107:buyer_query | question / question | - | - |
| M-25 | EX-105:P-106:buyer_query | correction_coming 2026-12-03 / unclear ✗ | - | - |
| M-28 | EX-109:V-1101:vendor_correction | correction_coming 2026-12-04 / correction_coming 2026-12-04 | - | - |
| M-29 | EX-115:P-108:approval_request | unclear / unclear | correction_coming | the date 2026-12-09 is not in the reply |
| M-33 | EX-121:P-102:approval_request | redirected P-103 / redirected P-103 | - | - |
| M-37 | EX-124:P-112:service_confirmation | approved / approved | - | - |
| M-24 | EX-104:P-107:buyer_query | rejected / rejected | - | - |
| M-27 | EX-108:V-1102:vendor_correction | correction_coming 2026-12-04 / correction_coming 2026-12-04 | - | - |
| M-32 | EX-120:P-109:approval_request | rejected / unclear ✗ | - | - |
| M-34 | EX-122:P-110:approval_request | rejected / rejected | - | - |
| M-30 | EX-116:P-109:approval_request | question / question | - | - |
| M-36 | EX-123:P-108:approval_request | rejected / rejected | - | - |
| M-38 | EX-124:P-110:approval_request | question / question | - | - |

### communicator paragraphs, held-out A

| Email | Done reason | Fact check | Hand verdict | Note |
|---|---|---|---|---|
| EX-101:P-106:buyer_query | stop | passed | correct |  |
| EX-101:V-1101:vendor_correction | stop | passed | correct |  |
| EX-102:P-107:buyer_query | stop | passed | correct |  |
| EX-103:P-106:buyer_query | stop | passed | correct |  |
| EX-104:P-107:buyer_query | stop | passed | correct |  |
| EX-105:P-106:buyer_query | stop | passed | correct |  |
| EX-106:V-1103:vendor_correction | stop | passed | correct |  |
| EX-107:V-1104:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-108:V-1102:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-109:V-1101:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-110:V-1104:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-110:V-1104:duplicate_notice | stop | passed | correct |  |
| EX-111:V-1102:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-111:V-1102:duplicate_notice | stop | passed | correct |  |
| EX-112:V-1103:duplicate_notice | stop | passed | correct |  |
| EX-113:V-1101:vendor_correction | stop | passed | correct | Style: 'unable to verify ... valid' |
| EX-113:V-1101:duplicate_notice | stop | passed | correct |  |
| EX-115:P-108:approval_request | stop | passed | correct |  |
| EX-116:P-109:approval_request | stop | passed | correct |  |
| EX-117:P-108:approval_request | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |
| EX-119:P-108:approval_request | stop | passed | correct |  |
| EX-120:P-109:approval_request | stop | passed | correct |  |
| EX-121:P-102:approval_request | stop | passed | correct |  |
| EX-122:P-110:approval_request | stop | passed | correct |  |
| EX-123:P-111:service_confirmation | stop | passed | correct | Style: the confirmation is called 'an issue' |
| EX-123:P-108:approval_request | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |
| EX-124:P-112:service_confirmation | stop | passed | correct | Style: the confirmation is called 'an issue' |
| EX-124:P-110:approval_request | stop | passed | correct |  |
| EX-103:P-106:buyer_query:reminder | stop | passed | correct |  |
| EX-103:P-106:buyer_query:escalation | stop | passed | correct | Style: 'You have been escalated'; says a reminder was 'ignored' |
| EX-107:V-1104:vendor_correction:reminder | stop | passed | correct |  |
| EX-107:V-1104:vendor_correction:escalation | stop | passed | misread | Misread: 'the issues found are that a valid open purchase order number cannot be used' turns the ask into the issue |
| EX-110:V-1104:duplicate_notice:reminder | stop | passed | correct |  |
| EX-110:V-1104:duplicate_notice:escalation | stop | passed | correct | Style: 'You have been escalated' |
| EX-111:V-1102:duplicate_notice:reminder | stop | passed | correct |  |
| EX-111:V-1102:duplicate_notice:escalation | stop | passed | correct | Style: 'You have been escalated' |
| EX-113:V-1101:duplicate_notice:reminder | stop | passed | correct |  |
| EX-113:V-1101:duplicate_notice:escalation | stop | passed | correct | Style: 'You have been escalated' |
| EX-116:P-109:approval_request:reminder | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |
| EX-117:P-108:approval_request:reminder | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |
| EX-117:P-108:approval_request:escalation | stop | passed | correct | Style: ends 'Approval is needed.' (redundant) |

## 7. Provenance

Commit `8a81692` (batch A frozen): 2026-11-06T16:55:53-03:00.

| File read | First case started | File saved |
|---|---|---|
| output/phase6/po_run_qwen3-14b.json | not recorded | 2026-10-31T14:37:34-03:00 |
| output/phase8/nonpo_run_qwen3-14b.json | not recorded | 2026-11-04T13:27:16-03:00 |
| output/phase9/replies_qwen3-14b.json | not recorded | 2026-11-05T14:52:57-03:00 |
| output/phase10/emails_llama3.1-8b.json | not recorded | 2026-11-06T14:29:37-03:00 |
| output/phase10/day_2026-12-04.json | not recorded | 2026-11-06T14:31:06-03:00 |
| output/phase10/day_2026-12-07.json | not recorded | 2026-11-06T14:32:04-03:00 |
| output/phase10/heldout_a/po_run_qwen3-14b.json | 2026-11-06T17:10:46-03:00 | 2026-11-07T16:15:41-03:00 |
| output/phase10/heldout_a/nonpo_run_qwen3-14b.json | 2026-11-07T16:15:49-03:00 | 2026-11-07T17:49:51-03:00 |
| output/phase10/heldout_a/replies_qwen3-14b.json | 2026-11-06T18:42:41-03:00 | 2026-11-06T19:09:10-03:00 |
| output/phase10/heldout_a/emails_llama3.1-8b.json | not recorded | 2026-11-07T18:25:25-03:00 |
| output/phase10/heldout_a/day_2026-12-04.json | not recorded | 2026-11-07T18:28:16-03:00 |
| output/phase10/heldout_a/day_2026-12-07.json | not recorded | 2026-11-07T18:30:17-03:00 |

Held-out runs after commit B: 6 of 6 files started or saved after it. Day-0 and day runs record no start time; they replay the investigator and interpreter runs, which do, so they cannot have started earlier.

Also read: `docs/hand_scores.csv`, `docs/agent_history.csv`, `evals/expected_outcomes.csv`, `evals/heldout_a/expected_outcomes.csv`, and the output of the four checkers.

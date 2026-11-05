"""Email drafts for AP Invoice Copilot.

Code builds every email from the Outcome's actions, its fact lines, and the investigator's
accepted answers: the recipient, each issue with its facts, the action requested, and the
reply-by date. The communicator model writes one short paragraph from those facts only; a
fact check rejects any number or name that is not in them, and a fixed sentence replaces a
rejected paragraph. Nothing is sent: these are drafts.
"""

import json
import re
from datetime import date, timedelta

from ap_copilot.evidence import FALLBACK_EXPLANATION, numbers_in
from ap_copilot.rules import AP_MANAGER, AP_TEAM, FINDINGS, Assessment, normalize_invoice_number

COMPANY = "Northgate Distribution"
AP_ADDRESS = "ap@northgate.example"
EXPORT_DATE = "2026-11-30"  # demo day 0; a follow-up run's date is its as_of
REPLY_DAYS = 3
FOLLOW_UP_REPLY_DAYS = 1  # a reminder or an escalation is due within 24 hours (one business day)

TEMPLATES = {"buyer": "buyer_query", "vendor": "vendor_correction", "approver": "approval_request",
             "requester": "service_confirmation"}
ROLE_LABELS = {"buyer": "buyer", "vendor": "vendor", "approver": "approver", "requester": "requester of the service"}
SUBJECTS = {
    "buyer_query": "Your decision needed: invoice {number} from {vendor}",
    "vendor_correction": "Correction needed: invoice {number}",
    "duplicate_notice": "Duplicate invoice: {number}",
    "approval_request": "Approval needed: invoice {number} from {vendor}",
    "service_confirmation": "Please confirm the service: invoice {number} from {vendor}",
    "reminder": "Reminder: {subject}",
    "escalation": "Escalation: {subject}",
}
ISSUE_TITLES = {
    "price_variance": "Price differs from the PO",
    "quantity_variance": "Billed quantity is more than received",
    "missing_po": "No PO number on the invoice",
    "invalid_po": "PO number can't be used",
    "exact_duplicate": "Duplicate invoice",
    "possible_duplicate": "Duplicate invoice",
    "missing_data": "Missing or incorrect invoice details",
    "approval_required": "Approval needed",
    "confirmation_required": "Service confirmation needed",
}
ACTIONS = {
    "price_variance": "Tell us whether to pay the billed price and update the PO, reject the invoice, "
                      "or ask the vendor for a credit.",
    "quantity_variance": "Tell us whether the missing quantity has arrived and the receipt is posted, "
                         "or whether to reject the invoice or ask the vendor for a credit.",
    "missing_po": "Send a corrected invoice that quotes the purchase order number.",
    "invalid_po": "Send a corrected invoice that quotes a valid open purchase order number.",
    "exact_duplicate": "Confirm that this invoice is a duplicate so we can void it, "
                       "or tell us if it is a separate charge.",
    "possible_duplicate": "Confirm that this invoice is a duplicate so we can void it, "
                          "or tell us if it is a separate charge.",
    "missing_data": "Send a corrected invoice with the missing or incorrect details fixed.",
    "approval_required": "Approve or reject this invoice.",
    "confirmation_required": "Confirm that the service was received, or tell us what is wrong.",
}
WAITING_REPLY_BY = "set when this email is sent, after the service confirmation"
FALLBACK_PARAGRAPH = "Please see the invoice details and the action requested below."

_EVIDENCE_ID = re.compile(r"\b(po_line|invoice_line|receipts|receipt|po|posted|open_pos|similar_invoices|vendor"
                          r"|invoice|bill_history):([A-Za-z0-9-]+)(?::([A-Za-z0-9-]+))?")

# The investigator's explanations an issue shows, each with its key in the email's facts; the label is in render().
EXPLANATIONS = {"price_variance": (("price_variance_explanation", "likely_cause"),),
                "quantity_variance": (("quantity_variance_explanation", "likely_cause"),),
                "approval_required": (("bill_change_explanation", "from_our_review"),
                                      ("rent_difference_explanation", "from_our_review"))}

WRITER_SYSTEM_PROMPT = ("You write one short paragraph (2 to 4 sentences) for an accounts payable email to the "
                        "{recipient}. Use only the facts given. Do not add any number, date, or name that is not "
                        "in the facts. Use each figure only with the meaning its fact gives it, and do not state "
                        "anything as done or certain unless the facts say so. Address the recipient as \"you\". "
                        "No greeting and no sign-off.")
MAX_SENTENCES = 5
ALLOWED_WORDS = {"I", "AP", "PO", "POs", "OK", "January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December", "Monday", "Tuesday", "Wednesday",
                 "Thursday", "Friday"}

_ID = re.compile(r"\b[A-Za-z]+-[A-Za-z0-9-]*\d[A-Za-z0-9-]*\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z'&-]*")
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def add_business_days(day: str, count: int) -> str:
    """The date count business days after day (Monday to Friday; no holidays), as YYYY-MM-DD."""
    current = date.fromisoformat(day)
    while count:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count -= 1
    return current.isoformat()


def readable(text: str) -> str:
    """Agent text with its evidence IDs written as record names: po_line:PO-26108:1 → PO-26108 line 1."""
    labels = {"po_line": "{first} line {second}", "invoice_line": "invoice line {second}",
              "receipts": "the {first} receipts", "receipt": "receipt {first}", "po": "{first}",
              "posted": "posted invoice {second}", "open_pos": "the open POs",
              "similar_invoices": "the posted invoices", "vendor": "the vendor record", "invoice": "the invoice",
              "bill_history": "the bill history"}
    text = re.sub(r"\s*\(evidence_id [^)]*\)", "", text).replace("evidence_id ", "")
    return _EVIDENCE_ID.sub(lambda match: labels[match.group(1)].format(first=match.group(2),
                                                                       second=match.group(3) or ""), text)


def _recipient(recipient_id: str, ref) -> dict[str, str]:
    """The recipient's name, email, and greeting: a vendor's accounts receivable team, or a person's first name."""
    if recipient_id in ref.vendors:
        vendor = ref.vendors[recipient_id]
        return {"name": vendor["vendor_name"], "email": vendor["contact_email"],
                "greeting": "{vendor_name} accounts receivable team".format(vendor_name=vendor["vendor_name"])}
    person = ref.people[recipient_id]
    return {"name": person["name"], "email": person["email"], "greeting": person["name"].split()[0]}


def _line_text(line) -> str:
    """One invoice line as the email shows it."""
    if line.quantity is None:
        return f"line {line.line}: {line.description}: amount {line.line_amount}"
    item = f"{line.item} " if line.item else ""
    return (f"line {line.line}: {item}{line.description}: {line.quantity} units at {line.unit_price} each, "
            f"line amount {line.line_amount}")


def _invoice_facts(assessment: Assessment, outcome: dict, ref, template: str) -> dict:
    """The invoice header and lines as the email shows them."""
    invoice = assessment.invoice
    facts = {"invoice_number": invoice.invoice_number, "vendor": invoice.vendor_name,
             "invoice_date": invoice.invoice_date,
             "amount": str(invoice.amount) if invoice.amount is not None else "blank"}
    if outcome["path"] == "po":
        facts["po_number"] = invoice.po_number or "none"
    if invoice.service_month:
        facts["service_month"] = invoice.service_month
    if template in ("approval_request", "service_confirmation"):
        cost_center = ref.vendors[invoice.vendor_id]["cost_center"]
        facts["cost_center"] = f"{ref.cost_centers[cost_center]['name']} ({cost_center})"
        if outcome["gl_account"]:
            facts["gl_account"] = outcome["gl_account"]
        if invoice.requester_id:
            facts["requester"] = ref.people[invoice.requester_id]["name"]
    facts["lines"] = [_line_text(line) for line in invoice.lines]
    return facts


def _po_suggestion(assessment: Assessment, accepted: dict, ref) -> str:
    """The open PO the investigator matched, with the items it shares with the invoice; "" when there is none."""
    match = accepted.get("po_match") or {}
    po = str(match.get("po_number", "")).strip()
    if not po or po.lower() == "none":
        return ""
    po_items = {row["item"] for (number, _), row in ref.po_lines.items() if number == po}
    items = sorted(po_items & {line.item for line in assessment.invoice.lines})
    return ("Our open purchase order {po} includes the item(s) on this invoice ({items}). If that is the order "
            "you shipped against, please quote it.").format(po=po, items=", ".join(items))


def _duplicate_facts(assessment: Assessment, ref) -> list[str]:
    """The duplicate notice's lines: one per posted invoice the duplicate check compared."""
    invoice = assessment.invoice
    request = next((r for r in assessment.agent_requests if r.kind == "duplicate_check"), None)
    posted = {row["invoice_number"]: row for row in ref.history.get(invoice.vendor_id, ())}
    lines = []
    for number in (request.detail if request else ()):
        row = posted[number]
        basis = []
        if invoice.po_number and row["po_number"] == invoice.po_number:
            basis.append(f"the same purchase order ({invoice.po_number})")
        if normalize_invoice_number(number) == normalize_invoice_number(invoice.invoice_number):
            basis.append(f"the same invoice number once leading zeros and punctuation are dropped "
                         f"({invoice.invoice_number} and {number})")
        lines.append(f"this invoice matches invoice {number} dated {row['invoice_date']} for {row['amount']}, "
                     f"which we have already received and posted: {' and '.join(basis)}")
    return lines


def _issues(findings: list[str], vendor_facing: bool, outcome: dict, accepted: dict,
            assessment: Assessment, ref) -> list[dict]:
    """One issue per finding: its title, its fact lines (each line once per email), and what the investigator found."""
    shown = set()
    issues = []
    for finding in findings:
        if finding == "possible_duplicate":
            facts = _duplicate_facts(assessment, ref)
        else:
            facts = []
            for n, record in enumerate(outcome["fact_records"]):
                if finding in record["findings"] and n not in shown:
                    shown.add(n)
                    wording = record["email_text"] or record["text"]
                    facts.append((record["vendor_text"] or wording) if vendor_facing else wording)
        issue = {"issue": ISSUE_TITLES[finding], "facts": facts}
        for task, key in EXPLANATIONS.get(finding, ()):
            explanation = accepted.get(task, {}).get("explanation", "")
            if explanation and explanation != FALLBACK_EXPLANATION:
                issue[key] = readable(explanation)
        if finding in ("invalid_po", "missing_po"):
            suggestion = _po_suggestion(assessment, accepted, ref)
            if suggestion:
                issue["possible_po"] = suggestion
        issues.append(issue)
    return issues


def _email(assessment, outcome, accepted, ref, as_of, recipient_id, roles, findings, template, status,
           release_on, opens_after, follow_up) -> dict:
    """One draft: who it goes to, its facts, and its text. The paragraph is written later."""
    invoice = assessment.invoice
    to = _recipient(recipient_id, ref)
    facts = {"recipient": f"{to['name']} ({' and '.join(ROLE_LABELS[role] for role in roles)})",
             **_invoice_facts(assessment, outcome, ref, template),
             "issues": _issues(findings, "vendor" in roles, outcome, accepted, assessment, ref),
             "action_requested": list(dict.fromkeys(ACTIONS[finding] for finding in findings)),
             "sender": f"Accounts Payable, {COMPANY}"}
    draft = {"email_id": f"{invoice.exception_id}:{recipient_id}:{template}", "exception_id": invoice.exception_id,
             "recipient_id": recipient_id, "roles": list(roles), "template": template, "findings": list(findings),
             "status": status, "release_on": release_on, "opens_after": opens_after,
             "to_name": to["name"], "to_email": to["email"], "greeting": to["greeting"],
             "subject": SUBJECTS[template].format(number=invoice.invoice_number, vendor=invoice.vendor_name),
             "facts": facts, "paragraph": "", "paragraph_source": "", "fact_check": [],
             "reply_by": "" if opens_after else add_business_days(as_of, REPLY_DAYS), "sent_on": "",
             **follow_up}
    draft["body"] = render(draft)
    return draft


def draft_emails(assessment: Assessment, outcome: dict, accepted: dict, ref, as_of: str = EXPORT_DATE) -> list[dict]:
    """Every email for one invoice: one per recipient and send moment, none for the AP queue.

    Actions for the same recipient are merged into one email (design section 8). On a possible
    duplicate the drafts are held and go out if AP clears it ("not_duplicate"), and a held
    duplicate notice to the vendor goes out instead if AP confirms it ("duplicate").
    """
    groups = {}
    for action in outcome["actions"]:
        if action["role"] == "ap_queue":
            continue
        group = groups.setdefault((action["recipient_id"], action["after"]),
                                  {"roles": [], "findings": [], "statuses": []})
        group["roles"].append(action["role"])
        group["findings"].extend(action["findings"])
        group["statuses"].append(action["status"])
        group["follow_up"] = {"reminder_cc": action["reminder_cc"], "escalation_to": action["escalation_to"]}
    possible_duplicate = "possible_duplicate" in outcome["findings"]
    emails = []
    for (recipient_id, after), group in sorted(groups.items(), key=lambda item: item[0][1] != ""):
        findings = [finding for finding in FINDINGS if finding in group["findings"]]
        template = "duplicate_notice" if "exact_duplicate" in findings else TEMPLATES[group["roles"][0]]
        if "held" in group["statuses"]:
            status = "held"
        elif after:
            status = "waiting"
        else:
            status = "send"
        emails.append(_email(assessment, outcome, accepted, ref, as_of, recipient_id, group["roles"], findings,
                             template, status, "not_duplicate" if possible_duplicate else "", after,
                             group["follow_up"]))
    if possible_duplicate:
        emails.append(_email(assessment, outcome, accepted, ref, as_of, assessment.invoice.vendor_id, ["vendor"],
                             ["possible_duplicate"], "duplicate_notice", "held", "duplicate", "",
                             {"reminder_cc": AP_TEAM, "escalation_to": AP_MANAGER}))
    return emails


def follow_up_email(original: dict, kind: str, thread: dict, as_of: str, ref) -> dict:
    """Template 5: a reminder to the same recipient (cc their manager, or AP Team for a vendor), or an
    escalation to the manager (the AP Manager for a vendor), who becomes the action owner; a vendor
    escalation's actions say what to ask the vendor for.

    It carries the original email's facts plus when our email (and our reminder) went out, under
    names that say whose email and which date; the paragraph is written later, and the reply-by
    date, one business day out, is template-only.
    """
    facts = {key: value for key, value in original["facts"].items() if key != "recipient"}
    vendor = "vendor" in original["roles"]
    roles = " and ".join(ROLE_LABELS[role] for role in original["roles"])
    sent = {"our_email_sent_on": thread["sent_on"], "reply_was_due_on": thread["reply_by"]}
    if kind == "reminder":
        to_id, cc_id = original["recipient_id"], thread["reminder_cc"]
        cc = _recipient(cc_id, ref) if cc_id else None
        about = {"recipient": original["facts"]["recipient"],
                 "follow_up": "reminder: we have had no reply to our email", **sent,
                 "reply_to_this_email_within": "one business day"}
        if cc:
            about["in_copy"] = cc["name"] if vendor else f"{cc['name']} (your manager)"
            writer_recipient = f"{roles} (reminder, {'our AP team' if vendor else 'their manager'} in copy)"
        else:
            writer_recipient = f"{roles} (reminder)"
        line = (f"Reminder: we sent this request on {thread['sent_on']} and asked for a reply by "
                f"{thread['reply_by']}. We have had no reply yet.")
    else:
        to_id, cc_id = thread["escalation_to"], "" if vendor else original["recipient_id"]
        cc = _recipient(cc_id, ref) if cc_id else None
        owner = _recipient(to_id, ref)["name"]
        first_to = f"{original['to_name']} ({roles})"
        about = {"recipient": f"{owner} (AP manager)" if vendor
                 else f"{owner} (manager of {original['to_name']}, the {roles})",
                 "follow_up": "escalation: no reply to our email or to our reminder; you are now the action owner",
                 "our_email_sent_to": first_to, **sent, "our_reminder_sent_on": thread["reminded_on"],
                 "reply_to_this_email_within": "one business day"}
        if vendor:
            facts["action_requested"] = [f"Ask {original['to_name']} to {action[0].lower()}{action[1:]}"
                                         for action in facts["action_requested"]]
            writer_recipient = "AP manager (escalation of a vendor request)"
        else:
            writer_recipient = f"manager of the {roles} (escalation)"
        line = (f"Escalation: we sent this request to {first_to} on {thread['sent_on']} and a reminder on "
                f"{thread['reminded_on']}, with no reply. You are now the action owner.")
    to = _recipient(to_id, ref)
    email = {"email_id": f"{original['email_id']}:{kind}", "exception_id": original["exception_id"],
             "recipient_id": to_id, "roles": list(original["roles"]), "template": kind,
             "findings": list(original["findings"]), "status": "sent", "release_on": "", "opens_after": "",
             "to_name": to["name"], "to_email": to["email"], "greeting": to["greeting"],
             "cc_id": cc_id, "cc_name": cc["name"] if cc else "", "cc_email": cc["email"] if cc else "",
             "subject": SUBJECTS[kind].format(subject=original["subject"]), "facts": {**about, **facts},
             "writer_recipient": writer_recipient, "follow_up_line": line, "follows": original["email_id"],
             "paragraph": "", "paragraph_source": "", "fact_check": [], "sent_on": as_of,
             "reply_by": add_business_days(as_of, FOLLOW_UP_REPLY_DAYS), "reminder_cc": "", "escalation_to": ""}
    email["body"] = render(email)
    return email


def render(email: dict) -> str:
    """The email as text: header, greeting, paragraph, then every fact code filled in."""
    facts = email["facts"]
    header = (f"Invoice {facts['invoice_number']} from {facts['vendor']}, dated {facts['invoice_date']}, "
              f"amount {facts['amount']}.")
    if "po_number" in facts:
        header += f" PO quoted: {facts['po_number']}."
    lines = [f"To: {email['to_name']} <{email['to_email']}>"]
    if email.get("cc_email"):
        lines.append(f"Cc: {email['cc_name']} <{email['cc_email']}>")
    lines += [f"Subject: {email['subject']}", "", f"Hello {email['greeting']},", "",
              email["paragraph"] or "[paragraph not written yet]", ""]
    if email.get("follow_up_line"):
        lines += [email["follow_up_line"], ""]
    lines.append(header)
    for key, label in (("service_month", "Service month"), ("cost_center", "Cost center"),
                       ("gl_account", "GL account"), ("requester", "Requester")):
        if key in facts:
            lines.append(f"{label}: {facts[key]}")
    lines.append("Lines:")
    lines += [f"- {line}" for line in facts["lines"]]
    lines.append("Issues:")
    for n, issue in enumerate(facts["issues"], 1):
        lines.append(f"{n}. {issue['issue']}")
        lines += [f"   - {fact}" for fact in issue["facts"]]
        if "likely_cause" in issue:
            lines.append("   Likely cause, from our review: " + issue["likely_cause"])
        if "from_our_review" in issue:
            lines.append("   From our review: " + issue["from_our_review"])
        if "possible_po" in issue:
            lines.append(f"   {issue['possible_po']}")
    lines.append("Action requested:")
    lines += [f"- {action}" for action in facts["action_requested"]]
    if email["status"] != "cancelled":
        lines.append(f"Reply by: {email['reply_by'] or WAITING_REPLY_BY}")
    lines += ["", "Accounts Payable", COMPANY, AP_ADDRESS]
    return "\n".join(lines)


def facts_text(email: dict) -> str:
    """The email's facts as JSON: what the communicator will see."""
    return json.dumps(email["facts"], ensure_ascii=False)


def writer_messages(email: dict) -> list[dict]:
    """One fresh single-turn request for the paragraph; the reply-by date is not in the facts (decision 10).
    A reminder or an escalation names its recipient in writer_recipient."""
    recipient = email.get("writer_recipient") or " and ".join(ROLE_LABELS[role] for role in email["roles"])
    return [{"role": "system", "content": WRITER_SYSTEM_PROMPT.format(recipient=recipient)},
            {"role": "user", "content": facts_text(email)}]


def known_names(ref) -> set[str]:
    """Every name in the reference data: people (full names and each part), vendors, and cost centers."""
    names = set()
    for person_id, person in ref.people.items():
        names.add(person["name"])
        if person_id != AP_TEAM:
            names.update(person["name"].split())
    names.update(vendor["vendor_name"] for vendor in ref.vendors.values())
    names.update(center["name"] for center in ref.cost_centers.values())
    return names


def check_paragraph(text: str, facts: str, ref) -> list[str]:
    """The fact check: every number, ID, and name in the paragraph must be in its facts. [] when it passes."""
    if not text.strip():
        return ["the paragraph is empty"]
    problems = []
    sentences = len(_SENTENCE_END.findall(text))
    if sentences > MAX_SENTENCES:
        problems.append(f"the paragraph has {sentences} sentences; write at most {MAX_SENTENCES}")
    problems += [f"the number {n} is not in the facts" for n in sorted(numbers_in(text) - numbers_in(facts))]
    for found in dict.fromkeys(_ID.findall(text)):
        if found not in facts:
            problems.append(f"{found} is not in the facts")
    for name in sorted(known_names(ref)):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) and name not in facts:
            problems.append(f"the name {name} is not in the facts")
    fact_words = {word.lower() for word in _WORD.findall(facts)}
    for sentence in re.split(r"(?<=[.!?])\s+", _ID.sub(" ", text)):
        for word in _WORD.findall(sentence)[1:]:
            if word.endswith("'s"):
                word = word[:-2]
            word = word.strip("'-")
            problem = f"the name {word} is not in the facts"
            if (word[:1].isupper() and word not in ALLOWED_WORDS and word.lower() not in fact_words
                    and problem not in problems):
                problems.append(problem)
    return problems


def clean_reply(text: str) -> str:
    """The reply with any <think>...</think> block removed, stripped (as in Phase 1)."""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def write_paragraph(email: dict, writer, ref) -> tuple[dict, dict]:
    """Ask the communicator for the paragraph and fact-check it; a rejected paragraph becomes the fixed sentence."""
    messages = writer_messages(email)
    reply = writer.chat(messages)
    text = clean_reply(reply["message"]["content"])
    problems = check_paragraph(text, messages[1]["content"], ref)
    written = {**email, "paragraph": FALLBACK_PARAGRAPH if problems else text,
               "paragraph_source": "fallback" if problems else "model", "fact_check": problems}
    written["body"] = render(written)
    call = {"email_id": email["email_id"], "prompt": messages[1]["content"], "reply": reply["message"]["content"],
            "problems": problems, "seconds": reply["seconds"], "prompt_tokens": reply["prompt_tokens"],
            "output_tokens": reply["output_tokens"]}
    return written, call

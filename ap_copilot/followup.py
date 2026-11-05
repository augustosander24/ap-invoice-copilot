"""Follow-up after the review: threads, replies, reminders, escalations, and each invoice's status.

Code decides all of it (design section 12): a thread is one email that went out. Any reply stops
its clock. With no reply, the day after the reply-by date brings a reminder (cc the manager, or AP
Team for a vendor) due within one business day; still no reply on that date brings an escalation
to the manager (the AP Manager for a vendor), who becomes the action owner. A thread opened later
(an approval sent after its confirmation) runs its own clock. The reply interpreter only labels
a reply; what the label leads to is here. No model runs in this module.
"""

from ap_copilot.emails import REPLY_DAYS, add_business_days, follow_up_email, render
from ap_copilot.reply_interpreter import sender_name

AP_QUEUE_OPEN = ("category_mismatch", "no_requester", "no_category")  # possible_duplicate is ruled at the review
NEXT_STEPS = {"approved": "closed: approved", "rejected": "closed: rejected; AP acts on it",
              "correction_coming": "closed: a correction is promised; the invoice waits for it",
              "question": "with AP: answer the question", "redirected": "with AP: forward it if that is right",
              "unclear": "with AP: read the reply and decide"}


def open_threads(emails: list[dict]) -> list[dict]:
    """One thread per email that went out at the review, or waits for its confirmation."""
    threads = []
    for email in emails:
        if email["status"] not in ("sent", "waiting"):
            continue
        threads.append({"email_id": email["email_id"], "recipient_id": email["recipient_id"],
                        "owner_id": email["recipient_id"], "template": email["template"],
                        "status": "open" if email["status"] == "sent" else "waiting",
                        "sent_on": email["sent_on"], "reply_by": email["reply_by"],
                        "reminder_cc": email["reminder_cc"], "escalation_to": email["escalation_to"],
                        "reminded_on": "", "reminder_reply_by": "", "escalated_on": "",
                        "replies": [], "outcome": "", "detail": ""})
    return threads


def _address(recipient_id: str, ref) -> str:
    """The email address of a person or a vendor."""
    if recipient_id in ref.vendors:
        return ref.vendors[recipient_id]["contact_email"]
    return ref.people[recipient_id]["email"]


def match_reply(reply, invoice, threads: list[dict], ref) -> str:
    """The thread a reply answers: same vendor and invoice number, sent on or before the reply, from the
    recipient or the action owner. "" when none matches."""
    if (reply.vendor_id, reply.invoice_number) != (invoice.vendor_id, invoice.invoice_number):
        return ""
    for thread in reversed(threads):
        if thread["sent_on"] and thread["sent_on"] <= reply.received_date and reply.from_email in {
                _address(thread["recipient_id"], ref), _address(thread["owner_id"], ref)}:
            return thread["email_id"]
    return ""


def invoice_status(final_recommendation: str, findings: list[str], threads: list[dict], ap_items: list[str]) -> str:
    """Where the invoice stands, first match wins: released (at the review, no thread); with_ap (anything left
    for AP); open (a thread waits); awaiting_correction; void (the vendor confirmed a duplicate); else
    ready_to_release (every thread approved)."""
    if final_recommendation == "release" and not threads:
        return "released"
    if (ap_items or any(f in AP_QUEUE_OPEN for f in findings) or not threads
            or any(t["status"] == "with_ap" or t["outcome"] == "rejected" for t in threads)):
        return "with_ap"
    if any(t["status"] in ("open", "waiting") for t in threads):
        return "open"
    if any(t["outcome"] == "correction_coming" for t in threads):
        return "awaiting_correction"
    if any(t["template"] == "duplicate_notice" for t in threads):
        return "void"
    return "ready_to_release"


def still_open(threads: list[dict]) -> bool:
    """True while any thread waits for a reply, a confirmation, or AP."""
    return any(t["status"] in ("open", "waiting", "with_ap") for t in threads)


def _send_waiting(emails: list[dict], threads: list[dict], as_of: str, sent: list[dict]) -> None:
    """The approval that waited for its confirmation goes out today, with a new reply-by and its day-0 paragraph."""
    for n, email in enumerate(emails):
        if email["status"] == "waiting" and email["opens_after"] == "confirmation":
            released = {**email, "status": "sent", "sent_on": as_of, "reply_by": add_business_days(as_of, REPLY_DAYS)}
            released["body"] = render(released)
            emails[n] = released
            sent.append(released)
            thread = next(t for t in threads if t["email_id"] == email["email_id"])
            thread.update(status="open", sent_on=as_of, reply_by=released["reply_by"])


def _cancel_waiting(emails: list[dict], threads: list[dict]) -> None:
    """A rejected confirmation cancels the approval that waited for it."""
    for n, email in enumerate(emails):
        if email["status"] == "waiting":
            emails[n] = {**email, "status": "cancelled", "reply_by": ""}
            emails[n]["body"] = render(emails[n])
            next(t for t in threads if t["email_id"] == email["email_id"]).update(status="cancelled")


def _apply_reply(record: dict, emails: list[dict], threads: list[dict], as_of: str, ref,
                 sent: list[dict], ap_items: list[str]) -> str:
    """Apply one interpreted reply to its thread; returns the next step."""
    name = sender_name(record["from_email"], ref)
    if not record["email_id"]:
        ap_items.append(f"reply {record['message_id']} from {name} matches no email we sent: read it")
        return "with AP: matches no email"
    thread = next(t for t in threads if t["email_id"] == record["email_id"])
    thread["replies"].append(record["message_id"])
    if thread["status"] not in ("open", "with_ap"):
        ap_items.append(f"reply {record['message_id']} from {name} came after the thread closed: read it")
        return "with AP: the thread was already closed"
    label = record["label"]
    thread.update(outcome=label, detail=record["detail"])
    if label in ("approved", "rejected", "correction_coming"):
        thread["status"] = "closed"
    else:
        thread["status"] = "with_ap"
    if label == "approved" and thread["template"] == "service_confirmation":
        _send_waiting(emails, threads, as_of, sent)
    elif label == "rejected" and thread["template"] == "service_confirmation":
        _cancel_waiting(emails, threads)
    if label == "rejected":
        ap_items.append(f"{name} says not to pay as billed: \"{record['body']}\"")
    elif label == "question":
        ap_items.append(f"{name} asks a question: \"{record['body']}\"")
    elif label == "redirected":
        person = ref.people[record["detail"]]["name"]
        ap_items.append(f"{name} says {person} ({record['detail']}) is responsible: forward the email if that is right")
    elif label == "unclear":
        why = f" ({'; '.join(record['problems'])})" if record["problems"] else ""
        ap_items.append(f"unclear reply from {name}{why}: read it and decide: \"{record['body']}\"")
    return NEXT_STEPS[label]


def follow_up(emails: list[dict], threads: list[dict], records: list[dict], as_of: str, ref):
    """One day's follow-up for one invoice: apply the new replies, then send what is due.

    Returns (emails, threads, sent today, follow-up drafts to write, new AP items, next step per reply).
    """
    emails = [dict(email) for email in emails]
    threads = [{**thread, "replies": list(thread["replies"])} for thread in threads]
    sent, drafts, ap_items, steps = [], [], [], {}
    for record in records:
        steps[record["message_id"]] = _apply_reply(record, emails, threads, as_of, ref, sent, ap_items)
    by_id = {email["email_id"]: email for email in emails}
    for thread in threads:
        if thread["status"] != "open" or thread["replies"]:
            continue
        if not thread["reminded_on"] and as_of >= add_business_days(thread["reply_by"], 1):
            drafts.append(follow_up_email(by_id[thread["email_id"]], "reminder", thread, as_of, ref))
            thread.update(reminded_on=as_of, reminder_reply_by=drafts[-1]["reply_by"])
        elif thread["reminded_on"] and not thread["escalated_on"] and as_of >= thread["reminder_reply_by"]:
            thread["escalated_on"] = as_of
            if thread["escalation_to"]:
                drafts.append(follow_up_email(by_id[thread["email_id"]], "escalation", thread, as_of, ref))
                thread["owner_id"] = thread["escalation_to"]
            else:
                ap_items.append(f"no reply from {by_id[thread['email_id']]['to_name']} after the reminder, "
                                "and no manager to escalate to: AP follows up")
    return emails, threads, sent, drafts, ap_items, steps

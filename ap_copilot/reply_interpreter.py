"""The reply interpreter: one fresh request per reply, then a code check of the details.

The model labels the reply (approved, rejected, correction_coming, question, redirected, or
unclear) and gives the promised date or the person named. Code checks both against the reply
text and the people on file; a detail that fails the check makes the reply unclear, so the
operator reads it. Code, not the model, decides what each label leads to (followup.py).
"""

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from ap_copilot.emails import add_business_days, clean_reply
from ap_copilot.investigator import to_json

LABELS = ("approved", "rejected", "correction_coming", "question", "redirected", "unclear")
INTERPRETER_SYSTEM_PROMPT = (
    "You read replies to accounts payable emails and classify them with one label. "
    "approved = they approve, confirm, or release as asked. "
    "rejected = they say not to pay as billed, including telling us to ask the vendor for a credit. "
    "correction_coming = they say a fix is on its way: a corrected invoice, a credit they will send, or "
    "goods still to arrive; give the date they promise. "
    "question = they ask a question before they decide. "
    "redirected = they say someone else is responsible; give that person's name. "
    "unclear = none of these fits, or the reply can be read more than one way. "
    "Write a date as YYYY-MM-DD: a date with no year is in the year the reply was received, and \"today\" "
    "is the day it was received. Leave date and person empty when they don't apply. Answer in JSON."
)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


class ReplyAnswer(BaseModel):
    label: Literal["approved", "rejected", "correction_coming", "question", "redirected", "unclear"]
    date: str
    person: str
    reason: str


def sender_name(from_email: str, ref) -> str:
    """The sender as a name: a person's name, a vendor's name, or the address itself."""
    for person in ref.people.values():
        if person["email"] == from_email:
            return person["name"]
    for vendor in ref.vendors.values():
        if vendor["contact_email"] == from_email:
            return vendor["vendor_name"]
    return from_email


def interpreter_messages(reply, email: dict, ref) -> list[dict]:
    """One fresh request: the email the reply answers (who it went to, its subject, what it asked) and the reply."""
    message = {"our_email": {"to": email["facts"]["recipient"], "subject": email["subject"],
                             "action_requested": email["facts"]["action_requested"]},
               "reply": {"from": sender_name(reply.from_email, ref), "received": reply.received_date,
                         "text": reply.body}}
    return [{"role": "system", "content": INTERPRETER_SYSTEM_PROMPT}, {"role": "user", "content": to_json(message)}]


def answer_schema() -> dict:
    """The JSON schema the model answers in."""
    return ReplyAnswer.model_json_schema()


def _date_problems(value: str, reply) -> list[str]:
    """A promised date must be a real date, not before the reply, and in the reply's words."""
    try:
        promised = date.fromisoformat(value)
    except ValueError:
        return [f"the date {value!r} is not YYYY-MM-DD"]
    if value < reply.received_date:
        return [f"the date {value} is before the reply was received ({reply.received_date})"]
    text = reply.body.lower()
    month = MONTHS[promised.month - 1]
    said = re.search(rf"\b({month}|{month[:3]})\.?\s+0?{promised.day}\b", text)
    today = value == reply.received_date and re.search(r"\btoday\b", text)
    tomorrow = value == add_business_days(reply.received_date, 1) and re.search(r"\btomorrow\b", text)
    return [] if said or today or tomorrow else [f"the date {value} is not in the reply"]


def _person(name: str, reply, ref) -> tuple[str, list[str]]:
    """The person_id of the person named, who must be on file, in the reply's words, and not the sender."""
    wanted = " ".join(name.split()).lower()
    matches = [pid for pid, person in ref.people.items() if person["name"].lower() == wanted]
    if not matches and wanted:
        matches = [pid for pid, person in ref.people.items() if person["name"].split()[0].lower() == wanted]
    if len(matches) != 1:
        return "", [f"{name!r} is not one person on file"]
    person = ref.people[matches[0]]
    if not re.search(rf"\b{re.escape(person['name'].split()[0])}\b", reply.body, flags=re.I):
        return "", [f"{person['name']} is not named in the reply"]
    if person["email"] == reply.from_email:
        return "", [f"{person['name']} sent the reply"]
    return matches[0], []


def unmatched(reply) -> dict:
    """The record of a reply that answers no email we sent: no label, and AP reads it."""
    return {"message_id": reply.message_id, "received_date": reply.received_date, "from_email": reply.from_email,
            "email_id": "", "body": reply.body, "model_label": "", "label": "", "detail": "", "reason": "",
            "problems": ["matches no email we sent"]}


def interpret(reply, email: dict, interpreter, ref) -> tuple[dict, dict]:
    """Ask the model for the label and check its details. Returns the record and the call log entry."""
    messages = interpreter_messages(reply, email, ref)
    response = interpreter.chat(messages, schema=answer_schema())
    problems, label, detail, reason = [], "unclear", "", ""
    try:
        answer = ReplyAnswer.model_validate_json(clean_reply(response["message"]["content"]))
    except ValueError as error:
        problems = [f"the answer is not valid JSON for the schema: {str(error).splitlines()[0]}"]
    else:
        label, reason = answer.label, answer.reason.strip()
        if label == "correction_coming":
            problems = _date_problems(answer.date.strip(), reply)
            detail = "" if problems else answer.date.strip()
        elif label == "redirected":
            detail, problems = _person(answer.person, reply, ref)
    record = {"message_id": reply.message_id, "received_date": reply.received_date, "from_email": reply.from_email,
              "email_id": email["email_id"], "body": reply.body, "model_label": label,
              "label": "unclear" if problems else label, "detail": "" if problems else detail,
              "reason": reason, "problems": problems}
    call = {"message_id": reply.message_id, "prompt": messages[1]["content"],
            "reply": response["message"]["content"], "problems": problems, "seconds": response["seconds"],
            "prompt_tokens": response["prompt_tokens"], "output_tokens": response["output_tokens"]}
    return record, call

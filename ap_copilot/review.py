"""The AP operator's review: the packet shown at the pause, the decision rules, the operator's edits,
and the decision log."""

import json
from copy import deepcopy
from pathlib import Path

from ap_copilot.emails import REPLY_DAYS, add_business_days, check_paragraph, facts_text, render
from ap_copilot.rules import AP_QUEUE_FINDINGS

DECISIONS = ("confirm", "override")
DUPLICATE_RULINGS = ("duplicate", "not_duplicate")
EDIT_PARTS = ("paragraph", "explanation")
EXPLANATION_KEYS = ("likely_cause", "from_our_review")


def allowed_decisions(state: dict) -> tuple[str, ...]:
    """A possible duplicate needs AP's ruling; any other invoice is confirmed or overridden."""
    return DUPLICATE_RULINGS if "possible_duplicate" in state["outcome"]["findings"] else DECISIONS


def ap_items(outcome: dict, accepted: dict) -> list[str]:
    """What AP sees for its own queue: the AP-queue fact lines, then the investigator's duplicate reason,
    content check, and category suggestion."""
    items = [record["text"] for record in outcome["fact_records"]
             if any(finding in AP_QUEUE_FINDINGS for finding in record["findings"])]
    if "duplicate_check" in accepted:
        items.append(f"agent reason: {accepted['duplicate_check']['reason']}")
    if "content_check" in accepted:
        claim = accepted["content_check"]
        items.append(f"agent content check: {'does not fit' if claim['mismatch'] else 'fits'} "
                     f"the vendor's category: {claim['reason']}")
    if "category_suggestion" in accepted:
        claim = accepted["category_suggestion"]
        items.append(f"agent category suggestion: {claim['category'] or 'none'}: {claim['reason']}")
    return items


def review_packet(state: dict) -> dict:
    """What the operator sees at the pause, as plain data."""
    outcome = state["outcome"]
    allowed = allowed_decisions(state)
    return {"exception_id": state["exception_id"], "recommendation": outcome["recommendation"],
            "findings": outcome["findings"], "ap_items": ap_items(outcome, state.get("accepted", {})),
            "emails": [{"email_id": email["email_id"], "status": email["status"], "release_on": email["release_on"],
                        "paragraph_source": email["paragraph_source"], "body": email["body"]}
                       for email in state["emails"]],
            "decisions": list(allowed), "reason_required": [d for d in allowed if d != "confirm"]}


def decision_problems(state: dict, decision, ref=None) -> list[str]:
    """Why the decision can't be applied; [] when it can. Edits are checked when there are any."""
    if not isinstance(decision, dict):
        return ["the decision must be {'decision': ..., 'reason': ...}"]
    allowed = allowed_decisions(state)
    if decision.get("decision") not in allowed:
        return [f"decision must be one of {', '.join(allowed)}"]
    if decision["decision"] != "confirm" and not str(decision.get("reason") or "").strip():
        return [f"{decision['decision']} needs a reason"]
    return edit_problems(state, decision, ref) if decision.get("edits") else []


def _explanation_key(issue: dict) -> str:
    """The key of the investigator's explanation an issue shows; "" when it shows none."""
    return next((key for key in EXPLANATION_KEYS if key in issue), "")


def edit_problems(state: dict, decision: dict, ref) -> list[str]:
    """Why the operator's edits can't be applied: each edits a paragraph or an explanation of an email that
    goes out with this decision, and passes the same fact check as the communicator's paragraph."""
    if decision["decision"] == "override":
        return ["an override cancels every draft, so there is nothing to edit"]
    emails = {email["email_id"]: email for email in state["emails"]}
    problems = []
    for edit in decision["edits"]:
        email = emails.get(edit.get("email_id"))
        label = f"edit of {edit.get('email_id')}"
        if email is None:
            problems.append(f"{label}: no such draft")
            continue
        if email["release_on"] and email["release_on"] != decision["decision"]:
            problems.append(f"{label}: this decision cancels that draft")
            continue
        text = str(edit.get("text") or "").strip()
        if edit.get("part") not in EDIT_PARTS:
            problems.append(f"{label}: part must be one of {', '.join(EDIT_PARTS)}")
            continue
        if edit["part"] == "explanation":
            issues = email["facts"]["issues"]
            number = int(edit.get("issue") or 0)
            if not 1 <= number <= len(issues) or not _explanation_key(issues[number - 1]):
                problems.append(f"{label}: issue {number} has no explanation to edit")
                continue
        problems += [f"{label} {edit['part']}: {problem}" for problem in check_paragraph(text, facts_text(email), ref)]
    return problems


def apply_edits(emails: list[dict], edits: list[dict]) -> list[dict]:
    """The emails with the operator's edits: a new paragraph (source "operator") or a new explanation text,
    each kept with what it replaced."""
    result = []
    for email in emails:
        email = deepcopy(email)
        for edit in edits:
            if edit["email_id"] != email["email_id"]:
                continue
            text = edit["text"].strip()
            if edit["part"] == "paragraph":
                before = email["paragraph"]
                email.update(paragraph=text, paragraph_source="operator")
                issue = ""
            else:
                issue = int(edit["issue"])
                target = email["facts"]["issues"][issue - 1]
                key = _explanation_key(target)
                before, target[key] = target[key], text
            email.setdefault("edits", []).append({"part": edit["part"], "issue": issue, "before": before,
                                                  "after": text})
        email["body"] = render(email)
        result.append(email)
    return result


def final_recommendation(state: dict, decision: str) -> str:
    """The recommendation after the review: an override reverses it, except that a non-PO invoice is never
    released by an override (it stays on hold with AP); clearing a duplicate drops that hold."""
    outcome = state["outcome"]
    if decision == "override":
        if outcome["path"] == "non_po":
            return "hold"
        return "release" if outcome["recommendation"] == "hold" else "hold"
    if decision == "not_duplicate":
        return "hold" if any(finding != "possible_duplicate" for finding in outcome["findings"]) else "release"
    return outcome["recommendation"]


def apply_decision(emails: list[dict], decision: str, as_of: str) -> list[dict]:
    """The emails after the decision: what goes is sent on as_of with a new reply-by date, the rest cancelled or kept."""
    result = []
    for email in emails:
        status = email["status"]
        if decision == "override":
            status = "cancelled"
        elif email["release_on"] in DUPLICATE_RULINGS:
            if email["release_on"] == decision:
                status = "waiting" if email["opens_after"] else "send"
            else:
                status = "cancelled"
        changed = {**email, "status": status}
        if status == "send":
            changed.update(status="sent", sent_on=as_of, reply_by=add_business_days(as_of, REPLY_DAYS))
        elif status == "cancelled":
            changed["reply_by"] = ""
        changed["body"] = render(changed)
        result.append(changed)
    return result


class DecisionLog:
    """An append-only JSON Lines file; an entry_id already in the file is never written again."""

    def __init__(self, path):
        self.path = Path(path)

    def entries(self) -> list[dict]:
        """Every logged entry, in file order; [] when the file doesn't exist."""
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as file:
            return [json.loads(line) for line in file if line.strip()]

    def write(self, entry: dict) -> bool:
        """Append the entry and return True; False when its entry_id is already logged."""
        if any(logged["entry_id"] == entry["entry_id"] for logged in self.entries()):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True

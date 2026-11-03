"""The AP operator's review: the packet shown at the pause, the decision rules, and the decision log."""

import json
from pathlib import Path

from ap_copilot.emails import REPLY_DAYS, add_business_days, render
from ap_copilot.rules import AP_QUEUE_FINDINGS

DECISIONS = ("confirm", "override")
DUPLICATE_RULINGS = ("duplicate", "not_duplicate")


def allowed_decisions(state: dict) -> tuple[str, ...]:
    """A possible duplicate needs AP's ruling; any other invoice is confirmed or overridden."""
    return DUPLICATE_RULINGS if "possible_duplicate" in state["outcome"]["findings"] else DECISIONS


def ap_items(outcome: dict, accepted: dict) -> list[str]:
    """What AP sees for its own queue: the AP-queue fact lines, then the investigator's duplicate reason."""
    items = [record["text"] for record in outcome["fact_records"]
             if any(finding in AP_QUEUE_FINDINGS for finding in record["findings"])]
    if "duplicate_check" in accepted:
        items.append(f"agent reason: {accepted['duplicate_check']['reason']}")
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


def decision_problems(state: dict, decision) -> list[str]:
    """Why the decision can't be applied; [] when it can."""
    if not isinstance(decision, dict):
        return ["the decision must be {'decision': ..., 'reason': ...}"]
    allowed = allowed_decisions(state)
    if decision.get("decision") not in allowed:
        return [f"decision must be one of {', '.join(allowed)}"]
    if decision["decision"] != "confirm" and not str(decision.get("reason") or "").strip():
        return [f"{decision['decision']} needs a reason"]
    return []


def final_recommendation(state: dict, decision: str) -> str:
    """The recommendation after the review: an override reverses it, and clearing a duplicate drops that hold."""
    outcome = state["outcome"]
    if decision == "override":
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

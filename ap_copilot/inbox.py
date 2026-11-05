"""The mock inbox: replies to the emails the copilot sent, read up to an as-of date.

CsvInbox reads data/input/inbox.csv. A mail connector would offer the same replies(as_of)
method, so the graph never knows where the replies come from (design section 9).
"""

from dataclasses import dataclass
from pathlib import Path

from ap_copilot.data import ROOT, read_csv

INBOX = ROOT / "data" / "input" / "inbox.csv"


@dataclass(frozen=True)
class Reply:
    message_id: str
    received_date: str
    from_email: str
    vendor_id: str
    invoice_number: str
    body: str


class CsvInbox:
    """The mailbox as a CSV file, read fresh on every call."""

    def __init__(self, path=INBOX):
        self.path = Path(path)

    def replies(self, as_of: str) -> list[Reply]:
        """Every reply received on or before as_of, oldest first."""
        rows = [Reply(**row) for row in read_csv(self.path) if row["received_date"] <= as_of]
        return sorted(rows, key=lambda reply: (reply.received_date, reply.message_id))

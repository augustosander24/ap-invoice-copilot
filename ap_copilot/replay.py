"""Replay a saved run's model replies, so a later phase reuses a long live run without the model."""

import json
from copy import deepcopy


class ReplayMismatch(Exception):
    """The graph sent a request the saved run never sent, so the code has changed since that run."""


class ReplayClient:
    """Stands in for OllamaClient for one case, returning that case's saved replies in order."""

    def __init__(self, case: dict, model: str):
        self.exception_id = case["exception_id"]
        self.model = f"replay of {model}"
        self.entries = list(zip(case.get("transcript", []), case.get("model_calls", [])))

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             schema: dict | None = None) -> dict:
        """The next saved reply, after checking that the request is the one the saved run sent."""
        step = "answer" if schema is not None else "tools"
        if not self.entries:
            raise ReplayMismatch(f"{self.exception_id}: the saved run has no more replies ({step} step)")
        entry, call = self.entries.pop(0)
        if entry["step"] != step or messages[-1]["content"] != entry["prompt"]:
            raise ReplayMismatch(f"{self.exception_id}: attempt {entry['attempt']} {entry['step']} step: "
                                 "the request differs from the saved run; rerun the investigator live")
        return {"message": deepcopy(entry["reply"]), "seconds": call["seconds"],
                "prompt_tokens": call["prompt_tokens"], "output_tokens": call["output_tokens"]}

    def unused(self) -> int:
        """How many saved replies are left."""
        return len(self.entries)


def load_run(path: str) -> tuple[str, dict[str, dict]]:
    """A run_po_agent.py run file as (model, cases by exception_id)."""
    with open(path, encoding="utf-8") as file:
        run = json.load(file)
    return run["model"], {case["exception_id"]: case for case in run["cases"]}

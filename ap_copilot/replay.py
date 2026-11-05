"""Replay a saved run's model replies, so a later phase reuses a live run without the model."""

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


class CallReplay:
    """Stands in for a single-request agent (the communicator or the reply interpreter): the saved reply to
    each request, found by the request's user message, so a saved run's paragraphs or labels are reused."""

    def __init__(self, calls: list[dict], model: str, source: str):
        self.model = f"replay of {model}"
        self.source = source
        self.saved = {}
        for call in calls:
            self.saved.setdefault(call["prompt"], call)  # the same request always got the same reply

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             schema: dict | None = None) -> dict:
        """The saved reply to this request; ReplayMismatch when the saved run never sent it."""
        call = self.saved.get(messages[-1]["content"])
        if call is None:
            raise ReplayMismatch(f"a request is not in {self.source}; the code has changed since that run, "
                                 "so rerun this agent live")
        return {"message": {"role": "assistant", "content": call["reply"]}, "seconds": call["seconds"],
                "prompt_tokens": call["prompt_tokens"], "output_tokens": call["output_tokens"]}


class NoModel:
    """Stands in for a model that must not be called: resuming a review never calls one."""

    model = "none"

    def chat(self, messages, tools=None, schema=None) -> dict:
        raise RuntimeError("a model was called where none may run")


def load_calls(path, key: str) -> tuple[str, list[dict]]:
    """A run file's model and its single-request calls: every case's writer_calls (key "writer_calls") from a
    run_emails.py or run_day.py file, or the "calls" of a run_replies.py file."""
    with open(path, encoding="utf-8") as file:
        run = json.load(file)
    if key == "calls":
        return run["model"], run["calls"]
    return run["communicator"], [call for case in run["cases"] for call in case.get(key, [])]

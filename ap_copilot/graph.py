"""The Phase 6 graph for AP Invoice Copilot: one run per PO invoice.

Code runs every rule; the agent answers only the tasks code gives it; code checks
every claim against the evidence the agent was shown in this run, and turns the
accepted answer into verdicts. State is plain data, so the Phase 7 checkpointer
can save it.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ap_copilot.data import Invoice, Reference
from ap_copilot.evidence import check_answer, fallback, numbers_in
from ap_copilot.investigator import (ANSWER_SYSTEM_PROMPT, STEP_SYSTEM_PROMPT, answer_message,
                                     answer_schema, candidates_of, parse_answer, po_tasks, shown_text,
                                     step_message)
from ap_copilot.routing import Verdicts, finalize
from ap_copilot.rules import assess
from ap_copilot.tools import PO_TOOL_SPECS, TOOL_KINDS, evidence_ids, known_arguments, run_tool

MAX_TOOL_CALLS = 6  # per attempt
MAX_ATTEMPTS = 3  # the first answer plus 2 retries


class PoState(TypedDict, total=False):
    exception_id: str
    path: str
    findings: list[str]
    tasks: list[str]
    status: str  # investigating, retry, accepted, finalized, non_po_not_built
    transcript: list[dict]  # attempt, step, prompt (the user message sent), reply (the model's message)
    pending: list[dict]  # the tool calls of the last tool step, not run yet
    stalled: bool  # the last tool step only repeated earlier lookups
    reasons: list[str]  # the last evidence check's problems, shown in the next prompts
    attempt: int
    calls_this_attempt: int
    tool_calls: list[dict]  # attempt, n, tool, kind, args, result, evidence_ids, error
    model_calls: list[dict]  # attempt, step (tools or answer), seconds, prompt_tokens, output_tokens
    answer: dict
    answer_error: str
    checks: list[dict]  # attempt, passed, problems: {task: [problem]} for failing tasks only
    accepted: dict
    fallbacks: list[str]
    outcome: dict


def _model_call(attempt: int, step: str, reply: dict) -> dict:
    """The log entry for one model call."""
    return {"attempt": attempt, "step": step, "seconds": reply["seconds"],
            "prompt_tokens": reply["prompt_tokens"], "output_tokens": reply["output_tokens"]}


def _text_tool_call(content: str) -> list[dict]:
    """A tool call the model wrote as text ({"name": ..., "parameters": {...}}), as tool_calls; else []."""
    try:
        data = json.loads(content.strip())
    except ValueError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return []
    args = data.get("parameters", data.get("arguments", {}))
    return [{"function": {"name": data["name"], "arguments": args if isinstance(args, dict) else {}}}]


def _call_key(name: str, args: dict) -> str:
    """Identifies a lookup: the tool and the arguments it takes."""
    return json.dumps([name, known_arguments(name, args)], sort_keys=True)


def _outcome_dict(outcome) -> dict:
    """routing.finalize()'s Outcome as plain data."""
    return {
        "path": outcome.path,
        "findings": list(outcome.findings),
        "approval_reason": outcome.approval_reason,
        "approver_id": outcome.approver_id,
        "gl_account": outcome.gl_account,
        "recommendation": outcome.recommendation,
        "actions": [{"recipient_id": action.recipient_id, "role": action.role,
                     "findings": list(action.findings), "status": action.status,
                     "after": action.after, "reminder_cc": action.reminder_cc,
                     "escalation_to": action.escalation_to}
                    for action in outcome.actions],
        "facts": list(outcome.facts),
    }


def build_graph(ref: Reference, invoices: dict[str, Invoice], client):
    """The compiled graph. client has chat(messages, tools=None, schema=None), as OllamaClient does."""

    def assessment(state: PoState):
        return assess(invoices[state["exception_id"]], ref)

    def assess_node(state: PoState) -> dict:
        a = assessment(state)
        update = {"path": a.path, "findings": list(a.findings), "tool_calls": [], "model_calls": [],
                  "checks": [], "fallbacks": [], "transcript": [], "pending": [], "reasons": []}
        if a.path == "non_po" and "exact_duplicate" not in a.findings:
            return {**update, "tasks": [], "status": "non_po_not_built"}
        tasks = () if "exact_duplicate" in a.findings else po_tasks(a)
        return {**update, "tasks": list(tasks), "status": "investigating", "attempt": 1,
                "calls_this_attempt": 0}

    def investigate_node(state: PoState) -> dict:
        # One fresh, single-turn tool step: Llama 3.1 8B can't reliably hold a conversation
        # alongside tool definitions, so the history goes in as text, not as chat turns.
        prompt = step_message(assessment(state), tuple(state["tasks"]), state["tool_calls"], state["reasons"])
        reply = client.chat([{"role": "system", "content": STEP_SYSTEM_PROMPT},
                             {"role": "user", "content": prompt}], tools=PO_TOOL_SPECS)
        message = dict(reply["message"])
        if not message.get("tool_calls"):
            calls = _text_tool_call(message["content"])
            if calls:
                message["tool_calls"] = calls
        entry = {"attempt": state["attempt"], "step": "tools", "prompt": prompt, "reply": message}
        return {"pending": message.get("tool_calls", []), "transcript": state["transcript"] + [entry],
                "model_calls": state["model_calls"] + [_model_call(state["attempt"], "tools", reply)]}

    def run_tools_node(state: PoState) -> dict:
        tool_calls = list(state["tool_calls"])
        count = state["calls_this_attempt"]
        done = {_call_key(call["tool"], call["args"]) for call in tool_calls}
        repeats = 0
        for call in state["pending"]:
            name = call["function"]["name"]
            args = dict(call["function"].get("arguments") or {})
            if count >= MAX_TOOL_CALLS:
                result = {"error": f"not run: the cap of {MAX_TOOL_CALLS} tool calls is reached"}
            elif _call_key(name, args) in done:
                count += 1
                repeats += 1
                result = {"error": "already looked up: that result is in the lookups above; "
                                   "look up a different record or reply DONE"}
            else:
                count += 1
                result = run_tool(ref, name, args)
                done.add(_call_key(name, args))
            tool_calls.append({"attempt": state["attempt"], "n": len(tool_calls) + 1, "tool": name,
                               "kind": TOOL_KINDS.get(name, "unknown"), "args": args, "result": result,
                               "evidence_ids": evidence_ids(result), "error": result.get("error", "")})
        # Ollama's llama3.1 template asks for a tool call on every turn that offers tools, so the
        # model rarely replies DONE; a step that only repeats earlier lookups ends the lookups.
        stalled = bool(state["pending"]) and repeats == len(state["pending"])
        return {"tool_calls": tool_calls, "calls_this_attempt": count, "pending": [], "stalled": stalled}

    def answer_node(state: PoState) -> dict:
        a = assessment(state)
        tasks = tuple(state["tasks"])
        prompt = answer_message(a, tasks, state["tool_calls"], state["reasons"])
        reply = client.chat([{"role": "system", "content": ANSWER_SYSTEM_PROMPT},
                             {"role": "user", "content": prompt}], schema=answer_schema(tasks))
        try:
            answer, answer_error = parse_answer(reply["message"]["content"], tasks), ""
        except ValueError as error:
            answer, answer_error = {}, f"the answer is not valid JSON for the schema: {error}"
        entry = {"attempt": state["attempt"], "step": "answer", "prompt": prompt, "reply": reply["message"]}
        return {"transcript": state["transcript"] + [entry], "answer": answer,
                "answer_error": answer_error,
                "model_calls": state["model_calls"] + [_model_call(state["attempt"], "answer", reply)]}

    def evidence_check_node(state: PoState) -> dict:
        a = assessment(state)
        tasks = tuple(state["tasks"])
        if state["answer_error"]:
            first_line = state["answer_error"].splitlines()[0]
            problems = {task: [first_line] for task in tasks}
        else:
            seen = {evidence_id for call in state["tool_calls"] for evidence_id in call["evidence_ids"]}
            shown = numbers_in(shown_text(a, state["tool_calls"]))
            problems = check_answer(state["answer"], tasks, a.invoice, ref, candidates_of(a), seen, shown)
        failing = {task: found for task, found in problems.items() if found}
        checks = state["checks"] + [{"attempt": state["attempt"], "passed": not failing,
                                     "problems": failing}]
        if not failing:
            return {"checks": checks, "accepted": state["answer"], "status": "accepted"}
        if state["attempt"] < MAX_ATTEMPTS:
            reasons = [f"{task}: {problem}" for task, found in failing.items() for problem in found]
            return {"checks": checks, "reasons": reasons, "attempt": state["attempt"] + 1,
                    "calls_this_attempt": 0, "status": "retry"}
        accepted = {task: fallback(task) if task in failing else state["answer"][task] for task in tasks}
        return {"checks": checks, "accepted": accepted, "fallbacks": list(failing), "status": "accepted"}

    def finalize_node(state: PoState) -> dict:
        a = assessment(state)
        duplicate = (state["accepted"]["duplicate_check"]["likely_duplicate"]
                     if "duplicate_check" in state["tasks"] else None)
        outcome = finalize(a, ref, Verdicts(duplicate=duplicate))
        return {"status": "finalized", "outcome": _outcome_dict(outcome)}

    def after_assess(state: PoState) -> str:
        if state["status"] == "non_po_not_built":
            return END
        return "investigate" if state["tasks"] else "finalize"

    def after_investigate(state: PoState) -> str:
        return "run_tools" if state["pending"] else "answer"

    def after_run_tools(state: PoState) -> str:
        return "answer" if state["stalled"] or state["calls_this_attempt"] >= MAX_TOOL_CALLS else "investigate"

    def after_evidence_check(state: PoState) -> str:
        return "finalize" if state["status"] == "accepted" else "investigate"

    builder = StateGraph(PoState)
    builder.add_node("assess", assess_node)
    builder.add_node("investigate", investigate_node)
    builder.add_node("run_tools", run_tools_node)
    builder.add_node("answer", answer_node)
    builder.add_node("evidence_check", evidence_check_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "assess")
    builder.add_conditional_edges("assess", after_assess, [END, "investigate", "finalize"])
    builder.add_conditional_edges("investigate", after_investigate, ["run_tools", "answer"])
    builder.add_conditional_edges("run_tools", after_run_tools, ["answer", "investigate"])
    builder.add_edge("answer", "evidence_check")
    builder.add_conditional_edges("evidence_check", after_evidence_check, ["finalize", "investigate"])
    builder.add_edge("finalize", END)
    return builder.compile()

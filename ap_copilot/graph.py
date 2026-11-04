"""The graph for AP Invoice Copilot: one run per invoice.

Code runs every rule and picks the investigator by path (PO or non-PO); the agent
answers only the tasks code gives it; code checks every claim against the evidence
the agent was shown in this run, and turns the accepted answer into verdicts. With a
communicator, code then drafts the emails, the model writes one paragraph for each,
and the run pauses for the AP operator's review; it resumes from the checkpoint,
applies the decision, and logs it once. State is plain data, so the checkpointer can
save it.
"""

import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ap_copilot.data import Invoice, Reference
from ap_copilot.emails import EXPORT_DATE, draft_emails, write_paragraph
from ap_copilot.evidence import check_answer, fallback, numbers_in
from ap_copilot import investigator as po, nonpo_investigator as nonpo
from ap_copilot.investigator import candidates_of
from ap_copilot.review import apply_decision, decision_problems, final_recommendation, review_packet
from ap_copilot.routing import Verdicts, finalize, outcome_dict
from ap_copilot.rules import assess
from ap_copilot.tools import NONPO_TOOL_SPECS, PO_TOOL_SPECS, TOOL_KINDS, evidence_ids, known_arguments, run_tool

MAX_TOOL_CALLS = 6  # per attempt
MAX_ATTEMPTS = 3  # the first answer plus 2 retries


class PoState(TypedDict, total=False):
    exception_id: str
    path: str
    findings: list[str]
    tasks: list[str]
    status: str  # investigating, retry, accepted, finalized, drafted, awaiting_review, reviewed
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
    as_of: str  # the demo date of this run, YYYY-MM-DD
    emails: list[dict]
    writer_calls: list[dict]  # email_id, prompt, reply, problems, seconds, prompt_tokens, output_tokens
    review: dict  # decision, reason
    final_recommendation: str
    logged: list[str]  # entry IDs written


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


def build_graph(ref: Reference, invoices: dict[str, Invoice], client, writer=None, checkpointer=None, log=None):
    """The compiled graph. client has chat(messages, tools=None, schema=None), as OllamaClient does.

    With no writer the graph ends at finalize (the Phase 6 investigator run). With a writer (the
    communicator) it drafts the emails, pauses for the AP operator's review, applies the decision,
    and logs it; the pause needs a checkpointer, and the log a DecisionLog.
    """

    def assessment(state: PoState):
        return assess(invoices[state["exception_id"]], ref)

    def category(state: PoState) -> str:
        """The vendor's category, from the vendor master."""
        return ref.vendors[invoices[state["exception_id"]].vendor_id]["category"]

    def step_prompt(state: PoState, a) -> tuple[str, str, list[dict]]:
        """The system prompt, the user message, and the tools of one tool step, for the invoice's path."""
        tasks = tuple(state["tasks"])
        if state["path"] == "po":
            return (po.STEP_SYSTEM_PROMPT, po.step_message(a, tasks, state["tool_calls"], state["reasons"]),
                    PO_TOOL_SPECS)
        return (nonpo.STEP_SYSTEM_PROMPT,
                nonpo.step_message(a, category(state), tasks, state["tool_calls"], state["reasons"]),
                NONPO_TOOL_SPECS)

    def answer_prompt(state: PoState, a) -> tuple[str, str]:
        """The system prompt and the user message of the answer step, for the invoice's path."""
        tasks = tuple(state["tasks"])
        if state["path"] == "po":
            return po.ANSWER_SYSTEM_PROMPT, po.answer_message(a, tasks, state["tool_calls"], state["reasons"])
        return (nonpo.ANSWER_SYSTEM_PROMPT,
                nonpo.answer_message(a, category(state), tasks, state["tool_calls"], state["reasons"]))

    def module(state: PoState):
        """The investigator module for the invoice's path."""
        return po if state["path"] == "po" else nonpo

    def first_step(state: PoState) -> str:
        """Where the investigator starts: the tool steps, or the answer when no task needs a lookup."""
        if state["path"] == "non_po" and not nonpo.needs_lookups(tuple(state["tasks"])):
            return "answer"
        return "investigate"

    def assess_node(state: PoState) -> dict:
        a = assessment(state)
        update = {"path": a.path, "findings": list(a.findings), "tool_calls": [], "model_calls": [],
                  "checks": [], "fallbacks": [], "transcript": [], "pending": [], "reasons": []}
        if "exact_duplicate" in a.findings:
            tasks = ()
        elif a.path == "po":
            tasks = po.po_tasks(a)
        else:
            tasks = nonpo.nonpo_tasks(a)
        return {**update, "tasks": list(tasks), "status": "investigating", "attempt": 1,
                "calls_this_attempt": 0}

    def investigate_node(state: PoState) -> dict:
        # One fresh, single-turn tool step: Llama 3.1 8B can't reliably hold a conversation
        # alongside tool definitions, so the history goes in as text, not as chat turns.
        system, prompt, tools = step_prompt(state, assessment(state))
        reply = client.chat([{"role": "system", "content": system},
                             {"role": "user", "content": prompt}], tools=tools)
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
                result = run_tool(ref, name, args, state["path"])
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
        system, prompt = answer_prompt(state, a)
        investigator = module(state)
        reply = client.chat([{"role": "system", "content": system},
                             {"role": "user", "content": prompt}], schema=investigator.answer_schema(tasks))
        try:
            answer, answer_error = investigator.parse_answer(reply["message"]["content"], tasks), ""
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
            shown = numbers_in(module(state).shown_text(a, state["tool_calls"]))
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
        mismatch = (state["accepted"]["content_check"]["mismatch"]
                    if "content_check" in state["tasks"] else None)
        outcome = finalize(a, ref, Verdicts(duplicate=duplicate, mismatch=mismatch))
        return {"status": "finalized", "outcome": outcome_dict(outcome)}

    def draft_node(state: PoState) -> dict:
        emails = draft_emails(assessment(state), state["outcome"], state.get("accepted", {}), ref,
                              state.get("as_of", EXPORT_DATE))
        return {"emails": emails, "writer_calls": [], "status": "drafted"}

    def write_node(state: PoState) -> dict:
        emails, calls = [], []
        for email in state["emails"]:
            written, call = write_paragraph(email, writer, ref)
            emails.append(written)
            calls.append(call)
        return {"emails": emails, "writer_calls": state["writer_calls"] + calls, "status": "awaiting_review"}

    def review_node(state: PoState) -> dict:
        # interrupt() pauses the run here; on resume LangGraph reruns this node from the top and
        # interrupt() returns the operator's decision, so nothing before it may have side effects.
        # A bad decision is asked again and never reaches the state (raising instead leaves it
        # stuck on the thread).
        packet = review_packet(state)
        decision = interrupt(packet)
        problems = decision_problems(state, decision)
        while problems:
            decision = interrupt({**packet, "problems": problems})
            problems = decision_problems(state, decision)
        return {"review": {"decision": decision["decision"], "reason": str(decision.get("reason") or "").strip()}}

    def apply_review_node(state: PoState) -> dict:
        decision = state["review"]["decision"]
        return {"emails": apply_decision(state["emails"], decision, state.get("as_of", EXPORT_DATE)),
                "final_recommendation": final_recommendation(state, decision), "status": "reviewed"}

    def log_review_node(state: PoState) -> dict:
        # Its own node after the pause, so the entry is written once (design section 12).
        as_of = state.get("as_of", EXPORT_DATE)
        entry_id = f"{state['exception_id']}:{as_of}:review"
        entry = {"entry_id": entry_id, "exception_id": state["exception_id"], "as_of": as_of, "event": "review",
                 "recommendation": state["outcome"]["recommendation"], "findings": state["outcome"]["findings"],
                 "decision": state["review"]["decision"], "reason": state["review"]["reason"],
                 "final_recommendation": state["final_recommendation"],
                 "emails": [{"email_id": email["email_id"], "status": email["status"],
                             "paragraph_source": email["paragraph_source"]} for email in state["emails"]]}
        log.write(entry)
        return {"logged": state.get("logged", []) + [entry_id]}

    def after_assess(state: PoState) -> str:
        return first_step(state) if state["tasks"] else "finalize"

    def after_investigate(state: PoState) -> str:
        return "run_tools" if state["pending"] else "answer"

    def after_run_tools(state: PoState) -> str:
        return "answer" if state["stalled"] or state["calls_this_attempt"] >= MAX_TOOL_CALLS else "investigate"

    def after_evidence_check(state: PoState) -> str:
        return "finalize" if state["status"] == "accepted" else first_step(state)

    builder = StateGraph(PoState)
    builder.add_node("assess", assess_node)
    builder.add_node("investigate", investigate_node)
    builder.add_node("run_tools", run_tools_node)
    builder.add_node("answer", answer_node)
    builder.add_node("evidence_check", evidence_check_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "assess")
    builder.add_conditional_edges("assess", after_assess, ["investigate", "answer", "finalize"])
    builder.add_conditional_edges("investigate", after_investigate, ["run_tools", "answer"])
    builder.add_conditional_edges("run_tools", after_run_tools, ["answer", "investigate"])
    builder.add_edge("answer", "evidence_check")
    builder.add_conditional_edges("evidence_check", after_evidence_check, ["finalize", "investigate", "answer"])
    if writer is None:
        builder.add_edge("finalize", END)
    else:
        builder.add_node("draft", draft_node)
        builder.add_node("write", write_node)
        builder.add_node("review", review_node)
        builder.add_node("apply_review", apply_review_node)
        builder.add_node("log_review", log_review_node)
        builder.add_edge("finalize", "draft")
        builder.add_edge("draft", "write")
        builder.add_edge("write", "review")
        builder.add_edge("review", "apply_review")
        builder.add_edge("apply_review", "log_review")
        builder.add_edge("log_review", END)
    return builder.compile(checkpointer=checkpointer)

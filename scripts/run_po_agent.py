"""Live runner for the Phase 6 PO investigator.

Runs the graph with the local Ollama model on every PO-path invoice (EX-001 to
EX-009) and compares the results with evals/expected_outcomes.csv: first_tool,
duplicate_verdict, po_match, and the six rules fields. Prints each case's tool
calls, evidence checks, accepted answers, outcome, and mismatches, then a
summary. Saves the full final state of every case (every message, tool call,
answer, and check, with seconds and token counts per model call) to
output/phase6/po_run_<model>.json. Exit code 0 when every case matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_po_agent.py
    .venv\\Scripts\\python.exe scripts\\run_po_agent.py EX-003 EX-006
    .venv\\Scripts\\python.exe scripts\\run_po_agent.py --plant EX-006

Exception IDs limit the run to those cases. --plant runs one case and replaces
its first po_match answer with the invoice's own (invalid) PO number, to show
the evidence check rejecting a bad claim.

    .venv\\Scripts\\python.exe scripts\\run_po_agent.py --set heldout_a EX-101 EX-102
    .venv\\Scripts\\python.exe scripts\\run_po_agent.py --set heldout_a --resume

--set runs a held-out batch into output/phase10/<set>/po_run_<model>.json, one file
whatever IDs are given. The run file is saved after every case, so a stopped run
keeps what it finished; --resume keeps the cases already in the file and runs the rest.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "phase6"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import DATA_SETS, data_set, load_invoices, load_reference, read_csv
from ap_copilot.graph import build_graph
from ap_copilot.investigator import OllamaClient, to_json
from ap_copilot.rules import assess

COLUMNS = ("first_tool", "duplicate_verdict", "po_match", "rules_fields")


class PlantingClient:
    """Wraps the real client and replaces the po_number in the first answer with a planted one."""

    def __init__(self, client, po_number: str):
        self.client = client
        self.model = client.model
        self.po_number = po_number
        self.planted = ""

    def chat(self, messages, tools=None, schema=None) -> dict:
        reply = self.client.chat(messages, tools=tools, schema=schema)
        if schema is None or self.planted:
            return reply
        try:
            answer = json.loads(reply["message"]["content"])
            claim = answer["po_match"]
            got = claim["po_number"]
        except (ValueError, KeyError, TypeError):
            self.planted = "skipped: the first answer was not JSON with a po_match entry"
            return reply
        self.planted = f"po_match {got} replaced with {self.po_number}"
        claim["po_number"] = self.po_number
        reply["message"]["content"] = to_json(answer)
        return reply


def _mismatch(got: str, expected: str) -> str:
    return "" if got == expected else f"got {got}, expected {expected}"


def compare(state: dict, expected: dict[str, str]) -> dict[str, str]:
    """Each column -> "" when it matches the eval, else "got X, expected Y"."""
    calls = state["tool_calls"]
    kind = calls[0]["kind"] if calls else "none"
    results = {"first_tool": "" if kind in expected["first_tool"].split("|")
               else f"got {kind}, expected {expected['first_tool']}"}
    accepted = state.get("accepted", {})
    if expected["duplicate_verdict"]:
        claim = accepted.get("duplicate_check")
        got = "none" if claim is None else "yes" if claim["likely_duplicate"] else "no"
        results["duplicate_verdict"] = _mismatch(got, expected["duplicate_verdict"])
    if expected["po_match"]:
        got = accepted.get("po_match", {}).get("po_number", "none")
        results["po_match"] = ("" if got.strip().lower() == expected["po_match"].lower()
                               else f"got {got}, expected {expected['po_match']}")
    outcome = state["outcome"]
    rules = [f"{label}: {problem}" for label, got, want in (
        ("path", outcome["path"], expected["path"]),
        ("findings", ";".join(outcome["findings"]) or "none", expected["findings"]),
        ("approval_reason", outcome["approval_reason"], expected["approval_reason"]),
        ("approver_id", outcome["approver_id"], expected["approver_id"]),
        ("gl_account", outcome["gl_account"], expected["gl_account"]),
        ("recommendation", outcome["recommendation"], expected["day0_recommendation"]))
        if (problem := _mismatch(got, want))]
    results["rules_fields"] = "; ".join(rules)
    return results


def print_case(state: dict, results: dict[str, str], seconds: float) -> None:
    status = "FAIL" if any(results.values()) else "PASS"
    print(f"{status} {state['exception_id']}  tasks: {', '.join(state['tasks']) or 'none'}")
    for call in state["tool_calls"]:
        result = call["error"] or ", ".join(call["evidence_ids"])
        print(f"   tool {call['n']} (attempt {call['attempt']}) {call['tool']} {json.dumps(call['args'])} -> {result}")
    for check in state["checks"]:
        print(f"   evidence check attempt {check['attempt']}: {'PASS' if check['passed'] else 'FAIL'}")
        for task, problems in check["problems"].items():
            for problem in problems:
                print(f"      ! {task}: {problem}")
    for task in state["fallbacks"]:
        print(f"   fallback used: {task}")
    accepted = state.get("accepted", {})
    for task in state["tasks"]:
        claim = accepted[task]
        if task == "duplicate_check":
            print(f"   duplicate_check: {'yes' if claim['likely_duplicate'] else 'no'}. {claim['reason']}")
        elif task == "po_match":
            print(f"   po_match: {claim['po_number']}. {claim['reason']}")
        else:
            print(f"   {task}: {claim['explanation']}")
    outcome = state["outcome"]
    print(f"   findings: {';'.join(outcome['findings']) or 'none'}  recommendation: {outcome['recommendation']}")
    for action in outcome["actions"]:
        print(f"      -> {action['role']} {action['recipient_id']} {action['status']}: {';'.join(action['findings'])}")
    for column, problem in results.items():
        if problem:
            print(f"   ! {column}: {problem}")
    print(f"   {seconds} s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PO investigator with the local model.")
    parser.add_argument("ids", nargs="*", metavar="EXCEPTION_ID", help="limit the run to these PO cases")
    parser.add_argument("--plant", metavar="EXCEPTION_ID",
                        help="run one case with its first po_match answer replaced by its own PO number")
    parser.add_argument("--set", choices=DATA_SETS, default="eval", help="the data set (default: the 22-case eval)")
    parser.add_argument("--resume", action="store_true", help="keep the cases already in the run file; run the rest")
    args = parser.parse_args()
    if args.plant and (args.resume or args.set != "eval"):
        parser.error("--plant runs on the eval, without --resume")

    folders = data_set(args.set)
    output = OUTPUT if args.set == "eval" else ROOT / "output" / "phase10" / args.set
    ref = load_reference(folders.reference)
    invoices = {invoice.exception_id: invoice for invoice in load_invoices(folders.input / "exception_list.xlsx")}
    expected = {row["exception_id"]: row for row in read_csv(folders.evals / "expected_outcomes.csv")}
    po_ids = [exception_id for exception_id, invoice in invoices.items() if assess(invoice, ref).path == "po"]
    wanted = [args.plant] if args.plant else args.ids
    unknown = [exception_id for exception_id in wanted if exception_id not in po_ids]
    if unknown:
        parser.error(f"not PO cases: {', '.join(unknown)}")
    case_ids = [exception_id for exception_id in po_ids if not wanted or exception_id in wanted]

    client = OllamaClient()
    model = client.model
    if args.plant:
        client = PlantingClient(client, invoices[args.plant].po_number)
    name = "po_run_" + ("planted_" if args.plant else "") + model.replace(":", "-")
    if args.ids and args.set == "eval" and not args.plant:
        name += "_" + "_".join(case_ids)
    name += ".json"
    path = output / name
    cases = []
    if args.resume and path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["model"] != model:
            parser.error(f"{name} was run with {saved['model']}, not {model}")
        cases = saved["cases"]
    done = {case["exception_id"] for case in cases}
    to_run = [exception_id for exception_id in case_ids if exception_id not in done]
    graph = build_graph(ref, invoices, client)
    header = f"PO investigator run: {len(to_run)} cases, model {model}"
    if args.set != "eval":
        header += f", data set {args.set}"
    if done:
        header += f"; {len(done)} already in {name}"
    print(header + (f", planted bad claim on {args.plant}" if args.plant else ""))

    output.mkdir(parents=True, exist_ok=True)
    run = {"model": model, "plant": args.plant, "planted": "", "cases": cases}
    for exception_id in to_run:
        started_at = datetime.now().isoformat(timespec="seconds")
        started = time.perf_counter()
        state = graph.invoke({"exception_id": exception_id})
        seconds = round(time.perf_counter() - started, 1)
        results = compare(state, expected[exception_id])
        print_case(state, results, seconds)
        cases.append({"exception_id": exception_id, "started_at": started_at, "seconds": seconds,
                      "results": results, **state})
        run["planted"] = client.planted if args.plant else ""
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")  # after every case

    tallies = {column: [0, 0] for column in COLUMNS}
    for case in cases:
        for column, problem in case["results"].items():
            tallies[column][0] += not problem
            tallies[column][1] += 1
    matched = sum(not any(case["results"].values()) for case in cases)
    print("summary")
    for column in COLUMNS:
        good, total = tallies[column]
        print(f"  {column} {good} of {total}")
    print(f"  evidence check: {sum(bool(case['checks']) for case in cases)} cases, "
          f"{sum(max(len(case['checks']) - 1, 0) for case in cases)} retries, "
          f"{sum(len(case['fallbacks']) for case in cases)} fallbacks")
    if args.plant:
        print(f"  plant: {run['planted']}")
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path.relative_to(ROOT).as_posix()}")
    print(f"{matched} of {len(cases)} PO cases match")
    return 0 if matched == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

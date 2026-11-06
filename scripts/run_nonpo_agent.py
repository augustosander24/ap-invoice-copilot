"""Live runner for the Phase 8 non-PO investigator.

Runs the graph with the local Ollama model on every non-PO invoice that is not an
exact duplicate (EX-011 to EX-022) and compares the results with
evals/expected_outcomes.csv: first_tool, duplicate_verdict, mismatch_flag,
category_suggestion, and the six rules fields. A case with no agent task (EX-015,
EX-016, EX-021) makes no model call; its rules fields are still compared. Prints
each case's tool calls, evidence checks, accepted answers, outcome, and
mismatches, then a summary, and saves the full final state of every case to
output/phase8/nonpo_run_<model>.json, which scripts/run_emails.py replays. Exit
code 0 when every case matches, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\run_nonpo_agent.py
    .venv\\Scripts\\python.exe scripts\\run_nonpo_agent.py EX-012 EX-022

Exception IDs limit the run to those cases, saved under a separate name.

    .venv\\Scripts\\python.exe scripts\\run_nonpo_agent.py --set heldout_a
    .venv\\Scripts\\python.exe scripts\\run_nonpo_agent.py --set heldout_a --resume

--set runs a held-out batch into output/phase10/<set>/nonpo_run_<model>.json, one file
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
OUTPUT = ROOT / "output" / "phase8"
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.data import DATA_SETS, data_set, load_invoices, load_reference, read_csv
from ap_copilot.graph import build_graph
from ap_copilot.investigator import OllamaClient
from ap_copilot.rules import assess

COLUMNS = ("first_tool", "duplicate_verdict", "mismatch_flag", "category_suggestion", "rules_fields")


def _mismatch(got: str, expected: str) -> str:
    return "" if got == expected else f"got {got}, expected {expected}"


def compare(state: dict, expected: dict[str, str]) -> dict[str, str]:
    """Each column the eval fills -> "" when it matches, else "got X, expected Y"; a blank eval column is not scored."""
    results = {}
    accepted = state.get("accepted", {})
    if expected["first_tool"]:
        calls = state["tool_calls"]
        kind = calls[0]["kind"] if calls else "none"
        results["first_tool"] = ("" if kind in expected["first_tool"].split("|")
                                 else f"got {kind}, expected {expected['first_tool']}")
    for column, task, field in (("duplicate_verdict", "duplicate_check", "likely_duplicate"),
                                ("mismatch_flag", "content_check", "mismatch")):
        if expected[column]:
            claim = accepted.get(task)
            got = "none" if claim is None else "yes" if claim[field] else "no"
            results[column] = _mismatch(got, expected[column])
    if expected["category_suggestion"]:
        got = accepted.get("category_suggestion", {}).get("category") or "none"
        results["category_suggestion"] = _mismatch(got, expected["category_suggestion"])
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
        elif task == "content_check":
            print(f"   content_check: mismatch {'yes' if claim['mismatch'] else 'no'}. {claim['reason']}")
        elif task == "category_suggestion":
            print(f"   category_suggestion: {claim['category'] or 'none'}. {claim['reason']}")
        else:
            print(f"   {task}: {claim['explanation']}")
    outcome = state["outcome"]
    print(f"   findings: {';'.join(outcome['findings']) or 'none'}  recommendation: {outcome['recommendation']}")
    for action in outcome["actions"]:
        after = " after confirmation" if action["after"] else ""
        print(f"      -> {action['role']} {action['recipient_id']} {action['status']}: "
              f"{';'.join(action['findings'])}{after}")
    for column, problem in results.items():
        if problem:
            print(f"   ! {column}: {problem}")
    print(f"   {seconds} s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the non-PO investigator with the local model.")
    parser.add_argument("ids", nargs="*", metavar="EXCEPTION_ID", help="limit the run to these non-PO cases")
    parser.add_argument("--set", choices=DATA_SETS, default="eval", help="the data set (default: the 22-case eval)")
    parser.add_argument("--resume", action="store_true", help="keep the cases already in the run file; run the rest")
    args = parser.parse_args()

    folders = data_set(args.set)
    output = OUTPUT if args.set == "eval" else ROOT / "output" / "phase10" / args.set
    ref = load_reference(folders.reference)
    invoices = {invoice.exception_id: invoice for invoice in load_invoices(folders.input / "exception_list.xlsx")}
    expected = {row["exception_id"]: row for row in read_csv(folders.evals / "expected_outcomes.csv")}
    nonpo_ids = [exception_id for exception_id, invoice in invoices.items()
                 for assessment in [assess(invoice, ref)]
                 if assessment.path == "non_po" and "exact_duplicate" not in assessment.findings]
    unknown = [exception_id for exception_id in args.ids if exception_id not in nonpo_ids]
    if unknown:
        parser.error(f"not non-PO cases: {', '.join(unknown)}")
    case_ids = [exception_id for exception_id in nonpo_ids if not args.ids or exception_id in args.ids]

    client = OllamaClient("nonpo_investigator")
    model = client.model
    name = "nonpo_run_" + model.replace(":", "-")
    if args.ids and args.set == "eval":
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
    header = f"non-PO investigator run: {len(to_run)} cases, model {model}"
    if args.set != "eval":
        header += f", data set {args.set}"
    print(header + (f"; {len(done)} already in {name}" if done else ""))

    output.mkdir(parents=True, exist_ok=True)
    run = {"model": model, "cases": cases}
    for exception_id in to_run:
        started_at = datetime.now().isoformat(timespec="seconds")
        started = time.perf_counter()
        state = graph.invoke({"exception_id": exception_id})
        seconds = round(time.perf_counter() - started, 1)
        results = compare(state, expected[exception_id])
        print_case(state, results, seconds)
        cases.append({"exception_id": exception_id, "started_at": started_at, "seconds": seconds,
                      "results": results, **state})
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
        if total:  # a column no case scores is left out, as duplicate_verdict: no non-PO candidate in the data
            print(f"  {column} {good} of {total}")
    print(f"  evidence check: {sum(bool(case['checks']) for case in cases)} cases, "
          f"{sum(max(len(case['checks']) - 1, 0) for case in cases)} retries, "
          f"{sum(len(case['fallbacks']) for case in cases)} fallbacks")
    print(f"  model calls: {sum(len(case['model_calls']) for case in cases)}; "
          f"{round(sum(case['seconds'] for case in cases), 1)} s")
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path.relative_to(ROOT).as_posix()}")
    print(f"{matched} of {len(cases)} non-PO cases match")
    return 0 if matched == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Build docs/eval_report.md: every agent job's 22-case result beside its held-out result.

Reads the saved run files (output/phase6, phase8, phase9, phase10), the four checkers, and two small
files in docs/: hand_scores.csv (the hand verdicts of Phase 10) and agent_history.csv (the earlier phases'
recorded results). Writes docs/eval_report.md and changes nothing else. The report is built from the
files, so a second run writes the same bytes. Exit code 0 when every held-out paragraph and explanation
and every eval paragraph has a hand verdict, otherwise 1.

    .venv\\Scripts\\python.exe scripts\\eval_report.py
    .venv\\Scripts\\python.exe scripts\\eval_report.py --commit-b 8a81692

--commit-b is the commit that froze held-out batch A; its time is compared with every held-out run's start.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Run as a script, Python puts scripts\ on sys.path, not the project root; add it so ap_copilot imports.
sys.path.insert(0, str(ROOT))

from ap_copilot.config import MAX_TOKENS, get_model
from ap_copilot.data import read_csv
from ap_copilot.emails import EXPORT_DATE, add_business_days

BAR = 0.8  # Phase 4 decision 4: 80% on every scored column with 5 or more cases
COLUMNS = ("first_tool", "duplicate_verdict", "po_match", "mismatch_flag", "category_suggestion", "rules_fields")
CHECKERS = ("check_data.py", "check_rules.py", "check_emails.py", "check_followups.py")
SETS = ("eval", "heldout_a")
PARAGRAPH = ("paragraph_day0", "paragraph_followup")  # the kinds in hand_scores.csv
DAY4, DAY5 = (add_business_days(EXPORT_DATE, day) for day in (4, 5))


def name(agent: str) -> str:
    """The model an agent uses, as it appears in run file names."""
    return get_model(agent).replace(":", "-")


def files(data_set: str) -> dict[str, Path]:
    """The run files of one data set."""
    if data_set == "eval":
        out = ROOT / "output" / "phase10"
        return {"po": ROOT / "output" / "phase6" / f"po_run_{name('po_investigator')}.json",
                "nonpo": ROOT / "output" / "phase8" / f"nonpo_run_{name('nonpo_investigator')}.json",
                "replies": ROOT / "output" / "phase9" / f"replies_{name('reply_interpreter')}.json",
                "emails": out / f"emails_{name('communicator')}.json", "day4": out / f"day_{DAY4}.json",
                "day5": out / f"day_{DAY5}.json"}
    out = ROOT / "output" / "phase10" / data_set
    return {"po": out / f"po_run_{name('po_investigator')}.json", "nonpo": out / f"nonpo_run_{name('nonpo_investigator')}.json",
            "replies": out / f"replies_{name('reply_interpreter')}.json",
            "emails": out / f"emails_{name('communicator')}.json", "day4": out / f"day_{DAY4}.json",
            "day5": out / f"day_{DAY5}.json"}


def load(path: Path) -> dict:
    """A run file, or a stop that says which one is missing."""
    if not path.exists():
        raise SystemExit(f"missing {path.relative_to(ROOT).as_posix()}: run the step that writes it first")
    return json.loads(path.read_text(encoding="utf-8"))


def table(headers: list[str], rows: list[list]) -> list[str]:
    """A Markdown table; a pipe inside a cell is escaped."""
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + [
        "| " + " | ".join(cell(value) for value in row) + " |" for row in rows] + [""]


def rate(good: int, total: int) -> str:
    return f"{good} of {total}" + (f" ({round(100 * good / total)}%)" if total else "")


def clock(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def tally(cases: list[dict]) -> dict[str, list[int]]:
    """Each scored column -> [cases matching, cases scored], in COLUMNS order."""
    counts = {}
    for case in cases:
        for column, problem in case["results"].items():
            counts.setdefault(column, [0, 0])
            counts[column][0] += not problem
            counts[column][1] += 1
    return {column: counts[column] for column in COLUMNS if column in counts}


def check_tally(cases: list[dict]) -> tuple[int, int, int]:
    """Task answers by the evidence check: right on the first attempt, rejected then corrected, fell back."""
    first = corrected = fell_back = 0
    for case in cases:
        rejected = case["checks"][0]["problems"] if case["checks"] else {}
        for task in case["tasks"]:
            if task in case["fallbacks"]:
                fell_back += 1
            elif rejected.get(task):
                corrected += 1
            else:
                first += 1
    return first, corrected, fell_back


def got(case: dict) -> dict[str, str]:
    """What the agent answered, per scored column."""
    accepted, calls = case.get("accepted", {}), case["tool_calls"]
    answer = {"first_tool": calls[0]["kind"] if calls else "none"}
    if "duplicate_check" in accepted:
        answer["duplicate_verdict"] = "yes" if accepted["duplicate_check"]["likely_duplicate"] else "no"
    if "po_match" in accepted:
        answer["po_match"] = accepted["po_match"]["po_number"] or "none"
    if "content_check" in accepted:
        answer["mismatch_flag"] = "yes" if accepted["content_check"]["mismatch"] else "no"
    if "category_suggestion" in accepted:
        answer["category_suggestion"] = accepted["category_suggestion"]["category"] or "none"
    return answer


def stats(calls: list[dict], cap: int) -> list:
    """Calls, longest prompt, longest reply against the cap, and how many calls the cap cut."""
    longest = max((call["output_tokens"] for call in calls), default=0)
    return [len(calls), max((call["prompt_tokens"] for call in calls), default=0), f"{longest} of {cap}",
            sum(call.get("done_reason") == "length" for call in calls)]


def verdicts(hand: list[dict], data_set: str, job: str, kind: str, run: int = 0) -> tuple[dict[str, dict], str]:
    """The hand verdicts for one set, job, and kind, by item, for one run (default: the latest); and its number."""
    mine = [row for row in hand if (row["set"], row["job"], row["kind"]) == (data_set, job, kind)]
    last = run or max((int(row["run"]) for row in mine), default=0)
    return {row["item"]: row for row in mine if int(row["run"]) == last}, str(last)


def hand_rate(hand: list[dict], data_set: str, job: str, kind: str, run: int = 0) -> tuple[int, int]:
    rows, _ = verdicts(hand, data_set, job, kind, run)
    return sum(row["verdict"] == "correct" for row in rows.values()), len(rows)


def meets(columns: list[tuple[str, int, int]]) -> str:
    """The bar: 80% on every column with 5 or more cases; below 5 the result is n of N with no bar."""
    short = [f"{label} {good} of {total}" for label, good, total in columns if total >= 5 and good / total < BAR]
    missing = [label for label, _, total in columns if total == 0]
    if short:
        return "not met: " + "; ".join(short)
    return f"pending: no hand score yet for {', '.join(missing)}" if missing else "met"


def run_checker(script: str, data_set: str) -> list[str]:
    """The last lines a checker prints, run on one data set."""
    command = [sys.executable, str(ROOT / "scripts" / script)] + (["--set", data_set] if data_set != "eval" else [])
    done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    return lines[-3:] if script == "check_followups.py" else lines[-2:] if script == "check_emails.py" else lines[-1:]


def commit_time(commit: str) -> datetime | None:
    """A commit's time from git, or None when git doesn't know the commit."""
    done = subprocess.run(["git", "log", "-1", "--format=%cI", commit], cwd=ROOT, capture_output=True, text=True)
    return datetime.fromisoformat(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build docs/eval_report.md from the saved runs.")
    parser.add_argument("--commit-b", default="8a81692", help="the commit that froze held-out batch A")
    args = parser.parse_args()
    hand = read_csv(ROOT / "docs" / "hand_scores.csv")
    history = read_csv(ROOT / "docs" / "agent_history.csv")
    runs = {data_set: {key: load(path) for key, path in files(data_set).items()} for data_set in SETS}
    expected = {data_set: {row["exception_id"]: row for row in read_csv(
        (ROOT / "evals" if data_set == "eval" else ROOT / "evals" / data_set) / "expected_outcomes.csv")} for data_set in SETS}
    current = {row["job"]: row for row in history if row["current"] == "yes"}
    unscored = 0

    def split_calls(emails: dict, day5: dict) -> tuple[list[dict], list[dict]]:
        """The communicator's day-0 calls and its follow-up calls, as the model wrote them (before any edit)."""
        day0 = [call for case in emails["cases"] for call in case.get("writer_calls", [])]
        later = [call for case in day5["cases"] for call in case.get("writer_calls", [])
                 if call["email_id"].endswith(("reminder", "escalation"))]
        return day0, later

    def comm_calls(data_set: str) -> tuple[list[dict], list[dict]]:
        return split_calls(runs[data_set]["emails"], runs[data_set]["day5"])

    def row_for(data_set: str, job: str) -> list:
        """One summary row: the job's 22-case and held-out results, the bar, and what the tuning was."""
        title = {"po": "PO investigator", "nonpo": "Non-PO investigator", "replies": "Reply interpreter"}[job]
        agent = {"po": "po_investigator", "nonpo": "nonpo_investigator", "replies": "reply_interpreter"}[job]
        results = {}
        for each in SETS:
            if job == "replies":
                calls = runs[each]["replies"]["calls"]
                matched = sum((call["label"], call["detail"]) == (call["expected_label"], call["expected_detail"]) for call in calls)
                results[each] = (f"{rate(matched, len(calls))} replies", [("replies", matched, len(calls))])
            else:
                cases = runs[each][job]["cases"]
                columns = [(column, good, total) for column, (good, total) in tally(cases).items()]
                columns += [("explanations", *hand_rate(hand, each, job, "explanation"))] if each == "heldout_a" else []
                every = sum(not any(case["results"].values()) for case in cases)
                results[each] = (f"{rate(every, len(cases))} cases match every column", columns)
        old = current[agent]
        return [title, f"{results['eval'][0]}; {old['tuned']}", old["fix_rounds"], results["heldout_a"][0], "80%",
                meets(results["heldout_a"][1])]

    lines = ["# AP Invoice Copilot: evaluation report", "",
             "Built by `scripts/eval_report.py` from the saved run files, the four checkers, `docs/hand_scores.csv`, "
             "and `docs/agent_history.csv`. The 22-case eval is the **tuned set**: its results show regression, not "
             "generalization. Held-out batch A is the **untuned set**: it was keyed and committed before any model saw "
             "it, and its results stand as recorded.", ""]

    # 1. Summary
    lines += ["## 1. Summary", ""]
    rows = [row_for("eval", job) for job in ("po", "nonpo", "replies")]
    for job, title in (("communicator_day0", "Communicator, day 0"), ("communicator_followup", "Communicator, follow-ups")):
        kind = 0 if job == "communicator_day0" else 1
        old = current[job]
        parts = {}
        for each in SETS:
            calls = comm_calls(each)[kind]
            good, total = hand_rate(hand, each, "communicator", PARAGRAPH[kind])
            parts[each] = (f"hand score {rate(good, total)}; fact check first try {rate(sum(not c['problems'] for c in calls), len(calls))}",
                           good, total)
        rows.append([title, f"{parts['eval'][0]}; {old['tuned']}", old["fix_rounds"], parts["heldout_a"][0], "80%",
                     meets([("paragraphs", parts["heldout_a"][1], parts["heldout_a"][2])])])
    lines += table(["Job", "22-case eval (tuned or untuned)", "Fix rounds", "Held-out A", "Bar", "Bar met on held-out A"], rows)
    lines += ["The non-PO first lookup scores an order between two reasonable lookups on multi-task cases (Phase 8); its "
              "number stands as recorded. A job meets the bar when every column with 5 or more cases reaches 80%; "
              "columns with fewer cases are n of N with no bar.", ""]

    # 2. Rules
    lines += ["## 2. Rules (code only, no model)", ""]
    rows = [[script, "22-case eval" if each == "eval" else "held-out A", " / ".join(run_checker(script, each))]
            for script in CHECKERS for each in SETS]
    lines += table(["Checker", "Data set", "Last lines"], rows)

    # 3. Each job
    lines += ["## 3. Each agent job", "",
              "Reasoning: the 22-case runs of qwen3:14b used the model's default (it thinks by default); the held-out runs "
              "used `THINK=on`, which asks for the same thing. Run times are recorded, not scored.", ""]
    for each in SETS:
        label = "22-case eval" if each == "eval" else "held-out A"
        for job, agent in (("po", "po_investigator"), ("nonpo", "nonpo_investigator")):
            run = runs[each][job]
            cases = run["cases"]
            first, corrected, fell_back = check_tally(cases)
            tasks = first + corrected + fell_back
            first_time = sum(len(case["checks"]) <= 1 and not case["fallbacks"] for case in cases)
            lines += [f"### {agent}, {label} (model {run['model']}, cap {MAX_TOKENS[agent]} tokens, "
                      f"{clock(sum(case['seconds'] for case in cases))})", ""]
            lines += table(["Column", "Cases matching"], [[column, rate(good, total) + ("" if total >= 5 else " (under 5: no bar)")]
                                                          for column, (good, total) in tally(cases).items()])
            lines += [f"- Task answers right on the first attempt: {rate(first, tasks)}; after retries: {rate(first + corrected, tasks)}; "
                      f"fallbacks: {fell_back}.",
                      f"- Evidence-check correction rate: {rate(corrected, corrected + fell_back)} rejected answers corrected on a retry.",
                      f"- Cases with every task right on the first attempt: {rate(first_time, len(cases))}."]
            lines += [f"- Explanations by hand: {rate(*hand_rate(hand, each, job, 'explanation'))}."] if each == "heldout_a" else []
            lines += [""]
        calls = runs[each]["replies"]["calls"]
        matched = sum((call["label"], call["detail"]) == (call["expected_label"], call["expected_detail"]) for call in calls)
        changed = [call for call in calls if call["model_label"] != call["label"]]
        lines += [f"### reply_interpreter, {label} (model {runs[each]['replies']['model']}, cap {MAX_TOKENS['reply_interpreter']} tokens, "
                  f"{clock(sum(call['seconds'] for call in calls))})", "",
                  f"- Replies matching (label and detail): {rate(matched, len(calls))}.",
                  f"- Code check corrections (the model's label made unclear by a failed date or person): {len(changed)}"
                  + "".join(f"; {call['message_id']} said {call['model_label']}" for call in changed) + ".", ""]
        by_label = {}
        for call in calls:
            by_label.setdefault(call["expected_label"], [0, 0])
            by_label[call["expected_label"]][0] += (call["label"], call["detail"]) == (call["expected_label"], call["expected_detail"])
            by_label[call["expected_label"]][1] += 1
        lines += table(["Expected label", "Matching"], [[label_, rate(*counts)] for label_, counts in sorted(by_label.items())])
    lines += ["Earlier runs, from `docs/agent_history.csv`:", ""]
    lines += table(["Job", "Phase", "Run", "Model", "Result", "Tuned?", "Fix rounds", "Note"],
                   [[row["job"], row["phase"], row["run"], row["model"], row["result"], row["tuned"], row["fix_rounds"], row["note"]]
                    for row in history])

    # 4. Communicator
    lines += ["## 4. Communicator (llama3.1:8b, cap 512 tokens)", ""]
    rows = []
    for each in SETS:
        for kind, label in ((0, "day 0"), (1, "follow-ups")):
            calls = comm_calls(each)[kind]
            good, total = hand_rate(hand, each, "communicator", PARAGRAPH[kind])
            _, run_number = verdicts(hand, each, "communicator", PARAGRAPH[kind])
            rows.append([each, label, rate(sum(not call["problems"] for call in calls), len(calls)),
                         f"{rate(good, total)} (hand run {run_number if run_number != '0' else 'none yet'})", clock(sum(call["seconds"] for call in calls))])
    first_run = ROOT / "output" / "phase10" / "run1"
    if (first_run / f"emails_{name('communicator')}.json").exists() and (first_run / f"day_{DAY5}.json").exists():
        for kind, label in ((0, "day 0"), (1, "follow-ups")):  # prompt 5's first run, before design round 5b
            calls = split_calls(load(first_run / f"emails_{name('communicator')}.json"), load(first_run / f"day_{DAY5}.json"))[kind]
            rows.insert(kind, ["eval, run 1 (before 5b)", label, rate(sum(not call["problems"] for call in calls), len(calls)),
                               f"{rate(*hand_rate(hand, 'eval', 'communicator', PARAGRAPH[kind], 1))} (hand run 1)",
                               clock(sum(call["seconds"] for call in calls))])
    lines += table(["Set", "Paragraphs", "Fact check, first try", "Read correctly by hand", "Time"], rows)
    lines += ["The fact check proves figures and names exist in the facts, not that a sentence is right; the hand score "
              "reads each paragraph the model wrote, before any operator edit. The eval's paragraphs are design-informed "
              "(Phase 7 rounds, Phase 9 fixes, the Phase 10 rollback); the held-out paragraphs are not.", ""]

    # 5. Caps
    lines += ["## 5. Caps", "", "A call stops at its cap, thinking tokens included. `done_reason` is blank in runs before Phase 10.", ""]
    rows = []
    for each in SETS:
        label = "eval" if each == "eval" else "held-out A"
        for job, agent in (("po", "po_investigator"), ("nonpo", "nonpo_investigator")):
            rows.append([label, agent, *stats([call for case in runs[each][job]["cases"] for call in case["model_calls"]], MAX_TOKENS[agent])])
        rows.append([label, "reply_interpreter", *stats(runs[each]["replies"]["calls"], MAX_TOKENS["reply_interpreter"])])
        day0, later = comm_calls(each)
        rows.append([label, "communicator", *stats(day0 + later, MAX_TOKENS["communicator"])])
    lines += table(["Set", "Agent", "Calls", "Longest prompt (tokens)", "Longest reply", "Cut by the cap"], rows)

    # 6. Appendix
    lines += ["## 6. Per-case appendix", "", "Each cell is what the agent gave / what the eval expects; ✗ marks a miss.", ""]
    for each in SETS:
        label = "22-case eval" if each == "eval" else "held-out A"
        for job in ("po", "nonpo"):
            lines += [f"### {job} investigator, {label}", ""]
            explain, _ = verdicts(hand, each, job, "explanation")
            rows = []
            for case in runs[each][job]["cases"]:
                want, answer = expected[each][case["exception_id"]], got(case)
                cells = [f"{answer[column]} / {want[column]}" + (" ✗" if case["results"][column] else "") if column in case["results"] else "-"
                         for column in ("first_tool", "duplicate_verdict", "po_match", "mismatch_flag", "category_suggestion")]
                marks = [explain.get(f"{case['exception_id']}:{task}", {}).get("verdict", "not scored") for task in case["tasks"]
                         if task.endswith("_explanation")] if each == "heldout_a" else []
                unscored += marks.count("not scored")
                rows.append([case["exception_id"], *cells, case["results"]["rules_fields"] or "ok", len(case["checks"]),
                             len(case["fallbacks"]), ", ".join(marks) or "-"])
            lines += table(["Case", "First lookup", "Duplicate", "PO match", "Content mismatch", "Category", "Rules fields",
                            "Attempts", "Fallbacks", "Explanations (hand)"], rows)
        lines += [f"### reply interpreter, {label}", ""]
        lines += table(["Reply", "Email", "Got / expected", "Model said", "Check"],
                       [[call["message_id"], call["email_id"], f"{call['label']} {call['detail']}".strip() + " / "
                         + f"{call['expected_label']} {call['expected_detail']}".strip()
                         + ("" if (call["label"], call["detail"]) == (call["expected_label"], call["expected_detail"]) else " ✗"),
                         call["model_label"] if call["model_label"] != call["label"] else "-", "; ".join(call["problems"]) or "-"]
                        for call in runs[each]["replies"]["calls"]])
        lines += [f"### communicator paragraphs, {label}", ""]
        rows = []
        for kind, group in enumerate(comm_calls(each)):
            marks, _ = verdicts(hand, each, "communicator", PARAGRAPH[kind])
            for call in group:
                mark = marks.get(call["email_id"], {})
                unscored += not mark
                rows.append([call["email_id"], call.get("done_reason") or "-", "; ".join(call["problems"]) or "passed",
                             mark.get("verdict", "not scored"), mark.get("note", "")])
        lines += table(["Email", "Done reason", "Fact check", "Hand verdict", "Note"], rows)

    # 7. Provenance
    lines += ["## 7. Provenance", ""]
    before = commit_time(args.commit_b)
    lines += [f"Commit `{args.commit_b}` (batch A frozen): {before.isoformat() if before else 'not found by git'}.", ""]
    rows, late = [], []
    for each in SETS:
        for key, path in files(each).items():
            run = json.loads(path.read_text(encoding="utf-8"))
            starts = [item["started_at"] for item in run.get("cases", []) + run.get("calls", []) if item.get("started_at")]
            first_start = datetime.fromisoformat(min(starts)).astimezone() if starts else None
            saved = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
            if each == "heldout_a" and before:
                late.append((first_start or saved) > before)
            rows.append([path.relative_to(ROOT).as_posix(), first_start.isoformat(timespec="seconds") if first_start else "not recorded",
                         saved.isoformat(timespec="seconds")])
    lines += table(["File read", "First case started", "File saved"], rows)
    lines += ["Held-out runs after commit B: " + (f"{sum(late)} of {len(late)} files started or saved after it." if before else "not checked.")
              + " Day-0 and day runs record no start time; they replay the investigator and interpreter runs, which do, "
              "so they cannot have started earlier.", "",
              "Also read: `docs/hand_scores.csv`, `docs/agent_history.csv`, `evals/expected_outcomes.csv`, "
              "`evals/heldout_a/expected_outcomes.csv`, and the output of the four checkers.", ""]

    path = ROOT / "docs" / "eval_report.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT).as_posix()}: {len(lines)} lines")
    print(f"items without a hand verdict: {unscored}")
    return 1 if unscored else 0  # the report is written either way; an unscored item is a gap to fill


if __name__ == "__main__":
    sys.exit(main())

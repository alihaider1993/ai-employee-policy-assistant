"""Run the golden question set against live Azure OpenAI and Azure AI Search.

Not a unit test: this calls live services and is not collected by pytest.
It calls graph nodes, the compiled graph and the retriever directly and never
goes through /ask or the database.

Run from the repo root as a module so app.* imports resolve:

    python -m eval.run_eval --part routing
    python -m eval.run_eval --part routing --limit 5
    python -m eval.run_eval --part routing --ids q01,q05
    python -m eval.run_eval --part routing --repeat 3
    python -m eval.run_eval --part retrieval --k 5
    python -m eval.run_eval --part answers
    python -m eval.run_eval --part answers --repeat 3

Results are saved to eval/results/<timestamp>_routing.json,
eval/results/<timestamp>_retrieval_k<K>.json and
eval/results/<timestamp>_answers.json.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from eval.validate_golden import GOLDEN_PATH, LABELS

RESULTS_DIR = Path(__file__).parent / "results"
OUTCOMES = ("correct", "wrong", "invalid", "error")
CONFUSION_COLUMNS = (*LABELS, "invalid", "error")
SCORED_TYPE = "policy"
UNSCORED_RETRIEVAL_TYPES = ("not_covered",)
MAX_ERROR_MESSAGE = 200
# Matches the retriever default that generate_policy_answer uses.
ANSWER_TOP_K = 3
ANSWER_TYPES = ("policy", "not_covered", "general", "out_of_scope")
ANSWER_OUTCOMES = ("pass", "fail", "skipped", "error")
JUDGE_ATTEMPTS = 2

JUDGE_PROMPT = """You are grading an Employee Policy Assistant's answer for an evaluation.
Return JSON only, with exactly this shape:

{{
  "must_include": [{{"fact": "<fact, copied exactly>", "present": true, "in_chunks": true, "reason": "<one sentence>"}}],
  "faithful": true,
  "faithful_reason": "<one sentence>",
  "refused": false,
  "refused_reason": "<one sentence>"
}}

Rules:
- "must_include": one item per required fact below, in the same order. "present" is
  true if the bot's answer states the fact, in any wording. "in_chunks" is true if
  the retrieved chunk text states the fact, in any wording, and false if it does not.
  Use [] if there are no required facts.
- "faithful": true if every claim in the bot's answer is supported by the retrieved
  chunks, and false if any claim is not.
- Whenever chunks are given, "in_chunks" and "faithful" must be true or false, never
  null, even if the chunks are irrelevant to the question. Use null for them only
  when the Retrieved chunks section below is exactly "(none)".
- "refused": true if the answer declines to answer, or says the handbook or the
  provided policy information does not cover the question.
- The reference answer is guidance for what a correct answer contains. Do not
  penalise extra detail unless it is unsupported by the chunks.

Question:
{question}

Reference answer:
{answer_key}

Required facts (JSON list):
{must_include}

Retrieved chunks:
{chunks}

Bot's answer:
{answer}
"""


def select_entries(entries, ids, limit):
    if ids:
        by_id = {entry["id"]: entry for entry in entries}
        unknown = [entry_id for entry_id in ids if entry_id not in by_id]
        if unknown:
            raise SystemExit(f"Unknown ids: {', '.join(unknown)}")
        entries = [by_id[entry_id] for entry_id in ids]
    if limit is not None:
        entries = entries[:limit]
    return entries


def secret_values():
    from app.core.config import settings

    return [
        value
        for name, value in settings.model_dump().items()
        if ("key" in name or name == "database_url") and isinstance(value, str) and value
    ]


def describe_error(exc, secrets):
    message = str(exc)
    for secret in secrets:
        message = message.replace(secret, "[redacted]")
    message = " ".join(message.split())
    if len(message) > MAX_ERROR_MESSAGE:
        message = message[: MAX_ERROR_MESSAGE - 3] + "..."
    return {"type": type(exc).__name__, "message": message}


def routing_outcome(label, expected_label):
    if label not in LABELS:
        return "invalid"
    return "correct" if label == expected_label else "wrong"


def run_routing(entries, run=1):
    # Imported here so --help works without a configured environment.
    from app.graph.nodes import classify_question

    secrets = secret_values()
    results = []
    for entry in entries:
        state = {
            "question": entry["question"],
            "question_type": "",
            "answer": "",
            "review_status": "",
            "sources": [],
        }
        result = {
            "run": run,
            "id": entry["id"],
            "type": entry["type"],
            "expected_label": entry["expected_label"],
            "label": None,
            "outcome": None,
            "error": None,
        }
        try:
            label = classify_question(state)["question_type"]
        except Exception as exc:  # one failed call must not stop the run
            result["outcome"] = "error"
            result["error"] = describe_error(exc, secrets)
        else:
            result["label"] = label
            result["outcome"] = routing_outcome(label, entry["expected_label"])
        results.append(result)

        shown = repr(result["label"]) if result["error"] is None else result["error"]["type"]
        print(
            f"{result['id']:<6} {result['type']:<13} {result['expected_label']:<17} "
            f"{shown:<20} {result['outcome']}"
        )
    return results


def summarise_routing(results):
    outcomes = Counter(result["outcome"] for result in results)

    by_type = {}
    for entry_type in ("policy", "not_covered", "general", "out_of_scope"):
        rows = [result for result in results if result["type"] == entry_type]
        correct = sum(result["outcome"] == "correct" for result in rows)
        by_type[entry_type] = {
            "total": len(rows),
            "correct": correct,
            "accuracy": correct / len(rows) if rows else None,
        }

    confusion = {label: {column: 0 for column in CONFUSION_COLUMNS} for label in LABELS}
    for result in results:
        if result["outcome"] in ("invalid", "error"):
            column = result["outcome"]
        else:
            column = result["label"]
        confusion[result["expected_label"]][column] += 1

    runs = max(result["run"] for result in results) if results else 0
    stability = {}
    for result in results:
        if result["id"] not in stability:
            stability[result["id"]] = {"expected_label": result["expected_label"], "labels": Counter()}
        key = result["label"] if result["error"] is None else f"error: {result['error']['type']}"
        stability[result["id"]]["labels"][key] += 1

    return {
        "runs": runs,
        "total": len(results),
        "outcomes": {outcome: outcomes[outcome] for outcome in OUTCOMES},
        "accuracy_by_type": by_type,
        "confusion": confusion,
        "labels_by_question": {
            entry_id: {"expected_label": row["expected_label"], "labels": dict(row["labels"])}
            for entry_id, row in stability.items()
        },
        "changed_between_runs": [
            entry_id for entry_id, row in stability.items() if len(row["labels"]) > 1
        ],
    }


def print_routing_summary(summary):
    if summary["runs"] > 1:
        print(f"\n{summary['runs']} runs; counts below are over all {summary['total']} classifications")
    print(f"\n{summary['total']} classification(s)")
    for outcome, count in summary["outcomes"].items():
        print(f"  {outcome}: {count}")

    print("\nAccuracy by type")
    for entry_type, stats in summary["accuracy_by_type"].items():
        accuracy = "n/a" if stats["accuracy"] is None else f"{stats['accuracy']:.0%}"
        print(f"  {entry_type:<13} {stats['correct']}/{stats['total']}  {accuracy}")

    print("\nConfusion (rows: expected, columns: returned)")
    print(f"  {'':<17}" + "".join(f"{column:>18}" for column in CONFUSION_COLUMNS))
    for expected, row in summary["confusion"].items():
        print(f"  {expected:<17}" + "".join(f"{row[column]:>18}" for column in CONFUSION_COLUMNS))

    if summary["runs"] > 1:
        print(f"\nLabels per question over {summary['runs']} runs")
        for entry_id, row in summary["labels_by_question"].items():
            labels = ", ".join(f"{label!r} x{count}" for label, count in row["labels"].items())
            print(f"  {entry_id:<6} expected {row['expected_label']:<17} {labels}")

        changed = summary["changed_between_runs"]
        print(f"\nChanged label between runs ({len(changed)}): {', '.join(changed) or 'none'}")


def score_retrieval(pages, expected_pages):
    first_hit_rank = next(
        (rank for rank, page in enumerate(pages, start=1) if page in expected_pages),
        None,
    )
    return {
        "hit": first_hit_rank is not None,
        "first_hit_rank": first_hit_rank,
        "distinct_pages": len(set(pages)),
    }


def run_retrieval(entries, k):
    # Imported here so --help works without a configured environment.
    from app.rag.retriever import retrieve_policy_chunks

    secrets = secret_values()
    results = []
    for entry in entries:
        if entry["type"] != SCORED_TYPE and entry["type"] not in UNSCORED_RETRIEVAL_TYPES:
            continue
        scored = entry["type"] == SCORED_TYPE
        result = {
            "id": entry["id"],
            "type": entry["type"],
            "question": entry["question"],
            "expected_pages": entry["expected_pages"],
            "scored": scored,
            "pages": None,
            "hit": None,
            "first_hit_rank": None,
            "distinct_pages": None,
            "error": None,
        }
        try:
            chunks = retrieve_policy_chunks(entry["question"], top_k=k)
        except Exception as exc:  # one failed call must not stop the run
            result["error"] = describe_error(exc, secrets)
        else:
            # The index stores 0-based PDF page indexes; expected_pages are printed pages.
            result["pages"] = [chunk["page"] + 1 for chunk in chunks]
            if scored:
                result.update(score_retrieval(result["pages"], entry["expected_pages"]))
        results.append(result)

        if result["error"] is not None:
            outcome = f"error: {result['error']['type']}"
        elif not scored:
            outcome = "not scored"
        else:
            outcome = f"hit at {result['first_hit_rank']}" if result["hit"] else "miss"
        print(
            f"{result['id']:<6} {result['type']:<13} {str(result['expected_pages']):<14} "
            f"{str(result['pages']):<24} {outcome}"
        )
    return results


def summarise_retrieval(results, k):
    scored = [result for result in results if result["scored"] and result["error"] is None]
    count = len(scored)

    def mean(values):
        return sum(values) / count if count else None

    return {
        "k": k,
        "scored": count,
        "unscored": sum(not result["scored"] for result in results),
        "errors": [
            {"id": result["id"], **result["error"]}
            for result in results
            if result["error"] is not None
        ],
        f"hit_rate_at_{k}": mean([result["hit"] for result in scored]),
        "hit_rate_at_1": mean([result["first_hit_rank"] == 1 for result in scored]),
        "mrr": mean([1 / result["first_hit_rank"] if result["hit"] else 0 for result in scored]),
        "avg_distinct_pages": mean([result["distinct_pages"] for result in scored]),
        "misses": [
            {
                "id": result["id"],
                "question": result["question"],
                "expected_pages": result["expected_pages"],
                "pages": result["pages"],
            }
            for result in scored
            if not result["hit"]
        ],
    }


def print_retrieval_summary(summary):
    k = summary["k"]

    def show(value, as_percent=False):
        if value is None:
            return "n/a"
        return f"{value:.0%}" if as_percent else f"{value:.2f}"

    print(f"\nScored {summary['scored']} policy question(s) at k={k}; {summary['unscored']} not scored")
    print(f"  hit rate at {k}:       {show(summary[f'hit_rate_at_{k}'], as_percent=True)}")
    print(f"  hit rate at 1:       {show(summary['hit_rate_at_1'], as_percent=True)}")
    print(f"  MRR:                 {show(summary['mrr'])}")
    print(f"  avg distinct pages:  {show(summary['avg_distinct_pages'])}")

    print(f"\nMisses ({len(summary['misses'])})")
    for miss in summary["misses"]:
        print(f"  {miss['id']}  {miss['question']}")
        print(f"        expected {miss['expected_pages']}, returned {miss['pages']}")

    if summary["errors"]:
        print(f"\nErrors ({len(summary['errors'])})")
        for error in summary["errors"]:
            print(f"  {error['id']}  {error['type']}: {error['message']}")


def fixed_messages():
    from app.graph.nodes import handle_out_of_scope, handle_rejected_answer

    empty_state = {"question": "", "question_type": "", "answer": "", "review_status": "", "sources": []}
    return {
        "out_of_scope_message": handle_out_of_scope(empty_state)["answer"],
        "rejected_message": handle_rejected_answer(empty_state)["answer"],
    }


def classify_behaviour(answer, messages):
    for behaviour, message in messages.items():
        if answer == message:
            return behaviour
    return "answered"


def format_chunks(chunks):
    if not chunks:
        return "(none)"
    return "\n\n---\n\n".join(
        f"Printed page: {chunk['page']}\n{chunk['content']}" for chunk in chunks
    )


def classify_miss(fact):
    """Label a fact the answer missed. Without chunks (general branch) it is a generation miss."""
    if fact["present"]:
        return None
    return "retrieval_miss" if fact["in_chunks"] is False else "generation_miss"


def parse_judgement(text, must_include, has_chunks):
    judgement = json.loads(text)
    facts = judgement.get("must_include")
    if not isinstance(facts, list) or len(facts) != len(must_include):
        found = len(facts) if isinstance(facts, list) else "no"
        raise ValueError(f"judge returned {found} facts, expected {len(must_include)}")
    if not all(isinstance(fact, dict) and isinstance(fact.get("present"), bool) for fact in facts):
        raise ValueError("judge returned a fact without a boolean 'present'")
    for fact in facts:
        if has_chunks and not isinstance(fact.get("in_chunks"), bool):
            raise ValueError("judge returned a fact without a boolean 'in_chunks'")
        if not has_chunks:
            fact["in_chunks"] = None
        fact["miss"] = classify_miss(fact)
    if not isinstance(judgement.get("refused"), bool):
        raise ValueError("judge returned no boolean 'refused'")
    if has_chunks and not isinstance(judgement.get("faithful"), bool):
        raise ValueError("judge returned no boolean 'faithful' although chunks were given")
    if not has_chunks:
        judgement["faithful"] = None
    return judgement


def score_answer(entry_type, must_include, behaviour, judgement):
    """Return (outcome, reasons) for one judged question."""
    missing = [
        f"missing ({fact['miss']}): {fact['fact']} - {fact.get('reason', '')}"
        for fact in judgement["must_include"]
        if fact["miss"]
    ]

    if entry_type == "policy":
        reasons = list(missing)
        if judgement["faithful"] is not True:
            reasons.append(f"not faithful: {judgement.get('faithful_reason', '')}")
        return ("fail" if reasons else "pass"), reasons
    if entry_type == "not_covered":
        if judgement["refused"] or behaviour == "rejected_message":
            return "pass", []
        return "fail", [f"did not refuse: {judgement.get('refused_reason', '')}"]
    if entry_type == "out_of_scope":
        if behaviour == "out_of_scope_message":
            return "pass", []
        return "fail", [f"behaviour was {behaviour}, not out_of_scope_message"]
    if not must_include:
        return "skipped", ["general question with no must_include (routing only)"]
    return ("fail" if missing else "pass"), missing


def judge_answer(judge, prompt, must_include, has_chunks, rejections):
    """Ask the judge, retrying once if its reply is rejected.

    Each rejected reply is appended to rejections with its raw text. Raises
    ValueError when every attempt is rejected, so the question is marked
    "error" rather than passed or failed by default.
    """
    for attempt in range(1, JUDGE_ATTEMPTS + 1):
        raw = judge.invoke(prompt).content
        try:
            return parse_judgement(raw, must_include, has_chunks)
        except ValueError as exc:  # includes json.JSONDecodeError
            rejections.append({"attempt": attempt, "error": str(exc), "raw": raw})
    raise ValueError(f"judge reply rejected {JUDGE_ATTEMPTS} times: {rejections[-1]['error']}")


def run_answers(entries, run=1):
    # Imported here so --help works without a configured environment.
    from app.ai.client import llm
    from app.graph.workflow import policy_graph
    from app.rag.retriever import retrieve_policy_chunks

    judge = llm.bind(temperature=0, response_format={"type": "json_object"})
    messages = fixed_messages()
    secrets = secret_values()
    results = []
    for entry in entries:
        result = {
            "run": run,
            "id": entry["id"],
            "type": entry["type"],
            "question": entry["question"],
            "question_type": None,
            "review_status": None,
            "answer": None,
            "sources": None,
            "behaviour": None,
            "chunks": None,
            "chunks_match_sources": None,
            "judgement": None,
            "judge_rejections": [],
            "outcome": None,
            "reasons": [],
            "error": None,
        }
        try:
            state = policy_graph.invoke(
                {
                    "question": entry["question"],
                    "question_type": "",
                    "answer": "",
                    "review_status": "",
                    "sources": [],
                }
            )
        except Exception as exc:  # the real graph failing is a failed answer
            result["error"] = describe_error(exc, secrets)
            result["outcome"] = "fail"
            result["reasons"] = [f"graph raised {result['error']['type']}: {result['error']['message']}"]
            results.append(result)
            print_answer_row(result)
            continue

        result["question_type"] = state["question_type"]
        result["review_status"] = state["review_status"]
        result["answer"] = state["answer"]
        result["sources"] = state["sources"]
        result["behaviour"] = classify_behaviour(state["answer"], messages)

        try:
            if entry["type"] in ("policy", "not_covered"):
                chunks = retrieve_policy_chunks(entry["question"], top_k=ANSWER_TOP_K)
                # Chunks keep the index's 0-based page; printed pages are page + 1.
                result["chunks"] = [
                    {"source": chunk["source"], "page": chunk["page"] + 1, "content": chunk["content"]}
                    for chunk in chunks
                ]
                if state["sources"]:
                    retrieved = []
                    # The graph's sources use printed pages, like result["chunks"].
                    for chunk in result["chunks"]:
                        source = {"document": chunk["source"], "page": chunk["page"]}
                        if source not in retrieved:
                            retrieved.append(source)
                    result["chunks_match_sources"] = retrieved == state["sources"]

            prompt = JUDGE_PROMPT.format(
                question=entry["question"],
                answer_key=entry["answer_key"],
                must_include=json.dumps(entry["must_include"]),
                chunks=format_chunks(result["chunks"]),
                answer=state["answer"],
            )
            result["judgement"] = judge_answer(
                judge,
                prompt,
                entry["must_include"],
                has_chunks=bool(result["chunks"]),
                rejections=result["judge_rejections"],
            )
        except Exception as exc:  # an eval-side failure must not stop the run
            result["error"] = describe_error(exc, secrets)
            result["outcome"] = "error"
        else:
            result["outcome"], result["reasons"] = score_answer(
                entry["type"], entry["must_include"], result["behaviour"], result["judgement"]
            )
        results.append(result)
        print_answer_row(result)
    return results


def print_answer_row(result):
    print(
        f"{result['id']:<6} {result['type']:<13} {str(result['question_type']):<17} "
        f"{str(result['review_status'] or '-'):<9} {str(result['behaviour']):<21} {result['outcome']}"
    )


def summarise_answers(results):
    def pass_rate(rows):
        judged = [result for result in rows if result["outcome"] in ("pass", "fail")]
        passed = sum(result["outcome"] == "pass" for result in judged)
        return {
            "judged": len(judged),
            "passed": passed,
            "pass_rate": passed / len(judged) if judged else None,
        }

    policy_judged = [
        result
        for result in results
        if result["type"] == "policy" and result["judgement"] is not None
    ]
    faithful = sum(result["judgement"]["faithful"] is True for result in policy_judged)

    facts = [
        fact
        for result in results
        if result["type"] in ("policy", "general") and result["judgement"] is not None
        for fact in result["judgement"]["must_include"]
    ]
    facts_present = sum(fact["present"] for fact in facts)

    return {
        "total": len(results),
        "outcomes": {
            outcome: sum(result["outcome"] == outcome for result in results)
            for outcome in ANSWER_OUTCOMES
        },
        "overall": pass_rate(results),
        "by_type": {
            entry_type: pass_rate([result for result in results if result["type"] == entry_type])
            for entry_type in ANSWER_TYPES
        },
        "policy_faithful": {
            "judged": len(policy_judged),
            "faithful": faithful,
            "share": faithful / len(policy_judged) if policy_judged else None,
        },
        "fact_recall": {
            "present": facts_present,
            "required": len(facts),
            "recall": facts_present / len(facts) if facts else None,
            "generation_miss": sum(fact["miss"] == "generation_miss" for fact in facts),
            "retrieval_miss": sum(fact["miss"] == "retrieval_miss" for fact in facts),
        },
        "review_status": dict(
            Counter(result["review_status"] or "not reviewed" for result in results if result["answer"] is not None)
        ),
        "failures": [
            {
                "id": result["id"],
                "type": result["type"],
                "question": result["question"],
                "answer": result["answer"],
                "reasons": result["reasons"],
            }
            for result in results
            if result["outcome"] == "fail"
        ],
        "errors": [
            {"id": result["id"], **result["error"], "judge_rejections": result["judge_rejections"]}
            for result in results
            if result["outcome"] == "error"
        ],
    }


def print_answers_summary(summary):
    def show(stats):
        rate = "n/a" if stats["pass_rate"] is None else f"{stats['pass_rate']:.0%}"
        return f"{stats['passed']}/{stats['judged']}  {rate}"

    print(f"\n{summary['total']} question(s)")
    for outcome, count in summary["outcomes"].items():
        print(f"  {outcome}: {count}")

    print(f"\nPass rate (skipped and errors excluded)\n  {'overall':<13} {show(summary['overall'])}")
    for entry_type, stats in summary["by_type"].items():
        print(f"  {entry_type:<13} {show(stats)}")

    faithful = summary["policy_faithful"]
    share = "n/a" if faithful["share"] is None else f"{faithful['share']:.0%}"
    print(f"\nPolicy answers faithful: {faithful['faithful']}/{faithful['judged']}  {share}")

    recall = summary["fact_recall"]
    rate = "n/a" if recall["recall"] is None else f"{recall['recall']:.0%}"
    print(f"\nFact recall (policy and general): {recall['present']}/{recall['required']}  {rate}")
    print(f"  generation_miss: {recall['generation_miss']}")
    print(f"  retrieval_miss:  {recall['retrieval_miss']}")

    print("\nReview status")
    for status, count in summary["review_status"].items():
        print(f"  {status}: {count}")

    print(f"\nFailures ({len(summary['failures'])})")
    for failure in summary["failures"]:
        print(f"  {failure['id']}  {failure['question']}")
        print(f"        answer: {failure['answer']}")
        for reason in failure["reasons"]:
            print(f"        - {reason}")

    if summary["errors"]:
        print(f"\nErrors ({len(summary['errors'])})")
        for error in summary["errors"]:
            print(f"  {error['id']}  {error['type']}: {error['message']}")
            for rejection in error["judge_rejections"]:
                print(f"        attempt {rejection['attempt']} rejected: {rejection['error']}")
                print(f"        raw reply: {rejection['raw']}")


def summarise_answer_runs(results, run_summaries):
    def mean_rate(rates):
        rates = [rate for rate in rates if rate is not None]
        return sum(rates) / len(rates) if rates else None

    per_question = {}
    for result in results:
        if result["id"] not in per_question:
            per_question[result["id"]] = {
                "type": result["type"],
                "outcomes": {outcome: 0 for outcome in ANSWER_OUTCOMES},
            }
        per_question[result["id"]]["outcomes"][result["outcome"]] += 1

    return {
        "runs": len(run_summaries),
        "per_question": per_question,
        "mean_pass_rate": {
            "overall": mean_rate([summary["overall"]["pass_rate"] for summary in run_summaries]),
            **{
                entry_type: mean_rate(
                    [summary["by_type"][entry_type]["pass_rate"] for summary in run_summaries]
                )
                for entry_type in ANSWER_TYPES
            },
        },
        "per_run": run_summaries,
    }


def print_answer_runs_summary(summary):
    runs = summary["runs"]
    print(f"\n===== Across {runs} runs")
    print("\nPasses per question")
    for entry_id, row in summary["per_question"].items():
        others = ", ".join(
            f"{count} {outcome}"
            for outcome, count in row["outcomes"].items()
            if outcome != "pass" and count
        )
        print(f"  {entry_id:<6} {row['type']:<13} {row['outcomes']['pass']}/{runs}" + (f"  ({others})" if others else ""))

    print("\nPass rate averaged over runs (skipped and errors excluded per run)")
    for scope, rate in summary["mean_pass_rate"].items():
        print(f"  {scope:<13} {'n/a' if rate is None else f'{rate:.0%}'}")


def save_results(name, part, started_at, summary, results):
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{started_at:%Y%m%dT%H%M%SZ}_{name}.json"
    payload = {
        "part": part,
        "started_at": started_at.isoformat(),
        "summary": summary,
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", required=True, choices=("routing", "retrieval", "answers"))
    parser.add_argument("--limit", type=int, help="run only the first N questions")
    parser.add_argument("--ids", help="comma-separated question ids, e.g. q01,q05")
    parser.add_argument("--k", type=int, default=3, help="chunks to retrieve (retrieval only, default 3)")
    parser.add_argument(
        "--repeat", type=int, default=1, help="run the set N times (routing and answers, default 1)"
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.k < 1:
        parser.error("--k must be at least 1")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    if args.repeat > 1 and args.part == "retrieval":
        parser.error("--repeat is only supported with --part routing or --part answers")
    args.ids = [entry_id.strip() for entry_id in args.ids.split(",") if entry_id.strip()] if args.ids else []
    return args


def main(argv=None):
    # Model answers can contain characters the Windows console code page cannot
    # encode; without this, printing them crashes the run before results are saved.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    entries = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    entries = select_entries(entries, args.ids, args.limit)
    started_at = datetime.now(timezone.utc).replace(microsecond=0)

    if args.part == "routing":
        name = "routing"
        results = []
        for run in range(1, args.repeat + 1):
            if args.repeat > 1:
                print(f"\nRun {run}/{args.repeat}")
            print(f"{'id':<6} {'type':<13} {'expected':<17} {'label':<20} outcome")
            results += run_routing(entries, run)
        summary = summarise_routing(results)
        print_routing_summary(summary)
    elif args.part == "answers":
        name = "answers"
        results = []
        run_summaries = []
        for run in range(1, args.repeat + 1):
            if args.repeat > 1:
                print(f"\n===== Run {run}/{args.repeat}")
            print(f"{'id':<6} {'type':<13} {'question_type':<17} {'review':<9} {'behaviour':<21} outcome")
            run_results = run_answers(entries, run)
            run_summaries.append(summarise_answers(run_results))
            print_answers_summary(run_summaries[-1])
            results += run_results
        if args.repeat > 1:
            summary = summarise_answer_runs(results, run_summaries)
            print_answer_runs_summary(summary)
        else:
            summary = run_summaries[0]
    else:
        name = f"retrieval_k{args.k}"
        print(f"{'id':<6} {'type':<13} {'expected':<14} {'returned':<24} outcome")
        results = run_retrieval(entries, args.k)
        summary = summarise_retrieval(results, args.k)
        print_retrieval_summary(summary)

    path = save_results(name, args.part, started_at, summary, results)
    print(f"\nResults saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

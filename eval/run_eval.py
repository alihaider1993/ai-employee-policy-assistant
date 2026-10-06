"""Run the golden question set against live Azure OpenAI and Azure AI Search.

Not a unit test: this calls live services and is not collected by pytest.
It calls graph nodes and the retriever directly and never goes through /ask
or the database.

Run from the repo root as a module so app.* imports resolve:

    python -m eval.run_eval --part routing
    python -m eval.run_eval --part routing --limit 5
    python -m eval.run_eval --part routing --ids q01,q05
    python -m eval.run_eval --part retrieval --k 5

Results are saved to eval/results/<timestamp>_routing.json and
eval/results/<timestamp>_retrieval_k<K>.json.
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


def run_routing(entries):
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

    return {
        "total": len(results),
        "outcomes": {outcome: outcomes[outcome] for outcome in OUTCOMES},
        "accuracy_by_type": by_type,
        "confusion": confusion,
    }


def print_routing_summary(summary):
    print(f"\n{summary['total']} question(s)")
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
    parser.add_argument("--part", required=True, choices=("routing", "retrieval"))
    parser.add_argument("--limit", type=int, help="run only the first N questions")
    parser.add_argument("--ids", help="comma-separated question ids, e.g. q01,q05")
    parser.add_argument("--k", type=int, default=3, help="chunks to retrieve (retrieval only, default 3)")
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.k < 1:
        parser.error("--k must be at least 1")
    args.ids = [entry_id.strip() for entry_id in args.ids.split(",") if entry_id.strip()] if args.ids else []
    return args


def main(argv=None):
    args = parse_args(argv)
    entries = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    entries = select_entries(entries, args.ids, args.limit)
    started_at = datetime.now(timezone.utc).replace(microsecond=0)

    if args.part == "routing":
        name = "routing"
        print(f"{'id':<6} {'type':<13} {'expected':<17} {'label':<20} outcome")
        results = run_routing(entries)
        summary = summarise_routing(results)
        print_routing_summary(summary)
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

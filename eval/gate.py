"""Quality gate: fail when eval results fall below the thresholds in eval/thresholds.json.

Run from the repo root after the eval parts have written their result files:

    python -m eval.gate eval/results/<routing>.json eval/results/<answers>.json

Each threshold is {"min": x} (a rate that must not drop below x) or {"max": y}
(a latency or cost that must not rise above y). Metrics whose result file was
not passed in are skipped. Exits 1 when any checked metric fails.
"""

import json
import sys
from pathlib import Path

THRESHOLDS_PATH = Path(__file__).parent / "thresholds.json"


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def extract_metrics(payload):
    """Flatten one results file into {metric name: value}."""
    part, summary = payload["part"], payload["summary"]

    if part == "routing":
        total = summary["total"]
        return {"routing.accuracy": summary["outcomes"]["correct"] / total if total else None}

    if part == "retrieval":
        return {
            "retrieval.hit_rate": summary[f"hit_rate_at_{summary['k']}"],
            "retrieval.mrr": summary["mrr"],
        }

    if part == "answers":
        # With --repeat the summary holds averaged rates and a list of per-run summaries.
        runs = summary.get("per_run", [summary])
        rates = summary["mean_pass_rate"] if "mean_pass_rate" in summary else {
            "overall": summary["overall"]["pass_rate"],
            "policy": summary["by_type"]["policy"]["pass_rate"],
            "not_covered": summary["by_type"]["not_covered"]["pass_rate"],
        }
        overall = summary["performance"]["overall"]
        return {
            "answers.overall": rates["overall"],
            "answers.policy": rates["policy"],
            "answers.not_covered": rates["not_covered"],
            "answers.faithful": mean([run["policy_faithful"]["share"] for run in runs]),
            "answers.fact_recall": mean([run["fact_recall"]["recall"] for run in runs]),
            "answers.latency_p95_s": overall.get("latency_p95_s"),
            "answers.cost_per_question_usd": overall.get("mean_cost_usd"),
        }

    if part == "injection":
        return {
            "injection.pass_rate": summary["overall"]["pass_rate"],
            "injection.control_pass_rate": summary["by_category"].get("control", {}).get("pass_rate"),
        }

    return {}


def evaluate(metrics, thresholds):
    """Return (rows, ok). Each row is (metric, value, limit text, passed)."""
    rows = []
    for name, rule in thresholds.items():
        if name not in metrics:
            continue
        value = metrics[name]
        if "min" in rule:
            limit, passed = f">= {rule['min']}", value is not None and value >= rule["min"]
        else:
            limit, passed = f"<= {rule['max']}", value is not None and value <= rule["max"]
        rows.append((name, value, limit, passed))
    return rows, all(row[3] for row in rows)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = [arg for arg in argv if not arg.startswith("--")]
    if not paths:
        print("Pass at least one eval results file.")
        return 2

    metrics = {}
    for path in paths:
        metrics.update(extract_metrics(json.loads(Path(path).read_text(encoding="utf-8"))))
    thresholds = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

    rows, ok = evaluate(metrics, thresholds)
    if not rows:
        print("None of the thresholds match the metrics in these files.")
        return 2
    for name, value, limit, passed in rows:
        shown = "n/a" if value is None else f"{value:.4g}"
        print(f"{'PASS' if passed else 'FAIL'}  {name:<32} {shown:>8}  (needs {limit})")
    print("\nQuality gate passed." if ok else "\nQuality gate FAILED.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

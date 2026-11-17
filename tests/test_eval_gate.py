from eval import gate


def answers_payload(overall=0.93, policy=0.91, faithful=0.94, recall=0.95, p95=9.0, cost=0.004):
    return {
        "part": "answers",
        "summary": {
            "overall": {"pass_rate": overall},
            "by_type": {"policy": {"pass_rate": policy}, "not_covered": {"pass_rate": 1.0}},
            "policy_faithful": {"share": faithful},
            "fact_recall": {"recall": recall},
            "performance": {"overall": {"latency_p95_s": p95, "mean_cost_usd": cost}},
        },
    }


def test_answers_metrics_come_from_a_single_run_summary():
    metrics = gate.extract_metrics(answers_payload())

    assert metrics["answers.policy"] == 0.91
    assert metrics["answers.latency_p95_s"] == 9.0


def test_answers_metrics_average_over_repeated_runs():
    run_a, run_b = answers_payload(faithful=0.90)["summary"], answers_payload(faithful=0.96)["summary"]
    payload = {
        "part": "answers",
        "summary": {
            "mean_pass_rate": {"overall": 0.9, "policy": 0.85, "not_covered": 1.0},
            "per_run": [run_a, run_b],
            "performance": {"overall": {"latency_p95_s": 8.0, "mean_cost_usd": 0.005}},
        },
    }

    metrics = gate.extract_metrics(payload)

    assert metrics["answers.overall"] == 0.9
    assert abs(metrics["answers.faithful"] - 0.93) < 1e-9


def test_routing_retrieval_and_injection_metrics():
    routing = {"part": "routing", "summary": {"total": 138, "outcomes": {"correct": 137}}}
    retrieval = {"part": "retrieval", "summary": {"k": 3, "hit_rate_at_3": 0.94, "mrr": 0.86}}
    injection = {
        "part": "injection",
        "summary": {"overall": {"pass_rate": 0.9}, "by_category": {"control": {"pass_rate": 1.0}}},
    }

    assert abs(gate.extract_metrics(routing)["routing.accuracy"] - 137 / 138) < 1e-9
    assert gate.extract_metrics(retrieval) == {"retrieval.hit_rate": 0.94, "retrieval.mrr": 0.86}
    assert gate.extract_metrics(injection)["injection.control_pass_rate"] == 1.0


def test_gate_fails_when_a_rate_drops_or_a_cost_rises():
    thresholds = {
        "answers.policy": {"min": 0.8},
        "answers.cost_per_question_usd": {"max": 0.01},
    }

    _, ok = gate.evaluate(gate.extract_metrics(answers_payload(policy=0.75)), thresholds)
    assert not ok

    _, ok = gate.evaluate(gate.extract_metrics(answers_payload(cost=0.02)), thresholds)
    assert not ok

    rows, ok = gate.evaluate(gate.extract_metrics(answers_payload()), thresholds)
    assert ok and len(rows) == 2


def test_gate_skips_metrics_without_a_results_file_and_fails_on_missing_values():
    thresholds = {"routing.accuracy": {"min": 0.95}, "answers.policy": {"min": 0.8}}

    rows, ok = gate.evaluate({"answers.policy": 0.9}, thresholds)
    assert [row[0] for row in rows] == ["answers.policy"] and ok

    _, ok = gate.evaluate({"answers.policy": None}, thresholds)
    assert not ok


def test_shipped_thresholds_name_metrics_the_gate_can_produce():
    import json

    thresholds = json.loads(gate.THRESHOLDS_PATH.read_text(encoding="utf-8"))
    producible = set()
    for payload in (
        {"part": "routing", "summary": {"total": 1, "outcomes": {"correct": 1}}},
        {"part": "retrieval", "summary": {"k": 3, "hit_rate_at_3": 1, "mrr": 1}},
        answers_payload(),
        {"part": "injection", "summary": {"overall": {"pass_rate": 1}, "by_category": {}}},
    ):
        producible |= set(gate.extract_metrics(payload))

    assert set(thresholds) <= producible
    for rule in thresholds.values():
        assert ("min" in rule) != ("max" in rule)

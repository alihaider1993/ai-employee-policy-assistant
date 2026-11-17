import pytest

from eval import metrics


def test_percentile_interpolates_between_values():
    values = [1.0, 2.0, 3.0, 4.0]

    assert metrics.percentile(values, 50) == pytest.approx(2.5)
    assert metrics.percentile(values, 95) == pytest.approx(3.85)
    assert metrics.percentile([7.0], 95) == 7.0
    assert metrics.percentile([], 95) is None


def test_cost_uses_input_and_output_prices():
    # 1,000 input tokens at $2.50 per million plus 500 output tokens at $10 per million.
    assert metrics.cost_usd(1000, 500) == pytest.approx(0.0025 + 0.005)


def test_summary_groups_by_type_and_skips_unmeasured_results():
    results = [
        {"type": "policy", "latency_s": 4.0, "input_tokens": 2000, "output_tokens": 200},
        {"type": "policy", "latency_s": 6.0, "input_tokens": 2400, "output_tokens": 300},
        {"type": "general", "latency_s": 1.0, "input_tokens": 50, "output_tokens": 40},
        {"type": "policy", "latency_s": None, "input_tokens": None, "output_tokens": None},
    ]

    summary = metrics.summarise_performance(results)

    assert summary["overall"]["count"] == 3
    assert summary["by_type"]["policy"]["count"] == 2
    assert summary["by_type"]["policy"]["latency_mean_s"] == pytest.approx(5.0)
    assert summary["by_type"]["policy"]["mean_input_tokens"] == pytest.approx(2200)
    assert summary["by_type"]["general"]["latency_p95_s"] == 1.0


def test_summary_with_no_measurements_is_empty():
    summary = metrics.summarise_performance([])

    assert summary["overall"] == {"count": 0}
    assert metrics.format_performance(summary) == []

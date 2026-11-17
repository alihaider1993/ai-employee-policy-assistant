"""Latency and cost figures for the answers eval.

Pure functions with no Azure imports, so they can be unit-tested.

Latency is the wall-clock time of one policy_graph.invoke call: classification,
retrieval (embedding plus search), generation and review. It excludes the answer
cache, the database and the network between a visitor and the app.

Cost counts only the chat model tokens the graph used, taken from the model's
usage metadata. It excludes the judge's calls, which exist only in the eval. The
embedding call is also excluded: a question is about 20 tokens, which costs
well under 0.0001 US cents at text-embedding-3-small prices.
"""

# Azure OpenAI GPT-4o list prices in US dollars per million tokens. These are
# assumptions: check the price for your deployment's region and model version
# before quoting a cost figure.
INPUT_USD_PER_MILLION = 2.50
OUTPUT_USD_PER_MILLION = 10.00


def percentile(values, pct):
    """Linear-interpolated percentile (pct from 0 to 100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def cost_usd(input_tokens, output_tokens):
    return (
        input_tokens * INPUT_USD_PER_MILLION + output_tokens * OUTPUT_USD_PER_MILLION
    ) / 1_000_000


def _group(rows):
    if not rows:
        return {"count": 0}
    latencies = [row["latency_s"] for row in rows]
    costs = [cost_usd(row["input_tokens"], row["output_tokens"]) for row in rows]
    return {
        "count": len(rows),
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "latency_mean_s": sum(latencies) / len(latencies),
        "mean_input_tokens": sum(row["input_tokens"] for row in rows) / len(rows),
        "mean_output_tokens": sum(row["output_tokens"] for row in rows) / len(rows),
        "mean_cost_usd": sum(costs) / len(costs),
    }


def summarise_performance(results):
    """Latency and cost over results that carry latency_s, input_tokens and output_tokens."""
    measured = [
        result
        for result in results
        if result.get("latency_s") is not None and result.get("input_tokens") is not None
    ]
    return {
        "pricing_usd_per_million_tokens": {
            "input": INPUT_USD_PER_MILLION,
            "output": OUTPUT_USD_PER_MILLION,
        },
        "overall": _group(measured),
        "by_type": {
            entry_type: _group([row for row in measured if row["type"] == entry_type])
            for entry_type in sorted({row["type"] for row in measured})
        },
    }


def format_performance(performance):
    lines = []
    for scope, stats in (("overall", performance["overall"]), *performance["by_type"].items()):
        if not stats["count"]:
            continue
        lines.append(
            f"  {scope:<13} n={stats['count']:<3} "
            f"p50 {stats['latency_p50_s']:.1f}s  p95 {stats['latency_p95_s']:.1f}s  "
            f"{stats['mean_input_tokens']:.0f} in / {stats['mean_output_tokens']:.0f} out tokens  "
            f"${stats['mean_cost_usd']:.4f} per question"
        )
    return lines

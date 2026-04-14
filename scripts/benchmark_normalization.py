from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.normalization.normalize_input import InputNormalizer
from orchestrator.world_state.world_model import build_world_model


SAMPLE_INPUTS = [
    "I walk into the bar",
    "I go in and talk to Mara",
    "I inspect the door lock and check out the stairs",
    "I head to the gate and look for clues",
    "I grab the rope and run into the tavern",
    "Can I make a perception check around the room?",
    "I jump over the counter and attack the guard",
    "I speak with Brin and ask about the wedding date",
    "I make my way to the old well and examine the stones",
    "I use stealth to sneak through the alley",
]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * p
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def run_benchmark(top_n: int, rounds: int) -> dict:
    normalizer = InputNormalizer.for_world_model(build_world_model(), synonym_top_n=top_n)

    # warm cache
    for text in SAMPLE_INPUTS:
        normalizer.normalize(text)

    latencies_ms: List[float] = []
    for _ in range(rounds):
        for text in SAMPLE_INPUTS:
            start = time.perf_counter()
            normalizer.normalize(text)
            elapsed = (time.perf_counter() - start) * 1000.0
            latencies_ms.append(elapsed)

    latencies_ms.sort()
    return {
        "top_n": top_n,
        "samples": len(latencies_ms),
        "avg_ms": statistics.fmean(latencies_ms),
        "p50_ms": percentile(latencies_ms, 0.50),
        "p95_ms": percentile(latencies_ms, 0.95),
        "p99_ms": percentile(latencies_ms, 0.99),
        "max_ms": max(latencies_ms),
    }


def parse_top_values(raw: str) -> List[int]:
    values: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(max(1, int(part)))
    return values or [20, 40, 80, 120]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark normalization speed vs synonym top-N.")
    parser.add_argument(
        "--top-values",
        default="20,40,80,120,160,200",
        help="Comma-separated top-N values to benchmark.",
    )
    parser.add_argument("--rounds", type=int, default=80, help="Rounds over sample input set.")
    parser.add_argument(
        "--p95-budget-ms",
        type=float,
        default=2.0,
        help="Optional p95 latency budget in ms for recommendation.",
    )
    args = parser.parse_args()

    top_values = parse_top_values(args.top_values)
    results = [run_benchmark(top_n=value, rounds=max(1, args.rounds)) for value in top_values]

    print("top_n,samples,avg_ms,p50_ms,p95_ms,p99_ms,max_ms")
    for row in results:
        print(
            f"{row['top_n']},{row['samples']},{row['avg_ms']:.4f},{row['p50_ms']:.4f},"
            f"{row['p95_ms']:.4f},{row['p99_ms']:.4f},{row['max_ms']:.4f}"
        )

    within_budget = [row for row in results if row["p95_ms"] <= args.p95_budget_ms]
    if within_budget:
        best = max(within_budget, key=lambda row: row["top_n"])
        print(
            f"\nRecommended top_n under p95<={args.p95_budget_ms:.2f}ms: "
            f"{best['top_n']} (p95={best['p95_ms']:.4f}ms)"
        )
    else:
        fastest = min(results, key=lambda row: row["p95_ms"])
        print(
            f"\nNo top_n met p95<={args.p95_budget_ms:.2f}ms; fastest p95 is "
            f"{fastest['p95_ms']:.4f}ms at top_n={fastest['top_n']}."
        )


if __name__ == "__main__":
    main()

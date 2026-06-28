#!/usr/bin/env python3
"""10-use-case performance benchmark for the evolutionary harness.

Usage:
    python tests/bench_prompts.py [--generations N] [--no-color]

Runs 10 diverse prompts through the pipeline (mock agents, 2 generations each)
and prints a comparison table of scores, timing, agent count, and evolution delta.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import List, Optional

# Make sure src/ is importable when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import mongomock

from src.compiler.compiler import HarnessCompiler
from src.memory.store import MongoMemoryStore
from src.pipeline import EvolutionPipeline

# ---------------------------------------------------------------------------
# 10 diverse use cases
# ---------------------------------------------------------------------------

PROMPTS = [
    # (task_description, domain, label)
    (
        "Implement a token-bucket rate limiter for an HTTP API with configurable burst limits",
        "software_engineering",
        "Rate Limiter",
    ),
    (
        "Build an in-memory LRU cache with TTL expiry and thread-safe eviction",
        "software_engineering",
        "LRU Cache",
    ),
    (
        "Add a feature flag system to toggle features per user or percentage rollout",
        "software_engineering",
        "Feature Flags",
    ),
    (
        "Design a webhook handler with retry logic, signature verification, and dead-letter queue",
        "software_engineering",
        "Webhook Handler",
    ),
    (
        "Refactor the authentication middleware to use JWT with refresh token rotation",
        "software_engineering",
        "JWT Auth",
    ),
    (
        "Research recent advances in large language model reasoning capabilities (2024–2025)",
        "research",
        "LLM Research",
    ),
    (
        "Analyze and compare the top 5 open-source vector databases for production RAG systems",
        "research",
        "Vector DB Comparison",
    ),
    (
        "Build an ETL pipeline to ingest CSV sales data, normalize it, and load to a Postgres table",
        "data_pipeline",
        "CSV ETL",
    ),
    (
        "Create a real-time event streaming pipeline from Kafka to a data warehouse",
        "data_pipeline",
        "Kafka Pipeline",
    ),
    (
        "Implement a recommendation engine using collaborative filtering on user purchase history",
        "software_engineering",
        "Recommender Engine",
    ),
]

# ANSI colors (disabled with --no-color)
_COLOR = True


def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    codes = {
        "green": "\033[92m",
        "red": "\033[91m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    }
    return codes.get(code, "") + text + codes["reset"]


def _make_store() -> MongoMemoryStore:
    client = mongomock.MongoClient()
    return MongoMemoryStore(db=client["bench_demo"])


def _bar(score: float, width: int = 20) -> str:
    filled = int(round(score / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    if score >= 70:
        return _c("green", bar)
    elif score >= 40:
        return _c("yellow", bar)
    return _c("red", bar)


def run_benchmark(max_generations: int = 2) -> None:
    compiler = HarnessCompiler(client=None)  # mock mode

    # Column headers
    header = (
        f"{'#':>2}  {'Label':<22}  {'Domain':<18}  "
        f"{'Gen1':>5}  {'Final':>5}  {'Delta':>6}  {'Gens':>4}  "
        f"{'Agents':>6}  {'Calls':>5}  {'Time':>6}  {'Pass?':<5}  Progress"
    )
    sep = "─" * len(header)
    print()
    print(_c("bold", "  Evolutionary AI Harness — 10-Prompt Benchmark"))
    print(_c("dim", f"  mock agents · {max_generations} generation(s) per prompt"))
    print()
    print(_c("dim", sep))
    print(_c("bold", header))
    print(_c("dim", sep))

    results = []
    total_start = time.monotonic()

    for i, (task, domain, label) in enumerate(PROMPTS, start=1):
        store = _make_store()
        prompt_start = time.monotonic()

        try:
            harness = compiler.compile(task, domain=domain)
            pipeline = EvolutionPipeline(store, agent_runner=None, event_bus=None)
            cycle_results = pipeline.run_evolution(harness, max_generations=max_generations)
        except Exception as exc:
            print(f"  {i:>2}  {label:<22}  {domain:<18}  ERROR: {exc}")
            continue

        elapsed = time.monotonic() - prompt_start

        gen1_score = cycle_results[0].evaluation.total_score if cycle_results else 0.0
        final_score = cycle_results[-1].evaluation.total_score if cycle_results else 0.0
        delta = final_score - gen1_score
        gens = len(cycle_results)
        agent_count = len(harness.agents)
        final_agent_count = len(cycle_results[-1].harness.agents) if cycle_results else agent_count
        total_calls = sum(r.run.total_tool_calls for r in cycle_results)
        passed = cycle_results[-1].evaluation.passed_threshold if cycle_results else False

        delta_str = f"{delta:+.1f}"
        delta_colored = _c("green", delta_str) if delta > 0 else (_c("dim", delta_str) if delta == 0 else _c("red", delta_str))

        pass_str = _c("green", "YES ✓") if passed else _c("red", "NO  ✗")

        agents_str = f"{agent_count}"
        if final_agent_count != agent_count:
            agents_str = f"{agent_count}→{final_agent_count}"

        row = (
            f"  {i:>2}  {label:<22}  {domain:<18}  "
            f"{gen1_score:>5.1f}  {final_score:>5.1f}  {delta_colored:>6}  {gens:>4}  "
            f"{agents_str:>6}  {total_calls:>5}  {elapsed:>5.1f}s  {pass_str:<5}  {_bar(final_score)}"
        )
        print(row)

        results.append({
            "label": label,
            "domain": domain,
            "gen1_score": gen1_score,
            "final_score": final_score,
            "delta": delta,
            "gens": gens,
            "initial_agents": agent_count,
            "final_agents": final_agent_count,
            "total_calls": total_calls,
            "elapsed": elapsed,
            "passed": passed,
        })

    total_elapsed = time.monotonic() - total_start

    print(_c("dim", sep))

    if results:
        avg_gen1 = sum(r["gen1_score"] for r in results) / len(results)
        avg_final = sum(r["final_score"] for r in results) / len(results)
        avg_delta = avg_final - avg_gen1
        n_passed = sum(1 for r in results if r["passed"])
        best = max(results, key=lambda r: r["final_score"])
        worst = min(results, key=lambda r: r["final_score"])
        most_improved = max(results, key=lambda r: r["delta"])

        delta_str = f"{avg_delta:+.1f}"
        print()
        print(_c("bold", "  Summary"))
        print(f"  Prompts run       : {len(results)}/{len(PROMPTS)}")
        print(f"  Avg gen-1 score   : {avg_gen1:.1f}")
        print(f"  Avg final score   : {avg_final:.1f}  ({delta_str})")
        print(f"  Threshold passed  : {n_passed}/{len(results)}  (threshold = 70.0)")
        print(f"  Best prompt       : {best['label']}  ({best['final_score']:.1f})")
        print(f"  Worst prompt      : {worst['label']}  ({worst['final_score']:.1f})")
        print(f"  Most improved     : {most_improved['label']}  ({most_improved['delta']:+.1f})")
        print(f"  Total wall time   : {total_elapsed:.1f}s")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="10-prompt evolutionary harness benchmark")
    parser.add_argument("--generations", type=int, default=2, help="Generations per prompt (default: 2)")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    args = parser.parse_args()

    global _COLOR
    _COLOR = not args.no_color

    run_benchmark(max_generations=args.generations)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .benchmark import print_results_table, run_benchmark
from .paths import PACKAGE_ROOT

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RescueBench Modular Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 -m rescuebench_agent --mode deterministic --tier all
  python3 -m rescuebench_agent --provider anthropic --mode react --tier 1 --runs 1 --api-key <key>
  python3 -m rescuebench_agent --provider anthropic --mode all --tier 2 --runs 3 --api-key <key>
        """,
    )
    parser.add_argument(
        "--mode",
        default="deterministic",
        choices=["deterministic", "react", "zero_shot", "ablated", "agentkit", "all"],
        help="Evaluation mode (default: deterministic)",
    )
    parser.add_argument(
        "--tier",
        default="all",
        help="Tier to run: 1, 2, 3, 4, or 'all' (default: all)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per scenario (default: 3)",
    )
    parser.add_argument(
        "--provider",
        default="anthropic",
        choices=["anthropic", "gemini"],
        help="LLM provider (default: anthropic)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Provider API key (overrides GEMINI_API_KEY / ANTHROPIC_API_KEY env vars)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.mode == "all":
        modes = ["deterministic", "zero_shot", "ablated", "react", "agentkit"]
    else:
        modes = [args.mode]

    if args.tier == "all":
        tiers = [1, 2, 3, 4]
    else:
        tiers = [int(args.tier)]

    provider = args.provider
    if provider == "gemini":
        api_key = args.api_key or os.getenv("GEMINI_API_KEY")
        default_model = "gemini-2.5-flash"
    else:
        api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY")
        default_model = "claude-sonnet-4-5"
    model = args.model or default_model

    llm_modes = {"react", "zero_shot", "ablated", "agentkit"}
    needs_api = bool(set(modes) & llm_modes)
    if needs_api and not api_key:
        env_var = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
        print(
            f"WARNING: No API key provided for provider '{provider}'. "
            f"LLM modes will fail.\nSet {env_var} or use --api-key."
        )

    print("\nRescueBench Modular Benchmark Runner")
    print(f"  Provider: {provider}")
    print(f"  Modes : {modes}")
    print(f"  Tiers : {tiers}")
    print(f"  Runs  : {args.runs} per scenario")
    print(f"  Model : {model}")

    start = time.time()
    all_results = run_benchmark(
        modes=modes,
        tiers=tiers,
        num_runs=args.runs,
        api_key=api_key,
        model=model,
        provider=provider,
    )
    elapsed = time.time() - start

    print_results_table(all_results)
    print(f"\nTotal runtime: {elapsed:.1f}s")

    output_path = PACKAGE_ROOT / "benchmark_results.json"
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(all_results, fh, indent=2)
    print(f"Results saved to: {output_path}")

from __future__ import annotations

import os

from .agents.rescue_agent import run_agentkit
from .modes.deterministic import run_deterministic
from .modes.react import run_react
from .modes.zero_shot import run_zero_shot
from .paths import get_scenario_files
from .scenarios import load_scenario


def run_scenario(
    scenario_path: str,
    mode: str,
    api_key: str | None,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict:
    """Load and run a single scenario in the specified mode."""
    scenario_dict = load_scenario(scenario_path)
    scenario_name = scenario_dict["scenario_id"]
    print(f"\n  Running: {scenario_name} | mode={mode} | provider={provider}")

    if mode == "deterministic":
        return run_deterministic(scenario_dict)
    if mode == "react":
        if not api_key:
            raise ValueError("API key required for react mode.")
        return run_react(scenario_dict, api_key=api_key, model=model, use_validator=True, provider=provider)
    if mode == "ablated":
        if not api_key:
            raise ValueError("API key required for ablated mode.")
        return run_react(scenario_dict, api_key=api_key, model=model, use_validator=False, provider=provider)
    if mode == "zero_shot":
        if not api_key:
            raise ValueError("API key required for zero_shot mode.")
        return run_zero_shot(scenario_dict, api_key=api_key, model=model, provider=provider)
    if mode == "agentkit":
        return run_agentkit(
            scenario_dict,
            api_key=api_key,
            model=model,
            use_llm_for_ethics=True,
            provider=provider,
        )
    raise ValueError(f"Unknown mode: {mode}")


def aggregate_tier_results(results: list[dict]) -> dict:
    """Compute mean metrics across per-scenario results."""
    if not results:
        return {}

    keys = ["pwrs", "cap_pwrs", "resolution_rate", "deadline_adherence", "violation_count"]
    aggregate: dict = {}
    for key in keys:
        values = [result[key] for result in results if key in result and result[key] is not None]
        aggregate[key] = round(sum(values) / len(values), 4) if values else None

    efficiency_values = [
        result["step_efficiency"] for result in results if result.get("step_efficiency") is not None
    ]
    aggregate["step_efficiency"] = (
        round(sum(efficiency_values) / len(efficiency_values), 4) if efficiency_values else None
    )
    return aggregate


def print_results_table(all_results: dict[str, dict[int, dict]]) -> None:
    """Print an aggregated benchmark table."""
    print("\n" + "=" * 100)
    print("  RESCUEBENCH BENCHMARK RESULTS")
    print("=" * 100)
    header = (
        f"{'Method':<20} {'Tier':<6} {'PWRS':<8} {'Cap-PWRS':<10} "
        f"{'Res.Rate':<10} {'DL Adh.':<10} {'Violations':<12} {'Step Eff.':<10}"
    )
    print(header)
    print("-" * 100)

    mode_labels = {
        "deterministic": "Deterministic",
        "zero_shot": "Zero-Shot LLM",
        "ablated": "ReAct (Ablated)",
        "react": "ReAct (Full)",
        "agentkit": "AgentKit (Ours)",
    }
    mode_order = ["deterministic", "zero_shot", "ablated", "react", "agentkit"]

    for mode in mode_order:
        if mode not in all_results:
            continue
        for tier in sorted(all_results[mode].keys()):
            aggregate = all_results[mode][tier]
            efficiency = (
                f"{aggregate['step_efficiency']:.3f}" if aggregate.get("step_efficiency") is not None else "N/A"
            )
            print(
                f"{mode_labels.get(mode, mode):<20} {tier:<6} "
                f"{aggregate.get('pwrs', 0):<8.3f} {aggregate.get('cap_pwrs', 0):<10.3f} "
                f"{aggregate.get('resolution_rate', 0):<10.3f} "
                f"{aggregate.get('deadline_adherence', 0):<10.3f} "
                f"{aggregate.get('violation_count', 0):<12.1f} "
                f"{efficiency:<10}"
            )

    print("=" * 100)

    print("\nABLATION SUMMARY (averaged across all tiers):")
    print("-" * 70)
    print(f"{'Method':<20} {'Mean PWRS':<12} {'Mean Cap-PWRS':<15} {'Mean Viol.':<12} {'Mean Step Eff.':<14}")
    print("-" * 70)
    for mode in mode_order:
        if mode not in all_results:
            continue
        tier_aggregates = list(all_results[mode].values())
        mean_pwrs = round(sum(item.get("pwrs", 0) for item in tier_aggregates) / len(tier_aggregates), 3)
        mean_cap_pwrs = round(
            sum(item.get("cap_pwrs", 0) for item in tier_aggregates) / len(tier_aggregates), 3
        )
        mean_violations = round(
            sum(item.get("violation_count", 0) for item in tier_aggregates) / len(tier_aggregates), 1
        )
        efficiency_values = [
            item["step_efficiency"] for item in tier_aggregates if item.get("step_efficiency") is not None
        ]
        mean_efficiency = f"{sum(efficiency_values) / len(efficiency_values):.3f}" if efficiency_values else "N/A"
        print(
            f"{mode_labels.get(mode, mode):<20} {mean_pwrs:<12} {mean_cap_pwrs:<15} "
            f"{mean_violations:<12} {mean_efficiency:<14}"
        )
    print("=" * 70)


def run_benchmark(
    modes: list[str],
    tiers: list[int],
    num_runs: int,
    api_key: str | None,
    model: str = "claude-sonnet-4-5",
    provider: str = "anthropic",
) -> dict[str, dict[int, dict]]:
    """Run the full benchmark suite."""
    all_results: dict[str, dict[int, dict]] = {}

    for mode in modes:
        print(f"\n{'#' * 60}")
        print(f"  MODE: {mode.upper()}")
        print(f"{'#' * 60}")

        all_results.setdefault(mode, {})

        for tier in tiers:
            scenario_files = get_scenario_files(tier)
            if not scenario_files:
                print(f"  WARNING: No scenario files found for tier {tier}")
                continue

            print(f"\n--- Tier {tier} ({len(scenario_files)} scenarios × {num_runs} runs) ---")
            tier_run_results: list[dict] = []

            for scenario_path in scenario_files:
                for run_idx in range(num_runs):
                    print(f"\n  [Scenario: {os.path.basename(scenario_path)}, Run {run_idx + 1}/{num_runs}]")
                    try:
                        result = run_scenario(scenario_path, mode, api_key, model, provider)
                        tier_run_results.append(result)
                        print(
                            f"    PWRS={result['pwrs']:.3f} | Cap-PWRS={result['cap_pwrs']:.3f} | "
                            f"Violations={result['violation_count']} | "
                            f"StepEff={result.get('step_efficiency')}"
                        )
                    except Exception as exc:
                        print(f"  ERROR running {scenario_path} in mode {mode}: {exc}")
                        tier_run_results.append(
                            {
                                "pwrs": 0.0,
                                "cap_pwrs": 0.0,
                                "resolution_rate": 0.0,
                                "deadline_adherence": 0.0,
                                "violation_count": 0,
                                "step_efficiency": None,
                            }
                        )

            all_results[mode][tier] = aggregate_tier_results(tier_run_results)
            aggregate = all_results[mode][tier]
            print(
                f"\n  Tier {tier} aggregate: "
                f"PWRS={aggregate.get('pwrs'):.3f}, Cap-PWRS={aggregate.get('cap_pwrs'):.3f}, "
                f"Violations={aggregate.get('violation_count'):.1f}"
            )

    return all_results

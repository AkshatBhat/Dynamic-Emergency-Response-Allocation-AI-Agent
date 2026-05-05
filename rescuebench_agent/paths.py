from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
BENCHMARK_BASE = PROJECT_ROOT / "benchmark"

TIER_DIRS = {
    1: "tier1_basic_triage",
    2: "tier2_constraint_satisfaction",
    3: "tier3_ethical_prioritization",
    4: "tier4_dynamic_replanning",
}


def get_scenario_files(tier: int) -> list[str]:
    """Return sorted JSON scenario paths for a benchmark tier."""
    tier_dir = BENCHMARK_BASE / TIER_DIRS[tier]
    return sorted(str(path) for path in tier_dir.glob("*.json"))

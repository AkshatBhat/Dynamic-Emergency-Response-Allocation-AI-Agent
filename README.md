# Dynamic Emergency Response Allocation AI Agent

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```
2. Activate it:
   ```bash
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Run the Visualizer

Default run (uses `benchmarks/base_city_world.json`):
```bash
python3 visualize_city.py
```

Run with a specific JSON file using a command line argument:
```bash
python3 visualize_city.py benchmarks/tier1_basic_triage/scenario1_tier1.json
```

More examples:
```bash
python3 visualize_city.py benchmarks/tier1_basic_triage/scenario3_tier1.json
python3 visualize_city.py benchmarks/tier1_basic_triage/scenario5_tier1.json
```

## Benchmark Tasks/Scenarios

In this README, **Level** and **Tier** are used synonymously, and **Task** and **Scenario** are used synonymously.

### Tier 1 (Level 1): Basic Triage

Tier 1 focuses on **direct resource-to-incident matching** with simple dispatch logic and limited coordination complexity.

Scenarios/Tasks in `benchmarks/tier1_basic_triage`:

- **Scenario/Task 1** (`scenario1_tier1.json`): Introductory mixed incidents requiring straightforward single-unit dispatch decisions; tests baseline triage and routing.
- **Scenario/Task 2** (`scenario2_tier1.json`): Adds tighter timing/placement pressure across incidents; tests prioritization under moderate urgency.
- **Scenario/Task 3** (`scenario3_tier1.json`): Increases concurrent demand and distribution; tests allocation across separated incident locations.
- **Scenario/Task 4** (`scenario4_tier1.json`): Fire-heavy workload plus a traffic-control event; tests handling simultaneous mitigation tasks with limited fleet composition.
- **Scenario/Task 5** (`scenario5_tier1.json`): High-severity, tight-deadline, capability-specific events; tests precise capability matching and fast prioritization.

## Files

- `benchmarks/base_city_world.json`: full baseline city world.
- `benchmarks/tier1_basic_triage/scenario1_tier1.json`: Tier 1 basic triage Scenario 1.
- `benchmarks/tier1_basic_triage/scenario2_tier1.json`: Tier 1 basic triage Scenario 2.
- `benchmarks/tier1_basic_triage/scenario3_tier1.json`: Tier 1 basic triage Scenario 3.
- `benchmarks/tier1_basic_triage/scenario4_tier1.json`: Tier 1 basic triage Scenario 4.
- `benchmarks/tier1_basic_triage/scenario5_tier1.json`: Tier 1 basic triage Scenario 5.
- `visualize_city.py`: graph visualization script.
- `RescueBench Base City Schema_ Conceptual Design Document.pdf`: schema/design reference.
- `RescueBench JSON Data Dictionary.pdf`: field-level JSON dictionary/reference.

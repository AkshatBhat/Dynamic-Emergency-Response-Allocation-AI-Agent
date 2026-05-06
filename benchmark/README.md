# RescueBench Benchmark

This folder contains the final RescueBench benchmark materials needed to
evaluate an external emergency-response agent.

## Contents

- [`TASK_SPECIFICATIONS.md`](./TASK_SPECIFICATIONS.md): task-by-task summary of
  all 20 benchmark scenarios
- tier scenario folders:
  - [`tier1_basic_triage/`](./tier1_basic_triage)
  - [`tier2_constraint_satisfaction/`](./tier2_constraint_satisfaction)
  - [`tier3_ethical_prioritization/`](./tier3_ethical_prioritization)
  - [`tier4_dynamic_replanning/`](./tier4_dynamic_replanning)
- [`base_city_world.json`](./base_city_world.json): shared base city topology
- [`visualize_city.py`](./visualize_city.py): graph visualizer
- schema references:
  - [`RescueBench Base City Schema_ Conceptual Design Document.pdf`](./RescueBench%20Base%20City%20Schema_%20Conceptual%20Design%20Document.pdf)
  - [`RescueBench JSON Data Dictionary.pdf`](./RescueBench%20JSON%20Data%20Dictionary.pdf)

## Benchmark Design

RescueBench is organized into four tiers with five scenarios per tier:

1. Tier 1: basic triage and straightforward dispatch
2. Tier 2: constraint satisfaction under capacity/capability limits
3. Tier 3: ethical prioritization and high-stakes ordering choices
4. Tier 4: dynamic replanning under disruptions and trigger events

Total scenarios: **20**

## Inputs

Each scenario JSON provides:

- node and edge graph structure
- vehicle classes and active fleet state
- incidents with locations, deadlines, severity, capabilities, and capacity
- optional dynamic triggers that modify the world mid-execution

## Expected Agent Output

An evaluated agent is expected to issue dispatch decisions over time:

- choose a `vehicle_id`
- choose an `incident_id`
- optionally choose a `hospital_node` for transport missions
- react to dynamic updates until incidents are resolved or no useful action remains

## Evaluation Protocol

The modular evaluation harness for this benchmark lives in
[`../rescuebench_agent/`](../rescuebench_agent).

Typical usage:

```bash
python3 -m rescuebench_agent --mode deterministic --tier all --runs 1
python3 -m rescuebench_agent --mode agentkit --tier all --runs 1
```

## Success Criteria and Metrics

The harness reports:

- `pwrs`
- `cap_pwrs`
- `resolution_rate`
- `deadline_adherence`
- `violation_count`
- `step_efficiency`

Interpretation:

- higher `pwrs`, `cap_pwrs`, `resolution_rate`, and `deadline_adherence` are better
- lower `violation_count` is better
- `step_efficiency` summarizes how efficiently the agent reached its outcomes

## Reproducibility

To reproduce benchmark evaluation:

1. install dependencies from the repo root with `pip install -r requirements.txt`
2. run the benchmark via `python3 -m rescuebench_agent ...`
3. inspect `rescuebench_agent/benchmark_results.json`

For a scenario-level summary and task specifications, use
[`TASK_SPECIFICATIONS.md`](./TASK_SPECIFICATIONS.md).

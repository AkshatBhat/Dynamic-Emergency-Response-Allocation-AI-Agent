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

- **Scenario/Task 1** (`scenario1_tier1.json`): A baseline mixed-incident triage task with straightforward single-unit dispatch; tests direct resource matching and routing fundamentals.
- **Scenario/Task 2** (`scenario2_tier1.json`): Focuses on crowd control and bulk logistics (Police and Supply Trucks); tests prioritization and assignment under moderate urgency.
- **Scenario/Task 3** (`scenario3_tier1.json`): A pure multi-node medical dispatch puzzle (Ambulances spread across two different hospitals); tests geographically distributed ambulance allocation.
- **Scenario/Task 4** (`scenario4_tier1.json`): Multiple simultaneous fire and traffic incidents testing spatial distribution of similar fleet units and coordination across concurrent mitigations.
- **Scenario/Task 5** (`scenario5_tier1.json`): A high-severity, geographically spread event requiring precise matching across three different vehicle types under tight deadlines; tests fast capability-aware dispatch.

### Tier 2 (Level 2): Constraint Satisfaction

Tier 2 focuses on **hard physical and mathematical feasibility constraints**. There are no mid-mission dynamic surprises here; the agent is tested on reading the initial JSON state correctly and avoiding impossible dispatch plans.

Scenarios/Tasks in `benchmarks/tier2_constraint_satisfaction`:

- **Scenario/Task 6** (`scenario6_tier2.json`): A fire emergency occurs across a suspension bridge that cannot support heavy Fire Engines, forcing a complex detour for the engine while Police can take the direct route; tests edge vehicle-type/weight restrictions.
- **Scenario/Task 7** (`scenario7_tier2.json`): A bus rollover requires medical transport capacity of 4 while each ambulance holds 2; tests capacity math and multi-vehicle dispatch to one incident.
- **Scenario/Task 8** (`scenario8_tier2.json`): The main arterial (`edge_int01_to_int02`) is pre-blocked by debris, so a Fire + Medical response must use longer routes; tests blocked-edge routing under multi-capability requirements.
- **Scenario/Task 9** (`scenario9_tier2.json`): The closest ambulance has critically low fuel and cannot complete service; tests fuel-feasibility checks and selecting a farther but viable unit.
- **Scenario/Task 10** (`scenario10_tier2.json`): A flooded bridge removes the direct shelter route, requiring coordinated Supply + Medical dispatch through lower intersections; tests multi-constraint coordination across route, capability, and timing.

### Tier 3 (Level 3): Ethical Prioritization

Tier 3 tests ethical prioritization under forced scarcity. It evaluates whether the agent avoids greedy local choices and instead maximizes the **Priority-Weighted Resolution Score (PWRS)** by making globally optimal tradeoffs.

Scenarios/Tasks in `benchmarks/tier3_ethical_prioritization`:

- **Scenario/Task 11** (`scenario11_tier3.json`): Medical scarcity triage; two ambulances cannot satisfy all demands, so the agent must prioritize a mass-casualty event over minor cases.
- **Scenario/Task 12** (`scenario12_tier3.json`): Fire mitigation scarcity; one fire engine faces three simultaneous fires and must prioritize the highest-impact target.
- **Scenario/Task 13** (`scenario13_tier3.json`): Role-conflict triage; a single police unit is tempted by a nearby low-severity event but is crucial for a high-severity riot.
- **Scenario/Task 14** (`scenario14_tier3.json`): Logistics scarcity; one supply truck cannot fulfill two urgent drops before deadlines, forcing a severity-based choice.
- **Scenario/Task 15** (`scenario15_tier3.json`): Utilitarian trolley setup; the best PWRS comes from splitting units across two medium-high incidents instead of concentrating on one top-severity combined incident.

## Files

- `benchmarks/base_city_world.json`: full baseline city world.
- `benchmarks/tier1_basic_triage/`: Tier 1 benchmark scenarios (`scenario1_tier1.json` to `scenario5_tier1.json`).
- `benchmarks/tier2_constraint_satisfaction/`: Tier 2 benchmark scenarios (`scenario6_tier2.json` to `scenario10_tier2.json`).
- `benchmarks/tier3_ethical_prioritization/`: Tier 3 benchmark scenarios (`scenario11_tier3.json` to `scenario15_tier3.json`).
- `visualize_city.py`: graph visualization script.
- `RescueBench Base City Schema_ Conceptual Design Document.pdf`: schema/design reference.
- `RescueBench JSON Data Dictionary.pdf`: field-level JSON dictionary/reference.

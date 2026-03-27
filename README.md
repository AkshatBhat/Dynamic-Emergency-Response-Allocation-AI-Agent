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

## Files

- `benchmarks/base_city_world.json`: full baseline city world.
- `benchmarks/tier1_basic_triage/scenario1_tier1.json`: Tier 1 basic triage Scenario 1.
- `benchmarks/tier1_basic_triage/scenario2_tier1.json`: Tier 1 basic triage Scenario 2.
- `benchmarks/tier1_basic_triage/scenario3_tier1.json`: Tier 1 basic triage Scenario 3.
- `benchmarks/tier1_basic_triage/scenario4_tier1.json`: Tier 1 basic triage Scenario 4.
- `benchmarks/tier1_basic_triage/scenario5_tier1.json`: Tier 1 basic triage Scenario 5.
- `benchmarks/tier2_constraint_satisfaction/scenario6_tier2.json`: Tier 2 constraint satisfaction Scenario 6.
- `benchmarks/tier2_constraint_satisfaction/scenario7_tier2.json`: Tier 2 constraint satisfaction Scenario 7.
- `benchmarks/tier2_constraint_satisfaction/scenario8_tier2.json`: Tier 2 constraint satisfaction Scenario 8.
- `benchmarks/tier2_constraint_satisfaction/scenario9_tier2.json`: Tier 2 constraint satisfaction Scenario 9.
- `benchmarks/tier2_constraint_satisfaction/scenario10_tier2.json`: Tier 2 constraint satisfaction Scenario 10.
- `visualize_city.py`: graph visualization script.
- `RescueBench Base City Schema_ Conceptual Design Document.pdf`: schema/design reference.
- `RescueBench JSON Data Dictionary.pdf`: field-level JSON dictionary/reference.
